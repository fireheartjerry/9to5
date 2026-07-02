"""Unit tests for the pure Components-V2 cockpit builders + transport clamp/multipart
helpers. No network, no discord.py, no TaskState construction (a lightweight stub state)."""
import json
import unittest

from notifications import cv2
from notifications import discord_bot as discord


class _StubState:
    def __init__(self, meta, subtasks, data=None):
        self.meta = meta
        self.subtasks = subtasks
        self.data = data or {}
        self.task_id = "abcd1234efgh"


def _state(**over):
    meta = {"goal_raw": "Build the thing", "status": "executing",
            "control_mode": "watch", "started_at": None, "work_dir": "C:/9to5"}
    meta.update(over.get("meta", {}))
    subs = over.get("subtasks", [
        {"subtask_id": "st-001", "title": "first", "status": "done",
         "verify_result": {"passed": True, "cmd": "pytest"}},
        {"subtask_id": "st-002", "title": "second", "status": "in_progress", "attempts": 2},
        {"subtask_id": "st-003", "title": "third", "status": "pending"},
    ])
    data = over.get("data", {"notifications": [{"kind": "replan"}], "adversary_reviews": [{}]})
    return _StubState(meta, subs, data)


def _flatten_text(comps):
    out = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == 10:
                out.append(str(n.get("content", "")))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for it in n:
                walk(it)

    walk(comps)
    return "\n".join(out)


def _custom_ids(comps):
    ids = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("custom_id"):
                ids.append(n["custom_id"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for it in n:
                walk(it)

    walk(comps)
    return ids


def _has_type(comps, t):
    found = [False]

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == t:
                found[0] = True
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for it in n:
                walk(it)

    walk(comps)
    return found[0]


class TestBuildCockpit(unittest.TestCase):
    def test_returns_container_and_flag(self):
        comps, flags = cv2.buildCockpit(_state(), "executing")
        self.assertEqual(flags, 1 << 15)
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0]["type"], 17)            # Container
        self.assertIn("accent_color", comps[0])

    def test_goal_progress_current_present(self):
        blob = _flatten_text(cv2.buildCockpit(_state(), "executing")[0])
        self.assertIn("Build the thing", blob)
        self.assertIn("%", blob)                          # progress bar percent
        self.assertIn("st-002", blob)                     # current subtask id
        self.assertIn("attempt 2", blob)                  # attempt hint
        self.assertIn("PASS `st-001`", blob)              # last verify (icon prefix '' unprovisioned)

    def test_control_buttons_inside_container(self):
        ids = _custom_ids(cv2.buildCockpit(_state(), "executing")[0])
        for cid in ("cp_pause", "cp_resume", "cp_approve", "cp_reject", "cp_skip", "cp_abort"):
            self.assertIn(cid, ids)

    def test_image_url_adds_media_gallery(self):
        comps, _ = cv2.buildCockpit(_state(), "executing", image_url="attachment://c.png")
        self.assertTrue(_has_type(comps, 12))             # MediaGallery present

    def test_no_image_no_media_gallery(self):
        comps, _ = cv2.buildCockpit(_state(), "executing")
        self.assertFalse(_has_type(comps, 12))

    def test_within_cv2_budget(self):
        comps, _ = cv2.buildCockpit(_state(), "executing")
        self.assertLessEqual(discord._cv2Count(comps), config_max_components())
        self.assertLessEqual(discord._cv2TextLen(comps), 4000)


def config_max_components():
    import config
    return config.DISCORD_CV2_MAX_COMPONENTS


class TestClamp(unittest.TestCase):
    def test_clamp_trims_runaway(self):
        big = [cv2.text("x" * 50) for _ in range(200)]    # 200 comps, 10000 chars
        clamped = discord._clampComponents(big)
        self.assertLessEqual(discord._cv2Count(clamped), 40)
        self.assertLessEqual(discord._cv2TextLen(clamped), 4000)

    def test_clamp_keeps_head(self):
        comps = [cv2.text("HEADER")] + [cv2.text("y" * 50) for _ in range(200)]
        clamped = discord._clampComponents(comps)
        self.assertEqual(clamped[0]["content"], "HEADER")

    def test_clamp_noop_when_small(self):
        small = [cv2.text("hello"), cv2.separator()]
        self.assertEqual(discord._clampComponents(small), small)


class TestMultipart(unittest.TestCase):
    def test_multipart_parts(self):
        data, files = discord._multipartParts(
            {"flags": 1 << 15, "components": []},
            [("c.png", b"\x89PNG", "image/png")])
        self.assertIn("payload_json", data)
        self.assertIn("files[0]", files)
        body = json.loads(data["payload_json"])
        self.assertEqual(body["attachments"], [{"id": 0, "filename": "c.png"}])
        self.assertEqual(files["files[0]"][0], "c.png")
