---
name: audit-docs-correctness
description: Compare documented code against documentation for VMware Migration Kit and os-migrate; suggest fixes only (read-only)
tags: [docs, audit, vmware-migration-kit, os-migrate, correctness]
---

# Audit docs correctness

Compares **documented** code areas against what the docs say. **Read-only** — no edits to code, docs, mapping files, or PRs. Outputs a report with suggested fixes only.

Runs after `audit-docs` (skill 1) or standalone if paths are already known good.

Shared config lives in `../audit-docs/config/`. Paths below are relative to this skill directory (`skills/audit-docs-correctness/`).

## Usage

```
/audit-docs-correctness
/audit-docs-correctness all
/audit-docs-correctness vmware
/audit-docs-correctness os-migrate
/audit-docs-correctness ../audit-docs/reports/audit-report-2026-07-01.json
/audit-docs-correctness vmware vmk-migrate-nbdkit
/audit-docs-correctness os-migrate ../audit-docs/reports/audit-report-2026-07-01.json osm-walkthrough
```

**Arguments:**
- `product` (optional, default `all`) — `all` | `vmware` | `os-migrate` (aliases: `vmk`, `osm`)
  - **`all`** (default): check **vmware-migration-kit first**, then **os-migrate**, in one report
- `report.json` (optional) — audit report from skill 1; only check rows with `paths_ok: true` and `status: mapped`
  - Combined reports: use each entry under `products[]`
  - Single-product reports: use top-level `mappings` or the one `products[]` entry
- `id` (optional) — single mapping id (e.g. `vmk-migrate-nbdkit`, `osm-walkthrough`)

## Prerequisites

- Local clones at paths in `../audit-docs/config/repos.yaml`
- Run `audit-docs` first (recommended) or ensure code/doc paths exist
- Install for Claude Code: `./scripts/install.sh --symlink` from repo root

## Which rows to check

Include a mapping only if **all** are true:

- `doc` is not null
- Code and doc files exist (from report or verified now)
- Not `status: undocumented`

Skip rows with `doc: null`. If a report is provided, skip rows where `paths_ok` is false.

When `product` is `all`, process products in this order:

1. `vmware-migration-kit` (`code-to-docs.vmware.yaml`)
2. `os-migrate` (`code-to-docs.os-migrate.yaml`)

## Steps

### 1. Load inputs

1. Read `../audit-docs/config/repos.yaml` and resolve paths (expand `~`):
   - Docs: `docs_repo.local_path` / `docs_repo.url`
   - For each product in scope:
     - Code: `code_repos.<key>.local_path` / `.url`
       - VMware: `vmware-migration-kit`
       - os-migrate: `os-migrate`
2. Read the matching `../audit-docs/config/code-to-docs.*.yaml` file(s)
3. If `report.json` given, read it and filter eligible rows per product; else use all mapped rows from each YAML

### 2. Compare doc vs code (by `kind`)

For each eligible mapping, read the mapped doc file and related code. Use `notes` on the mapping for section focus when present.

**playbook**
- Collection FQCN in doc matches `galaxy.yml` (`namespace`, `name`) for that product
- Playbook referenced in doc matches a file under `playbooks/`
- Sub-playbooks imported by the main playbook still exist if doc describes end-to-end flow

**role / feature**
- Variable names in doc examples exist in related role `defaults/main.yml`, playbooks, or role `README.md`
- Important user-facing defaults in code are reflected in doc (warning if missing from doc, not auto-fail)
- Doc mentions a variable name with no match in code → **issue**

**module**
- Parse `DOCUMENTATION` / `options:` from the module `.py`
- Required options missing from doc → **warning**
- Doc-only option names with no module match → **issue**

**ci / internal**
- Doc describes workflows or paths that exist under mapped `code:` globs

### 3. Classify each row

| Result | Meaning |
|--------|---------|
| **ok** | No meaningful mismatches |
| **warnings** | Minor gaps (undocumented vars, missing optional detail) |
| **issues** | Wrong names, stale examples, clear doc/code conflict |

Record **evidence** for every warning/issue: file path, **line number**, and quote from doc and code.

Always include the doc line number in findings (e.g. `operator-vmware-guide.adoc line 331`) and the code line number when citing code (e.g. `roles/conversion_host/defaults/main.yml line 18`). Those line numbers feed the `doc` and `code` report links.

### 3b. Doc link (per row)

Build a GitHub source link for the markdown **Doc** line:

```
{docs_repo.url}/blob/main/{doc_path}#L{line}
```

| Row | `doc_line` | Markdown Doc link |
|-----|------------|-------------------|
| **issues** / **warnings** | First line cited in findings | `[basename:331](url#L331)` |
| **ok** | Omit | `[basename](url)` (file only, no `#L`) |

### 3c. Code link (per row)

Build a GitHub source link for the markdown **Code** line from that product’s `code_repos.*.url`:

```
{code_repo.url}/blob/main/{code_path}#L{line}   # single file
{code_repo.url}/tree/main/{dir_path}            # directory / glob base (e.g. roles/foo/**)
```

