#!/usr/bin/env bash
# Verify BROWSER_LAYER_ENABLED is active (True) in the 9to5 config.
# Outputs "Browser Layer Enabled" if the flag is true, non-zero exit otherwise.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

result=$(cd "$SCRIPT_DIR" && python - <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import BROWSER_LAYER_ENABLED
print("Browser Layer Enabled" if BROWSER_LAYER_ENABLED else "Browser Layer Disabled")
sys.exit(0 if BROWSER_LAYER_ENABLED else 1)
PYEOF
)

echo "$result"
[ "$result" = "Browser Layer Enabled" ]
