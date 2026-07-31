#!/usr/bin/env python3
"""Mechanical doc↔code correctness audit for mapped rows.

Mirrors audit-docs path audit: deterministic checks by mapping ``kind``,
writes JSON + Markdown under skills/audit-docs/reports/. Read-only on
product and documentation clones.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("error: PyYAML required (pip install pyyaml)", file=sys.stderr)
    sys.exit(1)

PRODUCT_ORDER = ("vmware", "os-migrate")

PRODUCT_MAP = {
    "vmware": "code-to-docs.vmware.yaml",
    "vmk": "code-to-docs.vmware.yaml",
    "os-migrate": "code-to-docs.os-migrate.yaml",
    "osm": "code-to-docs.os-migrate.yaml",
    "all": None,
}

CODE_REPO_KEY = {
    "vmware": "vmware-migration-kit",
    "vmk": "vmware-migration-kit",
    "os-migrate": "os-migrate",
    "osm": "os-migrate",
}

CANONICAL_PRODUCT = {
    "vmware": "vmware",
    "vmk": "vmware",
    "os-migrate": "os-migrate",
    "osm": "os-migrate",
}

PRODUCT_DISPLAY = {
    "vmware": "vmware-migration-kit",
    "os-migrate": "os-migrate",
}

# Common prose / false-positive tokens (not treated as Ansible vars).
DOC_VAR_DENYLIST = frozenset(
    {
        "source_path",
        "example_com",
        "user_name",
        "file_name",
        "host_name",
        "project_name",
        "true_false",
        "left_right",
        "before_after",
        "read_only",
        "write_only",
        "line_number",
        "pull_request",
        "workflow_dispatch",
        "github_actions",
        "ansible_galaxy",
        "openstack_sdk",
        "short_description",
        "version_added",
        "required_false",
        "required_true",
    }
)

SNAKE_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")
BACKTICK_RE = re.compile(r"`([a-z][a-z0-9_]{3,})`")
YAML_KEY_RE = re.compile(r"(?m)^[ \t]*([a-z][a-z0-9_]{3,})\s*:")
FQCN_RE = re.compile(r"\b([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\b")
IMPORT_PLAYBOOK_RE = re.compile(
    r"import_playbook\s*:\s*[\"']?([^\"'\s#]+)[\"']?", re.IGNORECASE
)
DOC_FRAGMENT_RE = re.compile(
    r"DOCUMENTATION\s*=\s*[rR]?\"\"\"(.*?)\"\"\"", re.DOTALL
)
ANSIBLEAUTOPLUGIN_RE = re.compile(r"\[ansibleautoplugin\]", re.IGNORECASE)
WORKFLOW_NAME_RE = re.compile(
    r"\b([a-zA-Z0-9_-]+\.ya?ml)\b"
)


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def audit_docs_dir() -> Path:
    return skill_dir().parent / "audit-docs"


def expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_products(product_arg: str) -> list[str]:
    if product_arg == "all":
        return list(PRODUCT_ORDER)
    canon = CANONICAL_PRODUCT.get(product_arg)
    if not canon:
        raise SystemExit(f"error: unknown product: {product_arg}")
    return [canon]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def line_of(text: str, needle: str) -> int | None:
    idx = text.find(needle)
    if idx < 0:
        return None
    return text.count("\n", 0, idx) + 1


def first_line_of_any(text: str, needles: list[str]) -> int | None:
    best: int | None = None
    for n in needles:
        ln = line_of(text, n)
        if ln is not None and (best is None or ln < best):
            best = ln
    return best


def doc_source_url(docs_repo_url: str, doc: str | None, line: int | None = None) -> str | None:
    if not doc or not docs_repo_url:
        return None
    base = docs_repo_url.rstrip("/")
    url = f"{base}/blob/main/{doc}"
    if line:
        url += f"#L{line}"
    return url


def code_source_url(
    code_repo_url: str, code_path: str | None, line: int | None = None
) -> str | None:
    if not code_path or not code_repo_url:
        return None
    base = code_repo_url.rstrip("/")
    rel = code_path.replace("\\", "/")
    if any(ch in rel for ch in "*?[") or rel.endswith("/"):
        tree = rel.split("/**")[0].rstrip("/")
        return f"{base}/tree/main/{tree}"
    url = f"{base}/blob/main/{rel}"
    if line:
        url += f"#L{line}"
    return url


def resolve_code_files(code_repo: Path, patterns: list[str]) -> list[Path]:
    """Expand mapping code: entries to concrete files (capped for large trees)."""
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            matches = sorted(Path(p) for p in glob.glob(str(code_repo / pattern), recursive=True))
            if not matches and "/**" in pattern:
                base = code_repo / pattern.split("/**")[0]
                if base.is_dir():
                    matches = sorted(p for p in base.rglob("*") if p.is_file())
            for m in matches:
                if not m.is_file():
                    continue
                # Skip bulky / generated trees
                rel = str(m.relative_to(code_repo)).replace("\\", "/")
                if any(
                    part in rel
                    for part in (
                        "/__pycache__/",
                        "/.git/",
                        "/node_modules/",
                        "/.venv/",
                        "/aee/context/",
                    )
                ):
                    continue
                if m not in seen:
                    seen.add(m)
                    files.append(m)
        else:
            full = code_repo / pattern
            if full.is_file() and full not in seen:
                seen.add(full)
                files.append(full)
            elif full.is_dir():
                for m in sorted(full.rglob("*")):
                    if m.is_file() and m not in seen:
                        seen.add(m)
                        files.append(m)
    # Prefer defaults / yaml / yml / py first for searches; keep full list for existence
    return files


def collect_default_vars(files: list[Path]) -> dict[str, tuple[Path, int]]:
    """Map variable name → (file, line) from role defaults and top-level YAML keys."""
    found: dict[str, tuple[Path, int]] = {}
    for path in files:
        name = path.name
        rel = str(path).replace("\\", "/")
        if not (
            name.endswith((".yml", ".yaml"))
            and (
                "/defaults/" in rel
                or name in ("vars.yaml", "vars.yml", "defaults.yml", "defaults.yaml")
            )
        ):
            # Also accept role defaults/main.yml already covered; skip playbooks here
            if "/defaults/" not in rel:
                continue
        text = read_text(path)
        if not text.strip():
            continue
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            data = None
        if isinstance(data, dict):
            for key in data:
                if isinstance(key, str) and SNAKE_RE.fullmatch(key):
                    ln = line_of(text, f"{key}:") or 1
                    found.setdefault(key, (path, ln))
        # Fallback: line-oriented keys if YAML parse failed or nested
        for m in YAML_KEY_RE.finditer(text):
            key = m.group(1)
            if key not in found and "_" in key:
                ln = text.count("\n", 0, m.start()) + 1
                found[key] = (path, ln)
    return found


def role_prefixes(code_patterns: list[str]) -> set[str]:
    prefixes: set[str] = set()
    for p in code_patterns:
        m = re.match(r"roles/([^/]+)", p.replace("\\", "/"))
        if m:
            prefixes.add(m.group(1) + "_")
    return prefixes


def extract_doc_var_candidates(doc_text: str) -> dict[str, int]:
    """Return snake_case names cited in examples / backticks → first line."""
    hits: dict[str, int] = {}

    def add(name: str, pos: int) -> None:
        if "_" not in name or name in DOC_VAR_DENYLIST or len(name) < 5:
            return
        if name not in hits:
            hits[name] = doc_text.count("\n", 0, pos) + 1

    for m in BACKTICK_RE.finditer(doc_text):
        add(m.group(1), m.start())
    for m in YAML_KEY_RE.finditer(doc_text):
        add(m.group(1), m.start())
    for m in re.finditer(r"\+([a-z][a-z0-9_]{4,})\+", doc_text):
        add(m.group(1), m.start())
    return hits


def parse_module_documentation(py_text: str) -> dict[str, Any]:
    """Parse Ansible DOCUMENTATION fragment; return options dict and required names."""
    m = DOC_FRAGMENT_RE.search(py_text)
    if not m:
        return {"options": {}, "required": []}
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {"options": {}, "required": []}
    options = data.get("options") or {}
    if not isinstance(options, dict):
        options = {}
    required = [
        name
        for name, spec in options.items()
        if isinstance(spec, dict) and spec.get("required") is True
    ]
    return {"options": options, "required": required}


def galaxy_fqcn(code_repo: Path) -> str | None:
    galaxy = code_repo / "galaxy.yml"
    if not galaxy.is_file():
        return None
    data = load_yaml(galaxy) or {}
    ns = data.get("namespace")
    name = data.get("name")
    if ns and name:
        return f"{ns}.{name}"
    return None


def pick_report_paths(reports_dir: Path, date_str: str) -> tuple[Path, Path]:
    base = f"correctness-report-{date_str}"
    suffix = ""
    n = 1
    while True:
        json_path = reports_dir / f"{base}{suffix}.json"
        if not json_path.exists():
            md_path = reports_dir / f"{base}{suffix}.md"
            return json_path, md_path
        n += 1
        suffix = f"-{n}"


def load_audit_report_filter(path: Path | None) -> dict[str, set[str]] | None:
    """Return product_key → set of eligible mapping ids, or None if no report."""
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    eligible: dict[str, set[str]] = {}
    products = data.get("products")
    if products:
        for block in products:
            key = block.get("product_key") or ""
            ids: set[str] = set()
            for row in block.get("mappings") or []:
                if row.get("paths_ok") and row.get("status") == "mapped":
                    ids.add(row["id"])
            eligible[key] = ids
        return eligible
    # Single-product legacy shape
    key = data.get("product_key")
    if not key:
        product = data.get("product") or ""
        if "vmware" in product:
            key = "vmware"
        elif "os-migrate" in product or product == "os-migrate":
            key = "os-migrate"
        else:
            key = "vmware"
    ids = {
        row["id"]
        for row in data.get("mappings") or []
        if row.get("paths_ok") and row.get("status") == "mapped"
    }
    return {key: ids}


def classify(findings_issues: list[str], findings_warnings: list[str]) -> str:
    if findings_issues:
        return "issues"
    if findings_warnings:
        return "warnings"
    return "ok"


def check_playbook(
    code_repo: Path,
    doc_text: str,
    doc_name: str,
    code_patterns: list[str],
    files: list[Path],
) -> tuple[list[str], list[str], list[tuple[str, int | None]], list[tuple[str, int | None]]]:
    issues: list[str] = []
    warnings: list[str] = []
    doc_cites: list[tuple[str, int | None]] = []
    code_cites: list[tuple[str, int | None]] = []

    fqcn = galaxy_fqcn(code_repo)
    if fqcn:
        if fqcn not in doc_text:
            # Wrong FQCN variants
            wrong = re.findall(
                rf"\b{re.escape(fqcn.split('.')[0])}\.[a-z][a-z0-9_]*\b", doc_text
            )
            wrong = [w for w in wrong if w != fqcn]
            if wrong:
                w = wrong[0]
                ln = line_of(doc_text, w)
                issues.append(
                    f"{doc_name} line {ln}: '{w}' | galaxy.yml FQCN is {fqcn}"
                )
                doc_cites.append((w, ln))
                code_cites.append(("galaxy.yml", 1))
            else:
                warnings.append(
                    f"{doc_name}: collection FQCN '{fqcn}' not mentioned in doc"
                )
                doc_cites.append((doc_name, None))

    # import_playbook targets for mapped playbook files
    for path in files:
        if path.suffix not in (".yml", ".yaml"):
            continue
        rel_posix = str(path.relative_to(code_repo)).replace("\\", "/")
        if not rel_posix.startswith("playbooks/"):
            continue
        text = read_text(path)
        for m in IMPORT_PLAYBOOK_RE.finditer(text):
            target = m.group(1)
            target_path = (path.parent / target).resolve()
            alt = code_repo / "playbooks" / Path(target).name
            if not target_path.is_file() and not alt.is_file():
                ln = text.count("\n", 0, m.start()) + 1
                issues.append(
                    f"{rel_posix} line {ln}: import_playbook '{target}' not found"
                )
                code_cites.append((rel_posix, ln))

    # Mapped playbook path should be referenced somehow in doc when kind is playbook
    for pat in code_patterns:
        if not pat.startswith("playbooks/"):
            continue
        base = Path(pat).name
        stem = Path(base).stem
        if base not in doc_text and stem not in doc_text:
            warnings.append(
                f"{doc_name}: playbook '{base}' not referenced by name in doc"
            )

    return issues, warnings, doc_cites, code_cites


def check_role_or_feature(
    code_repo: Path,
    doc_text: str,
    doc_name: str,
    code_patterns: list[str],
    files: list[Path],
) -> tuple[list[str], list[str], list[tuple[str, int | None]], list[tuple[str, int | None]]]:
    issues: list[str] = []
    warnings: list[str] = []
    doc_cites: list[tuple[str, int | None]] = []
    code_cites: list[tuple[str, int | None]] = []

    defaults = collect_default_vars(files)
    prefixes = role_prefixes(code_patterns)
    for key in defaults:
        if "_" in key:
            prefixes.add(key.split("_", 1)[0] + "_")

    code_blob_parts: list[str] = []
    for path in files:
        if path.suffix in (".yml", ".yaml", ".md", ".py", ".txt", ".j2"):
            code_blob_parts.append(read_text(path))
    code_blob = "\n".join(code_blob_parts)
    code_var_names = set(defaults) | {
        m.group(0) for m in SNAKE_RE.finditer(code_blob) if "_" in m.group(0)
    }

    # Short forms of defaults (strip role prefix) for doc coverage checks
    short_forms: dict[str, str] = {}
    for key in defaults:
        for pref in prefixes:
            if key.startswith(pref) and len(key) > len(pref):
                short_forms[key] = key[len(pref) :]
                break

    doc_vars = extract_doc_var_candidates(doc_text)
    # Prefer yaml-key style citations for fuzzy stale-name detection
    yaml_keys = {m.group(1) for m in YAML_KEY_RE.finditer(doc_text)}

    def closest_default(name: str) -> str | None:
        best: tuple[float, str] | None = None
        for d in defaults:
            ratio = SequenceMatcher(None, name, d).ratio()
            short = short_forms.get(d, d)
            ratio2 = SequenceMatcher(None, name, short).ratio()
            score = max(ratio, ratio2)
            if best is None or score > best[0]:
                best = (score, d)
        if best and best[0] >= 0.72:
            return best[1]
        return None

    for name, ln in sorted(doc_vars.items(), key=lambda x: x[1]):
        if "_" not in name:
            continue
        if name in code_var_names or name in code_blob:
            continue

        scoped = bool(prefixes) and any(name.startswith(p) for p in prefixes)
        fuzzy = closest_default(name) if name in yaml_keys or name in doc_vars else None
        # Fuzzy only when it looks like a renamed default (yaml key or backtick)
        use_fuzzy = fuzzy is not None and (
            name in yaml_keys or f"`{name}`" in doc_text or f"+{name}+" in doc_text
        )

        if not scoped and not use_fuzzy:
            continue

        detail = (
            f"no match in mapped code (defaults / related files)"
            if not use_fuzzy
            else f"no match in mapped code; closest default is '{fuzzy}'"
        )
        issues.append(f"{doc_name} line {ln}: '{name}' | {detail}")
        doc_cites.append((name, ln))
        if fuzzy and fuzzy in defaults:
            p, pln = defaults[fuzzy]
            try:
                rel = str(p.relative_to(code_repo))
            except ValueError:
                rel = str(p)
            code_cites.append((rel, pln))
        elif defaults:
            p, pln = next(iter(defaults.values()))
            try:
                rel = str(p.relative_to(code_repo))
            except ValueError:
                rel = str(p)
            code_cites.append((rel, pln))

    # Defaults present in code but missing from doc → warning (allow short form)
    warn_count = 0
    for name, (path, pln) in sorted(defaults.items()):
        if name.startswith("_"):
            continue
        short = short_forms.get(name)
        if name in doc_text or (short and short in doc_text):
            continue
        if warn_count >= 8:
            break
        try:
            rel = str(path.relative_to(code_repo))
        except ValueError:
            rel = str(path)
        warnings.append(
            f"{rel} line {pln}: default '{name}' not mentioned in {doc_name}"
        )
        code_cites.append((rel, pln))
        warn_count += 1

    fqcn = galaxy_fqcn(code_repo)
    if fqcn:
        wrong_hits = [
            w
            for w in FQCN_RE.findall(doc_text)
            if f"{w[0]}.{w[1]}" != fqcn
            and w[0] == fqcn.split(".")[0]
            and "os_migration" in w[1]
        ]
        for ns, nm in wrong_hits:
            wrong = f"{ns}.{nm}"
            ln = line_of(doc_text, wrong)
            issues.append(
                f"{doc_name} line {ln}: '{wrong}' | galaxy.yml FQCN is {fqcn}"
            )
            doc_cites.append((wrong, ln))
            code_cites.append(("galaxy.yml", 1))

    return issues, warnings, doc_cites, code_cites


def check_module(
    code_repo: Path,
    doc_text: str,
    doc_name: str,
    files: list[Path],
) -> tuple[list[str], list[str], list[tuple[str, int | None]], list[tuple[str, int | None]]]:
    issues: list[str] = []
    warnings: list[str] = []
    doc_cites: list[tuple[str, int | None]] = []
    code_cites: list[tuple[str, int | None]] = []

    # ansibleautoplugin stubs pull options from code at build time — skip option diffs
    if ANSIBLEAUTOPLUGIN_RE.search(doc_text) and ":documentation:" in doc_text.lower():
        # Still verify :module: path if present
        mod_ref = re.search(r":module:\s*(\S+)", doc_text)
        if mod_ref:
            ref = mod_ref.group(1).lstrip("/")
            # Compare basename to mapped .py files
            mapped_py = [p for p in files if p.suffix == ".py"]
            if mapped_py:
                basenames = {p.name for p in mapped_py}
                ref_base = Path(ref).name
                if ref_base not in basenames and not any(
                    str(p).endswith(ref) or ref.endswith(p.name) for p in mapped_py
                ):
                    ln = line_of(doc_text, mod_ref.group(0))
                    issues.append(
                        f"{doc_name} line {ln}: :module: '{ref}' does not match "
                        f"mapped module file(s) {sorted(basenames)}"
                    )
                    doc_cites.append((ref, ln))
        return issues, warnings, doc_cites, code_cites

    for path in files:
        if path.suffix != ".py":
            continue
        # Skip golang wrappers / non-ansible modules without DOCUMENTATION
        text = read_text(path)
        if "DOCUMENTATION" not in text:
            continue
        parsed = parse_module_documentation(text)
        options = parsed["options"]
        required = parsed["required"]
        try:
            rel = str(path.relative_to(code_repo))
        except ValueError:
            rel = str(path)

        for opt in required:
            if opt not in doc_text:
                warnings.append(
                    f"{rel}: required option '{opt}' not mentioned in {doc_name}"
                )
                # approximate line of option in DOCUMENTATION
                ln = line_of(text, f"{opt}:") or line_of(text, "DOCUMENTATION")
                code_cites.append((rel, ln))

        doc_vars = extract_doc_var_candidates(doc_text)
        option_names = set(options)
        for name, ln in sorted(doc_vars.items(), key=lambda x: x[1]):
            # Only flag names that look like module options discussed near this module
            if name in option_names:
                continue
            # Heuristic: option-like and appears as yaml key; skip if in code file elsewhere
            if name in text:
                continue
            if name.endswith(("_info", "_path", "_name", "_id", "_type")) or name in doc_vars:
                # Only issue if the doc key is used as a parameter-looking yaml key
                # and module has options (so we're in a real reference page)
                if not option_names:
                    continue
                # Avoid flagging unrelated guide vars on multi-topic pages: require
                # the module stem to appear in the doc near the var — skip if module
                # name not in doc at all beyond stubs... for dedicated module pages OK
                stem = path.stem
                if stem not in doc_text and Path(doc_name).stem.find(stem) < 0:
                    continue
                # Don't issue for every random snake_case — only if it's a yaml key
                # already required by extract; further require similarity to an option
                if not any(
                    name.split("_")[0] == opt.split("_")[0] for opt in option_names
                ):
                    continue
                issues.append(
                    f"{doc_name} line {ln}: option-like '{name}' | not in {rel} DOCUMENTATION options"
                )
                doc_cites.append((name, ln))
                code_cites.append((rel, line_of(text, "options:") or 1))

    return issues, warnings, doc_cites, code_cites


def check_ci(
    code_repo: Path,
    doc_text: str,
    doc_name: str,
    files: list[Path],
) -> tuple[list[str], list[str], list[tuple[str, int | None]], list[tuple[str, int | None]]]:
    issues: list[str] = []
    warnings: list[str] = []
    doc_cites: list[tuple[str, int | None]] = []
    code_cites: list[tuple[str, int | None]] = []

    workflow_files = {
        p.name: p
        for p in files
        if "/.github/workflows/" in str(p).replace("\\", "/")
        or p.parent.name == "workflows"
    }
    # Also list all workflows if mapping includes the directory
    wf_dir = code_repo / ".github" / "workflows"
    if wf_dir.is_dir():
        for p in wf_dir.iterdir():
            if p.is_file() and p.suffix in (".yml", ".yaml"):
                workflow_files.setdefault(p.name, p)

    mentioned = []
    for m in WORKFLOW_NAME_RE.finditer(doc_text):
        name = m.group(1)
        if name.endswith((".yml", ".yaml")):
            mentioned.append((name, doc_text.count("\n", 0, m.start()) + 1))

    for name, ln in mentioned:
        if name not in workflow_files:
            # Only flag if it looks like a GH workflow reference
            if "workflow" in doc_text.lower() or ".github" in doc_text:
                issues.append(
                    f"{doc_name} line {ln}: workflow '{name}' not found under .github/workflows/"
                )
                doc_cites.append((name, ln))

    if workflow_files and mentioned:
        mentioned_names = {n for n, _ in mentioned}
        missing_docs = sorted(set(workflow_files) - mentioned_names)
        if missing_docs:
            warnings.append(
                f"{doc_name}: workflows present but not listed: {', '.join(missing_docs)}"
            )
            p = workflow_files[missing_docs[0]]
            try:
                rel = str(p.relative_to(code_repo))
            except ValueError:
                rel = str(p)
            code_cites.append((rel, 1))

    return issues, warnings, doc_cites, code_cites


def audit_mapping_row(
    code_repo: Path,
    docs_repo: Path,
    mapping: dict,
    *,
    docs_repo_url: str,
    code_repo_url: str,
) -> dict[str, Any] | None:
    doc = mapping.get("doc")
    if doc is None:
        return None

    doc_path = docs_repo / doc
    if not doc_path.is_file():
        return {
            "id": mapping["id"],
            "correctness": "issues",
            "doc": doc,
            "doc_url": doc_source_url(docs_repo_url, doc),
            "code": (mapping.get("code") or [None])[0],
            "code_url": code_source_url(
                code_repo_url, (mapping.get("code") or [None])[0]
            ),
            "findings": [f"doc file missing: {doc_path}"],
            "suggested_fix": f"Restore or fix doc path for mapping {mapping['id']}.",
        }

    code_patterns = list(mapping.get("code") or [])
    files = resolve_code_files(code_repo, code_patterns)
    if not files and code_patterns:
        return {
            "id": mapping["id"],
            "correctness": "issues",
            "doc": doc,
            "doc_url": doc_source_url(docs_repo_url, doc),
            "code": code_patterns[0],
            "code_url": code_source_url(code_repo_url, code_patterns[0]),
            "findings": [f"no files matched code: {code_patterns}"],
            "suggested_fix": "Fix code paths in the mapping YAML (read-only note for humans).",
        }

    doc_text = read_text(doc_path)
    doc_name = Path(doc).name
    kind = (mapping.get("kind") or "feature").lower()

    issues: list[str] = []
    warnings: list[str] = []
    doc_cites: list[tuple[str, int | None]] = []
    code_cites: list[tuple[str, int | None]] = []

    if kind == "playbook":
        i, w, dc, cc = check_playbook(
            code_repo, doc_text, doc_name, code_patterns, files
        )
    elif kind == "module":
        i, w, dc, cc = check_module(code_repo, doc_text, doc_name, files)
    elif kind == "ci":
        i, w, dc, cc = check_ci(code_repo, doc_text, doc_name, files)
    else:
        # role, feature, internal, or unknown → role/feature checks
        i, w, dc, cc = check_role_or_feature(
            code_repo, doc_text, doc_name, code_patterns, files
        )

    issues.extend(i)
    warnings.extend(w)
    doc_cites.extend(dc)
    code_cites.extend(cc)

    correctness = classify(issues, warnings)
    findings = issues + warnings

    doc_line = None
    for _, ln in doc_cites:
        if ln is not None:
            doc_line = ln
            break
    if doc_line is None and findings:
        # try to parse "line N" from first finding
        m = re.search(r" line (\d+)", findings[0])
        if m:
            doc_line = int(m.group(1))

    code_rel = None
    code_line = None
    for rel, ln in code_cites:
        code_rel = rel
        code_line = ln
        break
    if code_rel is None and code_patterns:
        code_rel = code_patterns[0]
        # Prefer a concrete file when pattern is a glob
        if files and any(ch in code_rel for ch in "*?["):
            try:
                code_rel = str(files[0].relative_to(code_repo))
            except ValueError:
                code_rel = str(files[0])

    row: dict[str, Any] = {
        "id": mapping["id"],
        "correctness": correctness,
        "kind": kind,
        "doc": doc,
        "doc_url": doc_source_url(
            docs_repo_url, doc, doc_line if correctness != "ok" else None
        ),
        "code": code_rel,
        "code_url": code_source_url(
            code_repo_url, code_rel, code_line if correctness != "ok" else None
        ),
        "findings": findings,
    }
    if correctness != "ok":
        if doc_line is not None:
            row["doc_line"] = doc_line
        if code_line is not None:
            row["code_line"] = code_line
        if issues:
            row["suggested_fix"] = (
                "Update the documentation so names/paths match the mapped code "
                f"(see findings for {mapping['id']})."
            )
        else:
            row["suggested_fix"] = (
                "Consider documenting the missing code defaults/options listed in findings."
            )
    return row


def audit_product(
    product: str,
    config_dir: Path,
    repos: dict,
    docs_repo: Path,
    docs_repo_url: str,
    *,
    mapping_id: str | None = None,
    eligible_ids: set[str] | None = None,
) -> dict[str, Any]:
    map_file = config_dir / PRODUCT_MAP[product]
    if not map_file.is_file():
        raise SystemExit(f"error: mapping file not found: {map_file}")
    map_data = load_yaml(map_file) or {}

    code_key = CODE_REPO_KEY[product]
    code_repo = expand(repos["code_repos"][code_key]["local_path"])
    if not code_repo.is_dir():
        raise SystemExit(f"error: code repo not found: {code_repo}")
    code_repo_url = (repos.get("code_repos") or {}).get(code_key, {}).get("url") or ""

    all_mappings = map_data.get("mappings") or []
    rows: list[dict[str, Any]] = []

    for m in all_mappings:
        mid = m.get("id")
        if mapping_id and mid != mapping_id:
            continue
        if m.get("doc") is None:
            continue
        if eligible_ids is not None and mid not in eligible_ids:
            continue
        # Verify paths exist (lightweight; skill 1 is authoritative when report given)
        doc_ok = (docs_repo / m["doc"]).is_file()
        if not doc_ok:
            continue
        code_ok = True
        for cp in m.get("code") or []:
            if any(ch in cp for ch in "*?["):
                if not glob.glob(str(code_repo / cp), recursive=True):
                    if "/**" in cp:
                        if not (code_repo / cp.split("/**")[0]).is_dir():
                            code_ok = False
                            break
                    else:
                        code_ok = False
                        break
            elif not (code_repo / cp).exists():
                code_ok = False
                break
        if not code_ok:
            continue

        row = audit_mapping_row(
            code_repo,
            docs_repo,
            m,
            docs_repo_url=docs_repo_url,
            code_repo_url=code_repo_url,
        )
        if row:
            rows.append(row)

    # Sort: issues, warnings, ok
    order = {"issues": 0, "warnings": 1, "ok": 2}
    rows.sort(key=lambda r: (order.get(r["correctness"], 9), r["id"]))

    summary = {
        "checked": len(rows),
        "ok": sum(1 for r in rows if r["correctness"] == "ok"),
        "warnings": sum(1 for r in rows if r["correctness"] == "warnings"),
        "issues": sum(1 for r in rows if r["correctness"] == "issues"),
    }
    return {
        "product": map_data.get("product") or PRODUCT_DISPLAY[product],
        "product_key": product,
        "code_repo_path": str(code_repo),
        "code_repo_url": code_repo_url,
        "summary": summary,
        "rows": rows,
    }


def md_link(label: str, url: str | None) -> str:
    if url:
        return f"[{label}]({url})"
    return label


def write_markdown(path: Path, report: dict) -> None:
    products = report.get("products") or []
    multi = len(products) > 1
    overall = report.get("summary") or {}
    generated = report.get("generated_at", "")

    if multi:
        lines = [
            f"# Correctness report ({generated[:10] or 'unknown'})",
            "",
            "Source: combined (vmware-migration-kit, then os-migrate)",
            f"Overall: **ok={overall.get('ok', 0)}**, "
            f"**warnings={overall.get('warnings', 0)}**, "
            f"**issues={overall.get('issues', 0)}**",
            "",
            "Method: mechanical script (`audit_correctness.py`). "
            "This run did not modify any repository.",
            "",
        ]
    else:
        product = (products[0].get("product") if products else "") or "product"
        lines = [
            f"# Correctness report — {product} ({generated[:10] or 'unknown'})",
            "",
            f"Overall: **ok={overall.get('ok', 0)}**, "
            f"**warnings={overall.get('warnings', 0)}**, "
            f"**issues={overall.get('issues', 0)}**",
            "",
            "Method: mechanical script (`audit_correctness.py`). "
            "This run did not modify any repository.",
            "",
        ]

    for block in products:
        if multi:
            lines.extend([f"## {block['product']}", ""])
        s = block["summary"]
        lines.extend(
            [
                f"Checked: {s['checked']} mapped rows",
                f"Summary: **ok={s['ok']}**, **warnings={s['warnings']}**, "
                f"**issues={s['issues']}**",
                "",
                "### Results",
                "",
            ]
        )
        for row in block["rows"]:
            lines.append(f"#### {row['id']}: {row['correctness']}")
            lines.append("")
            doc = row.get("doc") or ""
            doc_base = Path(doc).name
            if row.get("doc_line"):
                doc_label = f"{doc_base}:{row['doc_line']}"
            else:
                doc_label = doc_base
            code = row.get("code") or ""
            code_base = Path(str(code).rstrip("/")).name or str(code)
            if str(code).endswith("/**") or "*" in str(code):
                code_label = str(code)
            elif row.get("code_line"):
                code_label = f"{code_base}:{row['code_line']}"
            else:
                code_label = code_base if code_base else str(code)

            lines.append(f"Doc: {md_link(doc_label, row.get('doc_url'))}")
            lines.append(f"Code: {md_link(code_label, row.get('code_url'))}")
            lines.append("")
            findings = row.get("findings") or []
            if findings:
                if len(findings) == 1:
                    lines.append(f"Findings: {findings[0]}")
                else:
                    lines.append("Findings:")
                    for f in findings:
                        lines.append(f"- {f}")
                lines.append("")
            else:
                lines.append("Findings: none (mechanical checks passed)")
                lines.append("")
            if row.get("suggested_fix"):
                lines.append(f"Suggested fix: {row['suggested_fix']}")
                lines.append("")

        issue_ids = [r["id"] for r in block["rows"] if r["correctness"] == "issues"]
        warn_ids = [r["id"] for r in block["rows"] if r["correctness"] == "warnings"]
        if issue_ids:
            lines.extend(["### Issues (priority)", "", ", ".join(issue_ids), ""])
        if warn_ids:
            lines.extend(["### Warnings", "", ", ".join(warn_ids), ""])

    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mechanical doc↔code correctness audit for mapped rows"
    )
    parser.add_argument(
        "args",
        nargs="*",
        help="Optional: product (all|vmware|os-migrate), audit report.json, mapping id",
    )
    ns = parser.parse_args(argv)

    product = "all"
    report_path: Path | None = None
    mapping_id: str | None = None

    for a in ns.args:
        if a in PRODUCT_MAP:
            product = a
        elif a.endswith(".json"):
            report_path = Path(os.path.expanduser(a))
            if not report_path.is_file():
                # try relative to audit-docs/
                alt = audit_docs_dir() / a
                if alt.is_file():
                    report_path = alt
                else:
                    alt2 = audit_docs_dir() / "reports" / Path(a).name
                    if alt2.is_file():
                        report_path = alt2
                    else:
                        raise SystemExit(f"error: report not found: {a}")
        elif a.startswith("vmk-") or a.startswith("osm-") or mapping_id is None:
            # treat as mapping id (allow after product)
            if a in PRODUCT_MAP:
                continue
            mapping_id = a
        else:
            raise SystemExit(f"error: unrecognized argument: {a}")

    # Infer product from id when product still all
    if mapping_id and product == "all":
        if mapping_id.startswith("vmk-"):
            product = "vmware"
        elif mapping_id.startswith("osm-"):
            product = "os-migrate"

    return argparse.Namespace(
        product=product, report=report_path, id=mapping_id
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    config_dir = audit_docs_dir() / "config"
    reports_dir = audit_docs_dir() / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    repos_file = config_dir / "repos.yaml"
    if not repos_file.is_file():
        print(f"error: missing {repos_file}", file=sys.stderr)
        return 1

    repos = load_yaml(repos_file)
    docs_repo = expand(repos["docs_repo"]["local_path"])
    docs_repo_url = (repos.get("docs_repo") or {}).get("url") or ""
    if not docs_repo.is_dir():
        print(f"error: docs repo not found: {docs_repo}", file=sys.stderr)
        return 1

    eligible = load_audit_report_filter(args.report)

    products = resolve_products(args.product)
    blocks: list[dict[str, Any]] = []
    for product in products:
        ids = None
        if eligible is not None:
            ids = eligible.get(product, set())
        blocks.append(
            audit_product(
                product,
                config_dir,
                repos,
                docs_repo,
                docs_repo_url,
                mapping_id=args.id,
                eligible_ids=ids,
            )
        )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    json_path, md_path = pick_report_paths(reports_dir, today)

    overall = {
        "checked": sum(b["summary"]["checked"] for b in blocks),
        "ok": sum(b["summary"]["ok"] for b in blocks),
        "warnings": sum(b["summary"]["warnings"] for b in blocks),
        "issues": sum(b["summary"]["issues"] for b in blocks),
    }

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "mechanical",
        "source_report": str(args.report) if args.report else None,
        "summary": overall,
        "products": blocks,
    }
    if len(blocks) == 1:
        report["rows"] = blocks[0]["rows"]

    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, report)

    print(f"CORRECTNESS_JSON={json_path}")
    print(f"CORRECTNESS_MD={md_path}")
    print(
        f"SUMMARY checked={overall['checked']} ok={overall['ok']} "
        f"warnings={overall['warnings']} issues={overall['issues']}"
    )
    for b in blocks:
        s = b["summary"]
        print(
            f"PRODUCT {b['product']} checked={s['checked']} ok={s['ok']} "
            f"warnings={s['warnings']} issues={s['issues']}"
        )
        for r in b["rows"]:
            print(f"ROW {r['id']}|{r['correctness']}|findings={len(r.get('findings') or [])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
