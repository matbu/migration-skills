#!/usr/bin/env bash
# Run the repository security checks locally (same checks as CI).
#
#   scripts/security-check.sh                 # check tree (+ unpushed commits)
#   scripts/security-check.sh --install-hook  # run automatically before every git push
#
# Required: python3, git. Optional (skipped with a notice if missing):
# gitleaks, trufflehog, shellcheck, bandit, zizmor.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ "${1:-}" == "--install-hook" ]]; then
    hook="$(git rev-parse --git-path hooks)/pre-push"
    printf '#!/usr/bin/env bash\nexec "%s/scripts/security-check.sh"\n' "$REPO_ROOT" > "$hook"
    chmod +x "$hook"
    echo "Installed pre-push hook: $hook"
    exit 0
fi

failed=0
run() {
    local name=$1
    shift
    echo "==> $name"
    if "$@"; then
        echo "    OK"
    else
        echo "    FAILED: $name"
        failed=1
    fi
}
skip() { echo "==> $1: not installed, skipped (CI will still run it)"; }

run "checker self-test" python3 -I -m unittest discover -s .github/security -p 'test_*.py'
run "content check (tree)" python3 -I .github/security/check_content.py

# Commits not yet on the upstream branch (what a PR would contain)
if upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null); then
    base=$(git merge-base HEAD "$upstream")
    if [[ "$base" != "$(git rev-parse HEAD)" ]]; then
        run "content check (commits ${base:0:8}..HEAD)" \
            python3 -I .github/security/check_content.py --commits "${base}..HEAD"
    fi
fi

if command -v gitleaks > /dev/null; then
    run "gitleaks (tree)" gitleaks dir . --config .gitleaks.toml --redact --no-banner
    run "gitleaks (history)" gitleaks git . --config .gitleaks.toml --redact --no-banner
else
    skip gitleaks
fi

if command -v trufflehog > /dev/null; then
    run "trufflehog" trufflehog git "file://$REPO_ROOT" --results=verified,unknown --fail --no-update
else
    skip trufflehog
fi

if command -v shellcheck > /dev/null; then
    run "shellcheck" bash -c "git ls-files -z '*.sh' '*.bash' | xargs -0 -r shellcheck -S warning"
else
    skip shellcheck
fi

if command -v bandit > /dev/null; then
    run "bandit" bash -c "bandit -q -r . -x './.git,*/test_*.py' -ll -ii && \
        git ls-files -z '*test_*.py' | xargs -0 -r bandit -q -ll -ii -s B108"
else
    skip bandit
fi

if command -v zizmor > /dev/null; then
    run "zizmor" zizmor --offline .github/workflows
else
    skip zizmor
fi

echo
if [[ $failed -ne 0 ]]; then
    echo "Security checks FAILED. See SECURITY-CHECKS.md for how to fix or allowlist."
    exit 1
fi
echo "All security checks passed."
