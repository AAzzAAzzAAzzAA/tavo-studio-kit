# 世界书 / Lorebook / World Info 制作指南

## 1. 独立世界书的文件结构

SillyTavern 独立世界书文件至少需要：

```json
{
  "entries": {}
}
```

这份 `entries` 对象结构用于独立 ST 世界书文件和原生导入链路。不要把它直接塞给 `tavo.lorebook.create()` / `tavo.lorebook.update()`：sandbox.js 的 `i()` 函数对 `entries` 调用 `.map(o)`，说明 JS API create/update 链路期望的是 Tavo lorebook 对象里的 `entries` 数组。文件导入格式、卡内 `character_book`、JS API create/update 是三种不同形态。

常见完整形态：

```json
{
  "name": "示例世界书",
  "extensions": {},
  "entries": {
    "0": {
      "uid": 0,
      "key": ["关键词"],
      "keysecondary": [],
      "comment": "备注",
      "content": "真正注入 prompt 的内容",
      "constant": false,
      "selective": true,
      "selectiveLogic": 0,
      "addMemo": true,
      "order": 100,
      "position": 0,
      "disable": false,
      "excludeRecursion": false,
      "preventRecursion": false,
      "delayUntilRecursion": false,
      "displayIndex": 0,
      "probability": 100,
      "useProbability": true,
      "depth": 4,
      "group": "",
      "groupOverride": false,
      "groupWeight": 100,
      "scanDepth": null,
      "caseSensitive": null,
      "matchWholeWords": null,
      "useGroupScoring": null,
      "automationId": "",
      "role": 0,
      "vectorized": false,
      "sticky": null,
      "cooldown": null,
      "delay": null,
      "matchPersonaDescription": false,
      "matchCharacterDescription": false,
      "matchCharacterPersonality": false,
      "matchCharacterDepthPrompt": false,
      "matchScenario": false,
      "matchCreatorNotes": false,
      "triggers": [],
      "ignoreBudget": false
    }
  }
}
```

## 2. 最重要的规则

官方文档里最关键的一条：

- 只有 `content` 真正注入 prompt
- `key`、`comment`、标题、组名这些都不会注入

所以每个 entry 的 `content` 必须自己就说得通，不能假设模型看得到标题或关键词。

## 3. 核心字段怎么用

### `uid`

- 条目唯一编号。
- 通常与 `entries` 对象键保持一致。

### `key`

- 主触发关键词数组。
- 可以是普通关键词，也可以是 JS 风格 regex。
- 普通文本模式下逗号会分隔多个 key。

### `keysecondary`

- 二级条件关键词数组。
- 配合 `selectiveLogic` 使用。

### `content`

- 真正给模型看的内容。
- 要写成完整说明，而不是标题提示。
- 一般建议短而密。

### `comment`

- 给人看的 memo。
- 不进 prompt。

### `constant`

- `true` 时总是激活。
- 适合“总规则”“总口吻修正”“全局常量设定”。

### `selective` 与 `selectiveLogic`

- 用于二级关键词逻辑。
- `selectiveLogic` 枚举值：
  - `0` = `AND_ANY`
  - `1` = `NOT_ALL`
  - `2` = `NOT_ANY`
  - `3` = `AND_ALL`

### `order`

- 插入优先级。
- 官方文档说明：数值越大，越靠近上下文末端，影响通常越强。

### `position`

- 插入位置枚举：
  - `0` = Before Char Defs
  - `1` = After Char Defs
  - `2` = Top of Author's Note
  - `3` = Bottom of Author's Note
  - `4` = `@Depth`
  - `5` = Before Example Messages
  - `6` = After Example Messages
  - `7` = Outlet

### `depth`

- 当 `position = 4` 时，表示插入到聊天历史中的深度。

### `role`

- 当 `position = 4` 时使用：
  - `0` = system
  - `1` = user
  - `2` = assistant

### `excludeRecursion`

- 被勾上时，其他条目不能递归触发它。

### `preventRecursion`

- 这个条目自己激活后，不再继续触发别的条目。

### `delayUntilRecursion`

- 只允许在递归扫描阶段激活。

### `probability` / `useProbability`

- 触发概率。
- `100` 意味着稳定触发。

### `group` / `groupOverride` / `groupWeight`

- 控制 inclusion group。
- 同组多条同时满足时，只会保留一条。

### `scanDepth`

- 覆盖全局扫描深度。

### `caseSensitive`

