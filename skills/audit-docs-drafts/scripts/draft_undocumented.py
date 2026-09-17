#!/usr/bin/env python3
"""Collect code context for undocumented external mappings; write draft report skeleton.

Operator AsciiDoc prose is filled in by the agent (see SKILL.md). Read-only on
product repos, documentation repo, and mapping YAML.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("error: PyYAML required (pip install pyyaml)", file=sys.stderr)
    sys.exit(1)

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_SKILLS = _SCRIPTS_DIR.parent.parent
sys.path.insert(0, str(_REPO_SKILLS / "audit-docs" / "scripts"))
sys.path.insert(0, str(_REPO_SKILLS / "audit-docs-correctness" / "scripts"))

from audit_correctness import (  # noqa: E402
    CODE_REPO_KEY,
    CANONICAL_PRODUCT,
    IMPORT_PLAYBOOK_RE,
    PRODUCT_DISPLAY,
    PRODUCT_MAP,
    PRODUCT_ORDER,
    collect_default_vars,
    code_source_url,
    galaxy_fqcn,
    parse_module_documentation,
    read_text,
    resolve_code_files,
)
from audit_paths import check_code_path, expand, load_yaml  # noqa: E402

DOC_FRAGMENT_RE = re.compile(
    r"DOCUMENTATION\s*=\s*[rR]?\"\"\"(.*?)\"\"\"", re.DOTALL
)
ROLE_DIR_RE = re.compile(r"roles/([^/*]+)")
PLAYBOOK_FILE_RE = re.compile(r"playbooks/([^/*]+\.ya?ml)")
MODULE_FILE_RE = re.compile(r"plugins/modules/([^/*]+\.py)")


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def audit_docs_dir() -> Path:
    return skill_dir().parent / "audit-docs"


def resolve_products(product_arg: str) -> list[str]:
    if product_arg == "all":
        return list(PRODUCT_ORDER)
    canon = CANONICAL_PRODUCT.get(product_arg)
    if not canon:
        raise SystemExit(f"error: unknown product: {product_arg}")
    return [canon]


def pick_report_paths(reports_dir: Path, date_str: str) -> tuple[Path, Path]:
    base = f"doc-drafts-report-{date_str}"
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
    """Return product_key → set of eligible undocumented mapping ids."""
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
                if row.get("paths_ok") and row.get("status") == "undocumented":
                    ids.add(row["id"])
            eligible[key] = ids
        return eligible
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
        if row.get("paths_ok") and row.get("status") == "undocumented"
    }
    return {key: ids}


def mapping_paths_ok(code_repo: Path, mapping: dict) -> bool:
    for cp in mapping.get("code") or []:
        ok, _ = check_code_path(code_repo, str(cp))
        if not ok:
            return False
    return bool(mapping.get("code"))


def is_eligible_mapping(
    mapping: dict,
    code_repo: Path,
    eligible_ids: set[str] | None,
) -> bool:
    if mapping.get("doc") is not None:
        return False
    if mapping.get("audience") != "external":
        return False
    if mapping.get("kind") == "ci":
        return False
    if not mapping_paths_ok(code_repo, mapping):
        return False
    mid = mapping.get("id")
    if not mid:
        return False
    if eligible_ids is not None and mid not in eligible_ids:
        return False
    return True


def suggested_doc_path(mapping: dict, product_key: str) -> str:
    kind = mapping.get("kind") or "feature"
    code = list(mapping.get("code") or [])

    if kind == "role":
        for pattern in code:
            m = ROLE_DIR_RE.search(str(pattern).replace("/**", "/"))
            if m:
                return f"source/reference-role-{m.group(1)}.adoc"

    if kind == "module":
        for pattern in code:
            m = MODULE_FILE_RE.search(str(pattern))
            if m:
                return f"source/reference-module-{Path(m.group(1)).stem}.adoc"

    if kind == "playbook":
        for pattern in code:
            m = PLAYBOOK_FILE_RE.search(str(pattern))
            if m:
                return f"source/reference-playbook-{Path(m.group(1)).stem}.adoc"

    if product_key == "vmware":
        return "source/operator-vmware-guide.adoc"
    return "source/operator-walkthrough.adoc"


def primary_code_link(
    code_repo_url: str, code_patterns: list[str], files: list[Path], code_repo: Path
) -> tuple[str | None, str | None]:
    for path in files:
        rel = str(path.relative_to(code_repo)).replace("\\", "/")
        if rel.endswith((".yml", ".yaml", ".py", ".md")):
            return rel, code_source_url(code_repo_url, rel)
    for pattern in code_patterns:
        pat = str(pattern)
        if "/**" in pat:
            base = pat.split("/**")[0]
            return base, code_source_url(code_repo_url, base)
        if not any(ch in pat for ch in "*?["):
            return pat, code_source_url(code_repo_url, pat)
    return None, None


def build_code_urls(
    code_repo: Path,
    code_repo_url: str,
    files: list[Path],
    code_patterns: list[str],
    limit: int = 5,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for path in files:
        rel = str(path.relative_to(code_repo)).replace("\\", "/")
        url = code_source_url(code_repo_url, rel)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= limit:
            return urls
    if not urls:
        _, url = primary_code_link(code_repo_url, code_patterns, files, code_repo)
        if url:
            urls.append(url)
    return urls


def extract_playbook_context(
    code_repo: Path, files: list[Path], code_patterns: list[str]
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "fqcn": galaxy_fqcn(code_repo),
        "playbooks": [],
    }
    for path in files:
        rel = str(path.relative_to(code_repo)).replace("\\", "/")
        if not rel.startswith("playbooks/") or path.suffix not in (".yml", ".yaml"):
            continue
        text = read_text(path)
        entry: dict[str, Any] = {
            "path": rel,
            "imports": IMPORT_PLAYBOOK_RE.findall(text),
        }
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            data = None
        if isinstance(data, list) and data and isinstance(data[0], dict):
            play = data[0]
            entry["name"] = play.get("name")
            vars_block = play.get("vars")
            if isinstance(vars_block, dict):
                entry["vars"] = sorted(vars_block.keys())
        context["playbooks"].append(entry)
    if not context["playbooks"]:
        for pattern in code_patterns:
            pat = str(pattern)
            if pat.startswith("playbooks/"):
                context["playbooks"].append({"path": pat})
    return context


def extract_role_context(
    code_repo: Path, files: list[Path], code_patterns: list[str]
) -> dict[str, Any]:
    role_name: str | None = None
    for pattern in code_patterns:
        m = ROLE_DIR_RE.search(str(pattern).replace("/**", "/"))
        if m:
            role_name = m.group(1)
            break

    defaults = collect_default_vars(files)
    defaults_summary: dict[str, Any] = {}
    for key, (path, _) in list(defaults.items())[:40]:
        try:
            rel = str(path.relative_to(code_repo)).replace("\\", "/")
        except ValueError:
            rel = path.name
        defaults_summary[key] = rel

    task_files = sorted(
        {
            str(p.relative_to(code_repo)).replace("\\", "/")
            for p in files
            if "/tasks/" in str(p).replace("\\", "/") and p.suffix in (".yml", ".yaml")
        }
    )[:20]

    description: str | None = None
    for path in files:
        rel = str(path).replace("\\", "/")
        if rel.endswith("meta/main.yml") or rel.endswith("meta/main.yaml"):
            try:
                data = yaml.safe_load(read_text(path)) or {}
            except yaml.YAMLError:
                data = {}
            gi = data.get("galaxy_info") or {}
            if isinstance(gi, dict):
                description = gi.get("description")
            break

    readme_excerpt = ""
    for path in files:
        if path.name.lower() == "readme.md":
            readme_excerpt = read_text(path)[:800].strip()
            break

    return {
        "role_name": role_name,
        "defaults": defaults_summary,
        "task_files": task_files,
        "galaxy_info_description": description,
        "readme_excerpt": readme_excerpt,
    }


def extract_module_context(code_repo: Path, files: list[Path]) -> dict[str, Any]:
    modules: list[dict[str, Any]] = []
    for path in files:
        rel = str(path.relative_to(code_repo)).replace("\\", "/")
        if path.suffix != ".py" or "/modules/" not in rel:
            continue
        if path.name.startswith("_"):
            continue
        text = read_text(path)
        parsed = parse_module_documentation(text)
        short_desc: str | None = None
        fragment = DOC_FRAGMENT_RE.search(text)
        if fragment:
            try:
                doc_data = yaml.safe_load(fragment.group(1)) or {}
                short_desc = doc_data.get("short_description")
            except yaml.YAMLError:
                pass
        options_summary: dict[str, Any] = {}
        for name, spec in (parsed.get("options") or {}).items():
            if isinstance(spec, dict):
                entry: dict[str, Any] = {"required": bool(spec.get("required"))}
                if "default" in spec:
                    entry["default"] = spec.get("default")
                options_summary[name] = entry
        modules.append(
            {
                "module": path.stem,
                "path": rel,
                "short_description": short_desc,
                "required_options": parsed.get("required") or [],
                "options": options_summary,
            }
        )
    return {"modules": modules}


def extract_feature_context(
    code_repo: Path,
    files: list[Path],
    code_patterns: list[str],
    mapping: dict,
) -> dict[str, Any]:
    has_role = any("roles/" in str(p) for p in code_patterns)
    has_playbook = any(str(p).startswith("playbooks/") for p in code_patterns)
    has_module = any("plugins/modules/" in str(p) for p in code_patterns)

    context: dict[str, Any] = {"notes": mapping.get("notes")}
    if has_role:
        context["role"] = extract_role_context(code_repo, files, code_patterns)
    if has_playbook:
        context["playbook"] = extract_playbook_context(
            code_repo, files, code_patterns
        )
    if has_module:
        context["module"] = extract_module_context(code_repo, files)
    if not (has_role or has_playbook or has_module):
        context["file_count"] = len(files)
        context["sample_paths"] = sorted(
            str(p.relative_to(code_repo)).replace("\\", "/") for p in files[:15]
        )
    return context


def collect_code_context(
    code_repo: Path,
    mapping: dict,
    files: list[Path],
) -> dict[str, Any]:
    kind = mapping.get("kind") or "feature"
    code_patterns = list(mapping.get("code") or [])
    if kind == "playbook":
        return extract_playbook_context(code_repo, files, code_patterns)
    if kind == "role":
        return extract_role_context(code_repo, files, code_patterns)
    if kind == "module":
        return extract_module_context(code_repo, files)
    return extract_feature_context(code_repo, files, code_patterns, mapping)


def build_draft_row(
    mapping: dict,
    code_repo: Path,
    code_repo_url: str,
    product_key: str,
) -> dict[str, Any]:
    code_patterns = list(mapping.get("code") or [])
    files = resolve_code_files(code_repo, code_patterns)
    primary_rel, primary_url = primary_code_link(
        code_repo_url, code_patterns, files, code_repo
    )
    return {
        "id": mapping["id"],
        "kind": mapping.get("kind") or "feature",
        "code": code_patterns,
        "notes": mapping.get("notes"),
        "suggested_doc_path": suggested_doc_path(mapping, product_key),
        "code_context": collect_code_context(code_repo, mapping, files),
        "code_primary": primary_rel,
        "code_primary_url": primary_url,
        "code_urls": build_code_urls(code_repo, code_repo_url, files, code_patterns),
        "draft_adoc": None,
        "draft_status": "pending",
    }


def draft_product(
    product: str,
    config_dir: Path,
    repos: dict,
    mapping_id: str | None,
    eligible_ids: set[str] | None,
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
    drafts: list[dict[str, Any]] = []

    for mapping in all_mappings:
        if mapping_id and mapping.get("id") != mapping_id:
            continue
        if not is_eligible_mapping(mapping, code_repo, eligible_ids):
            continue
        drafts.append(build_draft_row(mapping, code_repo, code_repo_url, product))

    return {
        "product": map_data.get("product") or PRODUCT_DISPLAY[product],
        "product_key": product,
        "code_repo_path": str(code_repo),
        "code_repo_url": code_repo_url,
        "summary": {"draft_count": len(drafts)},
        "drafts": drafts,
    }


def write_markdown(path: Path, report: dict) -> None:
    lines = [
        f"# Documentation drafts ({report['draft_id']})",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This run did not modify the documentation repo or mapping YAML.",
        "",
        "## Overall summary",
        "",
        f"- Drafts: {report['summary']['draft_count']}",
        "",
    ]

    for block in report.get("products") or []:
        product = block["product"]
        count = block["summary"]["draft_count"]
        lines.extend(
            [
                f"## {product}",
                "",
                f"Checked: {count} undocumented external mapping(s)",
                "",
                "### Draft entries",
                "",
            ]
        )
        if not block.get("drafts"):
            lines.extend(["_No eligible undocumented external mappings._", ""])
            continue

        for draft in block["drafts"]:
            lines.append(f"#### {draft['id']}")
            lines.append("")
            lines.append(f"Suggested file: `{draft['suggested_doc_path']}`")
            if draft.get("code_primary_url"):
                label = draft.get("code_primary") or "code"
                lines.append(f"Code: [{label}]({draft['code_primary_url']})")
            if draft.get("notes"):
                lines.append(f"Mapping notes: {draft['notes']}")
            lines.append("")
            adoc = draft.get("draft_adoc")
            if adoc:
                lines.extend(["```adoc", adoc.rstrip(), "```", ""])
            else:
                lines.extend(["_Pending agent draft_", "", ""])

    source = report.get("source_report")
    if source:
        next_audit = f"reports/{Path(source).name}"
    else:
        next_audit = "reports/audit-report-{YYYY-MM-DD}.json"
    lines.extend(
        [
            "## Next step",
            "",
            "After human writes docs and updates `doc:` in code-to-docs YAML:",
            f"`/audit-docs` then `/audit-docs-correctness {next_audit}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect context for undocumented external mappings (draft report)"
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
            if a in PRODUCT_MAP:
                continue
            mapping_id = a
        else:
            raise SystemExit(f"error: unrecognized argument: {a}")

    if mapping_id and product == "all":
        if mapping_id.startswith("vmk-"):
            product = "vmware"
        elif mapping_id.startswith("osm-"):
            product = "os-migrate"

    return argparse.Namespace(product=product, report=report_path, id=mapping_id)


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
    eligible = load_audit_report_filter(args.report)

    products = resolve_products(args.product)
    blocks: list[dict[str, Any]] = []
    for product in products:
        ids = None
        if eligible is not None:
            ids = eligible.get(product, set())
        blocks.append(
            draft_product(
                product,
                config_dir,
                repos,
                mapping_id=args.id,
                eligible_ids=ids,
            )
        )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    json_path, md_path = pick_report_paths(reports_dir, today)
    product_tag = "all" if len(products) > 1 else products[0]

    overall_count = sum(b["summary"]["draft_count"] for b in blocks)
    report: dict[str, Any] = {
        "draft_id": f"{today}-{product_tag}",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_report": str(args.report) if args.report else None,
        "summary": {"draft_count": overall_count},
        "products": blocks,
    }
    if len(blocks) == 1:
        report["drafts"] = blocks[0]["drafts"]

    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, report)

    print(f"DRAFTS_JSON={json_path}")
    print(f"DRAFTS_MD={md_path}")
    print(f"SUMMARY draft_count={overall_count}")
    for b in blocks:
        print(f"DRAFTS {b['product_key']} count={b['summary']['draft_count']}")
        for d in b["drafts"]:
            print(f"DRAFT {d['id']}|{d['kind']}|{d['draft_status']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
