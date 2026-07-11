# Character Opening Messages And Examples

本文区分角色开场白、备用问候和对话示例，并说明 TavoJS、MCP、CCv2/CCv3 三条数据通道的字段名与真实验证边界。结论基于 `2026-07-10` fresh 官方文档、当前 Tavo `0.91.0` MCP schema，以及截至 `2026-07-11` 的真机证据。

## Evidence Snapshot

- `official-current`: `https://docs.tavoai.dev/cn/guides/bots/create/greeting/`
- `official-current`: `https://docs.tavoai.dev/cn/guides/bots/create/example/`
- `official-current`: `https://docs.tavoai.dev/cn/guides/javascript-api/`
- `official-current`: `https://docs.tavoai.dev/cn/guides/chat/start/`
- 本日完整重抓：`83/83` 页面、`errors=0`、`complete=true`；上述页面与 `assets/official-docs/text-20260710/` 的持久快照哈希一致。
- `mcp-runtime`: 本日 strict discovery 返回 Tavo `0.91.0`、70 tools、18 resources、7 resource templates、0 prompts。当前 character resource 要求 `name`、`description`、`first_mes`；create/update tool schema 暴露 snake_case 字段。
- `live-verified`: `artifacts/tavo-validation/20260710-020132-strict-import-kpi/` 中 15/15 个 CCv2 角色卡在真机完成导入和读回，三个目标字段均保留。
- `live-verified`: `artifacts/tavo-validation/20260709-phone-method-smoke/` 完成角色导入、零消息 chat 创建、当前线程切换、开场白选择面板和确认后首条 assistant message 读回。
- `live-verified`: `artifacts/tavo-validation/20260710-keyword-ui-send-diagnostic/` 再次捕获主问候与两个备用问候的宏展开面板，并读回宏展开后的主问候为 index `0` assistant message。
- `live-verified`: terminal passed 的 `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/` 使用五张 retained CCv2 卡，让只存在于 `data.description` 的五个工作标记分别到达真实模型回复，character-thread 5/5。该批次没有操作 greeting picker，也没有隔离 `mes_example`。
- `live-verified`: `artifacts/tavo-validation/20260711-cross-feature-aggregate-v1/` 的 case 26-29 分别物化主问候、备用 A、备用 B，并隔离 `mes_example`。三个 greeting selection result 都按 stable message ID 找到正确 marker；备用 A 的后续模型格式探针通过，备用 B 的 greeting 物化通过但模型首行格式失败，主问候物化通过但后续 assistant content 为空。`mes_example` only marker 到达真实模型并通过；它仍不证明最终 prompt 的精确位置或 role。

## Three Different Fields

| CC/MCP field | Purpose | Visible chat behavior |
| --- | --- | --- |
| `first_mes` | 主开场白，定义首次见面时的场景、语气、动作密度和节奏。 | 在新 chat 的问候选择中作为主选项；确认后可成为 index `0` 的 assistant message。 |
| `alternate_greetings` | 单聊备用开场白数组。 | 与主开场白一起出现在选择面板中，供用户选择。 |
| `mes_example` | 对话示例字符串，用于给模型示范 `{{char}}` / `{{user}}` 的说话与互动方式。 | 不属于问候选项；按上下文预算进入生成提示。 |

不要把 `mes_example` 拆成备用问候，也不要把 `alternate_greetings` 拼进 examples。它们分别服务于“用户选择首条可见消息”和“模型上下文示范”。

`groupOnlyGreetings` / `group_only_greetings` 是群聊专用开场白，与这里的单聊 `alternate_greetings` 分开。官方群聊页面说明它不影响一对一聊天。

## Channel Mapping

| Meaning | TavoJS native object | MCP create/update and readback | CCv2/CCv3 card data |
| --- | --- | --- | --- |
| 主开场白 | `firstMes` | `first_mes` | `data.first_mes` |
| 备用问候 | `alternateGreetings` | `alternate_greetings` | `data.alternate_greetings` |
| 对话示例 | `mesExample` | `mes_example` | `data.mes_example` |

### TavoJS CamelCase Channel

官方当前 TavoJS 文档说明：

