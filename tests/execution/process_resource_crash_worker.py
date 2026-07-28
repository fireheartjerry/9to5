"""Fresh-process creator-death worker for registered process boundaries."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform_core.execution.process_resources import RegisteredProcessLauncher
from platform_core.runtime.attempt_journal import AttemptJournal
from platform_core.runtime.candidate import ProcessResourceState


def main() -> int:
    case = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    journal = AttemptJournal(case["journal_root"])
    resource = journal.load_resources(case["transaction_id"])[0]
    real_transition = journal.transition_resource

    def die_before_created_commit(transaction_id, resource_id, state, **changes):
        if state is ProcessResourceState.CREATED:
            identity = json.dumps(
                {
                    "pid": changes["pid"],
                    "process_start_token": changes["process_start_token"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            with open(case["identity_path"], "xb") as stream:
                stream.write(identity)
                stream.flush()
                os.fsync(stream.fileno())
            os._exit(88)
        return real_transition(transaction_id, resource_id, state, **changes)

    journal.transition_resource = die_before_created_commit  # type: ignore[method-assign]
    launcher = RegisteredProcessLauncher(
        journal=journal,
        resource=resource,
        security_profile_digest=case["security_profile_digest"],
    )
    launcher(
        case["argv"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=case["cwd"],
        creationflags=case["creationflags"],
        env=case["environment"],
        start_new_session=(os.name != "nt"),
    )
    return 70


if __name__ == "__main__":
    raise SystemExit(main())
