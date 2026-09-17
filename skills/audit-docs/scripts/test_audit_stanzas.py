#!/usr/bin/env python3
"""Unit tests for mapping stanza builders in audit_paths.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audit_paths import (
    build_mapping_entry,
    build_new_stanzas,
    build_update_stanzas,
    format_stanza_yaml,
    infer_audience,
    resolve_unique_id,
)


class TestInferAudience(unittest.TestCase):
    def test_ci_is_internal(self) -> None:
        self.assertEqual(infer_audience("ci"), "internal")

    def test_playbook_is_external(self) -> None:
        self.assertEqual(infer_audience("playbook"), "external")


class TestResolveUniqueId(unittest.TestCase):
    def test_no_collision(self) -> None:
        self.assertEqual(resolve_unique_id("vmk-foo", {"vmk-bar"}), "vmk-foo")

    def test_collision_appends_suffix(self) -> None:
        existing = {"vmk-foo", "vmk-foo-2"}
        self.assertEqual(resolve_unique_id("vmk-foo", existing), "vmk-foo-3")


class TestFormatStanzaYaml(unittest.TestCase):
    def test_indented_list_item(self) -> None:
        entry = build_mapping_entry(
            mapping_id="vmk-test",
            doc=None,
            code=["playbooks/test.yml"],
            kind="playbook",
        )
        yaml_text = format_stanza_yaml(entry)
        self.assertTrue(yaml_text.startswith("  - id: vmk-test"))
        self.assertIn("doc: null", yaml_text)
        self.assertIn("status: undocumented", yaml_text)


class TestBuildNewStanzas(unittest.TestCase):
    def test_produces_add_stanza(self) -> None:
        unmapped = [
            {
                "suggested_id": "vmk-new-role",
                "code": ["roles/new_role/**"],
                "kind": "role",
                "reason": "code path not listed in any mapping",
                "doc_mentions": [],
                "suggested_doc": None,
            }
        ]
        stanzas = build_new_stanzas(unmapped, {"vmk-existing"}, "code-to-docs.vmware.yaml")
        self.assertEqual(len(stanzas), 1)
        stanza = stanzas[0]
        self.assertEqual(stanza["action"], "add")
        self.assertEqual(stanza["mapping_id"], "vmk-new-role")
        self.assertEqual(stanza["target_file"], "code-to-docs.vmware.yaml")
        self.assertEqual(stanza["entry"]["status"], "undocumented")
        self.assertIn("roles/new_role/**", stanza["entry"]["code"])

    def test_uses_suggested_doc_when_present(self) -> None:
        unmapped = [
            {
                "suggested_id": "vmk-hook",
                "code": ["roles/hook/**"],
                "kind": "role",
                "reason": "code path not listed in any mapping",
                "doc_mentions": [
                    "source/operator-vmware-guide.adoc",
                    "source/other.adoc",
                ],
                "suggested_doc": "source/operator-vmware-guide.adoc",
            }
        ]
        stanzas = build_new_stanzas(unmapped, set(), "code-to-docs.vmware.yaml")
        self.assertEqual(
            stanzas[0]["entry"]["doc"], "source/operator-vmware-guide.adoc"
        )
        self.assertNotIn("status", stanzas[0]["entry"])
        self.assertIn("Also mentioned in:", stanzas[0]["entry"]["notes"])


class TestBuildUpdateStanzas(unittest.TestCase):
    def test_emits_update_when_doc_mention_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docs_repo = Path(tmp)
            source = docs_repo / "source"
            source.mkdir()
            doc_path = source / "operator-vmware-guide.adoc"
            doc_path.write_text(
                "The prelude role prepares the conversion host.\n",
                encoding="utf-8",
            )
            mappings = [
                {
                    "id": "vmk-prelude",
                    "doc": None,
                    "code": ["roles/prelude/**"],
                    "audience": "external",
                    "kind": "role",
                    "status": "undocumented",
                    "notes": "Hook role",
                }
            ]
            with patch(
                "audit_paths.find_doc_mentions",
                return_value=["source/operator-vmware-guide.adoc"],
            ):
                stanzas = build_update_stanzas(
                    mappings,
                    docs_repo,
                    "vmware",
                    "code-to-docs.vmware.yaml",
                )
        self.assertEqual(len(stanzas), 1)
        stanza = stanzas[0]
        self.assertEqual(stanza["action"], "update")
        self.assertEqual(stanza["mapping_id"], "vmk-prelude")
        self.assertEqual(
            stanza["entry"]["doc"], "source/operator-vmware-guide.adoc"
        )
        self.assertNotIn("status", stanza["entry"])
        self.assertIn("was doc: null", stanza["entry"]["notes"])
        self.assertIn("Hook role", stanza["entry"]["notes"])

    def test_skips_when_no_doc_hits(self) -> None:
        mappings = [
            {
                "id": "vmk-unknown",
                "doc": None,
                "code": ["roles/unknown/**"],
                "kind": "role",
            }
        ]
        with patch("audit_paths.find_doc_mentions", return_value=[]):
            stanzas = build_update_stanzas(
                mappings,
                Path("/nonexistent"),
                "vmware",
                "code-to-docs.vmware.yaml",
            )
        self.assertEqual(stanzas, [])


if __name__ == "__main__":
    unittest.main()
