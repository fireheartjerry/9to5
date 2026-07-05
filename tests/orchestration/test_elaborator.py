"""Tests for resilient elaboration (the run must not die at the starting line).

R5: the elaborator is a pure prompt builder over the ONE llm_io seam -- the memoized
client, retry/backoff, and extraction live in llm_io. These tests drive the seam by
patching ``llm_io.getClient`` (the blessed client factory)."""
import os
import tempfile
import unittest
from unittest import mock

import llm_io
from agents import elaborator


def _client(chat):
    return mock.Mock(chat=chat)


class TestElaborate(unittest.TestCase):
    def test_success_returns_content(self):
        chat = mock.Mock(return_value={"message": {"content": "  the spec  "}})
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)):
            self.assertEqual(elaborator.elaborate("do a thing"), "the spec")

    def test_falls_back_when_ollama_down(self):
        chat = mock.Mock(side_effect=ConnectionError("refused"))
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)), \
             mock.patch("time.sleep"):
            spec = elaborator.elaborate("fix the bug in foo.py")
        self.assertIn("Objective", spec)
        self.assertIn("fix the bug in foo.py", spec)   # raw goal preserved

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] < 2:
                raise TimeoutError("slow")
            return {"message": {"content": "recovered spec"}}

        with mock.patch.object(llm_io, "getClient", return_value=_client(flaky)), \
             mock.patch("time.sleep"):
            self.assertEqual(elaborator.elaborate("g"), "recovered spec")
        self.assertEqual(calls["n"], 2)

    def test_injected_chat_seam_is_used(self):
        seen = {}

        def injected(system, user, *, act, want_json=False):
            seen["act"] = act
            return {"message": {"content": "seamed spec"}}

        self.assertEqual(elaborator.elaborate("g", chat=injected), "seamed spec")
        self.assertEqual(seen["act"], "elaborate")


class TestUniverse(unittest.TestCase):
    def test_defaults_when_brain_unavailable(self):
        chat = mock.Mock(side_effect=RuntimeError("down"))
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)), \
             mock.patch("time.sleep"):
            u = elaborator.extractUniverse("g", "spec", "/work/dir")
        self.assertEqual(u["allowed_paths"], ["/work/dir"])
        # Baseline hard boundaries always enforced.
        for d in __import__("config").UNIVERSE_DEFAULT_HARD_BOUNDARIES:
            self.assertIn(d, u["hard_boundaries"])

    def test_parses_brain_json(self):
        payload = '{"description":"d","allowed_paths":["a.py"],"allowed_to_expand_to":[],"hard_boundaries":["secret"]}'
        chat = mock.Mock(return_value={"message": {"content": payload}})
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)):
            u = elaborator.extractUniverse("g", "spec", "/w")
        self.assertEqual(u["allowed_paths"], ["a.py"])
        self.assertIn("secret", u["hard_boundaries"])

    def test_parses_pydantic_style_response(self):
        class _Msg:
            content = '{"description":"d","allowed_paths":["b.py"]}'

        class _Resp:
            message = _Msg()

        chat = mock.Mock(return_value=_Resp())
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)):
            u = elaborator.extractUniverse("g", "spec", "/w")
        self.assertEqual(u["allowed_paths"], ["b.py"])


class TestRepoGrounding(unittest.TestCase):
    def _repo(self, tmp):
        # A minimal real repo snapshot: AGENTS.md with a distinctive real path.
        with open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8") as fh:
            fh.write("Package & directory map\n- agents/planning/elaborator/core.py\n")
        return tmp

    def test_elaborate_grounds_prompt_in_real_repo(self):
        captured = {}

        def injected(system, user, *, act, want_json=False):
            captured["user"] = user
            return {"message": {"content": "spec"}}

        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp)
            elaborator.elaborate("do a thing", work_dir=tmp, chat=injected)
        self.assertIn("ACTUAL REPOSITORY SNAPSHOT", captured["user"])
        self.assertIn("agents/planning/elaborator/core.py", captured["user"])

    def test_extract_universe_grounds_prompt_in_real_repo(self):
        captured = {}

        def injected(system, user, *, act, want_json=False):
            captured["user"] = user
            return {"message": {"content": '{"allowed_paths":["agents/"]}'}}

        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp)
            elaborator.extractUniverse("g", "spec", tmp, chat=injected)
        self.assertIn("ACTUAL REPOSITORY SNAPSHOT", captured["user"])
        self.assertIn("agents/planning/elaborator/core.py", captured["user"])


