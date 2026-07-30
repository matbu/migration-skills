#!/usr/bin/env python3
"""Path audit for code-to-docs mappings. Writes JSON + Markdown reports."""

from __future__ import annotations

import argparse
import fnmatch
import glob
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

# Canonical product order for combined reports: VMware kit first, then os-migrate.
PRODUCT_ORDER = ("vmware", "os-migrate")

PRODUCT_MAP = {
    "vmware": "code-to-docs.vmware.yaml",
    "vmk": "code-to-docs.vmware.yaml",
    "os-migrate": "code-to-docs.os-migrate.yaml",
    "osm": "code-to-docs.os-migrate.yaml",
    "all": None,  # both products in PRODUCT_ORDER
}

CODE_REPO_KEY = {
    "vmware": "vmware-migration-kit",
    "vmk": "vmware-migration-kit",
    "os-migrate": "os-migrate",
    "osm": "os-migrate",
}

ID_PREFIX = {
    "vmware": "vmk",
    "vmk": "vmk",
    "os-migrate": "osm",
    "osm": "osm",
}

# Normalize aliases to a canonical key used in PRODUCT_ORDER.
CANONICAL_PRODUCT = {
    "vmware": "vmware",
    "vmk": "vmware",
    "os-migrate": "os-migrate",
    "osm": "os-migrate",
}

# Notable code units scanned for mapping coverage (relative to code repo).
CODE_INVENTORY_GLOBS = (
    "playbooks/*.yml",
    "roles/*/",
    "plugins/modules/*.py",
    ".github/workflows/*",
    "aee/",
    "doc/",
    "scripts/",
    "tests/",
    "meta/",
)

# Skip noisy or non-product paths when suggesting new mappings.
CODE_SUGGEST_SKIP_PREFIXES = (
    "plugins/modules/__pycache__/",
)

# Doc filename / content hints per product (for unmapped-doc suggestions).
DOC_FILENAME_HINTS = {
    "vmware": re.compile(
        r"(vmware|migrator-host|performance-expectations|golang-module|github-actions|aee)",
        re.IGNORECASE,
    ),
    "os-migrate": re.compile(
        r"(walkthrough|variables-guide|migration-parameters|install-from|usage-notes|"
        r"troubleshooting|upgrade|conversion-host-guide|reference-|modules-index|"
        r"operator-overview|process-summary|glossary|developer-design|developer-dev-env|"
        r"developer-contributing|developer-releasing)",
        re.IGNORECASE,
    ),
}

DOC_CONTENT_HINTS = {
    "vmware": re.compile(
        r"vmware[_-]migration[_-]kit|os_migrate\.vmware_migration_kit|VMware Migration Kit",
        re.IGNORECASE,
    ),
    "os-migrate": re.compile(
        r"os_migrate\.os_migrate|OpenStack to OpenStack|parallel cloud migration|"
        r"os-migrate walkthrough|export_workloads|import_workloads",
        re.IGNORECASE,
    ),
}

# Filenames that belong to the other product — skip when inventing docs.
DOC_EXCLUDE_FOR_PRODUCT = {
    "os-migrate": re.compile(r"vmware|golang-module", re.IGNORECASE),
    "vmware": re.compile(
        r"(walkthrough|variables-guide|migration-parameters|reference-module|"
        r"reference-role|modules-index)",
        re.IGNORECASE,
    ),
}

DOC_LABEL = {
    "vmware": "VMK-related",
    "os-migrate": "os-migrate-related",
}


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_products(product_arg: str) -> list[str]:
    """Return canonical product keys in report order."""
    if product_arg == "all":
        return list(PRODUCT_ORDER)
    canon = CANONICAL_PRODUCT.get(product_arg)
    if not canon:
        raise SystemExit(f"error: unknown product: {product_arg}")
    return [canon]


def check_code_path(code_repo: Path, code_path: str) -> tuple[bool, str | None]:
    # Glob patterns (*, **, ?, []) — including single-star file globs.
    if any(ch in code_path for ch in "*?["):
        pattern = str(code_repo / code_path)
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return True, None
        if "/**" in code_path:
            base = code_path.split("/**")[0]
            base_full = code_repo / base
            if not base_full.is_dir():
                return False, str(base_full)
        return False, pattern
    full = code_repo / code_path
    if full.is_file():
        return True, None
    return False, str(full)


def doc_source_url(docs_repo_url: str, doc: str | None) -> str | None:
    """GitHub blob URL for a documentation source file."""
    if not doc or not docs_repo_url:
        return None
    base = docs_repo_url.rstrip("/")
    return f"{base}/blob/main/{doc}"


