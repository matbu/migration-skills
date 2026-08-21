---
name: debug-osm-ci
description: Debug os-migrate CI Environment (KubeVirt devstack nodes via virtctl)
tags: [debug, ci, openstack, devstack, connectivity, kubevirt, virtctl]
---

# Debug os-migrate CI Environment

Diagnose and fix connectivity issues in an OpenStack (devstack) migration environment
where devstack nodes are KubeVirt VMs accessed via `virtctl`.
Checks conversion host network reachability, compares source vs destination configs, and generates concrete OpenStack CLI fixes.

## Execution

When this skill is invoked:

**Step 0 — Verify OpenShift login.**
Before anything else, check that the local environment is authenticated:
```bash
oc whoami 2>&1            # must succeed (not "Unauthorized")
kubectl get nodes 2>&1    # must list cluster nodes
```
If not logged in, abort with:
> "Run `oc login <cluster-url> --token=<token>` first. Get the command from the OpenShift web console → top-right menu → **Copy login command**."

**Step 1 — Resolve connection parameters.**
If `src_vmi` or `dst_vmi` are not given as arguments, read them from environment variables using the Bash tool:
```bash
echo "${SRC_VMI:-ubuntu@vmi/<src-vmi-name>}"   # source devstack VMI
echo "${DST_VMI:-ubuntu@vmi/<dst-vmi-name>}"   # destination devstack VMI
```
If either env var is unset, abort with:
> "Set `SRC_VMI` and `DST_VMI` environment variables or pass them as positional arguments to `/debug-osm-ci`."

For the identity file, use `$OSM_SSH_KEY` if set, otherwise `~/.ssh/id_rsa`.
For the namespace, use `$OSM_NS` if set. If unset, `--ns` is **required**.

**Step 2 — Run the workflow immediately:**
```
Workflow({ scriptPath: "~/.claude/skills/debug-osm-ci/workflow.js", args: [src_vmi, dst_vmi, identity_file, ...remaining_args] })
```
Include `--ns=<namespace>` in remaining_args if `$OSM_NS` is set.

After the workflow completes, present the results in a clear, structured format.

## Prerequisites

```bash
export SRC_VMI=ubuntu@vmi/<src-vmi-name>
export DST_VMI=ubuntu@vmi/<dst-vmi-name>
export OSM_NS=<your-namespace>     # required
export OSM_SSH_KEY=~/.ssh/your_key           # optional, defaults to ~/.ssh/id_rsa
```

## Overview

The skill orchestrates four phases:

1. **Prelim** — Deploy a fresh CentOS test instance on each cloud (idempotent: removes any existing instance first, including its floating IP). Instances are reachable via ProxyJump through the devstack VM using `virtctl`.
2. **Checks** — Run connectivity probes in parallel on both test instances:
   - Internet ICMP (8.8.8.8)
   - Internet HTTPS (google.com)
   - CentOS mirrors (mirror.centos.org, mirror.stream.centos.org)
   - DNS resolution
   - OpenStack Keystone API reachability (source and destination)
   - Cross-host ping between instances
   - DNF/YUM repository access
3. **Compare** — Collect OpenStack network config from both devstacks (networks, subnets, routers, security groups, floating IPs) plus OS-level config (resolv.conf, ip route, iptables) from the test instances. Identify differences.
4. **Solutions** — Generate precise, copy-pasteable commands (using `virtctl` for devstack access) to fix each identified issue, ordered by impact. Ends with a `COMMANDS TO RUN` runbook.

## Usage

