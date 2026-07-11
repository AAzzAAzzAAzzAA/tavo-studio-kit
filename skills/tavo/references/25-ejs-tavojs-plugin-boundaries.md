# EJS, TavoJS, Plugin, And MCP Boundaries

本页固定宏、EJS、TavoJS、TPG 插件和 MCP 五条通道的能力边界。重点不是罗列“看起来能做什么”，而是区分：提示词渲染、WebView 运行、插件封装、外部 RPC、持久数据写入和可视化证明分别由什么证据支持。

## Snapshot And Verdict Contract

当前声明面为 Tavo `0.92.0`；0.92 真机原子行为摘要为 `assets/evidence/0.92.0/20260717-live-matrix.json`。AR/EJS/世界书等未在该摘要中重测的 effect 仍沿用明确标注的 0.91 保留基线，不能被 0.92 插件矩阵代证。

- fresh 官方文档：2026-07-16 fail-closed 全量抓取完成，`83` 页、`0` 错误、`0` 未抓取、`0` 缺失文本；持久快照为 `assets/official-docs/text-20260716/` 与 `assets/official-docs/official_manifest-20260716.json`。
- current MCP surface：Tavo `0.92.0`，`70` tools、`18` resources、`7` resource templates、`0` prompts，17/17 动态 docs/schema 读取成功；路径为 `assets/schemas/mcp-surface-0.92.0-20260716.json`。
- current live gate：`assets/evidence/0.92.0/20260716-gate.json` 只证明 ADB/MCP 传输、版本、发现、文档读取、`tavo_status` 与原聊天/空输入锚点。
- current live matrix：`assets/evidence/0.92.0/20260717-live-matrix.json` 逐原子记录 entry/config/input/generation/TTS/package/theme/media/backup 结果；F05、F09、F11 为 mixed，媒体假网关不能替真人听感或真实供应商。
- prior-version live evidence：2026-07-10 至 2026-07-11 的 AR、TavoJS、插件、世界书与消息 artifact 均来自 Tavo `0.91.0`。它们可作回归控制，不能直接升级 0.92 新 `entry`、Hooks、config、TTS、input send、备份、主题或 ASR 语义。
- current declaration delta：新插件以根 `entry.js` 为入口，旧 `scripts.actions` 为兼容别名；新增插件 config 读取、chat/message 通知、input 拦截、generation 生命周期、TTS 与结构化 `tavo.input.send()` 结果。声明面为 `official-current`/`mcp-runtime`，真机可靠性只按 live matrix 的具体原子行为提升。

本文只使用三个 verdict：

- `verified`：精确到原子行为的结论已有对应版本的真机 effect/readback/UI artifact；必要时用 `verified (surface)` 与 `verified (effect)` 区分“入口存在”和“效果发生”。0.91 effect 不能省略版本标签。
- `official-only`：fresh 官方文档描述了该行为，但当前证据没有执行并回读这一精确行为。
- `runtime-only`：0.92 MCP 文档、schema 或工具面声明了行为，但没有匹配的 Android effect。
- `missing`：fresh 官方文档、current MCP 和对应版本真机证据都没有证明该精确行为；这表示“证据缺失”，不自动表示产品绝对不支持。

任何 verdict 都只覆盖该格写明的原子行为。一个通道的成功不能自动提升另一个通道，同名 API 在不同宿主中的成功也不能互相代证。

## Five Channels At A Glance

