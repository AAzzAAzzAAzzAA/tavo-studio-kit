# 世界书条目语义

本文说明 Tavo 世界书（Lorebook）条目的当前字段语义、触发逻辑、注入位置、兼容映射和验证流程。结论只来自 2026-07-10 的 fresh Tavo 官方文档抓取、同日连接手机的 MCP schema/runtime，以及工作区内保留的真机产物；旧 Tavo skill 和旧缓存不作为事实源。

## 证据快照

### 官方文档

`official-current`：2026-07-10 19:08 Asia/Shanghai（UTC+8）重新运行 `scripts/fetch_official_docs.py`，从 `https://docs.tavoai.dev/cn/` 完整抓取 83 页，结果为 `complete=true`、`errors=[]`、`unfetched_count=0`。本题使用的两页与 skill 内同日快照逐字节一致：

- 世界书基础说明：`https://docs.tavoai.dev/cn/guides/lore-book/`
- TavoJS 世界书对象与兼容字段：`https://docs.tavoai.dev/cn/guides/javascript-api/`
- 耐久快照：`assets/official-docs/text-20260710/cn_guides_lore-book.txt`
- 耐久快照：`assets/official-docs/text-20260710/cn_guides_javascript-api.txt`

基础世界书页说明世界书在幕后向模型提供世界规则、叙事主线和分层背景；触发词是检索标签，条目内容才是要注入的知识。高级字段的精确定义位于同日 TavoJS 官方页，而不是基础世界书页。

### 当前 MCP

`mcp-runtime`：2026-07-10 19:08 Asia/Shanghai（UTC+8）对连接手机执行 strict dump，服务器仍为 Tavo `0.91.0`，发现 70 tools、18 resources、7 resource templates、0 prompts；顶层调用和文档资源读取均无失败。世界书相关结果与耐久 schema 资产一致：

- `assets/schemas/mcp-surface-0.91.0-20260710.json`
- `assets/schemas/mcp-surface-index-0.91.0-20260710.json`
- resources：`tavo://schemas/lorebook`、`tavo://schemas/lorebook-entry`
- resource template：`tavo://lorebooks/{id}`
- tools：`tavo_lorebook_search`、`get`、`create`、`update`、`import`、`delete`、`entry_upsert`、`entry_delete`

MCP 的 `tools/list` 是自动化调用的机器可读契约。`tavo://schemas/lorebook-entry` 资源本身只列出四个必填字段；完整枚举和数值范围要以各写入 tool 的 `inputSchema` 为准。

### 真机产物

`live-verified` 和 `roundtrip-pass` 证据主要来自：

- 常驻条目：`artifacts/tavo-validation/20260710-constant-lorebook-diagnostic/`
- 关键词条目双通道：`artifacts/tavo-validation/20260710-keyword-switch-channel-ab/`
- 关键词 UI 发送诊断：`artifacts/tavo-validation/20260710-keyword-ui-send-diagnostic/`
- 50 资产 strict import 批次：`artifacts/tavo-validation/20260710-020132-strict-import-kpi/`
- 初始导入归一化反例：`artifacts/tavo-validation/20260709-phone-method-smoke/`
- 最新语义批次的混合结果：`artifacts/tavo-validation/20260710-185800-semantic-model-kpi-v20/`
- 重启后历史关键词诊断：`artifacts/tavo-validation/20260710-193000-lorebook-history-one-call/`
- 重启后常驻对照：`artifacts/tavo-validation/20260710-193300-lorebook-constant-post-restart/`
- 重启后当前输入关键词稳定等待诊断：`artifacts/tavo-validation/20260710-193600-lorebook-keyword-settle/`
- 常驻 + 关键词探针同书 A/B：`artifacts/tavo-validation/20260710-194000-lorebook-constant-keyword-mix/`
- 35 项跨功能矩阵聚合：`artifacts/tavo-validation/20260711-cross-feature-aggregate-v1/`

v20 已结束为 `status: failed`、`countsTowardKpi=false`：68 次真实模型请求中，除关键词世界书外的九个家族为 45/45，五个控制为 5/5；五个关键词逻辑正例在 15 个独立 attempt 中均未返回目标事实码。插件、active preset 和原聊天均恢复。它是完成的失败批次，不能计入总 KPI，但其世界书子族可作为稳定反例。

最新完成的语义批次是 `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/`。其 terminal manifest 为 `status: passed`、`countsTowardKpi: true`：十个家族各 5/5，五个控制 5/5，共 55 次真实模型请求。v23 的世界书正例由每本书中的 `constant` entry 承担；同书虽然保留了 keyword probe entry，但 primary assertions 没有把 probe marker 列为 expected 或 forbidden。因此 v23 加强 constant 证据，不是 keyword 回归通过。

