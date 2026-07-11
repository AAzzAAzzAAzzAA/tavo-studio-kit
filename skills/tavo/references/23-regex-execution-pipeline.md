# Tavo 正则执行管线百科

本页描述 Tavo `0.91.0` 当前可见的正则对象、执行分支、聊天绑定、导入与 MCP 操作，以及如何把“界面看起来变了”“模型实际收到的文本变了”“消息库中的原文变了”分开验证。

## 目录

- [证据边界](#证据边界)
- [一句话模型](#一句话模型)
- [原生对象](#原生对象)
- [Placements 与 Scopes](#placements-与-scopes)
- [Timings 与三个出口](#timings-与三个出口)
- [Substitution](#substitution)
- [Min/Max Depth](#minmax-depth)
- [正则助手与助手消息样式](#正则助手与助手消息样式)
- [导入、Create、Update 与 Readback](#导入createupdate-与-readback)
- [与世界书、提示词和聊天的交互](#与世界书提示词和聊天的交互)
- [A/B 真机验证方法](#ab-真机验证方法)
- [当前 Evidence 状态](#当前-evidence-状态)
- [作者检查表](#作者检查表)

## 证据边界

本页只使用以下三类证据：

- `official-current`：2026-07-10 重新读取的官方文档，包括[正则](https://docs.tavoai.dev/cn/guides/regular/)、[TavoJS API](https://docs.tavoai.dev/cn/guides/javascript-api/)、[宏](https://docs.tavoai.dev/cn/guides/supported-macros/)、[EJS 模板](https://docs.tavoai.dev/cn/guides/ejs-template/)、[高级前端渲染](https://docs.tavoai.dev/cn/guides/advanced-rendering/)、[世界书](https://docs.tavoai.dev/cn/guides/lore-book/)和[聊天高级设定](https://docs.tavoai.dev/cn/guides/chat/advanced-settings/)。
- `mcp-runtime`：2026-07-10 对当前手机执行的 strict MCP 重读。服务报告 Tavo `0.91.0`、70 tools、18 resources、7 resource templates、0 prompts，正则工具和 `tavo://schemas/regex`、`tavo://schemas/regex-entry` 均读取成功。可复核的持久快照为 `assets/schemas/mcp-surface-0.91.0-20260710.json`。
- `live-verified`：工作区中已经保留的真机、真实模型、MCP 请求/响应和 readback artifacts。
- 最新 terminal 语义批次：`artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/` 为 `status: passed`、`countsTowardKpi: true`；regex-runtime 5/5 primary 与 unbound control 1/1 均通过。

旧 Tavo/ST skill、旧接口记忆和未留证的经验不作为本页产品事实。文中“未验证”表示当前证据没有覆盖该行为，不表示产品一定不支持。

## 一句话模型

正则不是一个单一的“改消息”开关，而是一组绑定到聊天的文本转换规则。每条规则至少经过以下概念门控：

```text
正则组入库
  -> 聊天启用/绑定该正则组
  -> entry.enabled
  -> placements 选择文本通道
  -> timing 选择执行分支
  -> minDepth/maxDepth 选择消息深度
  -> findRegex + trimStrings + replaceString
  -> 显示副本 / 送模副本 / 持久消息中的一个或多个出口
```

这是理解模型，不是官方公布的内部函数调用顺序。特别是多规则排序、`trimStrings` 的精确内部次序、深度计数方向和宏替换的字节级转义算法，当前都没有足够证据可以写死。

## 原生对象

当前官方 TavoJS 文档和 MCP schema 使用如下原生形态：

```json
{
  "name": "状态栏显示",
  "entries": [
    {
      "identifier": "status-panel-v1",
      "name": "包装状态标签",
      "findRegex": "/<status>(.*?)<\\/status>/gim",
      "replaceString": "<pre>$1</pre>",
      "trimStrings": [],
      "placements": ["char"],
      "timing": "display",
      "substitution": "none",
      "minDepth": null,
      "maxDepth": null,
      "enabled": true
    }
  ]
}
```

字段语义：

| 字段 | 当前语义 | 边界 |
| --- | --- | --- |
| group `name` | 正则组名称。 | MCP `tavo_regex_create` 要求非空；TavoJS import 缺省组名为 `Regex`。 |
| `identifier` | 组内条目的稳定标识，供 entry upsert/delete 使用。 | MCP create/upsert 要求非空；ST import 可由端侧生成新 identifier。 |
| entry `name` | 条目显示名。 | 官方 TavoJS 文档称其必填，否则解析可能失败。 |
| `findRegex` | 查找表达式。支持普通 pattern；官方还写明可使用类似 JavaScript 的 `/pattern/flags` 形式。 | 实际支持的全部 flag、超时和正则引擎细节未公开。 |
| `replaceString` | 替换文本。官方示例支持 `$1`、`$2` 等捕获组和 `{{match}}` 全匹配占位符。 | `{{match}}` 与普通宏共享花括号外观，复杂组合应单独验证。 |
| `trimStrings` | 替换前要裁剪的字符串列表。 | 官方只描述“替换前修剪”；与捕获、宏、重复匹配的精确次序未验证。 |
| `placements` | 可多选的文本通道。 | 不是聊天/全局/消息变量的 storage scope。 |
| `timing` | 选择显示、送模或持久改写分支。 | 不能只凭名称推断跨 placement 的所有组合都有效。 |
| `substitution` | 正则字段中的宏替换模式。 | 不等于“是否执行 find/replace”。 |
| `minDepth` / `maxDepth` | 可选消息深度边界；`null` 表示未设置该边界。 | MCP 只约束为 `null` 或非负整数，没有公布方向和端点包含规则。 |
| `enabled` | 是否启用该条目。 | 正则组仍须绑定到当前聊天。 |

TavoJS create 允许省略若干 entry 字段，由端侧补默认值；官方给出的典型默认包括 `placements: ['char']` 和 `timing: 'display'`。MCP 的 create/update/upsert schema 更严格：一旦提交 entry，就要求 `identifier`、`name`、`findRegex`、`replaceString`、`trimStrings`、`placements`、`timing`、`substitution`、`enabled`，只有 depth 可以省略。

## Placements 与 Scopes

这里的 `placements` 是“处理哪类文本”，不是变量 API 的 `global/chat/message` 持久化 scope。

| 原生值 | 官方含义 | 当前可证明的范围 |
| --- | --- | --- |
| `user` | 用户输入/用户消息。 | 官方与 MCP schema 确认；暂无保留的真机 timing/depth A/B。 |
| `char` | AI/角色输出，即 assistant message content。 | v16 的 `editAndReceive` A/B 已证明该通道可持久改写角色输出。 |
| `reasoning` | AI 推理内容。 | 官方与 MCP schema 确认；当前没有 reasoning placement 的独立真机通过证据。 |
| `lorebook` | 世界书注入内容。 | 官方与 MCP schema 确认；触发扫描前后顺序及各 timing 组合未验证。 |

重要边界：

- `placements` 是数组，一条 entry 可以声明多个通道。
- 原生枚举没有 `system`、`preset`、`character-card` 或“某个角色 ID”。不要把 `char` 扩大解释为所有 system/preset/card prompt。
- 群聊里没有 entry 级 character selector；schema 本身不能表达“只改角色 A、不改角色 B”。
- `reasoning` 与消息 `content` 是不同字段。v16 的 `char` 样本中，持久 `content` 已替换，而 `reasoning` 仍能看到 raw marker；这与通道分离一致，但不等于 reasoning placement 已经通过测试。
- ST import 使用数值 `placement`，原生对象使用字符串 `placements`。当前 artifacts 只严格证明 `placement: [2]` 归一化为 `placements: ['char']`；其它数值不要凭旧 ST 记忆补表。

## Timings 与三个出口

官方 TavoJS 当前把五种 timing 解释为：

| `timing` | 显示态 | 本次/后续送模态 | MCP 持久消息 readback | 证据状态 |
| --- | --- | --- | --- | --- |
| `display` | 显示副本执行替换。 | 按“仅显示”语义，送模分支不应使用该显示副本。 | 官方明确写“不写入持久消息”，类似 ST `markdownOnly`。 | `official-current`；尚无专门 UI/MCP A/B。 |
| `send` | 不以显示为目标。 | 发送进模型前执行。 | 按官方语义是临时送模转换，不是持久改写。 | `official-current`；尚无隐藏 marker 真机 A/B。 |
| `sendAndDisplay` | 显示分支执行。 | 送模分支也执行。 | 没有 receive 语义，不应据此声称会改数据库原文。 | `official-current`；双出口尚未真机 A/B。 |
| `receive` | 收到后的已存文本通常会成为界面所读内容。 | 当前回复生成时无“把自己的输出再送给自己”的含义；该消息若被纳入后续上下文，模型会读到已持久化结果。 | 官方写“收到回复后持久化”，并注明只与输入/输出类通道相关。 | `official-current`；receive-only 尚无独立 artifact。 |
| `editAndReceive` | 收到或编辑后的持久结果会被显示。 | 后续轮次读取持久结果。 | 收到回复和编辑消息时都持久改写。 | receive 分支已由 v16 `char` A/B 证明；手动编辑分支未单独证明。 |

不要把三个出口混成一个“最终文本”：

1. **显示态**是气泡/Markdown/AR WebView 正在呈现的副本。`display` 可以让它与数据库原文不同。
2. **送模态**是某次请求组装给模型的上下文副本。`send` 可以让模型看到数据库和界面都没有显示的文本。
3. **持久消息**是 `tavo_message_get/find` 或 `tavo://chats/{id}/messages` 读回的 `content`/`reasoning`。`receive` 与 `editAndReceive` 才声明持久改写语义。

因此：

- “截图变了”不能证明模型看到变更，也不能证明 readback 变了。
- “模型按隐藏指令回答了”不能证明气泡或数据库原文变了。
- “MCP readback 已变”能证明持久态，但不能单独证明显示渲染正确。
- `sendAndDisplay` 是两个概念分支，不应描述成先改数据库、再从数据库发送。
- `editAndReceive` 应尽量设计成幂等规则；非幂等替换在每次编辑时可能再次加工。

## Substitution

当前原生枚举与 UI 文档可以对应为：

| UI 描述 | 原生值 | 可安全下的结论 |
| --- | --- | --- |
| 不替换 | `none` | 按 TavoJS 文档，这是“不做宏替换”，不是关闭正则替换。 |
| 原文替换 | `raw` | 对宏替换结果采用原文/raw 路径。 |
| 转义替换 | `escaped` | 对宏替换结果采用 escaped 路径。 |

最容易误读的是 `none`。v16 使用 `substitution: 'none'` 的规则仍把 `[RAW01]` 持久替换为 `CLEANED-...`，所以它绝不等于“跳过 `findRegex`/`replaceString`”。`replaceString` 决定正则替换，`substitution` 控制的是宏替换方式。

官方当前还确认：

- 宏可用于角色定义、预设、世界书、正则和其它生成提示词位置。
- EJS 可用于正则的匹配、替换和裁剪字符串。
- 同一字段先渲染 EJS，再处理 `{{}}` 宏；EJS 输出可以继续产生宏。

当前证据没有给出 `raw` 与 `escaped` 对反斜杠、美元符、HTML 实体、换行、JSON 字符和捕获组的完整算法，也没有证明它们在五种 timing 下的求值次数。涉及状态变量或写变量宏时，必须防止一次用户动作在显示与送模两个分支里产生两次副作用。

## Min/Max Depth

MCP schema 当前只保证：

- `minDepth`、`maxDepth` 可为 `null` 或大于等于 0 的整数；
- 两者均为可选字段；
- schema 没有表达 `minDepth <= maxDepth` 的交叉约束。

当前官方文字只称它们为“消息深度下限/上限”。没有足够证据确认：

- depth `0` 是最新消息、当前消息还是最老消息；
- min/max 是否包含端点；
- hidden message、reasoning、开场白、群聊消息怎样计数；
- `lorebook` placement 是否使用同一种 depth；
- `minDepth > maxDepth` 是拒绝、空范围还是自动交换。

所以创作时可以把 `null/null` 当作“不主动限制”，但不能在没有 A/B 的情况下声称 `0..3` 精确代表“最近四层”。需要限层时，应在目标手机版本上先建立深度方向表。

## 正则助手与助手消息样式

官方“正则助手”位于新建/编辑正则页的表达式输入框右侧代码图标中。当前模板包括：

- 思维链；
- 引用；
- 旁白；
- Markdown 代码块；
- 标签。

模板只负责自动填入候选表达式，不会替你决定 replacement、placement、timing、substitution 或 depth。选完模板后仍需逐项配置并验证。

若“助手样式”指角色气泡的视觉包装，推荐的最小意图是：

```json
{
  "placements": ["char"],
  "timing": "display",
  "substitution": "none"
}
```

然后让 `replaceString` 输出必要的 Markdown 或 HTML。这里有三条边界：

- 纯外观处理优先用 `display`，避免把装饰标签写入消息库或送给模型。
- 官方 AR 只明确保证开启后可渲染标准 HTML/CSS。正则输出 `<script>` 不等于 JavaScript 已执行；JS 还受 AR/JavaScript 设置和运行上下文约束。
- AR 开关关闭、Markdown 解析、HTML 转义、代码块和嵌套标签都可能改变最终视觉结果，必须用截图或像素证据验证，不能只看 source/readback。

若模型也必须看到包装标签，才选择 `sendAndDisplay`；若包装必须成为聊天历史原文，才选择 `receive`/`editAndReceive`。这三个需求不应为了省一条规则而混在一起。

## 导入、Create、Update 与 Readback

### 接口面

| 操作 | TavoJS | MCP runtime |
| --- | --- | --- |
| 列表/查找 | `tavo.regex.all()`、`find(name, {match})` | `tavo_regex_search` |
| 完整读取 | `tavo.regex.get(id)` | `tavo_regex_get`、`tavo://regexes/{id}` |
| ST 导入 | `tavo.regex.import(payload)` | `tavo_regex_import` |
| 原生创建 | `tavo.regex.create(regex)` | `tavo_regex_create` |
| 更新组 | `tavo.regex.update(regex)` | `tavo_regex_update` |
| 单条更新 | 未单列 | `tavo_regex_entry_upsert` |
| 单条删除 | 未单列 | `tavo_regex_entry_delete` |
| 纯文本试跑 | 未单列 | `tavo_regex_test` |
| 删除组 | `tavo.regex.delete(id)` | `tavo_regex_delete` |

TavoJS 的 `all()` 返回摘要，`entries` 是条目数量而不是 entry 数组；要审计字段必须 `get()`。TavoJS import/create/update 会请求用户确认。MCP 写工具当前支持 `dryRun`、`expectedRevision`、`clientRequestId`；更新前应先 get 并保留 revision。

### ST Import

官方 TavoJS 接受 `{name?, entries: SillyTavernRegexEntry[]}`。角色卡 `extensions.regex_scripts` 也可在 `tavo.character.import(card)` 时连同角色一起创建正则，并返回 `regexId`。

当前 strict import artifact：

- `artifacts/tavo-validation/20260710-020132-strict-import-kpi/run-manifest.json` 顶层为 `status: passed`、`countsTowardKpi: true`；
- 50 个真实文件导入中包含 10 个 regex；10 个均完成 search、dry-run、actual import、get readback 和 `tavo_regex_test`；
- 10 个 regex 的 `actualOk`、`readbackOk`、`semanticOutputOk` 均为 true。

这批样本严格证明的 ST 到原生归一化如下：

| ST 输入 | 原生 readback |
| --- | --- |
| `scriptName` | `name` |
| `findRegex` | `findRegex` |
| `replaceString` | `replaceString` |
| `trimStrings` | `trimStrings` |
| `placement: [2]` | `placements: ['char']` |
| `disabled: false` | `enabled: true` |
| `markdownOnly: false`, `promptOnly: false`, `runOnEdit: true` | `timing: 'editAndReceive'` |
| `substituteRegex: 0` | `substitution: 'none'` |
| `minDepth: null`, `maxDepth: null` | `minDepth: null`, `maxDepth: null` |
| 无原生 identifier | 端侧生成 identifier |

这不证明所有 ST 数值 placement、flags 和 substitution 数值的映射。导入成功也不等于原 JSON 逐字段原样保存；正确标准是“归一化后的原生 readback 是否符合预期”。

### Native Create

TavoJS `create` 要求组名，entries 可省略；端侧会给省略字段补默认值。MCP create 若携带 entries，应按当前 strict schema 提交完整 entry。推荐流程：

1. `tavo_regex_search` 排除同名对象；
2. `tavo_regex_create` + `dryRun: true` 检查 diff/warnings；
3. 使用稳定 `clientRequestId` 实际创建；
4. 用返回 id 执行 `tavo_regex_get`；
5. 比较预期原生字段，并另跑 `tavo_regex_test`；
6. 绑定到一次性聊天后再做 timing/placement 真机验证。

当前 MCP schema/runtime 证明 create 工具存在并规定了 payload；保留 artifacts 中没有一条专门覆盖“native create -> actual save -> readback”的正则 roundtrip，因此不要把 import roundtrip 政名为 create roundtrip。

### Update

TavoJS 官方推荐 `get -> 修改 -> update`，并要求更新对象带 `id` 和 `name`。MCP update 把 id 放在顶层，支持 `expectedRevision` 防止覆盖并发修改。

安全更新规则：

- 先 get，保留未知字段和当前 revision；
- 先 dry-run，确认 diff 只包含预期字段；
- 全组 update 时不要假设 entries 会自动 merge；保留未修改 entries；
- 只改一条时优先 `tavo_regex_entry_upsert`，以 `identifier` 定位；
- 重试实际写入时复用同一个 `clientRequestId`；
- 写后重新 get，不以 write response 代替 readback；
- 故意使用旧 revision 的冲突测试只能在一次性对象上做。

当前保留 artifacts 没有专门的 regex actual update/readback 通过案例，所以 update 的接口和并发控制属于 `mcp-runtime`，不是 `live-verified` roundtrip。

### Readback

完整审计至少读三层：

1. **正则对象**：`tavo_regex_get`/`tavo.regex.get`，核对 entries 和 revision。
2. **聊天绑定**：`tavo_chat_get` 的 `regexIds`，或 TavoJS current chat 的 `regexes` 摘要，确认该组确实启用。
3. **消息结果**：`tavo_message_find/get`，核对持久 `content` 与 `reasoning`。

`tavo_regex_test` 只证明 pattern/replacement 对一段输入的纯文本结果；它不经过聊天绑定、placement、timing、depth、模型请求、消息持久化或 AR 渲染，不能代替端到端测试。

## 与世界书、提示词和聊天的交互

### 聊天绑定

官方聊天高级设定允许在当前聊天启用/切换正则。MCP artifacts 中聊天对象使用 `regexIds`；TavoJS current chat 把已启用正则暴露为 `regexes` 摘要。一个正则对象存在于资料库，不等于它对所有聊天全局生效。

v16 的关键阴性对照正是同角色、persona、preset 与同类 prompt，但控制聊天未绑定 regex：绑定聊天把 `[RAW01]` 持久改为 `CLEANED-...`，未绑定聊天保留 `[RAW01]`。这证明“对象存在”和“聊天绑定”是两道不同门。

官方 TavoJS `chat.update` 当前只列出 name、characters、persona、background 为可更新字段；虽然返回对象可读 `regexes`，不要据此声称 TavoJS `chat.update` 可以绑定 regex。MCP `tavo_chat_create/update` 与 UI 高级设定是当前有证据的绑定路径。

### 世界书

`placements: ['lorebook']` 表示处理世界书注入内容。需要和两个不同问题分开：

- 世界书条目是否因关键词/constant 策略被选中；
- 被选中的注入文本是否再被 regex 转换。

官方没有公布 regex 与世界书关键词扫描的先后顺序。不能声称 regex 能先改用户消息、再替世界书制造触发词，也不能声称 lorebook placement 会改写世界书资料库原文。正确 A/B 是固定同一条已触发世界书，只改变 regex 绑定，并同时读取世界书对象、消息和模型结果。

`artifacts/tavo-validation/20260711-cross-feature-aggregate-v1/` 的 case 1/2 实际执行了这组 enabled/control A/B：两边都使用同一 keyword worldbook，A 绑定 `placements=['lorebook'] + timing='send'` 的 transform regex，B 不绑定。A 没有得到 transformed marker，B 也没有得到 raw marker；两个 exchange 都有唯一持久 user/assistant ID。由于共同先决条件“keyword worldbook 已注入”在 B 组也失败，这组结果只能记为 **blocked by keyword activation regression**，不能写成 lorebook-placement regex 成功或失败。后续应先用已验证的 constant entry 隔离 regex，再单独测试 keyword 顺序。

### 预设、角色卡与 Prompt

- `send`/`sendAndDisplay` 可处理相应 user/char 历史的送模副本。
- 原生 placements 没有“preset/card/system prompt”通道，所以不要把 send timing 扩大成任意 prompt 段的全局后处理器。
- EJS 和宏本身可以写在角色卡、预设、世界书和正则字段中；官方顺序是同一字段先 EJS、后宏。
- 正则字段中的 EJS/宏渲染，与聊天文本何时进入 regex、世界书何时扫描、多个 prompt 段怎样排序，是不同层次；当前证据不足以给出一条全局固定顺序。

### 消息生命周期

- `display` 适合无损外观、隐藏标签和状态栏包装。
- `send` 适合只给模型看的别名、控制标记或清理，不应被当作数据库脱敏。
- `receive` 适合确实要落盘的清理；一旦写入，该消息若仍被纳入后续上下文，模型历史也会继承结果。
- `editAndReceive` 还覆盖编辑路径，规则应考虑重复执行和用户手工修改。
- reasoning 是独立字段；只验证 content 不能外推 reasoning。
- 多条 entry 或多个正则组发生重叠时，当前官方/MCP 没有给出稳定排序契约。依赖链式替换的方案必须做顺序 A/B。

## A/B 真机验证方法

### 通用协议

每个结论使用一对或多对一次性聊天：

- A：绑定目标正则；
- B：不绑定、禁用 entry，或使用必不匹配 pattern；
- 两边使用相同角色、persona、preset、世界书、模型、采样参数、历史和用户 prompt；
- 关闭其它正则，记录 plugin/AR/EJS 设置，避免旁路变换；
- 每个样本使用不可复用 nonce，禁止从静态角色卡、preset 或测试脚本泄漏预期答案；
- 模型介导结论至少重复 3 到 5 组，逐例判定，不能用一次偶然服从代替证据。

每组至少保留：

```text
regex-source.json
regex-dry-run.json
regex-actual.json
regex-readback.json
chat-readback.json
messages-before.json
messages-after.json
input-send.json
screen-before.png
screen-after.png
ui-before.xml
ui-after.xml
case-result.json
run-manifest.json
```

验收必须同时写 expected 与 forbidden marker，并分别判定：

- UI 是否出现转换值；
- 模型回复是否证明送模值；
- MCP 持久消息是否出现转换值；
- B 组是否保留 raw 值；
- reload、切换聊天、重启 app 后结果是否仍符合该 timing 的持久化语义。

### 五种 Timing

| Case | A 组做法 | 必要判据 |
| --- | --- | --- |
| display | `char + display`，让真实模型输出 raw marker。 | A 截图显示 replacement；A MCP readback 仍是 raw；B 截图/readback 都是 raw；下一轮模型探针不能把显示专用 replacement 当作历史事实。 |
| send | `user + send`，raw 文本中放一个只有转换后才成立的隐藏指令或事实。 | A/B 持久用户消息和截图相同且为 raw；只有 A 的模型回答命中动态 nonce。 |
| sendAndDisplay | 使用同一 nonce 同时构造视觉 marker 与模型可回答事实。 | A UI 与模型都命中 replacement，持久 readback 仍 raw；B 三处都 raw/不命中。 |
| receive | `char + receive`，要求模型逐字输出 raw marker。 | A 收到后 MCP content 为 replacement，reload 后仍在；B 为 raw。当前轮模型推理不能被事后替换值冒充。 |
| editAndReceive | 先执行 receive case，再从真实 UI 把气泡编辑回 raw marker。 | 收到分支和 UI 编辑分支都重新持久化 replacement；只用 MCP message_update 不足以证明 UI 编辑管线。 |

### 四种 Placement

- `user`：在用户消息 content 放唯一 marker；分别观察 display/send/持久路径。
- `char`：让模型可见答案输出唯一 marker；禁止只在 reasoning 里出现。
- `reasoning`：选用确实返回 reasoning 的模型，在 reasoning 与 content 放不同 marker，分别 readback；模型没有 reasoning 时该样本无效，不记失败也不记通过。
- `lorebook`：使用 constant 世界书先隔离转换，再使用 keyword 世界书验证触发交互。A/B 的世界书源对象必须相同且保持 raw，模型只在 A 看到转换后的动态事实。

### Substitution

为 `none/raw/escaped` 建立三条除 substitution 外完全相同的规则。宏值至少包含：

```text
反斜杠 \  美元符 $1  花括号 {{x}}  小于号 <
引号 "'  与号 &  换行  中文标点
```

分别记录 find/replace/trim 字段经 EJS、宏和 regex 后的 UI、model-bound、readback。捕获组 `$1` 与 `{{match}}` 另设无宏控制样本，避免把正则占位符与宏替换混为一层。带写变量宏的样本必须记录执行前后计数，以发现 `sendAndDisplay` 双分支重复副作用。

### Depth

建立至少 6 层交替 user/char 消息，每层放唯一 `DEPTH_<floor>_<nonce>`。先用 `null/null` 做全范围基线，再逐一测试：

- `minDepth = maxDepth = 0..5`；
- 只有 min；
- 只有 max；
- 相邻边界；
- `minDepth > maxDepth` 的拒绝/空范围行为；
- hidden message、reasoning、开场白和群聊各自独立 case。

只有画出“配置值 -> 实际命中的稳定消息层”表后，才能写 depth 方向和包含性。模型 A/B 用 send timing，视觉 A/B 用 display timing，持久 A/B 用 receive timing；三种证据不能互相代替。

### Import/Create/Update/Readback

同一语义对象建立两条路径：

1. ST import：dry-run -> actual -> get -> test -> bind -> chat A/B；
2. native create：dry-run -> actual -> get -> test -> bind -> chat A/B。

随后在一次性 native 对象上执行：

- get revision；
- entry upsert 改一个 replacement；
- get 并确认只有目标字段变化；
- 使用旧 revision 尝试 update，确认冲突保护；
- 使用当前 revision 恢复；
- reload/app restart 后再次 readback。

是否删除测试对象取决于测试的 retention 约定。若保留，记录 id/name；若清理，删除后必须 search/get 证明对象确实不存在。

### 助手样式与 AR

使用同一条 `char + display` HTML/CSS replacement，分别在 AR off/on 下截图。验收包括：

- raw MCP content 不变；
- AR on 出现预期颜色、布局和标签；
- AR off 不产生脚本副作用；
- 长文本、代码块、中文、移动端窄屏不溢出；
- 只看 HTML source 或 UI tree 中存在文本不算视觉通过，需截图/像素证明。

## 当前 Evidence 状态

### 已确认

1. `official-current`：四种 placements、五种 timings、三种 substitution、可选 depth、正则助手五类模板、EJS/宏可进入正则字段。
2. `mcp-runtime`：当前 `0.91.0` 暴露 `search/get/create/update/import/delete/entry_upsert/entry_delete/test` 九个正则工具；create/update/upsert 的 enum 与必填字段如本页所列。
3. `roundtrip-pass`：`20260710-020132-strict-import-kpi` 顶层通过并计数；其中 10 个 ST regex 完成 dry-run、actual import、native readback 和纯文本 test。
4. `roundtrip-pass`：v16 准备阶段重新读取 10 个 strict regex，与历史 native readback 的 payload hash 全部一致；失败后的 resume verification 也有 10/10 regex comparison 通过。这证明对象 readback 稳定，不改变 v16 的顶层失败状态。
5. `live-verified, case-level only`：v16 的 regex-runtime 子族 5/5 主样本通过，未绑定 regex 的阴性对照 1/1 通过。样本只覆盖 `placements: ['char']`、`timing: 'editAndReceive'`、`substitution: 'none'`、depth `null/null`，并通过 MCP messages-after 证明 replacement 已写入持久 assistant content。
6. `semantic-pass, terminal run`：v23 在同一窄配置上再次完成 regex-runtime 5/5 与 unbound control 1/1；`model-calls/regex-runtime/*/messages-after.json` 中持久 assistant `content` 含 `CLEANED-*` 且不含对应 `[RAW*]`，control 的持久内容保留 `[RAW01]` 且不含 CLEANED。v23 整轮十个家族 50/50、五个控制 5/5，因此不再只是 failed run 内的 provisional family 证据。
7. `semantic-blocked-by-precondition`：2026-07-11 regex-worldbook A/B 的两个真实 exchange 都未看到该 keyword worldbook 的 raw marker；因此不能对 lorebook placement 的 transform effect 下结论。聚合路径为 `artifacts/tavo-validation/20260711-cross-feature-aggregate-v1/aggregate-manifest.json`。

### v16 必须怎样表述

`artifacts/tavo-validation/20260710-133100-semantic-model-kpi-v16/run-manifest.json` 的顶层事实是：

- `status: failed`；
- `countsTowardKpi: false`；
- `primaryAttempted: 21`、`primaryPassed: 18`；
- regex-runtime family 5/5；
- preset-stack 已有 2 个主样本失败，随后 persona-binding 发生无 assistant reply/transport abort，整轮在此终止；后续 families 未完成。

因此允许写“v16 中 regex-runtime 子族 5/5 case-level 通过”，禁止写“v16 通过”“v16 整轮验证成功”或“50 个主请求通过”。UI preflight 的 `status: passed` 也只是 preflight，不是 semantic run 的通过证据。

### 尚未确认

以下行为当前只能按官方/schema 描述，不能标为真机通过：

- `user`、`reasoning`、`lorebook` placement 的端到端语义；
- `display`、`send`、`sendAndDisplay`、receive-only，以及 `editAndReceive` 的手动编辑分支；
- `raw`、`escaped` 的精确转义差异；
- 任意非 null depth 的方向、包含性和特殊消息计数；
- native create actual roundtrip、native update actual roundtrip、stale revision 冲突；
- 多 entry/多 regex group 的执行顺序；
- 世界书扫描与 regex 的精确先后；2026-07-11 的首次 A/B 因 keyword 注入先决条件失败而保持未决，不得计为 regex 产品失败；
- 正则生成 HTML 的 AR 视觉结果与 JavaScript 执行；
- 其它 ST placement/substituteRegex 数值的映射。

后续运行不能自动覆盖这些缺口：v17 顶层 failed 且 regex 0 次；v18、v19 只到 prepared；v20 后来以 `status: failed`、`countsTowardKpi: false` 结束，虽有 regex-runtime 5/5 和 unbound control 1/1，但整轮因 keyword lorebook 回归失败。最新 v23 已 terminal passed，并把同一窄 regex 配置提升为完整 green epoch 内的 semantic evidence；它仍不能覆盖上列其它 placements、timings、substitution、depth、Markdown/code block、update 或 AR 缺口。

## 作者检查表

- 先决定目标出口：显示、送模、持久，避免默认选“全都改”。
- placement 只选需要的通道；不要把 `char` 当 system prompt。
- cosmetic HTML 使用 `char + display`，并单独验证 AR。
- 持久清理才用 receive/editAndReceive，并保证幂等。
- `substitution: none` 不会关闭 regex replacement。
- depth 未真机标定前保持 `null`，或把范围写成项目自己的已验证约束。
- ST import 后审计原生 readback，不比较表面字段名就宣布“完全保真”。
- MCP update 先 get、dry-run，再带 revision 和稳定 request id 写入。
- `tavo_regex_test` 通过只算纯文本变换通过，不算聊天管线通过。
- 每个 live claim 同时保留绑定 A、未绑定 B、expected marker、forbidden marker 和三出口证据。
- 报告 case-level 与 run-level 状态时分开写；子族通过不能覆盖整轮 failed。