```bash
# Run all phases (reads SRC_VMI / DST_VMI / OSM_SSH_KEY from env)
/debug-osm-ci

# Explicit VMI refs + identity file
/debug-osm-ci ubuntu@vmi/<src-vmi-name> ubuntu@vmi/<dst-vmi-name> ~/.ssh/your_key

# Custom namespace
/debug-osm-ci ubuntu@vmi/vm-1 ubuntu@vmi/vm-2 ~/.ssh/your_key --ns=my-namespace

# Provide known Keystone IPs (skip OS_AUTH_URL discovery)
/debug-osm-ci ubuntu@vmi/vm-1 ubuntu@vmi/vm-2 ~/.ssh/your_key --src-ip=192.168.1.10 --dst-ip=192.168.1.20

# Skip discovery by providing known test instance floating IPs
/debug-osm-ci ubuntu@vmi/vm-1 ubuntu@vmi/vm-2 ~/.ssh/your_key <src-fip> <dst-fip>

# ── Run only specific phases ──────────────────────────────────────────────────

# Just compare the two OpenStack environments (no test instances needed)
/debug-osm-ci --only=compare

# Compare + generate fixes
/debug-osm-ci --only=compare,solutions

# Only run connectivity checks (requires test instance IPs in args 4 & 5)
/debug-osm-ci ubuntu@vmi/vm-1 ubuntu@vmi/vm-2 ~/.ssh/your_key <src-fip> <dst-fip> --only=checks

# Only deploy test instances
/debug-osm-ci --only=prelim

# --only flag can appear anywhere in the argument list
/debug-osm-ci ubuntu@vmi/vm-1 ubuntu@vmi/vm-2 --only=compare,solutions
```

## Arguments

Positional arguments (flags starting with `--` are separated out automatically):

| Position | Argument | Default | Description |
|----------|----------|---------|-------------|
| 1 | `src_vmi` | `$SRC_VMI` | virtctl VMI ref for source devstack (e.g. `ubuntu@vmi/<src-vmi-name>`) |
| 2 | `dst_vmi` | `$DST_VMI` | virtctl VMI ref for destination devstack (e.g. `ubuntu@vmi/<dst-vmi-name>`) |
| 3 | `identity_file` | `$OSM_SSH_KEY` or `~/.ssh/id_rsa` | SSH identity file passed to `virtctl --identity-file` |
| 4 | `src_conv_host_ip` | (auto-discover) | Known floating IP of source test instance |
| 5 | `dst_conv_host_ip` | (auto-discover) | Known floating IP of destination test instance |

## Flags

| Flag | Values | Description |
|------|--------|-------------|
| `--ns=<namespace>` | string | Kubernetes namespace for `virtctl` (**required**) |
| `--src-ip=<ip>` | IP address | Devstack source host IP for Keystone checks (auto-discovered from openrc if absent) |
| `--dst-ip=<ip>` | IP address | Devstack dest host IP for Keystone checks (auto-discovered from openrc if absent) |
| `--only=<phase>` | `prelim`, `checks`, `compare`, `solutions` | Run only the listed phases (comma-separated). Omit to run all. |

### Phase dependencies when using `--only`

| Requested phase | What you need to provide |
|-----------------|--------------------------|
| `prelim` | Just devstack VMI refs + identity file |
| `checks` | Test instance IPs in args 4 & 5 (or run `prelim` first) |
| `compare` | Just devstack VMI refs + identity file (no test instance needed for OpenStack-level comparison) |
| `solutions` | Ideally combine with `compare`: `--only=compare,solutions` |

## Prerequisites

- **OpenShift login**: `oc login <cluster-url> --token=<token>` must succeed before running
- `virtctl` must be installed and `kubectl` context set to the correct cluster
- Identity file must be valid for both devstack VMIs
- Devstack OpenRC is assumed to be at `~/devstack/openrc` on each devstack VM (if installed as the ubuntu user, it may be at `/opt/stack/devstack/openrc`)
- The admin project must have a CentOS/RHEL image in Glance (for instance deployment)
- If deploying a test instance: a `default` security group must exist

## How Access Works

All devstack access uses `virtctl` (no direct SSH to host IPs needed):

```bash
# Run a command on source devstack
virtctl -n <your-namespace> ssh \
  --identity-file="~/.ssh/your_key" \
  --local-ssh-opts='-o IdentitiesOnly=yes' \
  ubuntu@vmi/<src-vmi-name> -c "openstack server list"

# SSH to a test instance inside devstack (virtctl as ProxyCommand)
VCPROXY="virtctl -n <your-namespace> ssh --identity-file=~/.ssh/your_key --local-ssh-opts='-o IdentitiesOnly=yes' ubuntu@vmi/<src-vmi-name> -- nc %h %p"
ssh -i /tmp/debug-conv-test-key-source -o "ProxyCommand=$VCPROXY" -o StrictHostKeyChecking=no cloud-user@<floating-ip> "echo ok"
```

