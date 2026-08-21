export const meta = {
  name: 'check-conv-host',
  description: 'Check VMware migration conversion host network requirements and run troubleshooting diagnostics',
  phases: [
    { title: 'Preflight', detail: 'Verify SSH connectivity to the conversion host' },
    { title: 'Network',   detail: 'Check port requirements: 443, 902 to vCenter; 10809 internal' },
    { title: 'Diagnose',  detail: 'Check DNS, metadata service, TLS certs, NBD logs, resolv.conf' },
    { title: 'Report',    detail: 'Summarise findings and generate copy-pasteable fixes' },
  ],
};

// ─── Schemas ──────────────────────────────────────────────────────────────────

const PREFLIGHT_SCHEMA = {
  type: 'object',
  properties: {
    reachable:   { type: 'boolean' },
    ssh_user:    { type: 'string' },
    hostname:    { type: 'string', description: 'hostname -f output from the conversion host' },
    os_release:  { type: 'string', description: 'OS release string' },
    error:       { type: ['string', 'null'] },
  },
  required: ['reachable'],
};

const CHECK_SCHEMA = {
  type: 'object',
  properties: {
    name:    { type: 'string' },
    target:  { type: 'string' },
    success: { type: 'boolean' },
    output:  { type: 'string', description: 'Truncated command output (max 300 chars)' },
    note:    { type: 'string', description: 'Optional explanation or recommendation' },
  },
  required: ['name', 'target', 'success', 'output'],
};

const NETWORK_SCHEMA = {
  type: 'object',
  properties: {
    checks:      { type: 'array', items: CHECK_SCHEMA },
    all_passed:  { type: 'boolean' },
    failed:      { type: 'array', items: { type: 'string' } },
  },
  required: ['checks', 'all_passed', 'failed'],
};

const DIAGNOSE_SCHEMA = {
  type: 'object',
  properties: {
    dns_ok:          { type: 'boolean', description: 'vCenter hostname resolves from conversion host' },
    dns_output:      { type: 'string' },
    metadata_ok:     { type: 'boolean', description: '169.254.169.254 reachable' },
    metadata_output: { type: 'string' },
    tls_ok:          { type: 'boolean', description: 'vCenter TLS cert trusted (if applicable)' },
    tls_output:      { type: 'string' },
    nbd_logs:        { type: 'array', items: { type: 'string' }, description: 'Recent NBD log file paths found in /tmp' },
    nbd_errors:      { type: 'string', description: 'Last 30 lines of the most recent NBD log, or empty if no logs' },
    resolv_conf:     { type: 'string', description: 'Content of /etc/resolv.conf' },
    hosts_file:      { type: 'string', description: 'Non-comment lines from /etc/hosts' },
    issues:          { type: 'array', items: { type: 'string' }, description: 'List of identified problems' },
  },
  required: ['dns_ok', 'metadata_ok', 'tls_ok', 'issues'],
};

const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    summary:      { type: 'string' },
    status:       { type: 'string', enum: ['healthy', 'issues_found', 'critical'] },
    fixes: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          issue:    { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'warning', 'info'] },
          commands: { type: 'array', items: { type: 'string' } },
        },
        required: ['issue', 'severity', 'commands'],
      },
    },
    runbook: {
      type: 'array',
      description: 'Flat ordered list of copy-pasteable shell commands to fix all issues',
      items: { type: 'string' },
    },
  },
  required: ['summary', 'status', 'fixes', 'runbook'],
};

// ─── Parse args and flags ─────────────────────────────────────────────────────
// Usage:
//   virtctl mode (default): <conv-host-ip> --devstack=ubuntu@vmi/... [--identity-file=...] [--ns=...] [--instance-key=...] [--user=...] [--vcenter=...]
//   direct SSH mode:        <conv-host-ip> --via=ssh --ssh-key=~/.ssh/... [--user=...] [--vcenter=...]

const allArgs = (() => {
  if (Array.isArray(args)) return args;
  if (typeof args === 'string') {
    const t = args.trim();
    if (t.startsWith('[')) { try { return JSON.parse(t); } catch(e) {} }
    if (t) return t.split(/\s+/);
  }
  return [];
})();

