# Tavo API 端点（Endpoint）总结

本文档基于 APK 实证：libapp.so 字符串、`assets/.../registry/{models.json,manifest.json}`、`assets/.../images/icon_platform_*.png`。

## 1. 这是什么

`Endpoint` 是 Tavo 用来管理"模型 API 接入"的实体。一个 Endpoint = "一个可调用的模型实例"，绑定的字段包括：

- 平台（OpenAI / Claude / Gemini / DeepSeek / Grok / Vertex AI / OpenRouter / 协议系兼容层 / 代理类平台）
- API base URL
- API secret（密钥）
- 模型 ID
- 模型平台 / 模型能力位
- Vertex AI 还多一组：region、project_id、auth_method、json_secret

负载均衡器（`LoadBalancer`）就是把多个 Endpoint 组合起来的虚拟分发层。

## 2. 平台总览（15 个逻辑平台 / 16 个图标资源）

经实证 `assets/flutter_assets/assets/images/icon_platform_*.png` 共有 **16 个图标资源**，但其中 `icon_platform_poprouter_dark` 只是 PopRouter 的深色主题图标，不是独立平台。因此可选平台按 **15 个逻辑平台** 记，按性质分四类：

### 2.1 直连原生平台（6 个）

| 平台 | 图标 | 说明 |
|------|------|------|
| OpenAI | `icon_platform_openai` | 直连 OpenAI 官方 API |
| Claude（Anthropic） | `icon_platform_claude` | 直连 Anthropic API |
| Gemini | `icon_platform_gemini` | 直连 Google AI Studio Gemini API |
| Vertex AI | `icon_platform_vertex_ai` | Google Cloud Vertex AI（多区域 + 服务账号认证） |
| DeepSeek | `icon_platform_deepseek` | 直连 DeepSeek API |
| Grok | `icon_platform_grok` | 直连 xAI Grok API |

> 直连证据：本地化串 `Create a direct model API connection`、西语 `directamente desde tu dispositivo al proveedor de IA que hayas configurado (p. ej., OpenAI, Google, OpenRouter)`。Tavo 默认按"设备 → 提供商"直连，密钥保存在本地。

### 2.2 协议系通用兼容层（3 个）

| 协议 | 图标 | 说明 |
|------|------|------|
| OpenAI 协议 | `icon_platform_openai_protocol` | 兼容 OpenAI 协议的自建/第三方端点 |
| Anthropic 协议 | `icon_platform_anthropic_protocol` | 兼容 Anthropic 协议的端点 |
| Gemini 协议 | `icon_platform_gemini_protocol` | 兼容 Gemini 协议的端点 |

这三类是“自定义端点入口”，让用户填 base URL + 密钥接入，包括反向代理、Cloudflare Workers、One-API、newapi 等中转方案。这里的“兼容”必须按所选协议理解：路径、鉴权、流式/非流式响应和返回 JSON 结构都要像对应协议，Tavo 不会把任意非兼容 API 自动翻译成 OpenAI/Anthropic/Gemini 协议。

### 2.3 代理类平台（5 个）

| 代理 | 图标 | 说明 |
|------|------|------|
| OpenRouter | `icon_platform_openrouter` | 多家模型聚合中转 |
| Volink | `icon_platform_volink` | Tavo 自家代理（同时也是 TTS 代理选项） |
| MantleAI | `icon_platform_mantleai` | 第三方代理 |
| PopRouter | `icon_platform_poprouter` / `icon_platform_poprouter_dark` | 第三方代理（第二个是深色主题图标，不算独立平台） |
| TinyRouter | `icon_platform_tinyrouter` | 第三方代理 |

> Volink 不是默认中转，更不是必选——它只是众多可选代理之一。SKILL.md 早期曾把端点描述得像"所有请求都走 Volink"，已改正。

### 2.4 元入口（1 个）

| 入口 | 图标 | 说明 |
|------|------|------|
| Load Balancer | `icon_platform_load_balancer` | 负载均衡器作为"虚拟模型"出现在端点列表里，详见 [load-balancer.md](load-balancer.md) |

## 3. Endpoint 编辑字段

来自 libapp.so 的 `endpoint_edit_*` 字符串：

### 3.1 通用字段

| 字段 i18n key | 用途 |
|---------------|------|
| `endpoint_edit_name` | 端点名称 |
| `endpoint_edit_model_platform` | 选择模型平台（即上面 15 个逻辑平台之一） |
| `endpoint_edit_api_base_url` | API base URL |
| `endpoint_edit_api_secret` | API 密钥 |
| `endpoint_edit_api_china_mainland` | 中国大陆访问标记（可能影响 base URL 或代理选择） |
| `endpoint_edit_test_connections` | 测试连接 |
| `endpoint_edit_api_get_secret` | "如何获取密钥"链接 |

### 3.2 模型字段

| 字段 i18n key | 用途 |
|---------------|------|
| `endpoint_edit_model` | 模型 ID |
| `endpoint_edit_select_chat_model` | 选择聊天模型 |
| `endpoint_edit_model_capable` | 模型能力位（详见 §4） |

