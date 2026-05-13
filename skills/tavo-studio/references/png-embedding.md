# PNG 角色卡嵌入说明

## 官方实现要点

SillyTavern 官方源码 `src/character-card-parser.js` 说明了当前 PNG 卡的核心机制：

1. 角色卡 JSON 先序列化为字符串
2. 再做 base64
3. 写进 PNG 的 `tEXt` chunk
4. 关键字使用 `chara`
5. 读取时如果有 `ccv3` 会优先读 `ccv3`，否则读 `chara`

这意味着：

- PNG 卡本质上是“图片 + 内嵌 JSON”
- 分享给别人时，一个 PNG 文件就能携带角色数据
- 为了版本管理，仍建议同时保留 `.json`
- 不要默认 Tavo 会读取 `chara` / `ccv3` 之外的自定义 chunk；正则、预设、脚本、备份信息即使塞进 PNG，也只能算打包携带，不能说会被自动识别导入

## 推荐实践

- 永远同时保留：
  - `character.card.json`
  - `character.card.png`
- 先改 JSON，再重新写入 PNG
- 不要把 PNG 当成唯一真源

## 什么时候需要重新嵌入

以下任意一种修改后都应重新生成 PNG：

- 改了角色设定字段
- 改了 `mes_example`
- 改了 `alternate_greetings`
- 改了 `data.character_book`
- 改了 `extensions.world`

## 命令

写入：

```bash
node skills/tavo-studio/scripts/embed_st_card_png.mjs \
  --png "/path/to/base.png" \
  --json "/path/to/character.card.json" \
  --out "/path/to/character.card.png" \
  --overwrite
```

提取：

```bash
node skills/tavo-studio/scripts/extract_st_card_png.mjs \
  --png "/path/to/character.card.png" \
  --out "/path/to/extracted.card.json"
```

## 验证方法

写入后立即再抽取一次，确保：

1. 能成功读出 JSON
2. `spec = "chara_card_v2"`
3. 关键字段没丢
4. 如果你依赖卡内 lore，`data.character_book.entries` 数量正确

## 典型工作流

1. 复制一张立绘 PNG 当底图
2. 先完成 `character.card.json`
3. 用脚本嵌入成 `character.card.png`
4. 导入 ST
5. 如果后续继续改卡，始终以 JSON 为主，再重新嵌入 PNG