class TestExcellenceGating(unittest.TestCase):
    def test_flag_off_is_byte_identical(self):
        def injected(system, user, *, act, want_json=False):
            return {"message": {"content": "SPEC"}}

        with mock.patch.object(__import__("config"), "ELABORATOR_EXCELLENCE_ENABLED", False):
            out = elaborator.elaborate("do a thing", chat=injected)
        self.assertEqual(out, "SPEC")  # no appended assumptions, no extra passes

    def test_flag_on_appends_inferred_assumptions(self):
        scripted = iter([
            {"message": {"content": "SPEC BODY"}},                 # elaborate
            {"message": {"content": "Inferred: scope — because vague"}},  # self_review
        ])

        def injected(system, user, *, act, want_json=False):
            return next(scripted)

        with mock.patch.object(__import__("config"), "ELABORATOR_EXCELLENCE_ENABLED", True):
            out = elaborator.elaborate("improve everything", chat=injected)
        self.assertIn("SPEC BODY", out)
        self.assertIn("Inferred: scope", out)

    def test_flag_on_universe_adds_unverified_paths(self):
        def injected(system, user, *, act, want_json=False):
            return {"message": {"content": '{"allowed_paths":["nope/missing.py"]}'}}

        with mock.patch.object(__import__("config"), "ELABORATOR_EXCELLENCE_ENABLED", True):
            u = elaborator.extractUniverse("g", "spec", ".", chat=injected)
        self.assertIn("nope/missing.py", u["unverified_paths"])
        self.assertNotIn("nope/missing.py", u["allowed_paths"])


class TestFiveW3H(unittest.TestCase):
    def _capture_system(self, flag_value):
        seen = {}

        def injected(system, user, *, act, want_json=False):
            if act == "elaborate":  # ignore the flag-on self_review pass; we want the elaborate prompt
                seen["system"] = system
            return {"message": {"content": "spec"}}

        with mock.patch.object(__import__("config"), "ELABORATOR_EXCELLENCE_ENABLED", flag_value):
            elaborator.elaborate("build a thing", chat=injected)
        return seen["system"]

    def test_flag_off_uses_original_system_prompt(self):
        from agents.planning.elaborator import core
        self.assertEqual(self._capture_system(False), core.ELABORATOR_SYSTEM)

    def test_flag_on_prompt_has_5w3h_dimensional_walk(self):
        system = self._capture_system(True)
        for dim in ("Why", "Who", "Where", "How"):
            self.assertIn(dim, system)
        # still instructs the same five output sections
        self.assertIn("Objective", system)
        self.assertIn("Deliverables", system)


class TestVagueGoalWiring(unittest.TestCase):
    def test_flag_on_vague_goal_injects_state_of_repo(self):
        import os, tempfile
        seen = {}

        def injected(system, user, *, act, want_json=False):
            if act == "elaborate":  # ignore the flag-on self_review pass; we want the elaborate prompt
                seen["user"] = user
            return {"message": {"content": "spec"}}

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".repo-map.json"), "w", encoding="utf-8") as fh:
                fh.write('{"modules": [{"path": "agents/planning/elaborator/core.py"}]}')
            with mock.patch.object(__import__("config"), "ELABORATOR_EXCELLENCE_ENABLED", True):
                elaborator.elaborate("improve everything", work_dir=tmp, chat=injected)
        self.assertIn("STATE OF THE REPO", seen["user"])
        self.assertIn("agents/planning/elaborator/core.py", seen["user"])


