# OS-Migrate AI Skills & Agents

A collection of intelligent agents and automation skills for the [os-migrate](https://github.com/os-migrate/os-migrate) Ansible collection, designed to streamline parallel cloud migrations and provide AI-powered assistance throughout the migration lifecycle.

## Overview

This repository provides Claude Code skills and AI agents that automate and enhance various aspects of cloud migration workflows. From development and release automation to customer-facing diagnostic tools, these skills help teams migrate workloads more efficiently and reliably.

## Skill Categories

### Development & Release
Skills that automate the development lifecycle for os-migrate:

- **Release Automation** - Automated release processes for os-migrate components
- **Linting & Quality** - Code quality checks for Golang, Ansible, and Python
- **CI/CD Debugging** - Intelligent analysis of CI pipeline failures
- **Dependency Management** - Automated dependency updates and conflict resolution

### Migration Operations
Customer-facing skills for migration execution and troubleshooting:

- **Migration Log Analysis** - AI-powered investigation of migration failures and errors
- **virt-inspector Integration** - Pre-migration guest inspection and compatibility checks
- **Performance Analysis** - Migration throughput optimization and bottleneck detection
- **Rollback Assistance** - Guided rollback procedures when migrations encounter issues

### Diagnostic & Troubleshooting
Deep diagnostic capabilities for complex migration scenarios:

- **Resource Mapping** - Automated discovery and mapping of source to target resources
- **Network Validation** - Pre and post-migration network connectivity verification
- **State Reconciliation** - Compare expected vs actual state after migration
- **Error Pattern Recognition** - Learn from historical failures to predict and prevent issues

## Getting Started

### Prerequisites

- [Claude Code](https://claude.ai/code) CLI or desktop app
- Access to the os-migrate Ansible collection
- Appropriate cloud credentials for your migration scenario

### Installation

Clone this repository to your local environment:

```bash
git clone https://github.com/os-migrate/migration-skills.git
cd migration-skills
```

Load skills into your Claude Code session:

```bash
# Skills are automatically discovered from the skills/ directory
claude
```

### Usage

Skills can be invoked directly within Claude Code conversations:

```
# Example: Analyze migration logs
/migration-log-analysis --log-path /var/log/os-migrate/latest.log

# Example: Run pre-migration inspection
/virt-inspector --vm vm-name-123 --platform vmware

# Example: Debug CI failure
/ci-debug --build-id 12345 --pipeline release
```

## Skill Development

### Directory Structure

```
migration-skills/
├── skills/
│   ├── release/           # Release automation skills
│   ├── linting/           # Code quality and linting
│   ├── ci-debug/          # CI/CD troubleshooting
│   ├── migration-logs/    # Log analysis and debugging
│   ├── virt-inspector/    # Guest inspection tools
│   └── diagnostics/       # General diagnostic utilities
├── agents/                # Standalone AI agents
└── tests/                 # Skill test suites
```

### Creating a New Skill

1. Create a new directory under `skills/` with your skill name
2. Add a `skill.md` file with skill definition and prompts
3. Include any supporting scripts or resources
4. Add tests to validate skill behavior
5. Update this README with skill documentation

Example skill structure:

```
skills/my-new-skill/
├── skill.md              # Skill definition
├── prompts/              # Reusable prompt templates
├── scripts/              # Helper scripts
└── tests/                # Skill tests
```

## Security

Every pull request goes through automated security checks: secret scanning
(gitleaks, trufflehog), detection of internal leaks and dangerous commands,
skill-specific risks (prompt injection, permission bypass, hidden Unicode),
shellcheck/bandit, and workflow hardening (zizmor). Run them locally with
`scripts/security-check.sh`. See [SECURITY-CHECKS.md](SECURITY-CHECKS.md) for details
and for how to handle false positives.

## Contributing

Contributions are welcome! Whether you're fixing bugs, adding new skills, or improving documentation:

1. Fork this repository
2. Create a feature branch (`git checkout -b feature/amazing-skill`)
3. Commit your changes (`git commit -m 'Add amazing migration skill'`)
4. Push to the branch (`git push origin feature/amazing-skill`)
5. Open a Pull Request

### Contribution Guidelines

- Skills should be well-documented with clear use cases
- Include examples and expected outputs
- Add tests for new functionality
- Follow existing naming conventions
- Keep skills focused and composable
- Run `scripts/security-check.sh` before pushing; never commit real IPs, hostnames, keys or tokens

## Use Cases

### For Migration Engineers
- Quickly diagnose migration failures without manual log parsing
- Validate guest compatibility before initiating migrations
- Optimize migration parameters based on workload characteristics

### For DevOps Teams
- Automate release processes with confidence
- Catch issues early with intelligent linting
- Debug CI failures faster with contextual analysis

### For Platform Teams
- Build migration playbooks with AI assistance
- Create custom migration workflows
- Monitor and optimize large-scale parallel migrations

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Related Projects

- [os-migrate](https://github.com/os-migrate/os-migrate) - Parallel cloud migration toolkit
- [Claude Code](https://claude.ai/code) - AI pair programmer and automation platform

## Support

For questions, issues, or feature requests:

- Open an issue in this repository
- Join the os-migrate community discussions
- Consult the os-migrate documentation

---

