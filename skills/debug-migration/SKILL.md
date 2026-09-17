---
name: diagnose-migration
description: Diagnose VMware Migration Failures
tags: [debug, migration, vmware, openstack, virt-v2v]
---

# Debug VMware Migration Failures

Analyze migration failures from VMware to OpenStack by pulling logs from the conversion host and using multi-agent AI analysis to identify root causes and suggest solutions.

## Overview

This skill orchestrates multiple specialized agents to:
1. **Pull the migration log** from the conversion host via SSH
2. **Analyze failures** across multiple dimensions (virt-v2v, nbdkit, network, filesystem, authentication)
3. **Search knowledge bases** for known issues and solutions
4. **Synthesize findings** with actionable recommendations
5. **Interactive Q&A** to clarify and explore further

## Usage

```bash
# Basic usage - analyzes log from conversion host
/debug-migration <conversion-host-ip> <log-path>

# Examples
/debug-migration 10.0.108.50 /tmp/osm-nbdkit-myvm-abc123.log
/debug-migration 192.168.1.100 /var/log/migration/failed-vm.log

# With custom SSH user (default: cloud-user)
/debug-migration 10.0.108.50 /tmp/migration.log root
```

## Arguments

1. **conversion-host-ip** (required): IP address or hostname of the conversion host
2. **log-path** (required): Full path to the migration log file on the conversion host
3. **ssh-user** (optional): SSH username (default: cloud-user)

## What It Does

### Phase 1: Log Retrieval
- SSH to conversion host
- Pull the migration log file
- Store locally for analysis
- Validate log format and extract metadata

### Phase 2: Multi-Dimensional Analysis

The workflow spawns **parallel specialist agents**, each analyzing a different failure dimension:

**Agent 1 - Virt-v2v Expert:**
- Filesystem conversion failures
- Driver injection issues
- Windows/Linux-specific problems
- Guest tools compatibility

**Agent 2 - NBDKit Expert:**
- NBDKit server crashes
- VDDK plugin issues
- Disk streaming errors
- Connection timeouts

**Agent 3 - Network Expert:**
- DNS resolution failures (vCenter, ESXi)
- Firewall/port blocking (902/TCP, 443/TCP)
- SSL/TLS certificate issues
- Network timeouts

**Agent 4 - Authentication Expert:**
- vCenter credential failures
- ESXi authentication issues
- Token expiration
- Permission denied errors

**Agent 5 - Storage Expert:**
- Disk format incompatibilities (BTRFS, LVM, etc.)
- Snapshot/CBT issues
- Volume attachment failures
- Out of space errors

### Phase 3: Knowledge Base Search

For each identified issue, agents search:
- VMware documentation
- OpenStack migration guides
- Known issues in GitHub (os-migrate repositories)
- Red Hat knowledge base articles
- Community forums and discussions

### Phase 4: Synthesis & Recommendations

A final **synthesis agent** combines all findings:
- Prioritizes issues by severity
- Removes duplicate/overlapping findings
- Provides step-by-step remediation
- Suggests preventive measures

### Phase 5: Interactive Q&A

After presenting findings, the skill asks:
- "Do you need clarification on any of these issues?"
- "Should I investigate any specific error in more depth?"
- "Would you like me to check related logs or configuration?"

## Output Format

```
🔍 Migration Failure Analysis Report
=====================================

📊 Log Summary:
  - VM: myvm-name
  - Timestamp: 2026-06-04 09:30:15
  - Duration: 45 minutes
  - Exit Code: 1

🚨 Critical Issues Found (2):

1. [CRITICAL] vCenter DNS Resolution Failure
   Category: Network
   Evidence: "Error: getaddrinfo: Name or service not known (vcenter.example.com)"
   Root Cause: Conversion host cannot resolve vCenter hostname
   Solution:
     • Add vCenter IP to /etc/hosts on conversion host
     • Or configure DNS server in OpenStack network
   Commands:
     ssh cloud-user@10.0.108.50 "echo '192.168.1.10 vcenter.example.com' | sudo tee -a /etc/hosts"

2. [CRITICAL] VDDK Authentication Failure
   Category: Authentication  
   Evidence: "vim.fault.NoPermission: Permission denied on object"
   Root Cause: vCenter user lacks required permissions
   Solution:
     • Grant "Virtual Machine > Provisioning > Disk access" permission
     • See: https://docs.redhat.com/vmware-migration-kit/#permissions
   
⚠️  Warnings (1):

1. [WARNING] Slow Disk Transfer Rate
   Category: Performance
   Evidence: "Transfer rate: 2.3 MB/s (expected ~50 MB/s)"
   Impact: Migration taking 10x longer than expected
   Suggestions:
     • Check network bandwidth between conversion host and ESXi
     • Verify no bandwidth throttling on vCenter
     • Consider storage network instead of management network

📚 Related Knowledge Base Articles:
  - KB12345: Troubleshooting vCenter Connectivity
  - GitHub Issue #156: DNS resolution in isolated networks
  - RHEL Documentation: VMware ACL requirements

🎯 Recommended Next Steps:
  1. Fix DNS resolution (5 min)
  2. Verify vCenter permissions (10 min)  
  3. Re-run migration playbook
  4. Monitor transfer rate in new attempt

❓ Questions?
  Type your question below, or say 'done' to finish.
```

