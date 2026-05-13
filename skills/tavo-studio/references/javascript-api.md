# Tavo JavaScript API 总结

## 1. 定位与版本信息

Tavo JavaScript API 是面向玩家和创作者的脚本接口，用来在开启 JavaScript 支持后，操作 Tavo 暴露给脚本层的一部分数据、聊天流程和界面行为。

文档标注信息：

- 文档页发布时间：2026-04-23
- 标注版本起点：`Since v0.75.0`
- 文档明确表示 API 仍处于早期 beta，持续更新中

文档还特别提到一个推荐玩法：

- 把 API 文档交给 AI
- 让 AI 生成与 Tavo 深度结合的脚本

也就是官方本身鼓励”Vibe Coding”式的 AI 协作开发。

### 1.1 命名空间说明（重要）

Tavo 的 JS 运行时有两个命名空间共存，各有不同用途：

| 命名空间 | 用途 | 性质 |
|----------|------|------|
| `window.tav` | **内部通道**，用于 Flutter ↔ WebView 通信 | 底层消息传递，不应直接调用 |
| `window.tavo` | **公开 API**，给用户脚本使用 | 文档化但仍处早期 beta，所有用户脚本应优先使用这个 |

关键事实：

- `window.tavo` 的方法最终通过 `window.tav.callParent` 和 `window.tav.callParentWithResult` 与 Flutter 原生层通信
- 脚本中**不要直接调用** `window.tav` 的方法，那是内部实现，可能随版本变化
- ST 兼容层在 `window.tav.compat.st` 下，通过 `window.tav.compat.st.triggerSlash` 提供

不要把 JS API 写成“能控制 Tavo 所有功能”。以包体 `sandbox.js` 暴露的 `window.tavo.*` 方法为边界；端点管理、TTS 端点管理、备份恢复、存储空间清理等原生设置没有公开 `window.tavo` 绑定。

### 1.2 内部通信机制（供理解，非调用接口）

WebView 中的 JS 与 Tavo Flutter 原生层通过 `postMessage` 通信：

- **单向调用**：`window.tav.callParent(method, params)` → 无返回值
- **双向调用**：`window.tav.callParentWithResult(method, params, options)` → 返回 Promise
  - 默认超时：**60 秒**（60000ms）
  - 可通过 `options.timeout` 自定义，设为 `0` 表示无限等待（如 `tavo.generate`）
  - 返回格式：`{requestId, method, params}` 发出，`{requestId, response, error}` 收回
- **变量存取**：`window.tav._getVariable(name, scope)` / `window.tav._setVariable(name, value, scope)` / `window.tav._unsetVariable(name, scope)`

### 1.3 沙箱与安全限制

WebView 运行在沙箱中，`sandbox.js` 做了以下防护：

- `window.parent`、`window.top`、`window.frameElement`、`window.opener` 全部重定向为 `window` 或 `null`
- `window.frames` 被重定义为返回 `window` 自身的 getter
- 剪贴板 API：优先用 `navigator.clipboard.writeText`，失败后降级到 `execCommand('copy')`，再失败则通过 `window.tav.callParent('clipboard_writeText', [text])` 交给原生层处理
- 全局错误通过 `window.addEventListener('error', ...)` 捕获并上报到 Flutter 层
- `console.log/warn/error` 全部重定向到 `window.tav.console`，最终回到 Flutter 的日志系统

## 2. 入门前要先记住的总原则

### 2.1 除变量操作外，大多数 API 都是异步

文档明确说明：

- 除变量 API 外，几乎所有接口都需要 `await`
- 如果在函数内使用 `await`，函数本身要写成 `async`

这意味着后续写任何 Tavo 脚本时，默认心智模型应该是：

- `tavo.get / set / unset` 可以直接用
- 其他接口大多写成 `await tavo.xxx.yyy(...)`

### 2.2 可以先导入官方辅助角色卡

官方提供了一个帮助查看 API 用法的角色卡 URL：

