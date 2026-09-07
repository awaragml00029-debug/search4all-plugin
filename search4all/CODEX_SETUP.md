# 在 Codex 里接入 search4all

> v2.0.0 起改成**远端 MCP 服务**：本机不再装 python 脚本，配置里只有一个地址和一份凭据。
> 旧版那套「下载 server.py + 手写绝对路径进 config.toml」已作废，见文末「从 1.x 升级」。

## 前置：一样东西

**API Key**：登录搜索页 → 右上角「🔐 API Key」→ 生成，`s4a_` 开头。**只显示一次**。
它和网页登录是分开的，重新登录不会让它失效。

## 安装（三步）

### 1. 把 key 放进环境变量

Codex 从环境变量读凭据，**key 不会落进 `config.toml`**。写进你的 shell 配置让它长期生效：

```bash
# ~/.bashrc 或 ~/.zshrc
export SEARCH4ALL_API_KEY="s4a_你的key"
```

Windows PowerShell：

```powershell
[Environment]::SetEnvironmentVariable("SEARCH4ALL_API_KEY", "s4a_你的key", "User")
```

设完**重开一个终端**，`echo $SEARCH4ALL_API_KEY` 能打印出来再往下走。

### 2. 装插件

```bash
codex plugin marketplace add awaragml00029-debug/search4all-plugin
codex plugin add search4all@issushow
```

这一步同时装上两样东西：**三个检索工具**（MCP）和**一份使用指导**（skill，告诉模型什么时候该查库）。
两样都要——只有工具的话模型经常想不起来用，照样去公网搜。

### 3. 验证

```bash
codex mcp get search4all
```

应当看到：

```
transport: streamable_http
url: https://search.092420.xyz/mcp
bearer_token_env_var: SEARCH4ALL_API_KEY
```

然后开一个 Codex 会话，问一句本实验室库里才有的东西（例如「我们库里关于批次效应校正是怎么说的」），
它应该调 `search_library` 并带编号来源回来。

## 提供的工具

| 工具 | 用途 |
|---|---|
| `search_library` | 检索知识库，返回答案 + 编号来源。连续提问自动接成追问 |
| `list_libraries` | 列出当前 key 能看到的库 |
| `get_entity` | 读知识 Wiki 里某实体的完整研究页 |
| `list_skills` / `get_skill` / `find_skill` | 账号下的 skill（网站「Skill」板块管理） |

两个 skill：`search4all`（什么时候该查库、怎么追问、怎么翻记忆）和
`search4all-sync`（把账号里的 skill 同步到本机，让客户端原生加载）。

## 可选：给单个工具的输出定 token 预算

`get_entity` 会返回整页 wiki（实测单页近万字符），`search_library` 也可能比较长。
想给它们上个硬预算，在 `~/.codex/config.toml` 里加：

```toml
[mcp_servers.search4all.tools.get_entity]
output_token_limit = 6000

[mcp_servers.search4all.tools.search_library]
output_token_limit = 4000
```

⚠️ **这一项只能你自己在 config.toml 里配，插件清单带不过去**——
实测把 `tools.<工具>.output_token_limit` 写进 `.codex-plugin/plugin.json` 的
`mcpServers` 里，Codex 会**静默丢弃**（`codex mcp list --json` 里根本没有这个字段）。
所以我们没在插件里预置，免得看着像生效其实没有。

## 不装插件、只要工具

如果你只想要检索工具、不想要 skill 指导层：

```bash
codex mcp add search4all --url https://search.092420.xyz/mcp \
  --bearer-token-env-var SEARCH4ALL_API_KEY
```

## 排查

| 现象 | 原因 |
|---|---|
| 401，提示「没有展开 `${...}` 占位符」 | 你手写了 `http_headers` 且用了占位符语法。Codex 不做插值，改用 `bearer_token_env_var` |
| 401「API key 无效或已被吊销」 | key 打错了，或已在网页端吊销。重新生成 |
| 429 | 今日点数或并发用尽。错误里带恢复时间 |
| 工具在但从不被调用 | skill 没装上。`codex plugin add search4all@issushow` 而不是只 `codex mcp add` |
| 连不上 | 先 `echo $SEARCH4ALL_API_KEY` 确认环境变量在**当前**终端里可见；Codex 读的是它自己进程的环境 |

## 从 1.x 升级

1.x 是本地 stdio：`~/.codex/servers/search4all.py` + `config.toml` 里手写的 `[mcp_servers.search4all]`（含明文 key）。
升级时：

```bash
codex mcp remove search4all          # 删掉旧的 stdio 配置
rm -f ~/.codex/servers/search4all.py # 本机脚本不再需要
```

然后按上面三步重装。**记得把 `config.toml` 里残留的明文 key 也清掉。**