## How It Works Internally

The skill uses the **Workflow tool** to orchestrate agents:

```javascript
export const meta = {
  name: 'debug-migration',
  description: 'Multi-agent analysis of VMware migration failures',
  phases: [
    { title: 'Retrieve Log', detail: 'Pull log from conversion host via SSH' },
    { title: 'Analyze', detail: 'Parallel expert agents examine different failure modes' },
    { title: 'Research', detail: 'Search knowledge bases for solutions' },
    { title: 'Synthesize', detail: 'Combine findings and prioritize recommendations' },
  ],
};

// Phase 1: Get the log
phase('Retrieve Log');
const logContent = await agent('Pull log from conversion host', {
  agentType: 'general-purpose',
  schema: LOG_SCHEMA
});

// Phase 2: Parallel analysis by specialists
phase('Analyze');
const analyses = await parallel([
  () => agent('Analyze for virt-v2v failures', {schema: FINDINGS_SCHEMA}),
  () => agent('Analyze for nbdkit failures', {schema: FINDINGS_SCHEMA}),
  () => agent('Analyze for network failures', {schema: FINDINGS_SCHEMA}),
  () => agent('Analyze for auth failures', {schema: FINDINGS_SCHEMA}),
  () => agent('Analyze for storage failures', {schema: FINDINGS_SCHEMA}),
]);

// Phase 3: Research each finding
phase('Research');
const researched = await pipeline(
  analyses.flat().filter(Boolean),
  finding => agent(`Search for solutions to: ${finding.issue}`, {
    schema: SOLUTION_SCHEMA
  })
);

// Phase 4: Synthesize
const report = await agent('Create final report with prioritized recommendations', {
  schema: REPORT_SCHEMA
});

return report;
```

## Requirements

- SSH access to conversion host
- SSH key authentication configured (no password prompts)
- Conversion host must be reachable from your machine
- Log file must exist on conversion host

## Common Issues

**Q: "SSH connection failed"**
- Ensure SSH key is in `~/.ssh/` and added to conversion host
- Check conversion host security group allows SSH (22/TCP)
- Verify IP address is correct

**Q: "Log file not found"**
- Check the log path is correct (case-sensitive)
- Verify log hasn't been rotated/cleaned up
- Look in `/tmp/osm-nbdkit-*.log` for recent logs

**Q: "Analysis found nothing"**
- Log may be incomplete (migration still running?)
- Log format may have changed (please report)
- Try manual inspection first

## Examples

### Example 1: DNS Resolution Failure

```bash
/debug-migration 10.0.108.50 /tmp/osm-nbdkit-testvm-xyz.log
```

**Output:**
```
🚨 Critical Issue: vCenter DNS Resolution Failure

The conversion host cannot resolve 'vcenter.example.com'.

Quick Fix:
  ssh cloud-user@10.0.108.50 "echo '192.168.1.10 vcenter.example.com' | sudo tee -a /etc/hosts"

Then re-run the migration.
```

### Example 2: Permission Denied

```bash
/debug-migration 192.168.1.100 /var/log/migration-failed.log
```

**Output:**
```
🚨 Critical Issue: vCenter Permission Denied

User 'migration@vsphere.local' lacks required permissions.

Required Permissions:
  ✗ Datastore > Browse datastore
  ✗ Virtual Machine > Provisioning > Disk access
  ✗ Virtual Machine > Snapshot > Create snapshot

See: CLAUDE.md section "VMware ACL Requirements"
```

### Example 3: Multiple Issues

```bash
/debug-migration 10.0.108.50 /tmp/complex-failure.log
```

**Output:**
```
🚨 Found 3 Critical Issues:

1. [CRITICAL] NBDKit VDDK Plugin Crash
   Install missing dependency: sudo dnf install nbdkit-vddk-plugin

2. [CRITICAL] Network Timeout to ESXi
   ESXi host 902/TCP blocked by firewall
   
3. [WARNING] BTRFS Filesystem Detected
   Use Fedora conversion host (RHEL kernel lacks BTRFS support)

Recommended: Fix in order listed above.
```

## Tips

- **Run from project root** so agents can access CLAUDE.md for context
- **Keep logs** - the skill saves a local copy to `/tmp/migration-diagnosis-{timestamp}/`
- **Re-run after fixes** to verify the issue is resolved
- **Share findings** - the report can be saved and shared with team

## Advanced: Customize Analysis

To add custom error patterns, edit:
```
~/.claude/skills/debug-migration/resources/known-patterns.yaml
```

Format:
```yaml
patterns:
  - regex: "getaddrinfo.*Name or service not known"
    category: network
    severity: critical
    solution: "Configure DNS or add to /etc/hosts"
```

## See Also

- `/vmw-build-prod` - Build production collection
- `/verify` - Verify a migration manually
- `CLAUDE.md` - Full VMware Migration Kit context