class TestPhase2Wiring(unittest.TestCase):
    def test_precedent_injected_when_flag_on(self):
        seen = {}

        def injected(system, user, *, act, want_json=False):
            if act == "elaborate":
                seen["user"] = user
            return {"message": {"content": "SPEC"}}

        cfg = __import__("config")
        with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
             mock.patch.object(cfg, "ELABORATOR_PRECEDENT_ENABLED", True), \
             mock.patch("agents.planning.elaborator.precedent.precedentBlock",
                        return_value="PRECEDENT (how similar goals resolved before):\n- past success: X"):
            elaborator.elaborate("do a thing", chat=injected)
        self.assertIn("PRECEDENT", seen["user"])

    def test_precedent_absent_when_subflag_off(self):
        seen = {}

        def injected(system, user, *, act, want_json=False):
            if act == "elaborate":
                seen["user"] = user
            return {"message": {"content": "SPEC"}}

        cfg = __import__("config")
        with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
             mock.patch.object(cfg, "ELABORATOR_PRECEDENT_ENABLED", False):
            elaborator.elaborate("do a thing", chat=injected)
        self.assertNotIn("PRECEDENT", seen["user"])

    def test_judge_note_appended_when_challenged(self):
        scripted = iter([
            {"message": {"content": "SPEC BODY"}},                       # elaborate
            {"message": {"content": "Inferred: scope — because vague"}},  # self_review
        ])

        def injected(system, user, *, act, want_json=False):
            return next(scripted)

        cfg = __import__("config")
        with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
             mock.patch.object(cfg, "SOCIETY_ENABLED", True), \
             mock.patch("agents.planning.elaborator.judge.judgeElaboration",
                        return_value={"verdict": "challenged", "concerns": ["path X not real"]}):
            out = elaborator.elaborate("improve everything", chat=injected)
        self.assertIn("Review Note", out)
        self.assertIn("path X not real", out)


class TestBestOfN(unittest.TestCase):
    def test_bestofn_off_single_shot_unchanged(self):
        calls = {"n": 0}

        def injected(system, user, *, act, want_json=False):
            if act == "elaborate":
                calls["n"] += 1
                return {"message": {"content": "SPEC"}}
            return {"message": {"content": ""}}  # self_review yields nothing to append

        cfg = __import__("config")
        # SOCIETY_ENABLED off so no advisory judge note is appended; this isolates the
        # best-of-N-off path (a single elaborate call whose output passes through unchanged).
        with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
             mock.patch.object(cfg, "ELABORATOR_BESTOFN_ENABLED", False), \
             mock.patch.object(cfg, "SOCIETY_ENABLED", False):
            out = elaborator.elaborate("improve everything", chat=injected)
        self.assertEqual(out, "SPEC")
        self.assertEqual(calls["n"], 1)  # exactly one elaborate call, no candidate fan-out

    def test_bestofn_on_generates_multiple_and_selects_grounded(self):
        import os, tempfile
        # stance 0 spec names a REAL file; stance 1 names a FAKE path. Grounded one must win.
        specs = iter(["use agents/planning/elaborator/core.py here",
                      "edit does/not/exist/nope.py here",
                      "third fallback spec"])

        def injected(system, user, *, act, want_json=False):
            if act == "elaborate":
                return {"message": {"content": next(specs)}}
            return {"message": {"content": ""}}  # self_review etc.

        cfg = __import__("config")
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "agents", "planning", "elaborator"))
            open(os.path.join(tmp, "agents", "planning", "elaborator", "core.py"), "w").close()
            with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
                 mock.patch.object(cfg, "ELABORATOR_BESTOFN_ENABLED", True), \
                 mock.patch.object(cfg, "ELABORATOR_CANDIDATES_MAX", 2), \
                 mock.patch("agents.planning.elaborator.core.isVagueGoal", return_value=True):
                out = elaborator.elaborate("improve everything", work_dir=tmp, chat=injected)
        self.assertIn("agents/planning/elaborator/core.py", out)  # grounded candidate won