| 通道 | 运行阶段与宿主 | 当前能力边界 | 不能据此声称 |
| --- | --- | --- | --- |
| 宏 `{{...}}` | 提示词式文本的宏展开；EJS 之后 | 注入角色、用户、场景、最近消息等上下文；操作 chat/global 变量宏 | 读取或修改世界书资产；控制真实输入框；消息 CRUD；执行 DOM/JS；证明 AR UI |
| EJS `<% ... %>` | 提示词组装阶段；先于宏 | 条件、循环、字符串输出、chat/global 变量 helper；可在世界书内容和扫描关键词等提示词字段中运行 | 任意浏览器 JS；`tavo.*` API；世界书资产 CRUD；输入框控制；消息 CRUD；插件 contribution |
| TavoJS `tavo.*` | 开启相应 WebView/JavaScript 运行条件后的脚本环境 | 官方公开变量、消息、聊天、世界书、输入框、文件、生成、图片与 TTS 等 API | 仅凭文档证明真机执行、声音、视觉布局、确认弹窗、字段保真或重启后持久化 |
| TPG 插件 | 安装的 `.tpg` 包；根 `entry.js`、native contribution 加 scoped TavoJS facade | actions/sidebar/fragments/settings；config 读取；chat/message、input、generation Hooks；TTS | 把 TPG 当成独立数据 API；把 `permissions` 当强制沙箱；把注册/文档面当 0.92 effect |
| MCP | 外部 agent 通过 HTTP JSON-RPC `tools/call` 调用当前暴露工具 | 世界书、聊天、消息、输入框、插件和多类资产的明确工具/schema；读写安全字段 | 直接读写 Tavo 变量；执行气泡 TavoJS；证明 AR 布局、点击、遮挡、CSS 或 WebView 生命周期 |

## Worldbook Read And Mutation

宏和 EJS “能写在世界书里”只表示世界书条目进入提示词组装时可以展开或执行模板。它们修改变量或输出文本时，没有读取世界书列表、取得世界书对象、保存条目或删除资产。

| 原子结论 | 宏 | EJS | TavoJS | TPG | MCP |
| --- | --- | --- | --- | --- | --- |
| 在世界书提示词字段中做动态文本 | `official-only` | `official-only` | `missing` | `missing` | `missing` |
| 读取世界书列表或对象 | `missing` | `missing` | `official-only` | `official-only`，经 scoped TavoJS | `verified (surface+read)` |
| 暴露 create/import/update/delete 入口 | `missing` | `missing` | `official-only` | `official-only`，经 scoped TavoJS | `verified (surface)` |
| 持久 import 后可再次读取 | `missing` | `missing` | `missing` | `missing` | `verified (effect)` |
| create/read/update 经插件 TavoJS 完成并由 MCP 持久回读 | `missing` | `missing` | `verified (effect, plugin host)` | `verified (effect)` | `verified (readback)` |
| actual delete 后 not-found | `missing` | `missing` | `official-only` | `official-only` | `missing`；本轮默认保留对象，仅做 tombstone update |
| 导入字段原样保真 | `missing` | `missing` | `missing` | `missing` | `missing`；已有反例证明会规范化 |

具体边界：

- 宏：世界书内容中可用 `{{char}}`、`{{user}}`、`{{scenario}}`、最近消息和变量宏。`{{setvar::...}}` 改的是会话变量，不是世界书条目。
- EJS：fresh docs 明确覆盖世界书“条目内容、扫描关键词”。`getvar/setvar/incvar/decvar/delvar` 改的是两层变量存储，不是世界书资产。
- TavoJS：fresh docs 暴露 `tavo.lorebook.all/get/find/import/create/update/delete`。`import` 明确会先弹用户确认；当前官方页面没有同样明确承诺世界书 `create/update/delete` 都弹确认，因此不能类推。
- TPG：current runtime docs 把 `tavo.lorebook.*` 放进 action/fragment 的 scoped facade。2026-07-11 case 34 已由 native plugin actions 依次执行 create/read/update 和保留式 tombstone update，宿主 action 返回对象 id `315`，MCP 按同一 id/marker readback，四步 direct runtime proof 通过。真实 delete 没有执行，不能把 tombstone 称为删除。
- MCP：当前 tools 明确包含 `tavo_lorebook_search/get/create/update/import/delete`、`tavo_lorebook_entry_upsert/delete`。本轮只读重验通过 `search/get` 读回 retained 世界书 id `2`、revision `rev_c7df71df3f0b195b` 和 smoke marker；registry 记录其来源是实际 import。
- 当前回读对象中的 entry identifier、默认策略和多项字段已被 Tavo 规范化。它证明“导入并持久存在”，同时反证“提交对象逐字段原样保存”。
- case 34 的后续模型回复没有按测试格式返回预声明 marker，所以该 case 的 semantic 层失败；这不推翻已经按 id/readback 通过的 create/read/update/tombstone effect，也不能被写成“插件 CRUD 全部失败”。

