# search4all —— Claude Code 插件

让 Claude Code 在遇到生信问题时直接检索实验室内部知识库，并把来源带回来。

> v2.0.0 起改成**远端 MCP 服务**：本机不装任何东西，不再需要 python3。
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
| 服务地址 | `https://search.092420.xyz`（**末尾不要加 `/mcp`**，插件自己拼） |
| API Key | 登录搜索页 → 右上角「🔐 API Key」→ 生成。`s4a_` 开头，**只显示一次** |

API key 与网页登录**互相独立**：你在网页端重新登录不会让插件掉线，插件也不占用网页会话。
key 丢了找不回来（服务端只存哈希），只能吊销后重发。它是敏感项，Claude Code 会把它单独
存进 `.credentials.json` 的 `pluginSecrets`，不写进 `settings.json`。

验证装好了：

```bash
claude mcp get plugin:search4all:search4all
```

应当看到 `Status: ✔ Connected`、`Type: http`、`URL: https://search.092420.xyz/mcp`。

## 提供的工具

| 工具 | 用途 |
|---|---|
| `search_library` | 检索知识库，返回答案 + 编号来源。连续提问自动接成追问 |
| `list_libraries` | 列出当前 key 能看到的库 |
| `get_entity` | 读知识 Wiki 里某实体的完整研究页 |
| `memory_recent` / `memory_search` / `memory_thread` | 调取本账号跨机器的历史对话 |
| `list_skills` / `get_skill` / `find_skill` | 账号下的 skill（网站「Skill」板块管理） |

两个 skill：`search4all`（什么时候该查库、怎么追问、怎么翻记忆）和
`search4all-sync`（把账号里的 skill 同步到本机，让客户端原生加载）。

**工具和 skill 两样都要**——只装工具的话模型经常想不起来用，照样去公网搜。

## 环境要求

无。v1.x 需要本机 `python3`（插件里带一个 stdio server），v2.0.0 之后不需要了。

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
| 提示「没有展开 `${...}` 占位符」 | 客户端没做配置插值。走 `/plugin` 配置的正常不会出现；出现了说明配置是手写进 `.mcp.json` 的 |
| `Status: ✘` 连不上 | 服务地址填错（检查末尾是不是多写了 `/mcp`），或不在实验室网络内 |
| 「额度或并发受限」 | 今日额度用尽，或你有请求还在跑（默认并发 2） |
| 工具压根没出现 | `claude mcp get plugin:search4all:search4all` 看状态，或 `claude --debug` 查启动日志 |

## 从 1.x 升级

1.x 是本地 stdio（插件里带一个 `mcp/server.py`）。`/plugin update search4all@issushow` 即可，
原有两项配置会沿用、不用重填——但**服务地址如果还是老的内网 `http://x.x.x.x:8800`，
要改成 `https://search.092420.xyz`**。升级后本机不再启动 python 进程。
