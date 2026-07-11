#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import run_phone_semantic_kpi as semantic


def ensure_neutral_character(
    client: semantic.TavoMcp,
    artifact_dir: Path,
    run_id: str,
) -> dict:
    name = f"Preset Hidden Seed Validator {run_id}"
    card = {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": name,
            "description": "A neutral assistant that follows the active system preset exactly.",
            "personality": "Calm, literal, concise, and cooperative.",
            "scenario": "A controlled prompt-runtime validation environment.",
            "first_mes": "我已准备好进行预设运行时验证。",
            "mes_example": "",
            "creator_notes": "Non-counting live diagnostic asset.",
            "system_prompt": "",
            "post_history_instructions": "",
            "alternate_greetings": [],
            "tags": ["codex", "diagnostic", run_id],
            "extensions": {},
        },
    }
    source = artifact_dir / "semantic-sources" / "neutral-preset-character.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    step_dir = artifact_dir / "setup" / "neutral-character"
    matches = semantic.search_exact(client, step_dir, "character", name)
    if len(matches) > 1:
        raise RuntimeError("Multiple exact neutral preset diagnostic characters exist.")
    if matches:
        character_id = int(matches[0]["id"])
    else:
        dry = semantic.tool_call(
            client,
            step_dir,
            "dry-run.json",
            "tavo_character_import_card",
            {
                "card": card,
                "dryRun": True,
                "clientRequestId": f"preset-hidden-{run_id}-character-dry",
            },
        )
        actual = semantic.tool_call(
            client,
            step_dir,
            "actual.json",
            "tavo_character_import_card",
            {
                "card": card,
                "dryRun": False,
                "clientRequestId": f"preset-hidden-{run_id}-character-actual",
            },
        )
        payload = semantic.response_payload(actual)
        character_id = int(payload.get("characterId") or payload.get("id") or 0)
        if not semantic.ok_response(dry) or not semantic.ok_response(actual) or character_id < 1:
            raise RuntimeError("Could not import the neutral preset diagnostic character.")
    readback = semantic.tool_call(client, step_dir, "readback.json", "tavo_character_get", {"id": character_id})
    parsed = semantic.response_payload(readback)
    if not semantic.ok_response(readback) or parsed.get("name") != name:
        raise RuntimeError("Neutral preset diagnostic character readback failed.")
    return {"id": character_id, "name": name, "sourcePath": str(source)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run five non-counting hidden-seed preset proofs.")
    parser.add_argument("--endpoint-json", default="/tmp/tavo_mcp_endpoint.json")
    parser.add_argument("--device", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--per-call-timeout", type=int, default=240)
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir).expanduser().resolve()
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        print("Artifact directory must be new and empty.", file=sys.stderr)
        return 2
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = semantic.dt.datetime.now().strftime("%Y%m%d%H%M%S")
    run_id = f"PRESETHIDDEN{stamp}"
    endpoint = semantic.load_endpoint(args.endpoint_json)
    url = str(endpoint.get("url") or "")
    auth = str(endpoint.get("auth") or "")
    global_lock_handle, global_lock_identity = semantic.acquire_phone_runtime_lock(args.device, url)
    client = semantic.TavoMcp(url, auth)
    runner_bundle = semantic.runner_bundle_records()
    manifest_path = artifact_dir / "run-manifest.json"
    manifest = {
        "case": "non-counting-hidden-seed-preset-diagnostic",
        "status": "running",
        "runId": run_id,
        "startedAt": semantic.now_utc(),
        "targetCalls": 5,
        "countsTowardKpi": False,
        "retention": "leave-in-place",
        "diagnosticEntrySha256": semantic.sha256(Path(__file__).resolve()),
        "semanticRunnerBundle": runner_bundle,
        "semanticRunnerBundleHash": semantic.stable_hash(runner_bundle),
        "globalRuntimeLockIdentity": global_lock_identity,
    }
    semantic.atomic_json(manifest_path, manifest)
    plugin_state: dict | None = None
    preset_state: dict | None = None
    original_chat_id: int | None = None
    results: list[dict] = []
    try:
        manifest["deviceIdentity"] = semantic.require_device_identity(args.device)
        semantic.atomic_json(manifest_path, manifest)
        semantic.capture_phone(args.device, artifact_dir, "phone-before")
        current = client.tool("tavo_current_chat_get", {})
        current_payload = semantic.response_payload(current).get("chat")
        current_chat = current_payload if isinstance(current_payload, dict) else {}
        original_chat_id = int(current_chat.get("id") or 0) or None

        character = ensure_neutral_character(client, artifact_dir, run_id)
        persona = semantic.ensure_neutral_persona(client, artifact_dir, run_id)
        presets = semantic.ensure_semantic_presets(client, artifact_dir, run_id)
        plugin = semantic.ensure_semantic_plugin(client, artifact_dir, run_id)
        chats = []
        for ordinal in range(1, 6):
            chat = semantic.ensure_chat(
                client,
                artifact_dir,
                run_id,
                "hidden-seed-preset-diagnostic",
                ordinal,
                {
                    "characterIds": [int(character["id"])],
                    "personaId": int(persona["id"]),
                    "presetId": int(presets[ordinal - 1]["id"]),
                },
            )
            semantic.ensure_chat_seed(
                client,
                artifact_dir,
                run_id,
                "hidden-seed-preset-diagnostic",
                ordinal,
                chat,
            )
            chats.append(chat)

        preset_state = semantic.snapshot_active_preset_runtime(
            client,
            artifact_dir / "active-preset-runtime",
            f"PRESET-HIDDEN-{run_id}",
        )
        plugin_state = semantic.isolate_plugin_runtime(
            client,
            artifact_dir / "plugin-isolation",
            str(plugin["id"]),
            f"PRESET-HIDDEN-{run_id}",
            str(plugin["readbackHash"]),
        )
        semantic.settle_plugin_runtime_ui(
            args.device,
            artifact_dir / "plugin-isolation" / "webview-settle",
            "hidden-seed-preset-diagnostic",
        )
        execution_meta = {
            "diagnosticId": f"PRESET-HIDDEN-{run_id}",
            "entryHash": manifest["diagnosticEntrySha256"],
            "runnerBundleHash": manifest["semanticRunnerBundleHash"],
        }
        for ordinal in range(1, 6):
            marker = str(presets[ordinal - 1]["marker"])
            nonce = semantic.nonce_for(run_id, "preset-stack", ordinal)
            prompt = semantic.with_nonce_after_context_prefix(
                (
                    "当前 system 预设包含一个以 SEM_PRESET_ 开头的完整固定标记。"
                    "可见答案的第一字符必须开始原样复制这个完整标记；不要使用聊天历史中的 seed、角色名或其他前缀。"
                    "随后严格使用 ASCII 标签 OBSERVE、QUESTION、VERIFY，按此顺序各写一段现场审计；不要翻译标签。"
                ),
                nonce,
                "当前 system 预设",
            )
            spec = semantic.CallSpec(
                family="preset-stack",
                ordinal=ordinal,
                chat_id=int(chats[ordinal - 1]["id"]),
                prompt=prompt,
                nonce=nonce,
                expected=[marker, "OBSERVE", "QUESTION", "VERIFY"],
                forbidden=[f"SEMANTIC_CHAT_SEED_{run_id}"],
                required_prefix=marker,
                ordered_markers=["OBSERVE", "QUESTION", "VERIFY"],
                attempt="diagnostic",
            )
            result = semantic.execute_call(
                client,
                artifact_dir,
                args.device,
                run_id,
                spec,
                args.per_call_timeout,
                execution_meta,
            )
            results.append(result)
            semantic.atomic_json(artifact_dir / "results.json", results)
            print(f"preset_hidden_call={ordinal} passed={str(bool(result.get('passed'))).lower()}", flush=True)

        passed = len(results) == 5 and all(result.get("passed") is True for result in results)
        plugins_restored = semantic.recover_plugin_runtime(
            client,
            Path(str(plugin_state["root"])),
            "hidden-seed-preset-complete",
        )
        plugin_state = None
        preset_restored = semantic.recover_active_preset_runtime(
            client,
            artifact_dir / "active-preset-runtime",
            "hidden-seed-preset-complete",
        )
        preset_state = None
        chat_restored = semantic.restore_original_chat(
            client,
            artifact_dir,
            original_chat_id,
            f"PRESET-HIDDEN-{run_id}",
        )
        semantic.settle_plugin_runtime_ui(
            args.device,
            artifact_dir / "restore-webview-settle",
            "hidden-seed-preset-restored",
        )
        semantic.capture_phone(args.device, artifact_dir, "phone-after")
        passed = passed and plugins_restored and preset_restored and chat_restored
        manifest.update(
            {
                "finishedAt": semantic.now_utc(),
                "status": "passed" if passed else "failed",
                "modelRequestsSent": len(results),
                "modelRequestsPassed": sum(1 for result in results if result.get("passed")),
                "pluginsRestored": plugins_restored,
                "activePresetRestored": preset_restored,
                "restoredOriginalChat": chat_restored,
                "countsTowardKpi": False,
            }
        )
        semantic.atomic_json(manifest_path, manifest)
        print(f"artifact_dir={artifact_dir}")
        print(f"status={manifest['status']}")
        return 0 if passed else 1
    except Exception as exc:  # noqa: BLE001
        plugins_restored = True
        preset_restored = True
        chat_restored = original_chat_id is None
        if plugin_state is not None:
            try:
                plugins_restored = semantic.recover_plugin_runtime(
                    client,
                    Path(str(plugin_state["root"])),
                    "hidden-seed-preset-fatal",
                )
            except Exception:  # noqa: BLE001
                plugins_restored = False
        if preset_state is not None:
            try:
                preset_restored = semantic.recover_active_preset_runtime(
                    client,
                    artifact_dir / "active-preset-runtime",
                    "hidden-seed-preset-fatal",
                )
            except Exception:  # noqa: BLE001
                preset_restored = False
        if original_chat_id is not None:
            try:
                chat_restored = semantic.restore_original_chat(
                    client,
                    artifact_dir,
                    original_chat_id,
                    f"PRESET-HIDDEN-{run_id}-fatal",
                )
            except Exception:  # noqa: BLE001
                chat_restored = False
        manifest.update(
            {
                "finishedAt": semantic.now_utc(),
                "status": "failed",
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "modelRequestsSent": len(results),
                "pluginsRestored": plugins_restored,
                "activePresetRestored": preset_restored,
                "restoredOriginalChat": chat_restored,
                "countsTowardKpi": False,
            }
        )
        semantic.atomic_json(manifest_path, manifest)
        print(traceback.format_exc(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
