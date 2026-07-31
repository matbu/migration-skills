#!/usr/bin/env bash
set -euo pipefail

# Mechanical doc↔code correctness audit (VMware kit, then os-migrate by default).
# Usage:
#   ./scripts/audit-correctness.sh
#   ./scripts/audit-correctness.sh all
#   ./scripts/audit-correctness.sh vmware [mapping-id]
#   ./scripts/audit-correctness.sh os-migrate [mapping-id]
#   ./scripts/audit-correctness.sh path/to/audit-report.json
#   ./scripts/audit-correctness.sh vmware path/to/audit-report.json [mapping-id]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "${SCRIPT_DIR}/audit_correctness.py" "$@"