### 3.3 Vertex AI 专属字段

| 字段 i18n key | 用途 |
|---------------|------|
| `endpoint_edit_auth_method` | 认证方式 |
| `endpoint_edit_auth_method_vertext_express` | "Vertex Express"快速认证（拼写就是 vertext） |
| `endpoint_edit_auth_method_vertext_full` | "Vertex Full"完整服务账号认证 |
| `endpoint_edit_json_secret` | JSON 密钥（服务账号 JSON） |
| `endpoint_edit_project_id` | GCP project ID |
| `endpoint_edit_region` | Vertex 区域选择 |
| `endpoint_edit_vertex_ai_regio_*` | 30 个具体区域键，详见 §5 |

## 4. 模型能力位

来自 libapp.so 字符串 + `icon_model_capable_*.png` 资源：

### 4.1 用户可编辑的能力位（6 个）

`endpoint_edit_model_capable_*` 显示 6 个能编辑的能力位：

- `cache` — 提示词缓存
- `code` — 代码解释器 / Code interpreter
- `function` — Function calling
- `image` — 图片输入（多模态识图）
- `reasoning` — 推理（reasoning effort）
- `structure` — 结构化输出

### 4.2 仅显示的能力位（再 + 2 个）

`assets/.../images/icon_model_capable_*.png` 还有：

- `asr` — 语音转文字
- `tts` — 文字转语音

这两个有图标资源但 `endpoint_edit_*` 里没有对应键，说明它们未出现在已知端点编辑开关中；通常由模型注册表自带的 `capabilities` 字段决定。

### 4.3 实证：注册表里 `capabilities` 字段示例

仅 9 个模型（多数在 `openrouter_popular` 里）含完整 `capabilities` 块，例如：

```json
{
  "id": "anthropic/claude-sonnet-4.6",
  "capabilities": {
    "reasoning": true,
    "function_call": true,
    "caching": true,
    "structured_output": true,
    "code_interpreter": false,
    "tts": false,
    "asr": false,
    "image_generation": false
  }
}
```

注意键名比 UI 编辑位多了 `image_generation`、并把 `code` 写成 `code_interpreter`、`function` 写成 `function_call`、`structure` 写成 `structured_output`、`cache` 写成 `caching`。

## 5. Vertex AI 区域（30 个）

`endpoint_edit_vertex_ai_regio_*`（注意拼写是 `regio` 而不是 `region`）：

```
亚太：asia_east1 / asia_east2 / asia_northeast1 / asia_northeast3 /
      asia_south1 / asia_southeast1 / australia_southeast1
欧洲：europe_central2 / europe_north1 / europe_southwest1 /
      europe_west1 / europe_west2 / europe_west3 / europe_west4 /
      europe_west6 / europe_west8 / europe_west9
中东：me_central1 / me_central2 / me_west1
北美：northamerica_northeast1 /
      us_central1 / us_east1 / us_east4 / us_east5 /
      us_south1 / us_west1 / us_west4
南美：southamerica_east1
全球：global
```

> 这只是 Vertex 端点本身可选的接入区域，**不是**负载均衡器的 geo-routing 策略——负载均衡器只有 `round_robin / weighted / random / lru` 四个策略，没有 geo/latency 路由（详见 [load-balancer.md](load-balancer.md)）。

## 6. 内置模型注册表

`assets/flutter_assets/assets/registry/`：

- `manifest.json` — 注册表版本和 sha256（实测版本 `0.5.5`，文件大小 31354 字节）
- `models.json` — **193 个模型**，按平台分组：

| 平台 key | 模型数 | 说明 |
|---------|--------|------|
| `openai` | 39 | |
| `vertex` | 59 | Vertex AI |
| `vertex_popular` | 7 | Vertex 热门子集 |
| `doubao` | 28 | 字节豆包/火山云 |
| `grok` | 17 | xAI |
| `claude` | 15 | Anthropic |
| `gemini` | 13 | Google AI Studio |
| `openrouter_popular` | 9 | OpenRouter 热门 |
| `deepseek` | 6 | |
| **合计** | **193** | |

### 6.1 模型对象字段

每个模型必有：`id`、`name`、`owned_by`。

可选附加字段（**不是所有模型都有**）：

| 字段 | 出现率 | 说明 |
|------|--------|------|
| `context_length` | 43/193（22%） | 上下文长度（token） |
| `pricing` | 43/193（22%） | `{prompt, completion}` 单价（USD/token） |
| `capabilities` | 9/193（5%） | 完整能力位对象 |

> 早期描述说"含定价和上下文长度"会让人误以为所有模型都有，实际只有约 1/5 的模型带定价和上下文。

### 6.2 真实模型示例（取自 registry）

**简化版（仅 id/name/owned_by）**：

```json
{ "id": "gpt-5.5", "name": "GPT-5.5", "owned_by": "Recently Popular" }
```

**带定价的（如 Claude）**：

