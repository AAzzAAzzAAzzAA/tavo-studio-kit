# 可选真机验证

普通用户不需要这一项。这一页只给已经有安卓模拟器和 Tavo 的维护者使用，用来补充真实 App 证据。

## 准备

- 安卓模拟器可通过 `adb` 连接。
- 模拟器里已安装 Tavo。
- 包名为 `app.bitbear.tav`。
- 需要测试脚本时，Tavo 内已开启高级前端渲染和 JavaScript 支持。
- 如需测试模型端点，在 `.env.local` 里配置 OpenAI-compatible 端点。
- 使用内置 `dev-kit/scripts/tavo-adb`，或通过 `TAVO_ADB_BIN` 指向兼容脚本。

`.env.local` 示例：

```bash
TAVO_OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
TAVO_OPENAI_API_KEY=sk-replace-me
TAVO_OPENAI_MODEL=your-model-id
TAVO_DEVICE=emulator-5554
```

## 命令

```bash
cd dev-kit
npm run probe:android
npm run verify:all
```

`verify:all` 会先跑本地检查，再跑真实 App probe。普通用户停在 `npm run verify:local` 即可。

## probe 会检查什么

- Tavo 能被 ADB 打开。
- 能记录 App 版本和前台状态。
- 能把生成文件推送到 `/sdcard/Download/codex-devkit-*`。
- 正则、世界书、预设、角色卡 JSON 能通过 Tavo UI 导入。
- AR direct HTML 能执行 JS 并调用 `tavo.set(...)`。
- AR widget HTML 能显示成功标记。
- 正则 JS 在应用到当前聊天后能显示成功标记。
- 配置端点后，可以测试 `/models` 和最短 chat completion。

## 正则 JS 注意点

导入正则组不代表当前聊天已经使用它。

probe 的路径是：

1. 导入生成的正则 JSON。
2. 打开生成角色的聊天。
3. 进入 `聊天设定 -> 正则`。
4. 选择 `<suite>.regex`。
5. 点击 `应用`。
6. 回到聊天。
7. 发送测试 marker。
8. 只有出现可见成功标记才算通过。

只看到 `<script>` 源码不算 JS 执行成功，必须有可观察结果。

## 安全规则

probe 不应该：

- 清空 App 数据
- 卸载 Tavo
- 恢复备份
- 删除用户资源
- 直接修改 ObjectBox 数据

生成资源使用 `codex-devkit-*` 前缀，方便识别和复查。