2026-07-11 的跨功能矩阵又用 25 个世界书/正则相关真实模型 exchange 做了独立边界探针。聚合清单从六个均完成状态恢复的保留运行中，为 35 个 canonical case 各选一个最强结果；其中世界书 case 3-25 全部来自同一完整运行。结果不是全绿：`constant` 和 keyword miss 通过；keyword hit、`andAny` hit、probability 100 keyword、scan-depth in-window、sticky 首次触发与 carry、cooldown 首次触发、delay 阈值后，以及 `atDepth/system` 未返回预声明 marker。probability 0、scan-depth outside、未激活 sticky、cooldown blocked 和 delay-before 等“应不出现目标 marker”的观察通过；cooldown expired 则在推进历史并轮换 entry 内容后出现了 rotated marker，即使同 chat 的首次 trigger 未出现。四个 marker 型 position 与 `atDepth/assistant` 的语义 marker 也出现。它们都是黑盒组合观察，不是 provider wire prompt-order 或字段独立因果证明。

## 条目模型

世界书由 `name` 和 `entries` 组成。条目正文的 Tavo native 形状如下：

```json
{
  "identifier": "amber-harbor-safety-v1",
  "name": "琥珀潮汐港安全规则",
  "content": "琥珀潮汐港只在潮位最低时开放；绿色桥灯表示结构不安全，禁止通行。",
  "enabled": true,
  "strategy": "keyword",
  "keywords": ["琥珀潮汐港", "琥珀港"],
  "secondaryKeywords": ["绿色桥灯", "最低潮位"],
  "secondaryKeywordStrategy": "andAny",
  "scanDepth": 10,
  "caseSensitive": false,
  "matchWholeWord": false,
  "injectionPosition": "lorebookAfter",
  "injectionDepth": 4,
  "injectionRole": "system",
  "probability": 100,
  "sticky": 0,
  "cooldown": 0,
  "delay": 0
}
```

当前 MCP create/update/upsert schema 对单条 entry 的最低要求是：

- `identifier`：非空字符串，稳定标识条目；更新和 upsert 应复用原值。
- `name`：显示和搜索名称，不是被注入的正文。
- `content`：注入到生成提示词的正文。
- `strategy`：`constant` 或 `keyword`。

其余字段在 schema 中可选，但为避免默认值、导入路径和版本差异，创建可复现资产时应显式填写。`enabled=false` 会关闭条目；关闭后不应再讨论关键词或概率是否命中。

## 触发模型

可以把条目是否进入生成上下文理解为一组概念门槛：启用状态、基础触发策略、关键词条件、概率条件和时序状态。这个模型便于解释字段，但不是已经证明的内部执行顺序；概率抽样与 `sticky`、`cooldown`、`delay` 的先后关系仍需专门实验。

### `constant`

`official-current`：`strategy: "constant"` 表示常驻。官方同时说明 `keywords` 只在 `strategy: "keyword"` 时生效，因此常驻条目不依赖主关键词或次级关键词。

`live-verified`：常驻诊断创建并读回了一个 native 条目，字段为 `constant`、`lorebookAfter`、`system`、`probability: 100`、三个时序值均为 0。绑定到真实聊天后，用户消息没有包含世界书关键词，模型仍原样给出唯一事实码 `CONSTANT_FACT_5749BFBD4401001A` 并正确解释紫色桥灯。证据：

- `artifacts/tavo-validation/20260710-constant-lorebook-diagnostic/source-lorebook.json`
- `artifacts/tavo-validation/20260710-constant-lorebook-diagnostic/lorebook-readback.json`
- `artifacts/tavo-validation/20260710-constant-lorebook-diagnostic/messages.json`
- `artifacts/tavo-validation/20260710-constant-lorebook-diagnostic/result.json`，其中 `passed=true`

这证明当前版本中该配置可以常驻注入；它不证明 `probability<100`、非零时序字段或其他注入位置下仍有相同行为。

`live-verified`：v23 又创建并读回五本互相隔离的 native 世界书，每本各有一条 constant entry 和一条 keyword probe entry。五个 primary case 均从 constant entry 返回各自唯一的 `LORE_FACT_*`；一个绑定同书但使用无关地点的 decoy control 仍返回 constant fact 且没有 probe marker，一个完全未绑定 control 没有返回 constant fact。五个 primary 和两个 control 均通过。证据：

- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/run-manifest.json`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/context-registry.json` 的 `semanticLorebooks`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/semantic-sources/lorebooks/`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-calls/lorebook-trigger/`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/controls/lorebook-trigger/`

这个批次严格证明的仍是 `constant + lorebookAfter + system + probability 100 + sticky/cooldown/delay 0`。目录名和 family 名中的 `lorebook-trigger` 只是测试分类名，不能把 constant 正例改称 keyword 正例。

### `keyword`

`official-current`：`strategy: "keyword"` 表示关键词触发。`keywords` 是主关键词列表，`secondaryKeywords` 和 `secondaryKeywordStrategy` 在主词命中后进一步约束。

官方没有提供单独的“全部主关键词”开关；所有次级策略都以“主词命中”为前提。最保守的作者解释是：主关键词列表承担 OR 式入口，即任一主词可形成主词命中。现有真机正例只使用一个主词，因此多个主词的精确 OR 行为仍未做对照验证。

`live-verified`：双通道诊断使用单个关键词“银杏码头”，native 创建和 readback 均保留 `strategy: keyword`、`secondaryKeywordStrategy: none`、`scanDepth: 10`、`caseSensitive: false`、`matchWholeWord: false`。通过 MCP 切换聊天和通过 UI 切换聊天的两个分支都在用户消息包含关键词后返回事实码 `SWITCH_FACT_4C6C80B16130E878`，两个 `result.json` 均为 `passed=true`。

这证明关键词条目在当前版本、该配置和两个切换通道中曾经工作；它不是“任何绑定聊天都必然触发”的保证。应用和 MCP 重启后的同日证据出现稳定回归：v20 的 15 个独立 attempt、历史消息触发诊断和当前输入等待 2 秒诊断都未注入 keyword marker；同环境新建 constant 世界书和 constant + keyword-probe 混合世界书均成功注入 constant marker，而 keyword probe 未出现。见文末混合证据。

v23 没有解决这组冲突。其五个 primary prompt 虽然包含各自 keyword，但验收只要求 constant `LORE_FACT_*`，没有要求或禁止 `LORE_KEYWORD_PROBE_*`；模型回复中没有 probe 也不能替代一个预先声明的 keyword assertion。故 v23 对 keyword 既不记 pass，也不记 fail。2026-07-11 case 4 则是预先声明 expected marker 的新正例，仍失败；case 5 的 miss control 通过，所以当前可靠性结论继续是 mixed/regressed，而不是“后来恢复正常”。

## 主词与次级词的五种策略

令：

- `P`：主关键词条件命中。
- `A`：`secondaryKeywords` 中至少一个词命中。
- `L`：`secondaryKeywords` 中全部词命中。

官方当前定义如下：

| `secondaryKeywordStrategy` | 逻辑表达 | 语义 |
| --- | --- | --- |
| `none` | `P` | 不启用次级关键词；主词命中即可继续。 |
| `andAny` | `P && A` | 主词命中，并且任意一个次级词命中。官方标为默认策略。 |
| `andAll` | `P && L` | 主词命中，并且全部次级词命中。 |
| `notAny` | `P && !A` | 主词命中，并且没有任何次级词命中。 |
| `notAll` | `P && !L` | 主词命中，并且次级词不是全部命中；次级列表非空时，零个或只命中一部分都满足“不是全部”。 |

重要边界：

- `none` 不是“没有主关键词”，而是“关闭次级门槛”。
- `notAny` 与 `notAll` 不等价：命中一部分次级词时，`notAny` 失败，`notAll` 仍可成立。
- 空 `secondaryKeywords` 下 `andAny`、`andAll`、`notAny`、`notAll` 的空集合求值没有被官方说明，也没有真机矩阵。不要借用编程语言的 vacuous truth 规则猜测；没有次级条件时明确使用 `none`。
- 当前 strict import 产物曾把 `selective: true` 归一化为 `andAny`，同时得到空次级列表。readback 只证明存储结果，不证明这个空列表组合如何触发。
- 历史行为正例只验证了 `none`。2026-07-11 又加入 `andAny` 的 hit/miss 一对真实模型探针：miss control 正确不泄漏，hit 正例未注入。它证明当前运行中的负门槛行为和正例回归，不证明 `andAny` 已可靠工作；`andAll`、`notAny`、`notAll` 仍待独立正反矩阵。

## 扫描与匹配

### `scanDepth`

`official-current`：关键词扫描的消息深度，默认 2，官方上限 1000。它以消息深度为单位，不是字符数、token 数或世界书条目数。

`mcp-runtime`：当前写入 schema 只声明整数且 `minimum: 0`，没有在 JSON Schema 中声明 1000 的 maximum。客户端仍应遵守官方 0 到 1000 的产品约束，不应把 schema 未写 maximum 解读成无限制。

2026-07-11 的 isolated probe 中，关键词位于设定窗口内的正例未注入，窗口外负例正确不泄漏。因此当前证据只能记录“in-window positive regression + outside negative control”，不能由负例反推出扫描窗口实现正确。仍未被当前证据定义的细节包括：

- 深度 0 是否只扫描本次待发送输入，还是完全不扫描；
- 当前输入是否计入深度；
- user、assistant、system、hidden、reasoning 消息分别是否参与；
- 编辑、重生成、群聊和续写是否使用相同窗口。

### `caseSensitive`

`official-current`：控制关键词是否区分大小写。

- `false`：按不区分大小写的方式比较。
- `true`：大小写必须匹配。

中文等无大小写文本不会因为这个开关产生通常意义上的差异。Unicode 大小写折叠、全角半角、变音符号和 locale 规则没有官方细化，也没有当前真机边界测试。

### `matchWholeWord`

`official-current`：控制是否全词匹配。

- `true`：要求关键词形成完整词边界，避免普通子串命中。
- `false`：允许关键词作为更长文本的一部分命中。

官方没有公开具体分词器或边界算法。中文、日文、无空格文本、连字符、下划线、标点和 emoji 周围的“整词”定义都应通过目标语言用例验证，不能直接套用 JavaScript `\b` 或 SillyTavern 的实现细节。

现有关键词正例使用中文、`caseSensitive=false`、`matchWholeWord=false`，只证明这个宽松组合可以命中；没有证明大小写和整词开关的正反边界。

## 概率与时序

### `probability`

`official-current`：激活概率，整数 0 到 100，默认 100。`mcp-runtime` 同样约束 `minimum: 0`、`maximum: 100`。

应把它理解为：条目通过确定性触发条件后，仍需经过概率门槛。当前证据没有说明随机抽样发生在每条 entry、每次 generation、每轮扫描还是每次递归处理，也没有说明随机种子和重生成是否复用结果。

保留的 constant 正例使用 `probability: 100`。2026-07-11 还对 keyword 条目做了 100/0 A/B：100 正例未注入，0 负例正确不泄漏。因此：

- 100 对 constant 有正例；对当前 keyword 路径有失败反例，不能合并成全局结论；
- 0 有一次 isolated keyword 负例通过，但单次负例不证明所有运行中都“绝对不激活”；
- 1 到 99 的统计分布、重生成稳定性和与 sticky/cooldown/delay 的交互均未验证。

### `sticky`

`official-current`：条目激活后持续保持的消息轮数；0 表示不持续。

它表达“已经激活后继续保留”，不是扩大最初的关键词扫描窗口。官方用语是“消息轮数”，没有明确一轮是单条消息还是一组 user/assistant exchange，因此不要把数值擅自换算成对话往返数。

### `cooldown`

`official-current`：条目激活一次后的冷却轮数；0 表示无冷却。

冷却关注再次激活。官方没有说明冷却期间 sticky 内容是否仍保留、概率失败是否启动冷却、重生成是否消耗轮数，以及切换聊天或重新绑定世界书是否重置状态。

### `delay`

`official-current`：延迟激活的消息轮数；0 表示立即。

官方没有说明延迟从首次满足关键词、首次绑定、聊天创建还是其他事件开始计数，也没有说明条件在等待期间消失时是否取消。

2026-07-11 已真实执行非零时序探针，但结果受 keyword 首次触发回归和测试内 entry update/MCP history mutation 共同限制：sticky trigger/carry 和 cooldown trigger 没有 marker，未激活与 blocked 观察没有目标 marker，cooldown expired 在推进历史并轮换内容后出现 rotated marker；delay-before 没有目标 marker而 delay-after 仍未出现 marker。它们能证明测试配置被创建、读回并进入真实 exchange，也能记录当前组合行为；由于先决正例失败且更新/推进可能改变状态，不能据此推导 sticky/cooldown/delay 的字段独立计数语义或组合优先级。

## 五种注入位置

| `injectionPosition` | 官方语义 | 与预设的关系 | 当前 live 证据 |
| --- | --- | --- | --- |
| `lorebookBefore` | 角色描述上方，UI 含义为 `↑Char`。 | 对应预设内置 marker `worldInfoBefore`。 | 2026-07-11 isolated semantic marker 出现；未证明精确 wire order。 |
| `lorebookAfter` | 角色描述下方，UI 含义为 `↓Char`。 | 对应预设内置 marker `worldInfoAfter`。 | constant 历史与 2026-07-11 isolated marker 均通过；keyword 可靠性仍 mixed。 |
| `topOfExampleMessages` | 示例对话之前。 | 位于示例消息块顶部。 | 2026-07-11 isolated semantic marker 出现；未证明相对 example 的精确 wire order。 |
| `bottomOfExampleMessages` | 示例对话之后。 | 位于示例消息块底部。 | 2026-07-11 isolated semantic marker 出现；未证明相对 example 的精确 wire order。 |
| `atDepth` | 聊天历史的绝对深度位置。 | 不依赖角色描述或示例消息的相对 marker。 | `depth=1/assistant` marker 出现；`depth=3/system` marker 未出现，当前为 role/depth-dependent mixed。 |

当前 MCP enum 与官方五项完全一致。不要把预设 entry 的 `relative` / `absolute` 枚举写进世界书 entry；那是另一个对象模型。

### `atDepth`、`injectionDepth` 与 `injectionRole`

- `injectionDepth` 是非负整数，只在 `injectionPosition: "atDepth"` 时生效。
- `injectionRole` 可为 `system`、`user`、`assistant`，决定注入消息的角色。
- 对 marker 型位置，schema 仍允许携带 `injectionRole`，官方也把它列为通用条目字段。2026-07-11 的 `atDepth` 只比较了 `system/depth 3` 与 `assistant/depth 1`，两个变量同时变化，因此不能把差异单独归因给 role 或 depth；`user` 仍未覆盖。

官方世界书段落没有定义 depth 0、1、2 分别落在最后一条消息的哪一侧。官方在“预设 absolute entry”段落给出了预设对象的 0/1 示例，但那不是 LorebookEntry 的明示契约；在没有世界书实测前，不应把预设的索引规则直接移植到 `atDepth`。

`atDepth` 的可靠验证必须同时记录：发送前历史、条目 depth/role readback、实际发给模型的有序消息或等价可观察结果，以及至少两个相邻 depth 的 A/B 对照。只看到模型复述正文无法证明它被插在指定深度或使用指定 role。

### 预设 marker 边界

官方 TavoJS 文档列出的相关内置 identifier 是 `worldInfoBefore`、`worldInfoAfter`、`dialogueExamples` 和 `chatHistory`。当前证据没有回答：自定义预设缺失、禁用或重复 marker 时，世界书是丢弃、回退还是重新定位。即使 readback 中 `lorebookIds` 绑定正确，也不能只据此断言注入已发生。

## Native、CCv3 与 ST-compatible

这里必须区分三个层次：

1. **Tavo native**：create/update/entry_upsert 的明确字段模型，也是 get/readback 的标准输出。
2. **CCv3-compatible**：当前官方 TavoJS 文档明确列出的兼容字段转换。
3. **SillyTavern-compatible import**：当前 MCP `tavo_lorebook_import` schema 宣称接受 “Tavo/spec-v3 or compatible SillyTavern shape”，但没有枚举完整 ST export 方言。

### 官方明确映射

当前官方 TavoJS 文档明确说 create/update 同样接受 CCv3 字段名并自动转换。该承诺属于 TavoJS 对象层；MCP create/update 的机器 schema 以 native 字段为主，自动化应在 MCP import 之外优先提交 native 形状。

| CCv3-compatible 输入 | Tavo native 输出 | 当前官方语义 |
| --- | --- | --- |
| `keys` | `keywords` | 主关键词列表。 |
| `secondary_keys` | `secondaryKeywords` | 次级关键词列表。 |
| `constant: true` | `strategy: "constant"` | 常驻。 |
| `constant: false` | `strategy: "keyword"` | 关键词触发。 |
| `position: "before_char"` | `injectionPosition: "lorebookBefore"` | 角色描述上方。 |
| `position: "after_char"` | `injectionPosition: "lorebookAfter"` | 角色描述下方。 |
| `selective: true` | `secondaryKeywordStrategy: "andAny"` | 主词加任一次级词。 |
| `selective: false` | `secondaryKeywordStrategy: "none"` | 不启用次级词门槛。 |

这个兼容层是语义转换，不是简单字段改名；尤其 `constant` 和 `selective` 都从布尔值转换为枚举。

### 真机导入观察

strict import 的 `01-lorebook.json` 是一个保留的 ST/CC 风格输入：两条 entry 使用 `keys`、`comment`、`content`、`enabled`、`constant`、`selective`、`order`、`probability`。实际导入后 MCP readback 显示：

- `keys` 保留为 `keywords`；
- `comment` 被观察到成为 native `name`；
- `constant: false` 成为 `strategy: keyword`；
- `selective: true` 成为 `secondaryKeywordStrategy: andAny`；
- `enabled` 与 `probability` 保留；
- 缺失的 `identifier` 被生成 UUID；
- 缺失字段被归一化为 `lorebookAfter`、depth 4、role `system`、scanDepth 2、case-insensitive、whole-word、sticky/cooldown/delay 0；
- 输入的 `order` 和顶层 `description` 没有出现在该 MCP readback 中。

证据对：

- `artifacts/tavo-validation/20260710-020132-strict-import-kpi/source-files/lorebook/01-lorebook.json`
- `artifacts/tavo-validation/20260710-020132-strict-import-kpi/imports/016-lorebook-01/readback.json`

这些默认值是 Tavo `0.91.0` 当前 import 路径的观察，不是所有版本、所有输入方言和 create/update 路径的永恒默认值。

更早的 method smoke 还保留了一个反例：提交方预期关键词条目，`tavo_lorebook_import` 的 dry-run 和实际 readback 却归一化成 `strategy: constant`、空 `keywords`。因此“import 接受”只能证明输入可转换，不能证明作者意图或字段被保留。证据：

- `artifacts/tavo-validation/20260709-phone-method-smoke/notes.md`
- `artifacts/tavo-validation/20260709-phone-method-smoke/mcp-import-switch-result.json`

### 当前不能承诺的 ST 映射

当前 fresh Tavo 官方页没有说明以下常见 ST 方言字段如何映射：`key`、`keysecondary`、`disable`、`selectiveLogic`、数字型 `position`、`useProbability`、`matchWholeWords`、以 uid 为键的 `entries` 对象，以及 ST 扩展中的 group/recursion 字段。

MCP import 的 `lorebook` payload 使用 `additionalProperties: true`，只表示 payload 不会在 JSON Schema 层预先枚举这些字段，不等于每个字段都被解释、保留或导出。对这类输入必须 dry-run、实际导入、get/readback 和逐字段比较；没有比较结果时，不要给出猜测性映射。

## 创建、导入与更新

### TavoJS 官方路径

`official-current`：

- `tavo.lorebook.all()`：获取概要列表。
- `tavo.lorebook.get(id)`：读取单个世界书，不存在返回 `null`。
- `tavo.lorebook.find(name, { match })`：按名称查找，match 可为 exact/prefix/suffix/contains，默认 exact。
- `tavo.lorebook.create(lorebook)`：创建，`name` 必填，返回新 ID。
- `tavo.lorebook.import(lorebook)`：导入 CCv3 `character_book` 形状；会弹窗确认，成功返回新 ID，取消返回 `null`。
- `tavo.lorebook.update(lorebook)`：更新，`id` 和 `name` 必填。
- `tavo.lorebook.delete(idOrObject)`：按 ID 或带 ID 的对象删除。

TavoJS 官方页没有为这些方法声明 MCP 式 `dryRun`、`expectedRevision` 或 `clientRequestId`。不要把两个 API 层的参数混用。

### MCP 自动化路径

当前 MCP tool 必须通过 JSON-RPC `tools/call` 调用，而不是把 `tavo_lorebook_create` 等 tool name 当作 JSON-RPC method。已验证的调用外形是：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "tavo_lorebook_create",
    "arguments": {
      "lorebook": {
        "name": "港务规则",
        "entries": []
      },
      "dryRun": true,
      "clientRequestId": "lorebook-create-harbor-rules-v1"
    }
  }
}
```

