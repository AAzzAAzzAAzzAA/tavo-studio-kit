# 角色卡制作指南

## 1. 官方结构

SillyTavern 当前常用角色卡结构是 `chara_card_v2`：

```json
{
  "spec": "chara_card_v2",
  "spec_version": "2.0",
  "data": {
    "name": "",
    "description": "",
    "personality": "",
    "scenario": "",
    "first_mes": "",
    "mes_example": "",
    "creator_notes": "",
    "system_prompt": "",
    "post_history_instructions": "",
    "alternate_greetings": [],
    "tags": [],
    "creator": "",
    "character_version": "",
    "extensions": {}
  }
}
```

`data.character_book` 是可选字段；要嵌入 lore 时再加。

## 2. 角色卡字段怎么写

### `name`

- 角色名。
- 导入后可见。
- 宏 `{{char}}` 会引用这个值。

### `description`

- 这是最重要的常驻设定区。
- 官方文档明确说明这里的内容会一直进 prompt。
- 应放：
  - 身份
  - 背景
  - 外貌
  - 与世界相关的长期事实
  - 行为边界
  - 说话风格的大框架
- 不要把“必须稳定记住的设定”只放进 `creator_notes`。

### `personality`

- 性格摘要。
- 比 `description` 更短、更聚焦。
- 适合放：傲慢/温柔/压场/嘴硬心软/冷静等概括。

### `scenario`

- 当前对话上下文。
- 适合放：
  - 关系初始状态
  - 当前地点/时间/情境
  - 这轮对话默认是怎样展开的

### `first_mes`

- 第一条消息。
- 官方文档明确指出模型会很强烈地从它学习：
  - 回复长度
  - 文风
  - 行动描写密度
  - 对话格式
- 想让角色以后也这么说话，就把这种风格写进 `first_mes`。
- 可写 Markdown；HTML 是否按富文本渲染，取决于聊天渲染链路和高级前端渲染设置。不要默认把浏览器整页 HTML/CSS/JS 写进 `first_mes` 后就会在 Tavo 中原样运行。

### `alternate_greetings`

- 额外开场白数组。
- 新聊天开始时可作为额外 swipes；群聊时系统可随机选。

### `mes_example`

- 示例对话。
- 用法要点：
  - 每一段示例前都加 `<START>`
  - 用 `{{user}}:` 标记用户发言
  - 用 `{{char}}:` 标记角色发言
- 它的目的不是塞设定，而是让模型学“怎么说”。
- 适合展示：
  - 方言
  - 节奏
  - 长短句分布
  - 动作与对白的组合方式

### `creator_notes`

- 元数据展示区，不是核心 prompt 区。
- 官方文档说明它主要给人看。
- 可以放：
  - 适配模型建议
  - 使用说明
  - 版本变更
  - 注意事项
- 不要把角色硬设定只写在这里。

### `system_prompt`

- 角色级主提示词覆盖项。
- 只有在用户设置启用 `Prefer Char. Prompt` 时才覆盖默认主提示。
- 可用 `{{original}}` 把全局默认主提示插回来。

### `post_history_instructions`

- 角色级 PHI。
- 一般用于收尾约束和高优先级行为规范。
- 只有在启用 `Prefer Char. Instructions` 时按角色覆盖。

### `tags`

- 数组。
- 用于组织与筛选。
- 不是字符串。

### `creator`

- 作者名。

### `character_version`

- 角色版本号。
- 建议用易读版本，如 `1.0.0`、`2026-03-29`。

### `extensions`

- 必须存在，并且必须是对象。
- 可以留空 `{}`。
- 常见扩展键：
  - `world`: 主世界书名
  - `depth_prompt`: 角色注入提示
  - `talkativeness`
  - `fav`

## 3. 哪些字段是“常驻 token”

根据官方文档，以下内容会稳定占用上下文：

- 角色名
- `description`
- `personality`
- `scenario`

以下内容不是永久常驻：

- `first_mes`
  - 一般只在聊天开始时使用
- `mes_example`
  - 会随着上下文紧张而被顶出，除非设置强制保留

这意味着：

- 永久设定放 `description` / `personality` / `scenario`
- 风格锚点放 `first_mes` / `mes_example`

## 4. `character_book` 嵌入格式

如果要把 lore 直接嵌进角色卡，放在：

```json
{
  "data": {
    "character_book": {
      "name": "示例世界书",
      "description": "",
      "scan_depth": null,
      "token_budget": null,
      "recursive_scanning": false,
      "extensions": {},
      "entries": []
    }
  }
}
```

`entries` 是数组，不是对象。

## 5. 最小可用角色卡

参考模板：

- `assets/templates/character-card.v2.minimal.json`

最小要点：

- `spec = "chara_card_v2"`
- `spec_version = "2.0"`
- `data.extensions = {}`
- `alternate_greetings` 和 `tags` 必须是数组

## 6. 推荐制作步骤

1. 先写一版纯 JSON。
2. 用 `jq` 或 Node 解析确认结构没坏。
3. 如果有 lore：
   - 独立做 `worldbook.json`
   - 需要嵌入时转成 `character_book`
4. 再写进 PNG。
5. 导入 ST 后实际开一轮新聊天，观察：
   - 第一条是否风格正确
   - 后续是否沿用风格
   - 世界书触发是否正常

## 7. 质检清单

交付角色卡前，按以下清单逐项检查。分为结构校验和内容校验两部分。

### 结构校验（必过）

