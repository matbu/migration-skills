export const meta = {
  name: 'debug-osm-ci',
  description: 'Debug OpenStack migration environment via virtctl: deploy test instances, check connectivity, compare configs, generate fixes',
  phases: [
    { title: 'Preflight', detail: 'Verify OpenShift login and virtctl connectivity to both VMIs' },
    { title: 'Prelim', detail: 'Deploy fresh CentOS test instances on both clouds via virtctl' },
    { title: 'Checks', detail: 'Test internet, CentOS mirrors, DNS, OpenStack APIs, and cross-host connectivity' },
    { title: 'Compare', detail: 'Collect and compare OpenStack network config between source and destination' },
    { title: 'Solutions', detail: 'Generate concrete, copy-pasteable remediation commands' },
  ],
};

// ─── Schemas ──────────────────────────────────────────────────────────────────

const ACCESS_SCHEMA = {
  type: 'object',
  properties: {
    host_ip:          { type: 'string', description: 'Floating IP of the deployed test instance' },
    ssh_user:         { type: 'string', description: 'SSH user (always cloud-user for CentOS)' },
    instance_ssh_key: { type: 'string', description: 'Local path to the private key for connecting to the instance' },
    ssh_via_proxy:    { type: 'boolean', description: 'True if ProxyJump through devstack was needed' },
    accessible:       { type: 'boolean' },
    deployed_instance:{ type: 'boolean', description: 'True if a test instance was deployed' },
    instance_name:    { type: 'string' },
    openstack_network:{ type: 'string' },
    openstack_image:  { type: 'string' },
    error:            { type: 'string' },
  },
  required: ['accessible'],
};

const CHECKS_SCHEMA = {
  type: 'object',
  properties: {
    side:     { type: 'string' },
    host_ip:  { type: 'string' },
    checks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name:    { type: 'string' },
          target:  { type: 'string' },
          success: { type: 'boolean' },
          output:  { type: 'string', description: 'Truncated command output (max 200 chars)' },
        },
        required: ['name', 'target', 'success'],
      },
    },
    all_passed:   { type: 'boolean' },
    failed_checks:{ type: 'array', items: { type: 'string' } },
  },
  required: ['side', 'host_ip', 'checks', 'all_passed', 'failed_checks'],
};

const COMPARE_SCHEMA = {
  type: 'object',
  properties: {
    source_openstack: { type: 'string', description: 'Human-readable summary of source network config' },
    dest_openstack:   { type: 'string', description: 'Human-readable summary of destination network config' },
    differences: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          area:              { type: 'string', description: 'e.g. router external gateway, subnet DNS, security group' },
          source_value:      { type: 'string' },
          dest_value:        { type: 'string' },
          likely_root_cause: { type: 'string' },
          severity:          { type: 'string', enum: ['critical', 'warning', 'info'] },
        },
        required: ['area', 'likely_root_cause', 'severity'],
      },
    },
  },
  required: ['differences'],
};

const SOLUTION_SCHEMA = {
  type: 'object',
  properties: {
    fixes: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          issue:          { type: 'string' },
          severity:       { type: 'string', enum: ['critical', 'warning', 'info'] },
          where_to_run:   { type: 'string', description: 'e.g. "destination devstack host" or "destination test instance"' },
          commands:       { type: 'array', items: { type: 'string' } },
          verify_command: { type: 'string', description: 'Command to confirm the fix worked' },
          explanation:    { type: 'string' },
        },
        required: ['issue', 'severity', 'where_to_run', 'commands'],
      },
    },
    summary:            { type: 'string' },
    verification_steps: { type: 'array', items: { type: 'string' } },
    quick_fix_runbook:  {
      type: 'array',
      description: 'Flat ordered list of exact shell commands to run to fix all issues, critical first. Use "# comment" lines to label each group. No explanations — just commands.',
      items: { type: 'string' },
    },
  },
  required: ['fixes', 'summary', 'quick_fix_runbook'],
};

// ─── Parse args and flags ─────────────────────────────────────────────────────
// Flags start with '--'; positional args are everything else.
// Example: /debug-osm-ci ubuntu@vmi/src-vm ubuntu@vmi/dst-vm ~/.ssh/your_key --ns=<your-namespace> --only=compare,solutions

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

// Positional args: src VMI, dst VMI, identity file
const srcDevstack  = positionalArgs[0] || '';   // e.g. ubuntu@vmi/<src-vmi-name>
const dstDevstack  = positionalArgs[1] || '';   // e.g. ubuntu@vmi/<dst-vmi-name>
const identityFile = positionalArgs[2] || '~/.ssh/id_rsa';

// Known test instance IPs (optional — auto-discovered in Prelim if absent)
const knownSrcFip = positionalArgs[3] || '';
const knownDstFip = positionalArgs[4] || '';

if (!srcDevstack || !dstDevstack) {
  const missing = [!srcDevstack && 'src_vmi', !dstDevstack && 'dst_vmi'].filter(Boolean).join(', ');
  throw new Error(
    `Missing required VMI connection parameters: ${missing}.\n` +
    `Pass them directly:\n` +
    `  /debug-osm-ci ubuntu@vmi/<src-vmi> ubuntu@vmi/<dst-vmi> [identity-file]\n` +
    `Flags:\n` +
    `  --ns=<namespace>          Kubernetes namespace (required)\n` +
    `  --src-ip=<ip>             Devstack source host IP for Keystone reachability checks\n` +
    `  --dst-ip=<ip>             Devstack dest host IP for Keystone reachability checks\n` +
    `  --only=prelim,checks,...  Run only specific phases`
  );
}