def audit_mapping(
    code_repo: Path,
    docs_repo: Path,
    mapping: dict,
    docs_repo_url: str = "",
) -> dict:
    broken_paths: list[str] = []
    code_ok = True
    for cp in mapping.get("code") or []:
        ok, broken = check_code_path(code_repo, cp)
        if not ok:
            code_ok = False
            if broken:
                broken_paths.append(broken)

    doc = mapping.get("doc")
    doc_exists = False
    if doc is not None:
        doc_full = docs_repo / doc
        doc_exists = doc_full.is_file()
        if not doc_exists:
            broken_paths.append(str(doc_full))

    if not code_ok:
        status = "broken"
    elif doc is None:
        status = mapping.get("status") or "undocumented"
    elif doc_exists and code_ok:
        status = "mapped"
    else:
        status = "broken"

    paths_ok = code_ok and (doc is None or doc_exists)
    doc_url = doc_source_url(docs_repo_url, doc) if doc_exists else None

    row: dict[str, Any] = {
        "id": mapping["id"],
        "paths_ok": paths_ok,
        "code_ok": code_ok,
        "doc": doc,
        "doc_exists": doc_exists,
        "status": status,
        "broken_paths": broken_paths,
    }
    if doc_url:
        row["doc_url"] = doc_url
    return row


def normalize_rel(path: str) -> str:
    return path.replace("\\", "/").rstrip("/")


def path_covered_by_pattern(rel_path: str, pattern: str) -> bool:
    """Return True if inventory path is covered by a mapping code: entry."""
    rel = normalize_rel(rel_path)
    pat = normalize_rel(pattern)

    if "**" in pat:
        base = pat.split("/**", 1)[0]
        return rel == base or rel.startswith(base + "/")

    if "*" in pat or "?" in pat or "[" in pat:
        return fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel + "/", pat)

    if rel == pat:
        return True
    if rel.startswith(pat.rstrip("/") + "/"):
        return True
    if pat.startswith(rel.rstrip("/") + "/"):
        return True
    return False


def is_code_covered(rel_path: str, code_patterns: list[str]) -> bool:
    return any(path_covered_by_pattern(rel_path, p) for p in code_patterns)


def invent_code_units(code_repo: Path) -> list[str]:
    """Collect notable relative code paths for coverage suggestions."""
    found: set[str] = set()
    for pattern in CODE_INVENTORY_GLOBS:
        if pattern.endswith("/"):
            base = pattern.rstrip("/")
            if "*" in base:
                parent, name_pat = base.rsplit("/", 1) if "/" in base else ("", base)
                search_root = code_repo / parent if parent else code_repo
                if not search_root.is_dir():
                    continue
                for child in search_root.iterdir():
                    if child.is_dir() and fnmatch.fnmatch(child.name, name_pat):
                        rel = normalize_rel(str(child.relative_to(code_repo)))
                        found.add(rel + "/")
            else:
                d = code_repo / base
                if d.is_dir():
                    found.add(normalize_rel(base) + "/")
        else:
            for match in sorted(code_repo.glob(pattern)):
                if match.is_file():
                    found.add(normalize_rel(str(match.relative_to(code_repo))))
    return sorted(
        p
        for p in found
        if not any(p.startswith(skip) for skip in CODE_SUGGEST_SKIP_PREFIXES)
    )


def invent_product_docs(docs_repo: Path, product: str) -> list[dict[str, Any]]:
    """Find documentation pages that appear related to the given product."""
    source = docs_repo / "source"
    if not source.is_dir():
        return []

    filename_re = DOC_FILENAME_HINTS[product]
    content_re = DOC_CONTENT_HINTS[product]
    exclude_re = DOC_EXCLUDE_FOR_PRODUCT.get(product)

    results: list[dict[str, Any]] = []
    for path in sorted(source.glob("*.adoc")):
        if exclude_re and exclude_re.search(path.name):
            continue
        rel = normalize_rel(str(path.relative_to(docs_repo)))
        reasons: list[str] = []
        if filename_re.search(path.name):
            reasons.append("filename hint")
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if text and content_re.search(text):
            reasons.append(f"mentions {DOC_LABEL[product]} in content")
        if reasons:
            results.append({"doc": rel, "reasons": reasons})
    return results


