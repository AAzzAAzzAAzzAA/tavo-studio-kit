#!/usr/bin/env python3
"""Run a retained Tavo asset roundtrip matrix against a real MCP surface.

The matrix focuses on asset fidelity and conservative write behavior:

* Characters are exercised through native create, readback, update, export,
  and import paths, including CCv2, CCv3, JSON, Tavo-wrapper, and PNG
  roundtrips.
* Personas are exercised through create, readback, update, export, import,
  and bind/restore paths.
* PNG card encode/decode uses the existing Node helpers in this skill.
* Default behavior is retain-only. There is no delete path and no implicit
  execution without ``--execute``.
* If the surface is missing a required tool, the case is reported as a
  structured ``surface-blocked`` result instead of being forced through.

This runner is intentionally offline-friendly: ``--self-check`` and
``--print-plan`` do not contact the surface.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
import secrets
import subprocess
import sys
import traceback
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = Path(__file__).resolve()
EMBED_PNG = ROOT / "scripts" / "embed_st_card_png.mjs"
EXTRACT_PNG = ROOT / "scripts" / "extract_st_card_png.mjs"
STATIC_SURFACE_DUMP = ROOT / "assets" / "schemas" / "mcp-surface-0.91.0-20260710.json"
DEFAULT_ENDPOINT = "/tmp/tavo_mcp_endpoint.json"

sys.path.insert(0, str(ROOT / "scripts"))

from run_phone_cross_feature_matrix import (  # noqa: E402
    asset_content_payload,
    payload_mismatches,
    stable_content_hash,
)
from run_phone_import_kpi import response_payload  # noqa: E402
from run_phone_kpi_batch import TavoMcp, load_endpoint, ok_response, redact  # noqa: E402


MIN_CASES = 1


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "-" for ch in value).strip("-")


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def durable_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def durable_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact(event), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def compare_expected(expected: Any, actual: Any, path: str = "$") -> list[str]:
    return payload_mismatches(expected, actual, path)


def response_asset_id(response: dict[str, Any]) -> int:
    payload = response_payload(response)
    for key in ("characterId", "personaId", "id"):
        candidate = payload.get(key)
        if isinstance(candidate, int) and candidate > 0:
            return candidate
        if isinstance(candidate, str) and candidate.isdigit() and int(candidate) > 0:
            return int(candidate)
    for nested_key in ("character", "persona"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            candidate = nested.get("id")
            if isinstance(candidate, int) and candidate > 0:
                return candidate
            if isinstance(candidate, str) and candidate.isdigit() and int(candidate) > 0:
                return int(candidate)
    return 0


def response_asset_payload(response: dict[str, Any], family: str) -> dict[str, Any]:
    payload = response_payload(response)
    if family == "character":
        if not isinstance(payload, dict):
            return {}
        if isinstance(payload.get("data"), dict):
            return payload["data"]
        nested = payload.get("character")
        if isinstance(nested, dict):
            if isinstance(nested.get("data"), dict):
                return nested["data"]
            return nested
        return asset_content_payload("character", payload)
    for key in ("persona", "chat", "preset", "lorebook", "regex"):
        nested = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(nested, dict):
            return nested
    return payload if isinstance(payload, dict) else {}


def request_id(run_id: str, case_key: str, phase: str) -> str:
    return f"{safe_name(run_id)}-{safe_name(case_key)}-{safe_name(phase)}"


def make_base_png() -> bytes:
    """Create a tiny valid RGBA PNG without any external assets."""

    def chunk(chunk_type: str, data: bytes) -> bytes:
        marker = chunk_type.encode("latin1")
        length = len(data).to_bytes(4, "big")
        crc = zlib.crc32(marker + data) & 0xFFFFFFFF
        return length + marker + data + crc.to_bytes(4, "big")

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(
        "IHDR",
        (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08"
        + b"\x06"
        + b"\x00"
        + b"\x00"
        + b"\x00",
    )
    raw_pixel = b"\x00\x00\x00\x00\x00"
    idat = chunk("IDAT", zlib.compress(raw_pixel, level=9))
    iend = chunk("IEND", b"")
    return signature + ihdr + idat + iend


def write_base_png(path: Path) -> None:
    durable_bytes(path, make_base_png())


def durable_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def run_node(script: Path, arguments: list[str], output: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", str(script), *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    payload: dict[str, Any]
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"ok": False, "rawOutput": proc.stdout, "exitCode": proc.returncode}
    durable_json(output, payload)
    return payload


def node_embed_png(png_path: Path, json_path: Path, out_path: Path, *, chara_only: bool = False) -> dict[str, Any]:
    args = ["--png", str(png_path), "--json", str(json_path), "--out", str(out_path), "--overwrite"]
    if chara_only:
        args.append("--chara-only")
    return run_node(EMBED_PNG, args, out_path.with_suffix(out_path.suffix + ".embed.json"))


def node_extract_png(png_path: Path, out_path: Path, *, prefer_chara: bool = False) -> dict[str, Any]:
    args = ["--png", str(png_path), "--out", str(out_path)]
    if prefer_chara:
        args.append("--prefer-chara")
    return run_node(EXTRACT_PNG, args, out_path.with_suffix(out_path.suffix + ".extract.json"))


def current_utc_name(prefix: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"{prefix}-{stamp}-{secrets.token_hex(3).upper()}"


def build_character_data(run_id: str) -> dict[str, Any]:
    return {
        "name": f"Codex Asset Roundtrip Character {run_id}",
        "description": (
            "{{char}} is a careful asset auditor. "
            "The character preserves exact evidence values and prefers concrete readbacks over guesses."
        ),
        "personality": "Precise, calm, concise, and intolerant of fabricated evidence.",
        "scenario": (
            "{{char}} and {{user}} are validating Tavo asset roundtrips on a retained test surface."
        ),
        "first_mes": "The desk is open. Show me the asset and I will read it back exactly.",
        "mes_example": (
            "<START>\n"
            "{{user}}: What matters most in a roundtrip check?\n"
            "{{char}}: Exact readback, stable update behavior, and no silent loss of fields."
        ),
        "creator_notes": f"Retained Codex asset roundtrip evidence for {run_id}.",
        "system_prompt": "Preserve exact machine-readable fields and do not invent missing evidence.",
        "post_history_instructions": "Keep replies grounded, short, and audit-friendly.",
        "alternate_greetings": [
            "Audit desk ready. We can start with the longest path.",
            "If the payload changed, name the field that changed.",
        ],
        "tags": ["codex", "asset-roundtrip", "retained-evidence"],
        "creator": "Codex",
        "character_version": "1.0.0",
        "nickname": "Audit Desk",
        "character_book": {
            "name": f"Codex Asset Book {run_id}",
            "description": "Portable character book used to exercise nested character_book roundtrips.",
            "scan_depth": 6,
            "token_budget": 512,
            "recursive_scanning": False,
            "entries": [
                {
                    "keys": [f"roundtrip-{run_id}", "asset-roundtrip"],
                    "secondary_keys": [f"nested-{run_id}"],
                    "comment": "Primary evidence rule.",
                    "content": (
                        f"When the prompt mentions roundtrip-{run_id}, preserve the exact run marker in readbacks."
                    ),
                    "constant": False,
                    "selective": True,
                    "insertion_order": 100,
                    "enabled": True,
                    "position": "after_char",
                }
            ],
        },
        "extensions": {
            "roundtrip": {
                "runId": run_id,
                "mode": "native-max",
                "notes": ["character_book", "avatar-free"],
            }
        },
    }


def build_character_card(run_id: str, *, spec: str = "chara_card_v2", spec_version: str = "2.0") -> dict[str, Any]:
    data = build_character_data(run_id)
    return {"spec": spec, "spec_version": spec_version, "data": data}


def build_persona_payload(run_id: str) -> dict[str, Any]:
    avatar_png = base64.b64encode(make_base_png()).decode("ascii")
    return {
        "name": f"Codex Asset Roundtrip Persona {run_id}",
        "description": (
            "A user persona that exists to verify persona create, update, export, import, and bind behavior."
        ),
        "avatar": f"data:image/png;base64,{avatar_png}",
        "active": False,
    }


@dataclass(frozen=True)
class CaseSpec:
    key: str
    family: str
    mode: str
    required_tools: tuple[str, ...]
    notes: str = ""

    @property
    def step_name(self) -> str:
        return safe_name(self.key)


@dataclass
class SurfaceReport:
    available_tools: tuple[str, ...]
    missing_tools: tuple[str, ...]
    server_info: dict[str, Any]
    raw: dict[str, Any]


def build_cases() -> list[CaseSpec]:
    return [
        CaseSpec(
            key="character-native",
            family="character",
            mode="character-native",
            required_tools=("tavo_character_create", "tavo_character_get", "tavo_character_update", "tavo_character_import_card"),
            notes="Native create/readback/update plus JSON and Tavo local export/import.",
        ),
        CaseSpec(
            key="character-ccv2",
            family="character",
            mode="character-ccv2",
            required_tools=("tavo_character_import_card", "tavo_character_get"),
            notes="CCv2 import roundtrip.",
        ),
        CaseSpec(
            key="character-ccv3",
            family="character",
            mode="character-ccv3",
            required_tools=("tavo_character_import_card", "tavo_character_get"),
            notes="CCv3 import roundtrip.",
        ),
        CaseSpec(
            key="character-png",
            family="character",
            mode="character-png",
            required_tools=("tavo_character_import_card", "tavo_character_get"),
            notes="PNG embed/extract/import roundtrip via existing Node tools.",
        ),
        CaseSpec(
            key="persona-roundtrip",
            family="persona",
            mode="persona-roundtrip",
            required_tools=(
                "tavo_current_chat_get",
                "tavo_persona_create",
                "tavo_persona_get",
                "tavo_persona_set_active",
                "tavo_persona_update",
            ),
            notes="Persona create/update/export/import plus bind and restore.",
        ),
    ]


def validate_case_plan(cases: list[CaseSpec]) -> None:
    errors: list[str] = []
    if len(cases) < MIN_CASES:
        errors.append("at least one case must be selected")
    keys = [case.key for case in cases]
    if len(keys) != len(set(keys)):
        errors.append("case keys are not unique")
    families = {case.family for case in cases}
    if families - {"character", "persona"}:
        errors.append(f"unknown case families: {sorted(families - {'character', 'persona'})}")
    for case in cases:
        if not case.required_tools:
            errors.append(f"{case.key} has no required tools")
        if not case.mode:
            errors.append(f"{case.key} has no execution mode")
    if errors:
        raise RuntimeError("Invalid asset roundtrip plan: " + "; ".join(errors))


def select_cases(cases: list[CaseSpec], raw_keys: str) -> list[CaseSpec]:
    if not raw_keys.strip():
        return cases
    requested = [item.strip() for item in raw_keys.split(",") if item.strip()]
    if not requested:
        raise RuntimeError("--case-keys did not contain any case key")
    if len(requested) != len(set(requested)):
        raise RuntimeError("--case-keys contains duplicates")
    available = {case.key for case in cases}
    unknown = sorted(set(requested) - available)
    if unknown:
        raise RuntimeError(f"Unknown --case-keys: {unknown}")
    wanted = set(requested)
    return [case for case in cases if case.key in wanted]


def plan_record(run_id: str, cases: list[CaseSpec], *, full_matrix_selection: bool) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "case": "tavo-phone-asset-roundtrip-matrix",
        "runId": run_id,
        "plannedCases": len(cases),
        "families": sorted({case.family for case in cases}),
        "selectedCaseKeys": [case.key for case in cases],
        "fullMatrixSelection": full_matrix_selection,
        "safety": {
            "executeRequiresFlag": True,
            "retainedByDefault": True,
            "deletePath": "none",
            "surfaceBlocked": "structured",
            "nodeHelpers": [str(EMBED_PNG), str(EXTRACT_PNG)],
        },
        "cases": [
            {
                **asdict(case),
                "requiredTools": list(case.required_tools),
                "specHash": stable_hash(asdict(case)),
            }
            for case in cases
        ],
    }


def validation_manifest(
    *,
    run_id: str,
    artifact_dir: Path,
    plan_hash: str,
    script_hash: str,
    cases: list[CaseSpec],
    status: str,
    started_at: str,
    finished_at: str | None,
    surface: dict[str, Any],
    summary: dict[str, Any],
    blocked_cases: list[str],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "case": "tavo-phone-asset-roundtrip-matrix",
        "runId": run_id,
        "status": status,
        "startedAt": started_at,
        "artifactDir": str(artifact_dir),
        "scriptHash": script_hash,
        "planHash": plan_hash,
        "selectedCaseKeys": [case.key for case in cases],
        "fullMatrixSelection": len(cases) == len(build_cases()),
        "countsTowardKpi": status == "passed" and len(cases) == len(build_cases()),
        "artifacts": [
            "plan.json",
            "surface.json",
            "results.json",
            "events.jsonl",
        ],
        "surface": surface,
        "summary": summary,
        "blockedCases": blocked_cases,
        "results": results,
        "partialEvidenceUsable": status in {"passed", "blocked"} and not summary.get("runnerFailures"),
    }
    if finished_at is not None:
        manifest["finishedAt"] = finished_at
    return manifest


def validate_validation_manifest_shape(manifest: dict[str, Any]) -> None:
    if manifest.get("schemaVersion") != "1.0.0":
        raise RuntimeError("manifest schemaVersion must be 1.0.0")
    for key in ("case", "status", "startedAt", "artifacts"):
        if key not in manifest:
            raise RuntimeError(f"manifest missing {key}")
    if not isinstance(manifest.get("artifacts"), list) or not manifest["artifacts"]:
        raise RuntimeError("manifest artifacts must be a non-empty list")


def create_artifact_lock(artifact_dir: Path) -> Any:
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise RuntimeError("Artifact directory already exists and is non-empty; every run must use a fresh directory.")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    handle = (artifact_dir / ".run.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("Another process holds this artifact directory lock.")
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()} acquired={now_utc()}\n")
    handle.flush()
    os.fsync(handle.fileno())
    return handle


def call_tool(client: TavoMcp, output: Path, tool: str, arguments: dict[str, Any], timeout: int) -> dict[str, Any]:
    response = client.tool(tool, arguments, timeout=timeout)
    durable_json(output, response)
    return response


def read_surface(client: TavoMcp, output_dir: Path) -> SurfaceReport:
    tools_response = client.rpc("tools/list", {})
    durable_json(output_dir / "tools-list.json", tools_response)
    tools_payload = response_payload(tools_response)
    tool_names = []
    if isinstance(tools_payload, dict):
        for item in tools_payload.get("tools") or []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                tool_names.append(item["name"])
    tool_names = sorted(set(tool_names))
    status_response = None
    try:
        status_response = client.tool("tavo_status", {}, timeout=30)
        durable_json(output_dir / "status.json", status_response)
    except Exception:
        status_response = None
    server_info: dict[str, Any] = {}
    if status_response is not None:
        status_payload = response_payload(status_response)
        if isinstance(status_payload, dict):
            server_info = dict(status_payload.get("serverInfo") or {})
    missing_tools = tuple(sorted(set().union(*(set(case.required_tools) for case in build_cases())) - set(tool_names)))
    surface = {
        "dumpedAt": now_utc(),
        "serverInfo": server_info,
        "availableTools": tool_names,
        "availableToolCount": len(tool_names),
        "missingRequiredTools": list(missing_tools),
    }
    durable_json(output_dir / "surface.json", surface)
    return SurfaceReport(tuple(tool_names), missing_tools, server_info, surface)


def surface_blocked_result(case: CaseSpec, missing: list[str], surface: SurfaceReport) -> dict[str, Any]:
    reason = f"Surface missing required tools: {', '.join(missing)}"
    return {
        "key": case.key,
        "family": case.family,
        "mode": case.mode,
        "passed": False,
        "status": "blocked",
        "failureClass": "surface_blocked",
        "usableAsEvidence": False,
        "surfaceBlocked": True,
        "block": {
            "kind": "surface-blocked",
            "reason": reason,
            "requiredTools": list(case.required_tools),
            "missingTools": missing,
            "availableTools": list(surface.available_tools),
        },
    }


def claim_asset(ledger: dict[str, list[dict[str, Any]]], family: str, asset_id: int, **metadata: Any) -> None:
    records = ledger.setdefault(family, [])
    for record in records:
        if record.get("id") == asset_id:
            record.update(metadata)
            return
    records.append({"id": asset_id, **metadata})


def load_ledger(path: Path, run_id: str) -> dict[str, list[dict[str, Any]]]:
    if path.exists():
        data = load_json(path)
        if data.get("runId") != run_id:
            raise RuntimeError("Ownership ledger belongs to a different run.")
        return data
    data = {
        "schemaVersion": "1.0.0",
        "runId": run_id,
        "createdAt": now_utc(),
        "character": [],
        "persona": [],
    }
    durable_json(path, data)
    return data


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
    ledger["updatedAt"] = now_utc()
    durable_json(path, ledger)


def compare_asset_payload(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    return compare_expected(expected, actual)


def write_intent(step_dir: Path, intent: dict[str, Any]) -> None:
    intent_path = step_dir / "intent.json"
    result_path = step_dir / "result.json"
    if intent_path.exists() and not result_path.exists():
        raise FileExistsError(f"Unresolved intent already exists for {step_dir.name}")
    durable_json(intent_path, intent)


def finalize_step(step_dir: Path, result: dict[str, Any]) -> None:
    durable_json(step_dir / "result.json", result)


def import_character_from_card(
    client: TavoMcp,
    case_dir: Path,
    label: str,
    card: dict[str, Any],
    timeout: int,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    import_path = case_dir / f"{label}.import-card.json"
    write_intent(case_dir / label, {"tool": "tavo_character_import_card", "label": label, "clientRequestId": request_id(label, label, "import")})
    response = call_tool(
        client,
        import_path,
        "tavo_character_import_card",
        {"card": card, "clientRequestId": request_id(label, label, "import"), "dryRun": False},
        timeout,
    )
    asset_id = response_asset_id(response)
    if asset_id <= 0:
        raise RuntimeError(f"{label} import did not return an id.")
    readback = call_tool(client, case_dir / f"{label}.readback.json", "tavo_character_get", {"id": asset_id}, timeout)
    payload = response_asset_payload(readback, "character")
    return asset_id, payload, response_payload(response)


def import_persona_from_payload(
    client: TavoMcp,
    case_dir: Path,
    label: str,
    persona: dict[str, Any],
    timeout: int,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    write_intent(case_dir / label, {"tool": "tavo_persona_create", "label": label})
    response = call_tool(
        client,
        case_dir / f"{label}.create.json",
        "tavo_persona_create",
        {"persona": persona, "clientRequestId": request_id(label, label, "create"), "dryRun": False},
        timeout,
    )
    asset_id = response_asset_id(response)
    if asset_id <= 0:
        raise RuntimeError(f"{label} create did not return an id.")
    readback = call_tool(client, case_dir / f"{label}.readback.json", "tavo_persona_get", {"id": asset_id}, timeout)
    payload = response_asset_payload(readback, "persona")
    return asset_id, payload, response_payload(response)


def normalize_character_readback(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)


def normalize_persona_readback(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {key: payload[key] for key in ("name", "description", "avatar", "active") if key in payload}
    return allowed


def execute_character_native(
    client: TavoMcp,
    case: CaseSpec,
    case_dir: Path,
    run_id: str,
    timeout: int,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    card = build_character_card(run_id)
    card_path = case_dir / "source" / "character.native.card.json"
    tavo_path = case_dir / "source" / "character.native.tavo.json"
    durable_json(card_path, card)
    durable_json(tavo_path, {"kind": "character", "format": "tavo", "card": card})

    create_args = {
        "character": card["data"],
        "clientRequestId": request_id(run_id, case.key, "create"),
        "dryRun": False,
    }
    write_intent(case_dir / "create", {"tool": "tavo_character_create", "arguments": create_args})
    create_response = call_tool(client, case_dir / "create.json", "tavo_character_create", create_args, timeout)
    character_id = response_asset_id(create_response)
    if character_id <= 0:
        raise RuntimeError("character create did not return a valid id")
    claim_asset(ledger, "character", character_id, case=case.key, mode=case.mode)
    save_ledger(case_dir.parent.parent / "ownership-ledger.json", ledger)

    readback = call_tool(client, case_dir / "readback.json", "tavo_character_get", {"id": character_id}, timeout)
    readback_payload = normalize_character_readback(response_asset_payload(readback, "character"))
    expected = dict(card["data"])
    mismatches = compare_asset_payload(expected, readback_payload)
    if mismatches:
        return {
            "key": case.key,
            "family": case.family,
            "mode": case.mode,
            "passed": False,
            "status": "failed_product_behavior",
            "failureClass": "product_behavior",
            "usableAsEvidence": True,
            "characterId": character_id,
            "productBehaviorFailures": mismatches,
        }

    updated = dict(expected)
    updated["description"] = expected["description"] + " Updated to prove roundtrip update behavior."
    update_args = {
        "id": character_id,
        "character": updated,
        "clientRequestId": request_id(run_id, case.key, "update"),
        "dryRun": False,
    }
    revision = readback_payload.get("revision")
    if isinstance(revision, str) and revision:
        update_args["expectedRevision"] = revision
    write_intent(case_dir / "update", {"tool": "tavo_character_update", "arguments": update_args})
    update_response = call_tool(client, case_dir / "update.json", "tavo_character_update", update_args, timeout)
    if not ok_response(update_response):
        raise RuntimeError("character update failed")
    updated_readback = call_tool(client, case_dir / "updated-readback.json", "tavo_character_get", {"id": character_id}, timeout)
    updated_payload = normalize_character_readback(response_asset_payload(updated_readback, "character"))
    if compare_asset_payload(updated, updated_payload):
        raise RuntimeError("character update did not persist the updated payload")

    json_export = case_dir / "exports" / "character.native.card.json"
    tavo_export = case_dir / "exports" / "character.native.tavo.json"
    durable_json(json_export, card)
    durable_json(tavo_export, {"kind": "character", "format": "tavo", "card": card})

    json_import_id, json_import_payload, _ = import_character_from_card(
        client,
        case_dir / "imports-json",
        f"{case.key}-json-import",
        load_json(json_export),
        timeout,
    )
    if compare_asset_payload(expected, json_import_payload):
        raise RuntimeError("character JSON import readback diverged from source payload")
    claim_asset(ledger, "character", json_import_id, case=f"{case.key}:json")

    tavo_import_card = load_json(tavo_export)["card"]
    tavo_import_id, tavo_import_payload, _ = import_character_from_card(
        client,
        case_dir / "imports-tavo",
        f"{case.key}-tavo-import",
        tavo_import_card,
        timeout,
    )
    if compare_asset_payload(expected, tavo_import_payload):
        raise RuntimeError("character Tavo-file import readback diverged from source payload")
    claim_asset(ledger, "character", tavo_import_id, case=f"{case.key}:tavo")

    return {
        "key": case.key,
        "family": case.family,
        "mode": case.mode,
        "passed": True,
        "status": "passed",
        "failureClass": None,
        "usableAsEvidence": True,
        "characterId": character_id,
        "importedCharacterIds": [json_import_id, tavo_import_id],
        "exportHashes": {
            "json": stable_hash(card),
            "tavo": stable_hash({"kind": "character", "format": "tavo", "card": card}),
        },
    }


def build_cc_card(run_id: str, *, spec: str, spec_version: str) -> dict[str, Any]:
    return build_character_card(run_id, spec=spec, spec_version=spec_version)


def execute_character_import_case(
    client: TavoMcp,
    case: CaseSpec,
    case_dir: Path,
    run_id: str,
    timeout: int,
    ledger: dict[str, Any],
    *,
    spec: str,
    spec_version: str,
) -> dict[str, Any]:
    card = build_cc_card(run_id, spec=spec, spec_version=spec_version)
    durable_json(case_dir / "source" / f"{case.key}.json", card)
    write_intent(case_dir / "import", {"tool": "tavo_character_import_card", "case": case.key})
    import_response = call_tool(
        client,
        case_dir / "import.json",
        "tavo_character_import_card",
        {"card": card, "clientRequestId": request_id(run_id, case.key, "import"), "dryRun": False},
        timeout,
    )
    character_id = response_asset_id(import_response)
    if character_id <= 0:
        raise RuntimeError(f"{case.key} import did not return a valid id")
    claim_asset(ledger, "character", character_id, case=case.key, spec=spec)
    save_ledger(case_dir.parent.parent / "ownership-ledger.json", ledger)
    readback = call_tool(client, case_dir / "readback.json", "tavo_character_get", {"id": character_id}, timeout)
    payload = normalize_character_readback(response_asset_payload(readback, "character"))
    expected = dict(card["data"])
    mismatches = compare_asset_payload(expected, payload)
    if mismatches:
        return {
            "key": case.key,
            "family": case.family,
            "mode": case.mode,
            "passed": False,
            "status": "failed_product_behavior",
            "failureClass": "product_behavior",
            "usableAsEvidence": True,
            "characterId": character_id,
            "productBehaviorFailures": mismatches,
        }
    return {
        "key": case.key,
        "family": case.family,
        "mode": case.mode,
        "passed": True,
        "status": "passed",
        "failureClass": None,
        "usableAsEvidence": True,
        "characterId": character_id,
        "spec": spec,
    }


def execute_character_png(
    client: TavoMcp,
    case: CaseSpec,
    case_dir: Path,
    run_id: str,
    timeout: int,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    card = build_character_card(run_id)
    source_dir = case_dir / "source"
    durable_json(source_dir / "character.png.card.json", card)
    base_png = source_dir / "base.png"
    write_base_png(base_png)
    embedded_png = case_dir / "artifacts" / "embedded.png"
    node_embed_png(base_png, source_dir / "character.png.card.json", embedded_png)
    extracted_json = case_dir / "artifacts" / "extracted.json"
    node_extract_png(embedded_png, extracted_json, prefer_chara=True)
    extracted_card = load_json(extracted_json)
    if compare_expected(card, extracted_card):
        raise RuntimeError("PNG extraction did not match the source card")
    import_response = call_tool(
        client,
        case_dir / "import.json",
        "tavo_character_import_card",
        {"card": extracted_card, "clientRequestId": request_id(run_id, case.key, "import"), "dryRun": False},
        timeout,
    )
    character_id = response_asset_id(import_response)
    if character_id <= 0:
        raise RuntimeError("PNG import did not return a valid id")
    claim_asset(ledger, "character", character_id, case=case.key, mode=case.mode)
    save_ledger(case_dir.parent.parent / "ownership-ledger.json", ledger)
    readback = call_tool(client, case_dir / "readback.json", "tavo_character_get", {"id": character_id}, timeout)
    payload = normalize_character_readback(response_asset_payload(readback, "character"))
    if compare_asset_payload(card["data"], payload):
        raise RuntimeError("PNG-imported character readback diverged from source payload")
    return {
        "key": case.key,
        "family": case.family,
        "mode": case.mode,
        "passed": True,
        "status": "passed",
        "failureClass": None,
        "usableAsEvidence": True,
        "characterId": character_id,
        "embeddedPng": str(embedded_png),
    }


def execute_persona_roundtrip(
    client: TavoMcp,
    case: CaseSpec,
    case_dir: Path,
    run_id: str,
    timeout: int,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    persona = build_persona_payload(run_id)
    source_dir = case_dir / "source"
    durable_json(source_dir / "persona.json", persona)
    current_chat = call_tool(client, case_dir / "current-chat.json", "tavo_current_chat_get", {}, timeout)
    current_chat_payload = response_payload(current_chat)
    prior_persona_id = 0
    if isinstance(current_chat_payload, dict):
        chat = current_chat_payload.get("chat")
        if isinstance(chat, dict):
            candidate = chat.get("personaId")
            if isinstance(candidate, int) and candidate > 0:
                prior_persona_id = candidate

    write_intent(case_dir / "create", {"tool": "tavo_persona_create", "case": case.key})
    create_response = call_tool(
        client,
        case_dir / "create.json",
        "tavo_persona_create",
        {"persona": persona, "clientRequestId": request_id(run_id, case.key, "create"), "dryRun": False},
        timeout,
    )
    persona_id = response_asset_id(create_response)
    if persona_id <= 0:
        raise RuntimeError("persona create did not return a valid id")
    claim_asset(ledger, "persona", persona_id, case=case.key, mode="created")
    save_ledger(case_dir.parent.parent / "ownership-ledger.json", ledger)
    readback = call_tool(client, case_dir / "readback.json", "tavo_persona_get", {"id": persona_id}, timeout)
    payload = normalize_persona_readback(response_asset_payload(readback, "persona"))
    if compare_expected({k: persona[k] for k in ("name", "description", "avatar", "active")}, payload):
        raise RuntimeError("persona readback diverged from created payload")

    updated = dict(persona)
    updated["description"] = updated["description"] + " Updated to prove persona update behavior."
    write_intent(case_dir / "update", {"tool": "tavo_persona_update", "case": case.key})
    update_args = {
        "id": persona_id,
        "persona": {k: updated[k] for k in ("name", "description", "avatar", "active")},
        "clientRequestId": request_id(run_id, case.key, "update"),
        "dryRun": False,
    }
    update_response = call_tool(client, case_dir / "update.json", "tavo_persona_update", update_args, timeout)
    if not ok_response(update_response):
        raise RuntimeError("persona update failed")
    updated_readback = call_tool(client, case_dir / "updated-readback.json", "tavo_persona_get", {"id": persona_id}, timeout)
    updated_payload = normalize_persona_readback(response_asset_payload(updated_readback, "persona"))
    if compare_expected({k: updated[k] for k in ("name", "description", "avatar", "active")}, updated_payload):
        raise RuntimeError("persona update did not persist the updated payload")

    export_path = case_dir / "exports" / "persona.json"
    updated_persona_payload = response_asset_payload(updated_readback, "persona")
    durable_json(export_path, updated_persona_payload)
    durable_json(case_dir / "exports" / "persona.tavo.json", {"kind": "persona", "persona": updated_persona_payload})

    imported_id, imported_payload, _ = import_persona_from_payload(
        client,
        case_dir / "imports",
        f"{case.key}-import",
        load_json(export_path),
        timeout,
    )
    claim_asset(ledger, "persona", imported_id, case=f"{case.key}:import")
    save_ledger(case_dir.parent.parent / "ownership-ledger.json", ledger)
    if compare_expected({k: updated[k] for k in ("name", "description", "avatar", "active")}, normalize_persona_readback(imported_payload)):
        raise RuntimeError("persona import readback diverged from exported payload")

    bind_args = {
        "id": imported_id,
        "clientRequestId": request_id(run_id, case.key, "bind"),
        "dryRun": False,
    }
    call_tool(client, case_dir / "bind-before.json", "tavo_persona_get", {"id": imported_id}, timeout)
    write_intent(case_dir / "bind", {"tool": "tavo_persona_set_active", "case": case.key, "personaId": imported_id})
    bind_response = call_tool(client, case_dir / "bind.json", "tavo_persona_set_active", bind_args, timeout)
    if not ok_response(bind_response):
        raise RuntimeError("persona bind failed")
    bound_readback = call_tool(client, case_dir / "bound-readback.json", "tavo_persona_get", {"id": imported_id}, timeout)
    bound_payload = normalize_persona_readback(response_asset_payload(bound_readback, "persona"))
    if bound_payload.get("active") is not True:
        raise RuntimeError("persona did not become active after bind")

    # Restore the previous active persona if one was present in the current chat snapshot.
    restore_id = prior_persona_id
    if restore_id > 0 and restore_id != imported_id:
        restore_args = {
            "id": restore_id,
            "clientRequestId": request_id(run_id, case.key, "restore"),
            "dryRun": False,
        }
        write_intent(case_dir / "restore", {"tool": "tavo_persona_set_active", "case": case.key, "personaId": restore_id})
        restore_response = call_tool(client, case_dir / "restore.json", "tavo_persona_set_active", restore_args, timeout)
        if not ok_response(restore_response):
            raise RuntimeError("persona restore failed")

    final_persona = call_tool(client, case_dir / "final-persona.json", "tavo_persona_get", {"id": imported_id}, timeout)
    if normalize_persona_readback(response_asset_payload(final_persona, "persona")).get("active") is True and restore_id > 0:
        raise RuntimeError("persona restore did not clear the imported persona active state")

    return {
        "key": case.key,
        "family": case.family,
        "mode": case.mode,
        "passed": True,
        "status": "passed",
        "failureClass": None,
        "usableAsEvidence": True,
        "personaId": persona_id,
        "importedPersonaId": imported_id,
        "restoredPersonaId": restore_id,
    }


def execute_case(
    client: TavoMcp,
    case: CaseSpec,
    case_dir: Path,
    run_id: str,
    timeout: int,
    ledger: dict[str, Any],
    surface: SurfaceReport,
) -> dict[str, Any]:
    missing = [tool for tool in case.required_tools if tool not in surface.available_tools]
    if missing:
        return surface_blocked_result(case, missing, surface)
    case_dir.mkdir(parents=True, exist_ok=True)
    if case.mode == "character-native":
        return execute_character_native(client, case, case_dir, run_id, timeout, ledger)
    if case.mode == "character-ccv2":
        return execute_character_import_case(client, case, case_dir, run_id, timeout, ledger, spec="chara_card_v2", spec_version="2.0")
    if case.mode == "character-ccv3":
        return execute_character_import_case(client, case, case_dir, run_id, timeout, ledger, spec="chara_card_v3", spec_version="3.0")
    if case.mode == "character-png":
        return execute_character_png(client, case, case_dir, run_id, timeout, ledger)
    if case.mode == "persona-roundtrip":
        return execute_persona_roundtrip(client, case, case_dir, run_id, timeout, ledger)
    raise RuntimeError(f"Unknown case mode: {case.mode}")


def summarize_results(results: list[dict[str, Any]], planned: int) -> dict[str, Any]:
    passed = [item["key"] for item in results if item.get("passed") is True]
    blocked = [item["key"] for item in results if item.get("status") == "blocked"]
    failed = [item["key"] for item in results if item.get("status") not in {"passed", "blocked"}]
    surface_blocked = [item["key"] for item in results if item.get("failureClass") == "surface_blocked"]
    return {
        "plannedCases": planned,
        "completedCases": len(results),
        "passedCases": passed,
        "blockedCases": blocked,
        "surfaceBlockedCases": surface_blocked,
        "failedCases": failed,
        "runnerFailures": [item["key"] for item in results if item.get("failureClass") == "runner_or_infrastructure"],
        "productBehaviorFailures": [item["key"] for item in results if item.get("failureClass") == "product_behavior"],
        "passedCount": len(passed),
        "blockedCount": len(blocked),
        "failedCount": len(failed),
        "duplicatePersistentIds": [],
        "overallStatus": (
            "passed"
            if len(passed) == planned and not blocked and not failed
            else "blocked"
            if blocked and not failed
            else "failed"
        ),
    }


def execute_live(args: argparse.Namespace) -> int:
    run_stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_id = f"ARM{run_stamp.replace('-', '')}{secrets.token_hex(4).upper()}"
    artifact_dir = (
        Path(args.artifact_dir).expanduser().resolve()
        if args.artifact_dir
        else ROOT.parent.parent.parent / "artifacts" / "tavo-validation" / f"{run_stamp}-asset-roundtrip-matrix"
    )
    artifact_lock = create_artifact_lock(artifact_dir)
    client: TavoMcp | None = None
    surface: SurfaceReport | None = None
    results: list[dict[str, Any]] = []
    ledger: dict[str, Any] = {}
    started_at = now_utc()
    all_cases = build_cases()
    cases = select_cases(all_cases, str(getattr(args, "case_keys", "") or ""))
    full_matrix_selection = len(cases) == len(all_cases)
    validate_case_plan(cases)
    plan = plan_record(run_id, cases, full_matrix_selection=full_matrix_selection)
    script_hash = hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest()
    manifest_path = artifact_dir / "run-manifest.json"
    durable_json(artifact_dir / "plan.json", plan)
    manifest = validation_manifest(
        run_id=run_id,
        artifact_dir=artifact_dir,
        plan_hash=stable_hash(plan),
        script_hash=script_hash,
        cases=cases,
        status="starting",
        started_at=started_at,
        finished_at=None,
        surface={},
        summary={},
        blocked_cases=[],
        results=[],
    )
    durable_json(manifest_path, manifest)
    try:
        endpoint = load_endpoint(args.endpoint_json)
        url = args.url or str(endpoint.get("url") or "")
        auth = args.auth or str(endpoint.get("auth") or "")
        if not url:
            raise RuntimeError("No Tavo MCP URL was supplied.")
        client = TavoMcp(url, auth)
        surface_dir = artifact_dir / "surface"
        surface = read_surface(client, surface_dir)
        ledger_path = artifact_dir / "ownership-ledger.json"
        ledger = load_ledger(ledger_path, run_id)
        manifest["status"] = "running"
        manifest["surface"] = surface.raw
        durable_json(manifest_path, manifest)
        for case in cases:
            case_dir = artifact_dir / "cases" / case.key
            append_event(artifact_dir / "events.jsonl", {"event": "case-start", "case": case.key, "at": now_utc()})
            try:
                result = execute_case(client, case, case_dir, run_id, int(args.per_call_timeout), ledger, surface)
            except BaseException as exc:  # noqa: BLE001
                result = {
                    "key": case.key,
                    "family": case.family,
                    "mode": case.mode,
                    "passed": False,
                    "status": "failed_runner_or_infrastructure",
                    "failureClass": "runner_or_infrastructure",
                    "usableAsEvidence": False,
                    "runnerInfrastructureFailures": [repr(exc)],
                    "traceback": traceback.format_exc(),
                }
            results.append(result)
            append_event(
                artifact_dir / "events.jsonl",
                {"event": "case-finish", "case": case.key, "status": result["status"], "at": now_utc()},
            )
            manifest["results"] = results
            manifest["summary"] = summarize_results(results, len(cases))
            manifest["blockedCases"] = manifest["summary"]["blockedCases"]
            manifest["countsTowardKpi"] = manifest["summary"]["overallStatus"] == "passed" and full_matrix_selection
            manifest["status"] = manifest["summary"]["overallStatus"]
            durable_json(manifest_path, manifest)
    except BaseException as exc:  # noqa: BLE001
        manifest["status"] = "failed_runner_or_infrastructure" if manifest.get("status") != "blocked" else manifest["status"]
        manifest["executionException"] = repr(exc)
        manifest["executionTraceback"] = traceback.format_exc()
    finally:
        summary = summarize_results(results, len(cases))
        if manifest.get("executionException") and not results:
            final_status = "failed_runner_or_infrastructure"
        elif summary["overallStatus"] == "blocked":
            final_status = "blocked"
        elif summary["overallStatus"] == "passed":
            final_status = "passed"
        elif manifest.get("executionException"):
            final_status = "failed_runner_or_infrastructure"
        else:
            final_status = "failed"
        if ledger:
            save_ledger(artifact_dir / "ownership-ledger.json", ledger)
        manifest["finishedAt"] = now_utc()
        manifest["summary"] = summary
        manifest["blockedCases"] = manifest["summary"]["blockedCases"]
        manifest["results"] = results
        manifest["countsTowardKpi"] = manifest["summary"]["overallStatus"] == "passed" and full_matrix_selection
        manifest["status"] = final_status
        durable_json(manifest_path, manifest)
        artifact_lock.close()
    print(
        json.dumps(
            {
                "artifactDir": str(artifact_dir),
                "runId": run_id,
                "status": manifest["status"],
                "countsTowardKpi": manifest["countsTowardKpi"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if manifest["status"] == "passed" else 1


def self_check() -> dict[str, Any]:
    cases = build_cases()
    validate_case_plan(cases)
    card = build_character_card("SELF-CHECK")
    persona = build_persona_payload("SELF-CHECK")
    if card["spec"] != "chara_card_v2" or card["data"]["character_book"]["entries"][0]["keys"] == []:
        raise RuntimeError("character payload sanity check failed")
    if not persona["avatar"].startswith("data:image/png;base64,"):
        raise RuntimeError("persona payload sanity check failed")
    png = make_base_png()
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("base PNG sanity check failed")
    with open(STATIC_SURFACE_DUMP, "r", encoding="utf-8") as handle:
        surface_dump = json.load(handle)
    surface_index_path = ROOT / "assets" / "schemas" / "mcp-surface-index-0.91.0-20260710.json"
    with open(surface_index_path, "r", encoding="utf-8") as handle:
        surface_index = json.load(handle)
    return {
        "ok": True,
        "plan": {
            "caseCount": len(cases),
            "caseKeys": [case.key for case in cases],
        },
        "staticSurface": {
            "toolCount": surface_index.get("summary", {}).get("toolCount", 0),
            "serverInfo": surface_dump.get("serverInfo", surface_index.get("serverInfo", {})),
        },
        "character": {"hash": stable_hash(card), "name": card["data"]["name"]},
        "persona": {"hash": stable_hash(persona), "name": persona["name"]},
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a retained Tavo asset roundtrip matrix.")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--self-check", action="store_true", help="Run offline structural checks only.")
    actions.add_argument("--print-plan", action="store_true", help="Print the offline plan without contacting the surface.")
    actions.add_argument("--execute", action="store_true", help="Explicitly authorize live MCP execution.")
    parser.add_argument("--endpoint-json", default=DEFAULT_ENDPOINT)
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--case-keys", default="", help="Comma-separated case keys to run.")
    parser.add_argument("--per-call-timeout", type=int, default=180)
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    cases = build_cases()
    selected = select_cases(cases, str(getattr(args, "case_keys", "") or ""))
    validate_case_plan(selected)
    run_id = current_utc_name("ARM")
    plan = plan_record(run_id, selected, full_matrix_selection=len(selected) == len(cases))
    if args.self_check:
        print(json.dumps(self_check(), ensure_ascii=False, indent=2))
        return 0
    if args.print_plan:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.execute:
        return execute_live(args)
    raise RuntimeError("No action selected")


if __name__ == "__main__":
    raise SystemExit(main())
