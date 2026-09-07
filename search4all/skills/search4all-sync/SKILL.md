---
name: search4all-sync
description: 把 search4all 账号下的 skill 同步到本机，让它们像本地 skill 一样被自动加载。用户说「同步我的 skill」「拉一下我的技能」「我在网站上加了 skill 怎么还没生效」「换了台机器怎么把我的东西弄回来」时用。也用于查看本机已同步了哪些、和远端差了什么。
---

# 同步 search4all 上的 skill 到本机

用户的 skill 存在 search4all 账号里（跨机器、跨客户端）。同步下来之后，它们会被
Codex / Claude Code / Gemini CLI / OpenCode 按**各自原生的渐进式加载**发现——
常驻上下文里只有名字和描述，真用到才读全文。所以同步是一次性动作，之后不花任何上下文。

## 架构：一份源，多端软链

```
~/.search4all/skills/<id>/     ← 唯一的源（SKILL.md + references/ scripts/ … 全在）
        ↓ 软链（建不了就自动复制）
~/.agents/skills/<id>          Codex
~/.claude/skills/<id>          Claude Code
~/.gemini/skills/<id>          Gemini CLI
~/.config/opencode/skills/<id> OpenCode
```

所以**启用/禁用只是增删一条链，不用重新下载**；也和用户自己手写的 skill 天然隔开。

## 怎么做

这个 skill 目录下有 `scripts/sync.py`。**你能从 skill 清单里看到本文件的绝对路径**，
同步脚本就在它旁边的 `scripts/` 里。用那个绝对路径运行：

```bash
python3 <本 SKILL.md 所在目录>/scripts/sync.py
```

先跑一次 `--dry-run` 给用户看会发生什么，确认后再实跑，这是**修改用户磁盘**的操作：

```bash
python3 .../scripts/sync.py --dry-run
```

常用参数：

| 参数 | 用途 |
|---|---|
| `--dry-run` | 只报告不落盘 |
| `--client <路径>` | 指定目标客户端目录（可重复）。不传会自动探测四家 |
| `--limit N` | 最多同步几个，默认 30 |
| `--url` / `--key` | 服务地址和凭据，一般不用传 |

## 凭据

脚本按顺序找 key：`--key` → 环境变量 `SEARCH4ALL_API_KEY` → `~/.search4all/key`。

**Codex 用户**通常已经设了环境变量（安装时就要求设），直接能跑。
**Claude Code 用户**的 key 存在客户端自己的凭据文件里，外部进程读不到，
脚本会报「找不到 API key」。这时告诉用户二选一：

```bash
# 办法一：环境变量（写进 ~/.bashrc 长期生效）
export SEARCH4ALL_API_KEY="s4a_..."

# 办法二：存成文件
mkdir -p ~/.search4all && printf '%s' "s4a_..." > ~/.search4all/key && chmod 600 ~/.search4all/key
```

**不要**替用户去翻他的 credentials 文件把 key 抠出来，让他自己给。

## 跑完之后

脚本会列出新增 / 更新 / 移除 / 未变。**要提醒用户重启客户端或开新会话**——
skill 清单是会话启动时构建的，同步完当前这个会话里看不到。

## 几条边界

- **只删自己管过的**（记录在 `~/.search4all/skills-manifest.json`）。
  用户手写的 skill 目录不在清单里，不会被动。
- **移除前先备份**到 `~/.search4all/skill-backups/<id>-<时间戳>/`，不做自动轮转删除。
  用户后悔了可以从那里捞回来。
- **随附文件会一起落盘**（`references/` `scripts/` `mcp-server/` 等）。也就是说
  远端 skill 里的脚本会出现在用户机器上——这是产品的既定取舍，但值得在
  用户第一次同步别人写的 skill 时提一句。
- 同步有数量上限（默认 30）。客户端的常驻 skill 清单有预算，塞太多会被静默丢弃。
  **装不下的不要硬同步**，让 `find_skill` 兜底。

## 不需要同步的情况

用户只是想**用**某个 skill 一次，不必落盘：直接 `find_skill` 找到它、`get_skill` 取正文，
照着做即可。同步是为了让它以后能被自动触发。
