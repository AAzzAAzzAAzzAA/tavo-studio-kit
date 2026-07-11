# Preset Entries And Prompt Injection

本文只描述 Tavo `0.91.0` 在 `2026-07-10` 至 `2026-07-11` 可由 fresh 官方文档、当前 MCP schema 和已有真机证据支持的预设行为。不要把 SillyTavern 经验、导入前 JSON 或单次模型输出当成 Tavo 的运行时事实。

## Evidence Snapshot

- `official-current`: `https://docs.tavoai.dev/cn/guides/preset/`
- `official-current`: `https://docs.tavoai.dev/cn/guides/javascript-api/`
- `official-current`: `https://docs.tavoai.dev/cn/qa/`
- 本日完整重抓：`83/83` 页面，`errors=0`，`complete=true`；相关页面与 `assets/official-docs/text-20260710/` 中的持久快照哈希一致。
- `mcp-runtime`: 本日 strict discovery 返回 Tavo `0.91.0`、70 tools、18 resources、7 resource templates、0 prompts，且所有 schema/doc resource 读取成功。持久 schema 见 `assets/schemas/mcp-surface-0.91.0-20260710.json`。
- `live-verified`: `artifacts/tavo-validation/20260710-020132-strict-import-kpi/` 中 10 个预设完成真实导入和读回。
- `live-verified`: `artifacts/tavo-validation/20260710-104500-active-preset-runtime-diagnostic/` 中 5 次真实模型请求均命中各自预设标记，并在结束后恢复原 active 预设。
- `live-verified`: `artifacts/tavo-validation/20260710-141000-hidden-seed-preset-proof/` 中 5 次隐藏标记探针均通过；标记只存在于预设，不存在于用户提示或聊天 seed。
- `live-verified`: terminal passed 的 `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/` 中，五个单一 relative/system custom entry 分别约束唯一前缀和 `OBSERVE -> QUESTION -> VERIFY` 输出顺序，5/5 primary 与 1/1 unbound control 通过；结束后 active preset 恢复为 `id=2`。
- `live-verified`: `artifacts/tavo-validation/20260711-cross-feature-aggregate-v1/` 的 case 30/31 分别使用 single absolute entry、depth 0 与 depth 3，两个真实模型 exchange 都返回预声明 isolated marker；来源运行恢复了原 active preset 和原 chat。

## Preset Object

当前 TavoJS 文档把完整预设表示为：

```js
{
  id,
  name,
  basicPrompts,
  entries
}
```

当前 MCP create/update schema 还接受预设级 `active`、`official`，并提供独立工具 `tavo_preset_set_active`。`name` 是 MCP preset resource 的唯一必填字段；`basicPrompts` 与 `entries` 缺失部分在 TavoJS create 路径中由应用补默认值。

`basicPrompts` 是模板集合，例如 persona、description、personality、scenario、example-message start、chat start、group chat start、group nudge、continue nudge、impersonation 和 lorebook wrapper。它和 `entries` 不同：前者定义模板文字，后者定义实际提示组件及其排列、启用状态、消息 role 和注入方式。

## Entry Schema

当前 MCP schema 对单个 entry 的字段约束如下：

```json
{
  "identifier": "unique-id",
  "name": "Display name",
  "content": "Prompt text",
  "role": "system",
  "type": "custom",
  "injectionPosition": "relative",
  "injectionDepth": 0,
  "forbidOverrides": false,
  "enabled": true,
  "active": true
}
```

| Field | Current contract |
| --- | --- |
| `identifier` | 非空字符串；同一预设内用于定位、更新或删除条目。内置条目使用固定 identifier。 |
| `name` | UI 显示名，不替代 `identifier`。 |
| `content` | 提词正文；`marker` 是位置标记，官方定义为无正文。 |
| `type` | 仅 `builtin`、`marker`、`custom`。 |
| `role` | 仅 `system`、`user`、`assistant`；官方把它定义为消息角色。 |
| `injectionPosition` | 仅 `relative` 或 `absolute`。 |
| `injectionDepth` | 非负整数；只有 `absolute` 时生效。 |
| `enabled` | 条目在激活列表中是否启用。 |
| `active` | 条目是否加入激活列表；`false` 表示只存档，不参与提示词构建。 |
| `forbidOverrides` | 当前 schema 可写，但导入或其他写操作可能规范化；必须读回后再判断实际保存值。 |