- `tavo.character.get/find` 返回的 Tavo 角色对象使用 `firstMes`、`alternateGreetings`、`mesExample`。
- `tavo.character.create` 要求 `name` 和 `firstMes`。
- `tavo.character.update` 要求 `id`、`name` 和 `firstMes`。
- create/update 同时接受 CCv3 风格 snake_case 字段，例如 `first_mes`、`mes_example`、`creator_notes`，并自动转换为 Tavo 格式。

在 TavoJS 原生对象中优先使用 camelCase。不要在同一个对象中同时提交 `firstMes` 与 `first_mes`；官方没有定义两者冲突时的优先级。

### MCP Snake_Case Channel

当前 `tools/list` 的 machine-readable schema 是 MCP 调用的准绳：

```json
{
  "character": {
    "name": "Example",
    "description": "...",
    "first_mes": "...",
    "alternate_greetings": ["..."],
    "mes_example": "<START>\n{{user}}: ...\n{{char}}: ..."
  }
}
```

- `tavo_character_create` 的当前 schema 要求 `name`、`description`、`first_mes`。
- `alternate_greetings` 必须是字符串数组。
- `mes_example` 必须是字符串，不是数组。
- `tavo_character_update` 接受同一组 snake_case 字段，并允许部分 character object；写前仍应先 get，以免丢失未知字段。
- `tavo_character_get` 的真实读回把角色正文放在 `data` 中，并使用 snake_case。
- `tavo://schemas/character` 当前也把 `first_mes` 列为必填字段。

不要把 TavoJS 的 camelCase 示例直接塞进 MCP `character` 参数。MCP schema 与 TavoJS adapter 是两条不同通道。

### Card Import Channel

`tavo_character_import_card` 接受一个开放的 `card` object；当前 tool schema 不逐字段限制 envelope。开放 schema 只表示 transport 接受对象，不等于每个 card spec、extension 或字段组合都已通过运行时验证。

导入时使用一套完整且单一的 card 结构：

```json
{
  "spec": "chara_card_v2",
  "spec_version": "2.0",
  "data": {
    "name": "Example",
    "description": "...",
    "first_mes": "...",
    "alternate_greetings": ["..."],
    "mes_example": "<START>\n{{user}}: ...\n{{char}}: ..."
  }
}
```

不要把 card envelope 传给 `tavo_character_create`；也不要把裸 MCP `character` object 当成一张已经声明 spec 的 CC 卡。

## CCv2 And CCv3

### CCv2: Live-Verified Import

本日 strict import KPI 使用了 15 张真实 `chara_card_v2` / `spec_version: "2.0"` JSON 卡。每张卡都包含：

- `data.first_mes` 字符串；
- 两项 `data.alternate_greetings`；
- 带 `<START>` 的 `data.mes_example` 字符串。

15/15 均完成 actual import 和 `tavo_character_get` 读回，三个字段保持为 snake_case 且内容保留。因此，“当前 Tavo `0.91.0` MCP import path 能导入这类 CCv2 JSON 并保存三个字段”是 `live-verified`。

这个结论不自动覆盖 PNG chunk、所有 CCv2 扩展或任意第三方畸形卡。

### CCv3: Official-Current, Not Live-Roundtripped Here

官方 TavoJS 文档明确写到：

- create/update 接受 CCv3 snake_case 字段并自动转换；
- `tavo.character.import(card)` 接受完整 `{spec: "chara_card_v3", data: {...}}` 或裸 `data` 对象；
- card 中的 `character_book` 和 `extensions.regex_scripts` 有对应联动导入说明，并会先请求用户确认。

当前 MCP import schema 对 `card` 是开放对象，因此没有与官方说法冲突。但现有保留真机 artifacts 中没有一张明确标记为 `chara_card_v3` 的完成导入、读回、开聊证据。CCv3 在本文中的等级是 `official-current` + `mcp-runtime-open-schema`，不是本地 `roundtrip-pass`。

## `first_mes`

官方“第一条消息”页面把它作为角色第一次出现时的完整开场。写作上它可以同时完成：

- 把 `{{char}}` 和 `{{user}}` 放进场景；
- 展示角色语气与动作节奏；
- 给用户一个可以立即回应的抓手；
- 以实际文本而非抽象形容词示范回复长度和排版。

当前 schema 边界：

- MCP character resource/create 要求非缺失的 `first_mes` 字段；schema 类型是 string。
- 官方 TavoJS create/update 要求 `firstMes`。
- 资料没有规定空字符串是否在所有 UI 路径都可正常开聊，因此不要用“字段存在但内容为空”替代有效开场。

