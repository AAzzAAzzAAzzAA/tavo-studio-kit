# Release Checklist

Use this before pushing a public GitHub release.

## One-Time Repository Setup

- Create a new standalone GitHub repository for `tavo-studio-kit`.
- Initialize Git inside this repository folder, not in the parent local workspace.
- Keep `.env.local`, `dist/`, `reports/`, and `node_modules/` untracked.
- Rotate any temporary API key that was ever used locally before publishing.

## Local Checks

```bash
cd dev-kit
npm install
npm run verify:local
```

Optional maintainer-only real-app probe:

```bash
npm run verify:all
```

Most community users only need `npm run verify:local`.

## Manual Review

- README says the project is not official.
- README presents `skills/tavo-studio` as the main entry and `dev-kit` as auxiliary.
- README presents emulator checks as optional maintainer verification, not a normal installation requirement.
- `dev-kit/.env.example` contains placeholders only.
- `.env.local` is not staged.
- `reports/` is not staged.
- `dist/tavo-import/` is not staged.
- No private screenshots or private endpoint logs are committed.
- `LICENSE` is present.
- `skills/tavo-studio/SKILL.md` contains no private absolute paths.

## Suggested First Tag

Use a preview tag until more people test it:

```bash
git tag v0.1.0
```

Suggested release title:

```text
Tavo Studio Kit v0.1.0 - skill-first Tavo workflow with local Dev Kit validation
```
