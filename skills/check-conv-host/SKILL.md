---
name: check-conv-host
description: Check VMware migration conversion host network requirements and run troubleshooting diagnostics
tags: [vmware, migration, conversion-host, network, nbdkit, vddk, os-migrate]
---

# Check Conversion Host — Network Requirements & Troubleshooting

Connects to an os-migrate VMware conversion host and verifies all network requirements,
then runs a full troubleshooting diagnostic: DNS, metadata service, TLS certificates,
NBD/VDDK availability, and migration logs.

## Execution

When this skill is invoked:

**Step 1 — Parse connection arguments.**
Extract the conversion host IP/address, access mode, and optional vCenter from the args.

**Step 2 — Run the workflow:**
```
Workflow({ scriptPath: "~/.claude/skills/check-conv-host/workflow.js", args: [...] })
```

Present results in a structured format with a `COMMANDS TO RUN` runbook at the end.

## Network Requirements (what is checked)

| Port / Protocol | Direction | Source / Destination | Purpose |
|-----------------|-----------|---------------------|---------|
| 443/TCP | Egress | vCenter | VMware API: authentication, VM metadata, snapshots, VDDK |
| 902/TCP | Egress | ESXi hosts / vCenter | Direct disk access via NFC/NBD — **critical for migration** |
| 22/TCP | Ingress | Admin / Ansible Controller | SSH remote management |
| 10809/TCP | Internal | Conversion host (local) | NBDKit local server — no firewall rule required |

## Usage

```bash
# Via devstack VMI (default — requires --devstack)
/check-conv-host <conv-host-fip> \
  --devstack=ubuntu@vmi/<dst-vmi-name> \
  --identity-file=~/.ssh/your_key \
  --ns=<your-namespace> \
  --vcenter=192.168.1.100

# With vCenter FQDN
/check-conv-host <conv-host-fip> \
  --devstack=ubuntu@vmi/<dst-vmi-name> \
  --identity-file=~/.ssh/your_key \
  --vcenter=vcenter.domain.local

# Direct SSH (no devstack hop)
/check-conv-host <conv-host-fip> \
  --via=ssh \
  --ssh-key=~/.ssh/conv_host_key \
  --vcenter=vcenter.domain.local

# With custom SSH user and OpenStack URL check
/check-conv-host centos@<conv-host-fip> \
  --via=ssh \
  --ssh-key=~/.ssh/conv_key \
  --vcenter=vcenter.domain.local \
  --openstack-url=http://192.168.121.2/identity

# With custom instance key path on devstack
/check-conv-host <conv-host-fip> \
  --devstack=ubuntu@vmi/<dst-vmi-name> \
  --identity-file=~/.ssh/your_key \
  --instance-key=/opt/stack/.ssh/conv_host \
  --vcenter=vcenter.domain.local
```

## Arguments

| Position | Argument | Description |
|----------|----------|-------------|
| 1 | `conv_host` | Conversion host IP or `user@ip` (e.g. `<conv-host-fip>` or `cloud-user@<conv-host-fip>`) |

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--via=<mode>` | `virtctl` | Access mode: `virtctl` (via devstack) or `ssh` (direct) |
| `--devstack=<vmi>` | — | Devstack VMI ref (required for virtctl mode, e.g. `ubuntu@vmi/<dst-vmi-name>`) |
| `--ns=<namespace>` | — | Kubernetes namespace for virtctl |
| `--identity-file=<path>` | `~/.ssh/id_rsa` | SSH identity file for virtctl |
| `--instance-key=<path>` | `/opt/stack/.ssh/conv_host` | Path to instance SSH key **on the devstack** (virtctl mode) |
| `--ssh-key=<path>` | `~/.ssh/id_rsa` | Local SSH key for direct SSH mode |
| `--user=<user>` | `cloud-user` | SSH user for the conversion host |
| `--vcenter=<ip-or-fqdn>` | — | vCenter IP or FQDN (optional — port 443/902 checks are skipped if absent) |
| `--openstack-url=<url>` | — | OpenStack auth URL to test reachability (optional) |

## Access Modes

### virtctl (default)

Reaches the conversion host by tunnelling through the devstack VMI via `virtctl`:

```
local → virtctl → devstack VM → SSH → conversion host
```

```bash
# SSH command pattern:
virtctl -n <your-namespace> ssh \
  --identity-file="~/.ssh/your_key" \
  --local-ssh-opts='-o IdentitiesOnly=yes' \
  ubuntu@vmi/<dst-vmi-name> \
  -c "ssh -i /opt/stack/.ssh/conv_host -o StrictHostKeyChecking=no cloud-user@<conv-host-fip> 'CMD'"