一个 custom entry 要参与当前提示词构建，至少要同时满足：条目 `active=true`、`enabled=true`，并且其所属预设是当前运行所用预设。`active=false` 与 `enabled=false` 不是同一个状态，不应互换。

## Builtin And Marker Identifiers

官方当前列出的固定 identifier 如下。表格顺序是官方说明顺序；某个具体预设的 relative 排列仍以它自己的 `entries` 数组顺序为准。

| Identifier | Type | Meaning |
| --- | --- | --- |
| `main` | `builtin` | Main Prompt，核心指令。 |
| `worldInfoBefore` | `marker` | 角色描述上方的世界书插入点。 |
| `personaDescription` | `marker` | 用户身份描述插入点。 |
| `charDescription` | `marker` | 角色描述插入点。 |
| `charPersonality` | `marker` | 角色性格插入点。 |
| `scenario` | `marker` | 场景描述插入点。 |
| `enhanceDefinitions` | `builtin` | 增强角色定义的补充提词。 |
| `nsfw` | `builtin` | Auxiliary Prompt，默认可为空。 |
| `worldInfoAfter` | `marker` | 角色描述下方的世界书插入点。 |
| `dialogueExamples` | `marker` | 对话示例插入点。 |
| `chatHistory` | `marker` | 聊天历史插入点。 |
| `jailbreak` | `builtin` | Post-History Instructions。 |

不要给 marker 的 `content` 编造运行时意义。它的职责是占位；实际插入内容来自 persona、character、worldbook、examples 或 history 等对应层。

## Relative And Absolute

| Mode | Official-current meaning | Depth behavior |
| --- | --- | --- |
| `relative` | 跟随预设 `entries` 列表顺序。 | `injectionDepth` 不生效，即使读回对象仍保留了一个数值。 |
| `absolute` | 插入到聊天历史的特定深度。 | `injectionDepth` 生效。 |

### Depth 0, 1, N

官方当前定义是：

- `0`: 最后一条消息之后。
- `1`: 最后一条消息之前。
- `N`: 按同一规则继续向更早的聊天历史位置移动，且 `N` 必须是非负整数。

这里的 depth 是提示构建中的注入深度，不应直接等同于 MCP message 的持久化 `index`。2026-07-11 的 depth 0 和 depth 3 isolated probes 都证明对应 entry 可以到达模型，但 marker 出现不能证明它在最终 prompt 中的精确相邻位置。现有官方文档和真机证据仍没有证明：depth 超过可用历史长度、隐藏消息是否参与计数、裁剪后的历史如何计数、多个 absolute entry 位于同一深度时的稳定先后次序。遇到这些情况应看本次上下文日志，而不是按其他酒馆实现类推。

## Role

`role` 只允许：

- `system`: 作为 system 角色的提示组件。
- `user`: 作为 user 角色的提示组件。
- `assistant`: 作为 assistant 角色的提示组件。

官方把 role 配置放在 custom entry 的“角色与注入”部分。它描述生成上下文中的消息角色，不等于新增一条持久化聊天消息，也不等于修改角色说话人。不同模型协议可能对连续同 role 消息进行合并或转换；当前资料没有承诺 provider 最终 wire payload 的逐条形态。

## Ordering Rules

1. Relative entry 的顺序由 `preset.entries` 数组顺序决定，不由 `name`、`identifier` 的字典序或创建时间决定。
2. Marker 也占据这个相对顺序，因此移动 marker 会移动对应动态层的位置。
3. TavoJS 官方文档明确说明 `tavo.preset.update(preset)` 中传入的 `entries` 会直接覆盖原数组。安全写法是先 `get`，在完整数组上修改，再 `update`。
4. MCP 提供 `tavo_preset_entry_upsert` 和 `tavo_preset_entry_delete`。schema 能证明它们按 `presetId` 和 `identifier` 操作，但没有定义“新 identifier upsert 后插入数组的哪个位置”；实际顺序必须用 `tavo_preset_get` 读回。
5. SillyTavern preset import 会被转换为 Tavo 的 `basicPrompts` 与 `entries`。真机 10 次导入证明了转换和读回可用，也证明导入会规范化字段；提交顺序或字段值不能只看源文件判定。

