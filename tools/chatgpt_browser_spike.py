"""Standalone CLI wrapper for the experimental ChatGPT browser driver.

This script stays isolated from production orchestration and delegates the live
browser path to ``agents.execution.chatgpt_browser_driver``.

RUN/TEST: python -m pytest tests/tools/test_chatgpt_browser_spike.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from agents.execution import chatgpt_browser_driver as driver


def _print(msg: str) -> None:
    print(msg, flush=True)

def run_spike(args: argparse.Namespace) -> int:
    if Path(args.profile) != driver.DEFAULT_PROFILE:
        raise driver.ChatGptBrowserError(
            f"Experimental driver is pinned to the dedicated recon profile only: {driver.DEFAULT_PROFILE}"
        )
    if Path(args.chrome) != driver.DEFAULT_CHROME:
        raise driver.ChatGptBrowserError(
            f"Experimental driver is pinned to the installed Chrome path only: {driver.DEFAULT_CHROME}"
        )
    if int(args.debug_port) != driver.DEFAULT_PORT:
        raise driver.ChatGptBrowserError(
            f"Experimental driver is pinned to debug port {driver.DEFAULT_PORT} during the spike."
        )
    if float(args.timeout) != driver.DEFAULT_TIMEOUT_S:
        raise driver.ChatGptBrowserError(
            f"Experimental driver is pinned to timeout {driver.DEFAULT_TIMEOUT_S} seconds during the spike."
        )

    ignore_line = driver._verify_profile_is_gitignored(driver.DEFAULT_PROFILE)
    _print(f"[safe] gitignored profile path verified: {driver.DEFAULT_PROFILE}")
    if ignore_line:
        _print(f"[safe] ignore rule: {ignore_line}")

    launch_mode = driver._ensure_debuggable_chrome(
        chrome=driver.DEFAULT_CHROME,
        profile=driver.DEFAULT_PROFILE,
        project_url=args.project_url,
        debug_port=driver.DEFAULT_PORT,
        timeout_s=driver.DEFAULT_TIMEOUT_S,
    )
    if launch_mode == "reused":
        _print(f"[safe] reusing dedicated Chrome on localhost:{driver.DEFAULT_PORT}")
    else:
        _print(f"[safe] launching dedicated Chrome with profile path only: {driver.DEFAULT_PROFILE}")
        _print(f"[safe] Chrome debug endpoint ready on localhost:{driver.DEFAULT_PORT}")

    response_text = driver.send_prompt_to_project(
        project_url=args.project_url,
        model=args.model,
        reasoning=args.reasoning,
        prompt=args.prompt,
    )
    _print(f"[safe] project url: {args.project_url}")
    _print("[assistant]")
    _print(response_text)
    if args.prompt == driver.DEFAULT_PROMPT:
        matched = response_text.strip() == driver.EXPECTED_DEFAULT_REPLY
        _print(f"[check] exact default reply matched: {'yes' if matched else 'no'}")
        if not matched:
            raise driver.ChatGptBrowserError(
                "Extracted response did not match the expected default test output."
            )
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=str(driver.DEFAULT_PROFILE))
    parser.add_argument("--project-url", default=driver.DEFAULT_PROJECT_URL)
    parser.add_argument("--model", default=driver.DEFAULT_MODEL)
    parser.add_argument("--reasoning", default=driver.DEFAULT_REASONING)
    parser.add_argument("--prompt", default=driver.DEFAULT_PROMPT)
    parser.add_argument("--chrome", default=str(driver.DEFAULT_CHROME))
    parser.add_argument("--debug-port", type=int, default=driver.DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=driver.DEFAULT_TIMEOUT_S)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    try:
        return run_spike(args)
    except driver.ChatGptBrowserError as exc:
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