const flagArgs       = allArgs.filter(a => typeof a === 'string' && a.startsWith('--'));
const positionalArgs = allArgs.filter(a => typeof a !== 'string' || !a.startsWith('--'));

const getFlag = (prefix, fallback) => {
  const f = flagArgs.find(a => a.startsWith(prefix));
  return f ? f.slice(prefix.length) : fallback;
};

// Connection args
const convHostArg  = positionalArgs[0] || '';   // e.g. <conv-host-fip> or cloud-user@<conv-host-fip>
const convHostIp   = convHostArg.includes('@') ? convHostArg.split('@')[1] : convHostArg;
const convHostUser = convHostArg.includes('@') ? convHostArg.split('@')[0]
                   : getFlag('--user=', 'cloud-user');

if (!convHostIp) {
  throw new Error(
    'Missing conversion host IP.\n' +
    'Usage:\n' +
    '  /check-conv-host <conv-host-ip> --devstack=ubuntu@vmi/<name> [--identity-file=<path>] [--vcenter=<ip>]\n' +
    '  /check-conv-host <conv-host-ip> --via=ssh --ssh-key=<path> [--vcenter=<ip>]'
  );
}

const via          = getFlag('--via=', 'virtctl');   // 'virtctl' | 'ssh'
const devstackVmi  = getFlag('--devstack=', '');     // e.g. ubuntu@vmi/<dst-vmi-name>
const ns           = getFlag('--ns=', '');
const identityFile = getFlag('--identity-file=', '~/.ssh/id_rsa');
const instanceKey  = getFlag('--instance-key=', '/opt/stack/.ssh/conv_host'); // key PATH ON the devstack
const localSshKey  = getFlag('--ssh-key=', '~/.ssh/id_rsa');                   // local key for direct SSH
const vcenter      = getFlag('--vcenter=', '');      // vCenter IP or FQDN (optional)
const osAuthUrl    = getFlag('--openstack-url=', '');

if (via === 'virtctl' && !devstackVmi) {
  throw new Error(
    'virtctl mode requires --devstack=ubuntu@vmi/<name>.\n' +
    'Either pass --devstack or use --via=ssh for direct SSH access.'
  );
}
if (via === 'virtctl' && !ns) {
  throw new Error('virtctl mode requires --ns=<namespace>. Pass your Kubernetes namespace.');
}

// ─── SSH helper ───────────────────────────────────────────────────────────────
// Returns the shell command string to run `cmd` on the conversion host.
const vcBase = `virtctl -n ${ns} ssh --identity-file="${identityFile}" --local-ssh-opts='-o IdentitiesOnly=yes'`;

const convSsh = (cmd) => {
  if (via === 'ssh') {
    // Direct SSH from local machine
    return `ssh -i ${localSshKey} -o StrictHostKeyChecking=no -o ConnectTimeout=15 ${convHostUser}@${convHostIp} "${cmd}"`;
  }
  // Via devstack: virtctl → devstack → conversion host
  return `${vcBase} ${devstackVmi} -c "ssh -i ${instanceKey} -o StrictHostKeyChecking=no -o ConnectTimeout=15 ${convHostUser}@${convHostIp} '${cmd}'"`;
};

// Describe how to reach the conversion host (for agent prompts)
const accessDescription = via === 'ssh'
  ? `Direct SSH: ssh -i ${localSshKey} -o StrictHostKeyChecking=no ${convHostUser}@${convHostIp} "CMD"`
  : `Via devstack VMI (virtctl → devstack → instance):\n  ${vcBase} ${devstackVmi} -c "ssh -i ${instanceKey} -o StrictHostKeyChecking=no ${convHostUser}@${convHostIp} 'CMD'"`;

log(`Conversion host: ${convHostUser}@${convHostIp}`);
log(`Access mode    : ${via}`);
if (via === 'virtctl') log(`Devstack VMI   : ${devstackVmi}`);
if (vcenter)   log(`vCenter target : ${vcenter}`);
if (osAuthUrl) log(`OpenStack URL  : ${osAuthUrl}`);

// ─── PHASE: Preflight ─────────────────────────────────────────────────────────

