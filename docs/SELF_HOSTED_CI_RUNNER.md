# Trusted Self-Hosted CI Runner

The `tests` workflow intentionally runs only trusted `main`, nightly, and manual-dispatch code.
It must never be enabled for `pull_request` or `pull_request_target` while using a workstation.

1. Create a repository-scoped Windows runner in GitHub Settings → Actions → Runners.
2. Install it under a dedicated local account and label it `self-hosted`, `Windows`, `X64`, and `9to5-ci`.
3. Run it as a service with a separate Actions work directory; do not point it at the active `C:\9to5` checkout.
4. Dispatch the `fast` workflow and confirm the job reports the self-hosted runner label before relying on it.
5. Keep the runner token and any account credentials outside the repository.

If the runner is unavailable, use `python tools/dev.py ci-local`; do not re-enable paid hosted runners as a silent fallback.
