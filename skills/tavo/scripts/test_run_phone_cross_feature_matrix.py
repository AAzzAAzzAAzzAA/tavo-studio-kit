#!/usr/bin/env python3
"""Offline tests for the retained WebView/plugin matrix runner."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import run_phone_cross_feature_matrix as runner  # noqa: E402
import aggregate_cross_feature_matrix as aggregator  # noqa: E402


class WebViewPluginMatrixOfflineTests(unittest.TestCase):
    def test_build_cases_cover_setup_visual_and_persistent_paths(self) -> None:
        cases = runner.build_webview_cases("RUN-A")
        keys = [case.key for case in cases]
        self.assertIn("bootstrap-runtime", keys)
        self.assertIn("prepare-ar-webview", keys)
        self.assertIn("seed-retained-chat", keys)
        self.assertIn("install-fixture-plugin", keys)
        self.assertGreaterEqual(len(cases), 20)
        visual_cases = [case for case in cases if case.requires_execute]
        persistent_cases = [case for case in cases if case.persistent]
        self.assertTrue(visual_cases)
        self.assertTrue(persistent_cases)
        for case in visual_cases:
            self.assertTrue(
                {"screen.png", "ui.xml", "marker.txt", "input.json", "readback.json"}.issubset(case.artifact_requirements),
                case.key,
            )
        for case in persistent_cases:
            self.assertTrue({"stable-id.txt", "stable-hash.json"}.issubset(case.artifact_requirements), case.key)

    def test_subset_selection_auto_expands_dependencies_and_fails_closed(self) -> None:
        cases = runner.build_webview_cases("RUN-SUBSET")
        selected = runner.select_webview_cases(cases, "tpg-state-persistence,ejs-json-escape")
        self.assertEqual(
            [case.key for case in selected],
            [
                "bootstrap-runtime",
                "prepare-ar-webview",
                "seed-retained-chat",
                "install-fixture-plugin",
                "ejs-json-escape",
                "tpg-state-persistence",
            ],
        )
        with self.assertRaisesRegex(RuntimeError, "Unknown case keys"):
            runner.select_webview_cases(cases, "does-not-exist")
        with self.assertRaisesRegex(RuntimeError, "duplicates"):
            runner.select_webview_cases(cases, "ejs-json-escape,ejs-json-escape")

    def test_plan_record_includes_stable_ids_and_hashes_for_persistent_cases(self) -> None:
        cases_a = runner.select_webview_cases(runner.build_webview_cases("RUN-A"), "")
        cases_b = runner.select_webview_cases(runner.build_webview_cases("RUN-B"), "")
        plan_a = runner.webview_plan_record("RUN-A", False, cases_a)
        plan_b = runner.webview_plan_record("RUN-B", False, cases_b)
        self.assertEqual(plan_a["plannedCaseCount"], len(cases_a))
        self.assertEqual(plan_a["plannedModelCalls"], len([case for case in cases_a if case.requires_execute]))
        self.assertNotEqual(plan_a["planHash"], plan_b["planHash"])
        persistent_records = [record for record in plan_a["caseRecords"] if record.get("persistent")]
        self.assertTrue(persistent_records)
        for record in persistent_records:
            self.assertIn("stableId", record)
            self.assertIn("stableHash", record)
            self.assertRegex(record["stableId"], r"^[A-Za-z0-9_.-]+$")

    def test_redaction_masks_nested_secret_material(self) -> None:
        redacted = runner.redact_sensitive(
            {
                "authorization": "Bearer abc",
                "token": "def",
                "nested": {"secret": "ghi", "keep": "ok", "deeper": {"password": "jkl"}},
                "plain": "visible",
            }
        )
        self.assertEqual(redacted["authorization"], "<redacted>")
        self.assertEqual(redacted["token"], "<redacted>")
        self.assertEqual(redacted["nested"]["secret"], "<redacted>")
        self.assertEqual(redacted["nested"]["keep"], "ok")
        self.assertEqual(redacted["nested"]["deeper"]["password"], "<redacted>")
        self.assertEqual(redacted["plain"], "visible")

    def test_reserve_case_intent_refuses_resend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            case = runner.build_webview_cases("RUN-INTENT")[4]
            first = runner.reserve_webview_case_intent(
                case_dir,
                case,
                "RUN-INTENT",
                stable_id="stable-id",
                stable_hash_value="stable-hash",
            )
            self.assertEqual(first["status"], "reserved")
            with self.assertRaises(FileExistsError):
                runner.reserve_webview_case_intent(
                    case_dir,
                    case,
                    "RUN-INTENT",
                    stable_id="stable-id",
                    stable_hash_value="stable-hash",
                )

    def test_execute_live_writes_retained_artifacts_without_phone_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact_dir = Path(temporary)
            args = runner.argparse.Namespace(
                self_check=False,
                print_plan=False,
                execute=True,
                case_keys="ejs-json-escape,tpg-state-persistence",
                run_id="RUN-EXECUTE",
                artifact_dir=str(artifact_dir),
                allow_runner_owned_deletes=False,
                device="",
                endpoint_json="",
                url="",
                auth="",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.prepare_webview_matrix_bundle(args), 0)
            manifest = json.loads((artifact_dir / "run-manifest.json").read_text(encoding="utf-8"))
            plan = json.loads((artifact_dir / "matrix-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "prepared_offline")
            self.assertEqual(plan["runId"], "RUN-EXECUTE")
            self.assertTrue((artifact_dir / "cases" / "bootstrap-runtime" / "state.json").exists())
            self.assertTrue((artifact_dir / "cases" / "ejs-json-escape" / "send-intent.json").exists())
            self.assertTrue((artifact_dir / "cases" / "tpg-state-persistence" / "stable-id.txt").exists())

    def test_main_routes_offline_modes_and_execute_delegation(self) -> None:
        for arguments, expects_execute in (
            (["runner", "--self-check"], False),
            (["runner", "--print-plan"], False),
            (["runner", "--execute"], True),
        ):
            with self.subTest(arguments=arguments):
                with (
                    mock.patch.object(sys, "argv", arguments),
                    mock.patch.object(runner, "prepare_webview_matrix_bundle", return_value=0) as execute_live,
                    contextlib.redirect_stdout(io.StringIO()) as stdout,
                ):
                    self.assertEqual(runner.webview_main(), 0)
                if expects_execute:
                    execute_live.assert_called_once()
                else:
                    execute_live.assert_not_called()
                    payload = json.loads(stdout.getvalue())
                    self.assertIsInstance(payload, dict)


class CrossFeatureEvidenceContractTests(unittest.TestCase):
    def make_context(self, root: Path) -> runner.RuntimeContext:
        ledger = runner.OwnershipLedger(root / "ownership-ledger.json", "RUN-OFFLINE")
        return runner.RuntimeContext(
            client=mock.Mock(name="offline-client"),
            artifact_dir=root,
            device="offline-device",
            run_id="RUN-OFFLINE",
            allow_deletes=False,
            timeout=30,
            registry={"markers": runner.all_markers("RUN-OFFLINE", False)},
            plan_hash="plan-hash",
            script_hash="script-hash",
            ledger=ledger,
        )

    def test_core_and_webview_scaffold_no_longer_override_each_other(self) -> None:
        core = runner.build_cases("RUN-CORE", False)
        webview = runner.build_webview_cases("RUN-WEBVIEW")
        self.assertEqual(len(core), runner.PLANNED_MODEL_CALLS)
        self.assertIsInstance(core[0], runner.CaseSpec)
        self.assertIsInstance(webview[0], runner.WebViewCaseSpec)
        self.assertIn("worldbook-keyword-hit", {case.key for case in core})
        self.assertIn("prepare-ar-webview", {case.key for case in webview})

    def test_core_subset_expands_paired_and_lifecycle_dependencies(self) -> None:
        cases = runner.build_cases("RUN-DEPENDENCIES", False)
        selected, selection = runner.resolve_case_selection(cases, "worldbook-cooldown-expired")
        self.assertEqual(
            [case.key for case in selected],
            [
                "worldbook-cooldown-trigger",
                "worldbook-cooldown-blocked",
                "worldbook-cooldown-expired",
            ],
        )
        self.assertEqual(selection["mode"], "dependency-expanded")
        self.assertEqual(
            selection["autoExpandedCaseKeys"],
            ["worldbook-cooldown-trigger", "worldbook-cooldown-blocked"],
        )
        sticky = runner.select_cases(cases, "worldbook-sticky-unactivated-control")
        self.assertEqual(
            [case.key for case in sticky],
            [
                "worldbook-sticky-trigger",
                "worldbook-sticky-carry",
                "worldbook-sticky-unactivated-control",
            ],
        )
        probability = runner.select_cases(cases, "worldbook-probability-0")
        self.assertEqual(
            [case.key for case in probability],
            ["worldbook-probability-100", "worldbook-probability-0"],
        )

    def test_exchange_separates_model_format_from_marker_semantics(self) -> None:
        case = runner.build_cases("RUN-AXES", False)[0]
        semantic_content = "WRONG_NONCE\n" + "\n".join(case.expected)
        _, infrastructure, model_format, model_semantic = runner.validate_case_exchange_axes(
            case,
            [],
            [
                {"id": 1, "index": 0, "role": "user", "content": case.prompt},
                {"id": 2, "index": 1, "role": "assistant", "content": semantic_content},
            ],
            True,
        )
        self.assertEqual(infrastructure, [])
        self.assertTrue(model_format)
        self.assertEqual(model_semantic, [])

        _, infrastructure, model_format, model_semantic = runner.validate_case_exchange_axes(
            case,
            [],
            [
                {"id": 3, "index": 0, "role": "user", "content": case.prompt},
                {"id": 4, "index": 1, "role": "assistant", "content": case.nonce + "\nwrong-marker"},
            ],
            True,
        )
        self.assertEqual(infrastructure, [])
        self.assertEqual(model_format, [])
        self.assertTrue(model_semantic)

    def test_direct_runtime_axis_survives_later_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            step_dir = Path(temporary)
            components: list[dict[str, object]] = []
            runner.run_direct_component(
                step_dir,
                components,
                "message-crud",
                lambda: {"passed": True, "stableId": 17},
            )
            with self.assertRaises(runner.DirectRuntimeBehaviorFailure) as raised:
                runner.run_direct_component(
                    step_dir,
                    components,
                    "current-chat-set",
                    lambda: (_ for _ in ()).throw(RuntimeError("current chat mismatch")),
                )
            axis = raised.exception.axis
            self.assertFalse(axis["passed"])
            self.assertEqual(axis["components"][0]["component"], "message-crud")
            persisted = json.loads((step_dir / "direct-runtime-axis.json").read_text(encoding="utf-8"))
            self.assertFalse(persisted["passed"])
            self.assertTrue(persisted["components"][0]["passed"])

    def test_greeting_exact_assertions_and_degraded_evidence(self) -> None:
        target = "GREETING_TARGET"
        exact = runner.evaluate_greeting_materialization(
            [],
            [{"id": 1, "index": 0, "role": "assistant", "content": target}],
            target,
            ("GREETING_OTHER_A", "GREETING_OTHER_B"),
            "ui-greeting-selection",
        )
        self.assertTrue(exact["passed"])
        self.assertTrue(exact["exactMaterializationProved"])
        self.assertEqual(exact["evidenceLevel"], "live-verified")

        degraded_messages = [
            {"id": 1, "index": 0, "role": "assistant", "content": "GREETING_OTHER_A"},
            {"id": 2, "index": 1, "role": "assistant", "content": target},
        ]
        degraded = runner.evaluate_greeting_materialization(
            degraded_messages,
            degraded_messages,
            target,
            ("GREETING_OTHER_A", "GREETING_OTHER_B"),
            "automatic-message-in-new-ledger-owned-chat",
        )
        self.assertTrue(degraded["passed"])
        self.assertFalse(degraded["exactMaterializationProved"])
        self.assertEqual(degraded["evidenceLevel"], "semantic-pass-observation")
        self.assertIn("selectedIndexZero", degraded["proofFailures"])
        self.assertIn("otherGreetingMarkersAbsent", degraded["proofFailures"])

    def test_append_proof_hashes_final_text_and_records_separator(self) -> None:
        proof = runner.input_append_proof("alpha", "beta", "alpha beta", "alpha beta")
        self.assertTrue(proof["passed"])
        self.assertEqual(proof["autoInsertedSeparator"], " ")
        self.assertTrue(proof["autoInsertedSeparatorObserved"])
        self.assertEqual(
            proof["combinedSha256"],
            runner.hashlib.sha256("alpha beta".encode("utf-8")).hexdigest(),
        )

    def test_scan_out_metadata_uses_actual_zero_sticky(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            context = self.make_context(Path(temporary))
            case = next(
                item
                for item in runner.build_cases(context.run_id, False)
                if item.key == "worldbook-scan-depth-outside-window"
            )
            with (
                mock.patch.object(runner, "append_owned_message", return_value={"id": 101}),
                mock.patch.object(runner, "append_neutral_window", return_value=[102, 103, 104, 105]),
            ):
                result = runner.run_case_prelude(context, case, 7, Path(temporary) / "scan-out")
            self.assertEqual(result["configuredScanDepth"], 2)
            self.assertEqual(result["configuredSticky"], 0)

    def test_tavojs_crud_uses_stable_effect_not_undocumented_return(self) -> None:
        run_id = "RUN-TAVOJS"
        _, source = runner.plugin_source(run_id, True, runner.all_markers(run_id, True))
        self.assertIn("successAuthority: 'stable-readback'", source)
        self.assertIn("successAuthority: deleted ? 'stable-not-found-readback'", source)
        self.assertNotIn("Boolean(updatedId)", source)
        self.assertNotIn("delete did not return the runner-owned id", source)

    def test_permission_absence_is_observation_not_gate_pass(self) -> None:
        record = runner.permission_observation_record(
            "lore-update",
            "是否允许修改世界书",
            observed=False,
            confirmed=False,
        )
        self.assertTrue(record["promptAbsent"])
        self.assertFalse(record["permissionGateVerified"])
        self.assertEqual(record["observation"], "prompt-not-observed")

    def test_legacy_aggregate_layers_direct_pass_and_current_chat_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            proof = Path(temporary) / "thread-roundtrip-result.json"
            proof.write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")
            legacy = {
                "failureClass": "runner_or_infrastructure",
                "runnerInfrastructureFailures": ["RuntimeError('Current-chat readback did not match 7')"],
                "traceback": "Current-chat readback did not match 7",
                "passed": False,
            }
            axes, components = aggregator.derive_evidence_axes(legacy, (), (proof,))
            self.assertFalse(axes["runnerTransportInfra"]["passed"])
            self.assertFalse(axes["directRuntimeBehavior"]["passed"])
            self.assertTrue(any(item.get("passed") is True for item in components))
            self.assertTrue(any(item.get("component") == "current-chat-set-after-direct-runtime" for item in components))
            self.assertEqual(aggregator.interpreted_failure_class(axes), "multi_axis")

    def test_aggregate_build_accepts_new_axis_results_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            output_dir = root / "aggregate"
            run_dir.mkdir()
            cases = runner.build_cases("RUN-AGGREGATE", False)
            plan = runner.plan_record("RUN-AGGREGATE", False, cases)
            (run_dir / "plan.json").write_text(json.dumps(plan) + "\n", encoding="utf-8")
            (run_dir / "run-manifest.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "startedAt": "2026-07-10T00:00:00+00:00",
                        "restorationPassed": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            for index, case in enumerate(cases, start=1):
                step_dir = run_dir / "model-calls" / case.family / case.step_name
                step_dir.mkdir(parents=True)
                result = {
                    "schemaVersion": "1.1.0",
                    "ordinal": case.ordinal,
                    "key": case.key,
                    "family": case.family,
                    "passed": True,
                    "failureClass": None,
                    "exchangeComplete": True,
                    "userMessageId": index * 2,
                    "assistantMessageId": index * 2 + 1,
                    "evidenceAxes": {
                        "runnerTransportInfra": {"evaluated": True, "passed": True, "failures": []},
                        "directRuntimeBehavior": {"evaluated": False, "passed": None, "failures": []},
                        "modelFormat": {"evaluated": True, "passed": True, "failures": []},
                        "modelSemantic": {"evaluated": True, "passed": True, "failures": []},
                    },
                }
                (step_dir / "result.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
                (step_dir / "send-start.json").write_text("{}\n", encoding="utf-8")
            aggregate = aggregator.build_aggregate([run_dir], output_dir, root)
            self.assertTrue(aggregate["coverage"]["coverageComplete"])
            self.assertEqual(aggregate["coverage"]["selectedCases"], runner.PLANNED_MODEL_CALLS)
            self.assertEqual(aggregate["coverage"]["modelFormatFailedCases"], 0)
            self.assertEqual(aggregate["coverage"]["modelSemanticFailedCases"], 0)

    def test_runner_offline_self_check_covers_new_contract(self) -> None:
        report = runner.offline_self_check()
        self.assertTrue(report["passed"], report.get("failures"))
        self.assertTrue(report["checks"]["dependentSelectionExpanded"])
        self.assertTrue(report["checks"]["inputAppendProofHashesExactFinalText"])


if __name__ == "__main__":
    unittest.main()
