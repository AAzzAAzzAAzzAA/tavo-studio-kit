#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

import run_phone_semantic_kpi as semantic


def main() -> int:
    parser = argparse.ArgumentParser(description="Run two non-counting live EJS runtime proofs.")
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
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    run_id = f"EJSDIAG{stamp}"
    endpoint = semantic.load_endpoint(args.endpoint_json)
    client = semantic.TavoMcp(str(endpoint.get("url") or ""), str(endpoint.get("auth") or ""))
    global_lock_handle, global_lock_identity = semantic.acquire_phone_runtime_lock(
        args.device,
        str(endpoint.get("url") or ""),
    )
    runner_bundle = semantic.runner_bundle_records()
    manifest_path = artifact_dir / "run-manifest.json"
    manifest = {
        "case": "non-counting-ejs-runtime-diagnostic",
        "status": "running",
        "runId": run_id,
        "startedAt": semantic.now_utc(),
        "targetCalls": 2,
        "countsTowardKpi": False,
        "retention": "leave-in-place",
        "globalRuntimeLockIdentity": global_lock_identity,
        "diagnosticEntrySha256": semantic.sha256(Path(__file__).resolve()),
        "semanticRunnerBundle": runner_bundle,
        "semanticRunnerBundleHash": semantic.stable_hash(runner_bundle),
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

        character = semantic.ensure_character(client, artifact_dir, run_id)
        persona = semantic.ensure_neutral_persona(client, artifact_dir, run_id)
        preset = semantic.ensure_neutral_preset(client, artifact_dir, run_id)
        plugin = semantic.ensure_semantic_plugin(client, artifact_dir, run_id)
        chats = []
        for ordinal in range(1, 3):
            chat = semantic.ensure_chat(
                client,
                artifact_dir,
                run_id,
                "ejs-runtime-diagnostic",
                ordinal,
                {
                    "characterIds": [int(character["id"])],
                    "personaId": int(persona["id"]),
                    "presetId": int(preset["id"]),
                },
            )
            semantic.ensure_chat_seed(
                client,
                artifact_dir,
                run_id,
                "ejs-runtime-diagnostic",
                ordinal,
                chat,
            )
            chats.append(chat)

        preset_state = semantic.snapshot_active_preset_runtime(
            client,
            artifact_dir / "active-preset-runtime",
            f"EJS-DIAG-{run_id}",
        )
        plugin_state = semantic.isolate_plugin_runtime(
            client,
            artifact_dir / "plugin-isolation",
            str(plugin["id"]),
            f"EJS-DIAG-{run_id}",
            str(plugin["readbackHash"]),
        )
        semantic.settle_plugin_runtime_ui(
            args.device,
            artifact_dir / "plugin-isolation" / "webview-settle",
            "ejs-runtime-diagnostic",
        )
        execution_meta = {
            "diagnosticId": f"EJS-DIAG-{run_id}",
            "entryHash": manifest["diagnosticEntrySha256"],
            "runnerBundleHash": manifest["semanticRunnerBundleHash"],
        }
        questions = [
            f"请原样复制 [EJS-EXTERNAL:{run_id}] 整行，再原样给出 EJS-SET-GET 的值。",
            f"请原样复制 [EJS-EXTERNAL:{run_id}] 整行，再说明 EJS-CONDITION 命中了哪个分支。",
        ]
        expected = [f"SET_{run_id}", "ALPHA"]
        for ordinal in range(1, 3):
            nonce = semantic.nonce_for(run_id, "macro-ejs", ordinal)
            spec = semantic.CallSpec(
                family="macro-ejs",
                ordinal=ordinal,
                chat_id=int(chats[ordinal - 1]["id"]),
                prompt=semantic.with_nonce_after_context_prefix(
                    questions[ordinal - 1], nonce, "assistant 角色卡"
                ),
                nonce=nonce,
                expected=[
                    f"[EJS-CARD-{run_id}]",
                    f"[EJS-EXTERNAL:{run_id}]",
                    expected[ordinal - 1],
                ],
                forbidden=["<%", "{{char}}", "{{user}}", "EJS_EXTERNAL_MISSING"],
                mode="ejs-runtime",
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
            print(f"ejs_diagnostic_call={ordinal} passed={str(bool(result.get('passed'))).lower()}", flush=True)

        tokens = [str(result.get("ejsRuntimeEvidence", {}).get("runtimeValue") or "") for result in results]
        passed = bool(
            len(results) == 2
            and all(result.get("passed") is True for result in results)
            and len(set(tokens)) == 2
            and all(tokens)
        )
        plugins_restored = semantic.recover_plugin_runtime(
            client,
            Path(str(plugin_state["root"])),
            "ejs-diagnostic-complete",
        )
        plugin_state = None
        preset_restored = semantic.recover_active_preset_runtime(
            client,
            artifact_dir / "active-preset-runtime",
            "ejs-diagnostic-complete",
        )
        preset_state = None
        chat_restored = semantic.restore_original_chat(
            client,
            artifact_dir,
            original_chat_id,
            f"EJS-DIAG-{run_id}",
        )
        semantic.capture_phone(args.device, artifact_dir, "phone-after")
        passed = passed and plugins_restored and preset_restored and chat_restored
        manifest.update(
            {
                "finishedAt": semantic.now_utc(),
                "status": "passed" if passed else "failed",
                "modelRequestsSent": len(results),
                "modelRequestsPassed": sum(1 for result in results if result.get("passed")),
                "uniqueRuntimeTokens": len(set(tokens)),
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
                    "ejs-diagnostic-fatal",
                )
            except Exception:  # noqa: BLE001
                plugins_restored = False
        if preset_state is not None:
            try:
                preset_restored = semantic.recover_active_preset_runtime(
                    client,
                    artifact_dir / "active-preset-runtime",
                    "ejs-diagnostic-fatal",
                )
            except Exception:  # noqa: BLE001
                preset_restored = False
        if original_chat_id is not None:
            try:
                chat_restored = semantic.restore_original_chat(
                    client,
                    artifact_dir,
                    original_chat_id,
                    f"EJS-DIAG-{run_id}-fatal",
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
