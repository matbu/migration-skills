---
name: audit-docs
description: Audit code-to-docs mappings for VMware Migration Kit and os-migrate (read-only report)
tags: [docs, audit, vmware-migration-kit, os-migrate]
---

# Audit docs to code

Read-only check of mapping files. Does not edit product repos or open PRs. Writes reports under `reports/` for use by `audit-docs-correctness` (skill 2).

All paths below are relative to this skill directory (`skills/audit-docs/`).

## Usage

```
/audit-docs
/audit-docs all
/audit-docs vmware
/audit-docs os-migrate
/audit-docs vmware vmk-migrate-nbdkit
/audit-docs os-migrate osm-walkthrough
```

**Arguments:**
- `product` (optional, default `all`) — `all` | `vmware` | `os-migrate` (aliases: `vmk`, `osm`)
  - **`all`** (default): audit **vmware-migration-kit first**, then **os-migrate**, in one report
  - Single product: same format as before, one product only
- `id` (optional) — audit a single mapping by `id` (e.g. `vmk-migrate-nbdkit`, `osm-walkthrough`). With `all`, the product is inferred from the `vmk-` / `osm-` prefix.

## Prerequisites

- Local clones at paths defined in `config/repos.yaml`
- Install skill for Claude Code: `./scripts/install.sh --symlink` from repo root

## Steps

1. Read `config/repos.yaml` and resolve local paths (expand `~`):
   - Code: `code_repos.vmware-migration-kit.local_path` and/or `code_repos.os-migrate.local_path`
   - Docs: `docs_repo.local_path`
2. Read mapping YAML(s) in product order:
   - VMware: `config/code-to-docs.vmware.yaml`
   - os-migrate: `config/code-to-docs.os-migrate.yaml`
3. For each mapping (or the one `id` if provided):
   - Verify each `code:` path under the product repo root:
     - Single file: file must exist
     - Glob (`*`, `**`): at least one matching file (or base dir for `/**`)
   - If `doc` is not null, verify the path exists under the documentation repo root
   - If `doc` is null, list as **undocumented** (use `status` from mapping if set)
   - Set `paths_ok: true` only if all code paths pass and (doc is null OR doc file exists)
4. Build the report data for each row:
   - `id`, `doc`, `doc_exists`, `paths_ok`, `code_ok`, `status`
   - When `doc_exists` is true, also set `doc_url` from `docs_repo.url` in `repos.yaml`:
     `{docs_repo.url}/blob/main/{doc}`
   - `status`: `mapped` (doc exists, paths OK), `undocumented` (doc null, code OK), `broken` (paths missing)
5. **Cross-reference coverage** (always over the full YAML for that product, even if `id` is set):
   - Inventory notable code units: `playbooks/*.yml`, `roles/*/`, `plugins/modules/*.py`, `.github/workflows/*`, plus `aee/`, `doc/`, `scripts/`, `tests/`, `meta/`
   - Inventory product-related docs under `source/*.adoc` (filename hints and/or content)
   - Compare against every `code:` / `doc:` already in that product’s mapping file
   - Record gaps as `mapping_suggestions` (candidates to add — do **not** edit the YAML)
