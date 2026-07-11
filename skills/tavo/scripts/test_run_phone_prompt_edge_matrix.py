#!/usr/bin/env python3
"""Offline tests for the prompt-edge runner."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from unittest import mock


from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import run_phone_prompt_edge_matrix as edge_runner  # noqa: E402


class PromptEdgeRunnerOfflineTests(unittest.TestCase):
    def test_offline_cli_modes_never_enter_live_executor(self) -> None:
        for arguments in (["runner", "--self-check"], ["runner", "--print-plan"]):
            with (
                self.subTest(arguments=arguments),
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(
                    edge_runner,
                    "execute_live",
                    side_effect=AssertionError("offline mode entered live executor"),
                ) as execute_live,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(edge_runner.main(), 0)
                execute_live.assert_not_called()

    def test_no_action_and_execute_without_endpoint_fail_before_live_executor(self) -> None:
        for arguments in (["runner"], ["runner", "--execute"]):
            with (
                self.subTest(arguments=arguments),
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(edge_runner, "load_endpoint", return_value={}),
                mock.patch.object(
                    edge_runner,
                    "execute_live",
                    side_effect=AssertionError("unsafe CLI reached live executor"),
                ) as execute_live,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(edge_runner.main(), 2)
                execute_live.assert_not_called()

    def test_plan_has_unique_cases_nonces_and_stable_message_ids(self) -> None:
        cases_a = edge_runner.build_cases("RUN-A", False)
        cases_b = edge_runner.build_cases("RUN-B", False)
        self.assertEqual(len(cases_a), 34)
        self.assertEqual(len({case.key for case in cases_a}), len(cases_a))
        self.assertEqual(len({case.nonce for case in cases_a}), len(cases_a))
        self.assertTrue(all(case.stable_message_ids["user"].endswith("-user") for case in cases_a))
        self.assertTrue(all(case.stable_message_ids["assistant"].endswith("-assistant") for case in cases_a))
        self.assertFalse({case.nonce for case in cases_a} & {case.nonce for case in cases_b})
        self.assertNotEqual(
            edge_runner.plan_record("RUN-A", False, cases_a)["planHash"],
            edge_runner.plan_record("RUN-B", False, cases_b)["planHash"],
        )

    def test_case_subset_auto_expands_dependency_and_preserves_plan_order(self) -> None:
        cases = edge_runner.build_cases("RUN-SUBSET", False)
        selected, selected_keys = edge_runner.expand_case_dependencies(cases, "keyword-case-sensitive-ascii-miss")
        self.assertEqual(selected_keys[0], "worldbook-precedence-baseline")
        self.assertEqual(selected_keys[-1], "keyword-case-sensitive-ascii-miss")
        self.assertEqual([case.key for case in selected], selected_keys)
        with self.assertRaisesRegex(RuntimeError, "Unknown"):
            edge_runner.expand_case_dependencies(cases, "does-not-exist")
        with self.assertRaisesRegex(RuntimeError, "duplicates"):
            edge_runner.expand_case_dependencies(cases, "keyword-case-sensitive-ascii-miss,keyword-case-sensitive-ascii-miss")

    def test_plan_record_is_verifiable_and_redacts_secrets(self) -> None:
        cases = edge_runner.build_cases("RUN-PLAN", True)
        plan = edge_runner.plan_record("RUN-PLAN", True, cases)
        self.assertEqual(plan["plannedModelCalls"], 34)
        self.assertEqual(plan["families"], list(edge_runner.MODEL_FAMILIES))
        self.assertTrue(plan["safety"]["executeRequiresFlag"])
        self.assertTrue(plan["safety"]["secretRedaction"])
        redacted = edge_runner.redact(
            {
                "authorization": "Bearer secret-token",
                "nested": {"auth": "abc", "token": "xyz"},
                "items": ["Bearer hidden", {"api_key": "s3cr3t"}],
            }
        )
        self.assertEqual(redacted["authorization"], "<redacted>")
        self.assertEqual(redacted["nested"]["auth"], "<redacted>")
        self.assertEqual(redacted["nested"]["token"], "<redacted>")
        self.assertEqual(redacted["items"][0], "Bearer <redacted>")
        self.assertEqual(redacted["items"][1]["api_key"], "<redacted>")

    def test_self_check_and_print_plan_emit_json_without_live_executor(self) -> None:
        for arguments, expected_key in (
            (["runner", "--self-check", "--run-id", "RUN-CLI"], "ok"),
            (["runner", "--print-plan", "--run-id", "RUN-CLI"], "schemaVersion"),
        ):
            with (
                self.subTest(arguments=arguments),
                mock.patch.object(sys, "argv", arguments),
                mock.patch.object(
                    edge_runner,
                    "execute_live",
                    side_effect=AssertionError("offline output entered live executor"),
                ) as execute_live,
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                self.assertEqual(edge_runner.main(), 0)
                payload = json.loads(stdout.getvalue())
                self.assertIn(expected_key, payload)
                execute_live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
