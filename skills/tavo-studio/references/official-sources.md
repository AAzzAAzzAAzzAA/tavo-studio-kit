# 官方依据

下面这些是本 skill 的主要依据。写卡、写世界书、做 PNG 嵌入时，优先相信这些来源而不是二手教程。

## 官方文档

- Characters: <https://docs.sillytavern.app/usage/characters/>
  - 角色管理面板
  - 角色 lore / chat lore 入口
  - 导出角色、导入 lore 的 UI 位置
- Character Design: <https://docs.sillytavern.app/usage/core-concepts/characterdesign/>
  - `description`、`first_mes`、`mes_example`、`creator_notes` 等字段的用途
  - 哪些字段属于”永久 token”，哪些不是
- Prompts: <https://docs.sillytavern.app/usage/prompts/>
  - 角色字段如何参与 prompt
  - `system_prompt` / `post_history_instructions` 的角色
- World Info: <https://docs.sillytavern.app/usage/core-concepts/worldinfo/>
  - 世界书触发逻辑
  - 插入位置
  - 递归、预算、扫描深度、角色过滤、触发类型
  - 角色绑定世界书时，导出角色会把主世界书嵌入角色卡

### Tavo 官方文档

- Tavo 文档总站：<https://docs.tavoai.dev/>
- JS API 指南：<https://docs.tavoai.dev/guides/javascript-api/>
- 预设指南：<https://docs.tavoai.dev/guides/preset/>
- 宏指南：<https://docs.tavoai.dev/guides/supported-macros/>
- 正则指南：<https://docs.tavoai.dev/guides/regular/>
- 长记忆指南：<https://docs.tavoai.dev/guides/long-memory/>
- 高级前端渲染：<https://docs.tavoai.dev/guides/advanced-rendering/>
- 其他功能：<https://docs.tavoai.dev/guides/others/>
- Tavo 官网：<https://tavoai.dev>
- 模型注册表：<https://tavoai.dev/registry>

## 官方源码

### SillyTavern 源码

仓库：<https://github.com/SillyTavern/SillyTavern>

本 skill 编写时核对的分支与提交：

- branch: `release`
- commit: `e3f41666c69db032e17e079fcddcf40cf47e8593`

重点文件：

- `src/types/spec-v2.d.ts`
  - 定义 `chara_card_v2` 的字段
- `src/character-card-parser.js`
  - 定义 PNG 嵌入/提取逻辑
  - 角色卡 JSON 会被 base64 后写入 PNG `tEXt` chunk
  - 关键字使用 `chara`，读取时优先兼容 `ccv3`
- `src/endpoints/characters.js`
  - 服务器端组装角色卡 JSON
  - 独立世界书转换为嵌入 `character_book` 的字段映射
- `src/endpoints/worldinfo.js`
  - 独立世界书文件要求至少包含 `entries`
- `public/scripts/world-info.js`
  - 世界书 entry 的默认字段
  - 插入位置枚举
  - `character_book` 转回前端世界书结构时的字段映射
- `public/scripts/char-data.js`
  - `data.extensions`、`character_book` 等扩展数据说明

### Tavo APK 源码依据（逆向分析）

在 Tavo 自身功能方面，以下 APK 内文件是**权威参考**，优先级高于任何二手教程：

| 文件 | 路径 | 用途 |
|------|------|------|
| **sandbox.js** | `/assets/flutter_assets/assets/dist/js/sandbox.js` | **JS API 精确实现**（约 15KB minified）。所有 `window.tavo.*` 方法的真实行为、字段转换规则（`o()` / `i()` / `t()` / `c()` / `w()`）、超时机制均以此为准 |
| **models.json** | `/assets/flutter_assets/assets/registry/models.json` | 内置模型注册表（**193 个模型**、9 个平台 key：openai 39 / vertex 59 / vertex_popular 7 / doubao 28 / grok 17 / claude 15 / gemini 13 / openrouter_popular 9 / deepseek 6）。每个模型必有 `id` / `name` / `owned_by`；约 22% 含 `context_length` + `pricing`；约 5% 含完整 `capabilities` 对象 |
| **manifest.json** | `/assets/flutter_assets/assets/registry/manifest.json` | 注册表版本元数据（最近实测 version `0.5.5`） |
| **bundle.min.js** | `/assets/flutter_assets/assets/dist/js/bundle.min.js` | 聊天渲染引擎（lodash + Tav 自定义渲染逻辑） |
| **index.html** | `/assets/flutter_assets/assets/dist/index.html` | WebView 入口，展示了消息气泡的 DOM 结构 |
| **libapp.so** | `/lib/arm64-v8a/libapp.so` | Dart AOT 编译的核心逻辑，包含全部 75K+ 运行时字符串 |
| **图标资源** | `/assets/flutter_assets/assets/images/icon_*.png` | 平台 / 模型能力 / TTS 平台图标——常用作"功能存在性"实证 |

当 Tavo 官方文档与 sandbox.js 冲突时，**以 sandbox.js 为准**——它是实际运行的代码。

### APK 提取与核对方法（最近一次：2026-05-05）

```bash
# 1. 从 root 模拟器拉 APK
adb shell pm path app.bitbear.tav   # 输出 base.apk 路径
adb pull '<上一步路径>' tavo.apk

# 2. 解压
unzip -oq tavo.apk -d apk-extracted

# 3. 关键文件
apk-extracted/assets/flutter_assets/assets/dist/js/sandbox.js
apk-extracted/assets/flutter_assets/assets/registry/{models.json,manifest.json}
apk-extracted/assets/flutter_assets/assets/images/icon_*.png
apk-extracted/lib/arm64-v8a/libapp.so

# 4. libapp.so 字符串提取
strings apk-extracted/lib/arm64-v8a/libapp.so | grep -E '<i18n_key_prefix>'
```

### Tavo ObjectBox 数据模型（已确认实体摘录，表内 30 项）

以下是当前 skill 已在 APK 字符串中确认并整理出的实体/关系类名称摘录，理解这些有助于判断"什么数据存哪里"。不要把此表当成已穷尽 schema dump：

| 类别 | 实体 |
|------|------|
| 角色与对话 | `Character`, `Conversation`, `Message`, `Persona`, `User` |
| 预设与配置 | `Preset`, `Lorebook`, `LorebookState`, `Regex`, `RegexConversationRef` |
| AI 端点 | `Endpoint`, `LoadBalancer`, `LoadBalancerLog` |
| TTS | `TtsEndpoint`, `TtsCharacterRef` |
| 设置 | `ModelSetting`, `ConversationSettings`, `ConversationState` |
| UI | `ChatTheme`, `RenderingSettings`, `MiscSettings`, `VisualSettings`, `ImgcapSettings`, `LtmSettings` |
| 系统 | `Ctxlog`, `GlobalState`, `DatabaseVersion`, `Default` |
| 关联 | `NullableChatThemeRef`, `ConversationNullableChatThemeRef` |

## 本地样例

如果当前工作区存在类似文件，它们是可参考的本地成功样本：

- `examples/<character>.card.json`
- `examples/<character>.card.png`
- `examples/<character>.worldbook.json`
- `examples/<character>.worldbook.multi-entry.json`

使用这些样例时：

- 学结构，不要机械照抄内容
- 优先复用字段组织方式
- 如果用户想做同类“角色卡 + 世界书联动”，可以参考它把独立世界书同时嵌入到 `data.character_book`
