# Tavo TTS（文字转语音）总结

## 1. 这是什么

Tavo 的 TTS 系统用于把聊天中的可播放文本转换为语音播放。它不只是一对一的文字朗读，而是一套多平台、多语言的语音合成生态，同时支持第三方 TTS 代理平台。

## 2. TTS 平台总览

经 APK 实证（图标资源 `assets/.../images/icon_tts_platform_*.png` + libapp.so 字符串），Tavo 在 UI 平台层级目前能列出 **13 个 TTS 平台图标**：

| 平台 | 类型 | 图标资源 | 说明 |
|------|------|----------|------|
| Android 系统 TTS | 系统内置 | `icon_tts_platform_android_system` | 调用 Android 默认 TTS |
| Google 系统 TTS | 系统内置 | `icon_tts_platform_google_system` | `com.google.android.tts` |
| Google Gemini TTS | AI 模型 | `icon_tts_platform_google_gemini` | 通过 Gemini 生成语音 |
| ElevenLabs | 第三方 API | `icon_tts_platform_elevenlabs` | 高品质 AI 语音合成 |
| MiniMax | 第三方 API | `icon_tts_platform_minimax` | MiniMax TTS API |
| Honor（荣耀）系统 TTS | 厂商内置 | `icon_tts_platform_honor_system` | `com.hihonor.voiceengine` |
| Huawei（华为）系统 TTS | 厂商内置 | `icon_tts_platform_huawei_system` | `com.huawei.hiai` |
| Vivo 系统 TTS | 厂商内置 | `icon_tts_platform_vivo_system` | 多个 vivo agent 包名 |
| Xiaomi（小米）系统 TTS | 厂商内置 | `icon_tts_platform_xiaomi_system` | `com.xiaomi.mibrain.speech` |
| iFlytek（讯飞）系统 TTS | 厂商内置 | `icon_tts_platform_iflytek_system` | `com.iflytek.speechcloud` 等 |
| iOS 系统 TTS | 系统内置 | `icon_tts_platform_ios_system` | iOS 端入口；Android APK 仅证明资源被打包 |
| **Multi-System（通用 Android TTS）** | 元入口 | `icon_tts_platform_multi_system` | 用任意已安装的 Android TTS 引擎，下面挂多个 `tts_engine_name_*` |
| Volink | 代理 | `icon_tts_platform_volink` | Tavo 自家代理（同时也算文本 API 代理） |

> ⚠️ "11 个平台" 是早期不完整的归类。实证更新：**13 个 UI 平台图标**（含 Multi-System 这个元入口和单独成图标的 Volink）。

### Multi-System 下能挂的具体引擎（来自 libapp.so 的 `tts_engine_name_*` 字符串）

```
baidu_duer / bishuge / honor / honor_ai / huawei
iflytek / iflytek_cloud / iflytek_tts / iflytek_vflynote
vivo_agent / vivo_base_agent / vivo_service / xiaomi
```

Multi-System 实际上是个 "通用 Android TTS 引擎选择器"——它把已安装的 TTS 引擎包（如 `com.github.jing332.tts_server_android`、百度 DuerOS 的 `baidu_duer`、`bishuge` 等）按包名识别后允许选用。所以**真正可用的引擎数量取决于设备上装了哪些 TTS APP**，不是固定 N 个。

### Multi-System 实证可识别的引擎包名（11 个）

来自 libapp.so 字符串：

| 包名 | 厂商/项目 |
|------|----------|
| `com.baidu.duersdk.opensdk` | 百度 DuerOS |
| `com.github.jing332.tts_server_android` | 开源项目 jing332/tts-server-android |
| `com.google.android.tts` | Google 系统 TTS |
| `com.hihonor.aipluginengine` | 荣耀 AI 插件引擎 |
| `com.hihonor.voiceengine` | 荣耀语音引擎 |
| `com.huawei.hiai` | 华为 HiAI |
| `com.iflytek.speechcloud` | 讯飞 SpeechCloud |
| `com.iflytek.speechsuite` | 讯飞 SpeechSuite |
| `com.iflytek.tts` | 讯飞通用 TTS |
| `com.vivo.aiservice` | vivo AI Service |
| `com.xiaomi.mibrain.speech` | 小米小爱语音 |

> iOS 系统 TTS 那条只能从图标资源命名看出来（`icon_tts_platform_ios_system.png` 在 Android APK 里也打包了），无法靠 Android APK 完全确认 iOS 端运行时表现，仅作"有此入口"参考。

## 3. TTS 代理平台

除直接 TTS 服务外，Tavo 还支持 4 个 **TTS 代理平台**，用于中转请求：

| 代理平台 | 原生通道名 | 说明 |
|----------|----------|------|
| **MantleAI** | `tavo_tts_mantleai` | TTS 代理平台 |
| **PopRouter** | `tavo_tts_poprouter` | TTS 代理平台 |
| **TinyRouter** | `tavo_tts_tinyrouter` | TTS 代理平台 |
| **Volink** | `tavo_tts_volink` | 与 AI 文本 API 共用 Volink 中转 |