## Variables And Scope

变量名相同不代表作用域相同，也不代表五个通道共享同一个访问入口。

| 通道 | 文档中的 scope | 当前结论 |
| --- | --- | --- |
| 宏 | chat：`setvar/addvar/incvar/decvar/getvar`；global：对应 `*globalvar` | `official-only`；没有当前宏渲染 artifact 证明持久效果 |
| EJS | `chat` 默认、`global`；`local` 兼容 chat；`message`/`initial` 在 EJS helper 中也按 chat 处理 | chat `setvar/getvar/incvar` 与 TPG/TavoJS chat scope 互操作为 `verified`；global 为 `official-only`；EJS 的 `message` 名称不是 TavoJS 的真实 message scope |
| TavoJS | `chat`、`global`、`message`，三者完全隔离 | chat `set/get` 为 `verified`；global/message 持久行为为 `official-only` |
| TPG | action/fragment 共享 scoped `tavo.get/set/update/unset`；只有 `/messages` fragment 有当前消息上下文 | native input action 中 chat `set/get` 为 `verified`；其它 facade 方法与 global/message 持久性为 `official-only` |
| MCP | current capabilities 把 variables 标为 `planned`，不是 available tool group | `missing`；当前没有 MCP 变量 get/set/unset 工具 |

现有真机 AR artifact 中，按钮代码先执行 `tavo.set(key, 'clicked', 'chat')`，再以 `tavo.get` 读取，随后把 `state=clicked` 写入可见状态和输入框。`after-click/screen.png` 与 `after-click/ui.xml` 同时出现该 marker，因此这只验证了当前 AR/TavoJS 宿主里的 chat scope set/get。它不验证：

- global scope 跨聊天或重启持久化；
- message scope 绑定、随消息删除或稳定 id roundtrip；
- chat 变量随导出/导入保留；
- 宏对同名变量的实际互操作；
- MCP 直接读取变量。

v23 为 EJS 与 TPG/TavoJS 的 chat scope 增加了双向 effect proof。每个 macro-ejs case 先由 native plugin action 用 `tavo.set` 写入一个运行时随机 token；角色 `description` 中的 EJS `getvar` 把该 token 放进真实模型上下文，同时 `incvar` 把 render counter 从 0 改为 1；随后另一个 plugin action 用 `tavo.get` 把同一 token 和 `after=1` 写回 composer。五个 token 均确认不在静态 sources、用户 prompt 或发送前消息中，五个 counter delta 均为 `+1`。这只验证 chat scope 和测试所用 helper，不证明 global、真实 TavoJS message scope 或宏变量互操作。

2026-07-11 又通过短时请求捕捉网关补上 wire proof。Tavo 正常发送产生的最终 OpenAI-compatible body 为 `system -> user -> assistant -> user`；测试角色 `description` 中的 set/get/default、条件、循环、inc 和 EJS 输出宏都已在 `system` 文本中展开，原始 `<%`、`{{char}}`、`{{user}}` 为零残留，EJS 输出的角色/用户宏变成实际 character/persona 名称。对应模型流式完成并持久回复 `ACK`。原始证据在 `artifacts/tavo-validation/20260711-ejs-request-capture-v1/`，请求 id `2b937cc103c34a13`。这把“模型看见 marker”提升为该角色描述路径的真实 role/order/render 证据，但不代证其它字段的 wire 位置。

2026-07-11 case 35 进一步在 chat A/B 中执行 `write A -> write B -> read B -> read A -> read B`，每次 plugin action 都读回各自 chat-scoped marker，证明测试路径中的 chat scope 随线程隔离。最后尝试切回 A 时，`tavo_current_chat_set` 返回 success/diff，但 immediate readback 与随后 9 次、约 5 秒轮询仍保持 B。这个结论分两层：chat-scope A/B direct runtime effect 通过；MCP current-chat switch 出现 success-without-effect regression。该 case 没有发送模型请求。

## Input Box: Clear, Set, Append, Send

