#!/usr/bin/env python3
"""Security / leak checker for the migration-skills repository.

Scans every git-tracked file for things that must never land in this public
repo of Claude Code skills:

* secrets: private keys, tokens, API keys, hard-coded passwords
* internal leaks: private IPs, internal hostnames, personal home paths, emails
* dangerous commands: pipe-to-shell, reverse shells, ``rm -rf /``, obfuscated exec
* agent-skill risks: prompt-injection phrases, permission/sandbox bypass,
  hidden Unicode (Trojan Source / ASCII smuggling)
* dangerous files: key/credential filenames, binaries, oversized files
* org-specific identifiers listed (as sha256 hashes only) in denylist.sha256
* skill hygiene: SKILL.md frontmatter with ``name`` and ``description``

Findings are ``error`` (fails the check) or ``warning`` (reported only).

False positives can be silenced either:
  - inline, with ``security-check: allow <rule-id>`` on the same line, or
  - in ``.github/security/allowlist.txt`` (see that file for the format).

Usage: check_content.py [--root DIR] [--allowlist FILE] [paths ...]
Only the Python standard library is used. Run with ``python3 -I``.
"""

from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import os
import re
import subprocess
import sys
from dataclasses import dataclass

MAX_FILE_BYTES = 1024 * 1024  # 1 MiB: skills are text, anything bigger is suspect

ERROR = "error"
WARNING = "warning"


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    severity: str
    message: str


@dataclass
class Rule:
    rule_id: str
    severity: str
    pattern: re.Pattern
    message: str
    # optional callable(match) -> bool; return False to drop the match
    validate: object = None
    # only apply to files matching one of these globs (None = all text files)
    globs: tuple | None = None


def _redact(text: str) -> str:
    text = text.strip()
    if len(text) <= 8:
        return text[:2] + "***"
    return text[:4] + "***" + text[-2:]


# --------------------------------------------------------------------------
# validators
# --------------------------------------------------------------------------

PLACEHOLDER_RE = re.compile(
    r"(?i)(change.?me|example|sample|dummy|fake|placeholder|your[_-]|my[_-]|"
    r"redacted|xxx|\*\*\*|<[^>]*>|\$\{?[A-Za-z_]|\{\{|%\(|secret_name|"
    r"password$|passw0rd$|^test|todo)"
)


def _not_placeholder(m: re.Match) -> bool:
    value = m.group("value")
    return not PLACEHOLDER_RE.search(value)


# Documentation / special ranges that are fine to show.
_ALLOWED_NETS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8",      # loopback
    "0.0.0.0/8",        # "any"
    "192.0.2.0/24",     # TEST-NET-1  (RFC 5737) -> use these in docs
    "198.51.100.0/24",  # TEST-NET-2
    "203.0.113.0/24",   # TEST-NET-3
    "169.254.169.254/32",  # cloud metadata service, well known
)]
_PRIVATE_NETS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
)]


def _is_private_ip(m: re.Match) -> bool:
    try:
        ip = ipaddress.ip_address(m.group(0))
    except ValueError:
        return False
    if any(ip in n for n in _ALLOWED_NETS):
        return False
    return any(ip in n for n in _PRIVATE_NETS)


_GENERIC_HOME_USERS = {
    "user", "username", "your-user", "youruser", "me", "runner", "stack",
    "ubuntu", "centos", "fedora", "cloud-user", "admin", "core", "ec2-user",
    "builder", "zuul", "jenkins", "vagrant", "test", "example", "foo", "bar",
}


def _is_personal_home(m: re.Match) -> bool:
    name = m.group("user")
    return name.lower() not in _GENERIC_HOME_USERS and not name.startswith(("$", "<", "{"))


_ALLOWED_EMAIL_RE = re.compile(
    r"(?i)(noreply|no-reply)|@(example\.(com|org|net)|users\.noreply\.github\.com|"
    r"anthropic\.com|localhost|vsphere\.local)$|"
    r"\.(?:service|target|socket|timer|mount|slice|path)$"  # systemd units: foo@bar.service
)


def _is_real_email(m: re.Match) -> bool:
    return not _ALLOWED_EMAIL_RE.search(m.group(0))


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def R(rule_id, severity, regex, message, validate=None, flags=0, globs=None):
    return Rule(rule_id, severity, re.compile(regex, flags), message, validate, globs)


