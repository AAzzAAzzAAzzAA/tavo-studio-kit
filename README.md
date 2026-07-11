# Tavo Skill

面向 Tavo 的百科式 Codex Skill，覆盖软件能力问答与创作工作流，并以当前官方文档、Tavo MCP 运行面和 Android 真机证据区分“官方声明”与“实际验证”。

## 包含内容

- Tavo 能力边界与非常规需求判断。
- 角色卡、人格、开场白和对话示例。
- 世界书、预设、正则、宏、EJS 与长记忆。
- Advanced Rendering、TavoJS 与 `.tpg` 插件。
- 图片、语音、设置、数据和 MCP 工作流。
- Android 真机验证脚本、测试矩阵与保留证据。

## 安装

```bash
mkdir -p ~/.codex/skills
cp -R skills/tavo ~/.codex/skills/tavo
```

之后在 Codex 中使用 `$tavo`，或直接提出 Tavo 能力、创作、调试与验证需求。

## 证据原则

Skill 将“声明面”和“运行可靠性”分开判断：

1. 当前官方文档用于确认产品公开声明。
2. 当前 MCP schema 与 runtime docs 用于确认机器可见接口。
3. Android 真机实验用于确认实际效果、渲染、持久化和回归。
4. 历史材料只作为待验证素材，不覆盖当前证据。

详见 [`skills/tavo/SKILL.md`](skills/tavo/SKILL.md)。

## 历史版本

旧 `tavo-studio` Skill 和 Dev Kit 已从主分支移除，完整备份保留在 Git 标签：

```text
legacy-tavo-studio-kit-2026-07-11
```

## License

MIT，见 [LICENSE](LICENSE)。
