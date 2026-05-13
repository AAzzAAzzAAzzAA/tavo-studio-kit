# Tavo Studio Kit

面向 Tavo 创作的第三方工具包。仓库以 `tavo-studio` skill 为主，`dev-kit/` 作为辅助验证工具。

它主要解决一个问题：让 AI 写 Tavo 角色卡、世界书、预设、正则和高级前端渲染脚本时，有一套可以反复参考和本地检查的工作流。

## 仓库结构

```text
skills/tavo-studio/   主体：Tavo Studio skill、参考资料、脚本和模板
dev-kit/              辅助：类型、mock、资源生成、本地校验
docs/                 发布检查、社区介绍、可选真机验证说明
```

## 包含什么

### Tavo Studio Skill

`skills/tavo-studio/` 是主入口：

- `SKILL.md`：AI agent 加载后遵守的 Tavo 工作流和边界。
- `references/`：角色卡、世界书、预设、正则、宏、长记忆、高级前端渲染、JS API 等参考资料。
- `scripts/`：PNG 角色卡嵌入/提取、世界书转换等辅助脚本。
- `assets/templates/`：角色卡和世界书模板。

### Dev Kit

`dev-kit/` 是辅助工具：

- `TavoApi` 类型提示。
- `createMockTavo()` 本地 mock。
- `defineTavoScript()` 脚本入口。
- `createTavoSDK()` / `tavoSDK` 可选包装层。
- Tavo 可导入资源生成器。
- AR widget 单文件构建。
- 可选真实 App 验证，适合已经有设备环境的维护者。

最终放进 Tavo 的脚本建议直接写官方风格的 `tavo.*` 调用；包装层主要用于本地开发体验。

## 安装 Skill

把 skill 复制到本地 Codex skills 目录：

```bash
mkdir -p ~/.codex/skills
cp -R skills/tavo-studio ~/.codex/skills/tavo-studio
```

之后新开 Codex 会话，提到 Tavo、角色卡、世界书、正则、高级前端渲染或 JavaScript API 时，就可以加载这个 skill。

## 使用 Dev Kit

```bash
cd dev-kit
npm install
npm run verify:local
```

生成 Tavo 可导入资源：

```bash
npm run build:assets
```

普通用户不需要安卓模拟器。已有设备环境的维护者可以参考 [可选真机验证](docs/android-verification.md)。

## 边界

- skill 负责提供工作流和参考资料，本身不等于运行结果。
- mock 是本地测试替身，不等于真实 Tavo App。
- 本地检查能验证类型、mock、生成器和已知 schema；真实 App 行为需要额外验证。
- 不要提交 `.env.local`、私有端点 key、私人聊天、未脱敏报告或截图。

## 文档

- [可选真机验证](docs/android-verification.md)
- [发布检查清单](docs/release-checklist.md)
- [社区介绍草稿](docs/community-post.md)

## 许可

MIT，见 [LICENSE](LICENSE)。