RULES: list[Rule] = [
    # ---- secrets ---------------------------------------------------------
    R("private-key", ERROR,
      r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----",
      "Private key material"),
    R("putty-key", ERROR, r"PuTTY-User-Key-File-\d", "PuTTY private key"),
    R("ssh-public-key", ERROR,
      r"\b(?:ssh-(?:rsa|ed25519|dss)|ecdsa-sha2-nistp\d+) AAAA[0-9A-Za-z+/]{40,}",
      "SSH public key (identifies a person/host)"),
    R("github-token", ERROR,
      r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b",
      "GitHub token"),
    R("aws-access-key", ERROR, r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "AWS access key id"),
    R("google-api-key", ERROR, r"\bAIza[0-9A-Za-z_\-]{35}\b", "Google API key"),
    R("slack-token", ERROR, r"\bxox[abposr]-[0-9A-Za-z-]{10,}", "Slack token"),
    R("anthropic-key", ERROR, r"\bsk-ant-[A-Za-z0-9_\-]{20,}", "Anthropic API key"),
    R("openai-key", ERROR, r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b", "OpenAI-style API key"),
    R("jwt", ERROR,
      r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
      "JSON Web Token"),
    R("galaxy-api-key", ERROR,
      r"(?i)(?:api[-_]?key|galaxy[-_]?(?:api[-_]?)?(?:key|token))[\"']?\s*[:= ]\s*[\"']?(?P<value>[0-9a-f]{40})\b",
      "Ansible Galaxy / hex API key"),
    R("hardcoded-credential", ERROR,
      r"(?i)\b(?:password|passwd|pwd|passphrase|secret|token|api[_-]?key|access[_-]?key|"
      r"os_password|client[_-]?secret)\b[\"']?\s*[:=]\s*[\"'](?P<value>[^\"'\s]{6,})[\"']",
      "Hard-coded credential", _not_placeholder),
    R("url-credentials", ERROR,
      r"\b[a-z][a-z0-9+.-]*://(?P<value>[^/\s:@]+:[^/\s:@]{3,})@[^\s/]+",
      "Credentials embedded in URL", _not_placeholder),
    R("kube-cert-data", ERROR,
      r"(?:client-key-data|client-certificate-data|certificate-authority-data):\s*[A-Za-z0-9+/=]{40,}",
      "Kubeconfig certificate/key data"),

    # ---- internal / personal leaks --------------------------------------
    R("private-ip", ERROR,
      r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])",
      "Private/internal IP address (use 192.0.2.x / 198.51.100.x / 203.0.113.x or a <placeholder>)",
      _is_private_ip),
    R("internal-hostname", ERROR,
      r"(?i)\b(?:[a-z0-9-]+\.)+(?:corp|internal|intranet|intra|lan|localdomain|lab|"
      r"(?:[a-z0-9-]+\.)?(?:int|eng|corp|lab)\.redhat\.com)\b",
      "Internal hostname"),
    R("personal-home-path", ERROR,
      r"(?:/Users|/home)/(?P<user>[A-Za-z0-9._$<{][A-Za-z0-9._-]*)/",
      "Personal home directory path (use ~ or $HOME)", _is_personal_home),
    R("email", WARNING,
      r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b",
      "Email address", _is_real_email),

    # ---- dangerous commands ---------------------------------------------
    R("pipe-to-shell", ERROR,
      r"\b(?:curl|wget|fetch)\b[^\n|;]*\|\s*(?:sudo\s+)?(?:env\s+\S+\s+)?(?:ba|z|k|da)?sh\b",
      "Downloaded content piped straight into a shell"),
    R("pipe-to-interpreter", ERROR,
      r"\b(?:curl|wget)\b[^\n|;]*\|\s*(?:sudo\s+)?(?:python\d?|perl|ruby|node)\b",
      "Downloaded content piped straight into an interpreter"),
    R("decode-and-exec", ERROR,
      r"(?:base64\s+(?:-d|--decode|-D)|xxd\s+-r|openssl\s+(?:enc\s+)?-d)[^\n]*\|\s*(?:ba|z)?sh\b|"
      r"\b(?:exec|eval)\s*\(\s*(?:base64\.b64decode|codecs\.decode|bytes\.fromhex|atob|Buffer\.from)\b|"
      r"\beval\s+\"?\$\((?:curl|wget|echo\s+[A-Za-z0-9+/=]{20,}\s*\|\s*base64)",
      "Obfuscated / decoded payload executed"),
    R("reverse-shell", ERROR,
      r">&\s*/dev/(?:tcp|udp)/|<>\s*/dev/(?:tcp|udp)/|/dev/(?:tcp|udp)/\S+\s+0>&1|"
      r"\bnc(?:at)?\b[^\n]*\s-(?:e|c)\s|\bbash\s+-i\s*[>&]+|"
      r"\bsocat\b[^\n]*exec:|\bmkfifo\b[^\n]*\bnc\b",
      "Reverse-shell / remote command channel pattern"),
    R("destructive-rm", ERROR,
      r"\brm\s+(?:-[A-Za-z]*\s+)*-[A-Za-z]*[rR][A-Za-z]*\s+(?:-[A-Za-z-]+\s+)*"
      r"(?:--no-preserve-root|/(?:\s|$|\*)|~/?(?:\s|$|\*)|\"?\$HOME\"?/?(?:\s|$|\*)|/\*)",
      "Recursive delete of /, ~ or $HOME"),
    R("disk-wipe", ERROR,
      r"\b(?:mkfs(?:\.\w+)?\s+/dev/|dd\b[^\n]*\bof=/dev/(?:sd|nvme|vd|hd|disk)|"
      r"shred\b[^\n]*/dev/|:\(\)\s*\{\s*:\|:&\s*\};:)",
      "Disk wipe / fork bomb"),
    R("history-or-log-tamper", ERROR,
      r"\b(?:history\s+-c|unset\s+HISTFILE|export\s+HISTFILE=/dev/null|"
      r"rm\s+[^\n]*(?:\.bash_history|/var/log/))",
      "Shell history / log tampering"),
    R("ssh-authorized-keys-write", ERROR,
      r">>?\s*[\"']?(?:~|\$HOME|/root|/home/[^/\s]+)/\.ssh/authorized_keys",
      "Writes to authorized_keys (persistence)"),
    R("credential-exfil", ERROR,
      r"\b(?:curl|wget|nc)\b[^\n]*(?:~|\$HOME)/\.(?:ssh/id_|aws/credentials|kube/config|netrc|"
      r"config/gcloud|docker/config\.json)",
      "Credential file sent over the network"),
    R("env-exfil", ERROR,
      r"\b(?:env|printenv|set)\b\s*\|\s*(?:curl|wget|nc)\b|"
      r"\b(?:curl|wget)\b[^\n]*(?:-d|--data(?:-binary|-raw)?|-F)\s*[\"']?@?(?:/proc/self/environ|\$\(env\))",
      "Environment variables sent over the network"),
    R("chmod-world-writable", WARNING, r"\bchmod\s+(?:-R\s+)?0?777\b", "World-writable permissions"),
    R("tls-verify-disabled", WARNING,
      r"\bcurl\b[^\n]*\s(?:-k|--insecure)\b|\bverify\s*=\s*False\b|"
      r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*[\"']?0|validate_certs\s*[:=]\s*(?:false|no)\b|"
      r"GIT_SSL_NO_VERIFY",
      "TLS certificate verification disabled"),
    R("sudo-nopasswd", WARNING, r"NOPASSWD\s*:\s*ALL", "Passwordless sudo for everything"),

    # ---- agent / skill specific -----------------------------------------
    R("prompt-injection", ERROR,
      r"(?i)\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+)?(?:the\s+)?"
      r"(?:previous|prior|above|earlier|system|original)\s+(?:instructions|prompts?|rules|guidelines)\b|"
      r"\byou\s+are\s+no\s+longer\s+(?:bound|restricted)|"
      r"\bdo\s+not\s+(?:tell|inform|show|mention\s+(?:this\s+)?to)\s+the\s+user\b|"
      r"\bwithout\s+(?:telling|informing|asking)\s+the\s+user\b|"
      r"\bhide\s+(?:this|these|the)\s+(?:output|command|step)s?\s+from\s+the\s+user\b",
      "Prompt-injection / covert instruction phrase"),
    R("permission-bypass", ERROR,
      r"--dangerously-skip-permissions|\bdangerouslyDisableSandbox\b\s*[\"']?\s*[:=]\s*[\"']?true|"
      r"[\"']?defaultMode[\"']?\s*:\s*[\"']bypassPermissions|--permission-mode[ =]bypassPermissions|"
      r"[\"']Bash\(\*\)[\"']|[\"']Bash[\"']\s*\]",
      "Claude Code permission / sandbox bypass"),
    R("claude-config-tamper", ERROR,
      r"(?:>>?|\btee\b|\bcp\b|\bmv\b|\bsed\s+-i)[^\n]*(?:~|\$HOME|\$CLAUDE_HOME)/\.claude/"
      r"(?:settings(?:\.local)?\.json|CLAUDE\.md|hooks)|"
      r"(?:>>?|\btee\b)[^\n]*(?:~|\$HOME)/\.(?:bashrc|zshrc|profile|bash_profile|zprofile)\b",
      "Modifies Claude Code settings/hooks or shell startup files"),
]