当前工具边界：

| 操作 | Tool | 关键要求 |
| --- | --- | --- |
| 搜索 | `tavo_lorebook_search` | ID 未知时先按名称搜索；支持 exact/prefix/suffix/contains。 |
| 读取 | `tavo_lorebook_get` | `id >= 1`；返回 `revision` 和完整 entries。 |
| Native 创建 | `tavo_lorebook_create` | `lorebook.name` 必填；entry 采用 native 字段。 |
| Native 更新 | `tavo_lorebook_update` | 顶层 `id` 与 `lorebook` 必填；先 get，保留未修改字段。 |
| 兼容导入 | `tavo_lorebook_import` | payload 可为 Tavo/spec-v3 或兼容 ST 形状；必须预期归一化。 |
| 单条 upsert | `tavo_lorebook_entry_upsert` | `lorebookId` 和完整 native entry 必填；适合最小化单条修改。 |
| 单条删除 | `tavo_lorebook_entry_delete` | `lorebookId` 与 `identifier` 必填。 |

所有世界书写入工具当前都公开 `dryRun`、`expectedRevision`、`clientRequestId`。安全流程是：

1. fresh dump MCP surface，确认 app 版本、tool schema 和资源可读。
2. 搜索并 get 目标；记录 `id`、`revision` 和原始 entries。
3. 只改需要改变的字段。单条修改优先 `entry_upsert`，避免重写整个数组。
4. 用相同 payload 调用 `dryRun: true`，检查 `diff`、warnings 和归一化结果。
5. 实际写入时携带 get 得到的 `expectedRevision` 和稳定的 `clientRequestId`；重试时复用同一个 request ID。
6. 再次 get，确认新 `revision`，逐字段比较，而不是只看 `ok: true`。
7. 若验证运行时语义，将世界书绑定到一次性 chat，记录原 `lorebookIds`，完成正反对照后恢复原绑定。

