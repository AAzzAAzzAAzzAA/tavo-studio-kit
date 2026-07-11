#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import run_phone_plugin_092_matrix as runner  # noqa: E402


class PhonePlugin092MatrixTests(unittest.TestCase):
    def test_catalog_is_exact_f01_f11_and_well_formed(self) -> None:
        cases = runner.build_cases()
        self.assertEqual([case.key for case in cases], [f"F{index:02d}" for index in range(1, 12)])
        self.assertEqual(runner.validate_catalog(cases), [])
        self.assertTrue(all(case.assertions for case in cases))
        self.assertTrue({"F05", "F06", "F07", "F08", "F09", "F10"} <= {case.key for case in cases if case.requires_model_fixture})
        self.assertEqual(runner.PROTECTED_CHAT_IDS, frozenset())

    def test_subset_expands_dependencies_in_canonical_order(self) -> None:
        selected = runner.expand_cases(runner.build_cases(), "F09")
        self.assertEqual([case.key for case in selected], ["F01", "F05", "F07", "F08", "F09"])
        with self.assertRaisesRegex(RuntimeError, "Unknown"):
            runner.expand_cases(runner.build_cases(), "F12")
        with self.assertRaisesRegex(RuntimeError, "duplicates"):
            runner.expand_cases(runner.build_cases(), "F01,F01")

    def test_evidence_evaluation_never_promotes_missing_or_false_results(self) -> None:
        case = runner.build_cases()[0]
        blocked = runner.evaluate_case(case, {})
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(set(blocked["missing"]), {item.key for item in case.assertions})
        failed = runner.evaluate_case(case, {"assertions": {case.assertions[0].key: False}})
        self.assertEqual(failed["status"], "failed")
        passed = runner.evaluate_case(
            case,
            {"assertions": {assertion.key: True for assertion in case.assertions}},
        )
        self.assertEqual(passed["status"], "passed")
        matrix = runner.evaluate_matrix(runner.build_cases(), {"cases": {}})
        self.assertEqual(matrix["counts"], {"passed": 0, "failed": 0, "blocked": 11})
        self.assertFalse(matrix["ok"])

    def test_prepare_is_deterministic_private_and_contains_expected_entry_forms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = runner.prepare_bundle(root / "one", "RUN-DETERMINISTIC", runner.build_cases())
            two = runner.prepare_bundle(root / "two", "RUN-DETERMINISTIC", runner.build_cases())
            hashes_one = {item["case"]: item["sha256"] for item in one["packages"]}
            hashes_two = {item["case"]: item["sha256"] for item in two["packages"]}
            self.assertEqual(hashes_one, hashes_two)
            self.assertEqual(list(hashes_one), [f"F{index:02d}" for index in range(1, 12)] + ["INSPECTOR"])
            self.assertEqual(stat.S_IMODE((root / "one").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((root / "one" / "plan.json").stat().st_mode), 0o600)
            stored_plan = json.loads((root / "one" / "plan.json").read_text(encoding="utf-8"))
            stored_hash = stored_plan.pop("planHash")
            self.assertEqual(stored_hash, runner.canonical_hash(stored_plan))
            self.assertEqual(stored_plan["cases"][0]["caseKey"], "F01")
            self.assertEqual(stored_plan["cases"][0]["assertions"][0]["assertionKey"], "entry_started_once")
            self.assertNotIn("key", stored_plan["cases"][0])
            self.assertNotIn("key", stored_plan["cases"][0]["assertions"][0])

            manifests: dict[str, dict] = {}
            entries: dict[str, str] = {}
            package_names: dict[str, list[str]] = {}
            for package in one["packages"]:
                path = Path(package["package"])
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    package_names[package["case"]] = names
                    self.assertEqual(names, sorted(names))
                    self.assertEqual(names.count("manifest.json"), 1)
                    manifests[package["case"]] = json.loads(archive.read("manifest.json"))
                    if "entry.js" in names:
                        entries[package["case"]] = archive.read("entry.js").decode("utf-8")
                    self.assertFalse(any(name.startswith("/") or "\\" in name or ".." in Path(name).parts for name in names))

            self.assertEqual(manifests["F01"]["entry"], "entry.js")
            self.assertNotIn("contributes", manifests["F01"])
            self.assertNotIn("entry", manifests["F02"])
            self.assertEqual(manifests["F02"]["scripts"]["actions"], "legacy.js")
            self.assertEqual(manifests["F03"]["entry"], "entry.js")
            self.assertEqual(manifests["F03"]["scripts"]["actions"], "legacy.js")
            self.assertIn("settings", manifests["F04"]["contributes"])
            self.assertIn("input", manifests["F06"]["permissions"])
            self.assertIn("generate", manifests["F07"]["permissions"])
            self.assertIn("tts", manifests["F11"]["permissions"])
            self.assertEqual(manifests["INSPECTOR"]["id"], runner.plugin_id("RUN-DETERMINISTIC", "INSPECTOR"))
            inspector_actions = manifests["INSPECTOR"]["contributes"]["inputActions"]
            self.assertEqual(len(inspector_actions), 22)
            self.assertEqual(
                [action["id"] for action in inspector_actions[:2]],
                ["dump-f01", "clear-f01"],
            )
            self.assertIn(runner.DUMP_SENTINEL, entries["INSPECTOR"])
            self.assertIn("tavo.input.set", entries["INSPECTOR"])
            self.assertIn("tavo.unset", entries["INSPECTOR"])
            self.assertNotIn("contributes", manifests["F01"])
            self.assertIn("fixture-scenarios.json", package_names["F09"])

    def test_record_helper_projects_whitelisted_evidence_and_logs_unique_sentinel(self) -> None:
        source = runner.record_helper("RUN-EVIDENCE", "F06")
        self.assertIn(runner.CONSOLE_SENTINEL, source)
        self.assertIn("EVIDENCE_SAFE_KEYS", source)
        self.assertIn("runId: EVIDENCE_RUN_ID", source)
        self.assertIn("case: EVIDENCE_CASE", source)
        self.assertIn("runtimeId: EVIDENCE_RUNTIME_ID", source)
        self.assertIn("seq: previousSeq + 1", source)
        self.assertIn(f"existing.slice(-{runner.MAX_EVIDENCE_ROWS - 1})", source)
        self.assertIn("markers: markers.slice", source)
        self.assertIn("Bearer|Basic", source)
        self.assertIn("EVIDENCE_CREDENTIAL_PATTERN", source)
        self.assertNotIn("payload: payload", source)

    def test_f08_modes_f09_delays_and_f11_voice_actions_are_explicit(self) -> None:
        cases = {case.key: case for case in runner.build_cases()}

        f08 = runner.fixture_files("RUN-BRANCHES", cases["F08"])
        f08_manifest = json.loads(f08["manifest.json"])
        f08_mode = f08_manifest["contributes"]["settings"]["schema"][0]
        self.assertEqual(f08_mode["key"], "mode")
        self.assertEqual(f08_mode["options"], ["append", "empty", "throw", "timeout"])
        f08_entry = f08["entry.js"].decode("utf-8")
        self.assertIn("tavo.plugin.config.get('mode')", f08_entry)
        self.assertNotIn("event.text.includes('[F08_", f08_entry)

        f09 = runner.fixture_files("RUN-BRANCHES", cases["F09"])
        f09_manifest = json.loads(f09["manifest.json"])
        f09_keys = [row["key"] for row in f09_manifest["contributes"]["settings"]["schema"]]
        self.assertEqual(f09_keys, ["cancelWindow", "delayMs"])
        scenarios = json.loads(f09["fixture-scenarios.json"])["scenarios"]
        self.assertEqual(scenarios["before-first"]["delayBeforeFirstMs"], 2500)
        self.assertEqual(scenarios["before-first"]["delayAfterFirstMs"], 0)
        self.assertEqual(scenarios["after-first"]["delayBeforeFirstMs"], 0)
        self.assertEqual(scenarios["after-first"]["delayAfterFirstMs"], 2500)
        self.assertIn("partial=false", scenarios["before-first"]["description"])
        self.assertIn("partial=true", scenarios["after-first"]["description"])

        f11 = runner.fixture_files("RUN-BRANCHES", cases["F11"])
        f11_manifest = json.loads(f11["manifest.json"])
        self.assertEqual(
            [action["id"] for action in f11_manifest["contributes"]["sidebar"]],
            ["missing", "character", "user", "both", "queue", "stop"],
        )
        f11_entry = f11["entry.js"].decode("utf-8")
        self.assertIn("{ character }", f11_entry)
        self.assertIn("{ persona }", f11_entry)
        self.assertIn("{ character, persona }", f11_entry)
        self.assertIn("Boolean(result)", f11_entry)
        self.assertIn("result ? 'tts-accepted' : 'tts-rejected'", f11_entry)
        self.assertIn("{ queue: true }", f11_entry)
        self.assertIn("record('queue-results'", f11_entry)
        self.assertIn("tavo.tts.stop()", f11_entry)
        self.assertIn('"first"', f11_entry)
        self.assertIn('"second"', f11_entry)

    def test_f06_has_isolation_canary_and_never_records_attachment_payloads(self) -> None:
        cases = {case.key: case for case in runner.build_cases()}
        f06 = runner.fixture_files("RUN-INPUT", cases["F06"])
        entry = f06["entry.js"].decode("utf-8")
        assertion_map = {assertion.key: assertion for assertion in cases["F06"].assertions}

        self.assertEqual(entry.count("tavo.plugin.on('input:beforeSend'"), 2)
        self.assertIn("record('before-canary', f06Evidence(event))", entry)
        self.assertIn("f06SafeAttachmentMeta", entry)
        self.assertIn("candidate.length", entry)
        self.assertNotIn("candidate.name", entry)
        self.assertNotIn("candidate.data", entry)
        self.assertNotIn("candidate.url", entry)
        self.assertTrue(assertion_map["second_handler_isolated"].required)
        self.assertFalse(assertion_map["cancel_preserves_attachments_if_exposed"].required)

    def test_plan_and_staging_assertions_cannot_be_confused_with_live_results(self) -> None:
        plan = runner.plan_record("RUN-STAGING", runner.build_cases())
        self.assertTrue(plan["evidenceInspector"]["separatePlugin"])
        self.assertFalse(plan["safety"]["executeRunsRuntimeAssertions"])
        self.assertIn("before-first", plan["modelFixtureScenarios"]["F09"])

        expected_id = runner.plugin_id("RUN-STAGING", "F01")
        package = {"pluginId": expected_id, "sha256": "a" * 64}

        def response(payload: dict) -> dict:
            return {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}

        assertions = runner.staging_assertions(
            package,
            response({"ok": True}),
            response({"ok": True}),
            response({"ok": True}),
            response({"ok": True, "plugin": {"enabled": False, "manifest": {"id": expected_id}}}),
        )
        self.assertTrue(all(value is True for value in assertions.values()), assertions)
        failed_early = runner.staging_assertions(package, response({"ok": False}), {}, {}, {})
        self.assertTrue(failed_early["packageSha256Recorded"])
        self.assertFalse(failed_early["dryRunAccepted"])
        self.assertFalse(failed_early["installAccepted"])
        self.assertIsNone(failed_early["readbackDisabled"])

    def test_prepare_refuses_nonempty_output_and_intent_refuses_resend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "bundle"
            output.mkdir()
            (output / "existing").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "absent or empty"):
                runner.prepare_bundle(output, "RUN-NONEMPTY", runner.build_cases())
            intent = root / "intent.json"
            runner.reserve_intent(intent, {"case": "F01"})
            with self.assertRaises(FileExistsError):
                runner.reserve_intent(intent, {"case": "F01"})

    def test_self_check_passes_without_phone_or_network(self) -> None:
        with (
            mock.patch.object(runner, "adb_gate", side_effect=AssertionError("self-check reached ADB")),
            mock.patch.object(runner.TavoMcp, "rpc", side_effect=AssertionError("self-check reached MCP")),
        ):
            result = runner.self_check("RUN-SELF-CHECK")
        self.assertTrue(result["ok"], result["failures"])
        self.assertEqual(result["caseCount"], 11)
        self.assertGreater(result["assertionCount"], 30)

    def test_offline_cli_modes_never_enter_live_execution(self) -> None:
        actions = (
            ["runner", "--self-check", "--run-id", "RUN-CLI"],
            ["runner", "--print-plan", "--run-id", "RUN-CLI"],
        )
        for arguments in actions:
            with (
                self.subTest(arguments=arguments),
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(runner, "execute_live", side_effect=AssertionError("offline mode entered live executor")) as live,
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                self.assertEqual(runner.main(), 0)
                self.assertIsInstance(json.loads(stdout.getvalue()), dict)
                live.assert_not_called()

    def test_prepare_cli_never_enters_live_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            arguments = [
                "runner",
                "--prepare",
                "--run-id",
                "RUN-PREPARE",
                "--output",
                str(Path(temporary) / "bundle"),
            ]
            with (
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(runner, "execute_live", side_effect=AssertionError("prepare entered live executor")) as live,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(runner.main(), 0)
                live.assert_not_called()

    def test_live_execution_refuses_protected_chat_before_endpoint_adb_or_mcp(self) -> None:
        args = argparse.Namespace(
            run_id="RUN-PROTECTED",
            confirm=runner.CONFIRMATION,
            test_chat_id=900001,
            protected_chat_ids=[900001],
            fixture_base_url="http://192.0.2.10:18792/v1",
            output=Path("/tmp/should-not-exist-tavo-092"),
            endpoint_file=Path("/tmp/does-not-matter"),
            device="test-device",
        )
        with (
            mock.patch.object(runner, "read_private_json", side_effect=AssertionError("read endpoint after protected chat")),
            mock.patch.object(runner, "adb_gate", side_effect=AssertionError("ADB after protected chat")),
            self.assertRaisesRegex(RuntimeError, "protected"),
        ):
            runner.execute_live(args, runner.build_cases())

    def test_live_execution_requires_confirmation_and_absolute_fixture_url(self) -> None:
        base = dict(
            run_id="RUN-SAFETY",
            test_chat_id=900001,
            protected_chat_ids=[900000],
            output=Path("/tmp/not-used"),
            endpoint_file=Path("/tmp/not-used"),
            device="test-device",
        )
        with self.assertRaisesRegex(RuntimeError, "confirm"):
            runner.execute_live(
                argparse.Namespace(**base, confirm="", fixture_base_url="http://127.0.0.1:1/v1"),
                runner.build_cases(),
            )
        with self.assertRaisesRegex(RuntimeError, "absolute"):
            runner.execute_live(
                argparse.Namespace(**base, confirm=runner.CONFIRMATION, fixture_base_url="127.0.0.1:1/v1"),
                runner.build_cases(),
            )

    def test_private_endpoint_reader_rejects_public_mode_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            endpoint = root / "endpoint.json"
            endpoint.write_text('{"url":"http://127.0.0.1/mcp","auth":"Bearer hidden"}', encoding="utf-8")
            endpoint.chmod(0o600)
            self.assertIn("url", runner.read_private_json(endpoint))
            endpoint.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "mode-0600"):
                runner.read_private_json(endpoint)
            endpoint.chmod(0o600)
            link = root / "link.json"
            link.symlink_to(endpoint)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                runner.read_private_json(link)

    def test_redaction_removes_nested_and_embedded_credentials(self) -> None:
        payload = runner.redact(
            {
                "authorization": "Bearer secret",
                "nested": {
                    "client-secret": "value",
                    "note": "sk-1234567890abcdefghijklmnop",
                },
            }
        )
        self.assertEqual(payload["authorization"], "<redacted>")
        self.assertEqual(payload["nested"]["client-secret"], "<redacted>")
        self.assertEqual(payload["nested"]["note"], "<redacted-secret>")

    def test_safe_stager_source_has_no_message_or_input_send_tool_call(self) -> None:
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn('client.tool("tavo_input_send"', source)
        self.assertNotIn('client.tool("tavo_message_', source)
        self.assertIn('client.tool("tavo_plugin_install"', source)


if __name__ == "__main__":
    unittest.main()
