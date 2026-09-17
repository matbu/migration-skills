#!/usr/bin/env python3
"""Apply agent-written AsciiDoc drafts to doc-drafts-report-2026-09-08.{json,md}."""

import json
import re
from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parents[2] / "audit-docs" / "reports"
JSON_PATH = REPORT_DIR / "doc-drafts-report-2026-09-08.json"
MD_PATH = REPORT_DIR / "doc-drafts-report-2026-09-08.md"

DRAFTS = {
    "vmk-setup-requirements": """= Setup requirements playbook (draft)

:product: vmware-migration-kit

== Overview

The `setup_requirements` playbook prepares the migrator host with OpenStack credentials and Python dependencies required by the VMware Migration Kit collection.

== When to use

Run this playbook on the migrator host before other migration playbooks when the host is not already running from the Ansible Execution Environment (AEE) and conversion hosts are not yet deployed.

== Requirements

* Migrator host with `dnf` package manager
* `~/.config/openstack/clouds.yaml` present on the control node (copied to the data directory)
* Variable `os_migrate_vmw_data_dir` set to the migration data directory
* Optional: `already_deploy_conversion_host` — when true, skips package and credential setup
* Optional: `runner_from_aee` — when true, skips package installation (AEE provides dependencies)

== Configuration

The playbook copies `clouds.yaml` to `{{ os_migrate_vmw_data_dir }}` and installs:

* `python3`, `python3-pip` (via dnf)
* `openstacksdk>1.0.0`, `requests`, `pyVim`, `pyVmomi`, `aiohttp` (via pip)

== Usage

[source,yaml]
----
ansible-playbook os_migrate.vmware_migration_kit.setup_requirements \\
  -e os_migrate_vmw_data_dir=/opt/os-migrate
----

== Related components

* Used early in the migration workflow before discovery and metadata conversion playbooks.

// TODO: Human review — verify against source code before publishing.
""",
    "vmk-prelude": """= Prelude role (draft)

:product: vmware-migration-kit

== Overview

The `prelude` role performs initial setup tasks and prerequisite checks for the VMware to OpenStack migration workflow. It is a hook role that operators can customize to inject pre-migration configuration.

== When to use

Included by `conversion_host` and `import_volumes` playbooks to run preparatory tasks on the migrator or conversion host before migration steps execute.

== Requirements

* Target host accessible via Ansible
* Privilege escalation (`become`) for `/etc/hosts` modifications

== Configuration

|===
| Variable | Default | Description

| `prelude_host_entries`
| `[]`
| List of lines to add to `/etc/hosts` on the target host
|===

== Usage

[source,yaml]
----
- name: Run prelude hook tasks
  ansible.builtin.include_role:
    name: os_migrate.vmware_migration_kit.prelude
  vars:
    prelude_host_entries:
      - "10.0.0.1 openstack.example.com"
----

== Related components

* `roles/conversion_host` — includes prelude during conversion host setup
* `playbooks/import_volumes.yml` — runs prelude on the migrator host before volume import

// TODO: Human review — verify against source code before publishing.
""",
    "vmk-metadata-convert": """= Metadata conversion (draft)

:product: vmware-migration-kit

== Overview

The `convert_metadata` playbook and role convert VMware VM metadata (from discovery) into OpenStack-compatible resource definitions, including flavors, network info, and import workload JSON files.

== When to use

After VMware discovery has produced per-VM JSON files under `os_migrate_vmw_data_dir`, run `convert_metadata.yml` to generate flavors and workload import data for each VM in `vms_list`.

== Requirements

* Migrator host with collection installed
* Per-VM discovery artifacts: `vm_info.json`, `guest_info.json`, `disk_info.json`, `network_info.json`
* Variable `vms_list` — list of VM names to convert
* Optional: `create_flavor` — when true, imports generated flavors to the destination cloud
* Optional: `copy_metadata_to_conv_host` — when true, syncs converted data to the conversion host

== Configuration

Role defaults (overridable per VM via playbook vars):

|===
| Variable | Default | Description

| `convert_metadata_strategy`
| `cold`
| Migration strategy (`cold` or `warm`)
| `convert_metadata_dry_run`
| `false`
| Dry-run mode
| `convert_metadata_security_groups`
| `default`
| Security groups for converted workloads
| `convert_metadata_os_migrate_tear_down`
| `false`
| Tear down resources after conversion
|===

Output files per VM under `os_migrate_vmw_data_dir/{{ vm_name }}/`:

* `flavors.yml` — flavor definition for OpenStack import
* `import_workloads.json` — workload metadata for `import_workloads` role

== Usage

[source,yaml]
----
ansible-playbook os_migrate.vmware_migration_kit.convert_metadata \\
  -e vms_list='["vm-01","vm-02"]' \\
  -e os_migrate_vmw_data_dir=/opt/os-migrate \\
  -e create_flavor=true
----

== Related components

* `playbooks/discovery.yml` — produces input JSON files
* `roles/import_workloads` — consumes `import_workloads.json`
* `plugins/modules/import_flavor` — imports generated flavor YAML to OpenStack

// TODO: Human review — verify against source code before publishing.
""",
    "vmk-import-volumes": """= Import volumes playbook (draft)

:product: vmware-migration-kit

== Overview

The `import_volumes` playbook runs prelude tasks on the migrator host, then imports VMware VM volumes to OpenStack via the conversion host using nbdkit-based migration.

== When to use

After metadata conversion and conversion host deployment, run this playbook to transfer VM disks from VMware to OpenStack volumes without creating OpenStack instances or network ports.

== Requirements

* Migrator host and conversion host configured in inventory
* Variable `vms_list` — list of VM names to migrate
* Conversion host with `import_workloads` role dependencies met
* OpenStack destination cloud credentials available

== Configuration

Playbook sets these vars on the conversion host play:

|===
| Variable | Value | Description

| `os_migrate_nbkit`
| `true`
| Use nbdkit for volume transfer
| `os_migrate_virt_v2v`
| `false`
| Disable virt-v2v path
| `os_migrate_create_network_port`
| `false`
| Do not create network ports
| `os_migrate_create_os_instance`
| `false`
| Do not create OpenStack instances
| `os_migrate_tear_down`
| `false`
| Keep migrated resources
|===

== Usage

[source,yaml]
----
ansible-playbook os_migrate.vmware_migration_kit.import_volumes \\
  -e vms_list='["vm-01"]' \\
  -e os_migrate_vmw_data_dir=/opt/os-migrate
----

== Related components

* `roles/prelude` — runs on migrator host first
* `roles/import_workloads` — performs per-VM volume migration on conversion host
* `playbooks/convert_metadata.yml` — prerequisite metadata conversion

// TODO: Human review — verify against source code before publishing.
""",
    "vmk-modules-openstack": """= VMware Migration Kit OpenStack modules (draft)

:product: vmware-migration-kit

== Overview

The VMware Migration Kit collection includes Ansible modules for OpenStack resource management during VMware-to-OpenStack migration. These modules complement the core migration roles and playbooks.

== When to use

Use these modules when building custom playbooks or extending migration workflows for flavor matching, server/port/volume lifecycle, Heat stack deployment, and metadata queries.

== Requirements

* OpenStack credentials via `cloud` parameter or `auth` dict
* Collection `os_migrate.vmware_migration_kit` installed

== Configuration

Key modules and required options:

=== Flavor management

* `best_match_flavor` — `cloud`, `guest_info_path`, `disk_info_path`
* `export_flavor` — `path`, `guest_info_path`, `disk_info_path`, `flavor_name`
* `import_flavor` — `cloud`, `flavors_file`
* `flavor_info` — `cloud`, `flavor_name`
* `delete_flavor` — `name`

=== Server and networking

* `create_server` — `name`, `auth`, `flavor_id`, `source_vm_json_path`
* `create_network_port` — `cloud`, `os_migrate_nics_file_path`, `vm_name`
* `delete_server`, `delete_port` — `name`

=== Volumes

* `volume_info` — `name`
* `volume_metadata_info` — `dst_cloud`, `volume_id`
* `delete_volume` — `name`

=== Heat templates

* `generate_heat_template` — `vms_data`, `stack_name`, `output_dir`
* `create_heat_stack` — `cloud`, `template_path`, `stack_name`

== Usage

[source,yaml]
----
- name: Find best matching flavor
  os_migrate.vmware_migration_kit.best_match_flavor:
    cloud: dst
    guest_info_path: /opt/os-migrate/vm-01/guest_info.json
    disk_info_path: /opt/os-migrate/vm-01/disk_info.json
  register: flavor_match
----

== Related components

* `roles/convert_metadata` — uses `export_flavor` and `import_flavor`
* `roles/import_workloads` — uses volume and server modules
* `plugins/doc_fragments/` — shared OpenStack authentication fragments

// TODO: Human review — verify against source code before publishing.
""",
    "vmk-changelog": """= VMware Migration Kit changelog (draft)

:product: vmware-migration-kit

== Overview

Release history for the VMware Migration Kit Ansible collection. The authoritative changelog is maintained in the collection repository at `CHANGELOG.md`.

== When to use

Consult the changelog when upgrading the collection or troubleshooting behavior changes between versions.

== Requirements

None — reference documentation only.

== Notable releases

=== v1.0.0

Initial release: VMware vCenter 7/8 to OpenStack migration for Linux guests (Ubuntu, CentOS 8/9, RHEL 8/9) using virt-v2v and a conversion host. Features include network mapping, best-match flavor selection, and persistent MAC addresses.

=== v1.2.0

Stability improvements: multi-NIC and multi-disk support, RHEL network config, tolerance for missing VMware Tools.

=== v1.2.7

nbdkit socket support for multiple concurrent migrations per conversion host; improved logging with per-VM log files.

=== v1.2.8

CBT (Changed Block Tracking) migration improvements, `volume_metadata_info` module, converted-volume metadata tracking.

=== v1.3.1

Key pair support for instance creation; `setup_requirements` playbook for migrator host.

== Related components

* Collection: `os_migrate.vmware_migration_kit`
* Source: `CHANGELOG.md` in the vmware-migration-kit repository

// TODO: Human review — verify full CHANGELOG.md before publishing.
""",
    "osm-how-it-works-workload": """= How workload migration works (draft)

:product: os-migrate

== Overview

The `import_workloads` role migrates OpenStack workloads (instances) from a source cloud to a destination cloud. It validates exported workload metadata, checks conversion host connectivity, exports source volumes via NBD, transfers data to the destination, and creates a new instance booting from the imported volume.

== When to use

After running `export_workloads.yml` to produce workload YAML files, use `import_workloads.yml` to perform the actual instance migration. This is the core workload migration path in os-migrate.

== Requirements

* Source and destination conversion hosts deployed and reachable
* Exported workload data in `os_migrate_data_dir`
* SSH key at `os_migrate_conversion_keypair_private_path`
* OpenStack credentials for source (`src`) and destination (`dst`) clouds

== Configuration

|===
| Variable | Default | Description

| `os_migrate_timeout`
| `1800`
| Timeout for migration operations (seconds)
| `os_migrate_workload_cleanup_on_failure`
| `true`
| Clean up temporary resources on failure
| `os_migrate_workload_boot_volume_prefix`
| `os-migrate-`
| Prefix for boot volume names on destination
| `os_migrate_workload_stop_before_migration`
| `false`
| Stop source VM before migration
| `os_migrate_workloads_data_copy`
| `true`
| Copy workload data during migration
| `os_migrate_workloads_filter`
| `regex: .*`
| Filter workloads to import
|===

== Usage

[source,yaml]
----
ansible-playbook os_migrate.os_migrate.import_workloads \\
  -e os_migrate_data_dir=/data
----

== Migration steps (per workload)

The role executes these phases via `import_workload_*` modules:

1. `import_workload_prelim` — preliminary setup and logging
2. `import_workload_dst_check` — verify destination cloud readiness
3. Optional source VM stop (when `os_migrate_workload_stop_before_migration` is true)
4. `import_workload_src_check` — verify source instance state
5. `import_workload_export_volumes` — NBD export of source volumes on conversion host
6. `import_workload_transfer_volumes` — transfer data and create destination volumes
7. `import_workload_create_instance` — create destination instance from imported volumes
8. Cleanup via `import_workload_src_cleanup` / `import_workload_dst_failure_cleanup`

== Related components

* `roles/export_workloads` — produces input workload YAML
* `roles/conversion_host` — provides conversion host infrastructure
* `playbooks/deploy_conversion_hosts.yml` — deploys conversion hosts

// TODO: Human review — verify against source code before publishing.
""",
    "osm-nbd-source-migration": """= NBD source migration with nbdkit direct mode (draft)

:product: os-migrate

== Overview

nbdkit direct mode allows workload migration without a source conversion host by spawning nbdkit directly on the OpenStack hypervisor (compute node). The `import_from_hypervisor` role and `update_workload_nbdkit_uris` module support this workflow.

== When to use

Use nbdkit direct mode when workloads have `use_nbdkit_direct: true` in their migration parameters and you want to avoid NBD export through a source conversion host.

== Requirements

* Workloads exported with `hypervisor_hostname` field populated
* SSH access to hypervisor nodes (default user: `stack`)
* Destination conversion host for volume transfer
* `nbdkit` available on hypervisor nodes

== Configuration

`import_from_hypervisor` role defaults:

|===
| Variable | Default | Description

| `os_migrate_nbdkit_port`
| `10809`
| nbdkit listening port
| `os_migrate_nbdkit_protocol`
| `tcp`
| Protocol (`tcp` or `ssh`)
| `os_migrate_nbdkit_ssh_user`
| `stack`
| SSH user for hypervisor access
| `os_migrate_nbdkit_readonly`
| `true`
| Read-only nbdkit export
| `os_migrate_nbdkit_timeout`
| `300`
| nbdkit spawn timeout (seconds)
| `os_migrate_nbdkit_nova_instances_dir`
| `/var/lib/nova/instances`
| Nova instances directory on hypervisor
|===

== Usage

Three-step workflow:

[source,bash]
----
# 1. Export workloads (includes hypervisor_hostname)
ansible-playbook export_workloads.yml -e os_migrate_data_dir=/data

# 2. Spawn nbdkit on hypervisors
ansible-playbook import_from_hypervisor.yml -e os_migrate_data_dir=/data

# 3. Import workloads using nbdkit URIs
ansible-playbook import_workloads.yml -e os_migrate_data_dir=/data
----

The `import_workload_transfer_volumes` module accepts `use_nbdkit_direct`, `nbdkit_socket_uri`, and `nbdkit_export_name` parameters for direct-mode transfers.

== Related components

* `roles/import_from_hypervisor` — spawns nbdkit on hypervisors
* `plugins/modules/update_workload_nbdkit_uris` — updates workload YAML with nbdkit disk URIs
* `plugins/modules/import_workload_export_volume_map` — creates volume map without source conversion host
* `roles/import_workloads` — performs migration using nbdkit URIs

// TODO: Human review — verify against source code before publishing.
""",
    "osm-changelog": """= os-migrate changelog (draft)

:product: os-migrate

== Overview

Release history for the os-migrate Ansible collection. The authoritative changelog is maintained in the collection repository at `CHANGELOG.rst`.

== When to use

Consult the changelog when upgrading the collection or reviewing changes to modules, roles, and CI configuration.

== Requirements

None — reference documentation only.

== Recent releases

=== 1.0.5

Documentation for `stringFilter` module; galaxy ignore file; README link fixes.

=== 1.0.4

Removed OCP references; added pylint and bindep; removed `community.general` dependency; certificate validation improvements.

=== 1.0.3

Updated openstacksdk version in AEE to 4.5.0 for CI stability.

=== 1.0.2

Maintenance updates for CI, linting, and sanity checks.

== Related components

* Collection: `os_migrate.os_migrate`
* Source: `CHANGELOG.rst` in the os-migrate repository

// TODO: Human review — verify full CHANGELOG.rst before publishing.
""",
    "osm-role-import_from_hypervisor": """= Import from hypervisor role (draft)

:product: os-migrate

== Overview

The `import_from_hypervisor` role spawns nbdkit on OpenStack hypervisors (compute nodes) for workloads that have `use_nbdkit_direct: true` in their migration parameters. It is part of the nbdkit direct mode migration workflow.

== When to use

Run after `export_workloads.yml` and before `import_workloads.yml` when migrating workloads using nbdkit direct mode instead of source conversion host NBD export.

== Requirements

* Exported `workloads.yml` with `hypervisor_hostname` populated
* SSH access to hypervisor nodes
* `nbdkit` installed on hypervisor compute nodes
* Variable `os_migrate_data_dir` pointing to migration data directory

== Configuration

|===
| Variable | Default | Description

| `os_migrate_nbdkit_port`
| `10809`
| nbdkit listening port
| `os_migrate_nbdkit_protocol`
| `tcp`
| Connection protocol
| `os_migrate_nbdkit_ssh_user`
| `stack`
| SSH user for hypervisor
| `os_migrate_nbdkit_readonly`
| `true`
| Read-only disk export
| `os_migrate_nbdkit_timeout`
| `300`
| Spawn timeout (seconds)
| `os_migrate_nbdkit_ip_allow`
| `null`
| Optional IP restriction (destination conversion host)
| `os_migrate_nbdkit_nova_instances_dir`
| `/var/lib/nova/instances`
| Nova instances path on hypervisor
|===

== Usage

[source,yaml]
----
ansible-playbook os_migrate.os_migrate.import_from_hypervisor \\
  -e os_migrate_data_dir=/data
----

For each workload with `use_nbdkit_direct: true`, the role:

1. Connects to the hypervisor from `hypervisor_hostname`
2. Finds the instance disk
3. Inspects disk format (qcow2 vs raw) and backing files
4. Spawns nbdkit with the correct plugin
5. Updates the workload file with the nbdkit URI

== Related components

* `playbooks/export_workloads.yml` — prerequisite export step
* `playbooks/import_workloads.yml` — subsequent migration step
* `plugins/modules/update_workload_nbdkit_uris` — updates workload YAML with disk URIs

// TODO: Human review — verify against source code before publishing.
""",
    "osm-module-import_workload_export_volume_map": """= import_workload_export_volume_map module (draft)

:product: os-migrate

== Overview

Creates a `volume_map` structure from workload data for nbdkit direct mode migration, without requiring a source conversion host. Handles both volume-backed and ephemeral-backed instances.

== When to use

Use in nbdkit direct mode workflows when you need a volume map before transferring data from hypervisor-hosted nbdkit exports to the destination cloud.

== Requirements

* Workload data dict loaded from os-migrate workloads YAML
* OpenStack credentials via `cloud` or `auth` parameter

== Configuration

|===
| Option | Required | Description

| `data`
| yes
| Workload data structure from workloads YAML file
| `cloud`
| no
| Cloud resource from clouds.yml
| `auth`
| no
| OpenStack authentication dict
| `validate_certs`
| no
| Validate HTTPS certificates
|===

== Usage

[source,yaml]
----
- name: Create volume map for nbdkit direct mode
  os_migrate.os_migrate.import_workload_export_volume_map:
    cloud: src
    data: "{{ workload_item }}"
  register: volume_info
----

== Returns

* `transfer_uuid` — UUID identifying this transfer
* `volume_map` — mapping of source volume devices to volume information (bootable flag, size, etc.)

== Related components

* `roles/import_from_hypervisor` — spawns nbdkit before volume map creation
* `plugins/modules/import_workload_transfer_volumes` — uses volume map for data transfer with `use_nbdkit_direct`

// TODO: Human review — verify against source code before publishing.
""",
    "osm-module-update_workload_nbdkit_uris": """= update_workload_nbdkit_uris module (draft)

:product: os-migrate

== Overview

Updates a workload entry in the workloads YAML file with nbdkit disk URIs. Supports multiple disks per instance (boot and ephemeral disks) for nbdkit direct mode migration.

== When to use

Called by the `import_from_hypervisor` role after spawning nbdkit on hypervisors, to record per-disk nbdkit URIs in the workload file before running `import_workloads`.

== Requirements

* Existing workloads YAML file at the specified path
* Instance ID matching a workload entry in the file
* List of nbdkit disk information dicts

== Configuration

|===
| Option | Required | Description

| `path`
| yes
| Path to workloads YAML file
| `instance_id`
| yes
| Instance ID to update
| `nbdkit_disks`
| yes
| List of disk dicts with `device`, `uri`, `port`, `size`, `bootable`
|===

== Usage

[source,yaml]
----
- name: Update workload with multiple nbdkit URIs
  os_migrate.os_migrate.update_workload_nbdkit_uris:
    path: /data/workloads.yml
    instance_id: abc-123-def-456
    nbdkit_disks:
      - device: "/dev/vda"
        uri: "nbd://hypervisor-01:10809"
        port: 10809
        size: 10
        bootable: true
      - device: "/dev/vdb"
        uri: "nbd://hypervisor-01:10810"
        port: 10810
        size: 10
        bootable: false
----

== Related components

* `roles/import_from_hypervisor` — spawns nbdkit and calls this module
* `roles/import_workloads` — reads updated workload file for migration
* `plugins/modules/import_workload_export_volume_map` — creates volume map from workload data

// TODO: Human review — verify against source code before publishing.
""",
}


def update_json() -> None:
    data = json.loads(JSON_PATH.read_text())
    for product in data["products"]:
        for draft in product["drafts"]:
            draft_id = draft["id"]
            if draft_id in DRAFTS:
                draft["draft_adoc"] = DRAFTS[draft_id].strip() + "\n"
                draft["draft_status"] = "draft"
    JSON_PATH.write_text(json.dumps(data, indent=2) + "\n")


def update_md() -> None:
    md = MD_PATH.read_text()
    for draft_id, adoc in DRAFTS.items():
        pattern = (
            rf"(#### {re.escape(draft_id)}\n\n.*?)\n\n_Pending agent draft_\n"
        )
        replacement = rf"\1\n\n```adoc\n{adoc.strip()}\n```\n"
        md, count = re.subn(pattern, replacement, md, count=1, flags=re.DOTALL)
        if count != 1:
            raise SystemExit(f"Failed to replace pending draft for {draft_id}")
    MD_PATH.write_text(md)


def main() -> None:
    update_json()
    update_md()
    print(f"Updated {JSON_PATH}")
    print(f"Updated {MD_PATH}")
    print(f"Applied {len(DRAFTS)} drafts")


if __name__ == "__main__":
    main()
