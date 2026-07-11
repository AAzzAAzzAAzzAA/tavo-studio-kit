# Phone Validation Runbook

This runbook fixes the real Android test method for Tavo. Do not rediscover the phone workflow from scratch unless the device, app, or MCP server changes in a way that invalidates this evidence.

## Current 0.92 Gate And User-State Anchor

`live-verified` gate artifact: `assets/evidence/0.92.0/20260716-gate.json`. Current atomic behavior summary: `assets/evidence/0.92.0/20260717-live-matrix.json`.

- Device identity redacted, model `24129PN74C`, Android 16.
- Package `app.bitbear.tav`, versionName `0.92.0`, versionCode `920`, running PID recorded in the gate artifact.
- MCP 70 tools, 18 resources, 7 templates, 0 prompts; five top-level reads, 17/17 docs/schema reads, and `tavo_status` passed.
- User state was preserved exactly: private chat identity omitted, 3 messages, blank input.
- The gate is transport/readiness evidence only. Promote 0.92 behavior only from the atomic matrix, retaining its mixed/manual/blocked boundaries.

## Prior 0.91 Method Baseline

- Device serial: private and omitted from public evidence.
- Device model: `24129PN74C`.
- Android version: `16`.
- Screen: `1200x2670`, density `520`.
- Package: `app.bitbear.tav`.
- App version during that smoke: `0.91.0`; use only as a prior-version regression control.
- UI framework: Flutter UI readable through UIAutomator for chat title, messages, input hint, focus state, and button bounds.
- MCP surface during smoke: `70` tools, `18` resources, `7` resource templates, `0` prompts. Current 0.92 counts happen to match, but capability content must still be read from the 0.92 dump.
- Accessibility service: not enabled during smoke. Record as blocked and use UI-tree bounds plus ADB tap.

## Required Preflight

Run these before any live validation case:

```bash
export TAVO_DEVICE="<adb-device-serial>"
adb devices -l
adb -s "$TAVO_DEVICE" shell dumpsys package app.bitbear.tav
adb -s "$TAVO_DEVICE" shell dumpsys window
adb -s "$TAVO_DEVICE" shell uiautomator dump /sdcard/window.xml
adb -s "$TAVO_DEVICE" exec-out screencap -p > screen-before.png
python3 scripts/dump_mcp_surface.py --strict --output <artifact-dir>
```

The strict gate must include `initialize`, `tools/list`, `resources/list`, `resources/templates/list`, `prompts/list`, all dynamically discovered docs/schema/capabilities/runtime reads, and one `tools/call -> tavo_status`. Save requested and negotiated protocol versions separately.

If the phone was asleep, recheck ICMP/TCP reachability and rerun MCP initialize after the screen wakes. Never reuse an old endpoint/token without rereading the current phone state.

## Operation Priority

1. MCP for state, dry-run, import, readback, binding, current-chat switching, and message send/read.
2. UIAutomator XML for locating controls by text, hint, class, `content-desc`, focus, and bounds.
3. ADB `input tap` from UI bounds when accessibility click is unavailable.
4. Clipboard/paste or input helper for long text and Chinese text.
5. Screenshot only for visual proof: Advanced Rendering, CSS, JS, plugin UI, layout, visible markers, and greeting selector.

## 0.92 Isolation And Backup Order

Before any write:

1. Capture user chat/input, current API binding, theme, voice playback rules, and every plugin enabled state.
2. Create full Backup A in a permission-restricted directory. Ordinary evidence records only filename alias, size, and SHA-256; never open or print backup contents.
3. Create unique ASCII-only test names/markers for roles, chats, plugins, and provider connections. Never send in the protected user chat recorded in the private run plan.
4. Run lower-risk plugin/input/generation/theme/media cases first.
5. Run Backup B restore only after other plugin cases pass. Any restore anomaly immediately stops later writes and triggers Backup A rollback.

The current 0.92 plan overrides the older broad leave-everything-enabled retention habit: test fixtures may remain installed as evidence but must finish disabled; temporary API connections and Mac services must be removed/stopped; user API/theme/voice/plugin state and the original protected chat with blank input must be restored.

## 0.92 Live Procedure Findings

- Runtime reload can produce a catch-up `chat:opened`; do not miscount it as the original transition or infer the missing `chat:updated` alias event from reload timing.
- Verify input and generation Hooks by source and by persisted message/provider capture. F06 proved UI/TavoJS/MCP input sources, while F09 showed that one generation source can regress independently of terminal semantics.
- Use a deterministic OpenAI-compatible fake gateway when real media credentials are unavailable. Record bounded request metadata and hashes, never audio/image bodies or credentials. A fake gateway proves protocol/integration only; human speech accuracy and audible TTS behavior remain manual.
- Native Backup B restore can restart Tavo. Compare complete pre/post state after the restart; require plugin id/version/config/enabled/runtime equality before disabling the restored fixture. Do not use same-PID continuity as a backup-restore acceptance condition.
- Live negative-package tests should stop once the required rejection boundary is proved. Keep ambiguous, missing-entry, backslash, and symlink fixtures in the offline validator unless a separate live test is explicitly needed.