| 检查项 | 通过标准 | 常见问题 |
|--------|----------|----------|
| JSON 可解析 | `JSON.parse` 不报错 | 字符串内未转义的引号、尾随逗号 |
| `spec` / `spec_version` 正确 | `chara_card_v2` + `2.0` 或 `chara_card_v3` + `3.0` | 忘记写或写成其他值 |
| `data.extensions` 存在 | 建议保留对象（至少 `{}`） | 缺失可能造成兼容问题或扩展信息丢失 |
| `alternate_greetings` 是数组 | `[]` 或包含字符串的数组 | 写成 `null` 或字符串 |
| `tags` 是数组 | `[]` 或包含字符串的数组 | 写成字符串 |
| `character_book` 结构 | 如有，`entries` 必须是数组，每条有 `key`、`content` | `entries` 写成对象 |
| PNG 元数据 | 提取后 JSON 与源 JSON 一致 | 嵌入后未回读验证 |

### 内容校验（建议过）

| 检查项 | 通过标准 | 说明 |
|--------|----------|------|
| `name` 非空 | 至少 1 字符 | 空名称会导致 `{{char}}` 宏失效 |
| `description` 体量 | ≥ 260 字 | 低于此值通常设定不够完整 |
| `description` 内容 | 包含身份、背景、外貌、行为边界 | 不要只写性格标签 |
| `personality` 非空 | 有性格摘要 | 空了不致命但浪费常驻 token 位 |
| `scenario` 非空 | 有场景描述 | 空了会让模型缺少情境感 |
| `first_mes` 非空 | 必须有内容 | 空开场白 = 角色卡不可用 |
| `first_mes` 风格一致 | 长度/文风与 description 的设定匹配 | 设定写长篇沉浸风但 first_mes 只有两句话 |
| `mes_example` 组数 | ≥ 2 组（以 `<START>` 计） | 1 组不够示范口吻变化 |
| `mes_example` 内容 | 是口吻示范不是设定百科 | 示例里不应该在解释角色设定 |
| `system_prompt` | 如有，≤ 400 字 | 过长的 system_prompt 会挤占上下文 |
| `post_history_instructions` | 如有，≤ 200 字 | 同上 |
| 宏统一 | 用户侧统一用 `{{user}}`，角色侧统一用 `{{char}}` | 混用真名和宏 |
| AI 废词 | 无黑名单词残留 | 参考 `ai-cliche-blacklist.md` |

### 玩法系统专项校验（如涉及）

| 检查项 | 通过标准 |
|--------|----------|
| 玩法模式与资源匹配 | 非"纯角色"模式时，应有系统包/预设 |
| 纯角色模式无残留 | 纯角色模式下不应残留系统包、变量包、系统正则 |
| 变量初始化 | 如启用变量模式，必须有变量初始化包或在预设中初始化 |
| 系统正则配套 | 如启用变量模式，建议有状态栏正则 |
| 世界书条目名 | 每条 entry 的 `comment` 非空，用于列表识别 |
| 世界书 `content` 独立 | 每条 `content` 独立成句，不依赖标题或 key 来补充语义 |

### 活人感校验（建议过）

| 检查项 | 说明 |
|--------|------|
| 角色不是服务型 NPC | description 和 system_prompt 中不应暗示角色永远体贴/理解/正确 |
| 有防御机制 | 角色面对不同关系层级应有差异化反应 |
| 情绪有惯性 | 冲突不应一被安慰就立刻化解 |
| 不替 {{user}} 行动 | first_mes 和 mes_example 中角色不替用户发言或决策 |

## 8. 结构化标签输出格式

当需要让 AI 模型一次性生成完整角色卡内容时，使用 `[TAG][/TAG]` 标签块格式比直接要求输出 JSON 更稳定。模型更容易正确生成标签块格式，解析端也更容易容错。

### 标准标签块顺序

```
[NAME]
角色名
[/NAME]

[NICKNAME]
昵称，没有可留空
[/NICKNAME]

[TAGS]
标签1, 标签2, 标签3
[/TAGS]

[DESCRIPTION]
角色设定内容
[/DESCRIPTION]

[PERSONALITY]
性格特点
[/PERSONALITY]

[SCENARIO]
场景描述
[/SCENARIO]

[FIRST_MES]
开场白
[/FIRST_MES]

[MES_EXAMPLE]
<START>
{{user}}: ...
{{char}}: ...
<START>
{{user}}: ...
{{char}}: ...
[/MES_EXAMPLE]

[SYSTEM_PROMPT]
系统指令
[/SYSTEM_PROMPT]

[POST_HISTORY_INSTRUCTIONS]
后置指令
[/POST_HISTORY_INSTRUCTIONS]
```

### 使用要点

- 在 prompt 末尾明确要求"只输出标签块，不要解释，不要 JSON，不要代码块"
- 每个标签块内可以给长度和内容指引（如 `[DESCRIPTION]` 内注明"2-4 段，写清身份、外貌、行为模式"）
- 解析时用正则 `\[TAG\]([\s\S]*?)\[\/TAG\]` 提取每个块的内容
- 如果模型输出格式不对，可以用二次修复 prompt 让模型重新整理成标签块格式
- `[MES_EXAMPLE]` 内必须包含 `<START>` 分隔符

### 与 JSON 输出的对比

| 维度 | 标签块格式 | JSON 格式 |
|------|-----------|----------|
| 模型输出稳定性 | 高 — 自然语言写作，不需要处理转义和引号 | 中 — 容易出现引号未闭合、逗号多余等 JSON 语法错误 |
| 内容质量 | 高 — 模型可以自然写长文本 | 中 — 长文本在 JSON 字符串里写作体验差 |
| 解析难度 | 低 — 简单正则提取 | 低 — `JSON.parse` 但需要错误处理 |
| 适用场景 | 生成阶段 | 最终交付阶段 |

建议流程：让模型以标签块格式输出 → 解析后填入角色卡 JSON 模板 → 校验 → 嵌入 PNG。

## 9. 全字段示例

完整例子请直接读：

- `assets/templates/character-card.v2.full.json`