# Hidden Unicode: zero-width, bidi controls (Trojan Source), tag chars (ASCII smuggling)
HIDDEN_UNICODE_RE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)

SENSITIVE_FILENAMES = [
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "*.pem", "*.key", "*.p12", "*.pfx",
    "*.jks", "*.keystore", "*.kdbx", "*.ppk", "*.ovpn", ".env", ".env.*", "*.env",
    "kubeconfig", "*.kubeconfig", ".netrc", "_netrc", "credentials", "credentials.*",
    ".git-credentials", "auth.json", "secrets.*", "*.tfstate", "*.tfvars",
    ".pgpass", ".htpasswd", "settings.local.json", "clouds.yaml", "secure.yaml",
    ".vault_pass*", "vault-password*", "*.asc", "*.gpg",
]
SENSITIVE_FILENAME_ALLOW = [".env.example", "*.example", "*.sample", "*.template"]

BINARY_ALLOW_GLOBS = ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.ico", "*.webp"]

# Quality rules only enforced on the current tree, not on history
HYGIENE_RULES = {"unexpected-executable", "skill-frontmatter", "skill-allowed-tools"}

SKILL_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)


# --------------------------------------------------------------------------
# allowlist
# --------------------------------------------------------------------------

@dataclass
class AllowEntry:
    rule: str
    path_glob: str
    regex: re.Pattern | None