对新建对象没有旧 revision 可保护；仍应使用 dry-run 和稳定的 `clientRequestId`。对既有对象，如果 revision 已变化，应重新 get 和重算修改，不要覆盖并发更新。

## 验证分层

一个世界书条目至少有五个不同的“成功”层级：

| 层级 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| Schema seen | 当前 tool schema 声明这些字段类型和 enum。 | 实际调用会接受，或 app 会保存、转换、执行它们。 |
| Dry-run pass | 当前输入能被解析，并能看到预期 diff。 | 数据已落盘。 |
| Roundtrip pass | actual write 后 get/readback 保留了目标 native 字段。 | 条目已进入模型上下文。 |
| Binding pass | chat readback 中包含目标 `lorebookIds`。 | 当前 generation 确实注入该 entry。 |
| Semantic pass | 正例回包包含唯一事实码，负例不泄漏事实码。 | 精确注入顺序、role、概率分布或多轮状态。 |

### 推荐行为测试

使用唯一、不可从角色卡或用户提示推断的事实码，并保留原始消息：

1. **constant 正例**：用户消息不出现任何关键词，要求复述常驻事实；应出现事实码。
2. **keyword 正例**：只在用户消息放入一个主关键词；应出现事实码。
3. **keyword 未命中对照**：绑定同一世界书但使用无关地点；不得出现事实码。
4. **未绑定对照**：提示中出现关键词，但 chat 不绑定世界书；不得出现事实码。
5. **次级策略矩阵**：对每个策略分别跑主词缺失、主词+零/一/全部次级词，避免复用聊天造成 sticky 污染。
6. **case/whole-word 矩阵**：大小写、前后缀、标点、中文邻接分别测试。
7. **概率测试**：先验证 0 与 100，再以足够多独立 generation 测 1 到 99；记录重生成与新消息的差异。
8. **时序测试**：每轮记录消息索引和 entry readback，分别测试 delay、sticky、cooldown，再测试组合。
9. **位置测试**：五个位置分别使用不同事实码；`atDepth` 再做相邻 depth 与三种 role 的 A/B。