// --ns=<namespace> — Kubernetes namespace for virtctl (required)
const nsFlag = flagArgs.find(a => a.startsWith('--ns='));
const ns = nsFlag ? nsFlag.replace('--ns=', '') : '';
if (!ns) throw new Error('--ns=<namespace> is required. Pass your Kubernetes namespace, e.g. --ns=my-namespace');

// --src-ip / --dst-ip — devstack host IPs for Keystone endpoint checks (optional)
// If absent, the agent will discover them by reading the openrc OS_AUTH_URL.
const srcIpFlag = flagArgs.find(a => a.startsWith('--src-ip='));
const dstIpFlag = flagArgs.find(a => a.startsWith('--dst-ip='));
const srcDevstackHost = srcIpFlag ? srcIpFlag.replace('--src-ip=', '') : null;
const dstDevstackHost = dstIpFlag ? dstIpFlag.replace('--dst-ip=', '') : null;

// --only=<phase>[,<phase>...] — if absent, run all phases
const onlyFlag   = flagArgs.find(a => a.startsWith('--only='));
const onlyPhases = onlyFlag
  ? new Set(onlyFlag.replace('--only=', '').split(',').map(s => s.trim().toLowerCase()))
  : null;

const shouldRun = (p) => !onlyPhases || onlyPhases.has(p);

if (onlyPhases) {
  log(`Running only: ${Array.from(onlyPhases).join(', ')}`);
} else {
  log('Running all phases');
}
log(`Source VMI: ${srcDevstack}, Dest VMI: ${dstDevstack}, Identity: ${identityFile}, NS: ${ns}`);

// ─── Preflight: verify OpenShift/kubectl login ────────────────────────────────
phase('Preflight');
log('Checking OpenShift login and virtctl connectivity...');
const preflight = await agent(`
Verify that the local environment is logged in to OpenShift and can reach the
KubeVirt cluster before attempting any virtctl operations. Use the Bash tool.

1. Check oc/kubectl login:
   oc whoami 2>&1
   If this fails with "Unauthorized" or "connection refused", the user must run:
     oc login <cluster-url> [--token=<token>]
   Get the login command from the OpenShift web console → top-right menu → "Copy login command".

2. Check kubectl context:
   kubectl config current-context 2>&1
   kubectl get nodes --no-headers 2>&1 | head -5

3. Check the target namespace exists and VMIs are visible:
   virtctl -n ${ns} get vmi 2>&1 | head -10
   If namespace not found: verify OSM_NS is correct (current: ${ns})

4. Verify the two target VMIs exist and are Running:
   virtctl -n ${ns} get vmi ${srcDevstack.replace('ubuntu@vmi/', '')} 2>&1
   virtctl -n ${ns} get vmi ${dstDevstack.replace('ubuntu@vmi/', '')} 2>&1

5. Quick connectivity test to source VMI:
   virtctl -n ${ns} ssh --identity-file="${identityFile}" --local-ssh-opts='-o IdentitiesOnly=yes' ${srcDevstack} -c "echo LOGIN_OK" 2>&1

Return a JSON object: { logged_in: bool, src_vmi_reachable: bool, dst_vmi_reachable: bool, error: string|null }
If logged_in is false, set error to the exact oc login command hint and stop — do not proceed.
`, { label: 'preflight-login', phase: 'Preflight', schema: {
  type: 'object',
  properties: {
    logged_in:         { type: 'boolean' },
    src_vmi_reachable: { type: 'boolean' },
    dst_vmi_reachable: { type: 'boolean' },
    error:             { type: ['string', 'null'] },
  },
  required: ['logged_in', 'src_vmi_reachable', 'dst_vmi_reachable'],
}});

if (preflight && !preflight.logged_in) {
  log('ERROR: Not logged in to OpenShift. Cannot proceed.');
  log(preflight.error || 'Run: oc login <cluster-url> --token=<token>');
  log('Get the login command from the OpenShift web console → top-right menu → "Copy login command".');
  return { status: 'error', message: 'OpenShift login required. ' + (preflight.error || 'Run: oc login <cluster-url>') };
}
if (preflight && (!preflight.src_vmi_reachable || !preflight.dst_vmi_reachable)) {
  const which = !preflight.src_vmi_reachable && !preflight.dst_vmi_reachable ? 'both VMIs' : (!preflight.src_vmi_reachable ? srcDevstack : dstDevstack);
  log(`WARNING: Cannot reach ${which}. Check VMI name, namespace, and identity file.`);
  log(preflight.error || '');
}
log(`Login OK — src reachable: ${preflight?.src_vmi_reachable}, dst reachable: ${preflight?.dst_vmi_reachable}`);

// ─── virtctl helpers ──────────────────────────────────────────────────────────
// Base virtctl SSH command (used in every devstack remote call)
const vcBase = `virtctl -n ${ns} ssh --identity-file="${identityFile}" --local-ssh-opts='-o IdentitiesOnly=yes'`;

// Run a command on a devstack VMI:
//   vcCmd(srcDevstack, 'openstack server list')
const vcCmd = (vmi, cmd) => `${vcBase} ${vmi} -c "${cmd}"`;

// ProxyCommand string for SSH to reach instances inside a devstack VM:
//   -o "ProxyCommand=<vcProxy(srcDevstack)>"
const vcProxy = (vmi) => `${vcBase} ${vmi} -- nc %h %p`;