## Entry Activation Vs Preset Activation

这里有三层不同状态：

| Layer | Field or tool | What it proves |
| --- | --- | --- |
| Entry membership | `entry.active` | 条目是否进入该预设的激活列表。 |
| Entry switch | `entry.enabled` | 已在激活列表中的条目是否启用。 |
| Preset selection | `chat.presetId` and preset-level `active` | 哪个预设与聊天绑定，以及预设库当前哪个对象处于 active 状态。 |

### `chat.presetId`

- 它是 chat resource 的会话级绑定字段。
- 当前 MCP 的 `tavo_chat_create` / `tavo_chat_update` 对 `chat` 使用开放对象 schema；真实创建与 `tavo_chat_get` 读回已经保存 `presetId`。
- 它证明“这条 chat 记录引用哪个 preset”，不单独证明该预设内容已经进入某次模型请求。
- 当前官方 TavoJS `tavo.chat.current()` 返回 `preset: {id, name}` 概要，但 `tavo.chat.update()` 的公开可更新字段列表没有列出 preset；通过 TavoJS 修改 preset 绑定不能从该页面推断。

### Global Preset `active`

- MCP preset 对象有顶层 `active`，并提供 `tavo_preset_set_active(id)`。
- 真实 active-preset diagnostic 在开始时读到唯一 active preset `id=2`，逐次把目标 preset 设为 active，模型调用后再恢复 `id=2`。
- `tavo_preset_set_active` 的真实 diff 显示目标从 `active=false` 变为 `true`；快照与恢复检查按“全库唯一 active preset”验证。
- 它证明预设库的全局 active 选择，不替代 chat 自己的 `presetId` 读回。

### When They Differ

已有成功真机探针在每次发送前都执行了两项检查：先从 chat 读出 `presetId`，再把同一个 preset 设为全局 active。隐藏标记随后在 5/5 次真实模型回复中出现。

v23 延续了同一安全条件：五个 primary chat 的 `presetId` 分别指向目标 preset，发送前将同一 preset 设为全局 active；unbound control 使用 neutral preset。五个目标回复都以各自 `SEM_PRESET_*` 开头并按要求输出三个标签，control 没有泄漏目标 marker。运行结束后的 `runtime-phases/01/active-preset-runtime/restore-all-model-calls-complete/result.json` 再次确认最终 active 集合为 `[2]`。

这组证据没有提供一个受控的“不一致 A/B”来证明冲突时究竟由 `chat.presetId` 还是全局 active 获胜。因此当前可靠规则是：

1. 用 `tavo_chat_get` 验证 chat 的 `presetId`。
2. 用 `tavo_preset_get` 验证该 preset 的顶层 `active`。
3. 在运行时验证前让两者指向同一 ID。
4. 不把任一读回字段单独写成“已证明注入”。

## Validation Method

### 1. Refresh The Surface

```bash
python3 scripts/fetch_official_docs.py --output /tmp/tavo-official-docs-current
python3 scripts/dump_mcp_surface.py --strict --output /tmp/tavo-mcp-surface-current
```

确认 server version、`tavo_preset_*` tools、`tavo_chat_*` tools 与 entry input schema。不要复用旧 token，也不要把 token 写入证据文件。

### 2. Validate Shape Without Mutation

对 create/update/upsert 先使用 `dryRun=true`：

- 检查 `identifier` 非空。
- 检查 `type`、`role`、`injectionPosition` 枚举。
- 检查 `injectionDepth >= 0`。
- 检查 `enabled` 和 `active` 分开设置。
- 保存 dry-run diff，但不要把 dry-run 当成持久化成功。

