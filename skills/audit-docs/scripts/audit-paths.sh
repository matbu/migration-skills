#!/usr/bin/env bash
set -euo pipefail

# Path audit for code-to-docs mappings (VMware kit, then os-migrate by default).
# Usage:
#   ./scripts/audit-paths.sh
#   ./scripts/audit-paths.sh all
#   ./scripts/audit-paths.sh vmware [mapping-id]
#   ./scripts/audit-paths.sh os-migrate [mapping-id]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "${SCRIPT_DIR}/audit_paths.py" "$@"
