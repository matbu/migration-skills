---
name: os-release
description: Create a new release by bumping version and updating changelog for os-migrate
tags: [release, version, changelog, os-migrate]
---

# OS-Migrate Release Skill

This skill automates the release process for os-migrate by:
1. Determining the next version number
2. Updating all version references across the codebase
3. Collecting changelog entries from recent commits or user input
4. Creating a release commit

## Usage

```
/os-release [VERSION] [--changelog "Changelog entry 1" "Entry 2" ...]
```

**Arguments:**
- `VERSION` (optional): Specific version to release (e.g., `1.0.4`, `1.1.0`, `2.0.0`). If omitted, auto-increments patch version.
- `--changelog` (optional): List of changelog entries. If omitted, will prompt for entries or extract from recent commits.

## Examples

```bash
# Auto-increment patch version (1.0.3 → 1.0.4) and prompt for changelog
/os-release

# Specific version with changelog entries
/os-release 1.1.0 --changelog "Add new migration features" "Fix authentication issues"

# Minor version bump, interactive changelog
/os-release 1.1.0
```

## What it does

1. **Read current version** from `galaxy.yml`
2. **Determine next version**:
   - If VERSION provided: use it
   - If not: increment patch (e.g., 1.0.3 → 1.0.4)
3. **Collect changelog entries**:
   - If `--changelog` provided: use those entries
   - If not: analyze recent commits since last version tag or ask user
4. **Update files**:
   - `galaxy.yml`: version field
   - `plugins/module_utils/const.py`: OS_MIGRATE_VERSION constant
   - `CHANGELOG.rst`: add new version section with entries
   - `aee/execution-environment.yml`: tarball reference
   - `aee/requirements.yml`: collection source path
   - `docs/src/user/walkthrough.rst`: version example
   - `tests/func/tasks/tenant/data/validate_data_dir/*/networks*.yml` (3 fixtures): `os_migrate_version` line
5. **Create git commit** (optional): "Bump release to vX.Y.Z" or "Bump minor release to X.Y.Z"

## Files Modified

- `galaxy.yml`
- `plugins/module_utils/const.py`
- `CHANGELOG.rst`
- `aee/execution-environment.yml`
- `aee/requirements.yml`
- `docs/src/user/walkthrough.rst`
- `tests/func/tasks/tenant/data/validate_data_dir/valid/networks.yml`
- `tests/func/tasks/tenant/data/validate_data_dir/invalid/networks.yml`
- `tests/func/tasks/tenant/data/validate_data_dir/invalid/networks-duplicate.yml`

## Prerequisites

- Must be on a clean git branch
- Must have write access to the repository

---

# Implementation

You are responsible for:

1. **Reading the current version** from `galaxy.yml` (line 3: `version: X.Y.Z`)

2. **Parsing the version argument** (if provided) or auto-incrementing:
   ```
   Current: 1.0.3
   Auto-increment patch: 1.0.4
   Minor bump: 1.1.0
   Major bump: 2.0.0
   ```

3. **Getting changelog entries** by either:
   - Using provided `--changelog` entries
   - Analyzing git commits since last version tag: `git log v1.0.3..HEAD --oneline`
   - Asking the user with AskUserQuestion

4. **Updating galaxy.yml**:
   ```yaml
   version: 1.0.4  # old: 1.0.3
   ```

5. **Updating plugins/module_utils/const.py**:
   ```python
   OS_MIGRATE_VERSION = "1.0.4"  # updated by build.sh  (old: 1.0.3)
   ```

6. **Updating CHANGELOG.rst** by adding new section after "Unreleased":
   ```rst
   1.0.4
   -----
   
   - Changelog entry 1
   - Changelog entry 2
   - Changelog entry 3
   ```
   Note: The CHANGELOG.rst follows RST format, not Markdown. Keep "Unreleased" section at the top.

7. **Updating aee/execution-environment.yml**:
   ```yaml
   additional_build_files:
     - src: ../os_migrate-os_migrate-1.0.4.tar.gz  # old: 1.0.3
       dest: tmp/
   ```

8. **Updating aee/requirements.yml**:
   ```yaml
   - name: os_migrate.os_migrate
     source: tmp/os_migrate-os_migrate-1.0.4.tar.gz  # old: 1.0.3
     type: file
   ```

9. **Updating docs/src/user/walkthrough.rst**:
   Find the line with `os_migrate_version: X.Y.Z` and update it:
   ```rst
   os_migrate_version: 1.0.4  # old: 1.0.3
   ```

10. **Updating the func test fixtures** (line 1 of each):
    `tests/func/tasks/tenant/data/validate_data_dir/valid/networks.yml`,
    `.../invalid/networks.yml`, `.../invalid/networks-duplicate.yml`:
    ```yaml
    os_migrate_version: 1.0.4  # old: 1.0.3
    ```
    `plugins/module_utils/filesystem.py` requires an exact match with
    `OS_MIGRATE_VERSION`; forgetting these breaks the gostack functional tests CI.
    Afterwards, `git grep -n "<old version>" -- ':!CHANGELOG.rst'` must return nothing
    (except intentionally old examples in walkthrough.rst like `0.17.0`).

11. **Creating a git commit** (ask user first):
    ```bash
    git add galaxy.yml plugins/module_utils/const.py CHANGELOG.rst aee/execution-environment.yml aee/requirements.yml docs/src/user/walkthrough.rst tests/func/tasks/tenant/data/validate_data_dir
    git commit -m "Bump minor release to 1.0.4"
    ```
    Note: Use "Bump minor release to X.Y.Z" for patch updates, "Bump major release to X.Y.Z" for minor/major updates.

12. **Show summary** of what was changed and next steps (e.g., "Push and create PR")

## Important Notes

- **Always validate the version format**: Must be semantic versioning (MAJOR.MINOR.PATCH)
- **Preserve CHANGELOG.rst formatting**: Follow existing RST structure, keep "Unreleased" section
- **Check for unreleased changes**: If no commits since last tag and no changelog provided, warn the user
- **Don't create git tag**: The tag should be created manually or by CI after PR merge
- **Verify current branch**: Warn if on `main` branch (should create feature branch first)
- **All 9 files must be updated**: galaxy.yml, const.py, CHANGELOG.rst, execution-environment.yml, requirements.yml, walkthrough.rst, and the 3 validate_data_dir fixtures

## Error Handling

- If version already exists in CHANGELOG.rst: error and exit
- If no changelog entries provided/found: prompt user
- If uncommitted changes exist: warn user
- If version format invalid: error with example
- If any of the 9 files are missing: error and list missing files
