# 安全说明

不要发布 API key、私有端点地址、私人聊天内容、未脱敏报告或私人截图。

本地密钥应放在 `.env.local`，这个文件已被 Git 忽略，也不会进入分享包。

分享日志前请脱敏：

- `Authorization` header
- bearer token
- API key
- 私有模型端点
- 私人聊天内容

如果发现这个工具包自身的安全问题，可以在 GitHub 仓库里开安全反馈；如果问题属于 Tavo App 本身，应反馈给 Tavo 维护者。