模型可能从用户问题猜中自然语言事实，所以只有唯一事实码和未绑定/未命中对照能把“注入”与“猜测”分开。

## 已验证边界

### 当前可写成已验证

- Tavo `0.91.0` 当前 MCP 同时公开世界书 search/get/create/update/import/delete/entry_upsert/entry_delete，并公开核心 native enum 与 schema 约束。
- native `constant` + `lorebookAfter` + `system` + probability 100 + 三个时序值 0 已完成创建、readback、绑定和真实模型回包验证。
- 同一 constant 配置已在 v23 五本隔离世界书中完成 5/5 primary semantic pass，并通过 bound-decoy 与 unbound 两个控制；v23 整轮 terminal passed。
- native `keyword` + 单主词 + `secondaryKeywordStrategy: none` + scanDepth 10 + case-insensitive + 非整词 + `lorebookAfter/system` + probability 100 已在独立双通道诊断中完成 readback、绑定和真实模型回包验证。
- 2026-07-11 跨功能矩阵在同一保留运行中验证了 `constant`、keyword miss、probability 0 negative、scan-depth outside negative、若干时序 negative，以及四个 marker 型 position 的 isolated marker；这些 scoped passes 不覆盖同运行中的 keyword positive regressions。
- 当前 import 能接收保留的 CC/ST 风格 `keys/comment/constant/selective` 输入并归一化为 native 对象；import 可能生成 identifier、补默认字段并丢失或不暴露某些输入字段。
- `tools/call` 是当前已验证的 MCP tool 调用方式；直接把 tool name 当 JSON-RPC method 会失败。