6. Print markdown. **Combined (`all`) reports** use this order and keep the existing Summary / Mappings / suggestions structure **per product**:

   ```markdown
   # Audit report (YYYY-MM-DD-all)
   ## Overall summary
   ## vmware-migration-kit
   ### Summary
   ### Mappings
   | id | paths OK | doc | status |
   ### Mapping suggestions …
   ## os-migrate
   ### Summary
   ### Mappings
   …
   ## Next step
   ```

   Single-product reports keep the previous title: `# Audit report — {product} ({audit_id})` with top-level `## Summary` / `## Mappings`.

   For **mapped** rows, the status cell is a link to the doc source:

   | id | paths OK | doc | status |
   |----|----------|-----|--------|
   | vmk-overview | yes | exists | [mapped](https://github.com/os-migrate/documentation/blob/main/source/operator-vmware-guide.adoc) |
   | vmk-metadata-convert | yes | null | undocumented |

7. **Save reports** (create `reports/` if missing):

   ```
   reports/audit-report-{YYYY-MM-DD}.md
   reports/audit-report-{YYYY-MM-DD}.json
   ```

   Use today's date. If both files already exist for that date, append `-2`, `-3`, etc.

8. Summarize in chat: overall totals, then per-product mapped / undocumented / broken and suggestion counts, and **full paths** to the saved report files

## Report JSON schema

Skill 2 (`audit-docs-correctness`) reads this file.

### Combined report (`product` = `all`, default)

```json
{
  "audit_id": "2026-07-01-all",
  "generated_at": "2026-07-01T14:00:00Z",
  "docs_repo_path": "/expanded/path/to/documentation",
  "docs_repo_url": "https://github.com/os-migrate/documentation",
  "summary": {
    "total": 136,
    "mapped": 124,
    "undocumented": 10,
    "broken": 2
  },
  "products": [
    {
      "product": "vmware-migration-kit",
      "product_key": "vmware",
      "code_repo_path": "/expanded/path/to/vmware-migration-kit",
      "code_repo_url": "https://github.com/os-migrate/vmware-migration-kit",
      "summary": { "total": 22, "mapped": 17, "undocumented": 5, "broken": 0 },
      "mappings": [ { "id": "vmk-overview", "paths_ok": true, "status": "mapped", "doc_url": "..." } ],
      "mapping_suggestions": { "summary": { "unmapped_code": 3, "unmapped_docs": 0 }, "unmapped_code": [], "unmapped_docs": [] }
    },
    {
      "product": "os-migrate",
      "product_key": "os-migrate",
      "code_repo_path": "/expanded/path/to/os-migrate",
      "code_repo_url": "https://github.com/os-migrate/os-migrate",
      "summary": { "total": 114, "mapped": 107, "undocumented": 5, "broken": 0 },
      "mappings": [],
      "mapping_suggestions": { "summary": { "unmapped_code": 0, "unmapped_docs": 0 }, "unmapped_code": [], "unmapped_docs": [] }
    }
  ]
}
```

`products` is always **vmware-migration-kit first**, then **os-migrate**.

### Single-product report

Same row fields as before. Also includes a one-element `products` array. Top-level `product`, `mappings`, and `mapping_suggestions` are set for backward compatibility.

- `doc_url`: present when `doc_exists` is true; omit otherwise
- Markdown `status` for mapped rows: `[mapped]({doc_url})`
- `mapping_suggestions`: end-of-section candidates **not** in that product’s `code-to-docs*.yaml`; suggestions only (never auto-edit the YAML)

Next step line for combined reports:

```text
Next: /audit-docs-correctness reports/audit-report-{YYYY-MM-DD}.json
```

## Rules

- Read-only on product repos and `config/code-to-docs*.yaml`
- **May write** only to `reports/` under this skill directory
- If a local clone is missing, report which `repos.yaml` path failed and stop (do not write partial reports)
- See `config/README.md` for mapping field meanings

---

# Implementation

You are responsible for executing the steps above when the user invokes `/audit-docs`.

## Autonomous execution

- Run the bundled script immediately. **Do not ask the user questions** or wait for confirmation.
- **Do not** paste scripts for the user to run — execute the command yourself.
- If the script fails, show stderr and stop. Do not ask how to proceed.

From the skill directory (`skills/audit-docs/`), run:

```bash
./scripts/audit-paths.sh
./scripts/audit-paths.sh all
./scripts/audit-paths.sh vmware
./scripts/audit-paths.sh os-migrate
./scripts/audit-paths.sh vmware vmk-migrate-nbdkit
```

The script defaults to **both products** (VMware then os-migrate), reads `config/repos.yaml` and the matching `code-to-docs*.yaml` files, checks paths, cross-references for unmapped coverage, and writes reports under `reports/`.

On success, print the script output (summary + `AUDIT_JSON=` / `AUDIT_MD=` lines). Do not re-implement the audit in inline Python.