真机边界：新 chat 创建后可以仍为 `messageCount: 0`。在已有 smoke 中，`first_mes` 没有在 MCP `tavo_chat_create` 返回时立即物化；它是在切换到新 chat、出现“开场白”面板并确认后，才成为 index `0`、role `assistant` 的持久消息。

## `alternate_greetings`

当前 MCP schema 要求字符串数组。已有真机角色包含两个备用问候；切换到新 chat 后，UI 面板依次显示：

1. 主 `first_mes`；
2. 第一条 `alternate_greetings`；
3. 第二条 `alternate_greetings`。

面板中的 `{{char}}` 和 `{{user}}` 已按当前角色与 persona 展开，这证明选择 UI 会渲染宏后的文本。早期 smoke 只确认主 `first_mes`；2026-07-11 的新矩阵随后在两个独立 chat 中分别点选 alternate A/B，并通过 stable message ID 读回对应 marker。因此：

- “备用问候会出现在选择面板”是 `live-verified`。
- 测试卡中的两项 alternate 都已完成选择，并在各自 chat 的一条 assistant message 中按 stable ID 找到目标 marker；这不单独证明该消息必为 index 0，也没有在 selection artifact 内排除同一消息同时含其它 greeting marker，更不外推到任意数量、空项、超长文本或群聊专用 greeting。
- 当前 MCP tools 没有公开一个 greeting index/choice 参数；不能虚构 `greetingIndex`、`alternateGreetingId` 或类似字段。

## `mes_example`

官方对话示例页面给出当前规则：

- 每个示例块前加 `<START>`。
- 使用 `{{char}}` 与 `{{user}}`，不要硬编码当前角色或用户名称。
- 示例在上下文空间充足时逐步插入。
- 文本生成 API 会把 `<START>` 转为示例分隔符；聊天式 API 会据此插入新的示例对话。
- `<START>` 标签本身不会原样留在最终提示内容中。

当前 MCP native field 是一个 string。多组示例应在同一字符串中用多个 `<START>` 分隔，例如：

```text
<START>
{{user}}: 第一种情境。
{{char}}: 第一种回应。
<START>
{{user}}: 第二种情境。
{{char}}: 第二种回应。
```

`mes_example` 的位置还取决于当前 preset 是否保留并启用了 `dialogueExamples` marker，以及上下文预算。角色 get 读回只能证明数据已保存，不能证明本次模型请求实际包含了示例。

2026-07-11 case 29 把唯一 marker 只放在 `mes_example`，真实模型回复返回该 marker，形成一次 isolated semantic pass。它证明测试配置下 example 内容到达模型；由于没有 provider wire payload 或上下文日志，仍不能证明 `<START>` 转换后的精确相邻位置、role 或多 example 裁剪顺序。

## Chat Creation, Greeting Choice And Thread Switching

当前 MCP 的相关工具是：

- `tavo_chat_create`
- `tavo_chat_get`
- `tavo_current_chat_get`
- `tavo_current_chat_set`
- `tavo_message_count/find/get`

已有真机流程证明：

1. `tavo_character_import_card` dry-run 与 actual import 成功，读回保留三个 opening/example 字段。
2. `tavo_chat_create` 使用 `characterIds` 与 `personaId` 创建新 chat。
3. 新 chat 的第一次 `tavo_chat_get(includeMessages=true)` 返回 `messageCount: 0` 和空 `messages`。
4. `tavo_current_chat_set` 把当前线程从旧 chat 切换到新 chat；dry-run 和 actual 均有独立 diff/readback。
5. Android UI 随后显示“开场白”选择面板，包含主问候和两个备用问候。
6. 确认主问候后，`tavo_chat_get(includeMessages=true)` 返回 `messageCount: 1`。
7. 新消息位于 `index: 0`，`role: "assistant"`，`characterId` 指向导入角色，content 与宏展开后的 `first_mes` 一致。

这说明三个动作必须分开理解：

- 创建 chat：建立会话记录，可能仍无消息。
- 切换当前线程：改变 app 当前 chat，可能触发 UI 选择流程。
- 确认问候：把所选开场物化为第一条 assistant message。

不要在 MCP create 成功后立刻声称开场白已经写入，也不要把 `tavo_current_chat_set` 的成功等同于问候已确认。

## Validation Method

