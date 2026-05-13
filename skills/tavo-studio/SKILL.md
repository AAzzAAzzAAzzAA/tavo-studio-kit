---
name: tavo-studio
description: Create, configure, explain, and validate Tavo / SillyTavern character cards, worldbooks, presets, macros, regex, long memory, JS API scripts, advanced rendering, PNG-embedded cards, and Tavo official capability boundaries. Tavo has broad ST/CCv3 import compatibility, but import/create/update/rendering paths differ; verify exact formats from references/source before producing importable files. Use when the user asks about Tavo, ST, 角色卡, character card, worldbook, 世界书, lorebook, 预设, 正则, 长记忆, 高级前端渲染, JavaScript API, 宏, PNG card, 图片发送, 备份, 存储空间, 聊天快捷键, 群聊快捷发言, TTS, 语音, 负载均衡, load balancer, 端点管理, API 端点, 官方能力, SDK, Dev Kit, testing, verification, or any related creation/configuration/scripting/troubleshooting task.
---

# Tavo Studio

Tavo 对 SillyTavern/CCv3 角色卡有较强导入兼容性，但不要把“能导入角色卡”扩展成“所有 ST 扩展字段、所有导入格式、普通浏览器行为都原样支持”。原生 import、JS API create/update、聊天气泡渲染是不同链路；涉及可导入文件或运行时行为时，必须按对应参考和包体证据确认。

本技能负责角色卡、世界书、正则、预设、宏、长记忆、JS API 和高级前端渲染等内容设计与文件产出。设备操作和端到端验证不是默认要求；真实 App 验证只作为维护者可选高级流程。

只读取和当前问题直接相关的参考文件，不要一次性展开所有资料。

本技能已经完整整合 `tavo-complete` 的官方能力边界、功能路由、回答规则和 Tavo Dev Kit 验收口径。用户只要求加载一个 Tavo skill 时，优先加载本技能。

---

## 官方能力边界（整合自 tavo-complete）

这一节处理 Tavo 的官方能力说明、配置建议、脚本编写和故障排查。边界是“只把文档里明确出现的能力当作官方支持能力”。

### 核心规则

- 把 `references/` 里的文件视为这个 skill 的权威范围。
- 如果某项能力不在这些参考里，不要把它说成“官方明确支持”。
- 如果你基于已知能力做延伸建议，必须明确说那是“归纳/推断/建议用法”，不是官方承诺。
- 解释 API、宏、字段名、设置项时，优先使用文档中的原始命名。

### 官方能力先读哪份参考

- 预设：读 [references/preset.md](references/preset.md)
- 世界书：读 [references/lorebook.md](references/lorebook.md)
- 正则：读 [references/regex.md](references/regex.md)
- 长记忆：读 [references/long-memory.md](references/long-memory.md)
- 高级前端渲染：读 [references/advanced-rendering.md](references/advanced-rendering.md)
- JavaScript API：读 [references/javascript-api.md](references/javascript-api.md)
- 宏：读 [references/macros.md](references/macros.md)
- 其他设置项：读 [references/others.md](references/others.md)

### 官方功能路由

#### 1. 提示词与上下文系统

遇到这些需求时，优先在以下几份里找：

- 角色行为模板、聊天推进、输出格式：`preset.md`
- 世界设定、知识注入、触发条目：`lorebook.md`
- 动态占位符、变量、时间、随机数：`macros.md`
- 文本清洗、输入简写展开、输出格式加工：`regex.md`
- 跨会话保留重要信息：`long-memory.md`

#### 2. 渲染与可编程能力

遇到这些需求时，优先在以下几份里找：

- HTML/CSS 页面化渲染：`advanced-rendering.md`
- JS 脚本、对象管理、生成请求、输入框控制：`javascript-api.md`

#### 3. 设置页工具功能

遇到这些需求时，优先读 `others.md`，里面覆盖：

- 存储空间
- 备份与恢复
- 图片发送
- 自定义聊天快捷键
- 群聊快捷发言

### 官方能力工作流程

1. 先判断用户是在问：
   - 官方是否支持某能力
   - 某个功能怎么配置
   - 某套玩法该用哪些能力组合
   - 如何写 JS / 宏 / 预设 / 世界书 / 正则
   - 某项配置为什么没生效
2. 只读取和问题直接相关的参考文件，不要一次性展开所有资料。
3. 回答时先说“官方明确支持的部分”，再说“建议做法”。
4. 如果要写代码或配置：
   - JS 接口名、对象字段、参数名以 `javascript-api.md` 为准
   - 宏名与变量宏写法以 `macros.md` 为准
   - 预设条目职责与结构以 `preset.md` 为准
   - 世界书条目职责与触发逻辑以 `lorebook.md` 为准
   - 正则字段和执行时机以 `regex.md` 为准
5. 如果用户要确认“是不是官方支持”，只引用参考里明确写到的能力，不要靠感觉补空白。

### 高价值的组合方式

这些组合是常见工作路径，但要记得它们是“能力组合建议”，不是额外新功能：

