# audit-docs-correctness

Mechanical doc↔code correctness checks for mapped rows from `../audit-docs/config/code-to-docs*.yaml`.

## Run

```bash
./scripts/audit-correctness.sh              # both products
./scripts/audit-correctness.sh vmware
./scripts/audit-correctness.sh os-migrate osm-walkthrough
./scripts/audit-correctness.sh ../audit-docs/reports/audit-report-YYYY-MM-DD.json
```

Requires local clones from `../audit-docs/config/repos.yaml` and PyYAML.

Reports: `../audit-docs/reports/correctness-report-*.{json,md}`.
