# 贡献说明

感谢你愿意改进 Tavo Studio Kit。

这个仓库的主入口是 `skills/tavo-studio/`，`dev-kit/` 是辅助的本地检查和资源生成工具。

## 开发检查

```bash
cd dev-kit
npm install
npm run verify:local
```

如果你已经有安卓模拟器和 Tavo，可以在 `dev-kit/` 里额外运行：

```bash
npm run verify:all
```

## 提交前检查

- 放进 Tavo 的示例脚本优先直接使用 `tavo.*`。
- `createTavoSDK()` 只作为本地开发辅助，不要让它成为 Tavo 运行时依赖。
- 修改 mock、schema、生成器或包装层时，同步补测试。
- 不要提交 `.env.local`、私有端点 key、私人截图或未脱敏报告。
- 如果改动声称真实 Tavo 行为，最好提供真实 App 验证证据；没有证据时要标明只是本地 mock 或格式推断。
- Tavo 格式或行为变化时，同时更新 README、docs 和测试预期。
- 公开版 skill 不要包含本机绝对路径或私人文件引用。

## 可选真机验证安全规则

真实 App probe 可能会导入测试资源。它不应该清空 App 数据、卸载 Tavo、恢复备份或直接编辑数据库。

生成资源统一使用 `codex-devkit-*` 前缀，方便识别和复查。
