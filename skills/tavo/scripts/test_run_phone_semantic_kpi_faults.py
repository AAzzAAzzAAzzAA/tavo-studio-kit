#!/usr/bin/env python3
"""Fault-injection tests for the semantic KPI runner's transaction files."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import run_phone_semantic_kpi as runner  # noqa: E402


class SemanticKpiTransactionFaultTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.artifact_dir = Path(temporary.name)
        self.client = mock.Mock(name="offline_client")
        self.spec = runner.CallSpec(
            family="character-thread",
            ordinal=1,
            chat_id=42,
            prompt="Return SEMANTIC_OK for NONCE_TEST.",
            nonce="NONCE_TEST",
            expected=["SEMANTIC_OK"],
            attempt="attempt-1",
        )
        self.execution_meta = {
            "epochId": "epoch-hash",
            "scriptHash": "script-hash",
            "planHash": "plan-hash",
            "contextHash": "context-hash",
            "deviceHash": "device-hash",
            "importManifestHash": "import-manifest-hash",
            "importEvidenceHash": "import-evidence-hash",
            "mcpSurfaceHash": "mcp-surface-hash",
            "uiPreflightEvidenceHash": "ui-preflight-hash",
        }

    @property
    def step_dir(self) -> Path:
        return (
            self.artifact_dir
            / "model-calls"
            / self.spec.family
            / self.spec.step_name
        )

    @property
    def expected_identity(self) -> dict[str, str]:
        return {
            **self.execution_meta,
            "specHash": runner.spec_record(self.spec)["specHash"],
        }

    def write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def write_intent(self, **overrides: object) -> dict[str, object]:
        intent: dict[str, object] = {
            **self.expected_identity,
            "family": self.spec.family,
            "ordinal": self.spec.ordinal,
            "attempt": self.spec.attempt,
            "variant": self.spec.variant,
            "chatId": self.spec.chat_id,
            "activePresetId": 77,
            "exactPrompt": self.spec.prompt,
            "promptSha256": hashlib.sha256(
                self.spec.prompt.encode("utf-8")
            ).hexdigest(),
            "beforeCount": 0,
            "beforeMessageIds": [],
            "beforeMessagesHash": runner.stable_hash([]),
            "nonce": self.spec.nonce,
            "status": "prepared-before-send",
        }
        intent.update(overrides)
        self.write_json(self.step_dir / "intent.private.json", intent)
        self.write_json(
            self.step_dir / "send-start.private.json",
            {
                **self.expected_identity,
                "chatId": self.spec.chat_id,
                "variant": self.spec.variant,
                "attempt": self.spec.attempt,
                "promptSha256": intent["promptSha256"],
                "sendStartedAt": "2026-01-01T00:00:00+00:00",
                "status": "entering-non-idempotent-input-send",
            },
        )
        return intent

    def completed_exchange(self) -> list[dict[str, object]]:
        return [
            {
                "id": 1001,
                "index": 1,
                "role": "user",
                "content": self.spec.prompt,
            },
            {
                "id": 1002,
                "index": 2,
                "role": "assistant",
                "content": "SEMANTIC_OK " + ("substantive-response " * 3),
            },
        ]

    def execute(self) -> dict[str, object]:
        return runner.execute_call(
            self.client,
            self.artifact_dir,
            "",
            "RUN_TEST",
            self.spec,
            1,
            self.execution_meta,
        )

    def test_start_without_intent_finishes_as_interrupted_without_side_effects(self) -> None:
        start_path = self.step_dir / "start.private.json"
        self.write_json(start_path, {"status": "started-before-side-effects"})

        with (
            mock.patch.object(
                runner,
                "set_current_chat",
                side_effect=AssertionError("start-only recovery reached phone setup"),
            ) as set_current_chat,
            mock.patch.object(
                runner,
                "reconcile_attempt_result",
                side_effect=AssertionError("start-only recovery attempted reconciliation"),
            ) as reconcile,
            mock.patch.object(
                runner,
                "tool_call",
                side_effect=AssertionError("start-only recovery called MCP"),
            ) as tool_call,
        ):
            result = self.execute()

        self.assertFalse(result["passed"])
        self.assertTrue(result["interruptedBeforeIntent"])
        self.assertFalse(result["inputSendOk"])
        self.assertIsNone(result["userMessageId"])
        self.assertIsNone(result["assistantMessageId"])
        self.assertEqual(
            runner.load_json(self.step_dir / "result.json"),
            result,
        )
        self.assertFalse((self.step_dir / "intent.private.json").exists())
        set_current_chat.assert_not_called()
        reconcile.assert_not_called()
        tool_call.assert_not_called()

    def test_existing_intent_reconciles_without_resending(self) -> None:
        self.write_intent()
        reconciled = {"reconciled": True, "passed": True}

        with (
            mock.patch.object(
                runner,
                "reconcile_attempt_result",
                return_value=reconciled,
            ) as reconcile,
            mock.patch.object(
                runner,
                "set_current_chat",
                side_effect=AssertionError("intent recovery restarted phone setup"),
            ) as set_current_chat,
            mock.patch.object(
                runner,
                "tool_call",
                side_effect=AssertionError("intent recovery resent the prompt"),
            ) as tool_call,
        ):
            result = self.execute()

        self.assertIs(result, reconciled)
        reconcile.assert_called_once()
        reconcile_args = reconcile.call_args.args
        self.assertEqual(reconcile_args[2], "")
        self.assertEqual(reconcile_args[3], "RUN_TEST")
        self.assertIs(reconcile_args[4], self.spec)
        self.assertEqual(reconcile_args[5], self.execution_meta)
        set_current_chat.assert_not_called()
        tool_call.assert_not_called()

    def test_existing_result_is_returned_without_overwrite(self) -> None:
        immutable_result = {
            **self.expected_identity,
            "passed": True,
            "sentinel": "immutable-result",
        }
        result_path = self.step_dir / "result.json"
        self.write_json(result_path, immutable_result)
        original_bytes = result_path.read_bytes()

        with mock.patch.object(
            runner,
            "durable_json",
            side_effect=AssertionError("existing result.json was rewritten"),
        ) as durable_json:
            result = self.execute()

        self.assertEqual(result, immutable_result)
        self.assertEqual(result_path.read_bytes(), original_bytes)
        durable_json.assert_not_called()

    def test_reconcile_preserves_an_existing_terminal_result(self) -> None:
        self.write_intent()
        result_path = self.step_dir / "result.json"
        terminal_result = {
            **self.expected_identity,
            "family": self.spec.family,
            "ordinal": self.spec.ordinal,
            "variant": self.spec.variant,
            "attempt": self.spec.attempt,
            "chatId": self.spec.chat_id,
            "passed": False,
            "userMessageId": 9001,
            "assistantMessageId": 9002,
            "finishedAt": "2026-01-01T00:00:00+00:00",
            "sentinel": "first-terminal-result",
        }
        self.write_json(result_path, terminal_result)
        original_bytes = result_path.read_bytes()

        with mock.patch.object(
            runner,
            "all_messages",
            return_value=self.completed_exchange(),
        ):
            result = runner.reconcile_attempt_result(
                self.client,
                self.artifact_dir,
                "",
                "RUN_TEST",
                self.spec,
                self.execution_meta,
                {"prompt": self.spec.prompt, "inputSendOk": False},
                grace_seconds=0,
            )

        self.assertEqual(result, terminal_result)
        self.assertEqual(result_path.read_bytes(), original_bytes)
        marker = runner.load_json(self.step_dir / "call-intent-reconciled.json")
        self.assertFalse(marker["passed"])
        self.assertEqual(marker["userMessageId"], 9001)
        self.assertEqual(marker["assistantMessageId"], 9002)

    def test_provisional_result_is_reconciled_without_being_mutated(self) -> None:
        self.write_intent()
        provisional_path = self.step_dir / "provisional-result.json"
        provisional = {
            **self.expected_identity,
            "prompt": self.spec.prompt,
            "inputSendOk": False,
            "passed": False,
            "failures": ["assistant reply had not persisted yet"],
        }
        self.write_json(provisional_path, provisional)
        provisional_bytes = provisional_path.read_bytes()

        with (
            mock.patch.object(
                runner,
                "all_messages",
                return_value=self.completed_exchange(),
            ) as all_messages,
            mock.patch.object(
                runner,
                "tool_call",
                side_effect=AssertionError("reconciliation resent the prompt"),
            ) as tool_call,
        ):
            result = self.execute()

        self.assertTrue(result["reconciled"])
        self.assertTrue(result["passed"])
        self.assertTrue(result["exchangeComplete"])
        self.assertEqual(result["userMessageId"], 1001)
        self.assertEqual(result["assistantMessageId"], 1002)
        self.assertEqual(runner.load_json(self.step_dir / "result.json"), result)
        self.assertEqual(provisional_path.read_bytes(), provisional_bytes)
        self.assertEqual(
            runner.load_json(self.step_dir / "call-intent-reconciled.json")["status"],
            "reconciled",
        )
        all_messages.assert_called_once()
        tool_call.assert_not_called()

    def test_intent_identity_hash_mismatch_is_rejected_before_reconcile(self) -> None:
        self.write_intent(contextHash="different-context-hash")

        with (
            mock.patch.object(
                runner,
                "reconcile_attempt_result",
                side_effect=AssertionError("mismatched intent reached reconciliation"),
            ) as reconcile,
            mock.patch.object(
                runner,
                "tool_call",
                side_effect=AssertionError("mismatched intent called MCP"),
            ) as tool_call,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "unresolved call intent belongs to another execution identity",
            ):
                self.execute()

        mismatch = runner.load_json(
            self.step_dir / "call-intent-identity-mismatch.json"
        )
        self.assertEqual(
            mismatch,
            {
                "contextHash": {
                    "expected": "context-hash",
                    "actual": "different-context-hash",
                }
            },
        )
        self.assertFalse((self.step_dir / "result.json").exists())
        reconcile.assert_not_called()
        tool_call.assert_not_called()

    def test_resume_control_flow_cannot_call_prepare_contexts(self) -> None:
        source = textwrap.dedent(inspect.getsource(runner.main))
        tree = ast.parse(source)
        main = next(
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
        )
        prepare_calls = [
            node
            for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "prepare_contexts"
        ]
        self.assertTrue(prepare_calls, "main() no longer has a prepare_contexts call to audit")

        parent: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(main):
            for child in ast.iter_child_nodes(node):
                parent[child] = node

        unsafe_lines = [
            call.lineno
            for call in prepare_calls
            if not self._branch_is_unreachable_when_resuming(call, parent)
        ]
        self.assertEqual(
            unsafe_lines,
            [],
            "resume can reach prepare_contexts at main() source line(s) "
            f"{unsafe_lines}; load the durable context registry instead",
        )

    @classmethod
    def _branch_is_unreachable_when_resuming(
        cls,
        target: ast.AST,
        parent: dict[ast.AST, ast.AST],
    ) -> bool:
        current = target
        while current in parent:
            ancestor = parent[current]
            if isinstance(ancestor, (ast.If, ast.IfExp)):
                condition = cls._evaluate_with_resume_true(ancestor.test)
                if condition is not None:
                    in_body = cls._contains(ancestor.body, target)
                    in_else = cls._contains(ancestor.orelse, target)
                    if (in_body and not condition) or (in_else and condition):
                        return True
            current = ancestor
        return False

    @staticmethod
    def _contains(branch: object, target: ast.AST) -> bool:
        nodes = branch if isinstance(branch, list) else [branch]
        return any(
            candidate is target
            for node in nodes
            if isinstance(node, ast.AST)
            for candidate in ast.walk(node)
        )

    @classmethod
    def _evaluate_with_resume_true(cls, node: ast.AST) -> bool | None:
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "resume"
            and isinstance(node.value, ast.Name)
            and node.value.id == "args"
        ):
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            value = cls._evaluate_with_resume_true(node.operand)
            return None if value is None else not value
        if isinstance(node, ast.BoolOp):
            values = [cls._evaluate_with_resume_true(value) for value in node.values]
            if isinstance(node.op, ast.And):
                if False in values:
                    return False
                return True if all(value is True for value in values) else None
            if isinstance(node.op, ast.Or):
                if True in values:
                    return True
                return False if all(value is False for value in values) else None
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and len(node.comparators) == 1
        ):
            left = cls._evaluate_with_resume_true(node.left)
            right = cls._evaluate_with_resume_true(node.comparators[0])
            if left is None or right is None:
                return None
            if isinstance(node.ops[0], (ast.Eq, ast.Is)):
                return left == right
            if isinstance(node.ops[0], (ast.NotEq, ast.IsNot)):
                return left != right
        return None


if __name__ == "__main__":
    unittest.main(verbosity=2)
