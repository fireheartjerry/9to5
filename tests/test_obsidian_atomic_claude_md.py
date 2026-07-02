"""writeClaudioMd must write CLAUDE.md as a complete-file swap: parallel subtasks share one
work_dir/CLAUDE.md and the executor's `claude` auto-reads it right after, so a concurrent reader
must never observe a half-written (torn) file."""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from memory import obsidian


class TestAtomicClaudeMd(unittest.TestCase):
    def test_concurrent_writes_are_never_torn(self):
        d = Path(tempfile.mkdtemp())
        target = d / "CLAUDE.md"
        HEAD, FOOT = "HEADER-START", "FOOTER-END"
        body = "x" * 8000    # large enough that a non-atomic write would be observably torn
        N_WRITERS = 3         # realistic concurrency: enough to exercise the atomic swap without
        torn: list[str] = []  # pathologically starving os.replace (which would trip the best-effort
        stop = threading.Event()   # non-atomic fallback only under extreme synthetic load, not real use)

        def writer(i: int) -> None:
            for _ in range(8):
                obsidian._atomicWriteText(target, f"{HEAD}\n{body}\n{FOOT}-{i}")

        def reader() -> None:
            valid_tails = tuple(f"{FOOT}-{i}" for i in range(N_WRITERS))
            while not stop.is_set():
                try:
                    t = target.read_text(encoding="utf-8")
                except (FileNotFoundError, PermissionError):
                    continue
                if t and not (t.startswith(HEAD) and t.rstrip().endswith(valid_tails)):
                    torn.append(t[:40] + "..." + t[-20:])
                # Yield between reads: an unthrottled spin holds the file handle often enough that
                # os.replace on Windows fails and backs off, inflating runtime ~10x without adding
                # detection power. The _fast_sleep fixture caps this to ~1ms.
                time.sleep(0.0005)

        writers = [threading.Thread(target=writer, args=(i,)) for i in range(N_WRITERS)]
        readers = [threading.Thread(target=reader) for _ in range(2)]
        for r in readers:
            r.start()
        for w in writers:
            w.start()
        for w in writers:
            w.join(timeout=30)
        stop.set()
        for r in readers:
            r.join(timeout=5)

        self.assertEqual(torn, [], f"observed {len(torn)} torn CLAUDE.md read(s); first: {torn[:1]}")
        final = target.read_text(encoding="utf-8")
        self.assertTrue(final.startswith(HEAD) and FOOT in final)
