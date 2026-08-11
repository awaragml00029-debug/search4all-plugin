# search4all 插件

把实验室生信知识库接进 AI 编码助手：遇到基因、通路、测序分析流程、R/Python 生信代码这类问题时，助手直接检索内部库并带回来源，不必再手工搜索。

这个仓库**只包含插件本体**（一个 MCP server + 使用指导）。它不含任何密钥，也不含服务端代码 —— 服务端另有私有仓库。

## Claude Code

```
/plugin marketplace add awaragml00029-debug/search4all-plugin
/plugin install search4all@issushow
```

启用时填两项配置：**服务地址**（`https://search.092420.xyz`）和 **API Key**。
详见 [search4all/README.md](./search4all/README.md)。

## Codex

见 [search4all/CODEX_SETUP.md](./search4all/CODEX_SETUP.md) —— 那份文档写成了可由 Codex 自己执行的形式，把链接丢给它说「按这个装好」即可。

## 先拿 API Key

两边都需要。登录搜索页 → 右上角「🔐 API Key」→ 生成。**明文只显示一次**，服务端只存哈希，丢了只能吊销重发。

没有服务地址或账号的，问管理员。

## 环境要求

只需要 `python3`（3.8+）。MCP server 是标准库手写的，不依赖 `mcp` SDK，也不用装 `uv`。

## 三个工具

| 工具 | 用途 |
|---|---|
| `search_library` | 检索知识库，返回答案 + 编号来源 |
| `list_libraries` | 列出当前 key 可见的库 |
| `get_entity` | 读知识 Wiki 里某实体的完整研究页 |

## 关于权限

**这个插件不会、也无法修改你的 AI 助手权限设置。** 它不捆绑任何 hooks，不拦截任何工具调用。

额度与访问控制全部在服务端按 API key 执行，禁用或卸载插件都不影响那些限制。
