"""End-to-end composition test for the elaborator excellence pipeline.

Every unit of the excellence pipeline is exercised in isolation by its own test
module (candidates, predict, self_review, precedent, judge, defer, uncertainty,
grounding). This test proves the stages actually COMPOSE inside
``elaborator.elaborate`` with the full tier of flags ON at once -- grounding ->
state-of-repo -> precedent -> 5W3H system -> best-of-N -> lookahead -> self-review
-> judge all wired together on a single real call.

Hermetic strategy: the two stages that would otherwise reach real infrastructure
(the embedding index behind ``precedent.precedentBlock`` and the adversary review
behind ``judge.judgeElaboration``) are monkeypatched to fixed returns. Everything
else -- best-of-N candidate generation, lookahead prediction, groundedness-based
selection, self-review, and prompt assembly -- runs the real ``core.py`` wiring
against an injected brain double, so this asserts the COMPOSITION, not mocks.

DEFER DECISION (option b: DEFER OFF for this composition test).
  With ``chat`` injected and DEFER on, ``core.elaborate`` runs defer LAST via
  ``escalate.escalateToModel(goal, chat=chat)``. Because ``chat is not None``
  bypasses escalate's empty-``ELABORATOR_DEFER_MODEL`` guard, escalate calls the
  brain with act="elaborate_defer" and returns a NON-EMPTY spec, which
  ``defer.maybeDefer`` then substitutes for ``out`` -- clobbering the best-of-N /
  self-review / judge output that assertions 6/7/8 verify. Defer's escalation path
  is already covered by test_elaborator_defer.py and test_elaborator_escalate.py,
  so we turn DEFER OFF here to keep the composition assertions honest. LOOKAHEAD
  stays ON: predict runs INSIDE best-of-N before ``out`` is finalized, so it
  composes cleanly with the rest.
"""
import os
import tempfile
import unittest
from unittest import mock

import config
from agents import elaborator


class TestElaboratorE2E(unittest.TestCase):
    def test_full_pipeline_composes_with_all_flags_on(self):
        prompts = []
        acts = []

        def brain(system, user, *, act, want_json=False):
            acts.append(act)
            if act == "elaborate":
                prompts.append((system, user))
                # The thorough/exhaustive stance names the REAL file so it wins on
                # groundedness; the other stances name a path that does not exist.
                if "thorough" in system or "exhaustive" in system:
                    return {"message": {"content":
                        "# Objective\ndo it\n# Deliverables\n- edit real_module.py\n"
                        "# Acceptance Criteria\n- works\n# Constraints\n- surgical\n# Assumptions\n- none\n"}}
                return {"message": {"content":
                    "# Objective\ndo it\n# Deliverables\n- edit does/not/exist.py\n"
                    "# Acceptance Criteria\n- works\n# Constraints\n- surgical\n# Assumptions\n- none\n"}}
            if act == "predict":
                return {"message": {"content":
                    '{"predicted_success": 0.7, "likely_files": ["real_module.py"], "likely_failure": "none"}'}}
            if act == "self_review":
                return {"message": {"content":
                    "Inferred: scope is module-local — because the goal is vague\n"
                    "Inferred: no new deps — because none named"}}
            return {"message": {"content": ""}}

        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "real_module.py"), "w").close()
            with open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8") as fh:
                fh.write("Package map\n- real_module.py\n")
            with open(os.path.join(tmp, ".repo-map.json"), "w", encoding="utf-8") as fh:
                fh.write('{"modules": [{"path": "real_module.py"}]}')

            meta = {}
            with mock.patch.object(config, "ELABORATOR_EXCELLENCE_ENABLED", True), \
                 mock.patch.object(config, "ELABORATOR_BESTOFN_ENABLED", True), \
                 mock.patch.object(config, "ELABORATOR_PRECEDENT_ENABLED", True), \
                 mock.patch.object(config, "ELABORATOR_LOOKAHEAD_ENABLED", True), \
                 mock.patch.object(config, "ELABORATOR_DEFER_ENABLED", False), \
                 mock.patch.object(config, "SOCIETY_ENABLED", True), \
                 mock.patch.object(config, "ELABORATOR_CANDIDATES_MAX", 3), \
                 mock.patch("agents.planning.elaborator.precedent.precedentBlock",
                            return_value="PRECEDENT (how similar goals resolved before):\n"
                                         "- past success: prior thing"), \
                 mock.patch("agents.planning.elaborator.judge.judgeElaboration",
                            return_value={"verdict": "challenged",
                                          "concerns": ["double-check scope"]}):
                out = elaborator.elaborate("improve everything", work_dir=tmp, chat=brain, out_meta=meta)

        # 1. best-of-N ran (multiple stance-varied elaborate calls composed).
        self.assertGreaterEqual(acts.count("elaborate"), 2)
        # 2. lookahead ran (predict called per candidate, inside best-of-N).
        self.assertIn("predict", acts)
        # 3. self-review ran after selection.
        self.assertIn("self_review", acts)
        # 4. grounding + state-of-repo + precedent all reached the prompt.
        joined_prompt = "\n".join(u for _, u in prompts)
        self.assertIn("ACTUAL REPOSITORY SNAPSHOT", joined_prompt)
        self.assertIn("STATE OF THE REPO", joined_prompt)
        self.assertIn("PRECEDENT", joined_prompt)
        # 5. 5W3H system prompt was used (dimensional walk present).
        joined_system = "\n".join(s for s, _ in prompts)
        for dim in ("Why", "Who", "Where", "How"):
            self.assertIn(dim, joined_system)
        # 6. best-of-N SELECTED the grounded (thorough) candidate.
        self.assertIn("real_module.py", out)
        self.assertNotIn("does/not/exist.py", out)
        # 7. self-review assumptions appended.
        self.assertIn("Inferred:", out)
        # 8. judge review note appended (verdict challenged).
        self.assertIn("Review Note", out)
        # 9. winning stance captured in out_meta.
        self.assertIn(meta.get("stance"), ("minimal-scope", "thorough", "risk-averse"))