### 只有官方与 schema 支撑

- `andAny`、`andAll`、`notAny`、`notAll` 的定义存在于当前官方文档和 MCP enum；`andAny` 已有一次 hit-fail/miss-pass 实测，其余策略和完整条件矩阵仍不足。
- `scanDepth` 的默认 2 和官方最大 1000、大小写开关、整词开关均有官方定义；精确窗口和 Unicode 边界未验证。
- probability 0 到 100、sticky/cooldown/delay 非负整数均由官方和 schema 支撑；0/100 与非零时序已有 scoped live 观察，但 keyword 先决正例失败，尚不能写成一般化执行规则。
- 五种 injectionPosition 和三种 injectionRole 均由官方和 schema 支撑；五种 position 都有 live exchange，四个 marker 型位置与 `atDepth/assistant` 出现 marker，`atDepth/system` 失败，但精确 prompt order 和单变量 role/depth 因果仍未证明。
- create/update/entry_upsert 的 dryRun/revision/idempotency 参数存在于当前 schema 和 runtime write-safety 文档；现有世界书产物没有覆盖每一种更新冲突路径。

### 混合证据与仍待验证

- `20260710-keyword-switch-channel-ab` 的两个独立分支证明关键词条目可以触发。
- 已结束的 `20260710-185800-semantic-model-kpi-v20` 中，五本书及 15 个独立聊天的 readback 均保持 `keyword`、目标关键词、`none`、after/system、probability 100；五个正例全部失败。绑定错误关键词和完全未绑定的两个控制均通过，未泄漏目标 marker。
- `20260710-193000-lorebook-history-one-call` 把关键词放进上一条持久用户消息，仍未注入；`20260710-193600-lorebook-keyword-settle` 在当前输入 set/get 后等待 2 秒再发送，也仍未注入。这排除了单纯“只扫描历史”或“输入状态尚未稳定”的解释。
- `20260710-193300-lorebook-constant-post-restart` 在相同角色、persona、preset 和插件隔离环境中新建 constant 世界书并成功回显唯一 marker。`20260710-194000-lorebook-constant-keyword-mix` 在同一本书放置 constant entry 与 keyword probe：constant marker 出现，keyword marker 未出现。故障边界集中于 keyword activation，而不是整个世界书绑定或注入链路。
- 这组混合结果说明“格式正确 + 绑定存在 + 提示含关键词”仍不足以保证每个运行环境都产生 keyword 语义结果。当前证据能确认重启后的可复现回归，但不能从黑盒证据指定内部根因。
- 关键词世界书的产品结论应写成“0.91.0 有同日成功真机证据，也有应用/MCP 重启后稳定失败证据；关键项目必须在目标会话跑绑定正例与未绑定负例，不能只看 readback”，不能写成绝对保证。
- v23 的 constant 5/5 不能覆盖或抵消 keyword 的 mixed verdict；它只进一步排除了“整个世界书绑定/注入链路都失效”的宽泛解释。
- `20260711-cross-feature-aggregate-v1` 新增了 35/35 case coverage index：34 次完整模型往返、68 个唯一持久消息 ID、六个来源运行全部恢复。世界书组再次复现 keyword positive、andAny positive、in-window positive 与多个时序 positive 的 marker 缺失，同时保留相邻 negative control；这强化“mixed/regressed”而不是根因推断。
- 多主词 OR、空次级列表、`andAll/notAny/notAll`、scanDepth 0/1/上限、case/whole-word 边界、概率中间值、非零时序的独立先决正例、worldbook competing priority/order、atDepth 单变量索引、`user` role、marker 缺失回退、递归/group/useRegex 扩展，以及完整 ST world-info 方言映射，仍没有足够的当前 live 证据。