| Row | `code_line` | Markdown Code link |
|-----|-------------|--------------------|
| **issues** / **warnings** | First code line cited in findings | `[basename:42](url#L42)` |
| **ok** | Omit | `[basename](url)` or `[dir/](tree-url)` (no `#L`) |

Pick the path to link:

1. Prefer the **first code file cited** in findings (with line when available).
2. Else the first concrete file under the mapping's `code:` list.
3. For a glob only (e.g. `roles/conversion_host/**`), link the directory with `/tree/main/` (strip `/**`).

When multiple code paths matter, link the primary one on the **Code** line; mention the others in **Findings**.

### 4. Suggest fixes (text only)

For **warnings** and **issues**, add a `suggested_fix` field:

- Describe what to change in the doc (not the code)
- Quote the doc snippet to replace or extend
- Do **not** apply edits — suggestions only

For **ok** rows, add a one-line confirmation to the report summary.

### 5. Write report

Print markdown and save to:

```
../audit-docs/reports/correctness-report-{YYYY-MM-DD}.md
../audit-docs/reports/correctness-report-{YYYY-MM-DD}.json
```

**Combined (`all`) markdown** — use headers and prose (not tables), product sections in order. List rows with **issues** first, then **warnings**, then **ok**.

```markdown
# Correctness report (YYYY-MM-DD)

Source: combined (vmware-migration-kit, then os-migrate)
Overall: **ok=…**, **warnings=…**, **issues=…**

This run did not modify any repository.

## vmware-migration-kit

Checked: N mapped rows …
Summary: **ok=…**, **warnings=…**, **issues=…**

### Results

#### {id}: {correctness}

Doc: [basename:331](doc_url)
Code: [basename:42](code_url)

Findings: …
(or bullet list when multiple findings)

Suggested fix: …
(omit Suggested fix when correctness is ok)

#### {next-id}: {correctness}
…

### Issues (priority)
…
### Warnings
…

## os-migrate

Checked: …
### Results
#### {id}: {correctness}
…
```

**Single-product markdown** — same header/prose shape:

```markdown
# Correctness report — {product} (YYYY-MM-DD)
…
## Results

#### {id}: {correctness}

Doc: …
Code: …

Findings: …

Suggested fix: …
```

**JSON shape:**

```json
{
  "generated_at": "2026-07-01T14:00:00Z",
  "summary": { "checked": 0, "ok": 0, "warnings": 0, "issues": 0 },
  "products": [
    {
      "product": "vmware-migration-kit",
      "product_key": "vmware",
      "summary": { "checked": 17, "ok": 3, "warnings": 4, "issues": 10 },
      "rows": [
        {
          "id": "vmk-conversion-host",
          "correctness": "ok|warnings|issues",
          "doc": "source/operator-vmware-guide.adoc",
          "doc_line": 331,
          "doc_url": "https://github.com/os-migrate/documentation/blob/main/source/operator-vmware-guide.adoc#L331",
          "code": "roles/conversion_host/defaults/main.yml",
          "code_line": 18,
          "code_url": "https://github.com/os-migrate/vmware-migration-kit/blob/main/roles/conversion_host/defaults/main.yml#L18",
          "findings": ["..."],
          "suggested_fix": "..."
        }
      ]
    },
    {
      "product": "os-migrate",
      "product_key": "os-migrate",
      "summary": { "checked": 0, "ok": 0, "warnings": 0, "issues": 0 },
      "rows": []
    }
  ]
}
```

- `products` is always **vmware first**, then **os-migrate** when both are in scope
- For a single-product run, `products` has one entry; top-level `rows` may also be set for convenience
- `doc_line` / `code_line`: first cited line for issues/warnings; omit for `ok`
- Omit or empty `suggested_fix` when `correctness` is `ok`

### 6. Summarize

- Overall ok / warnings / issues, then per product
- List ids with **issues** first, then **warnings** (within each product, VMware section before os-migrate)
- Remind: this run did not modify any repository

## Rules

- **Read-only** — do not modify code repo, documentation repo, or `code-to-docs*.yaml`
- **No PRs** — do not create branches or pull requests
- **No auto-fix** — suggest fixes in the report only; human applies changes
- Skip `doc: null` / undocumented mappings
- Many rows may share one `.adoc` file — report per **mapping id**, not “whole file wrong”
- Cite evidence; do not guess — read files with shell or read tool
- If clones missing, report failed path and stop
- See `../audit-docs/config/README.md` for mapping field meanings

---

# Implementation

You are responsible for executing the steps above when the user invokes `/audit-docs-correctness`.

Use `rg`, `grep`, and file reads to compare names and examples. Prefer narrow context: only files listed in the mapping's `code:` and the single `doc:` file.

When the same doc file appears in multiple mappings, check only what is relevant to that mapping's code paths and `notes`.

Build `doc_url` from `docs_repo.url` and `code_url` from the **current product’s** `code_repos.*.url` in `repos.yaml` — do not hardcode a different org or branch unless the user specifies one.

Default to **both products** (VMware kit, then os-migrate) unless the user names a single product.