- 是否区分大小写。

### `matchWholeWords`

- 单词级精确匹配。
- 官方文档特别提醒：中文、日文这类不用空格分词的语言，通常不建议开。

### `vectorized`

- 用于向量检索匹配。
- 不是必须。

### `sticky` / `cooldown` / `delay`

- 定时效果。
- 以“消息数”计。

### `ignoreBudget`

- 预算溢出时仍尽量保留。

## 4. 推荐写法

### 常量规则 entry

适合：

- 总体写作约束
- 一个稳定追加的人设特征
- 需要长期挂在 prompt 上的说明

典型配置：

- `constant: true`
- `position: 0` 或 `1`
- `probability: 100`
- `useProbability: false`

### 普通关键词 lore entry

适合：

- 地点
- 组织
- 法术
- 历史事件
- 特殊关系

典型配置：

- `constant: false`
- `key: ["地点名", "别称"]`
- `content` 写成独立百科句子

### 递归条目

适合：

- A 被提到时顺带拉出 B
- 人名拉出组织，组织再拉出规则

官方文档允许条目内容里的关键词继续触发别的条目，所以可以做层层展开。

## 5. 独立世界书与嵌入 `character_book` 的区别

### 独立世界书

- 顶层是 `entries` 对象
- 每个条目是 `entries["0"]` 这种结构
- 用于单独导入、绑定角色/聊天/人格

### JS API `lorebook.create/update`

- 顶层仍是 lorebook 对象，但 `entries` 应按数组处理
- sandbox.js 只对数组条目执行 `entries.map(o)` 字段转换
- 不要把独立世界书的 `entries: { "0": {...} }` 原样传给 `create/update`

### 嵌入 `character_book`

- 放在角色卡的 `data.character_book`
- `entries` 是数组
- 单条字段名会变成：
  - `key` -> `keys`
  - `keysecondary` -> `secondary_keys`
  - `disable` -> `enabled` 的反逻辑
  - `order` -> `insertion_order`
  - `position` 数字会保留在 `extensions.position`，同时额外映射出 `position: "before_char" | "after_char"`

如果你已经有独立世界书，直接用：

- `scripts/worldbook_to_character_book.mjs`

### ST→Tavo 字段精确转换（基于 sandbox.js 源码）

以上是 ST 内部格式（独立→嵌入）的转换。当世界书条目通过 `tavo.lorebook.create()` / `tavo.lorebook.update()` 进入 Tavo 时，还会经历第二层 ST→Tavo 转换。以下映射来自 sandbox.js 的 `o()` 和 `i()` 函数。

> ⚠️ **`tavo.lorebook.import()` 不走 `o()/i()` 转换**——它吃 ST 原始 `character_book` 格式直接转给 Flutter 层（与 `tavo.regex.import()`、`tavo.character.import()` 行为一致）。下面这张映射只在 `create/update` 链路上生效；要给 `import()` 喂数据，用 ST 原始字段名即可。

#### 字段名映射（`n` 对象）

| ST 字段（character_book 格式） | Tavo 内部字段 | 说明 |
|-------------------------------|-------------|------|
| `keys` | `keywords` | 主触发关键词 |
| `secondary_keywords` | `secondaryKeywords` | 次级关键词 |
| `secondary_keyword_strategy` | `secondaryKeywordStrategy` | 次级关键词策略 |
| `scan_depth` | `scanDepth` | 扫描深度 |
| `case_sensitive` | `caseSensitive` | 是否区分大小写 |
| `match_whole_word` | `matchWholeWord` | 单词级精确匹配 |
| `injection_position` | `injectionPosition` | 注入位置 |
| `injection_depth` | `injectionDepth` | 注入深度 |
| `injection_role` | `injectionRole` | 注入角色 |

> ⚠️ **CCv3 spec ↔ Tavo `o()` 字段名不一致**：CCv3 标准的 `character_book` 字段用的是 `secondary_keys`（"key" 的复数），但 Tavo 的 `o()` 函数体内 `n` 对象 key 写成的是 `secondary_keywords`（完整的 "keyword" 复数）。这是 sandbox.js 的硬证据：
> ```js
> const n = { keys:"keywords", secondary_keywords:"secondaryKeywords", ... }
> function o(e){ const t={...e}; for(const[e,a]of Object.entries(n)) e in t && !(a in t) && (t[a]=t[e], delete t[e]); ... }
> ```
> 后果：标准 ST/CCv3 卡里写的 `secondary_keys` **不会被 `create/update` 自动转换**。要让二级关键词生效，要么改写成 `secondary_keywords`（喂给 `create/update`），要么直接走 `lorebook.import()` 通道（直通 Flutter 层，由原生侧自己处理）。

