# 发布检查清单

公开发布前建议跑一遍。

## 仓库准备

- 单独创建 `tavo-studio-kit` 仓库。
- 在发布副本目录里初始化 Git，不要直接推父级工作区。
- 确认 `.env.local`、`dist/`、`reports/`、`node_modules/` 没有被跟踪。
- 发布前轮换本地测试用过的临时 key。

## 本地检查

```bash
cd dev-kit
npm install
npm run verify:local
```

普通社区用户只需要 `npm run verify:local`。

已有设备环境的维护者可以额外跑：

```bash
npm run verify:all
```

## 人工复查

- README 使用中文为主。
- README 说明 `skills/tavo-studio/` 是主入口，`dev-kit/` 是辅助工具。
- 安卓/真实 App 检查只作为可选维护者流程，不写成安装要求。
- `dev-kit/.env.example` 只包含占位符。
- `.env.local` 没有暂存。
- `reports/` 没有暂存。
- `dist/tavo-import/` 没有暂存。
- 没有私人截图、私人端点日志或未脱敏报告。
- `LICENSE` 存在。
- `skills/tavo-studio/SKILL.md` 不包含本机绝对路径。

## 建议首个 tag

```bash
git tag v0.1.0
```

建议 release 标题：

```text
Tavo Studio Kit v0.1.0：以 skill 为主的 Tavo 创作与本地验证工具包
```