// Full SSH command to reach a test instance inside a devstack VM
const instanceSsh = (vmi, instanceKey, instanceIp) =>
  `ssh -i ${instanceKey} -o "ProxyCommand=${vcProxy(vmi)}" -o StrictHostKeyChecking=no cloud-user@${instanceIp}`;

// ─── Mutable state shared across phases ──────────────────────────────────────

let srcAccess = null, dstAccess = null;
let srcHost   = knownSrcFip, dstHost = knownDstFip;
let srcInstanceKey = '/tmp/debug-conv-test-key-source';
let dstInstanceKey = '/tmp/debug-conv-test-key-destination';
let srcOk = !!knownSrcFip, dstOk = !!knownDstFip;

let srcChecks = null, dstChecks = null;
let srcPassed = true,  dstPassed = true;
let srcFailed = [],    dstFailed = [];

let comparison = null;
let solutions  = null;

// ─── Helper prompts ───────────────────────────────────────────────────────────

const accessCheckPrompt = (side, devstackVmi, localKeyPath) => `
You are deploying a fresh CentOS test instance on the ${side} OpenStack cloud to use as a debug target.
Use the Bash tool to run all commands. Source OpenRC with admin credentials for every OpenStack call.

Access to the devstack VM uses virtctl (KubeVirt), NOT plain SSH:
  ${vcBase} ${devstackVmi} -c "YOUR COMMAND HERE"

Parameters:
  Devstack VMI        : ${devstackVmi}
  virtctl namespace   : ${ns}
  Identity file       : ${identityFile}
  Local key path      : ${localKeyPath}
  Instance name       : debug-conv-test-${side}
  Keypair name        : debug-conv-test-key

─── STEP 1: Generate SSH keypair on devstack ─────────────────────────────────
Run on the devstack VM (overwrite if exists):
  ${vcCmd(devstackVmi, 'ssh-keygen -t ed25519 -f /tmp/debug-conv-test-key -N \'\' -q -y 2>/dev/null; true; ssh-keygen -t ed25519 -f /tmp/debug-conv-test-key -N \'\' -q')}

─── STEP 2: Upload public key to OpenStack (admin project) ───────────────────
Delete existing keypair if present, then create:
  ${vcCmd(devstackVmi, 'source devstack/openrc admin admin && openstack keypair delete debug-conv-test-key 2>/dev/null; openstack keypair create --public-key /tmp/debug-conv-test-key.pub debug-conv-test-key')}

─── STEP 3: Find CentOS image ────────────────────────────────────────────────
  ${vcCmd(devstackVmi, 'source devstack/openrc admin admin && openstack image list --format json')}
Select the first image whose name contains 'centos' (case-insensitive). If none, use the first image available.
Record IMAGE_ID.

─── STEP 4: Find medium-sized flavor ─────────────────────────────────────────
  ${vcCmd(devstackVmi, 'source devstack/openrc admin admin && openstack flavor list --format json')}
Prefer in order: m1.medium, m1.small, ds2G, any flavor with ≥2 GB RAM, then whatever is available.
Record FLAVOR_ID.

─── STEP 5: Find private (non-external) network ──────────────────────────────
  ${vcCmd(devstackVmi, 'source devstack/openrc admin admin && openstack network list --format json')}
Pick a non-external network. Prefer one named 'private'. Record PRIV_NET name.

─── STEP 6: Find public/external network ─────────────────────────────────────
  ${vcCmd(devstackVmi, 'source devstack/openrc admin admin && openstack network list --external --format json')}
Pick the first external network (usually 'public'). Record PUB_NET name.

─── STEP 7: Clean up any existing test instance (idempotent) ────────────────
Check whether the instance already exists:
  ${vcCmd(devstackVmi, `source devstack/openrc admin admin && openstack server show debug-conv-test-${side} -f value -c status 2>/dev/null || echo NOTFOUND`)}

If the instance exists (status is not "NOTFOUND"):
  a) Find its attached floating IP (may be empty if none):
     ${vcCmd(devstackVmi, `source devstack/openrc admin admin && openstack server show debug-conv-test-${side} -f json | python3 -c "import sys,json; d=json.load(sys.stdin); [print(ip['addr']) for net in d.get('addresses',{}).values() for ip in net if ip.get('OS-EXT-IPS:type')=='floating']" 2>/dev/null`)}
  b) Delete the instance and wait:
     ${vcCmd(devstackVmi, `source devstack/openrc admin admin && openstack server delete debug-conv-test-${side} --wait 2>/dev/null; true`)}
  c) Release the old floating IP found in (a), if any:
     ${vcCmd(devstackVmi, 'source devstack/openrc admin admin && openstack floating ip delete <OLD_FIP> 2>/dev/null; true')}

─── STEP 8: Create the test instance ────────────────────────────────────────
Use the admin project, default security group:
  ${vcCmd(devstackVmi, `source devstack/openrc admin admin && openstack server create --image <IMAGE_ID> --flavor <FLAVOR_ID> --network <PRIV_NET> --key-name debug-conv-test-key --security-group default --wait debug-conv-test-${side}`)}

─── STEP 9: Allocate floating IP and attach it ───────────────────────────────
  FIP=$(${vcBase} ${devstackVmi} -c "source devstack/openrc admin admin && openstack floating ip create <PUB_NET> -f value -c floating_ip_address")
  ${vcCmd(devstackVmi, 'source devstack/openrc admin admin && openstack server add floating ip debug-conv-test-' + side + ' $FIP')}
Record the floating IP as HOST_IP.

─── STEP 10: Pull private key to local machine ───────────────────────────────
  ${vcBase} ${devstackVmi} -c "cat /tmp/debug-conv-test-key" > ${localKeyPath}
  chmod 600 ${localKeyPath}

─── STEP 11: Wait for SSH (up to 3 attempts × 30 s) ─────────────────────────
NOTE: virtctl's "-- nc %h %p" ProxyCommand does NOT work with virtctl ≤ 1.8.x
("accepts 1 arg(s)"). Use SSH directly from inside the devstack VM instead:
  for i in 1 2 3; do
    sleep 30
    ${vcBase} ${devstackVmi} -c \
      "ssh -i /tmp/debug-conv-test-key -o StrictHostKeyChecking=no -o ConnectTimeout=15 cloud-user@$HOST_IP 'echo SSH_OK'" && break
  done

─── STEP 12: Discover cluster DNS and fix the private subnet + instance ──────
IMPORTANT: On KubeVirt-hosted devstack, outbound UDP/ICMP to public DNS (8.8.8.8,
1.1.1.1) is blocked by the upstream network. Instances need the Kubernetes cluster
DNS (found in the devstack host's resolvectl) instead.

a) Discover cluster DNS from devstack host:
   CLUSTER_DNS=$(${vcBase} ${devstackVmi} -c \
     "resolvectl status 2>/dev/null | awk '/Current DNS Server:/ {print \\$4; exit}'")
   echo "Cluster DNS: $CLUSTER_DNS"
   If empty, fall back to <cluster-dns-ip> (or your cluster's DNS IP).

b) Update the PRIVATE subnet DNS so future instances get the right nameserver via DHCP:
   ${vcBase} ${devstackVmi} -c "source devstack/openrc admin admin && \
     PRIV_SUBNET=\\\$(openstack subnet list --network private --ip-version 4 --format value -c ID | head -1) && \
     openstack subnet set --dns-nameserver \$CLUSTER_DNS \\\$PRIV_SUBNET && \
     echo 'Private subnet DNS updated'"

c) Fix /etc/resolv.conf on the already-running test instance immediately:
   ${vcBase} ${devstackVmi} -c \
     "ssh -i /tmp/debug-conv-test-key -o StrictHostKeyChecking=no cloud-user@$HOST_IP \
      'echo nameserver \$CLUSTER_DNS | sudo tee /etc/resolv.conf'"

─── STEP 13: Flush stale conntrack entries ───────────────────────────────────
After adding any MASQUERADE rule, stale zone-0 conntrack entries bypass it —
packets leave enp1s0 unmasqueraded and upstream drops replies.
Always flush after MASQUERADE changes:
   ${vcBase} ${devstackVmi} -c "sudo conntrack -D -s <pub-cidr> 2>/dev/null; sudo conntrack -D -d <pub-cidr> 2>/dev/null; echo flushed"

Return:
  host_ip          = the floating IP
  ssh_user         = "cloud-user"
  instance_ssh_key = "${localKeyPath}"
  ssh_via_proxy    = true
  accessible       = true/false
  deployed_instance= true
  instance_name    = "debug-conv-test-${side}"
  openstack_image  = image name used
  openstack_network= private network name used
  error            = error message if failed, otherwise omit
`;