转换规则：如果 ST 字段存在且 Tavo 字段不存在，则复制值到 Tavo 字段并删除旧字段。

#### 特殊转换（非简单字段名映射）

**`constant` → `strategy`**

| `constant` 值 | 结果 `strategy` |
|--------------|----------------|
| `true` | `"constant"` |
| `false` | `"keyword"` |

转换后删除 `constant` 字段。

**`position` → `injectionPosition`**

| `position` 值 | 结果 `injectionPosition` |
|--------------|------------------------|
| `"before_char"` | `"lorebookBefore"` |
| `"after_char"` | `"lorebookAfter"` |

转换后删除 `position` 字段。其他 `position` 值不产生映射（保持不动）。

**`selective` → `secondaryKeywordStrategy`**

| `selective` 值 | 结果 `secondaryKeywordStrategy` |
|---------------|------------------------------|
| `true` | `"andAny"` |
| `false` | `"none"` |

转换后删除 `selective` 字段。

#### 世界书对象整体转换（`i()` 函数）

顶层世界书对象的转换很简单：保留所有字段，仅对 `entries` 数组中的每个条目依次应用上述 `o()` 转换。

```
function i(lorebook) {
  if (!lorebook?.entries) return lorebook;
  return { ...lorebook, entries: lorebook.entries.map(o) };
}
```

#### 关键警告

- `tavo.lorebook.create/update()` 接受两种字段格式：CCv3/ST 旧字段（如 `keys`、`position`、`constant`、`selective`）会经 `o()` 函数自动转换为 Tavo 格式。注意 `o()` 的字段名映射表（`n` 对象）里 key 用的是 `secondary_keywords`（完整复数）而不是 CCv3 spec 里的 `secondary_keys`，所以标准 ST 卡里的 `secondary_keys` **不会**被自动转换。**推荐直接使用 Tavo JS API 字段名**（`keywords`、`secondaryKeywords`、`injectionPosition` 等），减少歧义；要喂 ST 原始格式时，走 `lorebook.import()` 通道而不是 `create/update`。
- `create/update` 的 `entries` 是数组形态；独立 ST 世界书文件的 `entries` 对象形态只适合文件/导入链路，不能默认照搬进 JS API
- `constant`、`position`（ST 旧值）、`selective` 这三个字段会被 `o()` 转换处理（分别转为 `strategy`、`injectionPosition`、`secondaryKeywordStrategy`），旧格式仍可用；但新脚本建议直接写目标字段，避免依赖转换逻辑
- `injectionPosition` 的合法值：sandbox.js 的 `o()` 函数中 ST `position` 转换只覆盖 `before_char`→`"lorebookBefore"` 和 `after_char`→`"lorebookAfter"`。JS API 实际支持的完整值集以官方文档为准，据官方 JS API 还包括 `topOfExampleMessages`、`bottomOfExampleMessages`、`atDepth` 等
- 世界书条目的 `secondary_keywords`（Tavo sandbox 兼容别名）和 `secondaryKeywords`（Tavo JS API 字段）是**两个不同字段**，前者会被映射为后者；CCv3/ST 标准字段名是 `secondary_keys`

## 6. 推荐模板

- 最小模板：`assets/templates/worldbook.minimal.json`
- 多条高级模板：`assets/templates/worldbook.advanced.json`

## 7. 来源

- https://docs.sillytavern.app/usage/core-concepts/worldinfo/
- SillyTavern 源码：`public/scripts/world-info.js`、`src/endpoints/worldinfo.js`
- https://docs.tavoai.dev/guides/lorebook/
- sandbox.js（APK 内 `/assets/dist/js/sandbox.js`）— ST→Tavo 世界书字段转换的精确实现（`o()` / `i()` 函数）

## 8. 制作建议

1. 先把 lore 分成“永远常驻”和“关键词触发”两类。
2. 常驻的少量规则用 `constant: true`。
3. 具体词条用 `key` 触发。
4. `content` 尽量一条只讲一件事。
5. 触发词尽量包含别称，但不要堆太多泛词。
6. 中文条目通常把 `matchWholeWords` 保持 `null` 或 `false` 更稳。