这些代理平台的本质：它们将 TTS 请求转发到上游 TTS 提供商（如 ElevenLabs、MiniMax 等），中间做鉴权、计费和路由。

## 4. TTS 原生通道（Flutter Method Channel）

Tavo 内部使用以下原生方法通道处理 TTS：

- `tavo_tts_mantleai` — MantleAI TTS 路由
- `tavo_tts_poprouter` — PopRouter TTS 路由
- `tavo_tts_tinyrouter` — TinyRouter TTS 路由
- `tavo_tts_volink` — Volink TTS 路由
- `tavo_tts_get` — 通用 TTS 查询

## 5. TTS 语言支持

经逆向确认支持的语言包：

| 语言 | 图标资源 |
|------|---------|
| 中文 | `icon_tts_modle_language_chinese.png` |
| 英文 | `icon_tts_modle_language_english.png` |

> 注：图标文件名里 `modle` 是 APK 内的真实拼写（不是笔误转抄），引用时按实际名字写。

实际可用的语音语言取决于所选 TTS 平台的支持范围。

## 5.1 模型能力位中的 TTS / ASR

`assets/flutter_assets/assets/images/` 下还有两个模型能力位图标：

- `icon_model_capable_tts.png` — 模型自身具备 TTS 能力的标记位
- `icon_model_capable_asr.png` — 模型自身具备 ASR（语音转文字）能力的标记位

这两个能力位不出现在已知端点编辑开关里（`endpoint_edit_model_capable_*` 只有 6 个可编辑位：cache / code / function / image / reasoning / structure）。当前包体证据中，模型注册表的 `capabilities` 字段可见 `tts: bool / asr: bool`。详见 [endpoint.md §4](endpoint.md)。

## 6. TTS 端点管理

类似于 AI 文本端点的管理方式，TTS 也有独立的端点管理：

### TtsEndpoint 实体（ObjectBox）

| 字段 | 说明 |
|------|------|
| 平台 | 选择 TTS 平台（ElevenLabs / MiniMax / Google 等） |
| API 密钥 | 对应平台的认证密钥 |
| 语音 ID | 平台特定的语音标识符 |
| 语言 | 目标语音语言 |

### TtsCharacterRef 实体

`TtsCharacterRef` 是"角色 ↔ TTS 端点"的关联实体。从实体名和官方"角色语音绑定"页可确认：

- 一个角色可以绑定一个 TTS 端点
- 不同角色可以绑定不同的 TTS 端点（不同平台 / 不同声音）

> 语速、音调等具体参数是否随角色单独存储**未从字段层确认**——实际能配什么取决于所选 TTS 平台暴露的参数。"语音设置"页面观察到的开关都是全局的（自动播放、播旁白、播代码块、播标签、后台播放），未见角色级语速 / 音调字段。

### UI 路径

1. 左侧边栏 → 更多 → 设置
2. 聊天设置 → TTS 设置
3. 或端点管理 → TTS 端点管理

## 7. TTS 播放控制

从 UI 资源推断的播放功能：

- **播放/暂停**：气泡旁有 TTS 播放按钮（`bubble_icon_tts.png`）
- **旁白按钮**：消息旁有专门的小喇叭按钮（`icon_tts_speaker.png`），用于朗读旁白
- **加载动画**：`tts_playing_lottie.json` — TTS 播放时的 Lottie 动画
- **语音绑定**：`icon_tts_voices_binding.png` — 将语音绑定到角色的图标
- **语音加载**：`icon_tts_voices_loading.png` — 加载语音列表时的状态

## 8. ElevenLabs 集成细节

- API 端点：`https://api.elevenlabs.io`
- 官网：`https://elevenlabs.com/`
- 需要 API key 认证

## 9. MiniMax 集成细节

- API 端点：`https://api.minimax.io/v1` / `https://api.minimaxi.com/v1`
- 双域名支持（国际版 + 中国版）

## 10. 适合的使用场景

- **多角色不同声音**：为每个角色绑定不同的 TTS 平台和声音
- **语言适配**：中文角色用讯飞，英文角色用 ElevenLabs
- **成本控制**：日常用系统 TTS（免费），特殊场景用第三方高品质 TTS
- **离线使用**：部分系统 TTS 引擎可能支持离线语音包；是否可用取决于设备和已安装引擎，不是 Tavo 自身保证

## 11. 注意事项

- 第三方 TTS（ElevenLabs、MiniMax）需要单独申请 API key 并付费
- 系统 TTS 的音质取决于设备厂商和 Android 版本
- 华为/荣耀/vivo/小米的厂商 TTS 仅在对应品牌手机上可用
- TTS 代理平台的计费与 AI 文本 API 分开
- TTS 语音缓存可在"存储空间"页面清理

## 12. 来源

- APK 逆向分析：libapp.so 字符串提取（TTS 平台包名、API 端点、方法通道名）
- APK 资源文件：`icon_tts_*` 系列 PNG、`tts_playing_lottie.json`
- ObjectBox 实体：`TtsEndpoint`、`TtsCharacterRef`
- AndroidManifest：`AudioService` 音频服务声明
