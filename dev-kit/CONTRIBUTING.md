# Contributing

This folder contains the auxiliary TypeScript Dev Kit. The main repository entry is `../skills/tavo-studio`.

Run local checks before changing SDK or probe behavior:

```bash
npm run verify:local
```

Use `npm run verify:all` when an Android emulator with Tavo is available.

Do not commit `.env.local`, private endpoint keys, private screenshots, or unredacted probe reports.