const checkPrompt = (side, convHost, devstackVmi, instanceKey, hostOk, otherConvHost) => {
  if (!hostOk || !convHost) {
    return `The ${side} test instance is not accessible (host="${convHost}"). Return exactly:
{"side":"${side}","host_ip":"${convHost || ''}","checks":[],"all_passed":false,"failed_checks":["SSH unreachable - skipping checks"]}`;
  }

  // SSH to instance via virtctl ProxyCommand (assign to var to avoid quote nesting)
  const sshPrefix = `ssh -i ${instanceKey} -o "ProxyCommand=${vcProxy(devstackVmi)}" -o StrictHostKeyChecking=no cloud-user@${convHost}`;
  const ssh = sshPrefix;

  const keystoneSrcNote = srcDevstackHost
    ? `http://${srcDevstackHost}:5000/`
    : `<src-devstack-ip>:5000/ (discover IP: ${vcCmd(devstackVmi, 'grep OS_AUTH_URL ~/devstack/openrc | grep -oP "(?<=http://)[^/:]+"')})`;
  const keystoneDstNote = dstDevstackHost
    ? `http://${dstDevstackHost}:5000/`
    : `<dst-devstack-ip>:5000/ (discover IP: ${vcCmd(devstackVmi, 'grep OS_AUTH_URL ~/devstack/openrc | grep -oP "(?<=http://)[^/:]+"')})`;

  const crossCheck = otherConvHost
    ? `7. Cross-host ping: ${ssh} "ping -c 3 -W 5 ${otherConvHost} 2>&1"
     success = "0% packet loss" in output`
    : `7. Cross-host ping: SKIP (other host IP unknown) — record success=true, output="skipped"`;

  return `
Run connectivity checks on the ${side} test instance. Use the Bash tool.

Access pattern (virtctl ProxyCommand):
  VCPROXY="${vcProxy(devstackVmi)}"
  ${ssh} "<command>"

Assign VCPROXY to a shell variable first to avoid quoting issues inside ProxyCommand.
Run each check as a SEPARATE SSH call. Truncate output to 200 chars.

1. Internet ICMP:   ${ssh} "ping -c 3 -W 5 8.8.8.8 2>&1"
   success = exit 0 AND "0% packet loss"
   IMPORTANT: KubeVirt upstream networks often block ICMP (the devstack host itself
   also cannot ping 8.8.8.8). If check 2 (HTTPS) passes but ICMP fails, set
   success=false but note "ICMP blocked by network policy — not a devstack issue".
   Do NOT classify this as a devstack config failure if HTTPS works.

2. Internet HTTPS:  ${ssh} "curl -s --max-time 15 -o /dev/null -w '%{http_code}' https://www.google.com"
   success = "200"
   This is the PRIMARY internet connectivity indicator on KubeVirt networks.

3. CentOS mirror:   ${ssh} "curl -s --max-time 20 -o /dev/null -w '%{http_code}' http://mirror.centos.org/"
   success = "200", "301", or "302"

4. CentOS Stream:   ${ssh} "curl -s --max-time 20 -o /dev/null -w '%{http_code}' https://mirror.stream.centos.org/"
   success = "200", "301", or "302"

5. DNS resolution:  ${ssh} "nslookup mirror.centos.org 2>&1 | head -8"
   success = output contains an IP address (x.x.x.x)
   NOTE: If DNS fails and /etc/resolv.conf has 8.8.8.8/1.1.1.1, those nameservers
   are likely unreachable (UDP/53 blocked same as ICMP). The fix is to set the
   private subnet DNS to the cluster DNS and update /etc/resolv.conf on the instance.

6a. Src Keystone:   ${ssh} "curl -s --max-time 10 -o /dev/null -w '%{http_code}' http://${keystoneSrcNote}"
    success = "200", "300", "301", or "401"
    If IP unknown: first run ${vcCmd(devstackVmi, 'grep OS_AUTH_URL ~/devstack/openrc | grep -oP "(?<=http://)[^/:]+"')} to get source devstack IP.

6b. Dst Keystone:   ${ssh} "curl -s --max-time 10 -o /dev/null -w '%{http_code}' http://${keystoneDstNote}"
    success = "200", "300", "301", or "401"

${crossCheck}

8. DNF/YUM repos:   ${ssh} "sudo dnf check-update --assumeno 2>&1 | grep -E '(Error|Cannot|Failed)' | head -5 || echo NO_ERRORS"
   success = "NO_ERRORS" or empty (dnf exit 100 with available updates is also OK)

Set all_passed=true ONLY if checks 1-8 all pass. List failed names in failed_checks.
`;
};

