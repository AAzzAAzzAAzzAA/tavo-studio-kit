# Tavo Studio Kit

非官方 Tavo 创作与验证工具包。这个仓库以 **Tavo Studio skill** 为主，`dev-kit/` 里的 TypeScript SDK/CLI 为辅助验证工具。

它的目标不是替代 Tavo 官方，也不是把 Tavo 变成 npm 运行时，而是帮助 AI 和人类更稳定地完成这些事：

- 理解 Tavo / SillyTavern 角色卡、世界书、预设、正则、宏、长记忆、高级前端渲染和 JavaScript API 的边界。
- 产出可导入 Tavo 的资源文件。
- 用本地 mock、类型检查和 JSON schema，把“看起来能用”变成“至少本地跑过测试”。

## Repository Layout

```text
skills/tavo-studio/   Main Codex skill: Tavo knowledge, workflows, references, scripts, templates
dev-kit/              Auxiliary TypeScript dev kit: mock, asset generation, local validation
docs/                 Release notes and community post draft
```

## What Is Included

### Tavo Studio Skill

`skills/tavo-studio/` 是主入口。它包含：

- `SKILL.md`：AI agent 加载后应遵守的 Tavo 工作流和边界。
- `references/`：Tavo/ST 相关能力说明和创作参考。
- `scripts/`：PNG 角色卡嵌入/提取、世界书转换等辅助脚本。
- `assets/templates/`：角色卡和世界书模板。

### Dev Kit

`dev-kit/` 是辅助验证工具。它包含：

- `TavoApi` 类型。
- `createMockTavo()` 本地 mock。
- `defineTavoScript()` 脚本入口。
- `createTavoSDK()` / `tavoSDK` 可选包装层。
- Tavo 可导入资源生成器。
- AR widget 单文件构建。
- Optional Android probe for maintainers who already have an emulator.

Final Tavo runtime code should still prefer direct `tavo.*` calls. The SDK wrapper is for local development convenience.

## Install The Skill

For Codex-style local skills, copy or symlink the skill folder into your skill directory:

```bash
mkdir -p ~/.codex/skills
cp -R skills/tavo-studio ~/.codex/skills/tavo-studio
```

Then start a new Codex session and mention Tavo, character cards, worldbooks, regex, Advanced Rendering, or JavaScript API work so the skill can load.

## Use The Dev Kit

```bash
cd dev-kit
npm install
npm run verify:local
```

Generate importable Tavo assets:

```bash
npm run build:assets
```

Most users do not need an Android emulator. Maintainers who already have Tavo installed in an emulator can run the optional probe documented in [Android verification](docs/android-verification.md).

## Boundaries

- This project is not affiliated with or endorsed by Tavo.
- The skill is guidance and workflow, not proof by itself.
- The mock is a local test double, not the real app.
- Local checks prove the Dev Kit's types, mock behavior, generators, and schema assumptions. Optional Android checks can add real-app evidence when available.
- Do not publish `.env.local`, private endpoint keys, private chats, unredacted reports, or private screenshots.

## Docs

- [Optional Android verification](docs/android-verification.md)
- [Release checklist](docs/release-checklist.md)
- [Community post draft](docs/community-post.md)

## License

MIT. See [LICENSE](LICENSE).