def load_allowlist(path: str) -> list[AllowEntry]:
    entries: list[AllowEntry] = []
    if not path or not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 2)
            if len(parts) < 2:
                sys.exit(f"{path}:{n}: expected '<rule-id|*> <path-glob> [regex]'")
            regex = re.compile(parts[2]) if len(parts) == 3 else None
            entries.append(AllowEntry(parts[0], parts[1], regex))
    return entries


def is_allowed(allow: list[AllowEntry], rule: str, path: str, matched: str, line_text: str) -> bool:
    inline = re.search(r"security-check:\s*allow\s+([\w,\- ]+)", line_text)
    if inline and rule in re.split(r"[,\s]+", inline.group(1)):
        return True
    for e in allow:
        if e.rule not in ("*", rule):
            continue
        if not fnmatch.fnmatch(path, e.path_glob):
            continue
        if e.regex is None or e.regex.search(matched) or e.regex.search(line_text):
            return True
    return False


# --------------------------------------------------------------------------
# hashed denylist of internal identifiers
# --------------------------------------------------------------------------
# Org-specific identifiers (internal namespaces, key names, usernames...) cannot
# be caught by generic regexes, and listing them in clear text would leak them.
# denylist.sha256 holds sha256(lowercased token) per line; every word-ish token
# of every scanned line is hashed and compared.

import hashlib  # noqa: E402

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]")


def load_denylist(path: str) -> set[str]:
    hashes: set[str] = set()
    if not path or not os.path.exists(path):
        return hashes
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            h = raw.split("#", 1)[0].strip().lower()
            if re.fullmatch(r"[0-9a-f]{64}", h):
                hashes.add(h)
    return hashes


def _token_hashes(line: str):
    for tok in TOKEN_RE.findall(line):
        variants = {tok}
        variants.update(t for t in re.split(r"[._]", tok) if len(t) > 2)
        for v in variants:
            yield v, hashlib.sha256(v.lower().encode()).hexdigest()