- 预设 + 宏：做动态提示词
- 世界书 + 宏：做条件触发设定和状态初始化
- 正则 + 宏：做输入简写展开、状态更新命令
- 高级前端渲染 + JavaScript API：做带 UI 的互动气泡或面板
- 长记忆 + 预设/世界书：把“长期保留信息”和“固定设定”分层管理

### 官方功能边界速记

- `预设`：系统级提示词模板与行为控制
- `世界书`：世界事实、背景知识、条件触发注入
- `宏`：动态占位符与变量系统
- `正则`：文本加工与替换中间层
- `长记忆`：聊天中的长期保留信息
- `高级前端渲染`：HTML/CSS 展示层
- `JavaScript API`：数据和交互的脚本层
- `其他`：设置页里的辅助功能

### 回答官方能力问题时的要求

- 如果用户问“官方是否支持”，答案必须保守。
- 如果文档只写了入口和基础功能，不要擅自扩展成完整产品能力图。
- 如果页面里存在标题但正文没展开，明确说明“文档当前没有继续展开”。
- 如果写示例代码，尽量贴近文档中的字段和方法，不要发明新的 API 名字。

### 官方能力交付偏好

默认按下面的顺序组织答案：

1. 官方明确支持什么
2. 该能力怎么配置或调用
3. 有哪些已知限制
4. 如果需要，再补充合理的组合建议

### Tavo Dev Kit v1 实测能力（2026-05-13）

这一节记录的是 Tavo Dev Kit 能力。它不是 Tavo 官方 SDK，也不要把它写成“官方已经提供的能力”。它的定位是：把 Tavo 可导入资源、本地 mock、类型检查和 JSON 校验串起来，让 AI 写出来的 Tavo 脚本和配置可以被重复测试。真实 App 验证是维护者可选的高级流程，不是普通用户默认工作流。

#### 与本 skill 的关系

- 本技能是知识、创作和边界入口：回答“官方文档明确支持什么”“某个 Tavo 能力应该怎么组合”“哪些说法不能当官方承诺”，也负责角色卡、世界书、正则、预设、AR HTML 和 JS 脚本的内容设计与文件产出。
- `Tavo Dev Kit` 是本地工程工具：生成 Tavo 可导入 JSON、本地跑 mock 测试、做类型检查和 schema 校验。
- 当用户问“SDK 和 skill 区别”时，直接解释成：skill 像说明书和操作规程，SDK 像可运行的工具箱和测试台。
- 当用户问“SDK 有什么是 skill 做不到的”时，重点说：skill 不能自己执行检查；Dev Kit 可以执行类型检查、单元测试、JSON 校验和资源生成。真实 App 导入验证属于可选高级能力。
- 当用户问“有没有必要做 SDK”时，保守回答：如果只是写一次角色卡/世界书，skill 足够；如果用户主要靠 AI 写代码并想稳定复验，Dev Kit 有价值，因为它把“看起来对”变成“能被测试报告证明”。

#### Dev Kit 位置和命令

- 工程目录：本仓库的 `dev-kit/`
- 常用命令：
  - `npm run typecheck`：检查 TypeScript 类型。
  - `npm test`：跑本地 mock 和生成逻辑测试。
  - `npm run build`：把库文件构建到 `dist/lib/`。
  - `npm run build:assets`：生成可导入 Tavo 的 JSON/HTML/报告样例。
  - `npm run build:widget`：把 `templates/ar-widget/widget.html|css|js` 打成单文件 AR widget HTML 和正则草稿。
  - `npm run package:zip`：生成分享 zip，排除 `node_modules`、`.env.local`、`reports/` 和 `dist/tavo-import/`。
  - `npm run verify:local`：普通用户推荐的本地验收入口，包含类型、本地测试、构建、资产生成、打包和发布检查。
- 输出目录：
  - `dev-kit/dist/tavo-import/`：给 Tavo 导入的资源文件。
  - `dev-kit/dist/lib/`：npm/TS 库构建输出。
  - `dev-kit/dist/packages/tavo-dev-kit-0.1.0.zip`：本地分享包，不含 `node_modules`、`.env.local`、`reports/` 和 `dist/tavo-import/`。
  - `dev-kit/reports/latest/`：可选真实 App 探测报告，不属于普通用户默认产物。
- 本地密钥只允许放在 `.env.local`，不要写入源码、README、skill、报告或回答。

#### 已验证的 Dev Kit 公开能力

这些能力来自本机实现和测试，不代表官方 Tavo 直接提供这些 npm API：