- `https://docs.tavoai.dev/static/images/tavojs-guide-0_8-zh.png`

这对后续让 AI 直接在 Tavo 里帮你写脚本非常有帮助。

## 3. 变量 API

变量 API 是最基础、也最常用的一组接口，用于跨页面刷新保存状态数据。

### 3.1 获取变量

- `tavo.get(name[, scope])`

文档示例：

- `tavo.get('age')`
- `tavo.get('bestScore', 'global')`

### 3.2 设置变量

- `tavo.set(name, value[, scope])`

支持保存：

- 数字
- 字符串
- 对象

### 3.3 删除变量

- `tavo.unset(name[, scope])`

### 3.4 变量路径

支持路径访问与删除，例如：

- `tavo.get('status.hp')`
- `tavo.unset('status.hp')`

这意味着可以把复杂状态存成对象，而不是只存平铺变量。

### 3.5 官方文档里的作用域

作用域章节明确列出的只有两个：

- `chat`：当前聊天作用域，**默认值**，可随聊天导出
- `global`：全局作用域，跨对话保存

**重要**：经源码（sandbox.js）验证，`tavo.get/set/unset` 的 scope 参数逻辑为：若传入的值不是 `”global”`，则默认使用 `”chat”`。`”global”` 需显式传入。源码中**不存在** `character` 作用域的处理逻辑，传入 `”character”` 会被当作 `”chat”` 处理。但官网文档示例中曾出现 `tavo.get('lover', 'character')`，与源码实现冲突——以源码为准，仅 `chat` 和 `global` 两个作用域生效。

### 3.6 与宏系统的关系

变量可以通过宏读回提示词中：

- `{{getvar::<name>}}`
- `{{getglobalvar::<name>}}`

所以一个常见组合是：

- JS API 负责维护状态
- 宏负责把状态注入到提示词或显示中

## 4. 聊天 API

所有聊天接口都在 `tavo.chat.<method>(...)` 下。

### 4.1 获取当前聊天

- `await tavo.chat.current()`
- 无聊天时返回 `null`

常见字段：

- `id`
- `name`
- `characters`
- `persona`
- `lorebooks`

### 4.2 更新当前聊天

- `await tavo.chat.update(chat)`

文档明确可更新字段：

- `name`
- `characters`，会直接替换当前聊天角色列表
- `persona`

限制：

- 只支持更新当前聊天
- 不支持按 ID 远程修改其他会话

## 5. 消息 API

所有消息接口都在 `tavo.message.<method>(...)` 下（官方文档支持，sandbox.js 中也可验证）。

支持的方法：

- `await tavo.message.find(indexRange[, filter])` — 按楼层范围查找消息
- `await tavo.message.get(messageId)` — 获取单条消息（传数字 ID）
- `await tavo.message.current()` — 获取当前消息（依赖 `tav.messageId`）
- `await tavo.message.count()` — 获取消息总数
- `await tavo.message.append(message)` — 追加消息
- `await tavo.message.update(message)` — 更新消息
- `await tavo.message.delete(messageId)` — 按消息 ID 删除消息（官方文档明确签名只接受 ID，需先取 `.id`；与 `character.delete` / `persona.delete` / `preset.delete` 同时接受 ID 或对象的行为**不同**）

### 5.1 消息对象常见字段

- `id`
- `role` — `"user"` / `"assistant"` / `"system"`（`tavo.message.append()` 的 role 只接受 `assistant | user`；`system` 出现在查找/返回的消息中，不建议假设 append 可创建 system 消息）
- `content` — 消息正文
- `characterId` — 所属角色 ID
- `hidden` — 是否隐藏

## 6. 角色 API

所有角色接口都在 `tavo.character.<method>(...)` 下。

支持的方法：

- `all()`
- `get(characterId)`
- `find(name)`
- `create(character)`
- `update(character)`
- `import(character)` — 导入角色卡。接受完整 CCv3 对象或裸 `data` 对象。包体字符串确认存在 `character_edit_lorebook_import_succeed_hint`、`character_edit_regex_import_succeed_hint` 与 `regex_scripts`，说明原生角色导入流程会处理卡内世界书/正则扩展；这属于 `character.import()` 原生导入链路，不等同于 `lorebook.create/update()` 或 `regex.create/update()` 的字段转换
- `delete(characterId | character)`

