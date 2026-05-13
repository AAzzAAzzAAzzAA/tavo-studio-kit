# Optional Android Verification

Most users do not need this. This page is for maintainers who already have an Android emulator with Tavo installed and want extra real-app evidence.

## Requirements

- Android emulator running and reachable through `adb`
- Tavo installed on the emulator
- Package name: `app.bitbear.tav`
- Advanced Rendering and JavaScript support enabled when script probes need them
- Optional OpenAI-compatible endpoint configured in `.env.local`
- The bundled helper `dev-kit/scripts/tavo-adb` available, or `TAVO_ADB_BIN` pointing to a compatible helper

Example `.env.local`:

```bash
TAVO_OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
TAVO_OPENAI_API_KEY=sk-replace-me
TAVO_OPENAI_MODEL=your-model-id
TAVO_DEVICE=emulator-5554
```

## Commands

```bash
cd dev-kit
npm run probe:android
npm run verify:all
```

`verify:all` runs local checks first, then Android probes. Community users can stop at `npm run verify:local`.

## What The Probe Verifies

- Tavo is reachable through ADB.
- App version and foreground state can be recorded.
- Generated files are pushed to `/sdcard/Download/codex-devkit-*`.
- Regex, worldbook, preset, and character card JSON can be imported through Tavo UI.
- AR direct HTML can execute JavaScript and call `tavo.set(...)`.
- AR widget HTML can render `AR_WIDGET_OK`.
- Regex JS can render `REGEX_JS_OK` after the imported regex group is applied to the current chat.
- `/models` and a short chat completion can be tested when endpoint env vars are provided.

## Regex JS Detail

Importing a regex group does not automatically prove that the current chat is using it.

The probe uses this path:

1. Import the generated regex JSON.
2. Open the generated character chat.
3. Open `聊天设定 -> 正则`.
4. Select `<suite>.regex`.
5. Tap `应用`.
6. Return to chat.
7. Send `CODEX_DEVKIT_REGEX_JS`.
8. Pass only when `REGEX_JS_OK` appears.

Source text is not enough proof. The probe requires an observable app-side result.

## Safety Rules

The probe should not:

- clear app data
- uninstall Tavo
- restore backups
- delete user resources
- directly modify ObjectBox data

Generated resources intentionally use `codex-devkit-*` names and may remain in the emulator for inspection.