## MCP Rules Learned From Smoke

- Use JSON-RPC method `tools/call` to invoke Tavo tools.
- Keep `mcp-direct-method-failed.json` as a negative regression case: direct tool-name RPC returned method-not-found behavior.
- Use dry-run before actual writes when the tool supports it.
- dryRun acceptance is not field preservation. Actual import plus readback/export comparison is required.
- `tavo_chat_update` with `expectedRevision` returned a false stale error during smoke. For smoke binding tests, read current state, dry-run without `expectedRevision`, actual update without it, read back, then restore.
- `tavo_input_get` can be UI-bound; if there is no active chat input, treat failure as active-screen state rather than permission failure.

## UI Rules Learned From Smoke

- The chat input was located by `android.widget.EditText` and bounds.
- ADB tap at the center of input bounds focused the field when accessibility click was unavailable.
- UI XML should be saved before and after each meaningful step.
- Screenshots should be paired with UI XML when the UI state matters.
- After an asynchronous import, dialog close, panel open/close, chat switch, or WebView rerender, capture fresh UI XML and a fresh screenshot. Do not reuse bounds from the previous state: stale or currently occluded nodes can remain in the accessibility tree briefly.
- Before tapping, require a positive-area target that is visible in the current screenshot and not covered by a dialog, panel, keyboard, or native composer. `clickable=true`, non-empty bounds, or an ADB return code of `0` does not prove the intended control received the touch.
- After tapping, verify the intended effect through a state change, input readback, message readback, or another target-specific signal.
- When a WebView or plugin control is close to Tavo's native composer or send control, run an actual touch A/B and verify which state changed. Do not infer the native hit region from the visible icon alone.
- Main chat UI may not visibly show chat-level lorebook binding; use MCP readback for that state.
- Switching to a newly created character chat can display a greeting selector. Capture the selector, confirm one greeting only when the test expects it, then capture the final chat screen.

## Composer Draft Lifecycle Boundary

Scoped observation on one Android device with Tavo `0.91.0`: clearing the composer and immediately reading an empty value did not guarantee that it stayed empty after chat navigation; the native draft-restoration layer could reload the earlier text.

- Treat immediate clear/readback as an atomic effect, not a persistence guarantee.
- After a chat switch, WebView reload, fragment remount, or app resume, clear sensitive or test text again and verify both composer readback and the current screenshot.
- Keep this as a version- and device-scoped validation boundary until a retained multi-device or newer-version test proves broader behavior.

## TavoJS Native-Bridge Resource Gate

Use this gate for plugins that make repeated TavoJS calls on Android, especially while validating Tavo `0.91.0`:

1. Record the Tavo PID before the first round and fail the comparison if the PID changes.
2. Record `FDSize` from `/proc/<pid>/status` and, when permitted, the actual entry count under `/proc/<pid>/fd` before and after each round.
3. Run at least three complete rounds in the same PID and include a 3–5 second idle window after each round to detect background polling.
4. Add a control using the native Tavo send path with the plugin disabled or inactive.
5. Search logcat for `HyperSentinel`, held-FD warnings, `too many open files`, ANR, fatal, and crash signals.
6. Report blocked `/proc` access honestly; do not substitute `FDSize` for the actual held-FD count.

Do not accept one successful round as stability proof. A resource regression can be cumulative while the first visible result still succeeds.

If the same UI/runtime blocker repeats twice, stop blind retries. Classify it as `blocked` or turn it into a precise manual step with the expected success marker.

## Artifact Layout

Each live run writes:

```text
artifacts/tavo-validation/YYYYMMDD-<case>/
  run-manifest.json
  device.txt
  adb-devices.txt
  mcp_surface.json
  mcp-requests-redacted.jsonl
  mcp-responses-redacted.jsonl
  ui-before.xml
  ui-after.xml
  screen-before.png
  screen-after.png
  readback.json
  notes.md
```

Optional files: `screen-mid.png`, `ui-mid.xml`, `screen.webm`, per-step JSON files, exported artifacts, diff reports, and cleanup proof only for explicit cleanup/restore tests.

## Retention And Cleanup Policy

The general preference is effect-first validation with durable evidence. For this 0.92 epoch, retain isolated fixture source/evidence and installed fixtures only when the plan calls for it, leave retained plugins disabled, and restore all user-facing state. Do not delete historical 0.91 evidence objects merely to make the 0.92 run look clean.

Every actual write must still be registered:

- object type;
- object id;
- object name;
- creation tool;
- retention decision: `leave-in-place`, `restore-binding`, or `cleanup-case`;
- cleanup tool or restore route when cleanup is explicitly part of the test;
- readback proof;
- final proof that the retained object/file exists or that the requested restore happened.

For binding/switch cases, restore the user's active binding only when the test temporarily changed it and the restore is part of preserving the working test environment. Retain the imported disposable objects unless cleanup is explicitly requested.