DENY_HASHES: set[str] = set()


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------

def tracked_files(root: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", root, "ls-files", "-z"], check=True, capture_output=True
    ).stdout.decode()
    return [p for p in out.split("\0") if p]


def scan_file(root: str, path: str, allow: list[AllowEntry]) -> list[Finding]:
    findings: list[Finding] = []
    full = os.path.join(root, path)
    base = os.path.basename(path)

    def add(line, rule, sev, msg, matched="", line_text=""):
        if not is_allowed(allow, rule, path, matched, line_text):
            findings.append(Finding(path, line, rule, sev, msg))

    if os.path.islink(full):
        target = os.readlink(full)
        if os.path.isabs(target) or ".." in target.split("/"):
            add(1, "symlink-escape", ERROR, f"Symlink points outside the repo: {target}")
        return findings
    if not os.path.isfile(full):
        return findings

    # ---- filename / size / binary checks
    if any(fnmatch.fnmatch(base, g) for g in SENSITIVE_FILENAMES) and not any(
        fnmatch.fnmatch(base, g) for g in SENSITIVE_FILENAME_ALLOW
    ):
        add(1, "sensitive-filename", ERROR, f"Sensitive file committed: {base}", base)

    size = os.path.getsize(full)
    if size > MAX_FILE_BYTES:
        add(1, "large-file", ERROR, f"File is {size // 1024} KiB (> {MAX_FILE_BYTES // 1024} KiB)")
        return findings

    with open(full, "rb") as fh:
        data = fh.read()
    if b"\0" in data[:8192]:
        if not any(fnmatch.fnmatch(base, g) for g in BINARY_ALLOW_GLOBS):
            add(1, "binary-file", ERROR, "Binary file committed (cannot be reviewed)")
        return findings
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        add(1, "non-utf8", ERROR, "File is not valid UTF-8 text")
        return findings

    if os.access(full, os.X_OK) and not (text.startswith("#!") or path.endswith((".sh", ".py"))):
        add(1, "unexpected-executable", WARNING, "Executable bit set on a non-script file")

    lines = text.splitlines()
    for idx, line_text in enumerate(lines, 1):
        hidden = HIDDEN_UNICODE_RE.search(line_text)
        if hidden and not (idx == 1 and hidden.start() == 0 and hidden.group(0) == "\ufeff"):
            add(idx, "hidden-unicode", ERROR,
                f"Hidden/bidi Unicode character U+{ord(hidden.group(0)):04X}", "", line_text)

        if DENY_HASHES:
            for tok, h in _token_hashes(line_text):
                if h in DENY_HASHES:
                    add(idx, "denylisted-identifier", ERROR,
                        f"Internal identifier from denylist.sha256: {_redact(tok)}", tok, line_text)
                    break

        for rule in RULES:
            if rule.globs and not any(fnmatch.fnmatch(path, g) for g in rule.globs):
                continue
            for m in rule.pattern.finditer(line_text):
                if rule.validate and not rule.validate(m):
                    continue
                add(idx, rule.rule_id, rule.severity,
                    f"{rule.message}: {_redact(m.group(0))}", m.group(0), line_text)
                break  # one finding per rule per line is enough

    # ---- SKILL.md frontmatter
    if base == "SKILL.md":
        fm = SKILL_FRONTMATTER_RE.match(text)
        if not fm:
            add(1, "skill-frontmatter", ERROR, "SKILL.md must start with YAML frontmatter (---)")
        else:
            body = fm.group(1)
            for key in ("name", "description"):
                if not re.search(rf"(?m)^{key}\s*:\s*\S", body):
                    add(1, "skill-frontmatter", ERROR, f"SKILL.md frontmatter missing '{key}'")
            if re.search(r"(?mi)^allowed-tools\s*:.*\bBash\b(?!\()", body):
                add(1, "skill-allowed-tools", ERROR,
                    "SKILL.md grants unrestricted Bash via allowed-tools; scope it, e.g. Bash(git status:*)")

    return findings


