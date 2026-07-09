# Pre-Execution Council Provider Roadmap

This note is planning-only. Do not wire these providers into production orchestration from here.

## Next Architecture Work

- Add selector council mode before broad provider expansion: independent memos, compressed claim/risk/disagreement maps, selected debate speakers, critique pairs, and final execution-grade synthesis.
- Keep provider-specific logic inside seat classes/adapters. The runner should continue to orchestrate seats, prompts, compact state, warnings, replay, and brief synthesis.

## Future Optional Seats

- Cloudflare Workers AI: explicitly gated later with `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, and `PRE_EXECUTION_COUNCIL_CLOUDFLARE_MODEL`; never log tokens; fall back to mock on quota, transport, or model errors; add after selector-mode planning unless there is a strong reason to do it sooner.
- GitHub Models or Cerebras: optional API seats only; explicitly gated; safe metadata and fallback behavior; never required for council execution.
- xAI Grok browser: do not confuse with Groq API; browser automation only; consider only after the browser automation abstraction is mature.
- Claude live: keep mocked while quota/safety is blocked; eventual integration must be read-only, planning-only, non-mutating, and explicitly gated.
