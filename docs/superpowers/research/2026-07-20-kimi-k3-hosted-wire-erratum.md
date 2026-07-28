# Kimi K3 hosted-service and wire-contract erratum

Initially captured at `2026-07-20T00:23:24Z` after the Kimi K3
research-transfer record, with a provider-surface closure follow-up at
`2026-07-20T00:33:53Z`. This is a non-authoritative evidence supplement. It
does not grant provider, trial, spend, topology, OCI, solver, or runtime
authority.

## Corrected availability statement

Kimi K3 became available as a hosted Kimi/API service on 2026-07-16. The
downloadable full model weights were not public at this capture time. Moonshot
promised the full weights by 2026-07-27 and described the technical report as
forthcoming, without binding the report itself to that exact date in the
captured launch wording. “Open” and “open-source” are therefore vendor release
positioning, not evidence of a downloadable, licensed, immutable checkpoint.

Direct registry queries returned no MoonshotAI Kimi-K3 repository and no
MoonshotAI Hugging Face Kimi-K3 model at the capture time. Component projects
such as Kimi-Linear and Attention-Residuals are not a complete K3 checkpoint or
serving closure.

## Official hosted API contracts relevant to a future dark driver

The general international Kimi Open Platform uses the OpenAI-compatible Chat
Completions wire at the exact base URL `https://api.moonshot.ai/v1` with bearer
authentication. Its official K3 quickstart identifies model `kimi-k3`. On this
surface K3 always reasons and currently accepts only `reasoning_effort="max"`.
Multi-turn and tool continuations must return the complete assistant message
unchanged; streaming emits `reasoning_content` separately from final `content`;
strict structured output applies to final `content` only; and dynamic tool
definitions must remain in request history because the service does not retain
them.

The same capture states that `max_completion_tokens` defaults to 131072 and is
bounded at 1048576; temperature 1.0, top-p 0.95, `n=1`, and zero penalties are
fixed; stable prefixes receive automatic caching; and the hosted web-search
tool was being updated and was not recommended for production. These facts
require exact provider-wire, session/model, tool-history, quota, and silent-
fallback controls before any future shadow trial.

Kimi Code is a separate subscription surface and must never be conflated with
the general API. It exposes an OpenAI-compatible base URL at
`https://api.kimi.com/coding/v1` and an Anthropic-compatible base URL at
`https://api.kimi.com/coding/`. Its K3 model ID is `k3`; K3 requires Moderato
membership or above, while the one-million-token context requires Allegretto or
above. This surface supports `low`, `high`, and `max` reasoning effort, unlike
the general API's captured max-only contract.

The Kimi Code model documentation also says that disabling thinking for K3 or
K2.7 routes the request to K2.6. It separately documents that a mistyped
HighSpeed model ID can silently fall back to standard `kimi-for-coding`.
Requested model text is therefore insufficient execution provenance: a future
dark driver would have to bind the exact provider surface, endpoint, returned
model/provider identity, thinking mode, plan entitlement, quota state, and
session history.

## Exact response fingerprints

The bodies were fetched without credentials using a fixed research user agent.
Response bodies are intentionally not vendored; URL, HTTP status, UTF-8 byte
length, retrieval time, and SHA-256 bind this observation and make drift
detectable.

| Source | HTTP | UTF-8 bytes | SHA-256 |
|---|---:|---:|---|
| `https://platform.kimi.com/docs/guide/kimi-k3-quickstart` | 200 | 882169 | `524c121f882aba74fa2cf787dfc3bb15d7d7e92ad66d41f024176bad89df418f` |
| `https://api.github.com/search/repositories?q=org%3AMoonshotAI%20Kimi-K3` | 200 | 55 | `4af480b8ee5b87b369a76c49bd22c9a783908272ebffbe97898f8ab0f0772a5f` |
| `https://huggingface.co/api/models?author=moonshotai&search=Kimi-K3&limit=100` | 200 | 2 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `https://platform.kimi.ai/docs/api/overview` | 200 | 379420 | `74b6a7766206c3e1a1dc4ad2a0f7993d40234a9d3f60c245d96a8dc35d96ae93` |
| `https://www.kimi.com/code/docs/en/` | 200 | 55747 | `6d8c6582b95c62a28656e5f0327221f4665748f7f3bdc48420146b1750b06c97` |
| `https://www.kimi.com/code/docs/en/kimi-code/models.html` | 200 | 49234 | `f9d171cc7c01598ea10a7e40ebcc3ce99495fb52c6220b2001d4cb75813b76d6` |

## Mandatory disposition

- Hosted availability is not `public_artifact` availability.
- The moving `kimi-k3` alias is not an immutable model revision.
- The hosted API violates the current `external_spend_allowed=false` gate.
- No SourcePassport or reviewed offline OCI closure can exist before exact
  weights, license, runtime, hashes, hardware topology, and independent oracles
  are available.
- Quark may eventually consume independently verified candidate formulations;
  K3 itself never becomes solver, dispatch, warrant, or promotion authority.
- Recheck public artifacts after the promised full-weight date, beginning
  2026-07-28, and issue a new evidence capture rather than rewriting this one.
