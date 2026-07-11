#!/usr/bin/env python3
"""Offline contract tests for the strict Tavo MCP surface gate."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("dump_mcp_surface.py")
SPEC = importlib.util.spec_from_file_location("dump_mcp_surface", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def complete_result() -> dict:
    calls = {method: {"result": {}} for method, _ in MODULE.READ_METHODS}
    calls["initialize"] = {
        "result": {
            "protocolVersion": MODULE.REQUESTED_PROTOCOL_VERSION,
            "serverInfo": {"name": "tavo", "version": "0.92.0"},
        }
    }
    return {
        "requested_protocol_version": MODULE.REQUESTED_PROTOCOL_VERSION,
        "calls": calls,
        "resource_reads": {"tavo://docs/plugins": {"result": {"contents": []}}},
        "status_tool_call": {"result": {"content": []}},
    }


class StrictGateTests(unittest.TestCase):
    def test_complete_gate_has_no_failures(self) -> None:
        result = complete_result()
        self.assertEqual(MODULE.strict_failures(result), [])
        summary = MODULE.summarize_surface(result)
        self.assertEqual(summary["requestedProtocolVersion"], "2025-06-18")
        self.assertEqual(summary["negotiatedProtocolVersion"], "2025-06-18")
        self.assertTrue(summary["statusToolCallOk"])

    def test_prompts_list_is_required(self) -> None:
        result = complete_result()
        result["calls"]["prompts/list"] = {"error": "unavailable"}
        self.assertIn("call:prompts/list", MODULE.strict_failures(result))

    def test_resource_failure_is_required(self) -> None:
        result = complete_result()
        result["resource_reads"]["tavo://docs/plugins"] = {"error": "missing"}
        self.assertIn("resource:tavo://docs/plugins", MODULE.strict_failures(result))

    def test_status_tool_call_is_required(self) -> None:
        result = complete_result()
        result["status_tool_call"] = {"error": "method failed"}
        self.assertIn("tool:tavo_status", MODULE.strict_failures(result))


if __name__ == "__main__":
    unittest.main()