const comparePrompt = (srcFail, dstFail, convHostAvail) => `
You are comparing the OpenStack network configuration between source and destination devstack environments.
Use the Bash tool to collect data from both devstack VMIs via virtctl, then identify differences.

Source devstack VMI  : ${srcDevstack}
Dest devstack VMI    : ${dstDevstack}
virtctl namespace    : ${ns}
Identity file        : ${identityFile}

Access pattern:
  ${vcBase} <devstack-vmi> -c "source devstack/openrc admin admin && <openstack-cmd>"

Source check failures      : ${JSON.stringify(srcFail)}
Destination check failures : ${JSON.stringify(dstFail)}

─── Collect on BOTH devstack VMIs ────────────────────────────────────────────
For each VMI (${srcDevstack} and ${dstDevstack}), run via virtctl:

1. ${vcBase} <vmi> -c "source devstack/openrc admin admin && openstack network list --format json"
2. ${vcBase} <vmi> -c "source devstack/openrc admin admin && openstack subnet list --format json --long"
3. ${vcBase} <vmi> -c "source devstack/openrc admin admin && openstack router list --format json"
4. ${vcBase} <vmi> -c "source devstack/openrc admin admin && openstack router show <each-router-id> --format json"
5. ${vcBase} <vmi> -c "source devstack/openrc admin admin && openstack security group rule list --format json --long"
6. ${vcBase} <vmi> -c "source devstack/openrc admin admin && openstack floating ip list --format json"
7. ${vcBase} <vmi> -c "source devstack/openrc admin admin && openstack port list --format json"

─── KubeVirt-specific: DNS and NAT conntrack ─────────────────────────────────
8. Discover the Kubernetes cluster DNS (reachable from instances via MASQUERADE):
   ${vcBase} <vmi> -c "resolvectl status 2>/dev/null | awk '/Current DNS Server:/ {print \\$4; exit}'"
   This is the CORRECT nameserver for instances. Public DNS (8.8.8.8, 1.1.1.1) is
   unreachable from instances — outbound UDP/ICMP to internet is blocked on KubeVirt
   networks. ICMP to 8.8.8.8 fails even from the devstack host itself.

9. Check PRIVATE subnet DNS (instances get nameservers from DHCP on the private subnet,
   NOT from the public/external subnet):
   ${vcBase} <vmi> -c "source devstack/openrc admin admin && openstack subnet list --network private --ip-version 4 --format json --long"
   Flag as CRITICAL if dns_nameservers contains only 8.8.8.8/1.1.1.1 and NOT the
   cluster DNS — this will cause all DNS failures in instances.

10. Check for stale conntrack entries blocking MASQUERADE:
    ${vcBase} <vmi> -c "sudo conntrack -L 2>/dev/null | grep -E 'UNREPLIED.*8.8.8.8|UNREPLIED.*github' | grep -v '192.168.121.2' | head -5"
    If unmasqueraded entries exist (reply dst is a floating IP, not 192.168.121.x),
    those stale zone-0 entries are bypassing the MASQUERADE rule.

11. Verify MASQUERADE rule and whether packets are correctly masqueraded:
    ${vcBase} <vmi> -c "sudo iptables -t nat -L POSTROUTING -n -v | grep MASQUERADE"
    Expected: a rule matching the public subnet CIDR going out enp1s0.

${convHostAvail ? `─── Collect on EACH accessible test instance (via virtctl ProxyCommand) ─────
Source instance : cloud-user@${srcHost} via ${srcDevstack}  (reachable: ${srcOk})
  VCPROXY="${vcProxy(srcDevstack)}"
  ${instanceSsh(srcDevstack, srcInstanceKey, srcHost)} "<cmd>"

