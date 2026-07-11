#!/usr/bin/env python3
"""Offline tests for the asset roundtrip matrix runner."""

from __future__ import annotations

import argparse
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

import run_phone_asset_roundtrip_matrix as runner  # noqa: E402


class AssetRoundtripMatrixOfflineTests(unittest.TestCase):
    def test_self_check_and_print_plan_stay_offline(self) -> None:
        for arguments in (["runner", "--self-check"], ["runner", "--print-plan"]):
            with (
                self.subTest(arguments=arguments),
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(
                    runner,
                    "execute_live",
                    side_effect=AssertionError("offline mode reached live executor"),
                ) as execute_live,
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                self.assertEqual(runner.main(), 0)
                self.assertTrue(json.loads(stdout.getvalue()))
                execute_live.assert_not_called()

    def test_execute_requires_explicit_authorization_and_rejects_missing_endpoint(self) -> None:
        for arguments in (["runner"], ["runner", "--execute"]):
            with (
                self.subTest(arguments=arguments),
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(
                    runner,
                    "execute_live",
                    side_effect=AssertionError("unsafe CLI reached live executor"),
                ) as execute_live,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                if arguments == ["runner"]:
                    with self.assertRaises(SystemExit) as raised:
                        runner.main()
                    self.assertEqual(raised.exception.code, 2)
                    execute_live.assert_not_called()
                else:
                    with self.assertRaises(AssertionError):
                        runner.main()
                    execute_live.assert_called_once()

    def test_case_selection_preserves_plan_order_and_rejects_bad_keys(self) -> None:
        cases = runner.build_cases()
        selected = runner.select_cases(cases, "character-png,character-native")
        self.assertEqual([case.key for case in selected], ["character-native", "character-png"])
        self.assertEqual(len(selected), 2)
        with self.assertRaisesRegex(RuntimeError, "Unknown"):
            runner.select_cases(cases, "does-not-exist")
        with self.assertRaisesRegex(RuntimeError, "duplicates"):
            runner.select_cases(cases, "character-native,character-native")

    def test_character_and_persona_payloads_include_the_expected_max_fields(self) -> None:
        card = runner.build_character_card("RUN-CHECK")
        self.assertEqual(card["spec"], "chara_card_v2")
        self.assertEqual(card["spec_version"], "2.0")
        self.assertIn("character_book", card["data"])
        self.assertIn("scan_depth", card["data"]["character_book"])
        self.assertIn("token_budget", card["data"]["character_book"])
        self.assertIn("extensions", card["data"])
        persona = runner.build_persona_payload("RUN-CHECK")
        self.assertTrue(persona["avatar"].startswith("data:image/png;base64,"))
        self.assertFalse(persona["active"])

    def test_base_png_is_valid_and_node_helpers_point_at_existing_tools(self) -> None:
        png = runner.make_base_png()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(runner.EMBED_PNG.name, "embed_st_card_png.mjs")
        self.assertEqual(runner.EXTRACT_PNG.name, "extract_st_card_png.mjs")
        with mock.patch.object(runner, "run_node", return_value={"ok": True}) as run_node:
            runner.node_embed_png(Path("/tmp/base.png"), Path("/tmp/card.json"), Path("/tmp/out.png"), chara_only=True)
            runner.node_extract_png(Path("/tmp/out.png"), Path("/tmp/extracted.json"), prefer_chara=True)
        self.assertEqual(run_node.call_count, 2)
        first_script, first_args, first_output = run_node.call_args_list[0].args
        self.assertEqual(first_script, runner.EMBED_PNG)
        self.assertIn("--chara-only", first_args)
        self.assertEqual(first_output.name, "out.png.embed.json")

    def test_surface_blocked_results_are_structured(self) -> None:
        case = runner.build_cases()[0]
        surface = runner.SurfaceReport(("tavo_character_get",), ("tavo_character_create",), {}, {"availableTools": ["tavo_character_get"]})
        result = runner.surface_blocked_result(case, ["tavo_character_create"], surface)
        self.assertTrue(result["surfaceBlocked"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["block"]["kind"], "surface-blocked")
        self.assertIn("tavo_character_create", result["block"]["missingTools"])

    def test_plan_and_validation_manifest_shapes_are_verifiable(self) -> None:
        cases = runner.select_cases(runner.build_cases(), "character-native,character-png")
        plan = runner.plan_record("RUN-PLAN", cases, full_matrix_selection=False)
        self.assertEqual(plan["schemaVersion"], "1.0.0")
        self.assertEqual(plan["plannedCases"], 2)
        manifest = runner.validation_manifest(
            run_id="RUN-MANIFEST",
            artifact_dir=Path("/tmp/asset-roundtrip"),
            plan_hash="plan-hash",
            script_hash="script-hash",
            cases=cases,
            status="blocked",
            started_at="2026-07-11T00:00:00+00:00",
            finished_at="2026-07-11T00:00:01+00:00",
            surface={"availableTools": ["tavo_character_get"]},
            summary={"runnerFailures": []},
            blocked_cases=["character-native"],
            results=[{"key": "character-native", "status": "blocked"}],
        )
        runner.validate_validation_manifest_shape(manifest)
        self.assertEqual(manifest["status"], "blocked")
        self.assertIn("plan.json", manifest["artifacts"])

    def test_self_check_reports_static_surface_and_payload_hashes(self) -> None:
        report = runner.self_check()
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["plan"]["caseCount"], 4)
        self.assertIn("toolCount", report["staticSurface"])
        self.assertIn("character", report)
        self.assertIn("persona", report)

    def test_local_ledger_helpers_do_not_require_surface_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = runner.load_ledger(root / "ownership-ledger.json", "RUN-LEDGER")
            runner.claim_asset(ledger, "character", 123, case="character-native")
            runner.save_ledger(root / "ownership-ledger.json", ledger)
            loaded = runner.load_json(root / "ownership-ledger.json")
        self.assertEqual(loaded["runId"], "RUN-LEDGER")
        self.assertEqual(loaded["character"][0]["id"], 123)


if __name__ == "__main__":
    unittest.main()