### 1. Schema And Channel Check

1. fresh dump `tools/list` 与 `tavo://schemas/character`。
2. TavoJS object 使用 camelCase；MCP create/update 使用 snake_case；card import 使用 CC envelope 内的 snake_case。
3. 不在同一 payload 中同时放 camelCase 与 snake_case 同义字段。

### 2. Field Roundtrip

为三个字段使用互不相同的随机 marker：

```text
OPEN_MAIN_<nonce>
OPEN_ALT_A_<nonce>
EXAMPLE_ONLY_<nonce>
```

先 dry-run，再 actual create/import，最后 `tavo_character_get`。逐字段比较类型、数组顺序、换行、`<START>` 和宏文本。导入成功但读回不一致时，只能记录为 normalization，不能记为精确保留。

### 3. Main Greeting Materialization

1. 创建只绑定目标 character/persona 的新 chat。
2. 确认 `messageCount: 0`。
3. `tavo_current_chat_set` 切换过去。
4. 捕获 UI tree 与截图，确认面板包含 `OPEN_MAIN_<nonce>`。
5. 选择主问候并确认。
6. `tavo_chat_get(includeMessages=true)` 和 `tavo_message_get` 确认 index `0` assistant content。

### 4. Alternate Greeting Materialization

为每个 alternate 使用独立的新 chat，避免旧 index `0` 干扰。捕获选择前面板，明确点击目标 alternate，再确认；读回的首条 assistant content 必须包含对应 alternate marker，且不得包含 main 或其他 alternate marker。UI 截图只能证明显示，message readback 才能证明持久化。

### 5. Example Injection

1. 把 `EXAMPLE_ONLY_<nonce>` 只放在 `mes_example`，不放入 greeting、description、scenario、preset、worldbook、history 或用户提示。
2. 确认当前 preset 的 `dialogueExamples` marker 为 `active=true` 且 `enabled=true`。
3. 开启官方上下文日志并发送一次正常模型请求。
4. 在最终上下文构造中检查 example block 的位置、role 转换和 `<START>` 处理。
5. 保存 character readback、preset readback、发送前消息、上下文日志和发送后 assistant message。

模型在可见回复中复述 example marker 不是必要条件；`mes_example` 的直接证据是它进入了最终生成上下文。若只看到字段读回而没有上下文日志，证据等级停留在 persistence，不升级为 runtime injection。

## Current Verification Boundary

| Claim | Evidence level through 2026-07-11 |
| --- | --- |
| TavoJS camelCase object 与 CCv3 snake_case adapter | `official-current` |
| MCP snake_case 字段、类型和 required 集合 | `mcp-runtime` |
| CCv2 JSON 导入并保留三个字段 | `live-verified`, 15/15 retained imports |
| CCv3 full-card import | `official-current`; 本地无明确 CCv3 roundtrip artifact |
| 新 chat 初始为 0 messages | `live-verified` |
| 当前线程可通过 MCP 切换 | `live-verified` |
| 选择面板显示 `first_mes` 与两个 alternates | `live-verified` |
| 选择面板中宏按 character/persona 展开 | `live-verified` |
| 确认主问候后物化为 index 0 assistant message | `live-verified` |
| 确认测试卡两项非默认 alternate 后目标 marker 的 assistant-message readback | `live-verified`, 两个独立 chat 与 stable message IDs；index 0/互斥字段仍需更严断言 |
| `mes_example` 在角色对象中导入和读回 | `live-verified` |
| 隔离 `mes_example` marker 到达真实模型 | `semantic-pass`, 1 个 isolated exchange；不证明精确 position/role |
| `mes_example` 在某次最终上下文中的精确位置与 role | 未被现有隔离证据证明 |
| greeting 选择的 MCP 参数或无 UI 自动选择接口 | 当前 schema 未暴露，不能虚构 |
| `data.description` 中的隔离 marker 到达真实模型回复 | `live-verified`, v23 character-thread 5/5 |

v23 的新增证据只加强“角色 description 参与当前 prompt”的窄结论。2026-07-11 的新矩阵补上测试卡主/两项 alternate 的物化与一个 example-only semantic probe；主问候和 alternate B 后续模型格式失败不推翻已经按 stable ID 通过的 greeting 持久化，也不能被改写成 greeting 选择失败。`mes_example` 的精确最终位置仍需上下文日志独立取证。
