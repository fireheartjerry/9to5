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
