# Security checks

Skills in this repo are instructions and scripts that Claude Code runs on
people's machines, often with shell access. Every pull request is therefore
checked by the [`Security checks`](.github/workflows/security.yml) workflow.
A failing check blocks the merge.

## What is checked

| Job | Tool | Catches |
|-----|------|---------|
| Leaks, dangerous commands & skill risks | [`check_content.py`](.github/security/check_content.py) | see below. Runs on the tree **and on every commit of the PR** |
| Secrets (gitleaks) | [gitleaks](https://github.com/gitleaks/gitleaks) + [`.gitleaks.toml`](.gitleaks.toml) | 150+ secret formats, plus Galaxy / OpenStack / vCenter credentials; tree + PR history |
| Secrets (trufflehog) | [trufflehog](https://github.com/trufflesecurity/trufflehog) | secrets, live-verified against providers where possible |
| Script analysis | shellcheck, bandit | unsafe shell (warning level and above), insecure Python (medium and above) |
| Workflow security | [zizmor](https://github.com/zizmorcore/zizmor) | template injection, unpinned actions, credential persistence in CI |

`check_content.py` errors on:

- **Secrets**: private keys, SSH public keys, GitHub/AWS/Google/Slack/Anthropic/OpenAI tokens, JWTs, Galaxy API keys, hard-coded passwords, credentials in URLs, kubeconfig key data
- **Internal leaks**: private IPs (RFC 1918 / CGNAT), internal hostnames (`*.corp`, `*.lab`, `*.internal`, `*.eng.redhat.com`, ...), personal home paths (`/Users/<name>/`), and org-specific identifiers from the hashed [`denylist.sha256`](.github/security/denylist.sha256)
- **Dangerous commands**: `curl … | sh`, decode-and-exec, reverse shells, `rm -rf /` or `~`, disk wipes, history/log tampering, writes to `authorized_keys`, sending credential files or the environment over the network
- **Agent / skill risks**: prompt-injection phrases ("ignore previous instructions", "don't tell the user"), Claude Code permission or sandbox bypass (`--dangerously-skip-permissions`, `bypassPermissions`, `Bash(*)`), writes to `~/.claude/settings.json`, hooks or shell rc files, hidden/bidi Unicode (Trojan Source, ASCII smuggling), and `allowed-tools` granting unscoped `Bash`
- **Files**: key/credential filenames (`id_rsa`, `*.pem`, `.env`, `kubeconfig`, `clouds.yaml`, ...), binaries, files over 1 MiB, symlinks pointing outside the repo, and `SKILL.md` without `name`/`description` frontmatter

It only **warns** on emails, `chmod 777`, disabled TLS verification and `NOPASSWD: ALL`.

The full git history is rescanned weekly, so newly added detector rules also cover old commits.

## Run locally before pushing

```bash
scripts/security-check.sh                 # same checks as CI (optional tools skipped if missing)
scripts/security-check.sh --install-hook  # run them automatically on every git push
```

`python3` is the only requirement. Install `gitleaks`, `trufflehog`, `shellcheck`,
`bandit` and `zizmor` for full coverage.

## Writing skills that pass

- Use placeholders (`<devstack-ip>`, `<your-namespace>`) or env vars (`$OSM_NS`), never your real values.
- For example IPs, use the documentation ranges `192.0.2.x`, `198.51.100.x` and `203.0.113.x` (RFC 5737). They are always accepted.
- Use `~` or `$HOME` instead of `/Users/<you>/` or `/home/<you>/`.
- Never commit keys or tokens, not even in a commit you revert later. Every commit of the PR is scanned, and anything that was pushed must be rotated.

## Handling a false positive

1. **Fix the content if you can** (placeholder, documentation IP, env var).
2. **One line:** add the comment `security-check: allow <rule-id>` on that line.
3. **Reviewed exception:** add `<rule-id> <path-glob> <regex>` to
   [`.github/security/allowlist.txt`](.github/security/allowlist.txt). Keep the
   regex as narrow as possible (for example `^10\.0\.0\.1$`).
4. **gitleaks:** add a `[[allowlists]]` entry to `.gitleaks.toml`, or a
   `gitleaks:allow` comment on the line.

Changes to the allowlist, the denylist or the workflow must get explicit reviewer approval.

## Adding an internal identifier to the denylist

Some org-specific names (internal namespaces, personal key names, usernames)
can't be caught by a generic pattern. Listing them in plain text would leak
them too, so only their SHA-256 is stored:

```bash
python3 -I .github/security/check_content.py --hash my-internal-namespace >> .github/security/denylist.sha256
# then add a vague comment after the hash, e.g.  "# internal CI namespace"
```

Matching is case-insensitive, on whole words and on their `.`/`_`-separated parts.
Short or common words can be guessed from their hash by brute force, so this
list hides names from casual reading but is not encryption.
