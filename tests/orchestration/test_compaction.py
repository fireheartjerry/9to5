"""Compaction trigger math + MUST-PRESERVE contract presence."""
import config
from platform_core.orchestration import compaction


def test_should_compact_false_for_small_payload():
    assert compaction.shouldCompact("sys", "tiny user", num_ctx=8192, headroom=2048) is False


def test_should_compact_true_when_over_window_budget():
    big = "x" * (8192 * 4)      # ~8192 tokens of user alone, well past the trigger
    assert compaction.shouldCompact("sys", big, num_ctx=8192, headroom=2048) is True


def test_should_compact_is_window_aware():
    mid = "x" * (4096 * 4)
    # Same payload trips the trigger at a small window but not a large one.
    assert compaction.shouldCompact("s", mid, num_ctx=4096, headroom=512) is True
    assert compaction.shouldCompact("s", mid, num_ctx=32768, headroom=512) is False


def test_must_preserve_contract_lists_identifiers():
    c = compaction.MUST_PRESERVE_CONTRACT.lower()
    for token in ("file path", "function", "error", "goal", "todo"):
        assert token in c


import re
from pathlib import Path



def _identifier_summary(text):
    # A stub summarizer that preserves identifiers (paths, fn names) like the real contract.
    ids = re.findall(r"[\w/\\.]+\.py|\w+\(\)|Error\w*", text)
    return "SUMMARY keeps: " + " ".join(sorted(set(ids)))


def test_compact_payload_preserves_identifiers_and_offloads(tmp_path):
    raw_old = ("Earlier: edited memory/retrieval.py and called retrieve_content() ; hit "
               "TimeoutError once. " * 400)
    newest = "NEWEST: now finalize the patch in platform_core/orchestration/compaction.py"
    user = raw_old + newest
    out = compaction.compactPayload("sys", user, num_ctx=8192, headroom=2048,
                                    summarize=_identifier_summary, offload_dir=str(tmp_path))
    assert "memory/retrieval.py" in out                 # MUST-PRESERVE identifier survived
    assert "retrieve_content()" in out
    assert newest in out                                 # newest reserve-half kept verbatim
    assert "[raw context offloaded to" in out
    files = list(Path(tmp_path).glob("ctx-*.txt"))
    assert files and "TimeoutError" in files[0].read_text(encoding="utf-8")


def test_compact_payload_drops_to_truncation_when_summarize_raises(tmp_path):
    user = "x" * (8192 * 4)
    def boom(_): raise RuntimeError("summarizer down")
    out = compaction.compactPayload("sys", user, num_ctx=8192, headroom=2048,
                                    summarize=boom, offload_dir=str(tmp_path))
    assert "context trimmed to fit the model window" in out   # brain_io._fitUserToCtx marker


def test_compact_payload_drops_to_truncation_when_summary_empty(tmp_path):
    user = "x" * (8192 * 4)
    out = compaction.compactPayload("sys", user, num_ctx=8192, headroom=2048,
                                    summarize=lambda _: "", offload_dir=str(tmp_path))
    assert "context trimmed to fit the model window" in out


def test_fit_or_compact_is_noop_passthrough_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "COMPACTION_ENABLED", False, raising=False)
    out = compaction.fitOrCompact("sys", "small", num_ctx=8192, headroom=2048,
                                  summarize=lambda _: "S")
    assert out == "small"


def test_fit_or_compact_uses_truncation_when_no_summarizer(monkeypatch):
    monkeypatch.setattr(config, "COMPACTION_ENABLED", True, raising=False)
    big = "x" * (8192 * 4)
    out = compaction.fitOrCompact("sys", big, num_ctx=8192, headroom=2048, summarize=None)
    assert "context trimmed to fit the model window" in out