If an explicit cleanup case is run, delete or restore in reverse dependency order: messages/chats, then characters/personas/lorebooks/regexes/presets/plugins. Verify cleanup with readback proof, not just a successful delete response.

Known smoke leftovers to account for before future destructive cleanup planning:

- lorebook id `2`, name `Codex Method Smoke Lorebook 20260709-220900`;
- character id `3`, name `Codex Method Smoke Character 20260709-221256`;
- chat id `3`, linked to character id `3`.

Do not delete these automatically. Treat them as retained validation evidence unless the user asks for cleanup.

## First Repeatable Cases

Prioritize these because they exercise the proven method:

1. `phone-preflight`: device/app/MCP/UI/screenshot.
2. `mcp-message-send-read`: MCP input set/get/send plus message readback.
3. `lorebook-import-switch`: dryRun, actual import, bind, readback, restore.
4. `character-import-chat-switch`: card dryRun, actual import, chat create, current-chat switch, greeting selector handling.
5. `ar-visible-marker`: import/render a harmless marker and prove with screenshot.
6. `plugin-minimal-package`: validate/package/import a minimal plugin and prove registration or documented failure.

For the 0.92 plugin/runtime epoch, use `scripts/run_phone_plugin_092_matrix.py` to enumerate and stage the guarded cases. Its offline modes do not contact ADB/MCP; live staging requires at least one explicit `--protected-chat-id`, refuses every protected chat, requires an isolated chat plus explicit confirmation, installs unique fixtures disabled, never sends input/messages during staging, and classifies missing runtime evidence as `blocked` rather than passed. Hook triggers and semantic evidence remain separate retained steps.

## KPI Batch Rule

When the user asks for effect-first exhaustive validation, use `scripts/run_phone_kpi_batch.py` instead of hand-assembling repeated MCP calls. The current stress KPI is:

- import at least `50` retained test assets/files into the real phone;
- send at least `50` real chat messages through Tavo so the app uses its configured model API;
- retain the imported assets, test chats, plugin files, screenshots, MCP request/response JSON, and model-message evidence;
- write `run-manifest.json` with `successfulImports`, `modelApiCallsAttempted`, and `modelApiCallsCompleted`.

The KPI batch does not replace targeted semantic tests. It proves volume, MCP write/read stability, and real model-call path health; worldbook trigger semantics, regex transformations, EJS expansion, AR layout, and TavoJS lifecycle still need dedicated matrix rows.

## Exact Provider-Request Capture

Use `scripts/tavo_request_capture_gateway.py` only when the unresolved question is about the final provider payload: EJS/macro expansion, message roles, prompt order, escaping, option forwarding, or raw-tag leakage. Do not route ordinary documented-fact tests through it.

Operational rules:

1. Bind to the Mac LAN address, require a temporary client key, and allow only the phone and local test source IPs.
2. Read the upstream and client keys from mode-`0600` files; let the gateway unlink them after startup. Never put keys in commands, Skill files, captures, or notes.
3. Configure Tavo manually with the LAN `/v1` base, temporary gateway key, and exact upstream model ID. Do not let automation rewrite the user's provider settings.
4. Prove `/v1/models` from the phone once, then send the smallest normal chat case that resolves the payload question.
5. Inspect the redacted capture body, pair it with stable message readback, restore the previous chat, stop the gateway, and retain the capture directory.

The gateway blocks upstream redirects, relays SSE incrementally, caps bodies, redacts common credential fields and values, and writes private capture files. Its offline contract is covered by `scripts/test_tavo_request_capture_gateway.py`.

## ASR Last-Step Rule

ASR is absent from the current official crawl and 0.92 MCP surface. Inspect native UI, Android microphone permission, provider schema, and redacted logs without a key first. A deterministic OpenAI-compatible fake gateway is acceptable for multipart request, transcript, cancel/fill/edit, and controlled failure-path integration tests. If a real-provider key is required, pause for the user to enter a temporary revocable key directly on the phone. Never transmit it through chat, ADB, CLI, screenshots, logs, or Skill files.

Run speech input last because it may require human voice and permission changes. Use one fixed harmless phrase, then classify recognition, cancel, permission denial, network failure, and edit-before-send separately. Human audio/voice judgments remain manual and must not be reported as automated passes.

The iOS immersive-mode quick-scroll repair is `not-applicable` on this Android run.

## Final Restoration Gate

Before declaring the epoch complete:

- return to the privately recorded original chat and verify its original message count and blank input;
- restore the original API, theme, voice rules, and every pre-existing plugin enabled state;
- disable retained 0.92 fixtures; remove temporary API connections; stop the local provider fixture;
- capture fresh UI XML/screenshot and MCP readback after restoration;
- confirm the Tavo PID did not change across the core three-round loop;
- rerun the ADB/MCP strict gate and compare counts/version/current state with the pre-write anchor;
- keep passed, failed, mixed, blocked, manual, and Android-not-applicable results in separate evidence classes.