### 6.1 创建/更新的必填项

- 创建：`name`、`firstMes`（也兼容 CCv3 的 `first_mes`）
- 更新：`id`、`name`、`firstMes`（也兼容 CCv3 的 `first_mes`）

### 6.2 角色对象的重要字段

文档列出的常见字段（JS API 主用 camelCase，同时兼容 CCv3 snake_case）：

- `id`、`avatar`、`name`、`nickname`
- `description` / `firstMes` / `mesExample`
- `personality` / `scenario`
- `creatorNotes` / `systemPrompt` / `postHistoryInstructions`
- `alternateGreetings`（数组）
- `tags`（数组）/ `creator`
- `characterVersion` / `groupOnlyGreetings`
- `creationDate` / `modificationDate`

> CCv3 兼容：以上 camelCase 字段均有对应 snake_case 别名（如 `firstMes` ↔ `first_mes`），详见 §18 字段映射表。

特别要记住：

- `nickname` 会替代 `name` 作为 `{{char}}` 的输出
- 创建、更新、删除角色时会弹出确认框，用户取消则操作无效

## 7. 用户身份 API

所有接口都在 `tavo.persona.<method>(...)` 下。

支持的方法：

- `all()`
- `get(personaId)`
- `find(name)`
- `create(persona)`
- `update(persona)`
- `delete(personaId | persona)`

注意：Persona API **没有** `import()` 方法（与角色卡不同），用户身份只能手动创建。

### 7.1 创建/更新的必填项

- 创建：`name`、`description`
- 更新：`id`、`name`、`description`

### 7.2 用户身份对象重要字段

- `id`
- `name`
- `description`
- `avatar`
- `active`
- `sortIndex`

这里的 `active` 用来表示是否为默认用户身份。

## 8. 预设 API

所有接口都在 `tavo.preset.<method>(...)` 下。

支持的方法：

- `all()`
- `get(presetId)`
- `find(name)`
- `create(preset)`
- `update(preset)`
- `import(preset)` — 从外部导入预设
- `delete(presetId | preset)`

### 8.1 创建与更新行为

- 创建时 `name` 必填
- `basicPrompts` 和 `entries` 缺失部分会自动补默认值
- 更新时 `id` 必填
- `entries` 在更新时会直接覆盖旧数组，所以推荐流程是：
- 先 `get`
- 修改局部字段
- 再 `update`

### 8.2 预设对象结构

主要字段：

- `id`
- `name`
- `basicPrompts`
- `entries`

### 8.3 BasicPrompts 的职责

`basicPrompts` 是系统级模板集合，文档列出这些关键字段：

- `persona`
- `description`
- `personality`
- `scenario`
- `exampleMessageStart`
- `chatStart`
- `groupChatStart`
- `groupNudge`
- `continueNudge`
- `impersonation`
- `lorebook`

可以把它理解成“提示词包装模板层”。

### 8.4 PresetEntry 条目结构

每个条目主要字段：

- `identifier`
- `name`
- `content`
- `enabled`
- `active`
- `type`
- `role`
- `injectionPosition`
- `injectionDepth`

`type` 有三种：

- `builtin`
- `marker`
- `custom`

### 8.5 内置 identifier 列表

文档列出的内置标识符包括：

- `main`
- `worldInfoBefore`
- `personaDescription`
- `charDescription`
- `charPersonality`
- `scenario`
- `enhanceDefinitions`
- `nsfw`
- `worldInfoAfter`
- `dialogueExamples`
- `chatHistory`
- `jailbreak`

这些对应 Tavo 内建的固定提示位和插入点。

## 9. 世界书 API

所有接口都在 `tavo.lorebook.<method>(...)` 下。

支持的方法：

