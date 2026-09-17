---
name: audit-docs-drafts
description: First-draft operator documentation for undocumented external mappings in code-to-docs YAML (read-only)
tags: [docs, audit, vmware-migration-kit, os-migrate, drafts]
---

# Audit docs — documentation drafts

Produces **first-draft operator documentation** for code areas tracked in the human-maintained mapping YAML but still missing a doc page (`doc: null`, `audience: external`). **Read-only** — no edits to code, documentation repo, mapping YAML, or PRs.

Runs after `/audit-docs` (and optional human YAML updates). Output is a **separate** report from the path audit.

Shared config: `../audit-docs/config/`. Paths below are relative to this skill directory (`skills/audit-docs-drafts/`).

## Usage

```
/audit-docs-drafts
/audit-docs-drafts all
/audit-docs-drafts vmware
/audit-docs-drafts os-migrate
/audit-docs-drafts vmware vmk-prelude
/audit-docs-drafts ../audit-docs/reports/audit-report-2026-09-01.json
/audit-docs-drafts vmware ../audit-docs/reports/audit-report-2026-09-01.json
```

**Arguments:**
- `product` (optional, default `all`) — `all` | `vmware` | `os-migrate` (aliases: `vmk`, `osm`)
  - **`all`** (default): **vmware-migration-kit first**, then **os-migrate**
- `report.json` (optional) — audit report from `/audit-docs`; only draft rows with `paths_ok: true` and `status: undocumented`
- `id` (optional) — single mapping id (e.g. `vmk-prelude`, `osm-changelog`)

## Prerequisites

- Local clones at paths in `../audit-docs/config/repos.yaml`
- Run `/audit-docs` first (recommended) or ensure code paths exist
- Install for Claude Code: `./scripts/install.sh --symlink` from repo root

## Which rows get a draft

Include a mapping only if **all** are true:

- `doc` is `null`
- `audience` is `external` (operator-facing)
- All `code:` paths exist (from audit JSON or verified inline)
- Not `kind: ci`
- Not filtered out by optional `id` or audit report filter

Skip `audience: internal`, broken paths, and rows that already have a `doc:` path.

When `product` is `all`, process products in this order:

1. `vmware-migration-kit` (`code-to-docs.vmware.yaml`)
2. `os-migrate` (`code-to-docs.os-migrate.yaml`)

## Steps

### 1. Run the script

From `skills/audit-docs-drafts/`:

```bash
./scripts/draft-undocumented.sh
./scripts/draft-undocumented.sh vmware
./scripts/draft-undocumented.sh ../audit-docs/reports/audit-report-YYYY-MM-DD.json
```

The script:

- Loads `../audit-docs/config/repos.yaml` and matching `code-to-docs.*.yaml`
- Filters eligible undocumented external mappings
- Extracts mechanical `code_context` per row (by `kind`: playbook, role, module, feature)
- Suggests a target `.adoc` path (`suggested_doc_path`)
- Writes skeleton reports under `../audit-docs/reports/doc-drafts-report-{YYYY-MM-DD}.{json,md}` with `draft_status: pending`

### 2. Agent: write operator AsciiDoc drafts (required)

After the script succeeds, **you must** complete the report:

1. Load `doc-drafts-report-*.json`
2. For each draft with `draft_status: pending` (or empty `draft_adoc`):
   - Read mapped code files (not only `code_context`)
   - Write **operator-facing** AsciiDoc: overview, when to use, requirements, configuration, usage, related components
   - Tone: technical, concise, for migration engineers
   - Mark as draft: title suffix `(draft)` or leading comment
   - Base claims on code and mapping `notes` only — do not invent behavior
3. Update **both** `.json` (`draft_adoc`, `draft_status: draft`) and `.md` (replace `_Pending agent draft_` with fenced `adoc` blocks)
4. Summarize in chat: draft count, ids, full paths to report files

### AsciiDoc draft template

Per entry, aim for:

```adoc
= {Component name} (draft)

:product: vmware-migration-kit | os-migrate

== Overview
What it is and where it fits in a migration workflow.

== When to use
Operator scenarios.

== Requirements
Hosts, credentials, conversion host, etc. (from code/notes only).

== Configuration
Key variables / module options (from defaults or DOCUMENTATION).

== Usage
Example playbook snippet with collection FQCN when applicable.

== Related components
From imports, notes, or mapping code paths.

// TODO: Human review — verify against source code before publishing.
```

### 3. Report shape

**Markdown** (`doc-drafts-report-*.md`):

```markdown
# Documentation drafts (YYYY-MM-DD-all)

## Overall summary
- Drafts: N

## vmware-migration-kit
### Draft entries

#### vmk-prelude

Suggested file: `source/reference-role-prelude.adoc`
Code: [roles/prelude/defaults/main.yml](url)

```adoc
= Prelude role (draft)
...
```

## Next step
After human writes docs and updates doc: in code-to-docs YAML:
/audit-docs then /audit-docs-correctness reports/audit-report-....json
```

**JSON** (`doc-drafts-report-*.json`):

```json
{
  "draft_id": "2026-09-01-all",
  "generated_at": "2026-09-01T15:00:00Z",
  "summary": { "draft_count": 10 },
  "products": [
    {
      "product": "vmware-migration-kit",
      "product_key": "vmware",
      "summary": { "draft_count": 7 },
      "drafts": [
        {
          "id": "vmk-prelude",
          "kind": "role",
          "code": ["roles/prelude/**"],
          "notes": "...",
          "suggested_doc_path": "source/reference-role-prelude.adoc",
          "code_context": {},
          "code_urls": ["https://github.com/..."],
          "draft_adoc": null,
          "draft_status": "pending"
        }
      ]
    }
  ]
}
```

## Rules

- **Read-only** on product repos, documentation repo, and `code-to-docs*.yaml`
- **May write** only to `../audit-docs/reports/doc-drafts-report-*.{json,md}`
- **Draft prose is required** — the script alone does not satisfy operator documentation
- Do not open PRs or edit the documentation repo

---

# Implementation

You are responsible for executing the steps above when the user invokes `/audit-docs-drafts`.

## Autonomous execution

1. Run `./scripts/draft-undocumented.sh` immediately with the user's arguments. **Do not** ask the user to run it.
2. If the script fails, show stderr and stop.
3. If `draft_count > 0`, **complete every pending draft** in the report (read code, write AsciiDoc, update json + md). Do not stop after the script.
4. If `draft_count` is 0, summarize that no eligible rows were found.

On success, print script output (`DRAFTS_JSON=` / `DRAFTS_MD=` / `DRAFTS … count=`) and a chat summary with ids drafted and full report paths.

Default to **both products** (VMware kit, then os-migrate) unless the user names a single product.
