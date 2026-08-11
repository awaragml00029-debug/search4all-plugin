# 在 Codex 里接入 search4all（可由 Codex 自动执行）

> **给用户**：把这个文件的链接或内容丢给 Codex，说一句「按这个文档把 search4all 装好」，它就能自己做完。
> 你只需要准备一样东西：**API Key**（见下方「前置」）。
>
> **给 AI agent**：本文件是可执行指令。请从「执行步骤」开始，按顺序完成，不要跳过验证步骤。

---

## 前置：用户需要提供的信息

执行前先向用户确认这两项，缺任何一项都不要继续：

| 项 | 值 | 从哪来 |
|---|---|---|
| `SEARCH4ALL_URL` | `https://search.092420.xyz` | 已知默认值，除非用户另有指定 |
| `SEARCH4ALL_API_KEY` | `s4a_` 开头的字符串 | 用户登录搜索页 → 右上角「🔐 API Key」→ 生成。**只显示一次** |

如果用户还没有 key，告诉他去上面那个页面生成，然后把 key 给你。**不要**编造或猜测 key。

---

## 执行步骤

### 步骤 1 · 确认 python3 可用

```bash
python3 --version
```

要求 3.8 及以上。不满足就停下来告诉用户先装 python3——本 MCP server 只依赖标准库，不需要 `pip install` 任何东西，但需要解释器本身。

### 步骤 2 · 取得 server.py

```bash
mkdir -p ~/.codex/servers
curl -fsSL -o ~/.codex/servers/search4all.py \
  https://raw.githubusercontent.com/awaragml00029-debug/search4all-plugin/main/search4all/mcp/server.py
```

验证下载成功且不是错误页：

```bash
head -3 ~/.codex/servers/search4all.py && wc -l ~/.codex/servers/search4all.py
```

预期：首行是 `#!/usr/bin/env python3`，行数约 340。如果拿到的是 HTML 或 404，停下来报告，不要继续。

### 步骤 3 · 写入 Codex 配置

配置文件是 `~/.codex/config.toml`。

**⚠️ 这个文件可能已经存在并且有用户的其他配置。绝对不要整体覆盖它。**
正确做法是读出现有内容，只追加/更新 `[mcp_servers.search4all]` 这一节。

要追加的内容（把两个占位符换成前置里确认的真实值）：

```toml
[mcp_servers.search4all]
command = "python3"
args = ["~/.codex/servers/search4all.py"]

[mcp_servers.search4all.env]
SEARCH4ALL_URL = "https://search.092420.xyz"
SEARCH4ALL_API_KEY = "在此填入用户提供的 s4a_ 开头的 key"
```

注意事项：

- `args` 里的 `~` 有些版本不展开，**保险起见写绝对路径**（用 `echo $HOME` 取真实路径拼接）。
- 若 `[mcp_servers.search4all]` 已存在，就地更新它的值，不要写出重复的节。
- 只想给单个项目用的话，可以写到项目下的 `.codex/config.toml`（仅对受信任项目生效）。

### 步骤 4 · 收紧文件权限（必做）

Codex 的配置里 key 是**明文存储**的，不像 Claude Code 会进系统密钥链。所以：

```bash
chmod 600 ~/.codex/config.toml
```

如果配置写在项目目录下的 `.codex/config.toml`，还要确认它已被 `.gitignore` 忽略：

```bash
grep -q '^\.codex/' .gitignore 2>/dev/null || echo '.codex/' >> .gitignore
```

**不要把带 key 的配置提交进任何仓库。**

### 步骤 5 · 验证接通

不依赖 Codex 重启，直接握手测一次：

```bash
printf '%s\n' \
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"setup-check","version":"1"}}}' \
'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_libraries","arguments":{}}}' \
| SEARCH4ALL_URL="https://search.092420.xyz" \
  SEARCH4ALL_API_KEY="用户提供的key" \
  python3 ~/.codex/servers/search4all.py 2>/dev/null
```

**预期**：第二行 JSON 的 `result.content[0].text` 里能看到库列表（`bioinfo: 生信文档` 等）。

看到这些就说明失败了，按表处置：

| 返回内容 | 原因 | 怎么办 |
|---|---|---|
| `鉴权失败：API key 无效或已被吊销` | key 错了或被吊销 | 让用户重新生成 |
| `连不上 search4all` | URL 错，或不在能访问该服务的网络里 | 核对 URL / 网络 |
| `额度或并发受限` | 今日额度用尽 | 明日恢复，或找管理员放宽 |
| `未配置 API key` | env 没传进去 | 检查 toml 里的 `[mcp_servers.search4all.env]` 节 |

### 步骤 6 · 重启 Codex 并复验

让用户重启 Codex（或重新加载配置），然后确认 `search4all` 的三个工具已出现。

---

## 装好之后：告诉模型什么时候该用

Codex **没有** Claude Code 的 skill 机制，所以「什么时候该调这个库」需要你手动写进项目的 `AGENTS.md`（Codex 会读它）。建议追加这段：

```markdown
## 生信问题优先查内部知识库

遇到基因、通路、富集、单细胞/转录组分析流程、生信工具与 R/Python 分析代码、
实验方案这类问题时，**先调 `search_library` 工具**，不要直接用公网搜索——
库里是本实验室整理并验证过的资料。

- 需要限定范围时先 `list_libraries` 拿库 id，再把 `libraries` 传给 `search_library`
- 需要某主题的系统性长文用 `get_entity`
- 引用时写明来源编号和标题；库里没有就直说「内部库里没有相关资料」，
  不要用公网知识冒充库内结论
- 调用消耗额度（`web: true` 更贵），不要为同一问题反复重试
```

**这一步不做的话，模型多半想不起来用这个工具**，装了等于白装。

---

## 三个工具

| 工具 | 用途 | 主要参数 |
|---|---|---|
| `search_library` | 检索知识库，返回答案 + 编号来源 | `query`（必填）、`libraries`、`web`、`max_sources` |
| `list_libraries` | 列出当前 key 可见的库 | 无 |
| `get_entity` | 读知识 Wiki 里某实体的完整研究页 | `name`（必填）|

---

## 与 Claude Code 版本的差异

| | Claude Code | Codex |
|---|---|---|
| 安装 | `/plugin install` 一条命令 | 手工配 `config.toml`（或让 Codex 按本文自动做）|
| API Key 存储 | 系统密钥链（`sensitive` 字段）| **明文在 config.toml** ← 注意权限 |
| 何时该用工具 | 插件自带 SKILL.md 自动生效 | 需手动写进 `AGENTS.md` |
| 更新 | `/plugin update` | 重新执行步骤 2 覆盖 `server.py` |

MCP server 本体两边完全相同，是同一个文件。

---

## 更新

```bash
curl -fsSL -o ~/.codex/servers/search4all.py \
  https://raw.githubusercontent.com/awaragml00029-debug/search4all-plugin/main/search4all/mcp/server.py
```

覆盖后重启 Codex 即可，配置不用动。