- `TavoApi` 类型：覆盖变量、message、chat、character、persona、preset、lorebook、regex、memory、generate、input、utils、app version 等脚本常用面；scope 明确为 `chat | global`，不推荐伪造 `character` scope。
- `createMockTavo()`：本地模拟 Tavo API，用来测试变量路径、chat/global scope、message API、资源 CRUD/import、memory、input、toast/export/select、app version、mock generate 等行为。
- `defineTavoScript()`：给 AI 写脚本用的标准入口，让脚本能被 TypeScript 类型检查和本地测试包住。
- `createTavoSDK()` / `tavoSDK`：可选包装层，提供 `vars`、`messages`、`chat.rename`、`memory.add`、`input.replace` 等便捷方法；它只作为开发辅助，最终放进 Tavo 的脚本默认仍应写官方 `tavo.*`。
- `dev/tavo.d.ts`、`dev/tavo-dev.mjs`、`.vscode/tavo.code-snippets`、`jsconfig.json`：支持普通 JS 本地补全、mock 运行和常用脚本片段。
- `buildTavoAssets()`：生成可导入 Tavo 的资源，包括角色卡、世界书、正则、预设、AR direct HTML、AR widget HTML、AR widget regex 草稿、导入清单和测试报告 JSON。
- `buildArWidgetFiles()`：把分文件 AR widget 模板构建成无 npm import、无外链、无 Node API 的单文件 HTML 和对应正则草稿。
- 可选真实 App 探测流程：如果维护者已有设备环境，可以把生成资源导入真实 Tavo App，并保存脱敏日志和报告。

#### 可选真实 App 验证

普通用户不需要准备模拟器。维护者如果已有设备环境，可以用 `dev-kit/` 的高级 probe 检查导入和 AR/JS 行为。公开文档里不要把这条可选路径写成安装要求。

#### 正则和 JS 的边界

这里仍然要区分“导入成功”“替换成功”“JS 执行成功”。本地 schema/mock 只能证明格式和脚本逻辑；如果要声称真实 App 已执行，仍需要可观察证据。

- 本地可验证：Dev Kit 生成的正则 JSON 符合当前已知导入结构。
- 可选真实 App probe 曾验证：导入后的正则组如果应用到当前聊天，可以把测试 marker 替换成可执行 HTML/script，并显示可见成功标记。
- 必须注意：只导入正则组还不够；真实 App 里要把正则组应用到目标聊天，否则该聊天不一定会使用这组正则。
- 生成 `<script>` 文本不等于 JS 已执行；必须有 toast、UI 文本、变量变化、message/memory/worldbook 更新等可观察结果才能算执行成功。
- 这个结论只覆盖当前 Dev Kit 的安全探针路径，不等于任意社区正则、任意触发时机、任意 Tavo 未来版本都稳定执行。
- 不推荐把自动回归默认改成 `接收时` / `接收和改写时` 等会改写既有消息的时机；当前探针使用可控文本标记和当前聊天绑定来降低风险。

#### 验收口径

当用户问“怎么知道 SDK 没乱跑”或“SDK 怎么确认跟软件一样”时，按这个口径回答：

1. 本地层：TypeScript 类型检查和 Vitest 测试保证 Dev Kit 自己的 mock、生成器和校验逻辑没明显坏。
2. 格式层：Zod/JSON 校验保证输出结构符合已知 Tavo 导入格式。
3. 文件层：生成的 JSON/HTML 能通过 schema/parse 检查，并能被用户手动导入 Tavo。
4. 可选真实 App 层：维护者可以把同一批 JSON 真的导入 Tavo，并生成报告。
5. 报告层：普通用户看 `npm run verify:local` 是否通过；维护者额外跑真实 App probe 时再看对应报告。

公开版默认通过口径是：`npm run verify:local` 通过。真实 App probe 是维护者可选回归，不作为普通用户安装要求。

#### 安全规则

- 不要为了验证而清空 Tavo、卸载 Tavo、恢复备份、删除聊天或直接改 ObjectBox 数据库。
- 可选真实 App 测试资源统一使用 `codex-devkit-*` 前缀，便于之后复查。
- 如果做真实 App 验证，优先走 UI 导入和 UI 验证；数据库读取只用于诊断或只读核对。
- 任何报告、日志、截图说明都必须默认脱敏；不要泄露 `.env.local` 里的真实 key。
- 如果 Tavo 版本升级，维护者可以重新跑真实 App probe 校准；普通用户仍可只跑本地检查。

#### 回答用户时的推荐说法

- 可以说：“Dev Kit 不是官方 SDK，但它把 Tavo 文件生成、本地 mock、类型检查和 schema 校验自动化了。”
- 可以说：“普通用户不需要模拟器；有设备环境的维护者可以额外跑真实 App 回归。”
- 可以说：“现在最硬的日常价值是稳定本地检查：AI 写完后可以跑一遍，看脚本类型、mock 行为和生成文件格式有没有明显问题。”
- 不要说：“SDK 等同 Tavo 运行时。”它只是 mock + 生成器 + 回归测试工具，真正行为仍以 Tavo App 实测为准。

## 参考路由

根据用户需求，读对应的参考文件：

### 从零构思角色卡

- [references/card-creation-guide.md](references/card-creation-guide.md) — **角色卡构思引导流程**。当用户想从零开始创作角色卡（表达了模糊想法、要求帮忙想角色、或说"帮我做张卡"），必须先读这份引导流程，按其中的阶段和格式逐轮引导用户，不要跳过引导直接写卡。

### 角色卡结构与字段