def scan_commits(root: str, rev_range: str, allow: list[AllowEntry],
                 skip: set[str]) -> tuple[int, list[Finding]]:
    """Scan every file version added/modified by each commit in rev_range.

    Catches content that was committed and later removed inside the same PR:
    it is gone from the tree but would stay in history after a merge.
    """
    import tempfile

    shas = subprocess.run(["git", "-C", root, "rev-list", "--no-merges", rev_range],
                          check=True, capture_output=True, text=True).stdout.split()
    findings: dict[tuple, Finding] = {}
    scanned = 0
    for sha in shas:
        names = subprocess.run(
            ["git", "-C", root, "diff-tree", "--root", "--no-commit-id", "-r", "-z",
             "--diff-filter=AMR", "--name-only", sha],
            check=True, capture_output=True).stdout.decode().split("\0")
        for path in filter(None, names):
            if path in skip:
                continue
            blob = subprocess.run(["git", "-C", root, "show", f"{sha}:{path}"],
                                  capture_output=True)
            if blob.returncode != 0:
                continue  # e.g. submodule / symlink
            with tempfile.TemporaryDirectory() as tmp:
                full = os.path.join(tmp, path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as fh:
                    fh.write(blob.stdout)
                scanned += 1
                for f in scan_file(tmp, path, allow):
                    if f.rule in HYGIENE_RULES:  # tree-only checks, not leaks
                        continue
                    key = (f.path, f.rule, f.message)
                    if key not in findings:
                        f.message += f" (introduced in commit {sha[:10]})"
                        findings[key] = f
    return scanned, list(findings.values())


def emit(findings: list[Finding]) -> None:
    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    for f in sorted(findings, key=lambda f: (f.severity != ERROR, f.path, f.line)):
        if gha:
            msg = f.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::{f.severity} file={f.path},line={f.line},title={f.rule}::{msg}")
        else:
            print(f"{f.severity.upper():7} {f.path}:{f.line} [{f.rule}] {f.message}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        errors = [f for f in findings if f.severity == ERROR]
        warns = [f for f in findings if f.severity == WARNING]
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Content security check\n\n")
            fh.write(f"**{len(errors)} error(s), {len(warns)} warning(s)**\n\n")
            if findings:
                fh.write("| Severity | Location | Rule | Detail |\n|---|---|---|---|\n")
                for f in findings:
                    detail = f.message.replace("|", "\\|")
                    fh.write(f"| {f.severity} | `{f.path}:{f.line}` | `{f.rule}` | {detail} |\n")
            fh.write("\nSilence a false positive with `security-check: allow <rule>` on the line, "
                     "or an entry in `.github/security/allowlist.txt`.\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--allowlist", default=None)
    ap.add_argument("--denylist", default=None,
                    help="file of sha256(lowercased token) lines (default .github/security/denylist.sha256)")
    ap.add_argument("--hash", metavar="TOKEN", nargs="+",
                    help="print the denylist line for TOKEN(s) and exit")
    ap.add_argument("--commits", metavar="RANGE",
                    help="scan each file version changed by commits in RANGE (e.g. base..head) "
                         "instead of the working tree")
    ap.add_argument("paths", nargs="*", help="limit to these paths (default: all tracked files)")
    args = ap.parse_args()
    if args.hash:
        for tok in args.hash:
            print(hashlib.sha256(tok.lower().encode()).hexdigest())
        return 0

    root = os.path.abspath(args.root)
    allowlist = args.allowlist or os.path.join(root, ".github/security/allowlist.txt")
    allow = load_allowlist(allowlist)
    DENY_HASHES.update(load_denylist(args.denylist or os.path.join(
        root, ".github/security/denylist.sha256")))
    files = [] if args.commits else (args.paths or tracked_files(root))
    # never scan the scanner's own pattern definitions / allowlist
    self_rel = {".github/security/check_content.py", ".github/security/allowlist.txt",
                ".github/security/denylist.sha256"}

    findings: list[Finding] = []
    if args.commits:
        count, findings = scan_commits(root, args.commits, allow, self_rel)
        what = f"file version(s) in {args.commits}"
    else:
        for p in files:
            if p in self_rel:
                continue
            findings.extend(scan_file(root, p, allow))
        count, what = len(files), "file(s)"

    emit(findings)
    errors = sum(1 for f in findings if f.severity == ERROR)
    warns = len(findings) - errors
    print(f"\n{count} {what} scanned: {errors} error(s), {warns} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
