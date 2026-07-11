# Security

Tavo 插件、Advanced Rendering、TavoJS、MCP 和请求捕捉脚本可能接触模型请求、聊天内容与外部服务。

- 只安装可信 `.tpg` 文件。
- 测试凭据使用假 token；真实凭据不得进入仓库或证据包。
- 发布真机证据前扫描 Authorization、API key、Cookie、本机路径和局域网地址。
- 原始真机采集只保存在私有工作区；公开仓库忽略 `skills/tavo/artifacts/`，只接受 `assets/evidence/` 下经过脱敏的摘要。
- 安全问题请通过 GitHub 私密漏洞报告联系维护者。
