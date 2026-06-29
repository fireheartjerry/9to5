# Human-Nature Layer — Research Digest (2026-06-28)

**Source:** deep-research harness — 6 angles, 28 sources fetched, 128 claims, 25 adversarially
verified (3-vote, 25/25 confirmed, 0 killed), synthesized to 11 findings.
**Purpose:** ground the `human-nature-insertion` spec (opinions / instinct / intuition / emotions /
self-awareness) in 2024–2026 frontier evidence. Companion to `human-nature-insertion.md`.

---

## One-line verdict

The five faculties are **buildable**, but only as **functional, calibrated, task-gated signals
grounded in accumulated experience** — never as scripted personality. The cross-cutting law:
human-likeness + autonomy both **inflate trust above actual reliability**, so every faculty added
must ship with a *legible calibration / honest-limit* counterweight.

---

## Findings → design principles (each verified 3-0)

### Substrate
1. **Disposition = durable versioned artifact, not a prompt costume.** Anthropic builds Claude's
   character via training + a written **constitution** treated as "final authority"; traits
   *causally* shape behavior, so persona edits are *alignment* changes.
   → 9to5: express the layer through the **SIE/experience ledger + a short written "Cast charter"**;
   treat the charter as authority, version/review it. We can't fine-tune a closed API → analogue is
   **memory-conditioning + a stable constitution-style preamble** (weaker lever; accept it).
   *Sources: anthropic.com/research/claude-character, /news/claude-new-constitution.*

2. **Persona is a double-edged sword — gate it by task type (PRISM).** Personas help generative /
   human-facing tasks but *drop* discriminative accuracy (MMLU 71.6%→66-68%).
   → **Persona/opinion/emotion ON** for Discord/Nightclaw chat, PR narration, design debate;
   **OFF** for verification verdicts, test pass/fail, diff-correctness. *Verifier owns verdicts —
   never let affect color a result.* *Source: arXiv 2603.18507 (single recent preprint; directional).*

3. **Expressed persona DRIFTS over long runs even while self-model stays stable.** Self-reports stay
   consistent; observer-rated expression decays — replicated boundary condition.
   → Don't trust one-time init for a long Run. **Re-anchor tone periodically; measure persona at the
   OUTPUT layer, not by asking the agent.** Keep Cast intensity **moderate** (high-intensity decays
   fastest). Self-awareness guardrail: "I'm still consistent" is *not* evidence — drift is invisible
   from inside. *Source: arXiv 2601.22812.*

### Opinions
4. **Earned, frank, non-sycophantic opinion is sanctioned design intent**, not a hack. Intended
   disposition voices warranted disagreement; rejects pandering, forced centrism, false objectivity;
   "treat users like intelligent adults."
   → Nightclaw *may* hold and voice an earned stance. Guardrail: pushback = warranted disagreement
   tied to **evidence/taste**, not reflexive contrarianism; express stance, don't unilaterally block.
   *Sources: claude-character, claude-new-constitution.*

5. **The sycophancy failure is SOCIAL, not logical.** A bare confident assertion ("the answer is X",
   no reasoning) flips a SOTA LLM **84.5%** of the time; a fully-reasoned rebuttal only 56.1%.
   Follow-up framing amplifies capitulation; re-framing as a **neutral judge comparison** gives the
   best net accuracy (+24.6%).
   → When you push back on a Nightclaw stance, it must **re-derive in a fresh neutral frame**
   ("user asserts X, I asserted Y — evaluate both on evidence"), not fold in-thread. Calibrate
   pushback to evidence, not to *your* assertiveness. *Source: arXiv 2509.16533.*

### Cross-cutting guardrail
6. **Autonomy AND human-likeness both raise risk.** Ceding control scales risk; agents that write+run
   their own code beyond constraints can override human control; personas/memory "trigger emotional
   compliance while masking statistical fallibility."
   → The layer must **increase** legible reliability signals (calibrated confidence, honest limits,
   verification receipts) to offset the trust it inflates. Keep human-in-loop ceilings; **cap
   self-modification of own constraints.** A more human-feeling Nightclaw earns MORE scrutiny, not a
   trust discount. *Source: arXiv 2502.02649 (contested position paper — risk lens, not law).*