phase('Preflight');
log('Verifying SSH connectivity to the conversion host...');

const preflight = await agent(`
Verify SSH connectivity to the conversion host and collect basic system info.
Use the Bash tool.

Access pattern:
${accessDescription}

Run the following commands:
1. Test SSH:
   ${convSsh('echo SSH_OK && hostname -f && cat /etc/os-release | head -3')}

2. If SSH fails:
   - In virtctl mode: first verify devstack login with:
     ${vcBase} ${devstackVmi} -c "echo DEVSTACK_OK"
   - Check if the instance key exists on devstack:
     ${vcBase} ${devstackVmi} -c "ls -la ${instanceKey} 2>&1"
   - Try alternative users (centos, ubuntu, ec2-user) if cloud-user fails

Return:
  reachable   = true/false
  ssh_user    = actual user that worked
  hostname    = output of hostname -f
  os_release  = first line of /etc/os-release
  error       = error message if failed, null otherwise
`, { label: 'preflight', phase: 'Preflight', schema: PREFLIGHT_SCHEMA });

if (!preflight || !preflight.reachable) {
  log('ERROR: Cannot reach the conversion host.');
  log(preflight?.error || 'SSH failed. Check IP, key, and network path.');
  return {
    status: 'error',
    message: `Cannot reach conversion host ${convHostUser}@${convHostIp}.\n${preflight?.error || ''}\n\nCheck:\n  - Is the floating IP correct?\n  - Does the key exist? ${via === 'virtctl' ? `(${instanceKey} on devstack)` : `(${localSshKey} locally)`}\n  - Is port 22 open on the conversion host?`,
  };
}
log(`Connected: ${preflight.hostname || convHostIp} (${preflight.os_release || 'unknown OS'})`);

// ─── PHASE: Network ───────────────────────────────────────────────────────────

phase('Network');
log('Checking port requirements...');

const networkResult = await agent(`
Check all VMware migration network requirements from the conversion host.
Use the Bash tool. Run each check as a SEPARATE command.

Access pattern:
${accessDescription}

─── PORT CHECKS ──────────────────────────────────────────────────────────────

Check 1 — Port 443/TCP to vCenter (VMware API, authentication, VDDK)
${vcenter
  ? `${convSsh(`nc -zv ${vcenter} 443 2>&1 | tail -1`)}
   Also try: ${convSsh(`curl -sk --max-time 10 -o /dev/null -w '%{http_code}' https://${vcenter}/sdk 2>&1`)}
   success = "succeeded" or "Connected" in nc output, OR http_code is 200/400/401/403/404 (any response = port open)`
  : 'vCenter not specified — record success=true, output="skipped: no --vcenter provided", note="Pass --vcenter=<ip> to check"'}

Check 2 — Port 902/TCP to ESXi/vCenter (NBD/NFC disk access — critical for migration)
${vcenter
  ? `${convSsh(`nc -zv ${vcenter} 902 2>&1 | tail -1`)}
   Also try: ${convSsh(`timeout 5 bash -c 'echo > /dev/tcp/${vcenter}/902' 2>&1 && echo 'open' || echo 'closed'`)}
   success = "succeeded" or "Connected" or "open" in output`
  : 'vCenter not specified — record success=true, output="skipped: no --vcenter provided", note="Pass --vcenter=<ip> to check"'}

Check 3 — Port 22/TCP ingress (SSH remote management)
Already confirmed reachable (preflight passed). Record success=true.

Check 4 — Port 10809/TCP internal (NBDKit local server — no firewall rule required)
${convSsh(`ss -tlnp 'sport = :10809' 2>&1; sudo ss -tlnp 'sport = :10809' 2>&1`)}
This port is used when a migration is actively running. If no migration is in progress,
it should be empty — that is NORMAL. Record success=true unless actively running a
migration AND it's missing. Output the listening state.

${vcenter ? `Check 5 — Internet/DNS reachability for vCenter
${convSsh(`getent hosts ${vcenter} 2>&1 || nslookup ${vcenter} 2>&1 | head -8`)}
success = output contains an IP address` : ''}

Return all checks. Set all_passed=true only if checks 1 and 2 pass (or were skipped).
`, { label: 'network-checks', phase: 'Network', schema: NETWORK_SCHEMA });