- [references/character-card-guide.md](references/character-card-guide.md) — `chara_card_v2` 各字段写法、常驻 token 规则、`character_book` 嵌入格式、质检清单、结构化标签输出格式
- [references/official-sources.md](references/official-sources.md) — 官方文档、源码、APK 逆向依据

### 写作质量

- [references/ai-cliche-blacklist.md](references/ai-cliche-blacklist.md) — AI 废词黑名单与文本清洗规则。生成角色卡内容后应参考此表做一轮清洗，或在生成 prompt 中预防。

### 玩法模式

- [references/gameplay-modes.md](references/gameplay-modes.md) — 9 种玩法模式分类（纯角色/武侠/仙侠/ARPG/剧情RPG/生存/种田/好感养成等），每种模式的配套资源清单和变量示例。做卡前先确认玩法模式，再走对应资源路线。

### 世界书

- [references/worldbook-guide.md](references/worldbook-guide.md) — 世界书 JSON 结构、字段逐条说明、独立格式与 `character_book` 转换规则
- [references/lorebook.md](references/lorebook.md) — 世界书设计策略：触发词规划、内容拆分、分层展开、与预设/长记忆的协作边界

> 两份互补：`worldbook-guide.md` 解决"JSON 怎么写才合法"，`lorebook.md` 解决"内容怎么设计才好用"。

### PNG 嵌入

- [references/png-embedding.md](references/png-embedding.md) — PNG `tEXt` chunk 嵌入/提取机制

### 预设

- [references/preset.md](references/preset.md) — 预设条目职责（Main Prompt、Post-History Instructions、基础提示词等），预设如何组装角色卡字段进 prompt，含 NSFW、Jailbreak、Impersonation 控制

### 宏

- [references/macros.md](references/macros.md) — `{{char}}`、`{{user}}`、变量宏（setvar/getvar/incvar/decvar）、全局变量、时间宏、随机数、宏助手

### 正则

- [references/regex.md](references/regex.md) — 文本清洗、输入简写展开、输出格式化、作用范围与执行时机、ST→Tavo 字段精确转换规则

> `references/regex.md` 讲的是功能和字段概念，不等于"界面可导入 JSON 长什么样"。如果要产出**可直接导入**的正则文件，必须额外核对本机导出样本或源码里的导入逻辑，不要把 API 字段描述直接当成导入文件格式。

### 长记忆

- [references/long-memory.md](references/long-memory.md) — 手动提取 vs 自动提取、JS API 操作

### JavaScript API

- [references/javascript-api.md](references/javascript-api.md) — 变量、聊天、角色、用户身份、预设、世界书、正则、长记忆、生成请求、输入框、工具函数的脚本接口。含命名空间说明、ST 兼容层、内部通信机制

### 高级前端渲染

- [references/advanced-rendering.md](references/advanced-rendering.md) — HTML/CSS 气泡化展示；重点包括 Tavo 不等于普通浏览器、Markdown/DOMPurify/iframe/JS 模式限制，以及与 JS API 配合做 UI 的边界

### TTS（文字转语音）

- [references/tts.md](references/tts.md) — 13 个 UI 平台 + Multi-System 下挂的多个 Android TTS 引擎、4 个代理、TTS 端点管理、角色语音绑定

### API 端点（Endpoint）

- [references/endpoint.md](references/endpoint.md) — 15 个逻辑平台 / 16 个图标资源、协议系兼容层、Vertex AI 30 区域 + 双认证模式、模型能力位、内置模型注册表（193 模型 + 字段分布）、19 个 warning 相关 key（约 17 个错误分类）

### 负载均衡器

- [references/load-balancer.md](references/load-balancer.md) — 多 AI 提供商请求分发、4 个策略（round_robin / weighted / random / lru，**无 geo/latency**）、端点管理联动、负载均衡日志、max_retries / weight 等配置项

### 其他设置

- [references/others.md](references/others.md) — 存储空间、备份恢复、图片发送、聊天快捷键、群聊快捷发言、快捷键、宏助手、群聊提示词系统、Discord 社区

---

## 各能力之间的关系

Tavo 的能力不是孤立的，它们组成一条完整的链路：

```
角色卡字段（description, first_mes, mes_example ...）
    ↓ 被预设模板组装进 prompt
预设（Main Prompt, Post-History Instructions ...）
    ↓ 字段和条目里可以使用宏
宏（{{char}}, {{getvar::hp}}, {{time}} ...）
    ↓ 世界书条目的 content 也可以用宏
世界书（触发词命中 → content 注入 prompt）
    ↓ 正则在发送前/后对文本做加工
正则（清洗输出、展开输入简写、拼接状态栏）
    ↓ 长记忆跨会话保留重要信息
长记忆（手动/自动提取，补充角色卡和世界书不覆盖的动态事实）
    ↓ JS API 可以脚本化操作已暴露的对象
JavaScript API（变量、聊天、消息、角色、预设、世界书、正则、记忆、生成请求等已暴露接口）
    ↓ 高级前端渲染负责展示层
高级前端渲染（HTML/CSS 气泡 UI，与 JS API 联动）
    ↓ 运行时能力依赖底层基础设施
基础设施（API 端点管理、负载均衡器、TTS 平台、模型注册表）
```

