# search4all 插件

把实验室生信知识库接进 AI 编码助手：遇到基因、通路、测序分析流程、R/Python 生信代码这类问题时，助手直接检索内部库并带回来源，不必再手工搜索。

这个仓库**只包含插件本体**（清单 + 使用指导）。它不含任何密钥，也不含服务端代码 —— 服务端另有私有仓库。

> **v2.0.0：改成远端 MCP 服务。** 本机不再装 python 脚本，配置里只有一个地址和一份凭据。
> 从 1.x 升级看各自 README 末尾的「从 1.x 升级」。

## Claude Code

```
/plugin marketplace add awaragml00029-debug/search4all-plugin
/plugin install search4all@issushow
```

启用时填两项：**服务地址**（`https://search.092420.xyz`，末尾不加 `/mcp`）和 **API Key**。
详见 [search4all/README.md](./search4all/README.md)。

## Codex

```bash
export SEARCH4ALL_API_KEY="s4a_你的key"     # 写进 ~/.bashrc 让它长期生效
codex plugin marketplace add awaragml00029-debug/search4all-plugin
codex plugin add search4all@issushow
```

Codex **不做配置占位符插值**，所以它这边凭据走环境变量（`bearer_token_env_var`），
key 不会落进 `config.toml`。详见 [search4all/CODEX_SETUP.md](./search4all/CODEX_SETUP.md)。

## 先拿 API Key

两边都需要。登录搜索页 → 右上角「🔐 API Key」→ 生成。**明文只显示一次**，服务端只存哈希，丢了只能吊销重发。

没有服务地址或账号的，问管理员。

## 环境要求

无。v1.x 需要本机 `python3`，v2.0.0 起工具跑在远端，本机什么都不用装。

## 工具与 skill

| 工具 | 用途 |
|---|---|
| `search_library` | 检索知识库，返回答案 + 编号来源。连续提问自动接成追问 |
| `list_libraries` | 列出当前 key 能看到的库 |
| `get_entity` | 读知识 Wiki 里某实体的完整研究页 |
| `memory_recent` / `memory_search` / `memory_thread` | 调取本账号跨机器的历史对话 |
| `list_skills` / `get_skill` / `find_skill` | 账号下的 skill（网站「Skill」板块管理） |

两个 skill：`search4all`（什么时候该查库、怎么追问、怎么翻记忆）和
`search4all-sync`（把账号里的 skill 同步到本机，让客户端原生加载）。

## 仓库结构

```
.claude-plugin/marketplace.json        Claude Code 的市场清单（Codex 也认这个路径）
search4all/
  .claude-plugin/plugin.json           Claude Code 清单 + userConfig（服务地址 / API Key）
  .codex-plugin/plugin.json            Codex 清单：内联 http MCP + bearer_token_env_var
  .mcp.json                            Claude Code 的 MCP 定义（http + ${user_config.*}）
  skills/search4all/SKILL.md           指导层（两边通用）
  skills/search4all/agents/openai.yaml  Codex 专有 skill 元数据（Claude Code 忽略）
  README.md / CODEX_SETUP.md           两边的安装说明
```

两份清单不是重复：**Claude Code 会展开 `${user_config.*}`，Codex 不会。**
所以 Claude Code 那份用占位符（装的时候填一次即可），Codex 那份把地址写死、凭据走环境变量。

## 关于权限

**这个插件不会、也无法修改你的 AI 助手权限设置。** 它不捆绑任何 hooks，不拦截任何工具调用。

额度与访问控制全部在服务端按 API key 执行，禁用或卸载插件都不影响那些限制。