const netPassed = networkResult?.all_passed ?? false;
const netFailed = networkResult?.failed ?? [];
log(`Network: ${netPassed ? 'ALL PASSED' : 'FAILED: ' + netFailed.join(', ')}`);

// ─── PHASE: Diagnose ─────────────────────────────────────────────────────────

phase('Diagnose');
log('Running troubleshooting diagnostics...');

const diagnose = await agent(`
Run troubleshooting diagnostics on the conversion host for VMware migration.
Use the Bash tool.

Access pattern:
${accessDescription}

─── 1. DNS RESOLUTION ────────────────────────────────────────────────────────
${vcenter
  ? `${convSsh(`getent hosts ${vcenter} 2>&1 || host ${vcenter} 2>&1 | head -5`)}
   success = output contains an IP address`
  : 'No vCenter specified — collect resolv.conf only and set dns_ok=true (skipped)'}

─── 2. /etc/resolv.conf ──────────────────────────────────────────────────────
${convSsh('cat /etc/resolv.conf')}

─── 3. /etc/hosts (non-comment lines) ───────────────────────────────────────
${convSsh("grep -v '^#' /etc/hosts | grep -v '^$'")}

─── 4. OPENSTACK METADATA SERVICE (169.254.169.254) ─────────────────────────
${convSsh('curl -s --max-time 5 http://169.254.169.254/openstack/latest/meta_data.json 2>&1 | head -3')}
success = JSON response (contains "uuid" or similar). Failure shows "no route to host".
If failed, the workaround is to set import_workloads_instance_uuid in the playbook.

─── 5. TLS CERTIFICATE CHECK ─────────────────────────────────────────────────
${vcenter
  ? `${convSsh(`curl -sv --max-time 10 https://${vcenter}/sdk 2>&1 | grep -iE '(SSL|TLS|certificate|x509|issuer|subject|error)' | head -10`)}
   tls_ok = true if NO "certificate signed by unknown authority" or "x509" error in output`
  : 'No vCenter — set tls_ok=true (skipped)'}

─── 6. NBD/NBDKIT LOGS ──────────────────────────────────────────────────────
${convSsh('ls /tmp/osm-nbdkit-*.log 2>/dev/null | head -10')}
${convSsh('ls /tmp/osm-nbdkit-*.log 2>/dev/null | tail -1 | xargs -I{} tail -30 {} 2>/dev/null || echo "no logs found"')}
Look for: "server has no export named", "port 902", "VDDK", "Failed to connect", "vddk: config_complete".

─── 7. VDDK / NBDKIT AVAILABILITY ──────────────────────────────────────────
${convSsh('which nbdkit 2>&1 && nbdkit --version 2>&1 | head -2')}
${convSsh('which nbdcopy 2>&1 && nbdcopy --version 2>&1 | head -2')}
${convSsh('ls /usr/lib/nbdkit/plugins/nbdkit-vddk-plugin.so 2>/dev/null || ls /usr/lib64/nbdkit/plugins/nbdkit-vddk-plugin.so 2>/dev/null || echo "VDDK plugin not found"')}

─── 8. OPENSTACK AUTH ──────────────────────────────────────────────────────
${osAuthUrl
  ? `${convSsh(`curl -s --max-time 10 -o /dev/null -w '%{http_code}' ${osAuthUrl} 2>&1`)}
   success = 200, 300, 301, 400, 401`
  : 'No OpenStack URL specified — skip'}
${convSsh('ls ~/clouds.yaml ~/.config/openstack/clouds.yaml /etc/openstack/clouds.yaml 2>/dev/null | head -3')}

Compile a list of issues: anything that would block or impair migration.
Return all findings. Set dns_ok=false if vCenter hostname does not resolve.
Set metadata_ok=false if metadata service is unreachable.
Set tls_ok=false if TLS certificate errors are found.
`, { label: 'diagnose', phase: 'Diagnose', schema: DIAGNOSE_SCHEMA });