做任何一个环节时，都可以自然地牵涉到其他环节。按需读取对应参考即可。

---

## 角色卡制作工作流

### 从零构思 vs 直接写卡

- 如果用户**只有模糊想法**（"帮我做张卡""我想做一个冷淡的角色"），先读 `references/card-creation-guide.md`，按引导流程逐轮帮用户厘清构思，完成后再进入下面的制作流程。
- 如果用户**已经有明确的设定**（提供了详细描述、或者给了现成文本要求转成角色卡），直接进入下面的制作流程。

### 默认交付物

除非用户明确说只要其中一种，否则默认同时产出：

1. `角色名.card.json`
2. `角色名.card.png`
3. `角色名.worldbook.json`

如果世界书要嵌入角色卡，再把它写进 `data.character_book`。

### 步骤

1. 先确认要做的是：
   - 只有角色卡
   - 只有世界书
   - 两者都要
   - 世界书既要独立 JSON，也要嵌进角色卡
2. 用官方字段语义写内容（详见 `character-card-guide.md`）：
   - `description` 放必须长期存在的核心设定
   - `personality` 放性格摘要
   - `scenario` 放当前对话场景
   - `first_mes` 决定开场风格和长度
   - `mes_example` 用 `<START>` 分块示范口吻
   - `creator_notes` 只放元信息，不放必须进 prompt 的硬设定
   - 字段里可以使用宏（如 `{{user}}`、`{{char}}`），参考 `macros.md`
3. 写独立世界书时，使用 ST 的 `entries` 顶层对象格式（详见 `worldbook-guide.md`）。
   - 设计触发词和内容拆分策略时，参考 `lorebook.md`
   - 世界书条目的 `content` 里也可以使用宏
4. 需要嵌入卡内 lore 时：
   - 直接写 `data.character_book`，或
   - 用 `scripts/worldbook_to_character_book.mjs` 把独立世界书转成嵌入格式
5. 需要 PNG 卡时，用 `scripts/embed_st_card_png.mjs` 把 JSON 写进 PNG 元数据。
6. 需要检查现成 PNG 卡时，用 `scripts/extract_st_card_png.mjs` 抽出内嵌 JSON。
7. 交付前按 `character-card-guide.md` 第 7 节质检清单做完整校验（结构校验 + 内容校验 + 活人感校验）。
8. 生成内容后参考 `ai-cliche-blacklist.md` 做 AI 废词清洗。

### 高优先级写作规则

- 角色必须稳定记住的东西不要只放在世界书或 `creator_notes` 里。`description` 是常驻 token 区，核心设定放这里。
- 世界书的 `key`、`comment`、标题本身不会注入 prompt；真正给模型看的只有 `content`，所以 `content` 必须独立成句、独立成立。
- `first_mes` 往往比任何"解释风格"的描述都更强——模型会从它学习回复长度、文风和格式。
- `mes_example` 不是设定百科，它是口吻示范器。
- 世界书尽量短、准、可触发。不要把整个角色卡内容复制进每个 entry。
- 需要分享时，优先给用户同时产出 `.json` 和 `.png`；PNG 用于导入，JSON 用于版本管理。
- 预设决定了角色卡字段如何被组装进 prompt（参考 `preset.md`），写卡时要意识到字段最终的上下文位置。
- 生成的文本必须经过 AI 废词清洗（参考 `ai-cliche-blacklist.md`），删除"不禁""油然而生""命运的齿轮"等套话。
- 角色不能写成服务型 NPC——允许嘴硬、回避、停顿、误判，但必须符合人设。面对不同关系层级必须有差异化反应。
- 做卡前先确认玩法模式（参考 `gameplay-modes.md`），不同模式的资源配套差异很大。没有明确玩法需求时默认走纯角色路线。

### 常用命令

把角色卡 JSON 嵌进 PNG：

```bash
node skills/tavo-studio/scripts/embed_st_card_png.mjs \
  --png "/path/to/base.png" \
  --json "/path/to/character.card.json" \
  --out "/path/to/character.card.png" \
  --overwrite
```

从 PNG 提取角色卡：

```bash
node skills/tavo-studio/scripts/extract_st_card_png.mjs \
  --png "/path/to/character.card.png" \
  --out "/path/to/extracted.card.json"
```

把独立世界书转成 `character_book`：

```bash
node skills/tavo-studio/scripts/worldbook_to_character_book.mjs \
  --in "/path/to/worldbook.json" \
  --out "/path/to/character_book.json" \
  --name "My Lorebook"
```

### 正则 / 前端配套工作流

如果用户要做"正则前端""消息框美化""状态栏""折叠块""伪前端 UI"，按下面顺序处理：

1. 先确认用户要的是：
   - 只做文本分框
   - 只折叠状态栏
   - 折叠整条消息
   - 还是直接用高级前端渲染做完整 HTML/CSS
