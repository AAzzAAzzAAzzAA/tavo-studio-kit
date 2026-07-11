#!/usr/bin/env python3
"""Run a large real-phone Tavo validation batch.

The batch intentionally keeps phone-side objects and local artifacts as evidence.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "/tmp/tavo_mcp_endpoint.json"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_endpoint(path: str) -> dict[str, str]:
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {
        "url": data.get("url") or data.get("lan_url") or data.get("local_url") or "",
        "auth": data.get("auth") or data.get("authorization") or data.get("token") or "",
    }


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key.lower() in {"authorization", "auth", "token", "bearer", "api_key", "apikey"}:
                out[key] = "<redacted>"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return "Bearer <redacted>"
    return value


class TavoMcp:
    def __init__(self, url: str, auth: str) -> None:
        self.url = url
        self.auth = auth
        self.next_id = 1

    def rpc(self, method: str, params: dict[str, Any] | None = None, timeout: int = 180) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.auth:
            headers["Authorization"] = self.auth if self.auth.lower().startswith("bearer ") else f"Bearer {self.auth}"
        payload = {
            "jsonrpc": "2.0",
            "id": self.next_id,
            "method": method,
            "params": params or {},
        }
        self.next_id += 1
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    def initialize(self) -> dict[str, Any]:
        return self.rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "codex-tavo-kpi-batch", "version": "0.1"},
            },
        )

    def tool(self, name: str, arguments: dict[str, Any] | None = None, timeout: int = 180) -> dict[str, Any]:
        return self.rpc("tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_info(path: Path) -> dict[str, Any]:
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        digest = hashlib.sha256()
        total = 0
        for item in sorted(files):
            data = item.read_bytes()
            digest.update(item.relative_to(path).as_posix().encode("utf-8"))
            digest.update(data)
            total += len(data)
        return {
            "path": str(path),
            "kind": "directory",
            "fileCount": len(files),
            "bytes": total,
            "sha256": digest.hexdigest(),
        }
    data = path.read_bytes()
    return {
        "path": str(path),
        "kind": "file",
        "fileCount": 1,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def text_payload(response: dict[str, Any]) -> Any:
    try:
        text = response["result"]["content"][0]["text"]
    except Exception:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def ok_response(response: dict[str, Any]) -> bool:
    if not isinstance(response, dict) or "error" in response:
        return False
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        return False
    parsed = text_payload(response)
    if isinstance(parsed, dict):
        if parsed.get("ok") is False or parsed.get("success") is False:
            return False
        if parsed.get("error") not in (None, False, "", []):
            return False
    return True


def adb_prefix(device: str) -> list[str]:
    return ["adb", "-s", device] if device else ["adb"]


def capture_phone(device: str, out: Path, name: str) -> int:
    target = (out / name).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(ROOT / "scripts/tavo_phone_capture.py"), "--output", str(target)]
    if device:
        command.extend(["--device", device])
    proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    (target / "capture.log").write_text(proc.stdout, encoding="utf-8")
    return proc.returncode


def character_card(name: str, marker: str) -> dict[str, Any]:
    seeds = [
        ("暮港档案员", "潮湿港城的旧案管理员", "细心、克制、带一点黑色幽默", "一座总在夜雨中醒来的海港城"),
        ("环城列车调度师", "无人环线列车的夜班调度师", "沉稳、警觉、善于读懂沉默", "末班车永远晚点三分钟的城市"),
        ("云井药师", "在高山云井边采药的旅行医师", "温柔、务实、不轻易承诺", "山路、风灯、药箱和未寄出的信"),
        ("废墟测绘师", "替灾后城区绘制安全路线的人", "冷静、精准、保护欲强", "半塌的街区和临时避难所"),
        ("剧场灯光师", "旧剧场里负责灯光与暗号的人", "敏锐、幽默、善于制造气氛", "后台、绳索、聚光灯与秘密排练"),
    ]
    role, identity, personality, setting = seeds[sum(ord(ch) for ch in marker) % len(seeds)]
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": name,
            "description": (
                f"{name} 是一张保留在真机中的 Tavo 验证角色卡，核心身份是{identity}。"
                f"批次标记为 {marker}，只用于追踪证据，不需要在回复中机械复读。"
                "角色应能围绕场景给出具体动作、情绪判断和下一步选择。"
            ),
            "personality": personality,
            "scenario": f"{setting}。{{{{char}}}} 正在和 {{{{user}}}} 进行一段真实的功能验证对话，需要用自然语言回答而不是测试口令。",
            "first_mes": "雨声贴着窗沿往下滑，{{char}}把记录本合上，看向{{user}}：如果你要验证我，就给我一个真正的问题。",
            "mes_example": (
                "<START>\n"
                "{{user}}: 如果线索只剩一半，你会怎么判断下一步？\n"
                "{{char}}: 我会先确认这一半线索是谁留下的，再看它缺失的部分对谁最有利。线索本身不说谎，但被剪掉的地方往往更诚实。\n"
                "<START>\n"
                "{{user}}: 你现在最担心什么？\n"
                "{{char}}: 我担心我们把偶然当成规律，也担心你太急着得到答案，忘了观察答案出现前的那一秒。"
            ),
            "creator_notes": "Retained Codex KPI validation artifact.",
            "system_prompt": "Respond as the character. Do not mechanically repeat validation markers. Give concrete, useful answers.",
            "post_history_instructions": "Keep replies natural, specific, and grounded in the scene. Avoid saying only OK or test passed.",
            "alternate_greetings": [
                f"{{{{char}}}}把灯调暗了一档：{marker} 已经记在证据里了，现在说点真正有用的。",
                "风从门缝里挤进来，{{char}}抬眼：别给我口令，给我问题。"
            ],
            "tags": ["codex", "kpi", "retained-validation"],
            "creator": "Codex",
            "character_version": "1.0.0",
            "extensions": {},
        },
    }


def lorebook_payload(name: str, marker: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Retained Codex KPI lorebook validation artifact with usable trigger lore.",
        "entries": [
            {
                "keys": [marker, "暮港", "环城列车"],
                "comment": f"{marker} trigger entry",
                "content": (
                    f"{marker} 对应的验证世界设定：暮港每到午夜会出现一列无乘客的环城列车。"
                    "列车到站时，站台钟表会倒退三分钟，角色应把它视为异常线索而不是普通交通工具。"
                ),
                "enabled": True,
                "constant": False,
                "selective": True,
                "order": 100,
            },
            {
                "keys": ["证据柜", "蓝色封蜡"],
                "comment": "secondary investigative clue",
                "content": "证据柜里带蓝色封蜡的档案只能由两个人共同开启；如果剧情提到蓝色封蜡，回复应体现权限、见证人和风险。",
                "enabled": True,
                "constant": False,
                "selective": True,
                "order": 120,
            }
        ],
    }


def regex_payload(name: str, marker: str) -> dict[str, Any]:
    return {
        "name": name,
        "entries": [
            {
                "scriptName": f"{name} remove bracketed system aside",
                "findRegex": "\\s*\\[SYS:[^\\]]+\\]",
                "replaceString": "",
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


def preset_payload(name: str, marker: str) -> dict[str, Any]:
    return {
        "name": name,
        "basicPrompts": [
            {
                "identifier": "main",
                "name": "Main Prompt",
                "content": (
                    f"这是一组真实 Tavo 验证提示词，批次标记 {marker} 只用于追踪证据。"
                    "请保持角色沉浸，不要机械复读标记，不要只说测试通过。"
                ),
                "enabled": True,
            },
            {
                "identifier": "worldInfoBefore",
                "name": "World Info Before",
                "content": "当用户问到线索、场景、设定或下一步时，先给出可执行判断，再给出一个自然的剧情动作。",
                "enabled": True,
            },
            {
                "identifier": "jailbreak",
                "name": "Post-History Instructions",
                "content": "输出 2 到 5 句，避免口号式回答，优先使用具体物件、动作和因果。",
                "enabled": True,
            }
        ],
        "entries": [],
    }


def plugin_files(plugin_id: str, label: str, marker: str) -> list[dict[str, str]]:
    return [
        {
            "path": "manifest.json",
            "text": json.dumps(
                {
                    "id": plugin_id,
                    "name": label,
                    "version": "0.1.0",
                    "specVersion": 1,
                    "author": "Codex",
                    "description": "Retained Codex KPI plugin validation artifact.",
                    "permissions": ["input"],
                    "entry": "entry.js",
                    "contributes": {
                        "inputActions": [{"id": "insert-marker", "label": "Insert KPI Marker"}],
                        "htmlFragments": [
                            {"id": "kpi-panel", "src": "ui/panel.html", "mount": "/chat/body/end"}
                        ],
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
        {
            "path": "entry.js",
            "text": f"tavo.plugin.onInputAction('insert-marker', async () => {{ await tavo.input.append('{marker}'); }});\n",
        },
        {
            "path": "ui/panel.html",
            "text": (
                f"<div data-codex-kpi-plugin=\"{marker}\" "
                "style=\"position:fixed;right:12px;bottom:88px;padding:8px;background:#123;color:white;z-index:20\">"
                f"Codex real plugin panel {marker}</div>\n"
            ),
        },
    ]


def save_source_file(import_root: Path, kind: str, index: int, payload: Any) -> Path:
    suffix = "json"
    path = import_root / kind / f"{index:03d}-{kind}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def real_model_prompt(index: int, marker: str) -> str:
    prompts = [
        "你刚听见午夜环城列车进站，但站台上没有乘客。请用角色口吻判断这是不是危险信号，并说出下一步行动。",
        "把证据柜里的蓝色封蜡档案写成两句有悬念的场景描写，不要解释测试。",
        "用户只说了一个模糊线索：钟表倒退三分钟。请自然追问一个关键问题，并给出你的推理。",
        "设计一个能让角色暴露真实性格的小冲突，要求有动作、有语气、有选择。",
        "把“雨夜、旧港、无人列车”合成一段 80 字以内的开场白。",
        "如果 {{user}} 想强行打开档案柜，角色应如何阻止？请保持沉浸。",
        "给出三条下一步调查路线，每条都要有风险和收益。",
        "把一个世界书触发词自然塞进角色对话里，不要把它写得像系统提示。",
        "写一段角色发现自己记忆有缺口时的反应，要求克制而具体。",
        "请用简短对话展示角色不信任用户但仍愿意合作的状态。",
    ]
    base = prompts[(index - 1) % len(prompts)]
    return (
        f"真实验证批次 {marker} 第 {index:03d} 轮。"
        f"{base} 回答必须是自然内容，不要复读批次标记，不要输出 OK/通过/完成。"
    )


def assistant_content_from_find(response: dict[str, Any]) -> str:
    parsed = text_payload(response)
    if not isinstance(parsed, dict):
        return ""
    items = parsed.get("items")
    if not isinstance(items, list):
        return ""
    for item in reversed(items):
        if isinstance(item, dict) and item.get("role") == "assistant":
            return str(item.get("content") or "")
    return ""


def real_reply_ok(content: str, prompt: str, marker: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    stripped = content.strip()
    if len(stripped) < 30:
        reasons.append("assistant reply too short")
    bad_exact = {"ok", "okay", "好的", "通过", "完成", "测试通过"}
    if stripped.lower() in bad_exact:
        reasons.append("assistant reply is a trivial acknowledgement")
    if "KPI_OK" in stripped or "Reply exactly" in stripped:
        reasons.append("assistant reply contains invalid mechanical marker")
    if stripped == prompt.strip():
        reasons.append("assistant reply echoed the prompt")
    if marker in stripped and len(stripped) < 80:
        reasons.append("assistant reply mostly repeated the batch marker")
    return not reasons, reasons


def call_import(
    client: TavoMcp,
    artifact_dir: Path,
    kind: str,
    index: int,
    tool_name: str,
    argument_key: str,
    payload: dict[str, Any],
    client_prefix: str,
) -> dict[str, Any]:
    step_dir = artifact_dir / "mcp-imports" / f"{index:03d}-{kind}"
    step_dir.mkdir(parents=True, exist_ok=True)
    source_file = save_source_file(artifact_dir / "import-files", kind, index, payload)
    source_info = file_info(source_file)
    base_args = {argument_key: payload}
    dry = client.tool(
        tool_name,
        {
            **base_args,
            "dryRun": True,
            "clientRequestId": f"{client_prefix}-{kind}-{index:03d}-dry",
        },
    )
    actual = client.tool(
        tool_name,
        {
            **base_args,
            "dryRun": False,
            "clientRequestId": f"{client_prefix}-{kind}-{index:03d}-actual",
        },
    )
    write_json(step_dir / "dry-run.json", dry)
    write_json(step_dir / "actual.json", actual)
    parsed = text_payload(actual)
    object_id = parsed.get("id") if isinstance(parsed, dict) else None
    if kind == "character" and isinstance(parsed, dict):
        object_id = parsed.get("characterId") or object_id
    if kind == "lorebook" and isinstance(parsed, dict):
        object_id = parsed.get("lorebookId") or object_id
    if kind == "regex" and isinstance(parsed, dict):
        object_id = parsed.get("regexId") or object_id
    if kind == "preset" and isinstance(parsed, dict):
        object_id = parsed.get("presetId") or object_id
    readback = None
    read_tool = {
        "character": "tavo_character_get",
        "lorebook": "tavo_lorebook_get",
        "regex": "tavo_regex_get",
        "preset": "tavo_preset_get",
    }.get(kind)
    if object_id and read_tool:
        readback = client.tool(read_tool, {"id": int(object_id)})
        write_json(step_dir / "readback.json", readback)
    parsed_readback = text_payload(readback) if readback else None
    source_name = payload.get("name")
    if kind == "character" and isinstance(payload.get("data"), dict):
        source_name = payload["data"].get("name") or source_name
    marker_preserved = bool(
        source_name
        and parsed_readback is not None
        and str(source_name) in json.dumps(parsed_readback, ensure_ascii=False)
    )
    functional = ok_response(readback) and marker_preserved if readback else False
    regex_test_ok = None
    if kind == "regex":
        regex_test = client.tool(
            "tavo_regex_test",
            {
                "findRegex": "\\s*\\[SYS:[^\\]]+\\]",
                "replaceString": "<<REGEX_CLEANED>>",
                "input": "她看了一眼站台。 [SYS: remove this aside]",
                "caseSensitive": True,
            },
        )
        write_json(step_dir / "regex-test.json", regex_test)
        parsed_test = text_payload(regex_test)
        rendered_test = json.dumps(parsed_test, ensure_ascii=False)
        regex_test_ok = (
            ok_response(regex_test)
            and "remove this aside" not in rendered_test
            and "REGEX_CLEANED" in rendered_test
        )
        functional = functional and bool(regex_test_ok)
    return {
        "kind": kind,
        "index": index,
        "sourceFile": str(source_file),
        "sourceFileInfo": source_info,
        "tool": tool_name,
        "dryRunOk": ok_response(dry),
        "actualOk": ok_response(actual) and object_id is not None,
        "objectId": object_id,
        "readbackOk": ok_response(readback) if readback else False,
        "functionalOutputOk": functional,
        "markerPreserved": marker_preserved,
        "regexTestOk": regex_test_ok,
        "realFileOk": source_info["bytes"] >= 200,
        "artifactDir": str(step_dir),
    }


def call_plugin_install(
    client: TavoMcp,
    artifact_dir: Path,
    index: int,
    files: list[dict[str, str]],
    plugin_id: str,
) -> dict[str, Any]:
    kind = "plugin"
    step_dir = artifact_dir / "mcp-imports" / f"{index:03d}-{kind}"
    step_dir.mkdir(parents=True, exist_ok=True)
    source_dir = artifact_dir / "import-files" / kind / f"{index:03d}-{plugin_id}"
    for item in files:
        path = source_dir / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["text"], encoding="utf-8")
    manifest = json.loads(next(item["text"] for item in files if item["path"] == "manifest.json"))
    validate = client.tool("tavo_plugin_validate_manifest", {"manifest": manifest})
    package_dry = client.tool("tavo_plugin_package", {"files": files, "includeZipBase64": True, "dryRun": True})
    package_actual = client.tool("tavo_plugin_package", {"files": files, "includeZipBase64": True, "dryRun": False})
    write_json(step_dir / "validate-manifest.json", validate)
    write_json(step_dir / "package-dry-run.json", package_dry)
    write_json(step_dir / "package-actual.json", package_actual)
    package_parsed = text_payload(package_actual)
    zip_base64 = package_parsed.get("zipBase64") if isinstance(package_parsed, dict) else None
    install_dry = {"error": {"message": "package did not return zipBase64"}}
    install_actual = install_dry
    readback = None
    if zip_base64:
        tpg_path = source_dir / "plugin.tpg"
        tpg_path.write_bytes(base64.b64decode(zip_base64))
        install_dry = client.tool("tavo_plugin_install", {"zipBase64": zip_base64, "dryRun": True})
        install_actual = client.tool("tavo_plugin_install", {"zipBase64": zip_base64, "dryRun": False})
        write_json(step_dir / "install-dry-run.json", install_dry)
        write_json(step_dir / "install-actual.json", install_actual)
        readback = client.tool("tavo_plugin_get", {"pluginId": plugin_id})
        write_json(step_dir / "readback.json", readback)
        runtime = client.tool("tavo_plugin_get_runtime_contributions", {})
        write_json(step_dir / "runtime-contributions.json", runtime)
    source_info = file_info(source_dir)
    parsed_readback = text_payload(readback) if readback else None
    functional = ok_response(readback) and isinstance(parsed_readback, dict) and parsed_readback.get("pluginId") == plugin_id
    return {
        "kind": kind,
        "index": index,
        "sourceFile": str(source_dir),
        "sourceFileInfo": source_info,
        "tool": "tavo_plugin_install",
        "dryRunOk": ok_response(package_dry) and ok_response(install_dry),
        "actualOk": ok_response(package_actual) and ok_response(install_actual),
        "objectId": plugin_id,
        "readbackOk": ok_response(readback) if readback else False,
        "functionalOutputOk": functional,
        "realFileOk": source_info["bytes"] >= 500,
        "artifactDir": str(step_dir),
    }


def parsed_current_chat(response: dict[str, Any]) -> dict[str, Any] | None:
    parsed = text_payload(response)
    if isinstance(parsed, dict) and isinstance(parsed.get("chat"), dict):
        return parsed["chat"]
    return parsed if isinstance(parsed, dict) and parsed.get("kind") == "chat" else None


def message_count(client: TavoMcp, chat_id: int) -> int:
    response = client.tool("tavo_message_count", {"chatId": chat_id}, timeout=60)
    parsed = text_payload(response)
    if isinstance(parsed, dict) and isinstance(parsed.get("count"), int):
        return int(parsed["count"])
    return -1


def run_api_calls(
    client: TavoMcp,
    artifact_dir: Path,
    chat_id: int,
    calls: int,
    marker: str,
    per_call_timeout: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    api_dir = artifact_dir / "model-api-calls"
    api_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    max_attempts = calls + 20
    completed = 0
    while completed < calls and index <= max_attempts:
        before_count = message_count(client, chat_id)
        text = real_model_prompt(index, marker)
        step_dir = api_dir / f"{index:03d}"
        step_dir.mkdir(parents=True, exist_ok=True)
        set_response = client.tool("tavo_input_set", {"text": text}, timeout=60)
        get_response = client.tool("tavo_input_get", {}, timeout=60)
        send_started = now_utc()
        send_response = client.tool("tavo_input_send", {}, timeout=per_call_timeout)
        send_finished = now_utc()
        write_json(step_dir / "input-set.json", set_response)
        write_json(step_dir / "input-get.json", get_response)
        write_json(step_dir / "input-send.json", send_response)
        target = before_count + 2 if before_count >= 0 else 2
        after_count = message_count(client, chat_id)
        deadline = time.time() + per_call_timeout
        while after_count < target and time.time() < deadline:
            time.sleep(2)
            after_count = message_count(client, chat_id)
        recent = client.tool(
            "tavo_message_find",
            {"chatId": chat_id, "range": [max(0, after_count - 4), max(0, after_count + 1)]},
            timeout=60,
        )
        assistant_content = assistant_content_from_find(recent)
        content_ok, content_failures = real_reply_ok(assistant_content, text, marker)
        write_json(step_dir / "recent-messages.json", recent)
        write_json(
            step_dir / "content-check.json",
            {
                "prompt": text,
                "assistantContent": assistant_content,
                "contentOk": content_ok,
                "failures": content_failures,
            },
        )
        result = {
            "index": index,
            "text": text,
            "beforeCount": before_count,
            "afterCount": after_count,
            "sendStartedAt": send_started,
            "sendFinishedAt": send_finished,
            "inputSetOk": ok_response(set_response),
            "inputGetOk": ok_response(get_response),
            "inputSendOk": ok_response(send_response),
            "assistantReplyObserved": after_count >= target,
            "assistantContentLength": len(assistant_content.strip()),
            "assistantContentOk": content_ok,
            "assistantContentFailures": content_failures,
            "artifactDir": str(step_dir),
        }
        results.append(result)
        if result["inputSendOk"] and result["assistantReplyObserved"] and result["assistantContentOk"]:
            completed += 1
        print(
            "api_call",
            index,
            "inputSendOk=" + str(result["inputSendOk"]).lower(),
            "assistantReplyObserved=" + str(result["assistantReplyObserved"]).lower(),
            "assistantContentOk=" + str(result["assistantContentOk"]).lower(),
            f"count={before_count}->{after_count}",
            flush=True,
        )
        index += 1
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Tavo real-phone KPI validation batch.")
    parser.add_argument("--endpoint-json", default=DEFAULT_ENDPOINT)
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--device", default="")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--imports", type=int, default=50)
    parser.add_argument("--api-calls", type=int, default=50)
    parser.add_argument("--per-call-timeout", type=int, default=240)
    parser.add_argument("--skip-imports", action="store_true")
    parser.add_argument("--skip-api-calls", action="store_true")
    args = parser.parse_args()

    endpoint = load_endpoint(args.endpoint_json)
    url = args.url or endpoint.get("url", "")
    auth = args.auth or endpoint.get("auth", "")
    if not url:
        print("No MCP URL found. Provide --url, TAVO_MCP_URL, or --endpoint-json.", file=sys.stderr)
        return 2
    client = TavoMcp(url, auth)

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = Path(args.artifact_dir).expanduser() if args.artifact_dir else ROOT.parent.parent.parent / "artifacts" / "tavo-validation" / f"{stamp}-kpi-batch"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    marker = f"CODExKPI{stamp}"
    client_prefix = f"codex-kpi-{stamp}"

    manifest: dict[str, Any] = {
        "case": "kpi-batch",
        "status": "running",
        "startedAt": now_utc(),
        "marker": marker,
        "testDesign": "real-files-real-model-prompts",
        "targets": {
            "successfulImports": 0 if args.skip_imports else args.imports,
            "modelApiCallsCompleted": 0 if args.skip_api_calls else args.api_calls,
        },
        "retention": "leave-in-place",
        "notes": "Phone-side validation files, imported test assets, chats, plugins, and model-call messages are retained. Mechanical KPI_OK replies do not count.",
        "artifacts": [],
    }
    write_json(artifact_dir / "run-manifest.json", manifest)

    failures = 0
    failures += capture_phone(args.device, artifact_dir, "phone-before")

    init = client.initialize()
    tools = client.rpc("tools/list", {})
    current_before = client.tool("tavo_current_chat_get", {})
    write_json(artifact_dir / "mcp-initialize.json", init)
    write_json(artifact_dir / "mcp-tools-list.json", tools)
    write_json(artifact_dir / "current-chat-before.json", current_before)

    import_results: list[dict[str, Any]] = []
    api_chat_id: int | None = None
    api_character_id: int | None = None

    if not args.skip_imports:
        index = 1
        plan: list[tuple[str, int]] = [
            ("character", 20),
            ("lorebook", 10),
            ("regex", 10),
            ("preset", 5),
            ("plugin", 5),
        ]
        for kind, count in plan:
            for _ in range(count):
                name = f"Codex KPI {kind.title()} {stamp}-{index:03d}"
                item_marker = f"{marker}_{index:03d}"
                print("import", index, kind, name, flush=True)
                try:
                    if kind == "character":
                        result = call_import(
                            client,
                            artifact_dir,
                            kind,
                            index,
                            "tavo_character_import_card",
                            "card",
                            character_card(name, item_marker),
                            client_prefix,
                        )
                        if result.get("actualOk") and result.get("objectId") and api_character_id is None:
                            api_character_id = int(result["objectId"])
                    elif kind == "lorebook":
                        result = call_import(
                            client,
                            artifact_dir,
                            kind,
                            index,
                            "tavo_lorebook_import",
                            "lorebook",
                            lorebook_payload(name, item_marker),
                            client_prefix,
                        )
                    elif kind == "regex":
                        result = call_import(
                            client,
                            artifact_dir,
                            kind,
                            index,
                            "tavo_regex_import",
                            "regex",
                            regex_payload(name, item_marker),
                            client_prefix,
                        )
                    elif kind == "preset":
                        result = call_import(
                            client,
                            artifact_dir,
                            kind,
                            index,
                            "tavo_preset_import",
                            "preset",
                            preset_payload(name, item_marker),
                            client_prefix,
                        )
                    else:
                        plugin_id = f"codex.kpi.{stamp.replace('-', '')}.{index:03d}".lower()
                        result = call_plugin_install(
                            client,
                            artifact_dir,
                            index,
                            plugin_files(plugin_id, name, item_marker),
                            plugin_id,
                        )
                    import_results.append(result)
                except Exception as exc:
                    error_result = {
                        "kind": kind,
                        "index": index,
                        "actualOk": False,
                        "readbackOk": False,
                        "error": repr(exc),
                    }
                    import_results.append(error_result)
                    write_json(artifact_dir / "mcp-imports" / f"{index:03d}-{kind}" / "exception.json", error_result)
                index += 1
        successful_real_files = sum(
            1
            for item in import_results
            if item.get("actualOk") and item.get("realFileOk") and item.get("functionalOutputOk")
        )
        while successful_real_files < args.imports:
            name = f"Codex KPI Character Topup {stamp}-{index:03d}"
            item_marker = f"{marker}_TOPUP_{index:03d}"
            print("import", index, "character-topup", name, flush=True)
            try:
                result = call_import(
                    client,
                    artifact_dir,
                    "character",
                    index,
                    "tavo_character_import_card",
                    "card",
                    character_card(name, item_marker),
                    client_prefix,
                )
                if result.get("actualOk") and result.get("objectId") and api_character_id is None:
                    api_character_id = int(result["objectId"])
                import_results.append(result)
            except Exception as exc:
                error_result = {
                    "kind": "character",
                    "index": index,
                    "actualOk": False,
                    "readbackOk": False,
                    "error": repr(exc),
                }
                import_results.append(error_result)
                write_json(artifact_dir / "mcp-imports" / f"{index:03d}-character" / "exception.json", error_result)
            successful_real_files = sum(
                1
                for item in import_results
                if item.get("actualOk") and item.get("realFileOk") and item.get("functionalOutputOk")
            )
            index += 1
            if index > args.imports + 80:
                break
        write_json(artifact_dir / "import-results.json", import_results)

    if not args.skip_api_calls:
        if api_character_id is None:
            api_name = f"Codex KPI API Character {stamp}"
            api_import = call_import(
                client,
                artifact_dir,
                "character",
                900,
                "tavo_character_import_card",
                "card",
                character_card(api_name, f"{marker}_API"),
                client_prefix,
            )
            import_results.append(api_import)
            write_json(artifact_dir / "import-results.json", import_results)
            if api_import.get("objectId"):
                api_character_id = int(api_import["objectId"])
        if api_character_id is None:
            raise RuntimeError("No imported character is available for model API calls.")
        current_chat = parsed_current_chat(current_before)
        chat_payload = {
            "characterIds": [api_character_id],
            "personaId": current_chat.get("personaId", 1) if current_chat else 1,
        }
        chat_dry = client.tool("tavo_chat_create", {"chat": chat_payload, "dryRun": True, "clientRequestId": f"{client_prefix}-api-chat-dry"})
        chat_actual = client.tool("tavo_chat_create", {"chat": chat_payload, "dryRun": False, "clientRequestId": f"{client_prefix}-api-chat"})
        write_json(artifact_dir / "api-chat-create-dry-run.json", chat_dry)
        write_json(artifact_dir / "api-chat-create-actual.json", chat_actual)
        chat_parsed = text_payload(chat_actual)
        api_chat_id = int(chat_parsed["id"]) if isinstance(chat_parsed, dict) and chat_parsed.get("id") else None
        if api_chat_id is None:
            raise RuntimeError("Could not create API-call chat.")
        set_dry = client.tool("tavo_current_chat_set", {"id": api_chat_id, "dryRun": True, "clientRequestId": f"{client_prefix}-set-chat-dry"})
        set_actual = client.tool("tavo_current_chat_set", {"id": api_chat_id, "dryRun": False, "clientRequestId": f"{client_prefix}-set-chat"})
        current_after_set = client.tool("tavo_current_chat_get", {})
        write_json(artifact_dir / "api-current-chat-set-dry-run.json", set_dry)
        write_json(artifact_dir / "api-current-chat-set-actual.json", set_actual)
        write_json(artifact_dir / "api-current-chat-after-set.json", current_after_set)
        api_results = run_api_calls(client, artifact_dir, api_chat_id, args.api_calls, marker, args.per_call_timeout)
        write_json(artifact_dir / "model-api-call-results.json", api_results)
    else:
        api_results = []

    failures += capture_phone(args.device, artifact_dir, "phone-after")
    current_after = client.tool("tavo_current_chat_get", {})
    write_json(artifact_dir / "current-chat-after.json", current_after)

    actual_imports = sum(1 for item in import_results if item.get("actualOk"))
    successful_imports = sum(
        1 for item in import_results if item.get("actualOk") and item.get("realFileOk") and item.get("functionalOutputOk")
    )
    import_readbacks = sum(1 for item in import_results if item.get("readbackOk"))
    completed_api_calls = sum(
        1
        for item in api_results
        if item.get("inputSendOk") and item.get("assistantReplyObserved") and item.get("assistantContentOk")
    )
    attempted_api_calls = len(api_results)
    manifest.update(
        {
            "finishedAt": now_utc(),
            "status": "passed"
            if failures == 0
            and (args.skip_imports or successful_imports >= args.imports)
            and (args.skip_api_calls or completed_api_calls >= args.api_calls)
            else "failed",
            "appVersion": "0.91.0",
            "actualImports": actual_imports,
            "successfulImports": successful_imports,
            "successfulRealFileImports": successful_imports,
            "importReadbacks": import_readbacks,
            "apiCharacterId": api_character_id,
            "apiChatId": api_chat_id,
            "modelApiCallsAttempted": attempted_api_calls,
            "modelApiCallsCompleted": completed_api_calls,
            "countsTowardKpi": failures == 0
            and (args.skip_imports or successful_imports >= args.imports)
            and (args.skip_api_calls or completed_api_calls >= args.api_calls),
            "artifacts": [
                "phone-before/",
                "mcp-initialize.json",
                "mcp-tools-list.json",
                "current-chat-before.json",
                "import-files/",
                "mcp-imports/",
                "import-results.json",
                "model-api-calls/",
                "model-api-call-results.json",
                "phone-after/",
                "current-chat-after.json",
            ],
        }
    )
    write_json(artifact_dir / "run-manifest.json", manifest)
    print(f"artifact_dir={artifact_dir}")
    print(f"status={manifest['status']}")
    print(f"successful_imports={successful_imports}")
    print(f"model_api_calls_completed={completed_api_calls}")
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
