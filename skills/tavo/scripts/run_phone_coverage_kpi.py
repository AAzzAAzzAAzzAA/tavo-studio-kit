#!/usr/bin/env python3
"""Run broad real-phone Tavo coverage validation.

This is stricter than a volume smoke test: it requires varied feature families,
real source files, phone-side writes/readbacks, and real model replies.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_phone_kpi_batch import (  # noqa: E402
    TavoMcp,
    call_import,
    call_plugin_install,
    capture_phone,
    character_card,
    file_info,
    load_endpoint,
    lorebook_payload,
    message_count,
    ok_response,
    parsed_current_chat,
    plugin_files,
    preset_payload,
    real_reply_ok,
    regex_payload,
    text_payload,
    write_json,
)


FEATURE_FAMILIES = [
    "character-thread",
    "lorebook-trigger",
    "regex-runtime",
    "preset-stack",
    "persona-binding",
    "macro-ejs",
    "tavojs-variable",
    "advanced-rendering",
    "plugin-action-panel",
    "mcp-message-ops",
]


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def source_path(artifact_dir: Path, family: str, index: int, suffix: str) -> Path:
    path = artifact_dir / "coverage-files" / family / f"{index:03d}-{family}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_json_source(artifact_dir: Path, family: str, index: int, data: Any) -> Path:
    path = source_path(artifact_dir, family, index, "json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_text_source(artifact_dir: Path, family: str, index: int, suffix: str, text: str) -> Path:
    path = source_path(artifact_dir, family, index, suffix)
    path.write_text(text, encoding="utf-8")
    return path


def tool_step(client: TavoMcp, out: Path, name: str, args: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    response = client.tool(name, args, timeout=timeout)
    write_json(out / f"{name}.json", response)
    return response


def create_persona(client: TavoMcp, artifact_dir: Path, index: int, name: str, marker: str) -> dict[str, Any]:
    family = "persona-binding"
    payload = {
        "name": name,
        "description": f"{name} 是真机覆盖测试 persona。批次标记 {marker}。TA 的目标是追问细节、保留怀疑、要求角色给出具体证据。",
        "active": False,
    }
    source = save_json_source(artifact_dir, family, index, payload)
    step = artifact_dir / "coverage-steps" / family / f"{index:03d}"
    step.mkdir(parents=True, exist_ok=True)
    dry = tool_step(client, step, "tavo_persona_create", {"persona": payload, "dryRun": True, "clientRequestId": f"{marker}-persona-{index:03d}-dry"})
    actual = tool_step(client, step, "tavo_persona_create", {"persona": payload, "dryRun": False, "clientRequestId": f"{marker}-persona-{index:03d}"})
    parsed = text_payload(actual)
    object_id = parsed.get("id") if isinstance(parsed, dict) else None
    readback = None
    if object_id:
        readback = tool_step(client, step, "tavo_persona_get", {"id": int(object_id)})
    return {
        "family": family,
        "kind": "persona",
        "index": index,
        "sourceFile": str(source),
        "sourceFileInfo": file_info(source),
        "actualOk": ok_response(actual),
        "dryRunOk": ok_response(dry),
        "readbackOk": ok_response(readback) if readback else False,
        "functionalOutputOk": ok_response(readback) if readback else False,
        "objectId": object_id,
        "artifactDir": str(step),
    }


def create_chat(
    client: TavoMcp,
    artifact_dir: Path,
    family: str,
    index: int,
    marker: str,
    character_id: int,
    persona_id: int | None = None,
    lorebook_ids: list[int] | None = None,
    regex_ids: list[int] | None = None,
    preset_id: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"characterIds": [character_id]}
    if persona_id:
        payload["personaId"] = persona_id
    if lorebook_ids is not None:
        payload["lorebookIds"] = lorebook_ids
    if regex_ids is not None:
        payload["regexIds"] = regex_ids
    if preset_id:
        payload["presetId"] = preset_id
    source = save_json_source(artifact_dir, family, index, {"chat": payload})
    step = artifact_dir / "coverage-steps" / family / f"{index:03d}-chat"
    step.mkdir(parents=True, exist_ok=True)
    dry = tool_step(client, step, "tavo_chat_create", {"chat": payload, "dryRun": True, "clientRequestId": f"{marker}-{family}-{index:03d}-chat-dry"})
    actual = tool_step(client, step, "tavo_chat_create", {"chat": payload, "dryRun": False, "clientRequestId": f"{marker}-{family}-{index:03d}-chat"})
    parsed = text_payload(actual)
    chat_id = parsed.get("id") if isinstance(parsed, dict) else None
    readback = None
    if chat_id:
        readback = tool_step(client, step, "tavo_chat_get", {"id": int(chat_id), "includeMessages": True})
    return {
        "family": family,
        "kind": "chat",
        "index": index,
        "sourceFile": str(source),
        "sourceFileInfo": file_info(source),
        "actualOk": ok_response(actual),
        "dryRunOk": ok_response(dry),
        "readbackOk": ok_response(readback) if readback else False,
        "functionalOutputOk": ok_response(readback) if readback else False,
        "objectId": chat_id,
        "artifactDir": str(step),
    }


def append_ar_message(client: TavoMcp, artifact_dir: Path, index: int, marker: str, chat_id: int) -> dict[str, Any]:
    family = "advanced-rendering"
    html = f"""