2. 明确边界：
   - 正则负责**把消息改写成目标文本/HTML**
   - 高级前端渲染负责**把 HTML/CSS 真正渲染出来**
   - 不要把"正则前端"和"AR 前端"混成一件事
3. 如果要产出**可导入的正则 JSON**，优先参考：
   - 本机已导出的 regex JSON 样本
   - 你本地 SillyTavern 的 regex extension 源码（如果有）
   - 本仓库 `skills/tavo-studio/references/regex.md`
4. **不要**把 `references/javascript-api.md` 里的正则对象字段直接当成界面导入格式。
5. **不要**默认让正则注入的 `<script>` 执行。正则只负责文本替换；脚本能否运行取决于高级前端渲染、`javaScriptExecutionMode`、DOMPurify 和 iframe 沙盒。需要可靠写状态时，优先用已暴露的 JS API，或要求用户明确启用对应 AR/JS 模式。

### Tavo Dev Kit 产出规则

当用户要做 Tavo 角色卡、世界书、正则、高级前端渲染组件或 JS API 脚本，并且希望“AI 写完以后能检查能跑”，优先把本技能的内容设计能力和本机 Dev Kit 的测试能力结合起来。

本仓库 Dev Kit：

- 路径：`dev-kit/`
- 定位：本地生成器 + mock + JSON 校验，不是 Tavo 官方 SDK。真实 App probe 是维护者可选能力。
- 适合：生成 Tavo 可导入文件、让 AI 写的脚本先过类型/单测、把输出格式先检查一遍。
- 常用命令：
  - `npm run typecheck`
  - `npm test`
  - `npm run build`
  - `npm run build:assets`
  - `npm run build:widget`
  - `npm run package:zip`
  - `npm run verify:local`
- 输出：
  - `dist/tavo-import/`：可导入 Tavo 的角色卡、世界书、正则、预设、AR HTML 等产物。
  - `dist/lib/`：库构建输出。
  - `dist/packages/tavo-dev-kit-0.1.0.zip`：分享包，不含 `node_modules`、`.env.local`、`reports/` 和 `dist/tavo-import/`。
  - `reports/latest/`：可选真实 App 测试报告和脱敏日志。

#### 产出代码时的主路线

写 Tavo JS/AR 组件时，默认采用这条路线：

1. 开发阶段可以用 Dev Kit 的类型、mock、示例和测试。
2. 业务代码尽量直接写官方 `tavo.*`，例如：
   - `tavo.get(...)`
   - `tavo.set(...)`
   - `tavo.message.find(...)`
   - `tavo.message.append(...)`
   - `tavo.chat.current(...)`
   - `tavo.memory.current()`
   - `tavo.utils.toast(...)`
3. 最终导入 Tavo 的文件必须是普通 JSON、HTML 或单文件脚本，不要包含 npm import。
4. 如果产出 AR HTML，构建后要检查最终单文件里没有 `import`、没有外部依赖、没有 Node 专用 API。
5. 如果要给正则用，正则只负责把模型输出的标记替换成 HTML/脚本文本；脚本是否执行必须靠高级前端渲染中的可观察结果确认。真实 App probe 只是可选强化验证。

#### 用 Dev Kit 交付 Tavo 资源的推荐口径

当用户要“做一个可导入的 Tavo 包/SDK 示例/前端组件”时，优先交付这些东西：

- 角色卡 JSON：符合 CCv3/ST v2 结构，核心设定写入常驻字段。
- 世界书 JSON：独立世界书格式，条目 `content` 独立成立，触发词短而准。
- 正则 JSON：用 Tavo/ST 界面可导入格式，不把 JS API 的内部对象字段误当导入格式。
- 预设 JSON：按 Tavo 预设结构表达提示词条目职责。
- AR HTML：如果有 UI，用单文件 HTML/CSS/JS，代码直接调用 `tavo.*`。
- AR widget：优先使用 `templates/ar-widget/widget.html|css|js` 分文件开发，再用 `npm run build:widget` 或 `build:assets` 打成单文件 HTML；真实 App 验收时要出现 `AR_WIDGET_OK` 这类可见 marker。
- 本地测试：mock 跑脚本逻辑，JSON parse 和 schema 校验通过。
- 真实 App 证明：维护者有设备环境时可以额外跑高级 probe；普通用户不需要这一步。

#### 正则 + AR/JS 的保守规则

必须区分三件事：

- 正则导入成功：说明 Tavo 接受这个 JSON 格式。
- 正则替换成功：说明 Tavo 把某段文本替换成了目标 HTML/文本。
- JS 执行成功：说明替换后的脚本真的在 Tavo 高级前端渲染里执行，并产生可观察副作用。

默认不要把前两者说成第三者。只有出现下面任一证据，才可以说 JS 跑通：

- UI 出现明确 marker。
- `tavo.set(...)` 后能通过 UI、日志或后续脚本读到变量变化。
- `tavo.message.append(...)` 追加了可见消息。
- `tavo.utils.toast(...)` 出现提示。
- memory/worldbook/chat 等对象出现可验证更新。