def find_doc_mentions(
    docs_repo: Path,
    needles: list[str],
    mapped_docs: set[str],
    product: str,
) -> list[str]:
    """Return mapped/known doc paths that mention any needle."""
    cleaned = [n for n in needles if n and len(n) >= 3]
    if not cleaned:
        return []
    source = docs_repo / "source"
    if not source.is_dir():
        return []
    hits: list[str] = []
    candidates = set(mapped_docs)
    filename_re = DOC_FILENAME_HINTS[product]
    exclude_re = DOC_EXCLUDE_FOR_PRODUCT.get(product)
    for p in source.glob("*.adoc"):
        if exclude_re and exclude_re.search(p.name):
            continue
        if filename_re.search(p.name):
            candidates.add(normalize_rel(str(p.relative_to(docs_repo))))
    patterns = [re.compile(re.escape(n), re.IGNORECASE) for n in cleaned]
    for rel in sorted(candidates):
        full = docs_repo / rel
        if not full.is_file():
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(p.search(text) for p in patterns):
            hits.append(rel)
    return hits


def mention_needles_for_code(unit: str) -> list[str]:
    """Build search terms for linking unmapped code to docs."""
    rel = normalize_rel(unit).rstrip("/")
    basename = Path(rel).name
    stem = Path(basename).stem if "." in basename else basename
    needles: list[str] = []
    generic_dirs = {
        "meta",
        "tests",
        "scripts",
        "doc",
        "aee",
        "roles",
        "playbooks",
        "plugins",
    }
    if unit.endswith("/") or "/" not in rel:
        needles.append(rel + "/")
        if stem not in generic_dirs:
            needles.append(rel)
            needles.append(stem)
    else:
        needles.append(basename)
        needles.append(stem)
        if "_" in stem:
            needles.append(stem.replace("_", "-"))
    seen: set[str] = set()
    out: list[str] = []
    for n in needles:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def suggest_mapping_id(code_path: str, prefix: str = "vmk") -> str:
    rel = normalize_rel(code_path).rstrip("/")
    stem = Path(rel).stem if "." in Path(rel).name else Path(rel).name
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return f"{prefix}-{slug}"


def discover_unmapped(
    code_repo: Path,
    docs_repo: Path,
    mappings: list[dict],
    product: str,
    docs_repo_url: str = "",
) -> dict[str, Any]:
    """Cross-reference repos against mapping YAML; suggest entries to add."""
    prefix = ID_PREFIX[product]
    label = DOC_LABEL[product]
    code_patterns: list[str] = []
    mapped_docs: set[str] = set()
    for m in mappings:
        for cp in m.get("code") or []:
            code_patterns.append(str(cp))
        doc = m.get("doc")
        if doc:
            mapped_docs.add(normalize_rel(doc))

    unmapped_code: list[dict[str, Any]] = []
    for unit in invent_code_units(code_repo):
        if is_code_covered(unit, code_patterns):
            continue
        doc_hits = find_doc_mentions(
            docs_repo, mention_needles_for_code(unit), mapped_docs, product
        )
        kind = "feature"
        if unit.startswith("playbooks/"):
            kind = "playbook"
        elif unit.startswith("roles/"):
            kind = "role"
        elif unit.startswith("plugins/modules/"):
            kind = "module"
        elif unit.startswith(".github/workflows/"):
            kind = "ci"
        suggestion: dict[str, Any] = {
            "code": [unit.rstrip("/") + ("/**" if unit.endswith("/") else "")],
            "suggested_id": suggest_mapping_id(unit, prefix=prefix),
            "kind": kind,
            "reason": "code path not listed in any mapping",
            "doc_mentions": doc_hits,
            "suggested_doc": doc_hits[0] if doc_hits else None,
        }
        unmapped_code.append(suggestion)

    unmapped_docs: list[dict[str, Any]] = []
    for item in invent_product_docs(docs_repo, product):
        doc = item["doc"]
        if doc in mapped_docs:
            continue
        unmapped_docs.append(
            {
                "doc": doc,
                "doc_url": doc_source_url(docs_repo_url, doc),
                "reasons": item["reasons"],
                "reason": f"{label} doc not used as doc: in any mapping",
                "suggested_id": suggest_mapping_id(Path(doc).stem, prefix=prefix),
            }
        )

    return {
        "unmapped_code": unmapped_code,
        "unmapped_docs": unmapped_docs,
        "summary": {
            "unmapped_code": len(unmapped_code),
            "unmapped_docs": len(unmapped_docs),
        },
    }


