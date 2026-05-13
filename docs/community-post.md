# Community Post Draft

## 中文

我做了一个非官方的 Tavo Studio Kit，主入口是一个 Tavo Studio skill，旁边带了一个本地 Dev Kit。

它主要解决一个问题：AI 帮我写 Tavo 脚本、正则、角色卡、世界书、预设之后，我想知道它到底能不能跑。

它现在能做：

- 用 skill 帮 AI 理解 Tavo/ST 角色卡、世界书、预设、正则、宏、长记忆、高级前端渲染和 JS API 的边界。
- 生成 Tavo 可导入的角色卡、世界书、正则、预设和 AR HTML。
- 提供 `tavo.*` 的 TypeScript 类型提示。
- 提供本地 mock，可以先跑单元测试。
- 提供 AR widget 分文件模板，并打包成 Tavo 可用的单文件 HTML。
- 维护者如果有设备环境，也可以额外跑真实 App probe。

注意：

- 这不是官方 SDK。
- mock 不等于真实 Tavo。
- 普通用户不需要安卓模拟器；真实 App probe 是可选高级验证。

适合：

- 经常让 AI 写 Tavo 脚本的人。
- 想把“看起来能用”变成“跑过测试”的人。
- 想做可重复验证的角色卡/世界书/正则/AR 组件的人。

## English

I built an unofficial Tavo Studio Kit. The main entry is a Tavo Studio skill, with a local Dev Kit as the auxiliary validation tool.

It helps agents understand Tavo/ST creation boundaries, generate importable Tavo assets, test AI-written scripts against a local mock `tavo` API, and build standalone Advanced Rendering widgets. A real-app probe is available for maintainers who already have an emulator setup.

Current highlights:

- TypeScript types for official-style `tavo.*` scripts
- local `createMockTavo()` runtime for tests
- importable character card, worldbook, regex, preset, AR direct HTML, and AR widget HTML generation
- split-file AR widget template builder
- optional real-app probe for maintainers

Important boundaries:

- not official
- mock behavior is not the real app
- emulator testing is optional and not required for normal use