宏中的 `{{input}}` 是生成上下文里的最近可见用户消息，不是当前 composer 文本。EJS 的 `lastUserMessage`/`lastCharMessage` 也是提示词上下文常量，不是输入框 API。

| 通道 | get | set | append | clear | send |
| --- | --- | --- | --- | --- | --- |
| 宏 | `missing` | `missing` | `missing` | `missing` | `missing` |
| EJS | `missing` | `missing` | `missing` | `missing` | `missing` |
| TavoJS | `official-only` | `verified` | `verified` | `official-only` | `official-only` |
| TPG | `official-only` | `verified`，native input actions | `verified`，native input actions | `official-only` | `official-only` |
| MCP | `verified` | `verified` | `verified (effect)` | `verified (effect)` | `verified`，normal UI flow |

当前 MCP surface 的五个工具是 `tavo_input_get/set/append/clear/send`，并明确：

- 绑定当前活动聊天页；没有活动聊天页时，失败不能直接解释为权限失败；
- `send` 走正常 UI chat flow；空白发送会被拒绝；
- 本轮只读 `tavo_input_get` 成功返回活动 chat id 与空文本，证明当前读取入口可用；
- registry 的 `mcp-input-message-readback` 记录了 set/get/send 与消息 readback；v23 另以 `tavo_input_clear` 后立即 `input_get` 的空字符串 readback 证明 clear effect。2026-07-11 case 32 又执行 clear -> read empty -> set prefix -> append suffix -> exact full readback -> normal send，形成 append 的直接 effect proof 和完整持久 exchange。

v23 的 AR/TavoJS message panels 分别执行三个 `tavo.input.set` 和两个 `tavo.input.append` action；native TPG inputActions 也执行三个 set 和两个 append。每次 action 后都由 MCP `input_get` 读回唯一 marker，再通过正常 input send 形成持久 user/assistant ID。这个证据不能反推 TavoJS/TPG 的 `clear` 或 `send`。

当前 MCP `input_append` 会在既有 composer 与追加片段之间插入一个 ASCII space。case 32 为得到精确目标文本，必须在原目标字符串已有的空格处分片，而不是把空格同时放进 suffix。作者脚本应在目标边界显式比较 `input_get`，不要假定 append 是无分隔符字符串拼接。

输入框出现文本只证明 set/append 的 composer side effect。只有 send 后按稳定 message id 或当前聊天消息列表回读，才能证明消息已持久进入聊天；即使进入聊天，也不自动证明模型生成成功。

## Message CRUD

| 通道 | Create | Read | Update | Delete |
| --- | --- | --- | --- | --- |
| 宏 | `missing` | 仅最近消息值为 `official-only`，不是对象读取 | `missing` | `missing` |
| EJS | 仅输出模板文本，`missing` | 仅内置 last-message 常量为 `official-only` | `missing` | `missing` |
| TavoJS | `tavo.message.append` 为 `official-only` | `find/get/current/count` 为 `official-only` | `update` 为 `official-only` | `delete` 为 `official-only` |
| TPG | scoped facade 的 `append` 为 `official-only` | `find/get/current/count` 为 `official-only` | `update` 为 `official-only` | `delete` 为 `official-only` |
| MCP | `append` 为 `verified (effect)`；`insert` 仅 `verified (surface)` | `find/get/count` 为 `verified (surface+read)` | `update` 为 `verified (effect)` | `delete` 为 `dry-run-pass`、actual effect `missing` |

边界细节：