## Connectivity Checks

| Check | Target | Expected |
|-------|--------|----------|
| Internet ICMP | 8.8.8.8 | 0% packet loss |
| Internet HTTPS | google.com | HTTP 200 |
| CentOS mirror | mirror.centos.org | HTTP 200/301 |
| CentOS Stream | mirror.stream.centos.org | HTTP 200/301 |
| DNS | mirror.centos.org | Resolves to IP |
| OpenStack source API | `src_devstack_ip/identity` | HTTP 200/401 |
| OpenStack dest API | `dst_devstack_ip/identity` | HTTP 200/401 |
| Cross-host ping | other test instance | 0% packet loss |
| DNF/YUM repos | package manager | No repo errors |

## Example Output

```
Phase: Prelim
  → Source test instance: cloud-user@172.24.4.5 (via virtctl proxy) — DEPLOYED
  → Dest test instance  : cloud-user@172.24.4.8 (via virtctl proxy) — DEPLOYED

Phase: Checks
  → Source: ALL PASSED
  → Destination: FAILED: Internet ICMP, CentOS mirror HTTP, DNS, DNF/YUM repos

Phase: Compare
  → Found 3 configuration differences:
    [CRITICAL] Host iptables MASQUERADE rule: source has active rule (68k packets), destination MISSING
    [CRITICAL] DNS cascade: direct consequence of missing NAT — no separate fix needed
    [WARNING]  Security group egress: source has IPv4/IPv6 any, destination has no egress rules

Phase: Solutions
  Fix 1 (CRITICAL) — Add missing MASQUERADE rule on destination devstack
    Commands:
      virtctl -n <your-namespace> ssh --identity-file="~/.ssh/your_key" \
        --local-ssh-opts='-o IdentitiesOnly=yes' ubuntu@vmi/<dst-vmi-name> \
        -c "sudo iptables -t nat -A POSTROUTING -s <pub-cidr> -o <iface> -j MASQUERADE"
    Verify: sudo iptables -t nat -L POSTROUTING -v -n | grep MASQUERADE

═══ COMMANDS TO RUN ══════════════════════════════════════════════════════════
# Fix 1 (CRITICAL) — Add MASQUERADE rule on destination
virtctl -n <your-namespace> ssh --identity-file="~/.ssh/your_key" \
  --local-ssh-opts='-o IdentitiesOnly=yes' ubuntu@vmi/<dst-vmi-name> \
  -c "sudo iptables -t nat -A POSTROUTING -s <pub-cidr> -o <iface> -j MASQUERADE"
══════════════════════════════════════════════════════════════════════════════
```

## Known Network Limitations (KubeVirt environment)

These are **upstream network policies — not devstack config issues**, no fix needed:

| Symptom | Root cause | Workaround |
|---------|-----------|------------|
| `ping 8.8.8.8` fails (even from the devstack host itself) | KubeVirt upstream blocks outbound ICMP | Use `curl -s -o /dev/null -w "%{http_code}" https://github.com` instead |
| DNS fails ("Name or service not known") | UDP/53 to 8.8.8.8/1.1.1.1 also blocked | Fix DNS nameserver to cluster DNS (see below) |
| ICMP check fails but HTTPS passes | Same ICMP block | Not a devstack issue — treat as INFO only |

## Common Issues and Fixes

**OpenShift not logged in**

All virtctl commands fail silently or with auth errors if not authenticated:
```bash
oc login <cluster-url> --token=<token>
# Get the command: OpenShift web console → top-right menu → "Copy login command"
```

**No internet from test instance**

1. Add MASQUERADE rule for the public subnet CIDR (`--external` network range):
   ```bash
   virtctl ... ubuntu@vmi/vm-2 -c "sudo iptables -t nat -A POSTROUTING -s <pub-cidr> -o enp1s0 -j MASQUERADE"
   ```
