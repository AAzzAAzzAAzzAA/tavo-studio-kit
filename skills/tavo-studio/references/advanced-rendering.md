# Tavo 高级前端渲染（Web）总结

## 1. 这是什么

高级前端渲染（Advanced Rendering，简称 AR）允许聊天气泡渲染常见 HTML 与 CSS 子集。它的核心意义是把原本普通的文本气泡，升级成可以做页面化展示的内容。

注意：Tavo 支持的是“聊天气泡内的 HTML/CSS 渲染”，不是把一整页网页原样丢进普通浏览器。复杂美化在浏览器里能显示，不代表在 Tavo 里一定能显示。

这意味着后续你可以在聊天里做：

- 富文本样式
- 更复杂的排版
- 图片展示
- 更像网页卡片、面板、仪表盘的 UI

## 2. 开启方式

文档给出的路径是：

1. 打开主界面
2. 左上角打开左侧边栏
3. 点击底部“更多”
4. 点击“设置”
5. 点击“高级前端渲染”
6. 打开“高级前端渲染”开关

## 3. 怎么使用

文档给出的基本用法是：

- 在聊天页改写任一气泡
- 在高级前端渲染开启后，把 HTML 内容粘贴进消息气泡
- 页面会尝试按 Tavo 渲染链路处理 HTML/CSS，而不是仅仅显示纯文本

官方示例表达了三种能力：

- 用 `<span style="color: red">` 改颜色
- 用 `<strong>` 做粗体
- 用 `<img src="...">` 显示图片

这说明 AR 至少支持：

- 基础 HTML 标签
- 内联样式
- 图片元素

## 4. 适合做什么

对后续和 Tavo 结合的玩法来说，AR 很适合这些方向：

- 角色状态面板
- 剧情章节卡片
- RPG HUD
- 任务清单
- 按钮风格的视觉展示；真实点击交互需要 JS 执行模式和 JS API 配合
- 图文混排角色介绍页
- 视觉化日志和报表

如果你后面要做“像网页一样的聊天气泡 UI”，这就是入口。

## 5. 和 JavaScript API 的关系

高级前端渲染主要负责“显示层”，而 JavaScript API 负责“逻辑层”。

一个高可玩性的组合通常是：

- AR 负责页面结构和样式
- JS API 负责读取变量、生成内容、操作输入框、管理角色/预设/世界书等

也就是说：

- AR = 前端渲染壳
- JS API = 交互与数据能力

## 6. 文档当前的边界

这个页面当前写得比较短，明确写出的只有：

- 开关路径
- HTML/CSS 渲染能力
- 一个简单 HTML 示例

页面里还有一个“JavaScript 支持”的标题，但当前文档正文没有继续展开说明。也就是说：

- AR 页面本身主要确认了 HTML/CSS 可用
- 具体 JavaScript 侧的能力，实际要看 `JavaScript API` 文档

## 7. Tavo 和普通浏览器的关键区别

包体里的 `assets/flutter_assets/assets/dist/js/bundle.min.js` 显示，Tavo 的消息渲染不是裸浏览器直接打开 HTML，而是：

```text
消息文本
  -> MarkdownConverter.convert()
  -> sandbox.render()
  -> DOMPurify.sanitize()
  -> 普通气泡或 iframe 沙盒
  -> Flutter WebView 展示
```

因此写 Tavo 美化时要按下面规则处理：

- 普通 HTML/CSS 会先经过 Markdown 转换，再进入安全净化。
- `<style>` 会被临时转成 `tav-escaped-style` 后再恢复，所以基础 CSS 可用，但不要依赖浏览器全局页面环境。
- `<script>` 和 `onclick`、`onload` 等事件属性会触发 JavaScript 检测；JS 能否执行取决于设置里的 JavaScript 执行模式。
- Tavo 有 `disabled`、`auto`、`codeblock`、`script`、`native` 五类 JS 执行模式；默认/关闭状态下不要假设 JS 会跑。
- `codeblock` 模式会查 `<pre>` 内容里是否包含 `html>`、`<html`、`<head`、`<body`。只有局部 `<div>...</div>` 的代码块可能不会被当成完整 HTML 沙盒执行。
- 沙盒 iframe 使用 `sandbox="allow-scripts allow-modals allow-same-origin"`，和普通网页环境仍然不同。
- 气泡有自己的宽度、字体、折行、滚动和高度计算；`100vh`、`position: fixed`、超宽绝对定位、复杂 overflow 容易显示异常。
- 包体提示 Flutter intrinsic layout 下 `vertical-align: baseline` 可能裁切或错位；图片、inline-block、inline SVG 异常时优先试 `vertical-align: bottom`。