- `all()`
- `get(lorebookId)`
- `find(name)`
- `create(lorebook)`
- `update(lorebook)`
- `import(lorebook)` — 从外部导入世界书
- `delete(lorebookId | lorebook)`

### 9.1 世界书对象

主要字段：

- `id`
- `name`
- `entries`

### 9.2 LorebookEntry 条目字段

文档列出的重要字段很多，这是后续自动化时必须记住的重点：

- `identifier`
- `name`
- `content`
- `enabled`
- `strategy`
- `keywords`
- `secondaryKeywords`
- `secondaryKeywordStrategy`
- `scanDepth`
- `caseSensitive`
- `matchWholeWord`
- `injectionPosition`
- `injectionDepth`
- `injectionRole`
- `probability`
- `sticky`
- `cooldown`
- `delay`

这说明 JS API 层面的世界书能力非常强，不只是简单的“关键词 + 文本”。

你可以控制：

- 主关键词与次级关键词逻辑
- 注入位置
- 激活概率
- 持续轮数
- 冷却
- 延迟

## 10. 正则 API

所有接口都在 `tavo.regex.<method>(...)` 下。

支持的方法：

- `all()`
- `get(regexId)`
- `find(name)`
- `create(regex)`
- `update(regex)`
- `import(regex)` — 从外部导入正则组
- `delete(regexId | regex)`

### 10.1 正则对象

主要字段：

- `id`
- `name`
- `entries`

### 10.2 RegexEntry 条目字段

文档列出的字段包括：

- `name`
- `findRegex`
- `replaceString`
- `trimStrings`
- `placements`
- `timing`
- `substitution`
- `minDepth`
- `maxDepth`
- `enabled`

其中：

- `placements` 可选 `user` / `char` / `reasoning` / `lorebook`
- `timing` 可选 `display` / `send` / `sendAndDisplay` / `receive` / `editAndReceive`
- `substitution` 可选 `none` / `raw` / `escaped`

## 11. 长记忆 API

所有接口都在 `tavo.memory.<method>(...)` 下。

支持的方法：

- `current()`
- `update(memory)`

记忆对象字段：

- `id`
- `enabled`
- `memories`

这是一个很精简但很实用的接口，适合用脚本维护长期记忆内容。

## 12. 生成请求 API

入口：

- `await tavo.generate(prompt, options)`

返回值：

- 完整字符串
- 不是流式分片

### 12.1 options 支持字段

- `context`：是否带当前上下文
- `preset`：可传预设 ID 或 `{ id }`
- `settings`：覆盖本次生成的模型参数

文档示例里的 `settings` 包括：

- `temperature`
- `topP`
- `maxCompletionTokens`

### 12.2 注意事项

- 这是一次性请求，不是流式输出
- 会使用当前聊天绑定的模型端点
- 如果当前聊天无可用端点，返回 `null`

### 12.3 官方示例价值

文档提供了一个非常实用的 demo：

- 调 `tavo.generate(...)` 生成角色卡 JSON
- 用 `tavo.utils.export(...)` 下载 JSON
- 再用 `tavo.character.create(...)` 直接创建角色

这说明 API 可以拼出“生成 -> 自行解析校验 -> 导出或请求创建”的流程。不要写成自动可靠落库：生成结果需要脚本自己校验 JSON，`character.create()` 仍可能弹确认框，用户取消或端点失败都要处理。

## 13. 输入框 API

所有接口都在 `tavo.input.<method>(...)` 下。

支持的方法：

- `await tavo.input.get()`
- `tavo.input.set(text)`
- `tavo.input.append(text)`
- `tavo.input.clear()`
- `tavo.input.send()`

适合做：

- 自动填充提示词
- 预制命令注入
- 一键发送
- UI 面板与输入框联动

## 14. 通用工具 API

所有接口都在 `tavo.utils.<method>(...)` 下。

### 14.1 toast

- `tavo.utils.toast(text)`
- 显示轻量提示

### 14.2 openUrl

