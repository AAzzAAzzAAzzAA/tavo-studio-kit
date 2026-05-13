# 贡献说明

这个目录是 TypeScript Dev Kit。仓库主入口在 `../skills/tavo-studio/`。

修改 SDK、mock、schema、生成器或 probe 行为前，先跑本地检查：

```bash
npm run verify:local
```

如果你已经有安卓模拟器和 Tavo，可以额外运行：

```bash
npm run verify:all
```

不要提交 `.env.local`、私有端点 key、私人截图或未脱敏报告。
