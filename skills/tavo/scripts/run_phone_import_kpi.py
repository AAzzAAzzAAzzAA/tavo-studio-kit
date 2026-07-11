#!/usr/bin/env python3
"""Import and verify 50 real Tavo assets on the connected phone.

The KPI is intentionally narrow: only character/lorebook/regex/preset imports
and plugin installs count. Chat creation, personas, messages, and dry-runs do
not count as imported files. Runs are journaled and resumable.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_phone_kpi_batch import (  # noqa: E402
    TavoMcp,
    capture_phone,
    file_info,
    load_endpoint,
    ok_response,
    redact,
    text_payload,
)


KIND_COUNTS = {
    "character": 15,
    "lorebook": 10,
    "regex": 10,
    "preset": 10,
    "plugin": 5,
}
TARGET_IMPORTS = sum(KIND_COUNTS.values())


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact(event), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def response_payload(response: dict[str, Any]) -> dict[str, Any]:
    parsed = text_payload(response)
    return parsed if isinstance(parsed, dict) else {}


def response_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = response_payload(response)
    items = parsed.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def tool_call(
    client: TavoMcp,
    step_dir: Path,
    filename: str,
    tool: str,
    arguments: dict[str, Any],
    timeout: int = 180,
) -> dict[str, Any]:
    response = client.tool(tool, arguments, timeout=timeout)
    atomic_json(step_dir / filename, response)
    return response


def character_payload(name: str, token: str, index: int) -> dict[str, Any]:
    roles = [
        ("档案修复师", "谨慎、耐心、会追问证据", "雨夜档案馆"),
        ("轨道调查员", "冷静、敏锐、行动优先", "停运的环城车站"),
        ("社区医生", "温和、务实、边界清楚", "临时诊疗站"),
        ("舞台监督", "机警、幽默、善于调度", "停电后的旧剧场"),
        ("灾后测绘员", "克制、精确、保护同伴", "封锁中的旧城区"),
    ]
    role, personality, setting = roles[(index - 1) % len(roles)]
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": name,
            "description": (
                f"{{{{char}}}} 是{role}，工作标记为 {token}。"
                "TA 会先区分事实、推测与未知，再给出可以执行的下一步。"
            ),
            "personality": personality,
            "scenario": f"{setting}。{{{{char}}}} 与 {{{{user}}}} 正在核对一条会改变行动路线的新线索。",
            "first_mes": "{{char}}把记录页推到{{user}}面前：先告诉我你亲眼看见了什么，再说你认为它意味着什么。",
            "mes_example": (
                "<START>\n"
                "{{user}}: 门锁没有损坏，但档案不见了。\n"
                "{{char}}: 那就先查钥匙、值班记录和门内摄像，不把没有破坏痕迹直接等同于熟人作案。"
            ),
            "creator_notes": f"Retained real-phone import evidence {token}.",
            "system_prompt": (
                f"Stay in character. Hidden validation fact: {token}. "
                "Give concrete observations and actions; never answer with a bare acknowledgement."
            ),
            "post_history_instructions": "Use 2-5 focused sentences and preserve causal details.",
            "alternate_greetings": [
                "{{char}}关掉录音笔：从头说，别省略你觉得不重要的部分。",
                "{{char}}看向{{user}}：我们先做一件能被复核的事。",
            ],
            "tags": ["codex", "retained-validation", "real-import"],
            "creator": "Codex",
            "character_version": "1.0.0",
            "extensions": {},
        },
    }


def lorebook_payload(name: str, token: str, index: int) -> dict[str, Any]:
    trigger = f"雾桥-{index:02d}"
    fact = f"{token}-FACT"
    return {
        "name": name,
        "description": f"Retained worldbook with trigger/control evidence {token}.",
        "entries": [
            {
                "keys": [trigger, f"桥灯-{index:02d}"],
                "comment": f"triggered fact {token}",
                "content": (
                    f"当对话出现 {trigger} 时，必须记住事实码 {fact}："
                    f"第 {index} 座雾桥只在潮位最低时开放，绿色桥灯表示结构不安全。"
                ),
                "enabled": True,
                "constant": False,
                "selective": True,
                "order": 100 + index,
                "probability": 100,
            },
            {
                "keys": [f"封存柜-{index:02d}"],
                "comment": "secondary rule",
                "content": f"封存柜-{index:02d} 需要两名见证者同时登记，记录号为 {token}-CABINET。",
                "enabled": True,
                "constant": False,
                "selective": True,
                "order": 200 + index,
                "probability": 100,
            },
        ],
    }


def regex_payload(name: str, token: str, index: int) -> dict[str, Any]:
    prefix = f"RAW{index:02d}"
    replacement = f"CLEANED-{token}"
    return {
        "name": name,
        "entries": [
            {
                "scriptName": f"Replace {prefix} wrapper with retained evidence",
                "findRegex": rf"\[{prefix}\]",
                "replaceString": replacement,
                "trimStrings": [],
                "placement": [2],
                "disabled": False,
                "markdownOnly": False,
                "promptOnly": False,
                "runOnEdit": True,
                "substituteRegex": 0,
            }
        ],
    }


def preset_payload(name: str, token: str, index: int) -> dict[str, Any]:
    instruction = (
        f"Preset evidence {token}. When the user asks for a three-part audit, "
        f"start with PRESET-{index:02d}-{token} and label the parts OBSERVE, QUESTION, VERIFY."
    )
    prompts = [
            {
                "identifier": "main",
                "name": "Main Prompt",
                "system_prompt": True,
                "marker": False,
                "content": (
                    "Write {{char}}'s next reply in a fictional chat between {{char}} and {{user}}. "
                    + instruction
                ),
                "role": "system",
                "injection_position": 0,
                "injection_depth": 4,
                "forbid_overrides": True,
            },
            {
                "identifier": "worldInfoBefore",
                "name": "Lorebook Before",
                "system_prompt": True,
                "marker": True,
            },
            {
                "identifier": "personaDescription",
                "name": "Persona Description",
                "system_prompt": True,
                "marker": True,
            },
            {
                "identifier": "charDescription",
                "name": "Char Description",
                "system_prompt": True,
                "marker": True,
            },
            {
                "identifier": "charPersonality",
                "name": "Char Personality",
                "system_prompt": True,
                "marker": True,
            },
            {
                "identifier": "scenario",
                "name": "Scenario",
                "system_prompt": True,
                "marker": True,
            },
            {
                "identifier": "worldInfoAfter",
                "name": "Lorebook After",
                "system_prompt": True,
                "marker": True,
            },
            {
                "identifier": "dialogueExamples",
                "name": "Chat Examples",
                "system_prompt": True,
                "marker": True,
            },
            {
                "identifier": "chatHistory",
                "name": "Chat History",
                "system_prompt": True,
                "marker": True,
            },
        ]
    order = [{"identifier": prompt["identifier"], "enabled": True} for prompt in prompts]
    return {
        "name": name,
        "impersonation_prompt": "[Write only as {{user}}.]",
        "new_chat_prompt": "[Start a new Chat]",
        "new_group_chat_prompt": "[Start a new group chat. Group members: {{group}}]",
        "new_example_chat_prompt": "[Example Chat]",
        "continue_nudge_prompt": "[Continue without repeating the prior text.]",
        "scenario_format": "{{scenario}}",
        "personality_format": "{{personality}}",
        "group_nudge_prompt": "[Write the next reply only as {{char}}.]",
        "wi_format": "{0}",
        "prompts": prompts,
        "prompt_order": [{"character_id": 100001, "order": order}],
    }


def plugin_sources(plugin_id: str, name: str, token: str, index: int) -> dict[str, str]:
    action_id = f"evidence-{index:02d}"
    fragment_id = f"panel-{index:02d}"
    manifest = {
        "id": plugin_id,
        "name": name,
        "version": "1.0.0",
        "specVersion": 1,
        "author": "Codex",
        "description": f"Retained real-phone plugin import evidence {token}.",
        "permissions": ["input", "variable"],
        "entry": "entry.js",
        "contributes": {
            "inputActions": [{"id": action_id, "label": f"Codex Evidence {index:02d}"}],
            "htmlFragments": [
                {"id": fragment_id, "src": "ui/panel.html", "mount": "/chat/body/end"}
            ],
            "settings": {
                "schema": [
                    {"type": "info", "text": f"Evidence token {token}"},
                    {"key": "enabled", "type": "switch", "label": "Enabled", "default": True},
                ]
            },
        },
    }
    action_prompt = (
        f"Plugin action {index:02d} executed. Explain one concrete way to verify a UI action. "
        f"Challenge token {token}."
    )
    actions = (
        f"tavo.plugin.onInputAction('{action_id}', async () => {{\n"
        f"  tavo.set('codex_plugin_{index:02d}', '{token}');\n"
        f"  await tavo.input.set({json.dumps(action_prompt, ensure_ascii=False)});\n"
        "});\n"
    )
    panel = (
        f"<section data-codex-plugin=\"{token}\" style=\"border:1px solid #168;padding:8px;margin:6px\">"
        f"<strong>Plugin evidence {index:02d}</strong><span>{token}</span></section>\n"
    )
    return {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        "entry.js": actions,
        "ui/panel.html": panel,
    }


def materialize_plan(artifact_dir: Path, marker: str) -> list[dict[str, Any]]:
    plan_path = artifact_dir / "import-plan.json"
    if plan_path.exists():
        plan = load_json(plan_path)
        if not isinstance(plan, list) or len(plan) != TARGET_IMPORTS:
            raise RuntimeError("Existing import-plan.json does not contain exactly 50 items.")
        upgraded = False
        for item in plan:
            kind = item.get("kind")
            if kind not in {"regex", "preset"} or "-V2-" in str(item.get("evidenceMarker") or ""):
                continue
            index = int(item["index"])
            item["name"] = f"Codex Final {kind.title()} {marker} V2 {index:02d}"
            item["evidenceMarker"] = f"{marker}-{kind.upper()}-V2-{index:02d}"
            payload = {"regex": regex_payload, "preset": preset_payload}[kind](
                item["name"], item["evidenceMarker"], index
            )
            Path(item["sourcePath"]).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            upgraded = True
        if upgraded:
            atomic_json(plan_path, plan)
        return plan

    plan: list[dict[str, Any]] = []
    ordinal = 0
    for kind, count in KIND_COUNTS.items():
        for index in range(1, count + 1):
            ordinal += 1
            variant = "-V2" if kind in {"regex", "preset"} else ""
            evidence_marker = f"{marker}-{kind.upper()}{variant}-{index:02d}"
            display_kind = kind.title()
            name = f"Codex Final {display_kind} {marker}{' V2' if variant else ''} {index:02d}"
            item: dict[str, Any] = {
                "ordinal": ordinal,
                "kind": kind,
                "index": index,
                "name": name,
                "evidenceMarker": evidence_marker,
            }
            if kind == "plugin":
                plugin_id = f"codex.final.{marker.lower()}.{index:02d}"
                source_dir = artifact_dir / "source-files" / kind / f"{index:02d}-{plugin_id}"
                for relative, content in plugin_sources(plugin_id, name, evidence_marker, index).items():
                    path = source_dir / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                item.update({"pluginId": plugin_id, "sourcePath": str(source_dir)})
            else:
                payload = {
                    "character": character_payload,
                    "lorebook": lorebook_payload,
                    "regex": regex_payload,
                    "preset": preset_payload,
                }[kind](name, evidence_marker, index)
                source_path = artifact_dir / "source-files" / kind / f"{index:02d}-{kind}.json"
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                item["sourcePath"] = str(source_path)
            plan.append(item)
    atomic_json(plan_path, plan)
    return plan


def exact_search(client: TavoMcp, step_dir: Path, item: dict[str, Any]) -> list[dict[str, Any]]:
    kind = item["kind"]
    if kind == "plugin":
        response = tool_call(
            client,
            step_dir,
            "search.json",
            "tavo_plugin_search",
            {"query": item["pluginId"], "match": "exact", "limit": 10},
        )
    else:
        response = tool_call(
            client,
            step_dir,
            "search.json",
            f"tavo_{kind}_search",
            {"query": item["name"], "match": "exact", "limit": 10},
        )
    if not ok_response(response):
        raise RuntimeError(f"Exact search failed for {item['kind']} item {item['ordinal']}.")
    return response_items(response)


def object_id_from(kind: str, response: dict[str, Any]) -> int | str | None:
    parsed = response_payload(response)
    if kind == "plugin":
        return parsed.get("pluginId") or parsed.get("id")
    aliases = {
        "character": "characterId",
        "lorebook": "lorebookId",
        "regex": "regexId",
        "preset": "presetId",
    }
    return parsed.get(aliases[kind]) or parsed.get("id")


def readback(
    client: TavoMcp,
    step_dir: Path,
    item: dict[str, Any],
    object_id: int | str,
) -> dict[str, Any]:
    if item["kind"] == "plugin":
        return tool_call(
            client,
            step_dir,
            "readback.json",
            "tavo_plugin_get",
            {"pluginId": str(object_id)},
        )
    return tool_call(
        client,
        step_dir,
        "readback.json",
        f"tavo_{item['kind']}_get",
        {"id": int(object_id)},
    )


def validate_readback(
    client: TavoMcp,
    step_dir: Path,
    item: dict[str, Any],
    object_id: int | str,
    response: dict[str, Any],
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    parsed = response_payload(response)
    rendered = json.dumps(parsed, ensure_ascii=False)
    if not ok_response(response):
        failures.append("readback MCP response was not successful")
    if item["name"] not in rendered:
        failures.append("readback did not preserve the asset name")
    if item["evidenceMarker"] not in rendered:
        failures.append("readback did not preserve the unique evidence token")
    readback_id = parsed.get("pluginId") if item["kind"] == "plugin" else parsed.get("id")
    if str(readback_id) != str(object_id):
        failures.append("readback object id did not match imported object id")

    if item["kind"] == "character":
        data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
        macro_text = " ".join(str(data.get(field) or "") for field in ("description", "scenario", "first_mes"))
        if "{{char}}" not in macro_text or "{{user}}" not in macro_text:
            failures.append("character macro fields did not preserve {{char}} and {{user}}")
    elif item["kind"] == "lorebook":
        entries = parsed.get("entries")
        if not isinstance(entries, list) or len(entries) < 2:
            failures.append("lorebook readback did not preserve both real entries")
    elif item["kind"] == "regex":
        index = int(item["index"])
        prefix = f"RAW{index:02d}"
        input_text = f"Before [{prefix}] After"
        expected = f"CLEANED-{item['evidenceMarker']}"
        test = tool_call(
            client,
            step_dir,
            "regex-test.json",
            "tavo_regex_test",
            {
                "findRegex": rf"\[{prefix}\]",
                "replaceString": expected,
                "input": input_text,
                "caseSensitive": True,
            },
        )
        test_rendered = json.dumps(response_payload(test), ensure_ascii=False)
        if not ok_response(test) or expected not in test_rendered or f"[{prefix}]" in test_rendered:
            failures.append("regex tool did not produce the expected transformed output")
    elif item["kind"] == "preset":
        entries = parsed.get("entries")
        if not isinstance(entries, list) or not any(
            isinstance(entry, dict) and item["evidenceMarker"] in str(entry.get("content") or "")
            for entry in entries
        ):
            failures.append("preset custom prompt entry was not preserved")
    elif item["kind"] == "plugin":
        runtime = tool_call(
            client,
            step_dir,
            "runtime-contributions.json",
            "tavo_plugin_get_runtime_contributions",
            {},
        )
        runtime_text = json.dumps(response_payload(runtime), ensure_ascii=False)
        if not ok_response(runtime) or item["pluginId"] not in runtime_text:
            failures.append("plugin runtime contributions did not include the installed plugin")
    return not failures, failures


def import_regular(
    client: TavoMcp,
    step_dir: Path,
    item: dict[str, Any],
    run_id: str,
) -> tuple[int | None, bool]:
    source_path = Path(item["sourcePath"])
    payload = load_json(source_path)
    source_fingerprint = str(file_info(source_path)["sha256"])[:16]
    kind = item["kind"]
    argument_key = {"character": "card", "lorebook": "lorebook", "regex": "regex", "preset": "preset"}[kind]
    tool = {"character": "tavo_character_import_card", "lorebook": "tavo_lorebook_import", "regex": "tavo_regex_import", "preset": "tavo_preset_import"}[kind]
    dry = tool_call(
        client,
        step_dir,
        "dry-run.json",
        tool,
        {
            argument_key: payload,
            "dryRun": True,
            "clientRequestId": f"{run_id}-{kind}-{item['index']:02d}-{source_fingerprint}-dry",
        },
    )
    if not ok_response(dry):
        return None, False
    actual = tool_call(
        client,
        step_dir,
        "actual.json",
        tool,
        {
            argument_key: payload,
            "dryRun": False,
            "clientRequestId": f"{run_id}-{kind}-{item['index']:02d}-{source_fingerprint}-actual",
        },
    )
    object_id = object_id_from(kind, actual)
    return int(object_id) if isinstance(object_id, int) or (isinstance(object_id, str) and object_id.isdigit()) else None, ok_response(actual)


def import_plugin(
    client: TavoMcp,
    step_dir: Path,
    item: dict[str, Any],
) -> tuple[str | None, bool]:
    source_dir = Path(item["sourcePath"])
    files: list[dict[str, str]] = []
    for path in sorted(source_dir.rglob("*")):
        if path.is_file() and path.name != "plugin.tpg":
            files.append({"path": path.relative_to(source_dir).as_posix(), "text": path.read_text(encoding="utf-8")})
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    validate = tool_call(client, step_dir, "validate-manifest.json", "tavo_plugin_validate_manifest", {"manifest": manifest})
    package_dry = tool_call(
        client,
        step_dir,
        "package-dry-run.json",
        "tavo_plugin_package",
        {"files": files, "includeZipBase64": True, "dryRun": True},
    )
    package_actual = tool_call(
        client,
        step_dir,
        "package-actual.json",
        "tavo_plugin_package",
        {"files": files, "includeZipBase64": True, "dryRun": False},
    )
    package_payload = response_payload(package_actual)
    zip_base64 = package_payload.get("zipBase64")
    if not all(ok_response(value) for value in (validate, package_dry, package_actual)) or not isinstance(zip_base64, str):
        return None, False
    (source_dir / "plugin.tpg").write_bytes(base64.b64decode(zip_base64))
    install_dry = tool_call(
        client,
        step_dir,
        "install-dry-run.json",
        "tavo_plugin_install",
        {"zipBase64": zip_base64, "dryRun": True},
    )
    install_actual = tool_call(
        client,
        step_dir,
        "install-actual.json",
        "tavo_plugin_install",
        {"zipBase64": zip_base64, "dryRun": False},
    )
    return item["pluginId"], ok_response(install_dry) and ok_response(install_actual)


def run_item(
    client: TavoMcp,
    artifact_dir: Path,
    item: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    step_dir = artifact_dir / "imports" / f"{item['ordinal']:03d}-{item['kind']}-{item['index']:02d}"
    step_dir.mkdir(parents=True, exist_ok=True)
    result_path = step_dir / "result.json"
    matches = exact_search(client, step_dir, item)
    if len(matches) > 1:
        result = {**item, "passed": False, "countable": False, "failures": ["multiple exact-name objects found; refusing ambiguous reconciliation"]}
        atomic_json(result_path, result)
        return result

    object_id: int | str | None = None
    reconciled = False
    actual_ok = False
    import_error: str | None = None
    if matches:
        match = matches[0]
        object_id = match.get("pluginId") if item["kind"] == "plugin" else match.get("id")
        reconciled = True
        actual_ok = object_id is not None
    else:
        try:
            if item["kind"] == "plugin":
                object_id, actual_ok = import_plugin(client, step_dir, item)
            else:
                object_id, actual_ok = import_regular(client, step_dir, item, run_id)
        except Exception as exc:  # noqa: BLE001
            import_error = repr(exc)
            atomic_json(
                step_dir / "import-exception.json",
                {"error": import_error, "traceback": traceback.format_exc()},
            )

    if object_id is None:
        # A write may have completed despite a transport error. Reconcile once by exact name/id.
        matches = exact_search(client, step_dir, item)
        if len(matches) == 1:
            object_id = matches[0].get("pluginId") if item["kind"] == "plugin" else matches[0].get("id")
            reconciled = True
            actual_ok = object_id is not None

    failures: list[str] = []
    readback_ok = False
    semantic_ok = False
    if object_id is None:
        failures.append("import/install produced no stable object id")
        if import_error:
            failures.append(f"write transport error before reconciliation: {import_error}")
    else:
        read = readback(client, step_dir, item, object_id)
        readback_ok = ok_response(read)
        semantic_ok, semantic_failures = validate_readback(client, step_dir, item, object_id, read)
        failures.extend(semantic_failures)

    source = Path(item["sourcePath"])
    source_info = file_info(source)
    minimum_bytes = 700 if item["kind"] in {"character", "preset", "plugin"} else 350
    real_source_ok = source_info["fileCount"] >= (4 if item["kind"] == "plugin" else 1) and source_info["bytes"] >= minimum_bytes
    if not real_source_ok:
        failures.append("source artifact was too small or incomplete to count as a real file")

    passed = bool(actual_ok and readback_ok and semantic_ok and real_source_ok and not failures)
    result = {
        **item,
        "finishedAt": now_utc(),
        "objectId": object_id,
        "actualOk": actual_ok,
        "readbackOk": readback_ok,
        "semanticOutputOk": semantic_ok,
        "realSourceOk": real_source_ok,
        "sourceInfo": source_info,
        "reconciledExisting": reconciled,
        "passed": passed,
        "countable": passed,
        "failures": failures,
        "artifactDir": str(step_dir),
    }
    atomic_json(result_path, result)
    return result


def progress(results: list[dict[str, Any]]) -> dict[str, Any]:
    counted = [result for result in results if result.get("countable")]
    kind_counts = {
        kind: sum(1 for result in counted if result.get("kind") == kind)
        for kind in KIND_COUNTS
    }
    unique_objects = {(str(result.get("kind")), str(result.get("objectId"))) for result in counted}
    return {
        "attempted": len(results),
        "counted": len(counted),
        "kindCounts": kind_counts,
        "uniqueCountedObjects": len(unique_objects),
        "failedOrdinals": [result.get("ordinal") for result in results if not result.get("passed")],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import and verify exactly 50 real Tavo test files.")
    parser.add_argument("--endpoint-json", default="/tmp/tavo_mcp_endpoint.json")
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--device", default="")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    args = parser.parse_args()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = (
        Path(args.artifact_dir).expanduser()
        if args.artifact_dir
        else ROOT.parent.parent.parent / "artifacts" / "tavo-validation" / f"{stamp}-strict-import-kpi"
    )
    manifest_path = artifact_dir / "run-manifest.json"
    if artifact_dir.exists() and any(artifact_dir.iterdir()) and not args.resume:
        print("Artifact directory already exists and is non-empty; pass --resume to continue it.", file=sys.stderr)
        return 2
    if args.resume and not manifest_path.exists():
        print("--resume requires an existing run-manifest.json.", file=sys.stderr)
        return 2
    artifact_dir.mkdir(parents=True, exist_ok=True)

    if manifest_path.exists():
        manifest = load_json(manifest_path)
        marker = str(manifest["marker"])
        run_id = str(manifest["runId"])
    else:
        marker = f"CF{stamp.replace('-', '')}"
        run_id = f"codex-final-import-{stamp}"
        manifest = {
            "case": "strict-real-file-import-kpi",
            "status": "planned" if args.plan_only else "running",
            "startedAt": now_utc(),
            "marker": marker,
            "runId": run_id,
            "targets": {"countedImports": TARGET_IMPORTS, "kindCounts": KIND_COUNTS},
            "countingContract": (
                "Only actual character/lorebook/regex/preset imports and plugin installs with a real local source, "
                "stable unique object id, live readback, preserved token, and kind-specific semantic output count."
            ),
            "retention": "leave-in-place",
            "countsTowardKpi": False,
        }
        atomic_json(manifest_path, manifest)

    plan = materialize_plan(artifact_dir, marker)
    if args.plan_only:
        checks = []
        for item in plan:
            info = file_info(Path(item["sourcePath"]))
            checks.append({"ordinal": item["ordinal"], "kind": item["kind"], "sourceInfo": info})
        atomic_json(artifact_dir / "plan-validation.json", checks)
        manifest.update({"status": "planned", "planItems": len(plan), "countsTowardKpi": False})
        atomic_json(manifest_path, manifest)
        print(f"artifact_dir={artifact_dir}")
        print(f"plan_items={len(plan)}")
        return 0

    endpoint = load_endpoint(args.endpoint_json)
    url = args.url or endpoint.get("url", "")
    auth = args.auth or endpoint.get("auth", "")
    if not url:
        print("No MCP URL found. Provide --url, TAVO_MCP_URL, or --endpoint-json.", file=sys.stderr)
        return 2
    client = TavoMcp(url, auth)
    events_path = artifact_dir / "events.jsonl"

    results: list[dict[str, Any]] = []
    try:
        manifest.update({"status": "running", "resumedAt": now_utc() if args.resume else None})
        atomic_json(manifest_path, manifest)
        if not (artifact_dir / "phone-before").exists():
            capture_code = capture_phone(args.device, artifact_dir, "phone-before")
            if capture_code != 0:
                raise RuntimeError(f"phone-before capture failed with exit code {capture_code}")
        initialize = client.initialize()
        tools_list = client.rpc("tools/list", {})
        atomic_json(artifact_dir / "mcp-initialize.json", initialize)
        atomic_json(artifact_dir / "mcp-tools-list.json", tools_list)
        server_info = initialize.get("result", {}).get("serverInfo", {}) if isinstance(initialize.get("result"), dict) else {}
        manifest["serverInfo"] = server_info

        for item in plan:
            append_event(events_path, {"at": now_utc(), "event": "item-start", "ordinal": item["ordinal"], "kind": item["kind"]})
            try:
                result = run_item(client, artifact_dir, item, run_id)
            except Exception as exc:  # noqa: BLE001
                step_dir = artifact_dir / "imports" / f"{item['ordinal']:03d}-{item['kind']}-{item['index']:02d}"
                result = {
                    **item,
                    "finishedAt": now_utc(),
                    "passed": False,
                    "countable": False,
                    "failures": [repr(exc)],
                    "traceback": traceback.format_exc(),
                    "artifactDir": str(step_dir),
                }
                atomic_json(step_dir / "result.json", result)
            results.append(result)
            current = progress(results)
            manifest.update({"progress": current, "lastCompletedOrdinal": item["ordinal"], "countsTowardKpi": False})
            atomic_json(manifest_path, manifest)
            append_event(events_path, {"at": now_utc(), "event": "item-finish", "ordinal": item["ordinal"], "passed": result.get("passed")})
            print(
                "import_kpi",
                f"{item['ordinal']:03d}/050",
                item["kind"],
                "passed=" + str(bool(result.get("passed"))).lower(),
                f"counted={current['counted']}/50",
                flush=True,
            )
            if not result.get("passed") and not args.continue_on_failure:
                append_event(
                    events_path,
                    {
                        "at": now_utc(),
                        "event": "fail-fast",
                        "ordinal": item["ordinal"],
                        "failures": result.get("failures", []),
                    },
                )
                break

        atomic_json(artifact_dir / "import-results.json", results)
        final_progress = progress(results)
        passed = (
            final_progress["counted"] == TARGET_IMPORTS
            and final_progress["uniqueCountedObjects"] == TARGET_IMPORTS
            and final_progress["kindCounts"] == KIND_COUNTS
            and not final_progress["failedOrdinals"]
        )
        capture_code = capture_phone(args.device, artifact_dir, "phone-after")
        if capture_code != 0:
            passed = False
        manifest.update(
            {
                "finishedAt": now_utc(),
                "status": "passed" if passed else "failed",
                "progress": final_progress,
                "countsTowardKpi": passed,
                "artifacts": [
                    "import-plan.json",
                    "source-files/",
                    "imports/",
                    "import-results.json",
                    "events.jsonl",
                    "phone-before/",
                    "phone-after/",
                    "mcp-initialize.json",
                    "mcp-tools-list.json",
                ],
            }
        )
        atomic_json(manifest_path, manifest)
        print(f"artifact_dir={artifact_dir}")
        print(f"status={manifest['status']}")
        print(f"counted_imports={final_progress['counted']}")
        return 0 if passed else 1
    except KeyboardInterrupt:
        manifest.update(
            {
                "pausedAt": now_utc(),
                "status": "paused",
                "countsTowardKpi": False,
                "progress": progress(results),
                "pauseReason": "keyboard-interrupt",
            }
        )
        atomic_json(manifest_path, manifest)
        append_event(events_path, {"at": now_utc(), "event": "paused", "reason": "keyboard-interrupt"})
        return 130
    except Exception as exc:  # noqa: BLE001
        manifest.update(
            {
                "failedAt": now_utc(),
                "status": "failed",
                "countsTowardKpi": False,
                "progress": progress(results),
                "failure": repr(exc),
            }
        )
        atomic_json(manifest_path, manifest)
        atomic_json(artifact_dir / "fatal-exception.json", {"error": repr(exc), "traceback": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