const issueCount = diagnose?.issues?.length ?? 0;
log(`Diagnostics: ${issueCount} issue(s) found`);
if (issueCount > 0) {
  for (const issue of diagnose.issues) log(`  - ${issue}`);
}

// ─── PHASE: Report ────────────────────────────────────────────────────────────

phase('Report');
log('Generating remediation report...');

const networkChecks = networkResult?.checks ?? [];
const diagIssues    = diagnose?.issues ?? [];

const report = await agent(`
Generate a concise remediation report for a VMware migration conversion host.

Conversion host: ${convHostUser}@${convHostIp}
Access mode    : ${via}
vCenter target : ${vcenter || '(not specified)'}

─── Network check results ────────────────────────────────────────────────────
${JSON.stringify(networkChecks, null, 2)}

─── Diagnostic findings ──────────────────────────────────────────────────────
DNS OK        : ${diagnose?.dns_ok}
DNS output    : ${diagnose?.dns_output || ''}
Metadata OK   : ${diagnose?.metadata_ok}
Metadata out  : ${diagnose?.metadata_output || ''}
TLS OK        : ${diagnose?.tls_ok}
TLS output    : ${diagnose?.tls_output || ''}
resolv.conf   : ${diagnose?.resolv_conf || ''}
/etc/hosts    : ${diagnose?.hosts_file || ''}
NBD logs      : ${JSON.stringify(diagnose?.nbd_logs)}
NBD errors    : ${diagnose?.nbd_errors || '(none)'}
Issues found  : ${JSON.stringify(diagIssues)}

─── Reference fixes ──────────────────────────────────────────────────────────
Port 902 blocked (critical — migration will fail):
  Contact network admin to open TCP/902 from ${convHostIp} to ${vcenter || '<vcenter-ip>'}.
  Workaround test: nc -zv ${vcenter || '<vcenter-ip>'} 902

Port 443 blocked:
  Contact network admin to open TCP/443 from ${convHostIp} to ${vcenter || '<vcenter-ip>'}.

DNS not resolving vCenter:
  ${convSsh(`echo '<vcenter-ip> ${vcenter || 'vcenter.domain.local'}' | sudo tee -a /etc/hosts`)}

OpenStack metadata not reachable:
  Set in the os-migrate import playbook:
    import_workloads_instance_uuid: <vm-uuid>

TLS certificate not trusted:
  Set in os-migrate playbook:
    import_workloads_vmware_insecure: true   # for VMware vCenter TLS
    import_workloads_openstack_insecure: true  # for OpenStack API TLS

VDDK plugin not found:
  Check that the conversion host image was built with VDDK support.
  The plugin should be at /usr/lib/nbdkit/plugins/nbdkit-vddk-plugin.so or
  /usr/lib64/nbdkit/plugins/nbdkit-vddk-plugin.so.

NBD "server has no export named" error — common causes:
  1. Port 902 blocked → check network
  2. vCenter FQDN not resolvable → fix DNS or /etc/hosts
  3. Invalid VMDK path in nbdkit command → check migration logs

Manual debug: run nbdkit and nbdcopy from the logs to replay:
  nbdkit --verbose vddk "path/to/guest.vmdk"   # in one shell
  nbdcopy ... nbd://localhost:10809             # in another shell

Generate:
  - summary: one paragraph describing overall health
  - status: 'healthy' | 'issues_found' | 'critical'
  - fixes: ordered by severity (critical first), with exact commands
  - runbook: flat list of copy-pasteable shell commands, critical first
    Use "# comment" lines to label groups. No prose — only valid shell lines.
`, { label: 'report', phase: 'Report', schema: REPORT_SCHEMA });

if (report?.runbook?.length) {
  log('');
  log('═══ COMMANDS TO RUN ════════════════════════════════════════════════════════');
  for (const cmd of report.runbook) log(cmd);
  log('════════════════════════════════════════════════════════════════════════════');
}
log(`Status: ${report?.status ?? 'unknown'}`);

return {
  status:      report?.status ?? 'unknown',
  conv_host:   { ip: convHostIp, user: convHostUser, via, hostname: preflight?.hostname },
  network:     networkResult,
  diagnostics: diagnose,
  report,
};
