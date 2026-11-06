# VMware Migration Kit Production Build Skill

This skill automates the production build of the VMware Migration Kit Ansible collection with guaranteed x86_64 binary output.

## How It Works

### Skill Execution Flow

When you invoke `/vmw-build-prod`, here's what happens:

1. **Claude Code reads `SKILL.md`**: The skill frontmatter and instructions tell Claude what this skill does
2. **Claude executes the bundled script**: The `scripts/build.sh` script is executed with your arguments
3. **Script handles all logic**: Architecture detection, git operations, make build-prod, verification
4. **Results returned**: Formatted output with success/failure indicators

### File Structure

```
.claude/skills/vmw-build-prod/
├── SKILL.md           # Skill metadata and instructions for Claude Code
├── README.md          # This file - documentation for humans
└── scripts/
    └── build.sh       # The actual build automation script
```

### How Scripts Are Executed

Claude Code skills can include bundled resources (scripts, templates, configs, etc.). When a skill references a script in its instructions:

```markdown
# In SKILL.md
Execute the bundled build script:
```bash
./scripts/build.sh "$@"
```
```

Claude Code will:
1. Change to the skill directory (`.claude/skills/vmw-build-prod/`)
2. Execute the bash code block
3. The script runs with access to bundled resources via relative paths

This makes skills **portable** and **self-contained** - all dependencies travel with the skill.

## Usage

### Via Claude Code

```bash
# Build latest version (local if x86_64)
/vmw-build-prod

# Build specific version
/vmw-build-prod v2.2.4

# Force remote build
/vmw-build-prod v2.2.4 192.168.1.100 builder

# Build and publish to Ansible Galaxy (only if all post-build checks pass)
/vmw-build-prod 2.2.4 192.168.1.100 builder --publish --api-key YOUR_KEY
```

### Direct Script Execution

You can also run the script directly:

```bash
# From anywhere in the project
./.claude/skills/vmw-build-prod/scripts/build.sh [version] [build-ip] [ssh-user]

# Examples
./.claude/skills/vmw-build-prod/scripts/build.sh
./.claude/skills/vmw-build-prod/scripts/build.sh v2.2.4
./.claude/skills/vmw-build-prod/scripts/build.sh latest 192.168.1.100
```

## Arguments

All arguments are optional and positional:

| Position | Argument | Default | Description |
|----------|----------|---------|-------------|
| 1 | `version` | latest tag | Git tag/branch to build |
| 2 | `build-ip` | local | Remote build machine IP (forces remote build) |
| 3 | `ssh-user` | `$USER` | SSH username for remote build |

Optional flags (any position):

| Flag | Description |
|------|-------------|
| `--publish` | Publish to Ansible Galaxy after all post-build checks pass |
| `--api-key KEY` | Galaxy API key (required with `--publish`; or set `GALAXY_API_KEY`) |

## Post-build Checks & Publishing

After every build, the local tarball is checked:

1. Non-empty, valid gzip archive
2. Packaged `plugins/modules/migrate` is an ELF 64-bit x86-64 binary
3. Collection version matches the requested tag (error with `--publish`, warning otherwise)
4. With `--publish`: the version is not already published on Galaxy

With `--publish`, the script first checks that an API key is given and `ansible-galaxy` is installed locally, so it fails before spending time on a build. It publishes only when every check is green. If the upload fails, the local tarball stays in `~/Downloads/`. The API key is never printed.

## Architecture Behavior

The script automatically handles architecture differences:

### On x86_64 Machine
- ✅ Builds locally in `/tmp/vmware-migration-kit-build-<timestamp>`
- ✅ Fast - no network overhead
- ✅ Verifies binaries are x86_64

### On ARM/Other Architecture
- ⚠️ Requires remote build machine IP
- ✅ Prompts for IP if not provided
- ✅ Builds remotely via SSH
- ✅ Downloads tarball via SCP
- ✅ Verifies remote binaries are x86_64

### Explicit Remote Build
- If you provide `build-ip`, remote build is used regardless of local architecture
- Useful for CI/CD or when you want consistent build environment

## Requirements

### Local Build Requirements
- x86_64 architecture
- Git access to repository
- Make and build dependencies installed
- `file` command available

