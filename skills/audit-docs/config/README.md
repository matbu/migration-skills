# Code ↔ docs mapping

Human-maintained links between product code (os-migrate, VMware Migration Kit) and the shared [documentation](https://github.com/os-migrate/documentation) repo. Used by doc audit agents and other automation — not tied to a single skill.

## Files

| File | Purpose |
|------|---------|
| `repos.yaml` | GitHub URLs and optional local clone paths for all three repos |
| `code-to-docs.os-migrate.yaml` | os-migrate code → documentation pages |
| `code-to-docs.vmware.yaml` | VMware Migration Kit code → documentation pages |

## Repositories

- **Code:** [os-migrate](https://github.com/os-migrate/os-migrate), [vmware-migration-kit](https://github.com/os-migrate/vmware-migration-kit)
- **Docs:** [documentation](https://github.com/os-migrate/documentation) (one site for both products)

Each mapping file applies to one code repo. All `doc:` paths point at the documentation repo.

## Mapping entry fields

Each item under `mappings:` links one doc page (or a gap) to one or more code paths.

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Stable unique name (use prefixes `osm-` or `vmk-`). Used in reports and automation. |
| `doc` | Yes | Path to the doc page in the **documentation** repo, or `null` if no page exists. |
| `code` | Yes | List of paths in the **product** repo (file or glob, e.g. `roles/foo/**`). |
| `audience` | Recommended | `external` (users/operators) or `internal` (contributors/CI). |
| `kind` | Recommended | Code type: `module`, `role`, `playbook`, `feature`, or `ci`. Guides how agents compare docs vs code. |
| `status` | Optional | Coverage note when doc is missing or incomplete: `undocumented`, `partial`, `stale`. |
| `notes` | Optional | Free-text reminder for yourself. |

### Path rules

- **`code:`** — relative to the product repo root (os-migrate or vmware-migration-kit).
- **`doc:`** — relative to the documentation repo root (e.g. `source/operator-walkthrough.adoc`).