2. **Always flush stale conntrack entries after adding MASQUERADE** — zone-0 entries
   created before the rule bypass it, leaving packets unmasqueraded on enp1s0:
   ```bash
   virtctl ... ubuntu@vmi/vm-2 -c "sudo conntrack -D -s <pub-cidr> 2>/dev/null; sudo conntrack -D -d <pub-cidr> 2>/dev/null"
   ```
   Confirm working: `conntrack -L | grep 8.8.8.8` reply tuple should show `dst=192.168.121.x`, not the floating IP.
3. Router missing external gateway → `openstack router set --external-gateway <pub-net-id> <router-id>`
4. Security group blocking egress → add egress rules for IPv4/IPv6

**DNS resolution fails ("Name or service not known")**

Instances get `nameserver 8.8.8.8` from DHCP, but 8.8.8.8 is unreachable. Use the
Kubernetes cluster DNS instead (discoverable from the devstack host's `resolvectl`):

```bash
# Discover cluster DNS from devstack host
virtctl ... ubuntu@vmi/vm-2 -c "resolvectl status | awk '/Current DNS Server:/ {print \$4; exit}'"
# → typically <cluster-dns-ip>
```

Fix the **private subnet** DNS (instances get DNS from the private network DHCP — updating
the public/external subnet DNS has no effect on instances):
```bash
virtctl ... ubuntu@vmi/vm-2 -c "source devstack/openrc admin admin && \
  PRIV_SUBNET=\$(openstack subnet list --network private --ip-version 4 -f value -c ID | head -1) && \
  openstack subnet set --dns-nameserver <cluster-dns-ip> \$PRIV_SUBNET"
```

Fix `/etc/resolv.conf` on already-running instances immediately (SSH from inside devstack):
```bash
virtctl ... ubuntu@vmi/vm-2 -c \
  "ssh -i /tmp/instance-key -o StrictHostKeyChecking=no cloud-user@<fip> \
   'echo nameserver <cluster-dns-ip> | sudo tee /etc/resolv.conf'"
```

**SSH to instance via virtctl ProxyCommand doesn't work**

`virtctl -- nc %h %p` fails with "accepts 1 arg(s)" on virtctl ≤ 1.8.x. SSH from inside the devstack VM instead:
```bash
# Copy instance key to devstack first (or use a key already there)
virtctl ... ubuntu@vmi/vm-2 -c \
  "ssh -i /tmp/instance-key -o StrictHostKeyChecking=no cloud-user@<fip> 'your-command'"
```

**CentOS mirrors unreachable**
- Fix DNS nameserver first (see above), then check router external gateway
- If routing is fine: check `iptables -L FORWARD -n` on devstack for blocking rules

**Cross-host ping fails**
- Security group missing ICMP ingress rule → `openstack security group rule create --protocol icmp --direction ingress --remote-ip <remote-cidr> default`
- Test instances on different networks with no routing path

**DNF/YUM repos fail**
- Fix DNS nameserver first — this is almost always the root cause

**Neutron L3 agent broken (all routing fails)**
- `virtctl -n <ns> ssh ... ubuntu@vmi/vm-2 -c "sudo systemctl restart devstack@q-l3.service"`

## Cleanup

If the skill deployed test instances, remove them afterward:

```bash
NS=<your-namespace>
KEY=~/.ssh/your_key

virtctl -n $NS ssh --identity-file="$KEY" --local-ssh-opts='-o IdentitiesOnly=yes' \
  ubuntu@vmi/<src-vmi-name> -c \
  "source devstack/openrc admin admin && \
   openstack server delete debug-conv-test-source --wait && \
   openstack floating ip delete <src-fip> && \
   openstack keypair delete debug-conv-test-key 2>/dev/null"

virtctl -n $NS ssh --identity-file="$KEY" --local-ssh-opts='-o IdentitiesOnly=yes' \
  ubuntu@vmi/<dst-vmi-name> -c \
  "source devstack/openrc admin admin && \
   openstack server delete debug-conv-test-destination --wait && \
   openstack floating ip delete <dst-fip> && \
   openstack keypair delete debug-conv-test-key 2>/dev/null"
```

## See Also

- `/diagnose-migration` — Analyze migration log failures (virt-v2v, nbdkit errors)
- `/vmw-build-prod` — Build the VMware Migration Kit collection