- TavoJS 当前公开 API 没有文档化 `insert`；MCP 独有 `tavo_message_insert`，不能把它反推给 TavoJS 或 TPG。
- TavoJS `message.current()` 指执行脚本所在气泡。TPG 只有挂在 `/messages` 的 HTML fragment 才有 current message；`/chat` fragment、input action 和 sidebar action 中应为 `null`。
- MCP message tools 显式接收 `chatId`。读取和目标操作优先用稳定 `id`；0-based `index` 会因插入/删除漂移。
- 早期只读 `tavo_message_find` 与 registry 的 input send/readback 只证明读取和正常发送路径。v23 另在五个独立聊天中直接 `tavo_message_append` 一个 `MCP_ORIGINAL_*` assistant message，按 stable ID 读回，再用 `tavo_message_update` 改为 `MCP_UPDATED_*` 并再次读回；随后五个真实模型回复都包含 updated marker 且不含 original marker。因此 append/read/update 及其进入后续模型上下文为 `verified`，insert/delete effect 仍未验证。
- 2026-07-11 case 33 再次 dry-run + actual append，按 stable id readback，再 dry-run + actual update 并读回；delete 只 dry-run，随后把同一消息更新为明确的 retained tombstone marker并读回。直接运行时步骤通过。后续真实模型看到了 retained marker，但可见回复首行没有遵守 nonce 格式，所以 semantic/format 层失败；不能把它改写成 MCP message CRUD 失败。
- message append 成功不证明 UI 已正确渲染；UI 可见也不证明 reasoning、hidden、characterId 等字段逐项保真。

## TPG Actions, Sidebar, And HTML

TPG 不是第五套脚本语言。它把 manifest、native contribution、HTML 文件和 action registration script 打成 `.tpg`，实际行为通过安装后的 scoped TavoJS facade 执行。

| 原子结论 | Verdict | Evidence boundary |
| --- | --- | --- |
| `.tpg` package、manifest validation、install/readback | `verified (0.92 effect)` for root/wrapper/development zip | 0.92 positive import roundtrips；其它负例不能由正例代证 |
| `inputActions` 注册到 runtime contributions | `verified (0.91 effect)`；0.92 package/runtime registration used by isolated fixtures | 0.92 matrix does not replace the older visual menu-click proof |
| input action handler 真机点击并 set/append 输入框 | `verified (0.91 effect)` | 旧 registry artifact；v23 五个 native inputActions、composer readback 和模型调用 |
| `sidebar` declaration 和 handler API | `official-only` | fresh docs 支持；本轮 current contributions 为 `sidebar: []`，无现有点击证据 |
| `htmlFragments` 注册与 normalized mount | `verified (0.91 effect)` | 0.91 MCP 读到 `/chat/body/end` fragment |
| HTML fragment 在真机可见 | `verified (0.91 effect)` | 0.91 screenshot/UI XML 可见 TPG/plugin panel markers |
| HTML fragment 内按钮点击 | `missing` | 现有 after-click marker 属于 AR message panel，不是 TPG fragment panel |
| 插件经 facade 完成世界书 create/read/update/tombstone | `verified (0.91 effect)` | case 34 action results + MCP stable-id/marker readback；actual delete 未执行 |
| 根 `entry.js`、旧入口兼容与双入口优先级 | `verified (0.92 effect)` | F01-F03 真机矩阵 |
| 无 UI contribution 的 entry 与 `plugin.config.get/all` | `verified (0.92 effect)` | F01/F04；通知别名可靠性另为 mixed |
| input Hooks | `verified (0.92 effect)` within tested sources/faults | F06 三源、rewrite/cancel/fail-open/acceptance timing；attachment N/A |
| generation Hooks | `mixed (0.92 effect)` | F07/F08 原子通过；F09 `othersContinuation` 回归且辅助排除 blocked |
| plugin TTS | `mixed (0.92 integration)` | configured character/queue request pass；persona blocked；听感 manual |

Manifest 和运行时边界：

- 新插件的 `contributes.inputActions` 与 `contributes.sidebar` 必须配 `entry`，通常指向根 `entry.js`。旧 `scripts.actions` 仅为兼容别名；两者同时存在时 `entry` 优先。hook-only 插件可以只有 `entry` 而没有 UI contribution。
- `contributes.htmlFragments` 是本地 UTF-8 HTML，挂载到 documented chat/message slots；它不是远程 URL，也不自动获得包内其它文件的 WebView 静态资源服务。
- input/sidebar handler 与 fragments 在 Advanced Rendering WebView runtime 中运行。AR 关闭时，native action 可以仍然可见，但点击不会执行 handler，并会引导用户开启 AR。
- fragment script 属于已安装 plugin runtime，不受“聊天内容 JavaScript 执行模式”控制；该模式只控制角色卡、模型输出和其它消息气泡脚本。
- 插件入口/fragment 应使用未限定的词法 `tavo` 作为 scoped facade，不要把 `window.tavo` 或 `globalThis.tavo` 当作插件作用域契约。
- MCP contribution readback 只能证明 manifest 被解析和 runtime entry 被注册，不能证明 native 菜单布局、点击、fragment 像素布局或遮挡。

