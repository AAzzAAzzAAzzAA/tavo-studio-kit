# Tavo Dev Kit

Local-first development kit for generating importable Tavo assets, testing AI-written scripts against a mock `tavo` API, and building standalone Advanced Rendering widgets.

This package is the auxiliary SDK/CLI for the repository's main `skills/tavo-studio` workflow. It is **not an official Tavo SDK**.

## Quick Start

```bash
npm install
npm run verify:local
npm run build:assets
```

Generated import files are written to `dist/tavo-import/`.

## Commands

```bash
npm run typecheck
npm test
npm run build
npm run build:assets
npm run build:widget
npm run package:zip
npm run check:release
npm run verify:local
```

## Public Surface

- `TavoApi`: typed official-style `tavo.*` interface for variables, messages, chat, resources, memory, generate, input, utils, and app version.
- `createMockTavo()`: local mock runtime for script tests.
- `defineTavoScript()`: typed entry for AI-written scripts.
- `createTavoSDK()` / `tavoSDK`: optional helper wrapper for local development.
- `buildTavoAssets()`: generates character card, worldbook, regex, preset, AR direct HTML, AR widget HTML, regex draft, manifest, and test report JSON.
- `buildArWidgetFiles()`: builds `templates/ar-widget/widget.html|css|js` into single-file HTML plus regex draft.

Final Tavo runtime code should still prefer direct `tavo.*` calls.

## Optional Android Probe

Most users can ignore this. If you already have an Android emulator with Tavo installed, `npm run probe:android` and `npm run verify:all` can import generated assets into the real app and write redacted evidence to `reports/latest/`.

## Boundaries

- The mock is a test double, not Tavo itself.
- JSON schema checks prove known import shape, not future Tavo compatibility.
- Optional Android probe evidence is useful when rerun against the Tavo version you care about, but it is not required for normal local use.
- `.env.local`, `dist/`, and `reports/` should not be committed.