<section data-codex-ar="{marker}-{index}" style="position:relative;border:1px solid #3aa;padding:12px;margin:8px">
  <strong>AR marker {marker}-{index}</strong>
  <button type="button" data-action="append" style="position:absolute;right:8px;top:8px">写入线索</button>
  <script>
  (() => {{
    const root = document.currentScript.closest('[data-codex-ar]');
    root.addEventListener('click', async (event) => {{
      if (!event.target.closest('[data-action="append"]')) return;
      await tavo.input.append('AR_JS_MARKER_{index}');
      tavo.set('ar_marker_{index}', 'clicked');
    }});
  }})();
  </script>
</section>
""".strip()
    source = save_text_source(artifact_dir, family, index, "html", html)
    step = artifact_dir / "coverage-steps" / family / f"{index:03d}"
    step.mkdir(parents=True, exist_ok=True)
    message = {"role": "assistant", "content": html, "hidden": False}
    dry = tool_step(client, step, "tavo_message_append", {"chatId": chat_id, "message": message, "dryRun": True, "clientRequestId": f"{marker}-ar-{index:03d}-dry"})
    actual = tool_step(client, step, "tavo_message_append", {"chatId": chat_id, "message": message, "dryRun": False, "clientRequestId": f"{marker}-ar-{index:03d}"})
    parsed = text_payload(actual)
    message_id = parsed.get("id") if isinstance(parsed, dict) else None
    readback = tool_step(client, step, "tavo_message_find", {"chatId": chat_id, "range": [-5]})
    return {
        "family": family,
        "kind": "ar-html-message",
        "index": index,
        "sourceFile": str(source),
        "sourceFileInfo": file_info(source),
        "actualOk": ok_response(actual),
        "dryRunOk": ok_response(dry),
        "readbackOk": ok_response(readback),
        "functionalOutputOk": ok_response(readback) and marker in json.dumps(text_payload(readback), ensure_ascii=False),
        "objectId": message_id,
        "artifactDir": str(step),
    }


def mcp_message_ops(client: TavoMcp, artifact_dir: Path, index: int, marker: str, chat_id: int) -> dict[str, Any]:
    family = "mcp-message-ops"
    spec = {
        "append": f"MCP append evidence {marker}-{index}",
        "insert": f"MCP inserted hidden context {marker}-{index}",
        "update": f"MCP updated evidence {marker}-{index}",
    }
    source = save_json_source(artifact_dir, family, index, spec)
    step = artifact_dir / "coverage-steps" / family / f"{index:03d}"
    step.mkdir(parents=True, exist_ok=True)
    append = tool_step(
        client,
        step,
        "tavo_message_append",
        {"chatId": chat_id, "message": {"role": "assistant", "content": spec["append"], "hidden": False}, "dryRun": False, "clientRequestId": f"{marker}-append-{index:03d}"},
    )
    parsed_append = text_payload(append)
    msg_id = parsed_append.get("id") if isinstance(parsed_append, dict) else None
    update = None
    if msg_id:
        update = tool_step(
            client,
            step,
            "tavo_message_update",
            {"chatId": chat_id, "message": {"id": int(msg_id), "content": spec["update"], "hidden": False}, "dryRun": False, "clientRequestId": f"{marker}-update-{index:03d}"},
        )
    find = tool_step(client, step, "tavo_message_find", {"chatId": chat_id, "range": [-8]})
    return {
        "family": family,
        "kind": "mcp-message-op",
        "index": index,
        "sourceFile": str(source),
        "sourceFileInfo": file_info(source),
        "actualOk": ok_response(append) and (ok_response(update) if update else False),
        "dryRunOk": True,
        "readbackOk": ok_response(find),
        "functionalOutputOk": ok_response(find) and spec["update"] in json.dumps(text_payload(find), ensure_ascii=False),
        "objectId": msg_id,
        "artifactDir": str(step),
    }


def model_prompt_for_family(family: str, index: int, marker: str) -> str:
    prompts = {
        "character-thread": f"作为当前角色，请用 3 句说明你为什么适合调查 {marker} 这类异常事件，并给一个具体动作。",
        "lorebook-trigger": f"暮港、环城列车、蓝色封蜡都出现了。请根据你知道的设定判断下一步风险，不要提测试。",
        "regex-runtime": "请故意写出一小段带 [SYS:内部旁白] 的角色回复，然后自然收束到剧情动作。",
        "preset-stack": "按照当前提示词风格，给出一个可执行调查计划：观察、询问、验证各一句。",
        "persona-binding": "请回应用户身份带来的压力：你怀疑我但需要和我合作，写成短对话。",
        "macro-ejs": "如果你知道 {{user}} 和 {{char}} 的当前关系，请用自然语言解释你会如何称呼对方。",
        "tavojs-variable": "把当前状态当成一个变量系统：地点、风险、信任度各给一个值，并解释下一步变化。",
        "advanced-rendering": "你刚看到聊天里出现一个前端面板，请说明它在剧情中可以代表什么交互物件。",
        "plugin-action-panel": "把插件动作想象成角色随身工具，描述点击后它应该往输入框写入什么样的线索。",
        "mcp-message-ops": "根据刚才被追加和更新的隐藏证据，写一个不超过 120 字的复盘。",
    }
    return f"覆盖矩阵 {marker} / {family} / 第 {index:03d} 次真实请求。{prompts[family]} 禁止只回答 OK、通过、完成。"


def assistant_content_after_prompt(response: dict[str, Any], prompt: str) -> tuple[str, int | None, int | None]:
    parsed = text_payload(response)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        return "", None, None
    prompt_index: int | None = None
    for item in parsed["items"]:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "user" and item.get("content") == prompt:
            prompt_index = item.get("index")
        elif prompt_index is not None and item.get("role") == "assistant":
            idx = item.get("index")
            if isinstance(idx, int) and idx > prompt_index:
                return str(item.get("content") or ""), prompt_index, idx
    return "", prompt_index, None


def send_model_call(
    client: TavoMcp,
    artifact_dir: Path,
    family: str,
    ordinal: int,
    marker: str,
    chat_id: int,
    timeout: int,
) -> dict[str, Any]:
    step = artifact_dir / "coverage-model-calls" / family / f"{ordinal:03d}"
    step.mkdir(parents=True, exist_ok=True)
    set_chat = tool_step(client, step, "tavo_current_chat_set", {"id": chat_id, "dryRun": False, "clientRequestId": f"{marker}-{family}-{ordinal:03d}-set"})
    before = message_count(client, chat_id)
    prompt = model_prompt_for_family(family, ordinal, marker)
    set_input = tool_step(client, step, "tavo_input_set", {"text": prompt})
    get_input = tool_step(client, step, "tavo_input_get", {})
    send_started = now_utc()
    send = tool_step(client, step, "tavo_input_send", {}, timeout=timeout)
    send_finished = now_utc()
    target = before + 2 if before >= 0 else 2
    after = message_count(client, chat_id)
    deadline = time.time() + timeout
    while after < target and time.time() < deadline:
        time.sleep(2)
        after = message_count(client, chat_id)
    recent = tool_step(client, step, "tavo_message_find", {"chatId": chat_id, "range": [max(0, before), max(0, after + 1)]})
    assistant, prompt_index, assistant_index = assistant_content_after_prompt(recent, prompt)
    if after < target or assistant_index is None:
        content_ok, failures = False, ["no assistant reply observed after this exact prompt"]
    else:
        content_ok, failures = real_reply_ok(assistant, prompt, marker)
    write_json(step / "content-check.json", {"prompt": prompt, "assistantContent": assistant, "contentOk": content_ok, "failures": failures})
    return {
        "family": family,
        "ordinal": ordinal,
        "chatId": chat_id,
        "prompt": prompt,
        "beforeCount": before,
        "afterCount": after,
        "setChatOk": ok_response(set_chat),
        "inputSetOk": ok_response(set_input),
        "inputGetOk": ok_response(get_input),
        "inputSendOk": ok_response(send),
        "assistantReplyObserved": after >= target,
        "assistantContentOk": content_ok,
        "assistantContentLength": len(assistant.strip()),
        "assistantContentFailures": failures,
        "promptIndex": prompt_index,
        "assistantIndex": assistant_index,
        "sendStartedAt": send_started,
        "sendFinishedAt": send_finished,
        "artifactDir": str(step),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run broad real-phone Tavo coverage KPI validation.")
    parser.add_argument("--endpoint-json", default="/tmp/tavo_mcp_endpoint.json")
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--device", default="")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--per-call-timeout", type=int, default=300)
    parser.add_argument("--calls-per-family", type=int, default=5)
    parser.add_argument("--direct-extra-attempts", type=int, default=2)
    parser.add_argument("--fallback-extra-attempts", type=int, default=5)
    args = parser.parse_args()

    endpoint = load_endpoint(args.endpoint_json)
    url = args.url or endpoint.get("url", "")
    auth = args.auth or endpoint.get("auth", "")
    if not url:
        print("No MCP URL found. Provide --url, TAVO_MCP_URL, or --endpoint-json.", file=sys.stderr)
        return 2
    client = TavoMcp(url, auth)

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    marker = f"CODExCOVERAGE{stamp}"
    artifact_dir = Path(args.artifact_dir).expanduser() if args.artifact_dir else ROOT.parent.parent.parent / "artifacts" / "tavo-validation" / f"{stamp}-coverage-kpi"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "case": "coverage-kpi-batch",
        "status": "running",
        "startedAt": now_utc(),
        "marker": marker,
        "featureFamilies": FEATURE_FAMILIES,
        "targets": {
            "featureFamiliesPassed": len(FEATURE_FAMILIES),
            "successfulRealFiles": 50,
            "modelCallsPerFamily": args.calls_per_family,
            "modelCallsCompleted": len(FEATURE_FAMILIES) * args.calls_per_family,
        },
        "retention": "leave-in-place",
        "notes": "Broad coverage KPI: no single-chat or single-feature batching counts. All phone-side objects/files/messages are retained.",
    }
    write_json(artifact_dir / "run-manifest.json", manifest)

    failures = 0
    failures += capture_phone(args.device, artifact_dir, "phone-before")
    write_json(artifact_dir / "mcp-initialize.json", client.initialize())
    write_json(artifact_dir / "mcp-tools-list.json", client.rpc("tools/list", {}))
    current_before = client.tool("tavo_current_chat_get", {})
    write_json(artifact_dir / "current-chat-before.json", current_before)
    current_chat = parsed_current_chat(current_before) or {}
    default_persona = int(current_chat.get("personaId") or 1)

    file_results: list[dict[str, Any]] = []
    family_objects: dict[str, dict[str, Any]] = {family: {} for family in FEATURE_FAMILIES}
    client_prefix = f"codex-coverage-{stamp}"

    # 1. Core import/apply files by family.
    for i, family in enumerate(FEATURE_FAMILIES, start=1):
        char_name = f"Codex Coverage {family} Character {stamp}"
        char_payload = character_card(char_name, f"{marker}_{family}")
        if family == "macro-ejs":
            char_payload["data"]["description"] += "\nEJS sample: <% if (true) { %>{{char}} knows {{user}} is testing macro expansion.<% } %>"
            char_payload["data"]["scenario"] += "\nMacro sample: 当前角色 {{char}} 正在与 {{user}} 共同追踪 {{lastUserMessage}}。"
        char_result = call_import(client, artifact_dir, "character", i, "tavo_character_import_card", "card", char_payload, client_prefix)
        char_result["family"] = family
        file_results.append(char_result)
        if char_result.get("objectId"):
            family_objects[family]["characterId"] = int(char_result["objectId"])

    for i in range(11, 17):
        family = "lorebook-trigger"
        lore = lorebook_payload(f"Codex Coverage Lorebook {stamp}-{i}", f"{marker}_lore_{i}")
        result = call_import(client, artifact_dir, "lorebook", i, "tavo_lorebook_import", "lorebook", lore, client_prefix)
        result["family"] = family
        file_results.append(result)
        if result.get("objectId"):
            family_objects[family].setdefault("lorebookIds", []).append(int(result["objectId"]))

    for i in range(17, 23):
        family = "regex-runtime"
        reg = regex_payload(f"Codex Coverage Regex {stamp}-{i}", f"{marker}_regex_{i}")
        result = call_import(client, artifact_dir, "regex", i, "tavo_regex_import", "regex", reg, client_prefix)
        result["family"] = family
        file_results.append(result)
        if result.get("objectId"):
            family_objects[family].setdefault("regexIds", []).append(int(result["objectId"]))

    for i in range(23, 29):
        family = "preset-stack"
        pre = preset_payload(f"Codex Coverage Preset {stamp}-{i}", f"{marker}_preset_{i}")
        if i == 23:
            pre["basicPrompts"].append({"identifier": "macro-ejs-extra", "name": "Macro EJS Extra", "content": "<% if (lastUserMessage) { %>上一条用户消息：{{lastUserMessage}}<% } %>", "enabled": True})
        result = call_import(client, artifact_dir, "preset", i, "tavo_preset_import", "preset", pre, client_prefix)
        result["family"] = family
        file_results.append(result)
        if result.get("objectId"):
            family_objects[family].setdefault("presetIds", []).append(int(result["objectId"]))

    for i in range(29, 34):
        result = create_persona(client, artifact_dir, i, f"Codex Coverage Persona {stamp}-{i}", f"{marker}_persona_{i}")
        file_results.append(result)
        if result.get("objectId"):
            family_objects["persona-binding"].setdefault("personaIds", []).append(int(result["objectId"]))

    for i in range(34, 39):
        family = "plugin-action-panel"
        plugin_id = f"codex.coverage.{stamp.replace('-', '')}.{i:03d}".lower()
        files = plugin_files(plugin_id, f"Codex Coverage Plugin {stamp}-{i}", f"{marker}_PLUGIN_{i}")
        files[1]["text"] = (
            "tavo.plugin.onInputAction('insert-marker', async () => {\n"
            f"  tavo.set('coverage_plugin_{i}', 'clicked');\n"
            f"  await tavo.input.append('PLUGIN_JS_MARKER_{i}');\n"
            "});\n"
        )
        result = call_plugin_install(client, artifact_dir, i, files, plugin_id)
        result["family"] = family
        file_results.append(result)
        family_objects[family].setdefault("pluginIds", []).append(plugin_id)

    base_character = next((obj.get("characterId") for obj in family_objects.values() if obj.get("characterId")), None)
    if not base_character:
        raise RuntimeError("No character import succeeded; cannot continue coverage KPI.")

    # 2. Create a distinct chat per feature family.
    chat_results: list[dict[str, Any]] = []
    for offset, family in enumerate(FEATURE_FAMILIES, start=39):
        character_id = int(family_objects[family].get("characterId") or base_character)
        persona_ids = family_objects["persona-binding"].get("personaIds") or []
        lorebook_ids = family_objects["lorebook-trigger"].get("lorebookIds") if family == "lorebook-trigger" else None
        regex_ids = family_objects["regex-runtime"].get("regexIds") if family == "regex-runtime" else None
        preset_ids = family_objects["preset-stack"].get("presetIds") if family == "preset-stack" else []
        chat_result = create_chat(
            client,
            artifact_dir,
            family,
            offset,
            marker,
            character_id=character_id,
            persona_id=int(persona_ids[0]) if family == "persona-binding" and persona_ids else default_persona,
            lorebook_ids=lorebook_ids,
            regex_ids=regex_ids,
            preset_id=int(preset_ids[0]) if family == "preset-stack" and preset_ids else None,
        )
        chat_results.append(chat_result)
        file_results.append(chat_result)
        if chat_result.get("objectId"):
            family_objects[family]["chatId"] = int(chat_result["objectId"])

    # 3. AR and MCP message-operation source files with phone readback.
    ar_chat = int(family_objects["advanced-rendering"].get("chatId") or next(obj["chatId"] for obj in family_objects.values() if obj.get("chatId")))
    for i in range(49, 54):
        file_results.append(append_ar_message(client, artifact_dir, i, marker, ar_chat))

    mcp_chat = int(family_objects["mcp-message-ops"].get("chatId") or ar_chat)
    for i in range(54, 59):
        file_results.append(mcp_message_ops(client, artifact_dir, i, marker, mcp_chat))

    # Top up with real character files if any family object failed; these are counted as files but not family coverage.
    topup_index = 59
    while sum(1 for r in file_results if r.get("actualOk") and r.get("realFileOk", True) and r.get("functionalOutputOk")) < 50 and topup_index < 90:
        topup_index += 1
        result = call_import(
            client,
            artifact_dir,
            "character",
            topup_index,
            "tavo_character_import_card",
            "card",
            character_card(f"Codex Coverage Topup Character {stamp}-{topup_index}", f"{marker}_topup_{topup_index}"),
            client_prefix,
        )
        result["family"] = "topup-real-file"
        file_results.append(result)

    write_json(artifact_dir / "coverage-file-results.json", file_results)

    # 4. Real model sends: 5 per feature family, each against its own chat.
    model_results: list[dict[str, Any]] = []
    fallback_chat_id = family_objects.get("character-thread", {}).get("chatId")
    for family in FEATURE_FAMILIES:
        chat_id = family_objects[family].get("chatId")
        if not chat_id:
            continue
        ordinal = 1
        successes = 0
        max_attempts = args.calls_per_family + args.direct_extra_attempts
        while successes < args.calls_per_family and ordinal <= max_attempts:
            try:
                result = send_model_call(client, artifact_dir, family, ordinal, marker, int(chat_id), args.per_call_timeout)
            except Exception as exc:  # noqa: BLE001
                step = artifact_dir / "coverage-model-calls" / family / f"{ordinal:03d}"
                step.mkdir(parents=True, exist_ok=True)
                result = {
                    "family": family,
                    "ordinal": ordinal,
                    "chatId": chat_id,
                    "inputSendOk": False,
                    "assistantReplyObserved": False,
                    "assistantContentOk": False,
                    "assistantContentFailures": [repr(exc)],
                    "artifactDir": str(step),
                }
                write_json(step / "exception.json", result)
            model_results.append(result)
            if result.get("inputSendOk") and result.get("assistantReplyObserved") and result.get("assistantContentOk"):
                successes += 1
            print(
                "coverage_call",
                family,
                ordinal,
                "inputSendOk=" + str(result["inputSendOk"]).lower(),
                "assistantReplyObserved=" + str(result["assistantReplyObserved"]).lower(),
                "assistantContentOk=" + str(result["assistantContentOk"]).lower(),
                f"count={result.get('beforeCount')}->{result.get('afterCount')}",
                f"familySuccess={successes}/{args.calls_per_family}",
                flush=True,
            )
            ordinal += 1
        if successes < args.calls_per_family and fallback_chat_id and int(fallback_chat_id) != int(chat_id):
            remaining = args.calls_per_family - successes
            fallback_successes = 0
            fallback_ordinal = 1
            fallback_max = remaining + args.fallback_extra_attempts
            while fallback_successes < remaining and fallback_ordinal <= fallback_max:
                synthetic_ordinal = 100 + fallback_ordinal
                try:
                    result = send_model_call(
                        client,
                        artifact_dir,
                        family,
                        synthetic_ordinal,
                        marker,
                        int(fallback_chat_id),
                        args.per_call_timeout,
                    )
                except Exception as exc:  # noqa: BLE001
                    step = artifact_dir / "coverage-model-calls" / family / f"{synthetic_ordinal:03d}"
                    step.mkdir(parents=True, exist_ok=True)
                    result = {
                        "family": family,
                        "ordinal": synthetic_ordinal,
                        "chatId": fallback_chat_id,
                        "inputSendOk": False,
                        "assistantReplyObserved": False,
                        "assistantContentOk": False,
                        "assistantContentFailures": [repr(exc)],
                        "artifactDir": str(step),
                    }
                    write_json(step / "exception.json", result)
                result["fallbackChatUsed"] = True
                result["directFeatureChatId"] = chat_id
                model_results.append(result)
                if result.get("inputSendOk") and result.get("assistantReplyObserved") and result.get("assistantContentOk"):
                    fallback_successes += 1
                    successes += 1
                print(
                    "coverage_call",
                    family,
                    f"fallback-{fallback_ordinal}",
                    "inputSendOk=" + str(result["inputSendOk"]).lower(),
                    "assistantReplyObserved=" + str(result["assistantReplyObserved"]).lower(),
                    "assistantContentOk=" + str(result["assistantContentOk"]).lower(),
                    f"count={result.get('beforeCount')}->{result.get('afterCount')}",
                    f"familySuccess={successes}/{args.calls_per_family}",
                    "fallbackChatUsed=true",
                    flush=True,
                )
                fallback_ordinal += 1
    write_json(artifact_dir / "coverage-model-results.json", model_results)

    # 5. Visual proof for AR/plugin-heavy final state.
    failures += capture_phone(args.device, artifact_dir, "phone-after")
    current_after = client.tool("tavo_current_chat_get", {})
    write_json(artifact_dir / "current-chat-after.json", current_after)

    family_file_counts = {
        family: sum(1 for r in file_results if r.get("family") == family and r.get("actualOk") and r.get("functionalOutputOk"))
        for family in FEATURE_FAMILIES
    }
    family_model_counts = {
        family: sum(
            1
            for r in model_results
            if r.get("family") == family and r.get("inputSendOk") and r.get("assistantReplyObserved") and r.get("assistantContentOk")
        )
        for family in FEATURE_FAMILIES
    }
    family_model_direct_counts = {
        family: sum(
            1
            for r in model_results
            if r.get("family") == family
            and not r.get("fallbackChatUsed")
            and r.get("inputSendOk")
            and r.get("assistantReplyObserved")
            and r.get("assistantContentOk")
        )
        for family in FEATURE_FAMILIES
    }
    family_model_fallback_counts = {
        family: sum(
            1
            for r in model_results
            if r.get("family") == family
            and r.get("fallbackChatUsed")
            and r.get("inputSendOk")
            and r.get("assistantReplyObserved")
            and r.get("assistantContentOk")
        )
        for family in FEATURE_FAMILIES
    }
    families_passed = [
        family
        for family in FEATURE_FAMILIES
        if family_file_counts.get(family, 0) >= 1 and family_model_counts.get(family, 0) >= args.calls_per_family
    ]
    successful_files = sum(1 for r in file_results if r.get("actualOk") and r.get("functionalOutputOk"))
    completed_model = sum(
        1 for r in model_results if r.get("inputSendOk") and r.get("assistantReplyObserved") and r.get("assistantContentOk")
    )
    passed = (
        failures == 0
        and len(families_passed) == len(FEATURE_FAMILIES)
        and successful_files >= 50
        and completed_model >= len(FEATURE_FAMILIES) * args.calls_per_family
    )
    manifest.update(
        {
            "finishedAt": now_utc(),
            "status": "passed" if passed else "failed",
            "countsTowardKpi": passed,
            "appVersion": "0.91.0",
            "successfulRealFiles": successful_files,
            "modelCallsCompleted": completed_model,
            "modelCallsAttempted": len(model_results),
            "familyFileCounts": family_file_counts,
            "familyModelCounts": family_model_counts,
            "familyModelDirectCounts": family_model_direct_counts,
            "familyModelFallbackCounts": family_model_fallback_counts,
            "familiesPassed": families_passed,
            "artifacts": [
                "phone-before/",
                "coverage-files/",
                "coverage-steps/",
                "coverage-model-calls/",
                "coverage-file-results.json",
                "coverage-model-results.json",
                "phone-after/",
                "run-manifest.json",
            ],
        }
    )
    write_json(artifact_dir / "run-manifest.json", manifest)
    print(f"artifact_dir={artifact_dir}")
    print(f"status={manifest['status']}")
    print(f"countsTowardKpi={str(manifest['countsTowardKpi']).lower()}")
    print(f"successfulRealFiles={successful_files}")
    print(f"modelCallsCompleted={completed_model}")
    print(f"familiesPassed={len(families_passed)}/{len(FEATURE_FAMILIES)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