当前 Dev Kit 日常交付时优先确认的是：

- 角色卡、世界书、预设、正则 JSON 的结构能通过本地校验。
- AR HTML/widget 输出为单文件，不能包含 npm import、外链或 Node 专用 API。
- JS 示例优先直接调用官方 `tavo.*`，包装层只用于本地开发体验。
- 如果维护者额外跑真实 App probe，才把真实 App 导入和可见 marker 当作证据。

#### 与其他 skill 的分工

- 本技能负责：判断官方文档明确支持什么、哪些是本机实测、哪些只是建议，也负责设计和产出角色卡、世界书、正则、预设、AR HTML、JS API 脚本。
- `tavo-complete` 的核心内容已经完整并入本技能；用户只想加载一个 Tavo skill 时，不需要额外加载 `tavo-complete`。
- `dev-kit/` 负责：生成文件、本地 mock、类型检查、JSON 校验；真实 App probe 是可选高级能力。
- 如果本地另有设备操作 skill，它只用于维护者做真实 App 补充验证。
- 需要普通验收时，先用本技能产出资源，再进入 `dev-kit/` 跑 `npm run verify:local`。

### 可导入正则文件的稳定格式

Tavo / SillyTavern 界面导入吃的是"脚本对象"或"脚本对象数组"，稳定字段应至少包含：

```json
{
  "id": "uuid",
  "scriptName": "脚本名",
  "findRegex": "/pattern/flags",
  "replaceString": "replacement",
  "trimStrings": [],
  "placement": [2],
  "disabled": false,
  "markdownOnly": true,
  "promptOnly": false,
  "runOnEdit": false,
  "substituteRegex": 0,
  "minDepth": null,
  "maxDepth": null
}
```

`placement` 的常用值：

- `1` = User Input
- `2` = AI Output
- `3` = Slash Commands
- `5` = World Info
- `6` = Reasoning

### 模板

直接从这些模板起步：

- [assets/templates/character-card.v2.minimal.json](assets/templates/character-card.v2.minimal.json)
- [assets/templates/character-card.v2.full.json](assets/templates/character-card.v2.full.json)
- [assets/templates/worldbook.minimal.json](assets/templates/worldbook.minimal.json)
- [assets/templates/worldbook.advanced.json](assets/templates/worldbook.advanced.json)

### 交付清单

完成后检查：

- 角色名、宏名、文件名一致
- `alternate_greetings` 是数组
- `tags` 是数组
- `data.extensions` 是对象
- 需要嵌 lore 时，`data.character_book.extensions` 和 `entries` 存在
- 独立世界书的每条 entry 都有可读的 `comment`，不要留空；它决定列表里的条目名
- 世界书的 `uid`、对象键、`displayIndex` 没有混乱
- PNG 已成功写入 `chara` 元数据
- 如果产出可导入正则文件，至少做一次 JSON parse，并确认顶层是"脚本对象"或"脚本数组"，不是世界书结构

### PNG 与外置资源的边界

- 官方角色卡 PNG 只保证 `chara` / `ccv3` payload 可被正常识别。
- `data.character_book` 可以随角色卡一起嵌入 PNG，因为它本来就是角色卡 JSON 的一部分。
- 正则、预设、脚本这类对象默认应视为外置资源。
- 就算额外把正则写进 PNG 的自定义 `tEXt` chunk，也不要说成"Tavo 会自动识别导入"；这最多只是打包或备份。

### 多对象交付顺序

同时处理角色卡、世界书、PNG、正则、前端时，按这个顺序走：

1. 先完成角色卡 JSON
2. 再完成独立世界书 JSON
3. 验证世界书条目名、结构和常驻/触发策略
4. 再嵌入 PNG
5. 最后再做外置正则 / 前端资源
6. 每完成一层就单独回读验证，不要等全部做完再一起验

---

## 常见组合玩法

这些是 Tavo 各能力之间经过验证的组合路径：

| 组合 | 做什么 |
|------|--------|
| 角色卡 + 世界书 + 宏 | 角色设定 + 条件触发知识 + 动态变量（如 HP、好感度、回合数） |
| 预设 + 宏 | 动态提示词模板；状态写入不要放在每轮都会重置的位置 |
| 世界书 + 宏 | 触发条目时初始化变量，做剧情切章或地图切换；仅在该条目实际进入 prompt 时生效 |
| 正则 + 宏 | 输入简写展开（`-hp5` → `{{decvar::hp}}` × 5）、输出状态栏拼接；显示-only 输出不等于状态已持久化 |
| 高级前端渲染 + JS API | HTML/CSS 展示 + 在允许 JS 模式下的互动气泡、RPG HUD、状态面板 |
| 长记忆 + 世界书 | 长记忆保留动态事实，世界书保留静态设定，分层管理 |
| JS API + 角色/世界书 | 脚本化批量创建或修改角色卡和世界书条目 |
| 负载均衡器 + 端点管理 | 高可用、按权重/轮换/随机/LRU 分发；跨区域需手动分组 |
| TTS + 角色绑定 | 每个角色配置不同的 TTS 平台和声音 |