Dest instance   : cloud-user@${dstHost} via ${dstDevstack}  (reachable: ${dstOk})
  VCPROXY="${vcProxy(dstDevstack)}"
  ${instanceSsh(dstDevstack, dstInstanceKey, dstHost)} "<cmd>"

Collect from each instance:
  cat /etc/resolv.conf
  ip route show
  ip addr show
  sudo iptables -t nat -L POSTROUTING -n -v | head -20
  sudo iptables -L FORWARD -n -v | head -20` : `─── Note: test instances not available (prelim was skipped) ─────────────────
Focus on OpenStack API-level comparison only.`}

─── Identify differences that explain the failures ───────────────────────────
Look for:
  - Router missing external gateway → "no internet"
  - Subnet missing DNS nameservers → DNS resolution failures
  - Security group with no egress rules → ping/curl blocked
  - Missing NAT in iptables on devstack → outbound traffic dropped
  - Wrong or missing default route on instance → routing failures
  - Empty /etc/resolv.conf → DNS failures

Return:
  source_openstack : paragraph summarising source network config
  dest_openstack   : paragraph summarising destination network config
  differences      : list of differences with area, source_value, dest_value, likely_root_cause, severity
`;

const solutionsPrompt = (srcFail, dstFail, diff, srcConfig, dstConfig) => `
You are an OpenStack networking expert. Generate precise, copy-pasteable fix commands.

Environment:
  Source devstack VMI  : ${srcDevstack}
  Dest devstack VMI    : ${dstDevstack}
  virtctl namespace    : ${ns}
  Identity file        : ${identityFile}
  Source test instance : cloud-user@${srcHost || '(unknown)'} — key: ${srcInstanceKey}
  Dest test instance   : cloud-user@${dstHost || '(unknown)'} — key: ${dstInstanceKey}

Access pattern for devstack (virtctl):
  ${vcBase} <vmi> -c "source devstack/openrc admin admin && <cmd>"

Access pattern for test instances (virtctl ProxyCommand):
  VCPROXY="${vcProxy('<devstack-vmi>')}"
  ssh -i <instance-key> -o "ProxyCommand=$VCPROXY" -o StrictHostKeyChecking=no cloud-user@<fip> "<cmd>"

Failed checks:
  Source      : ${JSON.stringify(srcFail)}
  Destination : ${JSON.stringify(dstFail)}

Config differences:
${JSON.stringify(diff, null, 2)}

Source OpenStack config : ${srcConfig || 'not collected'}
Dest OpenStack config   : ${dstConfig || 'not collected'}

Generate fixes ordered by impact (most critical first):
  1. One-sentence description of the issue
  2. WHERE to run (e.g. "destination devstack VMI, after source devstack/openrc admin admin")
  3. Exact shell commands — use real IDs/names from the diff data above
  4. verify_command to confirm the fix worked

─── Reference fixes (use only what is relevant) ──────────────────────────────
Missing iptables MASQUERADE + mandatory conntrack flush:
  ${vcCmd(dstDevstack, 'sudo iptables -t nat -A POSTROUTING -s <pub-cidr> -o enp1s0 -j MASQUERADE')}
  CRITICAL — always flush stale conntrack entries after adding MASQUERADE, otherwise
  existing zone-0 entries bypass the rule and packets leave enp1s0 unmasqueraded:
  ${vcCmd(dstDevstack, 'sudo conntrack -D -s <pub-cidr> 2>/dev/null; sudo conntrack -D -d <pub-cidr> 2>/dev/null; echo flushed')}
  Verify: ${vcCmd(dstDevstack, 'sudo iptables -t nat -L POSTROUTING -n -v | grep MASQUERADE')}
  Confirm masquerade is working (reply dst should be 192.168.121.x, not the floating IP):
  ${vcCmd(dstDevstack, 'sudo conntrack -L 2>/dev/null | grep 8.8.8.8 | head -3')}

Fix private subnet DNS — instances get DNS from the private subnet DHCP, NOT the public subnet:
  CLUSTER_DNS=$(${vcBase} ${dstDevstack} -c "resolvectl status 2>/dev/null | awk '/Current DNS Server:/ {print \\$4; exit}'" | tr -d '\\r\\n')
  ${vcCmd(dstDevstack, 'source devstack/openrc admin admin && PRIV_SUBNET=$(openstack subnet list --network private --ip-version 4 --format value -c ID | head -1) && openstack subnet set --dns-nameserver \$CLUSTER_DNS \$PRIV_SUBNET && echo updated')}
  Then fix running instances directly (new instances will get it from DHCP):
  ssh -i <instance-key> ... cloud-user@<fip> "echo \"nameserver \$CLUSTER_DNS\" | sudo tee /etc/resolv.conf"

Missing router external gateway:
  ${vcCmd(dstDevstack, 'source devstack/openrc admin admin && PUB=$(openstack network list --external -f value -c ID | head -1) && openstack router set --external-gateway $PUB <router-id>')}
  Verify: ${vcCmd(dstDevstack, 'source devstack/openrc admin admin && openstack router show <router-id> | grep external_gateway_info')}

Missing subnet DNS:
  ${vcCmd(dstDevstack, 'source devstack/openrc admin admin && openstack subnet set --dns-nameserver 8.8.8.8 --dns-nameserver 8.8.4.4 <subnet-id>')}
  Verify: ${vcCmd(dstDevstack, 'source devstack/openrc admin admin && openstack subnet show <subnet-id> | grep dns_nameservers')}

No egress security group rules (fresh devstack):
  ${vcCmd(dstDevstack, 'source devstack/openrc admin admin && openstack security group rule create --protocol any --direction egress --ethertype IPv4 default')}
  ${vcCmd(dstDevstack, 'source devstack/openrc admin admin && openstack security group rule create --protocol any --direction egress --ethertype IPv6 default')}
  Verify: ${vcCmd(dstDevstack, 'source devstack/openrc admin admin && openstack security group rule list default --egress')}

Fix /etc/resolv.conf on destination instance:
  VCPROXY="${vcProxy(dstDevstack)}"
  ssh -i ${dstInstanceKey} -o "ProxyCommand=$VCPROXY" -o StrictHostKeyChecking=no cloud-user@${dstHost || '<dst-fip>'} "echo -e 'nameserver 8.8.8.8\\nnameserver 8.8.4.4' | sudo tee /etc/resolv.conf"

Fix missing default route on instance:
  GW=$(${vcBase} ${dstDevstack} -c "source devstack/openrc admin admin && openstack subnet show <subnet-id> -f value -c gateway_ip")
  VCPROXY="${vcProxy(dstDevstack)}"
  ssh -i ${dstInstanceKey} -o "ProxyCommand=$VCPROXY" -o StrictHostKeyChecking=no cloud-user@${dstHost || '<dst-fip>'} "sudo ip route replace default via $GW"

Restart neutron L3 agent if NAT is broken:
  ${vcCmd(dstDevstack, 'sudo systemctl restart devstack@q-l3.service')}

Cleanup test instances (run after debugging):
  ${vcCmd(srcDevstack, 'source devstack/openrc admin admin && openstack server delete debug-conv-test-source --wait && openstack floating ip delete ' + (srcHost || '<src-fip>') + ' && openstack keypair delete debug-conv-test-key 2>/dev/null')}
  ${vcCmd(dstDevstack, 'source devstack/openrc admin admin && openstack server delete debug-conv-test-destination --wait && openstack floating ip delete ' + (dstHost || '<dst-fip>') + ' && openstack keypair delete debug-conv-test-key 2>/dev/null')}

Provide summary and verification_steps (ordered list of commands to confirm environment is healthy after fixes).

─── KubeVirt network policy (NOT a devstack issue, no fix needed) ────────────
ICMP (ping) to external IPs is blocked at the upstream KubeVirt network level.
Even the devstack host itself cannot ping 8.8.8.8. This is a network policy, not
a devstack configuration problem. Use curl/HTTP checks instead of ping to verify
internet connectivity. Do NOT list ICMP failure as a fix item if HTTPS passes.

─── quick_fix_runbook (REQUIRED) ─────────────────────────────────────────────
A flat, ordered array of exact shell commands to paste and run, one by one, to
fix ALL issues (critical first, then warnings). Rules:
  - Include "# Fix N (SEVERITY) — short label" comment lines before each group
  - Include "# Verify:" comment line followed by the verify command after each group
  - No prose, no markdown, no explanations — only valid shell lines and # comments
  - Use real IPs, keys, IDs from the data above (not placeholders)
  - Use virtctl for devstack access, SSH+ProxyCommand (via virtctl) for instances
  - Order: critical fixes first, then warnings, then final verification sweep
`;

