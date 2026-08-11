# search4all —— Claude Code 插件

让 Claude Code 在遇到生信问题时直接检索实验室内部知识库，并把来源带回来。

> 用 Codex 而不是 Claude Code？看 [CODEX_SETUP.md](./CODEX_SETUP.md)。

## 安装

```bash
# 1. 添加 marketplace
/plugin marketplace add awaragml00029-debug/search4all-plugin

# 2. 安装
/plugin install search4all@issushow
```

启用时会弹出两项配置：

| 配置 | 说明 |
|---|---|
| 服务地址 | search4all 网关地址，如 `http://10.0.0.5:8800` |
| API Key | 登录搜索页 → 右上角「🔐 API Key」→ 生成。`s4a_` 开头，**只显示一次** |

API key 与网页登录**互相独立**：你在网页端重新登录不会让插件掉线，插件也不占用网页会话。
key 丢了找不回来（服务端只存哈希），只能吊销后重发。

## 提供的工具

| 工具 | 用途 |
|---|---|
| `search_library` | 检索知识库，返回答案 + 编号来源。可选 `libraries` 限定范围、`web` 叠加公网 |
| `list_libraries` | 列出当前 key 能看到的库及 id |
| `get_entity` | 读知识 Wiki 里某个实体的完整研究页 |

同时附带一个 skill，告诉模型什么时候该优先查内部库而不是公网。

## 环境要求

只需要 `python3`（3.8+），无第三方依赖。MCP server 是标准库手写的，不必装 `mcp` SDK 或 `uv`。

## 额度

调用消耗账号的日额度，`web: true` 更贵，深度研究类操作最贵。额度用尽会返回 429，
剩余额度可在搜索页右上角「🔐 API Key」面板里看。

## 关于权限（重要）

**这个插件不会、也无法修改你的 Claude Code 权限设置。**

Claude Code 的插件清单（`plugin.json`）没有 `permissions` 字段——权限规则只存在于
settings.json 的层级里（Managed > User > Project），插件写不进去。插件能做的只有：

- 提供工具（MCP server）和指导（skill）
- 如果捆绑了 hooks，可以**限制**工具调用（`PreToolUse` 返回 `deny`）；但 hook 的
  `allow` 也不能覆盖你已有的 deny 规则

本插件没有捆绑任何 hooks，不拦截任何工具调用。

服务端才是真正的边界：所有额度、并发、库可见性的限制都在 search4all 后端按 API key
执行，禁用或卸载插件不会绕过它们。

## 排查

| 现象 | 原因 |
|---|---|
| 「鉴权失败」 | key 被吊销、或账号被停用。重新生成一个 |
| 「连不上 search4all」 | 服务地址填错，或不在实验室网络内 |
| 「额度或并发受限」 | 今日额度用尽，或你有请求还在跑（默认并发 2） |
| 工具压根没出现 | `python3` 不在 PATH。`claude plugin validate` 看详情，或 `claude --debug` 查 MCP 启动日志 |