### Remote Build Requirements
- SSH key authentication to remote machine
- Remote machine must be x86_64
- Remote machine must have:
  - Git access to repository
  - Make and all build dependencies
  - `file` command

## Output

The built collection tarball is placed in `~/Downloads/`:

```
~/Downloads/os_migrate-vmware_migration_kit-<version>.tar.gz
```

## Troubleshooting

### "SSH connection failed"
- Ensure SSH key authentication is set up
- Test manually: `ssh <user>@<ip> "echo OK"`
- Add your SSH key to the remote: `ssh-copy-id <user>@<ip>`

### "Remote machine is not x86_64"
- The remote build machine must be x86_64 architecture
- Check with: `ssh <user>@<ip> "uname -m"`

### "Build failed"
- Check build dependencies are installed
- Local build: ensure Podman/Docker is running
- Remote build: ensure remote has all dependencies
- Check the error output for specific issues

### "already published on Galaxy"
- Galaxy versions are immutable; bump the version in `galaxy.yml` and tag a new release

### "collection version ... does not match tag"
- `galaxy.yml` version was not bumped for the tag; fix the release before publishing

### "Binary verification FAILED"
- This means the built binary is not x86_64
- Should not happen on x86_64 machines
- Indicates a problem with the build environment

## Examples

### Example 1: Local Build (macOS ARM)
```bash
$ /vmw-build-prod v2.2.4

ℹ️  VMware Migration Kit Production Build
ℹ️  ======================================

ℹ️  Latest version: v2.2.4
ℹ️  Current architecture: arm64
⚠️  Architecture is arm64 (not x86_64)
❌ Remote build machine IP required
❌ Usage: /vmw-build-prod [version] [build-ip] [ssh-user]
❌ Example: /vmw-build-prod v2.2.4 192.168.1.100 builder
```

### Example 2: Remote Build
```bash
$ /vmw-build-prod v2.2.4 192.168.1.100 builder

ℹ️  VMware Migration Kit Production Build
ℹ️  ======================================

ℹ️  Latest version: v2.2.4
ℹ️  Current architecture: arm64
ℹ️  Building remotely on builder@192.168.1.100
ℹ️  Testing SSH connection...
✅ Remote architecture: x86_64
ℹ️  Cloning repository on remote...
ℹ️  Checking out version: v2.2.4
ℹ️  Collection version: 2.2.4
ℹ️  Running make build-prod on remote...
✅ Binary verification: x86-64 ELF
ℹ️  Downloading tarball to ~/Downloads/os_migrate-vmware_migration_kit-2.2.4.tar.gz
✅ Remote build complete!
✅ Downloaded: ~/Downloads/os_migrate-vmware_migration_kit-2.2.4.tar.gz
```

### Example 3: Local Build (Linux x86_64)
```bash
$ /vmw-build-prod

ℹ️  VMware Migration Kit Production Build
ℹ️  ======================================

ℹ️  Fetching latest git tag...
ℹ️  Latest version: v2.2.4
ℹ️  Current architecture: x86_64
✅ Architecture is x86_64, building locally
ℹ️  Building locally on x86_64 architecture
ℹ️  Version: v2.2.4
ℹ️  Build directory: /tmp/vmware-migration-kit-build-20260604_153045
ℹ️  Cloning repository...
ℹ️  Checking out version: v2.2.4
ℹ️  Collection version: 2.2.4
ℹ️  Running make build-prod...
✅ Binary verification: x86-64 ELF
ℹ️  Copying tarball to ~/Downloads/os_migrate-vmware_migration_kit-2.2.4.tar.gz
✅ Build complete!
✅ Output: ~/Downloads/os_migrate-vmware_migration_kit-2.2.4.tar.gz
```

## Integration with CI/CD

This skill can be integrated into CI/CD pipelines:

```yaml
# Example GitLab CI
build-production:
  stage: build
  tags:
    - x86_64  # Ensure runner is x86_64
  script:
    - ./.claude/skills/vmw-build-prod/scripts/build.sh $CI_COMMIT_TAG
  artifacts:
    paths:
      - ~/Downloads/*.tar.gz
```

## License

Apache-2.0 (same as VMware Migration Kit project)