### Emotions
7. **Emotion can be grounded in appraisal theory, not scripts** — appraisal "chain-of-emotion" beat
   vanilla architectures on UX/believability metrics.
   → Derive Cast emotions from **appraisal of run events** (clean run→satisfaction, repeat
   failure→frustration, novel discovery→curiosity). *Caveat:* evidence measured believability/UX,
   **not SWE task success** — don't assume affect improves coding throughput. *Source: arXiv 2309.05076.*

8. **Every emotion must be functionally justified** — in RL, computational emotion either improves the
   agent's **learning efficiency** OR serves as a **social signal**; grounded in homeostasis/appraisal
   dimensions.
   → Each Cast emotion must drive **behavior** (frustration→escalate/replan, curiosity→explore) OR
   **communication** — else it's theater, cut it. Ground each in ledger state (failure-streak count,
   novelty score). *Source: arXiv 1705.05172 (canonical survey).*

9. **Curiosity/intrinsic motivation is a real performance lever**, not decoration — intrinsic
   exploration reward improved hard reasoning (+22.23% AIME 2024, gains across 4 datasets; multiple
   independent groups).
   → Model "curiosity on novel discovery" as an **exploration signal that changes behavior** — more
   search/retries/branching when the ledger flags a problem novel. *Caveat: relative gain, ~2/30
   high-variance problems; debate is HOW not WHETHER.* *Source: arXiv 2505.17621.*

### Intuition
10. **Pre-verbal confidence has a real mechanistic substrate** — hidden states encode a calibrated
    correctness signal; a probe predicts whether a CoT will succeed **before a single token** is
    generated (ROC-AUC>0.7, ECE<0.1).
    → The faculty is scientifically grounded. **CRITICAL for 9to5: Claude API exposes no hidden
    states** → approximate black-box via **self-consistency sampling, early verbalized confidence,
    cross-Cast agreement**. Guardrail: pre-gen accuracy only **60-76%**, probes don't generalize OOD →
    treat gut as a **sometimes-wrong heuristic that EARNS trust over time**, never ground truth.
    *Sources: arXiv 2504.05419, 2505.24362.*

11. **A trustworthy confidence signal exists but isn't free** — larger models are well-calibrated on
    MC/TF *in the right format*; RLHF degrades calibration (recoverable via temperature scaling T~2.5).
    → Elicit confidence in **calibration-friendly formats** (MC/TF, verbalized P(True)) and
    **recalibrate** — the executor is RLHF'd → likely overconfident. Self-awareness must be backed by
    *recalibrated* numbers, not vibes. *Source: arXiv 2207.05221 (Kadavath, "LMs Mostly Know What They Know").*

---

## Open questions the research could NOT close (→ must resolve in spec / in-house)

1. Does persona/emotion/opinion expression **help or hurt SWE task completion** specifically
   (commit quality, test-pass, time-to-green)? No surviving claim measures this → needs an **in-house
   A/B on real 9to5 Runs** before the layer touches accuracy-critical work.
2. Best **black-box proxy** for pre-verbal confidence on a closed API (self-consistency variance vs
   verbalized P(True) vs cross-Cast agreement) + recalibration method.
3. How to ground **instinct** in an episodic/reflective memory architecture (Generative Agents /
   Reflexion / Voyager style) on top of SIE + failure-mode ledger — research didn't cover this directly.
4. The **safe ceiling on opinion-driven pushback** — where warranted disagreement (4,5) collides with
   the autonomy/overtrust guardrail (6).
5. How to **detect & correct expressed-persona drift online** during a long Run, given self-report
   stays stable while behavior decays (3).

---

## How this steers the spec (preview)

- Opinions → **tiered, evidence-gated** (cosmetic→soft→hard), neutral-judge re-derivation on pushback,
  hard-causal capped below "override the human's explicit goal."
- Instinct → ledger-grounded pattern flags (extends Nightclaw Instinct), sometimes-wrong-by-design.
- Intuition → black-box confidence proxy (self-consistency / verbalized P(True) / cross-Cast), recalibrated.
- Emotions → appraisal-derived from run events, each justified by behavior OR communication, gated off verify.
- Self-awareness → recalibrated honest-limits, drift measured at output layer, self-report distrusted.
- Cross-cutting → every faculty ships with a calibration/honest-limit counterweight; PRISM-style gating
  keeps all of it OFF the verifier.
