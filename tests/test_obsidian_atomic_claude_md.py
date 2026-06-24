"""writeClaudioMd must write CLAUDE.md as a complete-file swap: parallel subtasks share one
work_dir/CLAUDE.md and the executor's `claude` auto-reads it right after, so a concurrent reader
must never observe a half-written (torn) file."""
import tempfile
import threading
import unittest
from pathlib import Path

from memory import obsidian


class TestAtomicClaudeMd(unittest.TestCase):
    def test_concurrent_writes_are_never_torn(self):
        d = Path(tempfile.mkdtemp())
        target = d / "CLAUDE.md"
        HEAD, FOOT = "HEADER-START", "FOOTER-END"
        body = "x" * 20000   # large enough that a non-atomic write would be observably torn
        torn: list[str] = []
        stop = threading.Event()

        def writer(i: int) -> None:
            for _ in range(40):
                obsidian._atomicWriteText(target, f"{HEAD}\n{body}\n{FOOT}-{i}")

        def reader() -> None:
            while not stop.is_set():
                try:
                    t = target.read_text(encoding="utf-8")
                except (FileNotFoundError, PermissionError):
                    continue
                if t and not (t.startswith(HEAD) and t.rstrip().endswith(tuple(f"{FOOT}-{i}" for i in range(6)))):
                    torn.append(t[:40] + "..." + t[-20:])

        writers = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
        readers = [threading.Thread(target=reader) for _ in range(4)]
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


if __name__ == "__main__":
    unittest.main()
