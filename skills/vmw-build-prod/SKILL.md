---
name: vmw-build-prod
description: Build production VMware Migration Kit collection on x86_64 architecture (local or remote) and optionally publish it to Ansible Galaxy once all post-build checks pass
version: 1.1
---

# VMware Migration Kit Production Build

Build the production Ansible collection for VMware Migration Kit. This skill ensures the build happens on an x86_64 architecture and verifies the resulting binaries are x86_64.

## How This Skill Works

When you invoke `/vmw-build-prod`, Claude Code:
1. Reads the `SKILL.md` file (this file) to understand what to do
2. Executes the bundled `scripts/build.sh` script with your provided arguments
3. The script handles all the build logic (architecture checks, git clone, make build-prod, etc.)
4. Returns the results back to you with formatted output

The skill is **self-contained** - all logic is in the bundled script, so it can be executed independently or via Claude Code.

## Arguments

The skill accepts these optional arguments (space-separated):
1. `<version>` - Git tag/branch to build (default: latest git tag)
2. `<build-machine-ip>` - IP address of remote build machine (default: local build)
3. `<ssh-user>` - SSH user for remote build (default: current user, only used for remote builds)

Optional flags (can appear anywhere):
- `--publish` - Publish the tarball to Ansible Galaxy after **all** post-build checks are green
- `--api-key KEY` - Ansible Galaxy API key (required with `--publish`; falls back to the `GALAXY_API_KEY` env var)

To pass flags while keeping the default version, use `latest` as the first positional argument.

## Usage Examples

```bash
# Build latest version locally (must be on x86_64)
/vmw-build-prod

# Build specific version locally
/vmw-build-prod v2.2.4

# Build latest on remote machine
/vmw-build-prod latest 192.168.1.100

# Build specific version on remote machine with custom user
/vmw-build-prod v2.2.4 192.168.1.100 builder

# Build remotely, then publish to Galaxy if all checks pass
/vmw-build-prod 2.2.4 192.168.1.100 builder --publish --api-key YOUR_KEY

# Build locally (x86_64) and publish, key from environment
GALAXY_API_KEY=YOUR_KEY /vmw-build-prod 2.2.4 --publish
```

## Manual Execution

You can also run the script directly without Claude Code:

```bash
# From the project root
./.claude/skills/vmw-build-prod/scripts/build.sh [version] [build-ip] [ssh-user]

# Examples
./.claude/skills/vmw-build-prod/scripts/build.sh v2.2.4
./.claude/skills/vmw-build-prod/scripts/build.sh latest 192.168.1.100 builder
./.claude/skills/vmw-build-prod/scripts/build.sh 2.2.4 192.168.1.100 builder --publish --api-key YOUR_KEY
```

## Build Process

Execute the bundled build script:

```bash
./scripts/build.sh "$@"
```

The script performs these steps:

1. **Parse Arguments**: Extract version, build machine IP, and SSH user from args
2. **Get Version**: If version is "latest" or empty, fetch the latest git tag
3. **Check Architecture**: Determine if current machine is x86_64 or needs remote build
4. **Local Build** (if x86_64):
   - Clone repository to `/tmp/vmware-migration-kit-build-<timestamp>`
   - Checkout the specified version
   - Run `make build-prod`
   - Verify binary architecture with `file` command
   - Copy tarball to `$HOME/Downloads/`
   - Clean up temp directory
5. **Remote Build** (if not x86_64 or IP provided):
   - SSH to remote machine and run build commands
   - Verify binary architecture remotely
   - SCP tarball to local `$HOME/Downloads/`
   - Clean up remote temp directory
6. **Publish pre-flight** (only with `--publish`, runs *before* building): API key present and `ansible-galaxy` available locally — fails fast otherwise
7. **Post-build checks** (always run on the local tarball in `~/Downloads/`):
   - Tarball is non-empty and a valid gzip archive
   - Packaged `plugins/modules/migrate` is an **ELF 64-bit x86-64** binary
   - Collection version matches the requested tag (leading `v` stripped) — error when publishing, warning otherwise
   - With `--publish`: that version is not already on Galaxy
8. **Publish** (only with `--publish` and all checks green): `ansible-galaxy collection publish` from the local machine. If publish fails the local tarball is kept.

## API Key Security

- Never echo, log, or display the API key value. The script masks it in `ansible-galaxy` output.
- When reporting back to the user, do not repeat the key.

## Expected Output

The skill should provide:
- ✅ Architecture check result (x86_64 or ARM/other)
- ✅ Build location (local or remote IP)
- ✅ Version being built
- ✅ Build progress and completion status
- ✅ Binary architecture verification
- ✅ Final tarball location
- ❌ Clear error messages if anything fails

## Example Summary

```
VMware Migration Kit Production Build:
✅ Architecture: x86_64 (local build)
✅ Version: v2.2.4
✅ Build: SUCCESS
✅ Binary verification: migrate is x86-64 ELF
✅ Output: ~/Downloads/os_migrate-vmware_migration_kit-2.2.4.tar.gz
✅ Post-build checks: all passed
```

Or for remote build:

```
VMware Migration Kit Production Build:
⚠️  Architecture: arm64 (remote build required)
✅ Remote host: 192.168.1.100 (user: builder)
✅ Version: v2.2.4
✅ Remote build: SUCCESS
✅ Binary verification: migrate is x86-64 ELF
✅ Downloaded: ~/Downloads/os_migrate-vmware_migration_kit-2.2.4.tar.gz
✅ Remote cleanup: SUCCESS
✅ Post-build checks: archive OK, ELF x86-64, version matches tag, not yet on Galaxy
✅ Published: https://galaxy.ansible.com/ui/repo/published/os_migrate/vmware_migration_kit/
```
