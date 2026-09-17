#!/usr/bin/env bash
set -euo pipefail

# Documentation draft skeleton for undocumented external mappings (VMware, then os-migrate).
# Usage:
#   ./scripts/draft-undocumented.sh
#   ./scripts/draft-undocumented.sh all
#   ./scripts/draft-undocumented.sh vmware [mapping-id]
#   ./scripts/draft-undocumented.sh path/to/audit-report.json
#   ./scripts/draft-undocumented.sh vmware path/to/audit-report.json [mapping-id]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "${SCRIPT_DIR}/draft_undocumented.py" "$@"