def pick_report_paths(reports_dir: Path, date_str: str) -> tuple[Path, Path]:
    base = f"audit-report-{date_str}"
    suffix = ""
    n = 1
    while True:
        json_path = reports_dir / f"{base}{suffix}.json"
        if not json_path.exists():
            md_path = reports_dir / f"{base}{suffix}.md"
            return json_path, md_path
        n += 1
        suffix = f"-{n}"


def audit_product(
    product: str,
    config_dir: Path,
    repos: dict,
    docs_repo: Path,
    docs_repo_url: str,
    mapping_id: str | None = None,
) -> dict[str, Any]:
    """Run path audit for one product; return a product report block."""
    map_file = config_dir / PRODUCT_MAP[product]
    if not map_file.is_file():
        raise SystemExit(f"error: mapping file not found: {map_file}")
    map_data = load_yaml(map_file) or {}

    code_key = CODE_REPO_KEY[product]
    code_repo = expand(repos["code_repos"][code_key]["local_path"])
    if not code_repo.is_dir():
        raise SystemExit(f"error: code repo not found: {code_repo}")

    all_mappings = map_data.get("mappings") or []
    mappings = all_mappings
    if mapping_id:
        mappings = [m for m in all_mappings if m.get("id") == mapping_id]
        if not mappings:
            raise SystemExit(f"error: mapping id not found: {mapping_id}")

    results = [
        audit_mapping(code_repo, docs_repo, m, docs_repo_url=docs_repo_url)
        for m in mappings
    ]
    summary = {
        "total": len(results),
        "mapped": sum(1 for r in results if r["status"] == "mapped"),
        "undocumented": sum(1 for r in results if r["status"] == "undocumented"),
        "broken": sum(1 for r in results if r["status"] == "broken"),
    }
    mapping_suggestions = discover_unmapped(
        code_repo,
        docs_repo,
        all_mappings,
        product=product,
        docs_repo_url=docs_repo_url,
    )

    return {
        "product": map_data.get("product") or code_key,
        "product_key": product,
        "code_repo_path": str(code_repo),
        "code_repo_url": (repos.get("code_repos") or {}).get(code_key, {}).get("url")
        or "",
        "summary": summary,
        "mappings": results,
        "mapping_suggestions": mapping_suggestions,
    }


def append_product_markdown(lines: list[str], block: dict, *, heading_level: int = 2) -> None:
    """Append one product's Summary / Mappings / suggestions in the existing format."""
    product = block["product"]
    summary = block["summary"]
    h = "#" * heading_level
    h3 = "#" * (heading_level + 1)

    lines.extend(
        [
            f"{h} {product}",
            "",
            f"{h3} Summary",
            "",
            f"- Total mappings: {summary['total']}",
            f"- Mapped: {summary['mapped']}",
            f"- Undocumented: {summary['undocumented']}",
            f"- Broken: {summary['broken']}",
            "",
            f"{h3} Mappings",
            "",
            "| id | paths OK | doc | status |",
            "|----|----------|-----|--------|",
        ]
    )
    for r in block["mappings"]:
        paths = "yes" if r["paths_ok"] else "no"
        if r["doc_exists"]:
            doc_col = "exists"
        elif r["doc"] is None:
            doc_col = "null"
        else:
            doc_col = "missing"
        status = r["status"]
        if status == "mapped" and r.get("doc_url"):
            status = f"[mapped]({r['doc_url']})"
        lines.append(f"| {r['id']} | {paths} | {doc_col} | {status} |")

    if summary["broken"] > 0:
        lines.extend(["", f"{h3} Broken paths", ""])
        for r in block["mappings"]:
            if r["broken_paths"]:
                lines.append(f"#### {r['id']}" if heading_level == 2 else f"### {r['id']}")
                for bp in r["broken_paths"]:
                    lines.append(f"- `{bp}`")

    suggestions = block.get("mapping_suggestions") or {}
    unmapped_code = suggestions.get("unmapped_code") or []
    unmapped_docs = suggestions.get("unmapped_docs") or []
    sug_summary = suggestions.get("summary") or {}
    label = DOC_LABEL.get(block.get("product_key") or "", "product-related")

    lines.extend(
        [
            "",
            f"{h3} Mapping suggestions (not in code-to-docs YAML)",
            "",
            "Cross-referenced the code and docs repos against the mapping file. "
            "Items below are **not established** in the YAML and may be worth adding.",
            "",
            f"- Unmapped code units: {sug_summary.get('unmapped_code', len(unmapped_code))}",
            f"- Unmapped {label} docs: {sug_summary.get('unmapped_docs', len(unmapped_docs))}",
            "",
        ]
    )

    if unmapped_code:
        lines.extend(
            [
                "#### Unmapped code (consider adding)"
                if heading_level == 2
                else "### Unmapped code (consider adding)",
                "",
                "| suggested id | code | kind | docs that mention it |",
                "|--------------|------|------|----------------------|",
            ]
        )
        for item in unmapped_code:
            code_col = ", ".join(f"`{c}`" for c in item.get("code") or [])
            docs = item.get("doc_mentions") or []
            if docs:
                doc_col = ", ".join(f"`{d}`" for d in docs)
            else:
                doc_col = "— (no doc hit; may stay `doc: null`)"
            lines.append(
                f"| {item.get('suggested_id', '')} | {code_col} | "
                f"{item.get('kind', '')} | {doc_col} |"
            )
        lines.append("")
    else:
        sub = "####" if heading_level == 2 else "###"
        lines.extend(
            [f"{sub} Unmapped code", "", "_None — all inventoried units are covered._", ""]
        )

    if unmapped_docs:
        sub = "####" if heading_level == 2 else "###"
        lines.extend(
            [
                f"{sub} Unmapped docs (consider linking)",
                "",
                "| suggested id | doc | why |",
                "|--------------|-----|-----|",
            ]
        )
        for item in unmapped_docs:
            doc = item.get("doc") or ""
            url = item.get("doc_url")
            doc_cell = f"[`{doc}`]({url})" if url else f"`{doc}`"
            why = ", ".join(item.get("reasons") or [item.get("reason") or ""])
            lines.append(f"| {item.get('suggested_id', '')} | {doc_cell} | {why} |")
        lines.append("")
    else:
        sub = "####" if heading_level == 2 else "###"
        lines.extend(
            [
                f"{sub} Unmapped docs",
                "",
                f"_None — {label} docs are already mapped._",
                "",
            ]
        )