// ─── PHASE: Prelim ────────────────────────────────────────────────────────────

if (shouldRun('prelim')) {
  phase('Prelim');
  log('Deploying fresh CentOS test instances on source and destination in parallel...');

  const prelimResults = await parallel([
    () => agent(accessCheckPrompt('source', srcDevstack, '/tmp/debug-conv-test-key-source'), {
      label: 'prelim-source', phase: 'Prelim', schema: ACCESS_SCHEMA,
    }),
    () => agent(accessCheckPrompt('destination', dstDevstack, '/tmp/debug-conv-test-key-destination'), {
      label: 'prelim-dest', phase: 'Prelim', schema: ACCESS_SCHEMA,
    }),
  ]);

  srcAccess = prelimResults[0];
  dstAccess = prelimResults[1];

  if (srcAccess && srcAccess.host_ip)          { srcHost = srcAccess.host_ip; srcOk = srcAccess.accessible; }
  if (srcAccess && srcAccess.instance_ssh_key)   srcInstanceKey = srcAccess.instance_ssh_key;
  if (dstAccess && dstAccess.host_ip)          { dstHost = dstAccess.host_ip; dstOk = dstAccess.accessible; }
  if (dstAccess && dstAccess.instance_ssh_key)   dstInstanceKey = dstAccess.instance_ssh_key;

  log(`Source instance : cloud-user@${srcHost || 'unknown'} (key: ${srcInstanceKey}) — ${srcOk ? 'reachable' : 'UNREACHABLE'}`);
  log(`Dest instance   : cloud-user@${dstHost || 'unknown'} (key: ${dstInstanceKey}) — ${dstOk ? 'reachable' : 'UNREACHABLE'}`);

  if (!srcOk && !dstOk) {
    const srcErr = (srcAccess && srcAccess.error) || 'deployment or SSH failed';
    const dstErr = (dstAccess && dstAccess.error) || 'deployment or SSH failed';
    log(`ERROR: Could not reach either test instance.`);
    log(`  Source (${srcDevstack}): ${srcErr}`);
    log(`  Destination (${dstDevstack}): ${dstErr}`);
    return {
      status: 'error',
      message: `Could not deploy/reach test instances.\n  Source: ${srcErr}\n  Destination: ${dstErr}\n\nCheck:\n  1. ${vcCmd(srcDevstack, 'echo ok')}\n  2. Verify devstack OpenRC: ${vcCmd(srcDevstack, 'source devstack/openrc admin admin && openstack token issue')}`,
      source_access: srcAccess,
      dest_access: dstAccess,
    };
  }
} else {
  log('Skipping Prelim (--only flag set). Instance IPs and keys are unknown — some phases may be limited.');
}

