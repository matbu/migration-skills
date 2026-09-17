#!/usr/bin/env python3
"""Unit tests for draft_undocumented.py helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from draft_undocumented import (
    build_draft_row,
    collect_code_context,
    extract_role_context,
    is_eligible_mapping,
    load_audit_report_filter,
    suggested_doc_path,
)


class TestEligibility(unittest.TestCase):
    def test_external_doc_null_eligible(self) -> None:
        mapping = {
            "id": "vmk-test",
            "doc": None,
            "audience": "external",
            "code": ["playbooks/foo.yml"],
        }
        with patch("draft_undocumented.mapping_paths_ok", return_value=True):
            self.assertTrue(is_eligible_mapping(mapping, Path("/tmp"), None))

    def test_internal_excluded(self) -> None:
        mapping = {
            "id": "vmk-ci",
            "doc": None,
            "audience": "internal",
            "code": [".github/workflows/ci.yml"],
        }
        with patch("draft_undocumented.mapping_paths_ok", return_value=True):
            self.assertFalse(is_eligible_mapping(mapping, Path("/tmp"), None))

    def test_ci_kind_excluded(self) -> None:
        mapping = {
            "id": "vmk-ci",
            "doc": None,
            "audience": "external",
            "kind": "ci",
            "code": [".github/workflows/ci.yml"],
        }
        with patch("draft_undocumented.mapping_paths_ok", return_value=True):
            self.assertFalse(is_eligible_mapping(mapping, Path("/tmp"), None))

    def test_mapped_doc_excluded(self) -> None:
        mapping = {
            "id": "vmk-ok",
            "doc": "source/foo.adoc",
            "audience": "external",
            "code": ["playbooks/foo.yml"],
        }
        with patch("draft_undocumented.mapping_paths_ok", return_value=True):
            self.assertFalse(is_eligible_mapping(mapping, Path("/tmp"), None))


class TestSuggestedDocPath(unittest.TestCase):
    def test_role_path(self) -> None:
        mapping = {
            "kind": "role",
            "code": ["roles/prelude/**"],
        }
        self.assertEqual(
            suggested_doc_path(mapping, "vmware"),
            "source/reference-role-prelude.adoc",
        )

    def test_module_path(self) -> None:
        mapping = {
            "kind": "module",
            "code": ["plugins/modules/import_vmware_volume.py"],
        }
        self.assertEqual(
            suggested_doc_path(mapping, "vmware"),
            "source/reference-module-import_vmware_volume.adoc",
        )

    def test_playbook_path(self) -> None:
        mapping = {
            "kind": "playbook",
            "code": ["playbooks/setup_requirements.yml"],
        }
        self.assertEqual(
            suggested_doc_path(mapping, "vmware"),
            "source/reference-playbook-setup_requirements.adoc",
        )

    def test_feature_vmware_fallback(self) -> None:
        mapping = {"kind": "feature", "code": ["doc/**"]}
        self.assertEqual(
            suggested_doc_path(mapping, "vmware"),
            "source/operator-vmware-guide.adoc",
        )

    def test_feature_osm_fallback(self) -> None:
        mapping = {"kind": "feature", "code": ["doc/**"]}
        self.assertEqual(
            suggested_doc_path(mapping, "os-migrate"),
            "source/operator-walkthrough.adoc",
        )


class TestAuditReportFilter(unittest.TestCase):
    def test_filters_undocumented_paths_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.json"
            path.write_text(
                json.dumps(
                    {
                        "products": [
                            {
                                "product_key": "vmware",
                                "mappings": [
                                    {
                                        "id": "vmk-a",
                                        "paths_ok": True,
                                        "status": "undocumented",
                                    },
                                    {
                                        "id": "vmk-b",
                                        "paths_ok": True,
                                        "status": "mapped",
                                    },
                                    {
                                        "id": "vmk-c",
                                        "paths_ok": False,
                                        "status": "undocumented",
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            eligible = load_audit_report_filter(path)
        self.assertEqual(eligible, {"vmware": {"vmk-a"}})


class TestRoleContextExtraction(unittest.TestCase):
    def test_extracts_defaults_and_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            role = repo / "roles" / "prelude"
            (role / "defaults").mkdir(parents=True)
            (role / "tasks").mkdir(parents=True)
            (role / "defaults" / "main.yml").write_text(
                "prelude_enabled: true\n", encoding="utf-8"
            )
            (role / "tasks" / "main.yml").write_text("- debug: msg=hi\n", encoding="utf-8")
            files = list(repo.rglob("*"))
            files = [p for p in files if p.is_file()]
            ctx = extract_role_context(repo, files, ["roles/prelude/**"])
        self.assertEqual(ctx["role_name"], "prelude")
        self.assertIn("prelude_enabled", ctx["defaults"])
        self.assertTrue(any("tasks/main.yml" in t for t in ctx["task_files"]))


class TestBuildDraftRow(unittest.TestCase):
    def test_pending_status_and_suggested_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            pb = repo / "playbooks" / "setup.yml"
            pb.parent.mkdir(parents=True)
            pb.write_text("- hosts: localhost\n  gather_facts: false\n", encoding="utf-8")
            mapping = {
                "id": "vmk-setup",
                "doc": None,
                "audience": "external",
                "kind": "playbook",
                "code": ["playbooks/setup.yml"],
            }
            row = build_draft_row(mapping, repo, "https://github.com/example/repo", "vmware")
        self.assertEqual(row["draft_status"], "pending")
        self.assertIsNone(row["draft_adoc"])
        self.assertEqual(
            row["suggested_doc_path"], "source/reference-playbook-setup.adoc"
        )
        self.assertIn("playbooks", row["code_context"])


if __name__ == "__main__":
    unittest.main()