- `tavo.utils.openUrl(url)`
- 外部浏览器打开链接

### 14.3 select

- `await tavo.utils.select(options, title?, defaultValue?)`
- 弹出选择对话框
- `options` 支持三种格式：
  - `string[]` — 简单字符串列表
  - `{ value, label }[]` — 带标签的选项
  - `{ value, label, description?, subtitle? }[]` — 完整选项对象
- 返回所选 `value`，用户取消返回 `null`（官方文档签名；sandbox.js 中 `tavo.utils.select=async(e,t,a)` 确认有三个参数）

### 14.4 export

- `tavo.utils.export(name, data)`
- 导出文件并触发系统分享/保存
- `data` 推荐传 Base64，也支持普通文本

## 15. 后续开发时最值得遵守的实践

### 15.1 默认采用“先读再改”模式

对于角色、用户身份、预设、世界书、正则这类对象，推荐流程都是：

1. `get`
2. 修改内存中的对象
3. `update`

因为文档多次强调某些数组字段会直接整体覆盖。

### 15.2 把变量、宏、正则和 AR 组合起来

一个非常典型的高可玩性方案是：

- 变量 API 存状态
- 宏把状态注入提示词
- 正则做输入/输出文本加工
- Advanced Rendering 负责展示层
- Input API 负责交互

### 15.3 对破坏性操作做好用户确认预期

角色、正则等操作在前端会弹确认框。后续写脚本时要假设：

- 用户可能取消
- 调用成功不等于用户一定确认

### 15.4 记住 API 仍在 beta

这意味着：

- 字段和行为未来可能继续扩展
- 做脚本时最好不要写死太多脆弱假设

### 15.5 不要默认能操作的原生功能

当前 `sandbox.js` 暴露的是变量、聊天、消息、角色、用户身份、预设、世界书、正则、长记忆、生成请求、输入框、工具函数和 App 版本信息。未观察到公开 JS API 的能力包括：

- Endpoint / Load Balancer 创建、切换、编辑
- TTS endpoint、角色语音绑定编辑
- 备份与恢复、存储空间清理
- App 全局设置、账号/订阅/遥测开关

如果脚本需求触及这些面，必须说明“当前 JS API 未暴露”，不要编造 `tavo.endpoint.*`、`tavo.tts.*`、`tavo.backup.*` 之类方法。

## 16. ST 兼容层 API

Tavo 通过 `window.tav.compat.st` 提供 SillyTavern 兼容接口：

### triggerSlash

- `window.tav.compat.st.triggerSlash(command)` — 触发 ST 风格的斜杠命令
- 别名：`window.triggerSlash(command)`（全局快捷方式）

示例：

```js
// 两者等效
window.triggerSlash('/send hp-check')
window.tav.compat.st.triggerSlash('/send hp-check')
```

## 17. App 信息 API

### version / versionNumber

- `await tavo.app.version()` — 返回当前 Tavo 版本号字符串（如 `"0.81.3"`）
- `await tavo.app.versionNumber()` — 返回版本号数值（如 `813`）

适合做版本兼容判断，或在脚本中显示当前版本信息。

## 18. ST ↔ Tavo 字段映射（character.create / update 时自动执行）

以下映射记录 sandbox.js `t()` 函数中 camelCase（公开 JS API 字段名）到 snake_case（CCv3/ST 兼容的内部序列化名）的转换方向。`tavo.character.create/update()` 同时接受两种格式；`tavo.character.get/find()` 返回的对象通过 getter 别名同时暴露两种格式。

> ⚠️ **`tavo.character.import()` 不走 `t()` 转换**——它吃完整 CCv3（snake_case）格式直接转给 Flutter 层。这与 `tavo.regex.import()`、`tavo.lorebook.import()` 行为一致：所有 `import()` 都是直通通道，不做 camelCase ↔ snake_case 转换；只有 `create()` / `update()` 路径会触发 `t()`。

