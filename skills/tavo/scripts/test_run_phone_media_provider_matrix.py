#!/usr/bin/env python3
"""Offline tests for the media/provider matrix runner."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import run_phone_media_provider_matrix as runner  # noqa: E402


class MediaProviderMatrixOfflineTests(unittest.TestCase):
    def load_current_surface(self) -> runner.SurfaceSnapshot:
        return runner.load_surface_snapshot(runner.DEFAULT_SURFACE_JSON)

    def load_current_docs(self) -> dict[str, str]:
        return runner.load_official_docs(runner.DEFAULT_DOCS_ROOT)

    def clone_surface(
        self,
        surface: runner.SurfaceSnapshot,
        *,
        files_status: str | None = None,
        image_generation_status: str | None = None,
        extra_tool_names: tuple[str, ...] = (),
        message_schema_text: str | None = None,
    ) -> runner.SurfaceSnapshot:
        raw = copy.deepcopy(surface.raw)
        capabilities_payload = json.loads(surface.capabilities_text) if surface.capabilities_text else {}
        if files_status is not None:
            capabilities_payload.setdefault("toolGroups", {}).setdefault("files", {})["status"] = files_status
        if image_generation_status is not None:
            capabilities_payload.setdefault("toolGroups", {}).setdefault("imageGeneration", {})["status"] = image_generation_status
        if capabilities_payload:
            text = json.dumps(capabilities_payload, ensure_ascii=False, indent=2)
            raw["resource_reads"]["tavo://capabilities"]["result"]["contents"][0]["text"] = text
        tools = dict(surface.tools)
        tool_names = list(surface.tool_names)
        for name in extra_tool_names:
            tool_names.append(name)
            tools[name] = {"name": name, "inputSchema": {"type": "object", "properties": {}}}
        return runner.SurfaceSnapshot(
            raw=raw,
            server_info=copy.deepcopy(surface.server_info),
            summary=copy.deepcopy(surface.summary),
            tools=tools,
            tool_names=tuple(tool_names),
            tool_groups=copy.deepcopy(capabilities_payload.get("toolGroups", {})),
            resources=copy.deepcopy(surface.resources),
            docs_text=copy.deepcopy(surface.docs_text),
            capabilities_text=json.dumps(capabilities_payload, ensure_ascii=False, indent=2),
            message_schema_text=message_schema_text if message_schema_text is not None else surface.message_schema_text,
        )

    def test_current_surface_blocks_all_media_cases_without_fake_passes(self) -> None:
        surface = self.load_current_surface()
        docs = self.load_current_docs()
        cases = runner.build_cases("RUN-CURRENT")
        outcomes = [runner.plan_case(surface, docs, case) for case in cases]
        self.assertTrue(all(outcome.status == "blocked" for outcome in outcomes))
        self.assertTrue(any("deferred" in (outcome.blocked_reason or "") for outcome in outcomes))
        self.assertTrue(any("attachment" in (outcome.blocked_reason or "") for outcome in outcomes))
        self.assertEqual(docs["stt_docs_found"], "false")

    def test_case_subset_preserves_definition_order_and_rejects_bad_keys(self) -> None:
        cases = runner.build_cases("RUN-SUBSET")
        selected = runner.select_cases(cases, "tts-short-proof,image-send-roundtrip")
        self.assertEqual([case.key for case in selected], ["image-send-roundtrip", "tts-short-proof"])
        with self.assertRaisesRegex(RuntimeError, "Unknown"):
            runner.select_cases(cases, "not-a-case")
        with self.assertRaisesRegex(RuntimeError, "duplicates"):
            runner.select_cases(cases, "tts-short-proof,tts-short-proof")

    def test_secret_redaction_scrubs_nested_secret_like_fields(self) -> None:
        payload = {
            "apiKey": "sk-live-123",
            "authorization": "Bearer abc",
            "nested": {
                "client_secret": "one-two-three",
                "refresh_token": "rt-1",
                "password": "p4ss",
            },
            "model": "tiny",
        }
        redacted = runner.strict_redact(payload)
        self.assertEqual(redacted["apiKey"], "<redacted>")
        self.assertEqual(redacted["authorization"], "<redacted>")
        self.assertEqual(redacted["nested"]["client_secret"], "<redacted>")
        self.assertEqual(redacted["nested"]["refresh_token"], "<redacted>")
        self.assertEqual(redacted["nested"]["password"], "<redacted>")
        self.assertEqual(redacted["model"], "tiny")

    def test_semantic_media_assertions_reject_transport_only_success(self) -> None:
        self.assertEqual(
            runner.semantic_result_assertion("tts", {"ok": True}),
            (False, "TTS call returned no audio or playback evidence"),
        )
        self.assertEqual(
            runner.semantic_result_assertion("stt", {"ok": True, "text": ""}),
            (False, "STT call returned no non-empty transcript"),
        )
        self.assertEqual(
            runner.semantic_result_assertion(
                "image-send",
                {"content": "Codex media attachment proof."},
                required_marker="Codex media attachment proof.",
            ),
            (False, "message readback contains the text marker but no attachment field"),
        )

    def test_semantic_media_assertions_require_concrete_evidence(self) -> None:
        tts_ok, _ = runner.semantic_result_assertion("tts", {"ok": True, "audioUrl": "https://example.invalid/a.wav"})
        stt_ok, _ = runner.semantic_result_assertion("stt", {"ok": True, "transcript": "hello"})
        image_ok, _ = runner.semantic_result_assertion(
            "image-send",
            {
                "content": "Codex media attachment proof.",
                "attachments": [{"name": "tiny.png", "mimeType": "image/png"}],
            },
            required_marker="Codex media attachment proof.",
        )
        self.assertTrue(tts_ok)
        self.assertTrue(stt_ok)
        self.assertTrue(image_ok)

    def test_apply_semantic_assertion_marks_empty_stt_as_failed(self) -> None:
        surface = self.load_current_surface()
        docs = self.load_current_docs()
        case = next(case for case in runner.build_cases("RUN-SEMANTIC") if case.key == "stt-minimal-proof")
        outcome = runner.plan_case(
            self.clone_surface(surface, extra_tool_names=("tavo_stt_transcribe",)),
            docs,
            case,
        )
        runner.apply_semantic_assertion(outcome, {"ok": True, "text": ""})
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.block_kind, "semantic-assertion-failed")
        self.assertFalse(outcome.assertions[0]["passed"])

    def test_image_send_remains_blocked_when_files_are_available_but_message_schema_lacks_attachment_fields(self) -> None:
        surface = self.clone_surface(
            self.load_current_surface(),
            files_status="available",
        )
        docs = self.load_current_docs()
        case = next(case for case in runner.build_cases("RUN-FAULT") if case.key == "image-send-roundtrip")
        outcome = runner.plan_case(surface, docs, case)
        self.assertEqual(outcome.status, "blocked")
        self.assertIn("attachment", outcome.blocked_reason or "")

    def test_image_send_becomes_plannable_when_surface_and_schema_actually_support_attachments(self) -> None:
        surface = self.clone_surface(
            self.load_current_surface(),
            files_status="available",
            message_schema_text=json.dumps(
                {
                    "kind": "message",
                    "required": ["content"],
                    "properties": {
                        "content": {"type": "string"},
                        "attachments": {"type": "array", "items": {"type": "object"}},
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            extra_tool_names=("tavo_file_save", "tavo_file_load"),
        )
        docs = self.load_current_docs()
        case = next(case for case in runner.build_cases("RUN-POSITIVE") if case.key == "image-send-roundtrip")
        outcome = runner.plan_case(surface, docs, case)
        self.assertEqual(outcome.status, "planned")
        self.assertIsNone(outcome.blocked_reason)

    def test_plan_manifest_writer_keeps_case_artifacts_and_root_summary_shape(self) -> None:
        surface = self.load_current_surface()
        docs = self.load_current_docs()
        cases = runner.select_cases(runner.build_cases("RUN-MANIFEST"), "image-provider-config-status,stt-minimal-proof")
        outcomes = [runner.plan_case(surface, docs, case) for case in cases]
        with tempfile.TemporaryDirectory() as temporary:
            artifact_dir = Path(temporary)
            runner.save_support_artifacts(artifact_dir, surface, docs, outcomes)
            root_path = runner.write_root_manifest(
                artifact_dir,
                "RUN-MANIFEST",
                cases,
                outcomes,
                surface,
                docs,
                status="blocked",
                mode="plan",
            )
            manifest = json.loads(root_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["case"], "media-provider-matrix")
        self.assertEqual(manifest["status"], "blocked")
        self.assertIn("surfaceSummary", manifest)
        self.assertEqual(manifest["progress"]["total"], 2)
        self.assertEqual(manifest["progress"]["blocked"], 2)

    def test_live_execute_short_circuits_without_supported_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact_dir = Path(temporary)
            args = argparse.Namespace(
                artifact_dir=str(artifact_dir),
                surface_json=str(runner.DEFAULT_SURFACE_JSON),
                docs_root=str(runner.DEFAULT_DOCS_ROOT),
                endpoint_json=str(runner.DEFAULT_ENDPOINT_JSON),
                url="",
                auth="",
                device="offline-device",
                per_call_timeout=30,
                cases="image-provider-config-status",
                print_plan=False,
            )
            with mock.patch.object(
                runner,
                "capture_live_surface",
                side_effect=AssertionError("live surface capture should not be called in this offline test"),
            ):
                self.assertEqual(runner.run_offline_plan(args, live=False), 0)


if __name__ == "__main__":
    unittest.main()
