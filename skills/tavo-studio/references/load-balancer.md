# Tavo 负载均衡器总结

## 1. 这是什么

负载均衡器（Load Balancer）是 Tavo 用来在多个人工智能提供商（API 端点）之间自动分发请求的系统。它的核心目的是：

- 当一个 API 不可用或限流时，自动切换到备选
- 按策略在不同模型/提供商之间分配请求
- 降低单点故障风险
- 通过权重/轮换等方式分散成本、配额和可用性风险

## 2. 核心实体

经逆向分析确认，Tavo 的 ObjectBox 数据库中包含三个负载均衡相关实体：

| 实体 | 说明 |
|------|------|
| `LoadBalancer` | 负载均衡器配置（名称、策略、关联端点列表） |
| `LoadBalancerLog` | 请求分发日志（记录每次请求被路由到哪个端点） |
| `LoadBalancerStrategy` | 分发策略枚举 |

## 3. 策略类型

从 libapp.so 字符串确认的 4 种策略（来源：`load_balancer_strategy_round_robin`、`load_balancer_strategy_weighted`、`load_balancer_strategy_random`、`load_balancer_strategy_lru`）：

| 策略 | 标识符 | 说明 |
|------|--------|------|
| 轮询 | `round_robin` | 按顺序依次分发请求到各端点 |
| 加权 | `weighted` | 按端点权重比例分发 |
| 随机 | `random` | 随机选择可用端点 |
| LRU | `lru` | 最近最少使用（Least Recently Used），优先选最久未用的端点 |

## 4. 访问入口

### UI 路径

1. 打开左侧边栏
2. 更多 → 设置
3. 找到"负载均衡器"或"Load Balancer"

### Deep Link

```
tav://tavo/load_balancers/
```

可通过此 URL scheme 直接跳转到负载均衡器管理页面。

## 5. 负载均衡日志

`LoadBalancerLog` 实体的具体字段未从 ObjectBox schema dump 直接确认，**以下为按通用日志结构推断**（实际字段以 APK 内 schema 为准）：

- 请求时间
- 目标端点
- 成功/失败状态
- 响应延迟
- 错误信息（如有）

**libapp.so 实证可见的日志相关 i18n 键**：

| i18n key | 含义 |
|----------|------|
| `load_balancer_log` / `load_balancer_log_title` | 日志页入口与标题 |
| `load_balancer_log_size` | 当前日志体积 |
| `load_balancer_log_today_request` | 今日请求计数 |
| `load_balancer_log_total_request` | 累计请求计数 |
| `load_balancer_log_available_api` | 可用 API 数量 |
| `load_balancer_log_none` / `_none_info` | 空日志提示 |
| `load_balancer_max_log_size` / `_info` | 日志容量上限设置 |

日志可在"存储空间"页面中清理（与其他日志一起）。

## 5.1 重试与权重配置

libapp.so 还实证了几个均衡器配置项，与策略字段配合使用：

| i18n key | 含义 |
|----------|------|
| `load_balancer_max_retries` / `_info` | 单次请求最大重试次数 |
| `load_balancer_max_log_size` / `_info` | 日志保留上限 |
| `load_balancer_weight` / `_info` | 单条目权重（仅在 `weighted` 策略下生效） |
| `load_balancer_edit_entries` | 均衡组里的条目集合（一组 Endpoint） |
| `load_balancer_edit_options` | 均衡器选项（策略+重试+日志容量等） |
| `load_balancer_edit_name_prefix` | 命名前缀（创建均衡器时） |
| `load_balancer_explain` | 给用户的功能说明文案 |

## 6. 与端点管理的关系

负载均衡器依赖于 API 端点：

1. 先在"端点管理"中配置各个 AI 提供商（OpenAI、Claude、Gemini 等）
2. 再创建负载均衡器，将多个端点加入
3. 设置分发策略
4. 在聊天中选择负载均衡器作为"模型"

负载均衡器在聊天层面表现为一个"虚拟模型"——用户选择它，由系统决定实际调用哪个端点。

## 7. 适合的使用场景

- **高可用**：主 API 不稳定时按策略切换备选（依赖 `LoadBalancerStrategy` 与 `load_balancer_max_retries`）
- **成本与配额平衡**：用 `weighted` 策略偏向便宜端点，配额耗尽再走贵端点
- **同类端点轮换**：把请求/响应语义可互换的端点放进同一个均衡组
- **轮换与去抖**：`round_robin` / `lru` / `random` 用来分散请求

> ⚠️ libapp.so 字符串里**只有** `round_robin / weighted / random / lru` 四个策略 + 各自的 `*_desc` 描述键，**没有** geo/region/latency/nearest 类策略。"自动选择最近端点 / 跨国低延迟" 这种用法不在已知策略范围内——要做地理路由只能手动给不同地区配置不同均衡组并手动切。
> ⚠️ 负载均衡器也不是协议适配器。不要默认把 OpenAI 协议端点和 Anthropic 协议端点混进同一组，除非你已经验证它们在 Tavo 这一调用路径下请求格式、响应格式、模型能力和语义都可互换。

## 8. 注意事项

- 负载均衡器本身不存储 API key，它复用已配置端点的密钥
- 日志会增长，建议定期清理
- 如果均衡组内所有端点都不可用，聊天会报错并提示
- 负载均衡器主要用于聊天文本生成请求；TTS 走 `TtsEndpoint`、图片理解走独立的多模态端点（属于不同的端点体系，未观察到走 `LoadBalancer` 的证据）
- 如果用户目标是“跨区域低延迟”，只能建议手动建立按地区分组的端点/均衡组；不要说 Tavo 会自动按延迟或地理位置选择

## 9. 来源

- APK 逆向分析：ObjectBox 数据库实体列表
- libapp.so 字符串提取：`LoadBalancer`、`LoadBalancerLog`、`LoadBalancerStrategy`；策略字符串 `load_balancer_strategy_round_robin`、`load_balancer_strategy_weighted`、`load_balancer_strategy_random`、`load_balancer_strategy_lru`
- APK AndroidManifest：`tav://tavo/load_balancers/` deep link
