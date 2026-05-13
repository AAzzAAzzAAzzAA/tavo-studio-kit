# Contributing

Thanks for helping improve Tavo Dev Kit.

This project is a community helper, not an official Tavo SDK. The main entry is `skills/tavo-studio`; `dev-kit/` is the auxiliary test and generation tool.

## Development

```bash
cd dev-kit
npm install
npm run verify:local
```

Use `npm run verify:all` from `dev-kit/` when you have an Android emulator with Tavo available.

## Pull Request Checklist

- Prefer official-style `tavo.*` examples for scripts that will be pasted into Tavo.
- Keep `createTavoSDK()` as an optional local helper, not a required runtime dependency.
- Add or update Vitest coverage for mock, schema, generator, or wrapper behavior.
- Do not commit `.env.local`, private endpoint keys, private screenshots, or unredacted probe reports.
- If a change claims real Tavo behavior, include Android probe evidence or clearly mark it as mock-only.
- If Tavo changes a format or behavior, update README/docs and the probe expectations together.
- Keep the public skill free of machine-specific absolute paths and private local references.

## Android Probe Safety

The probe may import test resources into the emulator. It should not clear app data, uninstall Tavo, restore backups, or directly edit the app database.

Use the `codex-devkit-*` prefix for generated resources so test artifacts are easy to identify.