def write_markdown(path: Path, report: dict, rel_json: str) -> None:
    products = report.get("products") or []
    multi = len(products) > 1

    if multi:
        lines = [
            f"# Audit report ({report['audit_id']})",
            "",
            f"Generated: {report['generated_at']}",
            "",
            "Products in order: **vmware-migration-kit**, then **os-migrate**.",
            "",
        ]
        overall = report.get("summary") or {}
        if overall:
            lines.extend(
                [
                    "## Overall summary",
                    "",
                    f"- Total mappings: {overall.get('total', 0)}",
                    f"- Mapped: {overall.get('mapped', 0)}",
                    f"- Undocumented: {overall.get('undocumented', 0)}",
                    f"- Broken: {overall.get('broken', 0)}",
                    "",
                ]
            )
        for block in products:
            append_product_markdown(lines, block, heading_level=2)
        next_cmd = f"Next: /audit-docs-correctness {rel_json}"
    else:
        block = products[0] if products else report
        # Single-product title matches the previous format.
        product_name = block.get("product") or report.get("product")
        lines = [
            f"# Audit report — {product_name} ({report['audit_id']})",
            "",
            f"Generated: {report['generated_at']}",
            "",
        ]
        # Reuse append helper but at root style (## Summary) via a thin shim:
        # For single product keep ## Summary not ## product / ### Summary.
        summary = block["summary"]
        lines.extend(
            [
                "## Summary",
                "",
                f"- Total mappings: {summary['total']}",
                f"- Mapped: {summary['mapped']}",
                f"- Undocumented: {summary['undocumented']}",
                f"- Broken: {summary['broken']}",
                "",
                "## Mappings",
                "",
                "| id | paths OK | doc | status |",
                "|----|----------|-----|--------|",
            ]
        )
        for r in block["mappings"]:
            paths = "yes" if r["paths_ok"] else "no"
            if r["doc_exists"]:
                doc_col = "exists"
            elif r["doc"] is None:
                doc_col = "null"
            else:
                doc_col = "missing"
            status = r["status"]
            if status == "mapped" and r.get("doc_url"):
                status = f"[mapped]({r['doc_url']})"
            lines.append(f"| {r['id']} | {paths} | {doc_col} | {status} |")

        if summary["broken"] > 0:
            lines.extend(["", "## Broken paths", ""])
            for r in block["mappings"]:
                if r["broken_paths"]:
                    lines.append(f"### {r['id']}")
                    for bp in r["broken_paths"]:
                        lines.append(f"- `{bp}`")

        # Suggestions section via helper at heading_level that yields ### under empty —
        # call with a temp list then rewrite first heading... simpler to call append
        # with heading_level=1 so ## Summary would conflict. Just duplicate suggestions
        # by calling append after clearing product heading: use heading_level=1 and
        # strip the product title line.
        sug_lines: list[str] = []
        append_product_markdown(sug_lines, block, heading_level=1)
        # Drop "# product" and blank, keep from "## Summary" — but we already wrote
        # Summary/Mappings. Keep only from "## Mapping suggestions".
        start = 0
        for i, line in enumerate(sug_lines):
            if line.startswith("## Mapping suggestions"):
                start = i
                break
        lines.extend([""] + sug_lines[start:])

        product_key = block.get("product_key") or "vmware"
        next_cmd = f"Next: /audit-docs-correctness {product_key} {rel_json}"

    lines.extend(["## Next step", "", next_cmd, ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit code-to-docs path mappings")
    parser.add_argument(
        "product",
        nargs="?",
        default="all",
        choices=sorted(PRODUCT_MAP.keys()),
        help="vmware | os-migrate | all (default: all — VMware then os-migrate)",
    )
    parser.add_argument("id", nargs="?", help="optional mapping id filter")
    args = parser.parse_args()

    if args.id and args.product == "all":
        # Infer product from id prefix when possible.
        if args.id.startswith("vmk-"):
            args.product = "vmware"
        elif args.id.startswith("osm-"):
            args.product = "os-migrate"
        else:
            print(
                "error: mapping id filter requires a product "
                "(vmware or os-migrate), or an id prefixed with vmk-/osm-",
                file=sys.stderr,
            )
            return 1

    root = skill_dir()
    config_dir = root / "config"
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    repos = load_yaml(config_dir / "repos.yaml")
    docs_repo = expand(repos["docs_repo"]["local_path"])
    docs_repo_url = (repos.get("docs_repo") or {}).get("url") or ""

    if not docs_repo.is_dir():
        print(f"error: docs repo not found: {docs_repo}", file=sys.stderr)
        return 1

    products = resolve_products(args.product)
    blocks: list[dict[str, Any]] = []
    for product in products:
        blocks.append(
            audit_product(
                product,
                config_dir,
                repos,
                docs_repo,
                docs_repo_url,
                mapping_id=args.id,
            )
        )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    json_path, md_path = pick_report_paths(reports_dir, today)
    rel_json = f"reports/{json_path.name}"

    overall = {
        "total": sum(b["summary"]["total"] for b in blocks),
        "mapped": sum(b["summary"]["mapped"] for b in blocks),
        "undocumented": sum(b["summary"]["undocumented"] for b in blocks),
        "broken": sum(b["summary"]["broken"] for b in blocks),
    }

    product_tag = "all" if len(products) > 1 else products[0]
    report: dict[str, Any] = {
        "audit_id": f"{today}-{product_tag}",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "docs_repo_path": str(docs_repo),
        "docs_repo_url": docs_repo_url,
        "summary": overall,
        "products": blocks,
    }

    # Backward-compatible top-level fields when a single product is audited.
    if len(blocks) == 1:
        b = blocks[0]
        report["product"] = b["product"]
        report["code_repo_path"] = b["code_repo_path"]
        report["mappings"] = b["mappings"]
        report["mapping_suggestions"] = b["mapping_suggestions"]

    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, report, rel_json)

    print(f"AUDIT_JSON={json_path}")
    print(f"AUDIT_MD={md_path}")
    print(
        f"SUMMARY total={overall['total']} mapped={overall['mapped']} "
        f"undocumented={overall['undocumented']} broken={overall['broken']}"
    )
    for b in blocks:
        s = b["summary"]
        print(
            f"PRODUCT {b['product']} total={s['total']} mapped={s['mapped']} "
            f"undocumented={s['undocumented']} broken={s['broken']}"
        )
        sug = (b.get("mapping_suggestions") or {}).get("summary") or {}
        print(
            f"SUGGESTIONS {b['product_key']} unmapped_code={sug.get('unmapped_code', 0)} "
            f"unmapped_docs={sug.get('unmapped_docs', 0)}"
        )
        for r in b["mappings"]:
            paths = "yes" if r["paths_ok"] else "no"
            doc_col = (
                "exists" if r["doc_exists"] else ("null" if r["doc"] is None else "missing")
            )
            print(f"ROW {r['id']}|{paths}|{doc_col}|{r['status']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