0.92 新入口边界：

- `tavo.plugin.config.get/all` 同步、只读，合并 schema 默认值与用户覆盖；`all()` 返回浅拷贝，修改不会保存。
- chat/message 通知只观察状态；message 具体事件先于 `message:changed`，流式中间状态不是 `message:added`。
- `input:beforeSend/afterSend` 只在 entry 注册，覆盖 UI/TavoJS/MCP 三源；错误/超时/无效文本按 handler fail-open，显式 cancel 才停止后续 handler。
- generation prepare/success/error/cancelled 只在 entry 注册，HTML fragment 不能注册。0.92 真机已逐项观察到 prepare/success 的改写与 fail-open、脱敏 error、cancel 的 `partial=true/false` 保存差异和单终态互斥；完整 source 白名单仍是 mixed，因为 `othersContinuation` 受控路径未触发 Hook，辅助生成排除项也未补证。
- plugin `tavo.tts.play` 必须显式选择 character/persona；`stop` 控制共享 current-chat 队列。声音身份必须人工听感确认。

0.92 真机补充边界：

- `chat:opened` 字段、specific message event 在 `message:changed` 前、流式只产生一次持久 assistant add、handler 隔离均通过；`chat:changed` 兼容 handler 未收到受控 `chat:updated`，整组保持 mixed。
- `generation:prepare` 的改写只进入瞬时 provider 请求，持久 user message 保持原文；`generation:success` 在保存前改写，空/异常/超时 fail-open。`reply`、`regeneration`、`continuation` 被观察到，但 `othersContinuation` 受控路径无 Hook/消息。
- `tavo.input.send()` 的成功/失败对象与接受阶段返回通过；`busy` 未观察到，不能写成三种 reason 全覆盖。
- Backup B 真机 roundtrip 恢复了插件 id/version/config/enabled/runtime contribution。它证明备份中的插件状态，不证明所有数据类型或降级恢复。

v23 的 plugin-action-panel family 仍不能替 HTML fragment 按钮补证。实际 marker 是 `TPG_<run>_*`，来自 `actions.js` 注册的 native `inputActions`；`ui/panel.html` 内按钮生成的是不同的 `TPG_PANEL_<run>_*`。五个前者通过不能改写成一个后者通过。

## Permissions And Confirmation

### Macro And EJS

- fresh docs 没有为宏/EJS 变量写入描述逐次权限弹窗。它们在提示词渲染过程中执行，不能当作一次性用户点击事务。
- EJS 默认开启，可在兼容性设置中关闭。错误标签会让整个字段回退到原始未渲染文本；“原文仍在”不是部分执行成功。
- 宏/EJS 没有 TPG manifest permissions，也没有 MCP access scope。

### TavoJS

- message content 中的 TavoJS 依赖相应 AR/JavaScript 设置。现有 registry 记录 JavaScript `自动` 模式出现风险提示并需明确确认。
- fresh TavoJS docs 明确写到 `tavo.lorebook.import` 操作前弹用户确认。2026-07-11 case 34 在当前设备实际观察到 create 弹“是否允许创建世界书”，update 和 tombstone update 弹“是否允许修改世界书”；runner 只在动词与本次 runId 都匹配时确认。actual delete 没有运行，因此删除弹窗仍不能类推。
- current runtime guide 的通用规则是破坏性、昂贵或外部动作可能受 Tavo confirmation settings 约束；每一个具体 API 是否弹窗仍以该 API 文档和真机为准。

### TPG

- fresh docs 要求安装时阅读风险提示，只安装可信来源。插件可包含脚本和 UI fragment，启用/禁用不等于代码经过安全审计。
- `manifest.permissions` 可声明 `input/message/generate/variable/file/network/tts` 等能力。0.92 MCP `tavo://docs/plugins` 明确说明它们是作者意图声明，尚不是运行时强制 permission gate。该结论为 `runtime-only` contract，不等于已经做过绕过测试。
- 权限声明过少不保证调用会被拦截；声明完整也不代表用户已授权每一次持久写入。