---

## 功能边界速记

| 能力 | 负责什么 | 不负责什么 |
|------|----------|------------|
| 角色卡 | 角色身份、设定、开场、示例对话 | 系统行为规则 |
| 世界书 | 世界事实、条件触发知识注入 | 输出格式、口吻控制 |
| 预设 | 系统级提示词模板、行为与输出规则 | 角色具体设定 |
| 宏 | 动态占位符、变量状态系统 | 文本加工 |
| 正则 | 文本清洗、格式化、简写展开 | 状态存储 |
| 长记忆 | 跨会话动态事实保留 | 静态世界设定 |
| JS API | 脚本化操作 `sandbox.js` 暴露的对象：变量、聊天、消息、角色、用户身份、预设、世界书、正则、记忆、生成请求、输入框、工具函数、版本信息 | 未暴露的原生设置，如端点/TTS 端点/备份/存储空间配置 |
| 高级前端渲染 | HTML/CSS 展示层；按 Tavo WebView、Markdown、DOMPurify、iframe 沙盒运行 | 普通浏览器整页环境、保证任意 JS 执行 |
| TTS | 文字转语音、多平台语音合成 | 内容生成 |
| 负载均衡器 | 多端点请求分发、故障转移 | 端点自身的鉴权、协议转换、geo/latency 路由 |
| API 端点 | 模型提供商的连接配置 | 模型行为控制、把非兼容 API 自动适配成所选协议 |

### 轻量提及：其他相关领域

以下领域在 APK 实证中得到确认，详细内容见对应 reference，主索引在此：

- **API 端点 / 模型注册表**：见 [references/endpoint.md](references/endpoint.md)。要点：默认直连而非走 Volink；15 个逻辑平台 / 16 个图标资源；30 个 Vertex 区域；内置 193 个模型（仅约 1/5 含定价/上下文长度，5% 含完整 capabilities）；19 个 warning 相关 key（约 17 个错误分类）。
- **角色卡导入源**：libapp.so 实证支持 6 个外部导入源（直接 URL 导入）：
  - `chub.ai`（API: `api.chub.ai/api/characters/`、世界书: `api.chub.ai/api/lorebooks/download`）
  - `janitorai.com`
  - `realm.risuai.net`（PNG-v3 下载: `realm.risuai.net/api/v1/download/png-v3/`）
  - `aicharactercards.com`（带 `pngapi/v1/image/` 接口）
  - `pygmalion.chat`（导出: `server.pygmalion.chat/api/export/character/`）
  - `onlycards.ai`（API: `card.onlycards.ai/api/v1/cards/`，前端 `t.onlycards.ai`）

  导入时按 URL 正则识别站点，后续格式处理属于 App 原生导入流程；不要把它等同于 JS API 中 `lorebook.create/update()` 的 `o()/i()` 转换链路。
- **隐私提示**：Tavo App 包含 Microsoft Clarity（行为追踪）和 Sentry（错误监控 + Session Replay）。分发包含 API 密钥的备份文件时请注意安全。

### 默认不能假设的能力

- 不要假设“浏览器能渲染”就等于“Tavo 气泡里能渲染”；Tavo 先走 Markdown/DOMPurify，再按 JS 模式决定是否进 iframe。
- 不要假设正则输出 `<script>` 或事件属性后脚本一定执行；正则不是 JS runner，也不是状态数据库。
- 不要假设 ST/CCv3 扩展字段都会影响 Tavo 运行时；有些字段只是兼容、导入、导出或保留字段。
- 不要假设 PNG 除 `chara` / `ccv3` 角色卡 payload 外的自定义 chunk 会被 Tavo 自动识别为正则、预设或脚本。
- 不要假设 JS API 能操作所有 App 数据；以 `sandbox.js` 暴露的 `window.tavo.*` 方法为边界。
- 不要假设负载均衡器会做协议转换、跨区域最近路由或语义兼容判断；只把可互换端点放进同一组。
- 不要假设勾选模型能力位就证明上游模型真的支持；图片、reasoning、function、structure 等仍以实际端点响应为准。

---

## 回答规则

- `references/` 里的文件是这个 skill 的权威范围。
- 如果某项能力不在参考里，不要说成"官方明确支持"。
- 基于已知能力的延伸建议，必须标注为"归纳/推断/建议用法"。
- 写代码或配置时，API 名、字段名、参数名以对应参考文件为准。
- 如果文档页面有标题但正文没展开，明确说明"文档当前没有继续展开"。
- 只要任务涉及"可导入对象"的文件格式（正则、角色卡、世界书、预设等），优先找**真实导出样本**或**源码导入逻辑**，不要只凭文档概念猜格式。
- 如果用户说"折叠状态栏"，默认理解为"只折叠状态区域，不折叠正文"；如果要折叠整条消息，必须先确认。

默认按这个顺序组织答案：

1. 官方明确支持什么
2. 怎么配置或调用
3. 已知限制
4. 合理的组合建议