// ─── PHASE: Checks ────────────────────────────────────────────────────────────

if (shouldRun('checks')) {
  phase('Checks');
  log('Running connectivity checks on source and destination instances in parallel...');

  const checkResults = await parallel([
    () => agent(checkPrompt('source', srcHost, srcDevstack, srcInstanceKey, srcOk, dstHost), {
      label: 'checks-source', phase: 'Checks', schema: CHECKS_SCHEMA,
    }),
    () => agent(checkPrompt('destination', dstHost, dstDevstack, dstInstanceKey, dstOk, srcHost), {
      label: 'checks-dest', phase: 'Checks', schema: CHECKS_SCHEMA,
    }),
  ]);

  srcChecks = checkResults[0];
  dstChecks = checkResults[1];
  srcPassed = !!(srcChecks && srcChecks.all_passed);
  dstPassed = !!(dstChecks && dstChecks.all_passed);
  srcFailed = (srcChecks && srcChecks.failed_checks) || [];
  dstFailed = (dstChecks && dstChecks.failed_checks) || [];

  log(`Source      : ${srcPassed ? 'ALL PASSED' : 'FAILED: ' + srcFailed.join(', ')}`);
  log(`Destination : ${dstPassed ? 'ALL PASSED' : 'FAILED: ' + dstFailed.join(', ')}`);

  if (!onlyPhases && srcPassed && dstPassed) {
    log('All checks passed on both sides! Migration environment looks healthy.');
    return {
      status: 'healthy',
      source:      { access: srcAccess, checks: srcChecks },
      destination: { access: dstAccess, checks: dstChecks },
      message: 'All connectivity checks passed. Environment is ready for migration.',
    };
  }
} else {
  log('Skipping Checks (--only flag set).');
}

// ─── PHASE: Compare ───────────────────────────────────────────────────────────

if (shouldRun('compare')) {
  phase('Compare');
  const convHostAvail = srcOk || dstOk;
  const issuesSide = !srcPassed && !dstPassed ? 'both source and destination'
                   : !srcPassed               ? 'source'
                   : !dstPassed               ? 'destination'
                   :                            'both environments';
  log(`Gathering OpenStack config to compare ${issuesSide}...`);

  comparison = await agent(comparePrompt(srcFailed, dstFailed, convHostAvail), {
    label: 'compare-configs', phase: 'Compare', schema: COMPARE_SCHEMA,
  });

  const diffCount = (comparison && comparison.differences) ? comparison.differences.length : 0;
  log(`Found ${diffCount} configuration difference(s)`);
} else {
  log('Skipping Compare (--only flag set).');
}

// ─── PHASE: Solutions ─────────────────────────────────────────────────────────

if (shouldRun('solutions')) {
  phase('Solutions');
  log('Generating concrete remediation commands...');

  const diff      = (comparison && comparison.differences)      || [];
  const srcConfig = (comparison && comparison.source_openstack) || '';
  const dstConfig = (comparison && comparison.dest_openstack)   || '';

  solutions = await agent(solutionsPrompt(srcFailed, dstFailed, diff, srcConfig, dstConfig), {
    label: 'generate-solutions', phase: 'Solutions', schema: SOLUTION_SCHEMA,
  });

  if (solutions && solutions.quick_fix_runbook && solutions.quick_fix_runbook.length) {
    log('');
    log('═══ COMMANDS TO RUN ════════════════════════════════════════════════════════');
    for (const cmd of solutions.quick_fix_runbook) {
      log(cmd);
    }
    log('════════════════════════════════════════════════════════════════════════════');
  }
  log('Analysis complete!');
} else {
  log('Skipping Solutions (--only flag set).');
}

// ─── Return ───────────────────────────────────────────────────────────────────

return {
  status: srcPassed && dstPassed ? 'healthy'
        : srcPassed              ? 'destination_issues'
        : dstPassed              ? 'source_issues'
        :                          'both_issues',
  phases_run: onlyPhases ? Array.from(onlyPhases) : ['prelim', 'checks', 'compare', 'solutions'],
  source:      { access: srcAccess, checks: srcChecks },
  destination: { access: dstAccess, checks: dstChecks },
  comparison:  comparison,
  solutions:   solutions,
};