```

Note: `virtctl -- nc %h %p` ProxyCommand does **not** work with virtctl ≤ 1.8.x.
The skill uses the two-hop SSH approach instead.

### Direct SSH

SSH directly from the local machine to the conversion host:

```bash
ssh -i ~/.ssh/conv_host_key -o StrictHostKeyChecking=no cloud-user@<conv-host-fip> "CMD"
```

Use this when the conversion host's floating IP is directly reachable.

## Phases

### Preflight
- Verifies SSH connectivity to the conversion host
- Collects hostname and OS release
- Aborts with a clear error if unreachable

### Network
Checks all four port requirements:
- **443/TCP → vCenter**: VMware API (authentication, metadata, VDDK)
- **902/TCP → vCenter/ESXi**: NFC/NBD disk data access (critical — migration fails without this)
- **22/TCP ingress**: confirmed reachable (SSH session is active)
- **10809/TCP internal**: NBDKit local server (only relevant during active migration)

### Diagnose
- **DNS**: vCenter hostname resolution (`getent hosts`, `nslookup`)
- **resolv.conf** and **/etc/hosts**: nameserver and host override config
- **Metadata service** (169.254.169.254): if unreachable, provides workaround
- **TLS certificates**: detects self-signed or untrusted CA errors for vCenter/OpenStack
- **NBD logs**: finds `/tmp/osm-nbdkit-*.log` files and extracts last 30 lines
- **VDDK plugin**: verifies nbdkit and the vddk plugin are installed
- **OpenStack auth**: tests the configured auth URL (if provided)

### Report
Generates a prioritised fix list and a copy-pasteable `COMMANDS TO RUN` runbook.

## Example Output

```
Phase: Preflight
  → Connected: vmware-conversion-host.local (CentOS Stream 9)

Phase: Network
  → Port 443/TCP → vcenter.domain.local : PASS
  → Port 902/TCP → vcenter.domain.local : FAIL (connection refused)
  → Port 22/TCP  → conversion host      : PASS (SSH session active)
  → Port 10809   → localhost            : no service (no migration running — OK)

Phase: Diagnose
  → DNS: vcenter.domain.local → 192.168.1.100  PASS
  → Metadata 169.254.169.254  → FAIL (no route to host)
  → TLS cert                  → FAIL (x509: certificate signed by unknown authority)
  → NBD logs: /tmp/osm-nbdkit-myvm-abc123.log  → errors found

Phase: Report  [2 CRITICAL, 1 WARNING]

═══ COMMANDS TO RUN ═════════════════════════════════════════════
# Fix 1 (CRITICAL) — Port 902 blocked (contact network admin)
nc -zv vcenter.domain.local 902
# Fix 2 (CRITICAL) — TLS cert not trusted — add to playbook:
# import_workloads_vmware_insecure: true
# Fix 3 (WARNING) — Metadata unreachable — add to playbook:
# import_workloads_instance_uuid: <uuid-from-openstack-server-show>
═════════════════════════════════════════════════════════════════
```

## Troubleshooting Reference

### Port 902 blocked (NBD/NFC)
Port 902 must be open from the conversion host to the vCenter/ESXi hosts.
This is the **most common cause** of migration failure (`nbdkit: error: server has no export named ''`).

```bash
# Test from conversion host:
nc -zv <vcenter-ip> 902
# or:
curl -v telnet://<vcenter-ip>:902
```

### DNS not resolving vCenter
```bash
# Add to /etc/hosts on conversion host:
echo "<vcenter-ip> vcenter.domain.local" | sudo tee -a /etc/hosts
```

### OpenStack metadata service unreachable
```
Failed to fetch metadata: ... dial tcp 169.254.169.254:80: connect: no route to host
```
Workaround — set in os-migrate import playbook:
```yaml
import_workloads_instance_uuid: <uuid>
```

### TLS certificate not trusted
```yaml
# In os-migrate import playbook:
import_workloads_vmware_insecure: true    # skip VMware vCenter TLS verification
import_workloads_openstack_insecure: true # skip OpenStack API TLS verification
```

### NBD "server has no export named" error
Common causes (in order):
1. Port 902 blocked — fix network
2. vCenter FQDN not resolvable — fix DNS or `/etc/hosts`
3. Malformed nbdkit command — check migration logs

### Manual replay (debug)
```bash
# Terminal 1: run nbdkit with verbose logging
nbdkit --verbose vddk "[Datastore] path/to/guest.vmdk"

# Terminal 2: run nbdcopy (from log command)
nbdcopy ... nbd://localhost:10809
# Should see: "vddk: config_complete." in nbdkit output
```

### Enable debug logging in os-migrate
```yaml
import_workloads_debug: true
```
Logs saved to `/tmp/osm-nbdkit-<vm>-<id>.log` on the conversion host.

## See Also

- `/debug-osm-ci` — Debug devstack CI environment (network, NAT, DNS)
- `/diagnose-migration` — Analyze migration failure logs (virt-v2v, nbdkit errors)