这也是“浏览器能渲染，Tavo 里渲染不出来”的常见原因。

## 8. 推荐写法

### 轻量 HTML/CSS 气泡

优先使用一层唯一 class 包住全部内容，CSS 全部限定在这个 class 下，避免污染 Tavo 自己的气泡样式。

```html
<div class="my-tavo-card">
  <style>
    .my-tavo-card {
      box-sizing: border-box;
      width: 100%;
      max-width: 100%;
      overflow-wrap: anywhere;
    }

    .my-tavo-card * {
      box-sizing: border-box;
    }

    .my-tavo-card img {
      display: block;
      max-width: 100%;
      height: auto;
      vertical-align: bottom;
    }
  </style>

  <div class="panel">
    内容放这里
  </div>
</div>
```

### 需要 JavaScript 的气泡

如果要让 JS 稳定执行，不要只给一个局部片段。建议写成带 `<body>` 的完整片段，并确保 Tavo 设置里的 JavaScript 执行模式允许执行。

```html
<body>
  <div id="app">内容</div>

  <script>
    document.getElementById("app").textContent = "已执行";
  </script>
</body>
```

如果放在 Markdown 代码块里，优先使用：

````markdown
```html
<body>
  <div id="app">内容</div>
  <script>
    document.getElementById("app").textContent = "已执行";
  </script>
</body>
```
````

## 9. 常见踩坑清单

- 不要把普通网页的 `<html><head>...</head><body>...</body></html>` 当作唯一写法；普通美化通常只需要一个 scoped wrapper。
- 不要依赖页面级 `body`、`html`、`window.top`、`window.parent` 的普通浏览器行为；Tavo 沙盒会改写部分环境。
- 不要把 CSS 写成全局选择器，例如 `div { ... }`、`img { ... }`；用 `.my-tavo-card img { ... }`。
- 不要依赖外链字体、远程脚本、复杂第三方库；移动 WebView、网络权限和安全净化都会增加失败率。
- 不要用 `position: fixed` 做气泡内布局；优先用普通流、flex、grid。
- 不要让元素宽度超过气泡；给容器和媒体元素加 `max-width: 100%`。
- 不要用只在桌面浏览器稳定的新 CSS 特性做核心布局；Tavo 实际运行在移动端 WebView。
- 如果 JS 不执行，先检查 JavaScript 执行模式，再检查内容是否含 `<script>` 或完整 `<body>`/`<html>` 片段。
- 如果 HTML 直接显示成代码，先确认“高级前端渲染”已开启。
- 如果非标准标签不显示，检查设置里的“Show Non-Standard HTML Tags”（包体字符串确认存在）。

## 10. 适合后续开发/配置时记住的点

- AR 是构建视觉化聊天界面的展示能力
- 需要真实交互或读写状态时，再与 JS API 配合；纯美化优先不用 JS
- 当前官方文档对 JS 支持说明较少，做复杂功能时应同时参考 JS API 文档和包体里的 `sandbox.js`/`bundle.min.js`
- 如果只想做轻量美化，单用 scoped HTML/CSS 就已经够用
- 如果要交付给用户直接粘贴，优先给“无 JS 版本”；只有明确需要交互时才给 JS 版本
- 排查顺序：先确认 AR 开关，再确认 JS 执行模式，再看是否被 Markdown/DOMPurify/沙盒规则影响

## 11. 来源

- https://docs.tavoai.dev/guides/advanced-rendering/
- 包体证据：`assets/flutter_assets/assets/dist/js/bundle.min.js`
  - `MessageBubbleItem.build()`：消息内容先走 `markdownConverter.convert()`，再走 `sandbox.render()`
  - `Sandbox.render()`：存在 `disabled`、`auto`、`codeblock`、`script`、`native` 分支
  - `_purifyHtml()`：使用 `DOMPurify.sanitize(...)`
  - `_hasScript()`：检测 `<script>` 和 `onclick`/`onload` 等事件属性
  - `_getCodeblocks()`：代码块里需出现 `html>`、`<html`、`<head`、`<body` 才更可能进入代码块沙盒执行
  - `IframeBuilder`：iframe 使用 `sandbox="allow-scripts allow-modals allow-same-origin"`