### MCP

- MCP Server 默认关闭；用户选择 access scope 后启用，并以 bearer token 鉴权。当前官方 docs 明确 `403` 表示访问范围不允许连接或操作。
- 拿到 endpoint 和 token 的客户端可调用已暴露工具。token 不能进入公开聊天、截图、reference、日志或 issue。
- current write schemas 提供 `dryRun`、`expectedRevision`、`clientRequestId`。安全顺序是 read/search -> 最小 patch -> dry-run diff -> actual write -> stable-id readback。
- current surface 没有证明每次 MCP write 都会出现手机端交互确认框。因此“已通过 bearer/access scope”不能当作用户对每次 destructive write 的确认。
- 删除、覆盖、重置、卸载等 destructive operation 必须有明确操作意图；成功响应之后仍需 readback 证明最终状态。

## What The AR Screenshot Proves

当前工作树内最强的直接 AR 证据可用 v23 的首个 TavoJS panel case 复核：

- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-calls/tavojs-variable/01-attempt-1/ui-after-action/screen.png`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-calls/tavojs-variable/01-attempt-1/ui-after-action/ui.xml`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-calls/tavojs-variable/01-attempt-1/ui-after-action/package.txt`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-calls/tavojs-variable/01-attempt-1/ui-action/ui-action-marker-result.json`
- `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-calls/tavojs-variable/01-attempt-1/ui-action/input-readback-action-1-poll-1.json`
- 对应冻结源：`artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/semantic-sources/advanced-rendering-js01a1.html`

这些文件共同证明：

- `package.txt` 为 Tavo `0.91.0`；
- UI tree 中出现 `android.webkit.WebView`、`AR_PANEL_SV20260710203242JS01A1` 和五个 AR 按钮；
- screenshot 中 panel、按钮、`state=clicked` 状态和 composer 文本同时真实可见；
- 点击“AR 观察场景”后，状态变为 `AR_SV20260710203242JS01A1_OBSERVE state=clicked`；
- MCP `input_get` 同时读回对应长文本；冻结源把该行为绑定到 chat-scope `tavo.set/get` 与 `tavo.input.set`；
- 对应 `result.json` 还记录后续正常发送产生唯一 user/assistant message ID 和通过的真实模型回复。

这些文件不证明：

- TPG fragment 内按钮被点击；
- native plugin input action、HTML fragment button 或 sidebar action 的点击效果；
- 这个单一 observe case 中的 TavoJS `input.clear/append/send`；
- message append/update/delete；
- 世界书 create/update/delete；
- global/message 变量跨重启持久；
- 导出/导入 roundtrip；
- AR 在不同屏幕尺寸、滚动位置或聊天切换后仍无重叠。

因此，AR/CSS/HTML/JS 的视觉结论必须有 screenshot；MCP 或 UIAutomator 只能补结构和状态。反过来，screenshot 也不能替代 persistent readback。

v23 另外保留了十个计数内 AR/TavoJS panel case 的 before/after screenshot、UI XML、clicked status 和 composer readback，位于 `model-calls/tavojs-variable/` 与 `model-calls/advanced-rendering/`。它们证明当前 1200x2670 真机 viewport 中测试 panel 可见、按钮可点击、chat `set/get` 返回 `clicked`，且 input set/append side effect 可读。它们没有做 app restart、导出/导入、sanitization matrix、不同屏幕尺寸或 fixed/sticky/z-index/overflow A/B，不能升级这些边界。

## Non-Substitution Rules For Persistent CRUD

以下证明链不能互相替代：

