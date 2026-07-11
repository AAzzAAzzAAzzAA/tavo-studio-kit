#!/usr/bin/env python3
"""Capability-driven real-phone media/provider matrix for Tavo.

The runner is intentionally fail-closed:

* It reads the current MCP surface before every live attempt.
* It consults the official snapshot docs for image, voice, TTS, STT, and
  settings coverage.
* If the current surface does not expose the required media/provider capability
  or the message/file schema is insufficient, the case is recorded as
  ``surface-blocked`` instead of being faked as a pass.
* Live writes use dry-run -> actual -> readback only when the surface exposes a
  real tool path. Provider secrets are always redacted in artifacts.
* Default retention is effect-first: chats, media, and disposable evidence stay
  in place unless a case is explicitly a restore/cleanup case.

The current 0.92.0 surface snapshot shipped with this skill does not expose the
media/provider tools needed for the requested matrix, so the default local run
should report structured surface-blocked cases rather than pretend success.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import base64
import io
import math
import re
import subprocess
import sys
import traceback
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT_JSON = Path("/tmp/tavo_mcp_endpoint.json")
DEFAULT_SURFACE_JSON = ROOT / "assets" / "schemas" / "mcp-surface-0.92.0-20260716.json"
DEFAULT_DOCS_ROOT = ROOT / "assets" / "official-docs" / "text-20260716"
SCRIPT_PATH = Path(__file__).resolve()
sys.path.insert(0, str(ROOT / "scripts"))

from run_phone_import_kpi import response_payload, response_items  # noqa: E402
from run_phone_kpi_batch import TavoMcp, capture_phone, load_endpoint, ok_response, redact  # noqa: E402


SECRET_KEY_RE = re.compile(
    r"(authorization|auth|token|bearer|api[_-]?key|apikey|secret|client[_-]?secret|"
    r"access[_-]?token|refresh[_-]?token|password|private[_-]?key)$",
    re.IGNORECASE,
)
ATTACHMENT_HINT_RE = re.compile(r"(attachment|attachments|file|files|image|dataurl)", re.IGNORECASE)
IMAGE_TOOL_RE = re.compile(r"(image|generation|imagine|multimodal)", re.IGNORECASE)
VOICE_TOOL_RE = re.compile(r"(voice|tts|speech)", re.IGNORECASE)
STT_TOOL_RE = re.compile(r"(stt|transcrib|speech[_-]?to[_-]?text|recogniz)", re.IGNORECASE)


@dataclass(frozen=True)
class SurfaceSnapshot:
    raw: dict[str, Any]
    server_info: dict[str, Any]
    summary: dict[str, Any]
    tools: dict[str, dict[str, Any]]
    tool_names: tuple[str, ...]
    tool_groups: dict[str, dict[str, Any]]
    resources: dict[str, str]
    docs_text: dict[str, str]
    capabilities_text: str
    message_schema_text: str

    def group_status(self, name: str) -> str:
        group = self.tool_groups.get(name) or {}
        return str(group.get("status") or "missing")

    def has_tool(self, predicate: re.Pattern[str]) -> bool:
        return any(predicate.search(name) for name in self.tool_names)


@dataclass(frozen=True)
class CaseSpec:
    key: str
    family: str
    doc_keys: tuple[str, ...]
    requires_groups: tuple[str, ...] = ()
    tool_patterns: tuple[re.Pattern[str], ...] = ()
    requires_attachment_schema: bool = False
    retention: str = "leave-in-place"
    notes: str = ""


@dataclass
class CaseOutcome:
    key: str
    family: str
    status: str
    block_kind: str | None
    blocked_reason: str | None
    docs: dict[str, str]
    surface: dict[str, Any]
    steps: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    readback: dict[str, Any] | None = None
    restoration_attempted: bool = False
    restoration_passed: bool = False
    assertions: list[dict[str, Any]] = field(default_factory=list)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def strict_redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SECRET_KEY_RE.search(key_text) or key_text.lower().endswith("_key"):
                out[key_text] = "<redacted>"
            else:
                out[key_text] = strict_redact(item)
        return out
    if isinstance(value, list):
        return [strict_redact(item) for item in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return "Bearer <redacted>"
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(strict_redact(value), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(strict_redact(row), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def maybe_json_text(response: dict[str, Any]) -> Any:
    return response_payload(response)


def call_tool(
    client: TavoMcp,
    artifact_dir: Path,
    tool: str,
    arguments: dict[str, Any],
    *,
    timeout: int,
    step_name: str,
) -> dict[str, Any]:
    output = artifact_dir / f"{safe_name(step_name)}.json"
    try:
        response = client.tool(tool, arguments, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - preserve diagnostic detail
        failure = {
            "tool": tool,
            "arguments": arguments,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
        }
        atomic_json(output.with_name(output.stem + "-exception.json"), failure)
        raise
    atomic_json(output, response)
    return response


def load_surface_snapshot(path: Path) -> SurfaceSnapshot:
    data = load_json(path)
    tools: dict[str, dict[str, Any]] = {}
    tool_names: list[str] = []
    tool_groups: dict[str, dict[str, Any]] = {}
    resources: dict[str, str] = {}
    capabilities_text = ""
    message_schema_text = ""

    if isinstance(data.get("calls"), dict):
        tools_payload = (((data.get("calls") or {}).get("tools/list") or {}).get("result") or {}).get("tools") or []
        for tool in tools_payload:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "")
            if name:
                tools[name] = tool
                tool_names.append(name)

    resource_reads = data.get("resource_reads") or {}
    for uri, payload in resource_reads.items():
        text = ""
        if isinstance(payload, dict):
            result = payload.get("result") or {}
            contents = result.get("contents") if isinstance(result, dict) else None
            if isinstance(contents, list) and contents:
                first = contents[0] if isinstance(contents[0], dict) else {}
                text = str(first.get("text") or "")
        resources[str(uri)] = text

    capabilities_text = resources.get("tavo://capabilities", "")
    message_schema_text = resources.get("tavo://schemas/message", "")
    try:
        capabilities = json.loads(capabilities_text) if capabilities_text.strip().startswith("{") else {}
    except Exception:
        capabilities = {}
    if isinstance(capabilities, dict):
        tool_groups = {str(key): value for key, value in (capabilities.get("toolGroups") or {}).items() if isinstance(value, dict)}

    return SurfaceSnapshot(
        raw=data,
        server_info=(data.get("summary") or {}).get("serverInfo") or {},
        summary=data.get("summary") or {},
        tools=tools,
        tool_names=tuple(tool_names),
        tool_groups=tool_groups,
        resources=resources,
        docs_text={},
        capabilities_text=capabilities_text,
        message_schema_text=message_schema_text,
    )


def load_official_docs(root: Path) -> dict[str, str]:
    mapping = {
        "image_api_settings": root / "cn_guides_voice-connection_image-api-settings.txt",
        "image_setting": root / "cn_guides_voice-connection_image-setting.txt",
        "image_sent": root / "cn_guides_others_image-sent.txt",
        "voice_api_settings": root / "cn_guides_voice-connection_voice-api-settings.txt",
        "voice_setting": root / "cn_guides_voice-connection_voice-setting.txt",
        "voice_binding": root / "cn_guides_voice-connection_voice-binding.txt",
        "tts_guide": root / "cn_guides_voice-connection_tts-guide.txt",
        "google_tts": root / "cn_guides_voice-connection_tts-guide_google-tts.txt",
        "iflyrec_tts": root / "cn_guides_voice-connection_tts-guide_iflyrec-tts.txt",
        "api_setting": root / "cn_guides_api-setting.txt",
        "api_select_model": root / "cn_guides_api-setting_select-model.txt",
        "app_settings": root / "cn_guides_others.txt",
    }
    docs: dict[str, str] = {}
    for key, path in mapping.items():
        docs[key] = path.read_text(encoding="utf-8") if path.exists() else ""
    docs["stt_docs_found"] = "true" if any(
        re.search(r"(\bstt\b|speech-to-text|语音转写|语音识别|转写|听写)", text, re.IGNORECASE)
        for text in docs.values()
        if isinstance(text, str)
    ) else "false"
    return docs


def docs_for_case(case: CaseSpec, docs: dict[str, str]) -> dict[str, str]:
    return {key: docs.get(key, "") for key in case.doc_keys}


def any_tool_matches(surface: SurfaceSnapshot, *patterns: re.Pattern[str]) -> bool:
    return any(surface.has_tool(pattern) for pattern in patterns)


def message_attachment_supported(surface: SurfaceSnapshot) -> bool:
    return bool(ATTACHMENT_HINT_RE.search(surface.message_schema_text))


def image_case_supported(surface: SurfaceSnapshot, case: CaseSpec) -> tuple[bool, str]:
    if case.requires_attachment_schema and not message_attachment_supported(surface):
        return False, "surface-blocked: current message schema does not expose attachment/file/image fields"
    image_groups = {surface.group_status(name) for name in case.requires_groups}
    if any(status not in {"available"} for status in image_groups):
        return False, f"surface-blocked: capability groups {sorted(case.requires_groups)} are {sorted(image_groups)}"
    if case.tool_patterns and not any_tool_matches(surface, *case.tool_patterns):
        return False, "surface-blocked: no matching media tool name is exposed by the current surface"
    return True, ""


def voice_case_supported(surface: SurfaceSnapshot, case: CaseSpec) -> tuple[bool, str]:
    if case.requires_groups:
        statuses = {name: surface.group_status(name) for name in case.requires_groups}
        if any(status not in {"available"} for status in statuses.values()):
            return False, f"surface-blocked: capability groups not available {statuses}"
    if case.tool_patterns and not any_tool_matches(surface, *case.tool_patterns):
        return False, "surface-blocked: current surface exposes no matching voice/TTS/STT tool names"
    return True, ""


def resolve_tool(surface: SurfaceSnapshot, *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate in surface.tools:
            return candidate
    lowered = {name.lower(): name for name in surface.tool_names}
    for candidate in candidates:
        candidate_lower = candidate.lower()
        if candidate_lower in lowered:
            return lowered[candidate_lower]
        for name in surface.tool_names:
            if candidate_lower in name.lower():
                return name
    return None


def tool_schema(surface: SurfaceSnapshot, tool_name: str) -> dict[str, Any]:
    tool = surface.tools.get(tool_name) or {}
    schema = tool.get("inputSchema")
    return schema if isinstance(schema, dict) else {}


def build_arguments(
    surface: SurfaceSnapshot,
    tool_name: str,
    canonical: dict[str, Any],
    *,
    dry_run: bool | None = None,
    expected_revision: str | None = None,
    client_request_id: str | None = None,
) -> dict[str, Any]:
    props = (tool_schema(surface, tool_name).get("properties") or {})
    arguments: dict[str, Any] = {}
    for key, schema in props.items():
        lower = str(key).lower()
        if key in canonical:
            arguments[key] = canonical[key]
            continue
        if lower == "dryrun" and dry_run is not None:
            arguments[key] = dry_run
            continue
        if lower == "expectedrevision" and expected_revision is not None:
            arguments[key] = expected_revision
            continue
        if lower == "clientrequestid" and client_request_id is not None:
            arguments[key] = client_request_id
            continue
        if lower in {"provider", "platform", "service"} and "provider" in canonical:
            arguments[key] = canonical["provider"]
            continue
        if "model" in lower and "model" in canonical:
            arguments[key] = canonical["model"]
            continue
        if "voice" in lower and "voiceId" in canonical:
            arguments[key] = canonical["voiceId"]
            continue
        if "api" in lower and "apiKey" in canonical:
            arguments[key] = canonical["apiKey"]
            continue
        if lower in {"text", "prompt"} and "text" in canonical:
            arguments[key] = canonical["text"]
            continue
        if lower in {"message", "chat", "character", "binding", "config", "providerconfig"}:
            for candidate_key in (key, lower):
                if candidate_key in canonical:
                    arguments[key] = canonical[candidate_key]
                    break
            else:
                if key in {"message", "chat", "character"} and key in canonical:
                    arguments[key] = canonical[key]
            continue
        if any(fragment in lower for fragment in ("audio", "input", "sample")) and "audioDataUrl" in canonical:
            arguments[key] = canonical["audioDataUrl"]
            continue
        if lower in {"id", "chatid", "characterid"}:
            if key in canonical:
                arguments[key] = canonical[key]
            elif lower == "chatid" and "chatId" in canonical:
                arguments[key] = canonical["chatId"]
            elif lower == "characterid" and "characterId" in canonical:
                arguments[key] = canonical["characterId"]
            elif lower == "id" and "id" in canonical:
                arguments[key] = canonical["id"]
            continue
        if isinstance(schema, dict) and schema.get("type") == "boolean" and key in canonical:
            arguments[key] = canonical[key]
    return arguments


def response_object_id(response: dict[str, Any]) -> int | str | None:
    parsed = response_payload(response)
    if not isinstance(parsed, dict):
        return None
    for key in ("id", "chatId", "characterId", "lorebookId", "presetId", "regexId", "pluginId"):
        value = parsed.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.strip():
            return value
    return None


def semantic_text(value: Any) -> str:
    """Return a stable searchable representation for semantic assertions."""

    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def has_mapping_key(value: Any, *wanted: str) -> bool:
    targets = {item.lower() for item in wanted}
    if isinstance(value, dict):
        if any(str(key).lower() in targets for key in value):
            return True
        return any(has_mapping_key(item, *wanted) for item in value.values())
    if isinstance(value, list):
        return any(has_mapping_key(item, *wanted) for item in value)
    return False


def semantic_result_assertion(
    family: str,
    payload: Any,
    *,
    required_marker: str = "",
) -> tuple[bool, str]:
    """Require observable result semantics instead of merely a non-throwing call."""

    if isinstance(payload, dict):
        if payload.get("error") not in (None, "", False):
            return False, "result contains an error"
        if payload.get("ok") is False or payload.get("success") is False:
            return False, "result explicitly reports failure"

    text = semantic_text(payload)
    if required_marker:
        if required_marker not in text:
            return False, f"readback does not contain required marker {required_marker!r}"
        if family == "image-send":
            lowered = text.lower()
            if not has_mapping_key(payload, "attachment", "attachments"):
                return False, "message readback contains the text marker but no attachment field"
            if not any(marker in lowered for marker in ("tiny.png", "image/png", "data:image/")):
                return False, "message readback contains no concrete image attachment evidence"
        return True, "required marker is present in readback"

    if family == "tts":
        if payload is True:
            return True, "TTS returned boolean true"
        if isinstance(payload, dict):
            evidence_keys = (
                "audio",
                "audioDataUrl",
                "audioUrl",
                "file",
                "path",
                "played",
                "queued",
                "durationMs",
            )
            if any(payload.get(key) not in (None, "", False, [], {}) for key in evidence_keys):
                return True, "TTS returned concrete audio or playback evidence"
        return False, "TTS call returned no audio or playback evidence"

    if family == "stt":
        if isinstance(payload, str) and payload.strip():
            return True, "STT returned non-empty transcript text"
        if isinstance(payload, dict):
            for key in ("text", "transcript", "transcription", "recognizedText"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return True, f"STT returned non-empty {key}"
        return False, "STT call returned no non-empty transcript"

    return False, f"no semantic assertion is defined for {family}"


def apply_semantic_assertion(
    outcome: CaseOutcome,
    payload: Any,
    *,
    required_marker: str = "",
) -> CaseOutcome:
    passed, detail = semantic_result_assertion(
        outcome.family,
        payload,
        required_marker=required_marker,
    )
    outcome.assertions.append(
        {
            "name": "semantic-result",
            "passed": passed,
            "detail": detail,
        }
    )
    outcome.status = "passed" if passed else "failed"
    outcome.block_kind = None if passed else "semantic-assertion-failed"
    outcome.blocked_reason = None if passed else detail
    return outcome


def tiny_png_data_url() -> str:
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2s3n0AAAAASUVORK5CYII="
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def tiny_wav_data_url() -> str:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        frames = bytearray()
        for index in range(1600):
            sample = int(math.sin(index / 16.0) * 1200)
            frames.extend(sample.to_bytes(2, "little", signed=True))
        wav_file.writeframes(bytes(frames))
    return "data:audio/wav;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def maybe_capture_phone(device: str, artifact_dir: Path, name: str) -> None:
    if not device:
        return
    capture_phone(device, artifact_dir, name)


def execute_message_attachment_case(
    client: TavoMcp,
    surface: SurfaceSnapshot,
    artifact_dir: Path,
    case: CaseSpec,
    *,
    run_id: str,
    device: str,
    timeout: int,
) -> CaseOutcome:
    write_tool = resolve_tool(surface, "tavo_message_append")
    read_tool = resolve_tool(surface, "tavo_message_get", "tavo_message_find", "tavo_message_count")
    current_chat_tool = resolve_tool(surface, "tavo_current_chat_get", "tavo_current_chat_set")
    if not write_tool or not read_tool or not current_chat_tool:
        return plan_case(surface, load_official_docs(DEFAULT_DOCS_ROOT), case)
    canonical_message = {
        "chatId": 1,
        "message": {
            "role": "user",
            "content": "Codex media attachment proof.",
            "attachments": [
                {
                    "type": "image",
                    "name": "tiny.png",
                    "mimeType": "image/png",
                    "dataUrl": tiny_png_data_url(),
                }
            ],
        },
        "clientRequestId": f"{run_id}-{case.key}-append",
    }
    before = call_tool(client, artifact_dir / case.key, "tavo_current_chat_get", {}, timeout=timeout, step_name=f"{case.key}-current-chat-before")
    current_chat_id = response_object_id(before) or canonical_message["chatId"]
    canonical_message["chatId"] = int(current_chat_id) if str(current_chat_id).isdigit() else canonical_message["chatId"]

    dry_arguments = build_arguments(surface, write_tool, canonical_message, dry_run=True, client_request_id=f"{run_id}-{case.key}-dry")
    if "dryRun" in (tool_schema(surface, write_tool).get("properties") or {}):
        call_tool(client, artifact_dir / case.key, write_tool, dry_arguments, timeout=timeout, step_name=f"{case.key}-dry-run")
    actual_arguments = build_arguments(surface, write_tool, canonical_message, dry_run=False, client_request_id=f"{run_id}-{case.key}-actual")
    actual = call_tool(client, artifact_dir / case.key, write_tool, actual_arguments, timeout=timeout, step_name=f"{case.key}-actual")
    maybe_capture_phone(device, artifact_dir / case.key, "screen-after-message")
    readback_id = response_object_id(actual)
    readback: dict[str, Any] | None = None
    if read_tool == "tavo_message_get" and readback_id is not None:
        readback = call_tool(
            client,
            artifact_dir / case.key,
            read_tool,
            {"chatId": canonical_message["chatId"], "id": int(readback_id)},
            timeout=timeout,
            step_name=f"{case.key}-readback",
        )
    elif read_tool == "tavo_message_find":
        readback = call_tool(
            client,
            artifact_dir / case.key,
            read_tool,
            {"chatId": canonical_message["chatId"], "filter": "Codex media attachment proof"},
            timeout=timeout,
            step_name=f"{case.key}-readback",
        )
    else:
        readback = actual
    outcome = plan_case(surface, load_official_docs(DEFAULT_DOCS_ROOT), case)
    semantic_payload = response_payload(readback) if isinstance(readback, dict) else {}
    outcome.readback = strict_redact(semantic_payload)
    apply_semantic_assertion(
        outcome,
        semantic_payload,
        required_marker="Codex media attachment proof.",
    )
    outcome.artifacts = [
        f"cases/{case.key}/{case.key}-dry-run.json",
        f"cases/{case.key}/{case.key}-actual.json",
    ]
    if readback is not None:
        outcome.artifacts.append(f"cases/{case.key}/{case.key}-readback.json")
    return outcome


def execute_asset_case(
    client: TavoMcp,
    surface: SurfaceSnapshot,
    docs: dict[str, str],
    artifact_dir: Path,
    case: CaseSpec,
    *,
    run_id: str,
    timeout: int,
) -> CaseOutcome:
    write_tool = resolve_tool(
        surface,
        *(f"tavo_{case.family.replace('-', '_')}_create", f"tavo_{case.family.replace('-', '_')}_update", f"tavo_{case.family.replace('-', '_')}_import"),
    )
    read_tool = resolve_tool(
        surface,
        *(f"tavo_{case.family.replace('-', '_')}_get", f"tavo_{case.family.replace('-', '_')}_search", f"tavo_{case.family.replace('-', '_')}_status"),
    )
    if not write_tool:
        return plan_case(surface, docs, case)
    if case.family == "image-provider":
        canonical = {
            "provider": "codex-harmless-provider",
            "model": "codex-harmless-model",
            "apiKey": "<redacted>",
            "name": f"Codex Media Image Provider {run_id}",
        }
    elif case.family == "voice-provider":
        canonical = {
            "provider": "codex-harmless-provider",
            "model": "codex-harmless-voice-model",
            "apiKey": "<redacted>",
            "name": f"Codex Media Voice Provider {run_id}",
        }
    elif case.family == "voice-binding":
        canonical = {
            "characterId": 1,
            "voiceId": "codex-harmless-voice-id",
            "name": f"Codex Voice Binding {run_id}",
        }
    else:
        canonical = {"name": f"Codex Media Asset {run_id}"}
    dry_arguments = build_arguments(
        surface,
        write_tool,
        canonical,
        dry_run=True,
        client_request_id=f"{run_id}-{case.key}-dry",
    )
    if "dryRun" in (tool_schema(surface, write_tool).get("properties") or {}):
        call_tool(client, artifact_dir / case.key, write_tool, dry_arguments, timeout=timeout, step_name=f"{case.key}-dry-run")
    actual_arguments = build_arguments(
        surface,
        write_tool,
        canonical,
        dry_run=False,
        client_request_id=f"{run_id}-{case.key}-actual",
    )
    actual = call_tool(client, artifact_dir / case.key, write_tool, actual_arguments, timeout=timeout, step_name=f"{case.key}-actual")
    readback: dict[str, Any] | None = None
    readback_id = response_object_id(actual)
    if read_tool == "tavo_status":
        readback = call_tool(client, artifact_dir / case.key, read_tool, {}, timeout=timeout, step_name=f"{case.key}-readback")
    elif read_tool and readback_id is not None:
        readback = call_tool(
            client,
            artifact_dir / case.key,
            read_tool,
            {"id": int(readback_id) if str(readback_id).isdigit() else readback_id},
            timeout=timeout,
            step_name=f"{case.key}-readback",
        )
    else:
        readback = actual
    outcome = plan_case(surface, docs, case)
    semantic_payload = response_payload(readback) if isinstance(readback, dict) else {}
    outcome.readback = strict_redact(semantic_payload)
    apply_semantic_assertion(outcome, semantic_payload, required_marker=run_id)
    outcome.artifacts = [
        f"cases/{case.key}/{case.key}-dry-run.json",
        f"cases/{case.key}/{case.key}-actual.json",
    ]
    if readback is not None:
        outcome.artifacts.append(f"cases/{case.key}/{case.key}-readback.json")
    return outcome


def execute_sample_case(
    client: TavoMcp,
    surface: SurfaceSnapshot,
    docs: dict[str, str],
    artifact_dir: Path,
    case: CaseSpec,
    *,
    run_id: str,
    timeout: int,
) -> CaseOutcome:
    tool = resolve_tool(surface, *(tuple(surface.tools) if surface.tools else ()))
    if case.family == "tts":
        tool = resolve_tool(surface, "tavo_tts_generate", "tavo_voice_tts_generate", "tavo_tts_speak", "tavo_voice_tts_play")
        canonical = {"text": "hi", "voiceId": "codex-harmless-voice-id", "model": "codex-harmless-voice-model"}
    else:
        tool = resolve_tool(surface, "tavo_stt_transcribe", "tavo_voice_stt_transcribe")
        canonical = {"audioDataUrl": tiny_wav_data_url(), "language": "en"}
    if not tool:
        return plan_case(surface, docs, case)
    dry_supported = "dryRun" in (tool_schema(surface, tool).get("properties") or {})
    if dry_supported:
        call_tool(
            client,
            artifact_dir / case.key,
            tool,
            build_arguments(surface, tool, canonical, dry_run=True, client_request_id=f"{run_id}-{case.key}-dry"),
            timeout=timeout,
            step_name=f"{case.key}-dry-run",
        )
    actual = call_tool(
        client,
        artifact_dir / case.key,
        tool,
        build_arguments(surface, tool, canonical, dry_run=False, client_request_id=f"{run_id}-{case.key}-actual"),
        timeout=timeout,
        step_name=f"{case.key}-actual",
    )
    outcome = plan_case(surface, docs, case)
    semantic_payload = response_payload(actual) if isinstance(actual, dict) else actual
    outcome.readback = strict_redact(semantic_payload)
    apply_semantic_assertion(outcome, semantic_payload)
    outcome.artifacts = [f"cases/{case.key}/{case.key}-actual.json"]
    return outcome


def build_cases(run_id: str) -> list[CaseSpec]:
    return [
        CaseSpec(
            key="image-provider-config-status",
            family="image-provider",
            doc_keys=("image_api_settings", "image_setting", "image_sent"),
            requires_groups=("generation", "imageGeneration"),
            tool_patterns=(IMAGE_TOOL_RE,),
            notes="Read image provider status/config, then attempt a harmless image-generation roundtrip only if the surface exposes it.",
        ),
        CaseSpec(
            key="image-send-roundtrip",
            family="image-send",
            doc_keys=("image_sent",),
            requires_groups=("files",),
            tool_patterns=(re.compile(r"message", re.IGNORECASE),),
            requires_attachment_schema=True,
            notes="Send a tiny local image, read back the chat/message attachment state, and capture screenshot evidence.",
        ),
        CaseSpec(
            key="voice-provider-config-status",
            family="voice-provider",
            doc_keys=("voice_api_settings", "voice_setting", "voice_binding"),
            tool_patterns=(VOICE_TOOL_RE,),
            notes="Read voice provider status/config with secrets redacted and only perform writes if the surface exposes a real voice provider path.",
        ),
        CaseSpec(
            key="voice-binding-roundtrip",
            family="voice-binding",
            doc_keys=("voice_binding",),
            tool_patterns=(re.compile(r"voice", re.IGNORECASE), re.compile(r"bind", re.IGNORECASE)),
            notes="Create/readback/export/import a character voice binding on disposable evidence only if the surface exposes the needed tools.",
        ),
        CaseSpec(
            key="tts-short-proof",
            family="tts",
            doc_keys=("tts_guide", "google_tts", "iflyrec_tts"),
            tool_patterns=(re.compile(r"tts", re.IGNORECASE),),
            notes="Generate a very short TTS sample and preserve visible playback evidence only when a real TTS tool exists.",
        ),
        CaseSpec(
            key="stt-minimal-proof",
            family="stt",
            doc_keys=("voice_api_settings", "voice_setting"),
            tool_patterns=(STT_TOOL_RE,),
            notes="Check whether STT is actually available and, if so, submit the smallest harmless sample that the surface can support.",
        ),
    ]


def select_cases(cases: list[CaseSpec], subset: str | None) -> list[CaseSpec]:
    if not subset:
        return cases
    requested = [item.strip() for item in subset.split(",") if item.strip()]
    if len(set(requested)) != len(requested):
        raise RuntimeError("Case subset contains duplicates.")
    by_key = {case.key: case for case in cases}
    unknown = [item for item in requested if item not in by_key]
    if unknown:
        raise RuntimeError(f"Unknown case keys: {', '.join(unknown)}")
    selected = [case for case in cases if case.key in requested]
    if not selected:
        raise RuntimeError("Case subset resolved to no cases.")
    return selected


def plan_case(surface: SurfaceSnapshot, docs: dict[str, str], case: CaseSpec) -> CaseOutcome:
    case_docs = docs_for_case(case, docs)
    if case.family == "image-provider":
        supported, reason = image_case_supported(surface, case)
    elif case.family == "image-send":
        supported, reason = image_case_supported(surface, case)
    elif case.family in {"voice-provider", "voice-binding", "tts", "stt"}:
        supported, reason = voice_case_supported(surface, case)
    else:
        supported, reason = False, "surface-blocked: unknown case family"

    surface_view = {
        "toolCount": len(surface.tools),
        "serverInfo": surface.server_info,
        "summary": surface.summary,
        "capabilityGroups": {
            name: {"status": surface.group_status(name), "tools": group.get("tools", [])}
            for name, group in surface.tool_groups.items()
        },
        "messageSchemaSupportsAttachments": message_attachment_supported(surface),
    }

    if not supported:
        return CaseOutcome(
            key=case.key,
            family=case.family,
            status="blocked",
            block_kind="surface-blocked",
            blocked_reason=reason,
            docs=case_docs,
            surface=surface_view,
            steps=["inspect-surface", "inspect-official-docs", "record-surface-blocked"],
            artifacts=[],
        )

    return CaseOutcome(
        key=case.key,
        family=case.family,
        status="planned",
        block_kind=None,
        blocked_reason=None,
        docs=case_docs,
        surface=surface_view,
        steps=["dry-run", "actual", "readback"],
    )


def summarize_plan(outcomes: list[CaseOutcome]) -> dict[str, int]:
    return {
        "total": len(outcomes),
        "blocked": sum(1 for outcome in outcomes if outcome.status == "blocked"),
        "planned": sum(1 for outcome in outcomes if outcome.status == "planned"),
        "passed": sum(1 for outcome in outcomes if outcome.status == "passed"),
        "failed": sum(1 for outcome in outcomes if outcome.status == "failed"),
    }


def write_case_manifest(case_dir: Path, outcome: CaseOutcome) -> None:
    manifest = {
        "schemaVersion": "1.0.0",
        "case": outcome.key,
        "status": outcome.status,
        "startedAt": now_utc(),
        "evidenceLevel": "mcp-runtime",
        "countsTowardKpi": False,
        "artifacts": outcome.artifacts,
        "progress": {
            "blocked": 1 if outcome.status == "blocked" else 0,
            "planned": 1 if outcome.status == "planned" else 0,
            "passed": 1 if outcome.status == "passed" else 0,
            "failed": 1 if outcome.status == "failed" else 0,
        },
        "retention": outcome.block_kind or "leave-in-place",
        "notes": outcome.blocked_reason or "",
        "docs": sorted(outcome.docs.keys()),
        "surface": {
            "toolCount": outcome.surface.get("toolCount", 0),
            "messageSchemaSupportsAttachments": outcome.surface.get("messageSchemaSupportsAttachments", False),
        },
        "assertions": outcome.assertions,
    }
    if outcome.blocked_reason:
        manifest["blockedReason"] = outcome.blocked_reason
    if outcome.readback is not None:
        manifest["readback"] = outcome.readback
    atomic_json(case_dir / "run-manifest.json", manifest)


def write_root_manifest(
    artifact_dir: Path,
    run_id: str,
    selected_cases: list[CaseSpec],
    outcomes: list[CaseOutcome],
    surface: SurfaceSnapshot,
    docs: dict[str, str],
    *,
    status: str,
    mode: str,
) -> Path:
    manifest = {
        "schemaVersion": "1.0.0",
        "case": "media-provider-matrix",
        "status": status,
        "startedAt": now_utc(),
        "finishedAt": now_utc(),
        "runId": run_id,
        "mode": mode,
        "device": "",
        "appVersion": str(surface.server_info.get("version") or ""),
        "countsTowardKpi": False,
        "evidenceLevel": "mcp-runtime",
        "artifacts": [
            "surface.json",
            "official-docs.json",
            "plan.json",
            *[f"cases/{case.key}/run-manifest.json" for case in selected_cases],
        ],
        "progress": summarize_plan(outcomes),
        "selectedCases": [case.key for case in selected_cases],
        "surfaceSummary": surface.summary,
        "capabilityGroups": {
            name: {"status": surface.group_status(name), "tools": group.get("tools", [])}
            for name, group in surface.tool_groups.items()
        },
        "docsCoverage": {
            "consulted": [key for key, value in docs.items() if key != "stt_docs_found" and value],
            "sttDocsFound": docs.get("stt_docs_found") == "true",
        },
        "notes": "Requested media/provider capability is surface-blocked on the current runtime surface unless a future surface exposes the needed tools.",
        "cases": [
            {
                "key": outcome.key,
                "family": outcome.family,
                "status": outcome.status,
                "blockKind": outcome.block_kind,
                "blockedReason": outcome.blocked_reason,
                "assertions": outcome.assertions,
            }
            for outcome in outcomes
        ],
    }
    path = artifact_dir / "run-manifest.json"
    atomic_json(path, manifest)
    return path


def save_support_artifacts(artifact_dir: Path, surface: SurfaceSnapshot, docs: dict[str, str], outcomes: list[CaseOutcome]) -> None:
    atomic_json(artifact_dir / "surface.json", surface.raw)
    atomic_json(artifact_dir / "official-docs.json", strict_redact(docs))
    atomic_json(
        artifact_dir / "plan.json",
        {
            "planHash": stable_hash([outcome.key + ":" + outcome.status for outcome in outcomes]),
            "cases": [
                {
                    "key": outcome.key,
                    "family": outcome.family,
                    "status": outcome.status,
                    "blockKind": outcome.block_kind,
                    "blockedReason": outcome.blocked_reason,
                    "docs": sorted(outcome.docs.keys()),
                    "assertions": outcome.assertions,
                }
                for outcome in outcomes
            ],
        },
    )


def current_surface_fallback() -> SurfaceSnapshot:
    return load_surface_snapshot(DEFAULT_SURFACE_JSON)


def capture_live_surface(args: argparse.Namespace, artifact_dir: Path) -> SurfaceSnapshot:
    endpoint = load_endpoint(args.endpoint_json)
    url = args.url or endpoint.get("url", "")
    auth = args.auth or endpoint.get("auth", "")
    if not url:
        raise RuntimeError("No MCP URL available.")
    dump_dir = artifact_dir / "mcp-surface"
    dump_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "dump_mcp_surface.py"),
        "--strict",
        "--output",
        str(dump_dir),
        "--url",
        url,
    ]
    if auth:
        command.extend(["--auth", auth])
    proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    (artifact_dir / "dump-mcp-surface.log").write_text(proc.stdout, encoding="utf-8")
    if proc.returncode:
        raise RuntimeError("dump_mcp_surface.py failed; inspect dump-mcp-surface.log")
    return load_surface_snapshot(dump_dir / "mcp_surface.json")


def run_offline_plan(args: argparse.Namespace, *, live: bool) -> int:
    artifact_dir = Path(args.artifact_dir).expanduser() if args.artifact_dir else ROOT / "artifacts" / "tavo-validation" / f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-media-provider-matrix"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    cases = select_cases(build_cases("MEDIA-PROVIDER-MATRIX"), args.cases)
    if live:
        surface = capture_live_surface(args, artifact_dir)
    else:
        surface = load_surface_snapshot(Path(args.surface_json).expanduser() if args.surface_json else DEFAULT_SURFACE_JSON)
    docs = load_official_docs(Path(args.docs_root).expanduser() if args.docs_root else DEFAULT_DOCS_ROOT)
    outcomes = [plan_case(surface, docs, case) for case in cases]

    if live:
        endpoint = load_endpoint(args.endpoint_json)
        url = args.url or endpoint.get("url", "")
        auth = args.auth or endpoint.get("auth", "")
        if not url:
            raise RuntimeError("No MCP URL available.")
        client = TavoMcp(url, auth)
        for index, (case, outcome) in enumerate(zip(cases, outcomes, strict=True), start=1):
            case_dir = artifact_dir / "cases" / case.key
            case_dir.mkdir(parents=True, exist_ok=True)
            if outcome.status == "blocked":
                write_case_manifest(case_dir, outcome)
                atomic_json(
                    case_dir / "blocked.json",
                    {
                        "case": case.key,
                        "blockedKind": outcome.block_kind,
                        "blockedReason": outcome.blocked_reason,
                        "surface": outcome.surface,
                        "docs": outcome.docs,
                    },
                )
                continue
            try:
                if case.family == "image-send":
                    executed = execute_message_attachment_case(
                        client,
                        surface,
                        case_dir,
                        case,
                        run_id="MEDIA-PROVIDER-MATRIX",
                        device=args.device,
                        timeout=args.per_call_timeout,
                    )
                elif case.family in {"image-provider", "voice-provider", "voice-binding"}:
                    executed = execute_asset_case(
                        client,
                        surface,
                        docs,
                        case_dir,
                        case,
                        run_id="MEDIA-PROVIDER-MATRIX",
                        timeout=args.per_call_timeout,
                    )
                elif case.family in {"tts", "stt"}:
                    executed = execute_sample_case(
                        client,
                        surface,
                        docs,
                        case_dir,
                        case,
                        run_id="MEDIA-PROVIDER-MATRIX",
                        timeout=args.per_call_timeout,
                    )
                else:
                    executed = outcome
                    executed.status = "blocked"
                    executed.block_kind = "surface-blocked"
                    executed.blocked_reason = "surface-blocked: unsupported case family in executor"
                outcomes[index - 1] = executed
                write_case_manifest(case_dir, executed)
            except Exception as exc:  # noqa: BLE001 - preserve diagnostic detail
                failure = plan_case(surface, docs, case)
                failure.status = "failed"
                failure.block_kind = "failed_runner_or_infrastructure"
                failure.blocked_reason = repr(exc)
                failure.artifacts = sorted(
                    [
                        *failure.artifacts,
                        f"cases/{case.key}/{case.key}-dry-run.json",
                        f"cases/{case.key}/{case.key}-actual.json",
                        f"cases/{case.key}/{case.key}-readback.json",
                    ]
                )
                outcomes[index - 1] = failure
                write_case_manifest(case_dir, failure)
                atomic_json(
                    case_dir / "failure.json",
                    {
                        "case": case.key,
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    },
                )

    save_support_artifacts(artifact_dir, surface, docs, outcomes)
    for outcome, case in zip(outcomes, cases, strict=True):
        case_dir = artifact_dir / "cases" / case.key
        case_dir.mkdir(parents=True, exist_ok=True)
        write_case_manifest(case_dir, outcome)
        if outcome.status == "blocked":
            atomic_json(
                case_dir / "blocked.json",
                {
                    "case": case.key,
                    "blockedKind": outcome.block_kind,
                    "blockedReason": outcome.blocked_reason,
                    "surface": outcome.surface,
                    "docs": outcome.docs,
                },
            )

    root_status = "blocked" if all(outcome.status == "blocked" for outcome in outcomes) else "planned"
    if live:
        if all(outcome.status == "blocked" for outcome in outcomes):
            root_status = "blocked"
        elif any(outcome.status == "failed" for outcome in outcomes):
            root_status = "failed_runner_or_infrastructure"
        else:
            root_status = "passed"
    root_manifest = write_root_manifest(
        artifact_dir,
        "MEDIA-PROVIDER-MATRIX",
        cases,
        outcomes,
        surface,
        docs,
        status=root_status,
        mode="execute" if live else "plan",
    )

    payload = {
        "artifactDir": str(artifact_dir),
        "manifest": str(root_manifest),
        "status": root_status,
        "summary": summarize_plan(outcomes),
        "cases": [
            {
                "key": outcome.key,
                "status": outcome.status,
                "blockKind": outcome.block_kind,
                "blockedReason": outcome.blocked_reason,
            }
            for outcome in outcomes
        ],
    }
    if args.print_plan or not live:
        print(json.dumps(strict_redact(payload), ensure_ascii=False, indent=2))
    else:
        print(f"artifact_dir={artifact_dir}")
        print(f"manifest={root_manifest}")
        print(f"status={root_status}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Tavo media/provider real-phone matrix.")
    parser.add_argument("--execute", action="store_true", help="Run the live matrix when the current surface exposes the needed tools.")
    parser.add_argument("--self-check", action="store_true", help="Inspect the current surface and official snapshot docs without making phone changes.")
    parser.add_argument("--print-plan", action="store_true", help="Print the planned matrix as JSON.")
    parser.add_argument("--cases", default="", help="Comma-separated subset of case keys.")
    parser.add_argument("--artifact-dir", default="", help="Artifact directory for manifests and captures.")
    parser.add_argument("--surface-json", default="", help="Use a specific MCP surface JSON snapshot instead of the bundled default.")
    parser.add_argument("--docs-root", default="", help="Use a specific official-docs snapshot directory instead of the bundled default.")
    parser.add_argument("--endpoint-json", default=str(DEFAULT_ENDPOINT_JSON))
    parser.add_argument("--url", default="")
    parser.add_argument("--auth", default="")
    parser.add_argument("--device", default="")
    parser.add_argument("--per-call-timeout", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (args.execute or args.self_check or args.print_plan):
        print("Use --self-check, --print-plan, or --execute.", file=sys.stderr)
        return 2
    live = bool(args.execute)
    return run_offline_plan(args, live=live)


if __name__ == "__main__":
    raise SystemExit(main())
