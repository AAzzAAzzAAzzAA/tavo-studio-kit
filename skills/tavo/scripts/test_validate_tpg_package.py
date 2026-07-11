#!/usr/bin/env python3
"""Offline regression tests for the Tavo 0.92 plugin package validators."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
FIXTURES = SKILL_ROOT / "assets" / "fixtures"
TEMPLATES = SKILL_ROOT / "assets" / "templates"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_tavo_artifact import (  # noqa: E402
    is_safe_package_path as artifact_path_is_safe,
    resolve_tpg_entry,
    validate as validate_artifact,
)
from validate_tpg_package import is_safe_relative, validate_package  # noqa: E402


def write_manifest(root: Path, payload: dict[str, object]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class TpgPackageFixtureTests(unittest.TestCase):
    def test_current_entry_template_and_fixture_pass(self) -> None:
        for root in (TEMPLATES / "plugin-minimal", FIXTURES / "plugin-minimal"):
            with self.subTest(root=root):
                result = validate_package(root)
                self.assertEqual((), result.errors)
                self.assertEqual("entry", result.entry_source)
                self.assertEqual("entry.js", result.entry_path)
                self.assertTrue((root / "entry.js").is_file())
                self.assertFalse((root / "actions.js").exists())

    def test_legacy_alias_is_accepted_only_as_fallback(self) -> None:
        result = validate_package(FIXTURES / "plugin-legacy")
        self.assertEqual((), result.errors)
        self.assertEqual("scripts.actions", result.entry_source)
        self.assertEqual("legacy-actions.js", result.entry_path)
        manifest = json.loads((FIXTURES / "plugin-legacy" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(("scripts.actions", "legacy-actions.js"), resolve_tpg_entry(manifest))

    def test_root_entry_wins_and_ignored_legacy_file_may_be_absent(self) -> None:
        result = validate_package(FIXTURES / "plugin-dual")
        self.assertEqual((), result.errors)
        self.assertEqual("entry", result.entry_source)
        self.assertEqual("entry.js", result.entry_path)
        self.assertFalse((FIXTURES / "plugin-dual" / "ignored-missing-legacy.js").exists())
        manifest = json.loads((FIXTURES / "plugin-dual" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(("entry", "entry.js"), resolve_tpg_entry(manifest))

    def test_hook_only_entry_needs_no_contributions(self) -> None:
        root = FIXTURES / "plugin-hook-only"
        result = validate_package(root)
        self.assertEqual((), result.errors)
        manifest_errors = validate_artifact(root / "manifest.json", "tpg-manifest")
        self.assertEqual([], manifest_errors)

    def test_single_wrapping_folder_is_selected_as_plugin_root(self) -> None:
        result = validate_package(FIXTURES / "plugin-nested")
        self.assertEqual((), result.errors)
        self.assertEqual((FIXTURES / "plugin-nested" / "wrapper").resolve(), result.plugin_root)
        self.assertEqual(result.plugin_root / "manifest.json", result.manifest_path)

    def test_multiple_nested_manifests_are_rejected_as_ambiguous(self) -> None:
        result = validate_package(FIXTURES / "plugin-ambiguous")
        self.assertTrue(any("multiple nested manifest.json" in error for error in result.errors))
        self.assertIsNone(result.plugin_root)

    def test_root_manifest_wins_over_multiple_nested_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, {"id": "codex.root-wins", "name": "Root Wins", "version": "0.92.0"})
            write_manifest(root / "one", {"id": "codex.one", "name": "One", "version": "0.92.0"})
            write_manifest(root / "two", {"id": "codex.two", "name": "Two", "version": "0.92.0"})
            result = validate_package(root)
            self.assertEqual((), result.errors)
            self.assertEqual(root.resolve(), result.plugin_root)

    def test_dangerous_manifest_paths_are_rejected_by_both_validators(self) -> None:
        root = FIXTURES / "plugin-dangerous-path"
        package_errors = "\n".join(validate_package(root).errors)
        for label in (
            "entry",
            "cover",
            "scripts.actions",
            "contributes.inputActions[0].icon",
            "contributes.htmlFragments[0].src",
        ):
            with self.subTest(label=label):
                self.assertIn(label, package_errors)
        artifact_errors = validate_artifact(root / "manifest.json", "tpg-manifest")
        self.assertGreaterEqual(len(artifact_errors), 5)

    def test_missing_effective_entry_file_is_rejected(self) -> None:
        result = validate_package(FIXTURES / "plugin-missing-entry")
        self.assertTrue(any("entry file does not exist" in error for error in result.errors))

    def test_actions_require_an_entry_or_legacy_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(
                root,
                {
                    "id": "codex.no-entry",
                    "name": "No Entry",
                    "version": "0.92.0",
                    "contributes": {"inputActions": [{"id": "x", "label": "X"}]},
                },
            )
            result = validate_package(root)
            self.assertTrue(any("entry is required" in error for error in result.errors))
            artifact_errors = validate_artifact(root / "manifest.json", "tpg-manifest")
            self.assertTrue(any("entry is required" in error for error in artifact_errors))

    def test_external_symlink_entry_is_rejected_without_reading_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "plugin"
            write_manifest(
                root,
                {"id": "codex.external-link", "name": "External Link", "version": "0.92.0", "entry": "entry.js"},
            )
            outside = base / "outside.js"
            outside.write_text("external marker\n", encoding="utf-8")
            (root / "entry.js").symlink_to(outside)
            errors = "\n".join(validate_package(root).errors)
            self.assertIn("outside the selected plugin root", errors)
            self.assertIn("external symlink", errors)

    def test_old_manifest_filename_is_not_a_manifest_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_manifest = root / "tavo-plugin.json"
            old_manifest.write_text(
                json.dumps({"id": "codex.old-name", "name": "Old Name", "version": "0.91.0"}),
                encoding="utf-8",
            )
            self.assertTrue(any("missing manifest.json" in error for error in validate_package(root).errors))
            self.assertTrue(
                any("filename must be manifest.json" in error for error in validate_artifact(old_manifest, "tpg-manifest"))
            )

    def test_empty_manifest_is_not_treated_as_an_unparsed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, {})
            errors = "\n".join(validate_package(root).errors)
            self.assertIn("manifest id", errors)
            self.assertIn("manifest name", errors)
            self.assertIn("manifest version", errors)

    def test_path_predicates_reject_all_documented_unsafe_forms(self) -> None:
        unsafe = [
            "",
            " entry.js",
            "entry.js ",
            "/entry.js",
            "../entry.js",
            "ui/../entry.js",
            "ui\\entry.js",
            "https://example.invalid/entry.js",
            "C:/entry.js",
            "./entry.js",
            "ui//entry.js",
        ]
        for value in unsafe:
            with self.subTest(value=value):
                self.assertFalse(is_safe_relative(value))
                self.assertFalse(artifact_path_is_safe(value))
        for value in ("entry.js", "runtime/entry.js", "icons/menu icon.png"):
            with self.subTest(value=value):
                self.assertTrue(is_safe_relative(value))
                self.assertTrue(artifact_path_is_safe(value))

    def test_schema_declares_entry_precedence_and_legacy_deprecation(self) -> None:
        schema = json.loads(
            (SKILL_ROOT / "assets" / "schemas" / "tpg-manifest.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("entry", schema["properties"])
        self.assertTrue(schema["properties"]["scripts"]["properties"]["actions"]["deprecated"])


if __name__ == "__main__":
    unittest.main()