## Readback 扩展字段

当前 get/readback 还会出现 `excludeRecursion`、`preventRecursion`、`delayUntilRecursion`、`groupName`、`groupOverride`、`groupWeight`、`useGroupScoring`、`useRegex`。这些字段不在当前官方 LorebookEntry 字段段落和 MCP create/update entry schema 的显式 properties 中，现有产物通常只是显示默认值。

本文不为它们补写推测语义。若要使用，应先从更新后的官方文档或 MCP schema 获得定义，再做 native create/update、readback 和模型行为验证；仅因为 `additionalProperties: true` 或 readback 出现字段，不能把它们视为稳定作者 API。

## 证据索引

官方与 runtime：

- `assets/official-docs/text-20260710/cn_guides_lore-book.txt`
- `assets/official-docs/text-20260710/cn_guides_javascript-api.txt`
- `assets/schemas/mcp-surface-0.91.0-20260710.json`
- `assets/schemas/mcp-surface-index-0.91.0-20260710.json`

常驻行为：

- `artifacts/tavo-validation/20260710-constant-lorebook-diagnostic/source-lorebook.json`
- `artifacts/tavo-validation/20260710-constant-lorebook-diagnostic/lorebook-readback.json`
- `artifacts/tavo-validation/20260710-constant-lorebook-diagnostic/messages.json`
- `artifacts/tavo-validation/20260710-constant-lorebook-diagnostic/result.json`

关键词行为：

- `artifacts/tavo-validation/20260710-keyword-switch-channel-ab/source-lorebook.json`
- `artifacts/tavo-validation/20260710-keyword-switch-channel-ab/A-MCP-switch/readback.json`
- `artifacts/tavo-validation/20260710-keyword-switch-channel-ab/A-MCP-switch/messages.json`
- `artifacts/tavo-validation/20260710-keyword-switch-channel-ab/A-MCP-switch/result.json`
- `artifacts/tavo-validation/20260710-keyword-switch-channel-ab/B-UI-switch/result.json`
- `artifacts/tavo-validation/20260711-cross-feature-aggregate-v1/aggregate-manifest.json`

兼容导入与归一化：

- `artifacts/tavo-validation/20260710-020132-strict-import-kpi/source-files/lorebook/01-lorebook.json`
- `artifacts/tavo-validation/20260710-020132-strict-import-kpi/imports/016-lorebook-01/readback.json`
- `artifacts/tavo-validation/20260709-phone-method-smoke/notes.md`
- `artifacts/tavo-validation/20260709-phone-method-smoke/mcp-import-switch-result.json`

混合结果：

- `artifacts/tavo-validation/20260710-185800-semantic-model-kpi-v20/run-manifest.json`
- `artifacts/tavo-validation/20260710-185800-semantic-model-kpi-v20/semantic-sources/lorebooks/01-keyword-lorebook.json`
- `artifacts/tavo-validation/20260710-185800-semantic-model-kpi-v20/setup/semantic-lorebooks/01/readback.json`
- `artifacts/tavo-validation/20260710-185800-semantic-model-kpi-v20/model-calls/lorebook-trigger/01-natural-v1-attempt-1/preset-chat-readback.json`
- `artifacts/tavo-validation/20260710-185800-semantic-model-kpi-v20/model-attempt-results.json`

最新 constant 语义批次：

- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/run-manifest.json`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/context-registry.json`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-results.json`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/restore-original-chat.json`