```json
{
  "id": "claude-opus-4-7",
  "name": "Claude Opus 4.7",
  "owned_by": "Recently Popular",
  "context_length": 1000000,
  "pricing": { "prompt": "0.000005", "completion": "0.000025" }
}
```

## 7. 端点 warning 相关 key（19 个；约 17 个错误分类）

APK 中共有 **19 个唯一 `endpoint_warning_*` key**。其中 `endpoint_warning_view_details` 是"查看详情"按钮，`endpoint_warning_wrong_url_detail` 是 `wrong_url` 的详情文本；如果只按错误分类算，约为 **17 类**。这些分类对调试端点请求很有用：

| i18n key | 含义 |
|----------|------|
| `endpoint_warning_busy` | 服务繁忙 |
| `endpoint_warning_empty_response` | 响应为空 |
| `endpoint_warning_geo_restricted` | 地区受限（仅个别模型/平台） |
| `endpoint_warning_invalid_secret` | 密钥无效 |
| `endpoint_warning_malformed_response` | 响应格式异常 |
| `endpoint_warning_model_inactive` | 模型未启用 |
| `endpoint_warning_model_not_found` | 模型不存在 |
| `endpoint_warning_multimodal_required` | 当前操作需要多模态模型（如图片发送） |
| `endpoint_warning_network_error` | 网络错误 |
| `endpoint_warning_no_available_endpoint` | 无可用端点（例如均衡组全挂） |
| `endpoint_warning_other_error` | 其它错误 |
| `endpoint_warning_partner_high_cost_warning` | 高成本警告（特定合作平台） |
| `endpoint_warning_prohibited_content` | 内容被拒（违规） |
| `endpoint_warning_quota_exhausted` | 配额耗尽 |
| `endpoint_warning_server_error` | 上游服务器错误 |
| `endpoint_warning_unknown_error` | 未知错误 |
| `endpoint_warning_view_details` | 查看详情按钮（UI 文案，不是错误分类） |
| `endpoint_warning_wrong_url` | URL 错误（base URL 不对） |
| `endpoint_warning_wrong_url_detail` | URL 错误详情文案（归入 `wrong_url`） |

> 注意 `geo_restricted` 是**端点请求级别**的"地区被服务方拒绝"，和负载均衡的 geo-routing 不是一回事。

## 8. 端点管理界面字符串

`endpoint_list_*`、`endpoint_manage_*`：

- `endpoint_list` — 端点列表页
- `endpoint_list_set_default_hint` — 设置默认端点
- `endpoint_list_hint_delete_api` / `_load_balancer` — 删除端点 / 删除均衡器的提示
- `endpoint_manage_creation_endpoint` / `_desc` — "创建普通端点"入口
- `endpoint_manage_creation_load_balancer` / `_desc` — "创建负载均衡器"入口
- `endpoint_manage_creation_title` — 创建页面标题
- `endpoint_manage_hint_none_data` / `endpoint_manage_none_data` — 空列表提示

## 9. 与其他能力的关系

- **角色卡聊天**：每个聊天可绑定一个 Endpoint 作为生成模型；可被 LoadBalancer 这个"虚拟端点"替代
- **图片发送**：要求所选 Endpoint 的 `image` 能力位为 true（即多模态模型）
- **TTS**：完全独立于普通 Endpoint，走 `TtsEndpoint`（详见 [tts.md](tts.md)）
- **JS API**：`tavo.generate(prompt, options)` 默认用当前聊天绑定的 Endpoint；`options.preset` 可指定预设但不能切端点
- **备份**：备份文件可选择是否包含 Endpoint 的 API 密钥；包含密钥的备份要按敏感文件处理

## 10. 后续配置时记住的点

- 默认走直连，密钥本地保存；只有显式选了代理类平台才中转
- Vertex AI 用 Express 模式时不需要服务账号 JSON，用 Full 模式才需要 `endpoint_edit_json_secret`
- 模型注册表只是“内置候选”，不是硬限制；协议系平台 + 自定义 base URL 可以填写该端点实际支持、且响应格式兼容所选协议的模型 ID
- 模型能力位会影响 UI 行为（图片发送要求 image 位、reasoning 控制台要求 reasoning 位等）；在用自建端点时如果 Tavo 不知道能力位，要在端点编辑里手动勾选，但勾选只代表告诉 Tavo“尝试这样调用”，不证明上游模型真的支持
- 端点错误时优先看 `endpoint_warning_*` 分类，不要笼统说"不能连"

## 11. 来源

- APK 字符串：libapp.so（arm64-v8a）`endpoint_*`、`load_balancer_*`、`icon_*`、本地化串
- APK 资源：`assets/flutter_assets/assets/images/icon_platform_*.png`、`icon_model_capable_*.png`
- APK 注册表：`assets/flutter_assets/assets/registry/manifest.json`（version 0.5.5）+ `models.json`（193 模型）
- sandbox.js（不在本文档范围内，端点级 API 没有 JS 绑定，只能通过 Flutter 原生层操作）