### 3. Roundtrip Persistence

1. `tavo_preset_get` 保存修改前对象与 revision。
2. 使用 `expectedRevision` 和唯一 `clientRequestId` 写入。
3. 再次 `tavo_preset_get`。
4. 逐项比较 `entries` 顺序、role、position、depth、enabled、active 与正文。
5. 对 import 路径比较源对象与 Tavo 读回对象，记录所有规范化差异。

### 4. Verify Binding And Global State Separately

1. `tavo_chat_get` 记录 `chat.presetId`。
2. 全量搜索并逐个 get preset，记录所有顶层 `active=true` 的 ID。
3. dry-run `tavo_preset_set_active`，确认 dry-run 不改变读回。
4. actual set-active 后再次读取目标 preset 与 active 集合。
5. 测试结束后恢复原 active preset，并再次核对 active 集合。

### 5. Prove Runtime Injection

最强的现有方法是隐藏唯一标记探针：

1. 只在目标 preset entry 中放一个随机、不可猜的 marker。
2. 保证 marker 不在用户提示、character、persona、worldbook、regex、plugin、聊天 seed 和先前消息中。
3. 创建或选择绑定该 preset 的 chat，并让 `chat.presetId` 与全局 active ID 一致。
4. 通过正常 UI/MCP input send 触发真实模型请求。
5. 用 message readback 检查可见 assistant 回复，并保存请求前后的 message IDs/count。
6. 至少使用不同 marker 重复多次；`20260710-141000-hidden-seed-preset-proof` 已按此方法完成 5/5。

### 6. Prove Position, Depth And Role

模型是否复述 marker 只能证明“模型看到了它”，不能证明 entry 的精确位置或 role。精确验证使用官方上下文日志：在设置中开启上下文日志，进入聊天右侧面板的“日志”，检查预设匹配/触发、最终上下文构造与模型调用记录。

对 position/depth/role 的证据应同时保存：

- 提交的 preset JSON；
- `tavo_preset_get` 读回；
- chat 的有序消息快照；
- 上下文日志中 entry 前后的相邻组件；
- 模型调用记录中的 role；
- 最终 assistant message readback。

没有上下文日志或等价的最终请求证据时，只能把 relative/absolute/depth/role 写成 `official-current` 或 `mcp-runtime`，不能升级为逐位置 `live-verified`。

## Current Verification Boundary

| Claim | Evidence level through 2026-07-11 |
| --- | --- |
| Entry 字段、枚举、非负 depth | `official-current` + `mcp-runtime` |
| Relative 跟随列表顺序；absolute 使用 history depth；0/1/N 语义 | `official-current` |
| 预设导入、保存、读回可用 | `live-verified`, 10/10 retained imports |
| `chat.presetId` 可持久化和读回 | `live-verified` |
| preset 顶层 active 可切换并恢复 | `live-verified` |
| 对齐 chat binding 与 global active 后，预设隐藏 marker 到达真实模型 | `live-verified`, 5/5 hidden probes |
| 单个 relative/system custom entry 可约束唯一 prefix 与输出标签顺序 | `live-verified`, v23 5/5 primary + 1/1 unbound control |
| 单个 absolute entry 在 depth 0 与 depth 3 可到达真实模型 | `live-verified`, 2026-07-11 两个 isolated semantic probes；不是精确顺序证明 |
| 两者不一致时的优先级 | 未被现有受控证据证明 |
| 多个 absolute entry 同 depth 的 tie-break | 未被现有受控证据证明 |
| 超长 depth、隐藏消息、裁剪历史的计数方式 | 未被现有受控证据证明 |
| provider 最终如何合并相邻同 role 消息 | 未被当前官方文档或真机证据承诺 |

v23 的 `orderedMarkers` 检查的是模型可见回复中的标签顺序，不是多个 preset entries 在最终 prompt 中的相邻位置。2026-07-11 的 absolute probes 同样只证明 marker 可达。两组证据都不能升级“多个 relative entries 精确排列”“absolute depth 的相邻位置”“provider wire role”这些仍需上下文日志证明的结论。
