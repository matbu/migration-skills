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
   - `CHANGELOG.rst`: append a new version section with entries at the **end** of the file (versions are listed oldest first)
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
   - Analyzing git commits since the last release tag. os-migrate tags have **no `v` prefix**
     (`1.0.3`, not `v1.0.3`): `git log 1.0.3..HEAD --oneline`. If the tag is missing
     locally, run `git fetch --tags` first, or fall back to the previous "Bump ... release"
     commit: `git log --oneline $(git log -1 --format=%H --grep='^Bump .*release to 1.0.3')..HEAD`
   - Asking the user with AskUserQuestion

4. **Updating galaxy.yml**:
   ```yaml
   version: 1.0.4  # old: 1.0.3
   ```

5. **Updating plugins/module_utils/const.py**:
   ```python
   OS_MIGRATE_VERSION = "1.0.4"  # updated by build.sh  (old: 1.0.3)
   ```

6. **Updating CHANGELOG.rst** by appending a new section at the **end of the file**.
   `CHANGELOG.rst` lists versions **oldest first** (1.0.2, 1.0.3, ... newest last) and has
   **no "Unreleased" section**: do not insert the new section at the top or between
   existing versions (certification review flagged 1.1.2 being listed before 1.1.1).

   Before editing, check the new version is greater than the last one listed:
   ```bash
   grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' CHANGELOG.rst | tail -1   # must be < new version
   ```

   Append, separated from the previous section by one blank line:
   ```rst
   1.0.4
   -----

   - Changelog entry 1
   - Changelog entry 2
   - Changelog entry 3
   ```
   Note: CHANGELOG.rst is RST, not Markdown. The `-----` underline must be at least as
   long as the version string.

   After editing, verify the version headings are still in ascending order (prints
   nothing and exits 0 when correct; works with macOS and GNU `sort`):
   ```bash
   grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' CHANGELOG.rst | sort -V -C && echo "CHANGELOG order OK"
   ```

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

11. **Creating a git commit** (only after explicit user approval):
    Leave all changes **unstaged** so the user can review them with `git diff`, then ask.
    Do not run `git add` or `git commit` until the user explicitly says OK.
    ```bash
    git add galaxy.yml plugins/module_utils/const.py CHANGELOG.rst aee/execution-environment.yml aee/requirements.yml docs/src/user/walkthrough.rst tests/func/tasks/tenant/data/validate_data_dir
    git commit -m "Bump minor release to 1.0.4"
    ```
    Note: Use "Bump minor release to X.Y.Z" for patch updates, "Bump major release to X.Y.Z" for minor/major updates.

12. **Show summary** of what was changed and next steps (e.g., "Push and create PR")

## Important Notes

- **Always validate the version format**: Must be semantic versioning (MAJOR.MINOR.PATCH)
- **Preserve CHANGELOG.rst formatting**: Follow existing RST structure; versions are oldest first, so the new section always goes at the end (there is no "Unreleased" section)
- **Check for unreleased changes**: If no commits since last tag and no changelog provided, warn the user
- **Don't create git tag**: The tag should be created manually or by CI after PR merge
- **Verify current branch**: Warn if on `main` branch (should create feature branch first)
- **All 9 files must be updated**: galaxy.yml, const.py, CHANGELOG.rst, execution-environment.yml, requirements.yml, walkthrough.rst, and the 3 validate_data_dir fixtures

## Error Handling

- If version already exists in CHANGELOG.rst: error and exit
- If the new version is not greater than the last version in CHANGELOG.rst: error and exit
- If the CHANGELOG.rst order check (`sort -V -C`) fails after editing: fix the order before continuing
- If no changelog entries provided/found: prompt user
- If uncommitted changes exist: warn user
- If version format invalid: error with example
- If any of the 9 files are missing: error and list missing files
