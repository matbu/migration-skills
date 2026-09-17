# audit-docs-drafts

Operator documentation **first-draft** skeleton for mappings that are in `code-to-docs*.yaml` but still have `doc: null` (`audience: external`, valid code paths).

## Run

```bash
./scripts/draft-undocumented.sh              # both products
./scripts/draft-undocumented.sh vmware
./scripts/draft-undocumented.sh os-migrate vmk-prelude
./scripts/draft-undocumented.sh ../audit-docs/reports/audit-report-YYYY-MM-DD.json
```

Requires local clones from `../audit-docs/config/repos.yaml` and PyYAML.

Reports: `../audit-docs/reports/doc-drafts-report-*.{json,md}`.

After the script runs, the agent **must** fill `draft_adoc` in the report (see `SKILL.md`).