1. 官方文档或 runtime docs 只证明 contract 被声明，不证明当前设备执行成功。
2. tool/API surface 只证明入口存在，不证明权限、确认、payload、effect 或持久性。
3. local schema、manifest validation、package 成功或 `dryRun` 只证明形状/预览可接受，不证明真实写入。
4. actual call 返回 success 只证明调用被接受；必须按 stable id/revision readback。
5. readback 证明当前存储状态，不证明 AR 视觉、native 菜单、点击目标或 CSS 布局。
6. screenshot 证明当时像素与可见 side effect，不证明数据库对象、未知字段、重启持久或导出保真。
7. input set/append 证明 composer 变化，不证明 send；send 证明消息路径，不证明直接 message CRUD；消息落库不证明模型生成。
8. worldbook import 证明对象创建，不证明 update/delete，不证明 entry 逐字段保真，也不证明关键词触发语义。
9. plugin contribution readback 证明注册，不证明 handler 启动、异步完成、fragment 可见或 sidebar 可用。
10. chat variable set/get 不证明 global/message scope；EJS 的 `message` 兼容名也不能替 TavoJS message scope。
11. MCP 工具成功不能证明同名 TavoJS API；TPG handler 成功不能证明角色卡气泡中的 TavoJS 生命周期。
12. 每个 C/R/U/D 动词分别取证。Create 不能代 Update，Read 不能代 Delete，Delete 的成功响应不能代删除后的 not-found/readback。

## Evidence Ledger

### Fresh Official Docs

- [宏（Macros）](https://docs.tavoai.dev/cn/guides/supported-macros/)
- [EJS 模板](https://docs.tavoai.dev/cn/guides/ejs-template/)
- [TavoJS API](https://docs.tavoai.dev/cn/guides/javascript-api/)
- [高级前端渲染](https://docs.tavoai.dev/cn/guides/advanced-rendering/)
- [世界书](https://docs.tavoai.dev/cn/guides/lore-book/)
- [插件使用](https://docs.tavoai.dev/cn/guides/plugins/)
- [插件开发](https://docs.tavoai.dev/cn/guides/plugin-development/)
- [MCP Server](https://docs.tavoai.dev/cn/guides/mcp-server/)

Durable current snapshot: `assets/official-docs/text-20260716/` and `assets/official-docs/official_manifest-20260716.json`. The 20260710 snapshot remains the prior-version comparison.

### Current MCP Surface

- full redacted 0.92 surface: `assets/schemas/mcp-surface-0.92.0-20260716.json`
- compact 0.92 index: `assets/schemas/mcp-surface-index-0.92.0-20260716.json`
- current gate: `assets/evidence/0.92.0/20260716-gate.json`
- current runtime resources used here: `tavo://capabilities`, `tavo://docs/macros`, `tavo://docs/tavojs`, `tavo://docs/plugins`, `tavo://docs/tools`, `tavo://docs/write-safety`, `tavo://runtime`
- 0.92 current gate 只调用 `tavo_status` 并读取 runtime/docs/schema；没有执行 lorebook/message/input/plugin semantic writes。
- retained 0.91 read-only/effect evidence：lorebook search/get、message find、input get、plugin runtime contributions 与 `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/`；本页只提升其逐 case、逐版本实际执行并 readback 的原子行为。

### Existing Device And Registry Evidence

- directly present AR screenshot/UI/package evidence: `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/model-calls/tavojs-variable/01-attempt-1/ui-after-action/`
- directly present earlier visual baseline: `artifacts/tavo-validation/20260710-084738-semantic-model-kpi-v2/`
- terminal semantic epoch: `artifacts/tavo-validation/20260710-203300-semantic-model-kpi-v23/`
- cross-feature mixed coverage index: `artifacts/tavo-validation/20260711-cross-feature-aggregate-v1/`
- project verdict registry: `assets/evidence/registry.json`
- related interpretation rules: `references/00-source-of-truth.md`, `references/14-evidence-registry.md`, `references/19-debugging-pitfalls.md`

Registry rows whose listed artifact directory is absent from the current working tree remain useful version-scoped project records, but they cannot visually or byte-for-byte prove anything beyond their exact recorded claim. Present artifacts, current runtime reads and fresh official docs take precedence when narrowing a boundary.

Project-specific external MCP client/plugin implementations are intentionally outside this Tavo Skill. This page covers only Tavo's native MCP boundary and the separation between MCP, TPG, TavoJS, EJS, and Advanced Rendering.
