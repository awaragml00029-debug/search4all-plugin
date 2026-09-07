#!/usr/bin/env python3
"""
把 search4all 账号下的 skill 同步到本机，让各家 AI 客户端用**原生的渐进式加载**发现它们。

## 架构：SSOT + 软链多端（v2.1 重写）

    ~/.search4all/skills/<id>/          ← SSOT，本脚本唯一写内容的地方
        SKILL.md
        references/ scripts/ ...        ← 远端有什么就落什么
        .claude-plugin/plugin.json      ← 我们生成；Claude Code 要，别家忽略
            ↓ 软链（建不了就复制）
    ~/.agents/skills/<id>               Codex
    ~/.claude/skills/<id>               Claude Code
    ~/.gemini/skills/<id>               Gemini CLI
    ~/.config/opencode/skills/<id>      OpenCode

**为什么不直接往各客户端目录写**（v2.0 就是那么干的，这版改掉了）：

- 启用/禁用要重下。现在启用 = 建一条链，禁用 = 删链，源目录一直在。
- 多端要写 N 份。现在一份源，N 条链。
- 和用户手写的 skill 混在同一个命名空间里。现在天然隔开。

这套做法是照 CodexPlusPlus（`crates/codex-plus-core/src/skills.rs`）和 cc-switch 抄的，
它们都是这个形状，且已被大量用户验证。

## 为什么是脚本而不是让模型自己抄

模型完全可以自己调 list_skills / get_skill 再写文件。但那样**每份 skill 的正文和附件
都要过一遍模型的上下文** —— 一个带 48 个文件的 skill 就能把渐进式加载省下的全花掉。
脚本走 HTTP 直连，进上下文的只有最后那几行摘要，成本 O(1)。

## 凭据（三级回退）

1. `--key`
2. 环境变量 `SEARCH4ALL_API_KEY`（Codex 的标准装法就是设这个）
3. `~/.search4all/key`（600 权限的文件；Claude Code 把插件密钥存在自己的
   credentials 文件里，外部进程读不到，所以给它准备了这条）
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://search.092420.xyz"
HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".search4all")
SSOT = os.path.join(ROOT, "skills")            # 单一真相源
BACKUPS = os.path.join(ROOT, "skill-backups")  # 卸载先备份，不直接删
MANIFEST = os.path.join(ROOT, "skills-manifest.json")
UA = "search4all-sync/2.1"
# 名字来自服务端（已归一），这里再挡一道，因为它要拼进路径
SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789-_")

# 各客户端扫描的 skill 目录。装了哪个就往哪个建链。
CLIENTS = [
    ("codex",    os.path.join(HOME, ".agents", "skills"),
     lambda: os.path.isdir(os.path.join(HOME, ".codex")) or bool(os.environ.get("CODEX_HOME"))),
    ("claude",   os.path.join(HOME, ".claude", "skills"),
     lambda: os.path.isdir(os.path.join(HOME, ".claude"))),
    ("gemini",   os.path.join(HOME, ".gemini", "skills"),
     lambda: os.path.isdir(os.path.join(HOME, ".gemini"))),
    ("opencode", os.path.join(HOME, ".config", "opencode", "skills"),
     lambda: os.path.isdir(os.path.join(HOME, ".config", "opencode"))),
]


def die(msg, code=1):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def find_key(cli_key):
    if cli_key:
        return cli_key.strip()
    env = (os.environ.get("SEARCH4ALL_API_KEY") or "").strip()
    if env:
        return env
    path = os.path.join(ROOT, "key")
    if os.path.isfile(path):
        with open(path) as f:
            k = f.read().strip()
        if k:
            return k
    die("找不到 API key。三选一：传 --key、设环境变量 SEARCH4ALL_API_KEY、"
        f"或把 key 写进 {os.path.join(ROOT, 'key')}（记得 chmod 600）。")


def api(base, key, path, params=None):
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}", "User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = (json.loads(e.read().decode()) or {}).get("error", "")
        except Exception:
            pass
        if e.code == 401:
            die(f"鉴权失败（401）。key 可能无效或已吊销。{body}")
        die(f"HTTP {e.code}: {body or url}")
    except Exception as e:
        die(f"连不上 {url}：{e}")


# --------------------------------------------------------------- 链接与落盘

def link_or_copy(source, link):
    """
    先试软链，不行就复制。

    Windows 上建软链需要开发者模式或管理员权限，普通用户常常建不了——
    这时候悄悄退回复制，比直接失败有用得多。（抄 CodexPlusPlus 的 link_or_copy。）
    返回 "link" 或 "copy"。
    """
    remove_link(link)
    os.makedirs(os.path.dirname(link), exist_ok=True)
    try:
        os.symlink(source, link, target_is_directory=True)
        return "link"
    except (OSError, NotImplementedError, AttributeError):
        shutil.copytree(source, link)
        return "copy"


def remove_link(link):
    """链可能是软链，也可能是复制出来的实体目录，两种都要能删干净。"""
    if os.path.islink(link):
        os.unlink(link)
    elif os.path.isdir(link):
        shutil.rmtree(link)
    elif os.path.exists(link):
        os.remove(link)


def write_source(sid, files, description):
    """把整棵文件树写进 SSOT。先写暂存目录再整体替换，避免半成品被客户端读到。"""
    dest = os.path.join(SSOT, sid)
    staging = os.path.join(SSOT, f".staging-{sid}")
    if os.path.exists(staging):
        shutil.rmtree(staging)
    for rel, content in files.items():
        # 服务端已经做过 zip-slip 校验，这里再挡一道：谁也不该信上游
        parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts) or not parts:
            raise ValueError(f"非法路径：{rel}")
        path = os.path.join(staging, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    # Claude Code 认的是「skills-dir 插件」布局：光有 SKILL.md 不会被加载。
    # 生成在 SSOT 源目录里 —— 一份源两个消费者，Codex 会忽略这个点开头的目录。
    pd = os.path.join(staging, ".claude-plugin")
    os.makedirs(pd, exist_ok=True)
    with open(os.path.join(pd, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump({"name": sid, "version": "1.0.0",
                   "description": description, "skills": ["./"]},
                  f, ensure_ascii=False, indent=2)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.rename(staging, dest)
    return dest


def backup_source(sid):
    """卸载前把源整体挪进备份目录，不做自动轮转删除。"""
    src = os.path.join(SSOT, sid)
    if not os.path.isdir(src):
        return None
    os.makedirs(BACKUPS, exist_ok=True)
    dst = os.path.join(BACKUPS, f"{sid}-{time.strftime('%Y%m%d%H%M%S')}")
    shutil.move(src, dst)
    return dst


def load_manifest():
    if os.path.isfile(MANIFEST):
        try:
            with open(MANIFEST) as f:
                return json.load(f)
        except Exception:
            pass
    return {"managed": {}}


def save_manifest(man):
    os.makedirs(ROOT, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)


def detect_clients(explicit):
    if explicit:
        out = []
        for spec in explicit:
            if ":" in spec:
                kind, path = spec.split(":", 1)
            else:
                kind, path = "custom", spec
            out.append((kind, os.path.expanduser(path)))
        return out
    return [(k, p) for k, p, present in CLIENTS if present()]


# ------------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="把 search4all 的 skill 同步到本机")
    ap.add_argument("--url", default=os.environ.get("SEARCH4ALL_URL") or DEFAULT_URL)
    ap.add_argument("--key")
    ap.add_argument("--client", action="append",
                    help="目标客户端 skill 目录，可重复；写成 <名字>:<路径> 或纯路径。不传则自动探测")
    ap.add_argument("--limit", type=int, default=30,
                    help="最多同步几个（客户端常驻清单有预算上限，默认 30）")
    ap.add_argument("--dry-run", action="store_true", help="只看会发生什么，不动磁盘")
    a = ap.parse_args()

    key = find_key(a.key)
    clients = detect_clients(a.client)
    if not clients:
        die("没探测到任何客户端的 skill 目录（Codex/Claude Code/Gemini/OpenCode）。"
            "用 --client 指定一个。")

    data = api(a.url, key, "/skills/visible", {"limit": a.limit})
    remote = data.get("skills") or []
    if not remote:
        print("账号下没有可同步的 skill。到 search4all 网站的「Skill」板块添加。")
        return

    man = load_manifest()
    managed = man.get("managed", {})
    added, updated, unchanged, removed = [], [], [], []
    seen = set()

    print(f"远端 {len(remote)} 个 skill；本机客户端："
          + "、".join(f"{k}({os.path.basename(os.path.dirname(p))})" for k, p in clients)
          + ("（dry-run，不动磁盘）" if a.dry_run else ""))

    for s in remote:
        sid = s["name"]
        if not sid or set(sid) - SAFE:
            print(f"  跳过名字不安全的 skill: {sid!r}", file=sys.stderr)
            continue
        seen.add(sid)
        if managed.get(sid, {}).get("hash") == s.get("content_hash"):
            unchanged.append(sid)
            continue
        if not a.dry_run:
            full = api(a.url, key, "/skills/get", {"id": s["id"]})
            files = full.get("files") or {"SKILL.md": full.get("body") or ""}
            write_source(sid, files, full.get("description") or "")
            for _, root in clients:
                link_or_copy(os.path.join(SSOT, sid), os.path.join(root, sid))
        (updated if sid in managed else added).append(sid)
        managed[sid] = {"hash": s.get("content_hash"), "synced_at": time.strftime("%F %T")}

    # 只处理我们自己管过、而远端已经没有的；用户手写的目录不在 managed 里，碰都不碰
    for sid in [x for x in managed if x not in seen]:
        if not a.dry_run:
            for _, root in clients:
                remove_link(os.path.join(root, sid))
            backup_source(sid)
        managed.pop(sid, None)
        removed.append(sid)

    if not a.dry_run:
        man["managed"] = managed
        save_manifest(man)

    for label, items in (("新增", added), ("更新", updated),
                         ("移除(已备份)", removed), ("未变", unchanged)):
        if items:
            print(f"  {label} {len(items)}: {', '.join(items)}")
    if not (added or updated or removed):
        print("  已是最新")
    print(f"\n源目录：{SSOT}")
    print("完成。重启客户端（或开新会话）后这些 skill 才会被加载。")


if __name__ == "__main__":
    main()
