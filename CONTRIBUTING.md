# Contributing

提交 Tavo 产品事实前，请标明证据来源，并遵循 `skills/tavo/SKILL.md` 中的 evidence labels。

- 官方能力应对应当前官方文档或当前 MCP runtime docs。
- 实际可用性结论应附可复现的 Android/MCP 证据。
- 不要把旧 Skill、旧缓存或历史 API 当作当前事实。
- 不要提交 API key、Bearer token、Cookie、账号信息或未脱敏请求。
- 不要提交 `skills/tavo/artifacts/`、设备序列号、IMEI、私有聊天 ID/标题、局域网 MCP 地址或用户绝对路径。

提交前运行：

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/tavo
python3 skills/tavo/scripts/audit_skill_skeleton.py skills/tavo
python3 skills/tavo/scripts/audit_tavo_skill.py skills/tavo
```