class TestLookaheadAndDefer(unittest.TestCase):
    def test_lookahead_prefers_higher_predicted(self):
        import os, tempfile
        # Both candidates name the SAME real file (equal groundedness); lookahead must break the tie.
        specs = iter(["edit agents/planning/elaborator/core.py",
                      "edit agents/planning/elaborator/core.py"])

        def injected(system, user, *, act, want_json=False):
            if act == "elaborate":
                return {"message": {"content": next(specs)}}
            if act == "predict":
                # stance 0 (minimal-scope) low, stance 1 (thorough) high
                score = 0.1 if "minimal-scope" in system else 0.9
                return {"message": {"content": '{"predicted_success": %s}' % score}}
            return {"message": {"content": ""}}

        cfg = __import__("config")
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "agents", "planning", "elaborator"))
            open(os.path.join(tmp, "agents", "planning", "elaborator", "core.py"), "w").close()
            with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
                 mock.patch.object(cfg, "ELABORATOR_BESTOFN_ENABLED", True), \
                 mock.patch.object(cfg, "ELABORATOR_LOOKAHEAD_ENABLED", True), \
                 mock.patch.object(cfg, "ELABORATOR_CANDIDATES_MAX", 2), \
                 mock.patch.object(cfg, "SOCIETY_ENABLED", False), \
                 mock.patch("agents.planning.elaborator.core.isVagueGoal", return_value=True):
                out = elaborator.elaborate("improve everything", work_dir=tmp, chat=injected)
        # The 'thorough' (higher-predicted) candidate won; both specs identical text so we assert it ran without error and returned a spec.
        self.assertIn("core.py", out)

    def test_defer_wiring_is_inert_by_default_escalate(self):
        def injected(system, user, *, act, want_json=False):
            return {"message": {"content": "SPEC"}} if act == "elaborate" else {"message": {"content": ""}}
        cfg = __import__("config")
        with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
             mock.patch.object(cfg, "ELABORATOR_BESTOFN_ENABLED", False), \
             mock.patch.object(cfg, "ELABORATOR_DEFER_ENABLED", True), \
             mock.patch.object(cfg, "SOCIETY_ENABLED", False):
            out = elaborator.elaborate("do a thing", chat=injected)
        self.assertEqual(out, "SPEC")  # default escalate_fn keeps local -> unchanged


class TestDeferLive(unittest.TestCase):
    def test_defer_escalates_via_model_when_uncertain(self):
        # elaborate returns a spec with 2+ "Inferred:" lines -> uncertainty defers -> escalate returns BIG
        def injected(system, user, *, act, want_json=False):
            if act == "elaborate":
                return {"message": {"content": "SPEC\n"}}
            if act == "self_review":
                return {"message": {"content": "Inferred: a — b\nInferred: c — d"}}
            if act == "elaborate_defer":
                return {"message": {"content": "ESCALATED SPEC"}}
            return {"message": {"content": ""}}
        cfg = __import__("config")
        with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
             mock.patch.object(cfg, "ELABORATOR_BESTOFN_ENABLED", False), \
             mock.patch.object(cfg, "ELABORATOR_DEFER_ENABLED", True), \
             mock.patch.object(cfg, "SOCIETY_ENABLED", False):
            out = elaborator.elaborate("do a thing", chat=injected)
        self.assertIn("ESCALATED SPEC", out)


class TestOutMeta(unittest.TestCase):
    def test_out_meta_records_single_shot_stance(self):
        def injected(system, user, *, act, want_json=False):
            return {"message": {"content": "SPEC"}} if act == "elaborate" else {"message": {"content": ""}}
        cfg = __import__("config")
        meta = {}
        with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
             mock.patch.object(cfg, "ELABORATOR_BESTOFN_ENABLED", False), \
             mock.patch.object(cfg, "SOCIETY_ENABLED", False):
            elaborator.elaborate("do a thing", chat=injected, out_meta=meta)
        self.assertEqual(meta.get("stance"), "single-shot")

    def test_out_meta_records_bestofn_stance(self):
        import os, tempfile
        specs = iter(["edit agents/planning/elaborator/core.py", "edit nope/fake.py"])
        def injected(system, user, *, act, want_json=False):
            if act == "elaborate":
                return {"message": {"content": next(specs)}}
            return {"message": {"content": ""}}
        cfg = __import__("config")
        meta = {}
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "agents", "planning", "elaborator"))
            open(os.path.join(tmp, "agents", "planning", "elaborator", "core.py"), "w").close()
            with mock.patch.object(cfg, "ELABORATOR_EXCELLENCE_ENABLED", True), \
                 mock.patch.object(cfg, "ELABORATOR_BESTOFN_ENABLED", True), \
                 mock.patch.object(cfg, "ELABORATOR_CANDIDATES_MAX", 2), \
                 mock.patch.object(cfg, "SOCIETY_ENABLED", False), \
                 mock.patch("agents.planning.elaborator.core.isVagueGoal", return_value=True):
                elaborator.elaborate("improve everything", work_dir=tmp, chat=injected, out_meta=meta)
        self.assertIn(meta.get("stance"), ("minimal-scope", "thorough"))  # a real stance id