| JS API 字段名 (camelCase) | 内部序列化名 (snake_case) |
|--------------------------|-------------------------|
| `firstMes` | `first_mes` |
| `mesExample` | `mes_example` |
| `creatorNotes` | `creator_notes` |
| `systemPrompt` | `system_prompt` |
| `postHistoryInstructions` | `post_history_instructions` |
| `alternateGreetings` | `alternate_greetings` |
| `characterBook` | `character_book` |
| `characterVersion` | `character_version` |
| `groupOnlyGreetings` | `group_only_greetings` |
| `creationDate` | `creation_date` |
| `modificationDate` | `modification_date` |

在 JS API 中创建/更新角色时，**camelCase 和下划线格式都接受**（如 `firstMes` 和 `first_mes` 均可）。sandbox.js 的 `t()` 函数会自动转换 camelCase → snake_case。官方文档推荐使用 camelCase。`tavo.character.get/find()` 返回的对象同时提供两种格式的访问（通过 getter 别名）。

## 19. 适合后续开发/自动化时记住的总图

- 变量：状态存储
- chat：当前会话控制
- message：消息查询、追加、更新、删除
- character：内容资源管理（含 `import`）
- persona：用户身份管理（**无** `import`，只能手动 `create/update`）
- preset：系统提示词模板管理（含 import）
- lorebook：条件触发知识注入（含 import）
- regex：文本中间层（含 import）
- memory：长期信息保存
- generate：独立 AI 请求
- input：输入框联动
- utils：提示、打开链接、导出
- app：版本信息
- compat.st：ST 斜杠命令兼容

## 19.1 sandbox.js 方法清单（APK 实证逐字摘录）

经 `grep -oE 'window\.tavo\.[a-z]+\.[a-z]+=' sandbox.js | sort -u` 实证，0.75 版 sandbox.js 暴露的全部 `window.tavo.*` 方法：

```
window.tavo.app.version=
window.tavo.app.versionNumber=

window.tavo.character.all=
window.tavo.character.create=
window.tavo.character.delete=
window.tavo.character.find=
window.tavo.character.get=
window.tavo.character.import=
window.tavo.character.update=

window.tavo.chat.current=
window.tavo.chat.update=

window.tavo.input.append=
window.tavo.input.clear=
window.tavo.input.get=
window.tavo.input.send=
window.tavo.input.set=

window.tavo.lorebook.all=
window.tavo.lorebook.create=
window.tavo.lorebook.delete=
window.tavo.lorebook.find=
window.tavo.lorebook.get=
window.tavo.lorebook.import=
window.tavo.lorebook.update=

window.tavo.memory.current=
window.tavo.memory.update=

window.tavo.message.append=
window.tavo.message.count=
window.tavo.message.current=
window.tavo.message.delete=
window.tavo.message.find=
window.tavo.message.get=
window.tavo.message.update=

window.tavo.persona.all=
window.tavo.persona.create=
window.tavo.persona.delete=
window.tavo.persona.find=
window.tavo.persona.get=
window.tavo.persona.update=
                          ← 无 .import

window.tavo.preset.all=
window.tavo.preset.create=
window.tavo.preset.delete=
window.tavo.preset.find=
window.tavo.preset.get=
window.tavo.preset.import=
window.tavo.preset.update=

window.tavo.regex.all=
window.tavo.regex.create=
window.tavo.regex.delete=
window.tavo.regex.find=
window.tavo.regex.get=
window.tavo.regex.import=
window.tavo.regex.update=

window.tavo.utils.export=
window.tavo.utils.openUrl=
window.tavo.utils.select=
window.tavo.utils.toast=
```

`tavo.generate(...)` 直接是顶层函数（不是 `tavo.generate.xxx` 形式），所以 grep 不到它。`tavo.set/get/update/unset` 同理是顶层变量 API。`window.tav.compat.st.triggerSlash` 在另一个命名空间下（详见 §16）。

## 20. 来源

- https://docs.tavoai.dev/guides/javascript-api/
- sandbox.js（APK 内 `/assets/dist/js/sandbox.js`）— API 实现的权威源码
