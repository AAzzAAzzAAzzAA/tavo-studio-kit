# Tavo Dev Kit

`dev-kit/` 是 `tavo-studio` skill 的辅助工具，用来做本地类型检查、mock 测试、资源生成和打包。

## 快速开始

```bash
npm install
npm run verify:local
npm run build:assets
```

生成结果会写入 `dist/tavo-import/`。

## 常用命令

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

## 公开能力

- `TavoApi`：官方风格 `tavo.*` 的 TypeScript 类型。
- `createMockTavo()`：本地 mock 运行环境。
- `defineTavoScript()`：AI 写脚本时的类型入口。
- `createTavoSDK()` / `tavoSDK`：可选便捷包装层。
- `buildTavoAssets()`：生成角色卡、世界书、正则、预设、AR HTML、manifest 和测试报告。
- `buildArWidgetFiles()`：把 `templates/ar-widget/widget.html|css|js` 打成单文件 HTML 和正则草稿。

最终导入 Tavo 的脚本建议直接写 `tavo.*`，不要依赖 npm import。

## 可选真实 App 验证

普通用户可以忽略这一项。已有安卓模拟器和 Tavo 的维护者，可以运行：

```bash
npm run probe:android
npm run verify:all
```

报告会写入 `reports/latest/`，不要提交到 Git。

## 边界

- mock 是本地测试替身，不等于真实 Tavo App。
- schema 校验只能证明已知导入结构，不代表未来版本永远兼容。
- `.env.local`、`dist/`、`reports/` 不应提交。
