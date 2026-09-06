#!/usr/bin/env python3
"""
把 search4all 账号下的 skill 同步到本地磁盘，让 Codex / Claude Code 用**各自原生的
渐进式加载**去发现它们（常驻上下文里只有名字+描述，命中才读全文）。

## 为什么是脚本而不是让模型自己抄

模型完全可以自己调 list_skills / get_skill 再写文件。但那样**每份 SKILL.md 的正文
都要过一遍模型的上下文** —— 20 个 skill 就是几十 KB，正好把「渐进式加载省下来的
上下文」又全花掉了。脚本走 HTTP 直连，进上下文的只有最后那几行摘要，成本 O(1)。

## 凭据从哪来（三级回退）

1. `--key`
2. 环境变量 `SEARCH4ALL_API_KEY`（Codex 的标准装法就是设这个）
3. `~/.search4all/key`（600 权限的文件；Claude Code 用户可以放这里，因为它把
   插件密钥存在自己的 credentials 文件里，外部进程读不到）

## 安全

- **只写 SKILL.md 正文，不写 scripts/**。远端 skill 是别人写的指令，让它顺带落一个
  可执行脚本到你机器上是另一个量级的风险，v1 不做。
- **只碰自己管过的目录**。同步清单记在 `<目标目录>/.search4all-sync.json` 里，
  不在清单里的目录一律不动 —— 你自己手写的 skill 不会被我们删掉。
- **内容变了会明说**，列出 added/updated/removed，不静默覆盖。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://search.092420.xyz"
MANIFEST = ".search4all-sync.json"
UA = "search4all-sync/1.0"
# 名字来自服务端，服务端已经归一过；这里再挡一道，因为它要拼进路径。
SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789-_")


def die(msg, code=1):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def find_key(cli_key):
    if cli_key:
        return cli_key.strip()
    env = (os.environ.get("SEARCH4ALL_API_KEY") or "").strip()
    if env:
        return env
    path = os.path.expanduser("~/.search4all/key")
    if os.path.isfile(path):
        with open(path) as f:
            k = f.read().strip()
        if k:
            return k
    die("找不到 API key。三选一：传 --key、设环境变量 SEARCH4ALL_API_KEY、"
        "或把 key 写进 ~/.search4all/key（记得 chmod 600）。")


def detect_dests():
    """
    探测这台机器上哪些 skill 目录是活的，返回 [(路径, 风格)]。

    **两家要的布局不一样，实测出来的**：

    - Codex（`~/.agents/skills`）：一个目录 + 一份 `SKILL.md` 就够。
    - Claude Code（`~/.claude/skills`）：那里放的其实是「skills-dir 插件」，
      光有 `SKILL.md` **不会被加载**，还必须有 `.claude-plugin/plugin.json`
      （`claude plugin init` scaffold 出来的就是这个形状）。

    装了哪个就往哪个写，两个都装就都写。
    """
    home = os.path.expanduser("~")
    out = []
    if os.path.isdir(os.path.join(home, ".codex")) or os.environ.get("CODEX_HOME"):
        out.append((os.path.join(home, ".agents", "skills"), "codex"))
    if os.path.isdir(os.path.join(home, ".claude")):
        out.append((os.path.join(home, ".claude", "skills"), "claude"))
    return out


def write_skill(dest, flavor, name, description, body):
    """按目标客户端的布局把一个 skill 写下去。"""
    d = os.path.join(dest, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(body)
    if flavor == "claude":
        pd = os.path.join(d, ".claude-plugin")
        os.makedirs(pd, exist_ok=True)
        with open(os.path.join(pd, "plugin.json"), "w", encoding="utf-8") as f:
            json.dump({"name": name, "version": "1.0.0",
                       "description": description, "skills": ["./"]},
                      f, ensure_ascii=False, indent=2)


def api(base, key, path, params=None):
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}", "User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
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


def load_manifest(dest):
    p = os.path.join(dest, MANIFEST)
    if os.path.isfile(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return {"managed": {}}


def sync_one(dest, flavor, skills, base, key, dry_run):
    os.makedirs(dest, exist_ok=True)
    man = load_manifest(dest)
    managed = man.get("managed", {})
    added, updated, unchanged, removed = [], [], [], []

    seen = set()
    for s in skills:
        name = s["name"]
        if not name or set(name) - SAFE:
            print(f"  跳过名字不安全的 skill: {name!r}", file=sys.stderr)
            continue
        seen.add(name)
        if managed.get(name) == s.get("content_hash"):
            unchanged.append(name)
            continue
        if not dry_run:
            body = api(base, key, "/skills/get", {"id": s["id"]}).get("body") or ""
            write_skill(dest, flavor, name, s.get("description") or "", body)
        (updated if name in managed else added).append(name)
        managed[name] = s.get("content_hash")

    # 只删我们自己管过、而远端已经没有的；用户手写的目录不在 managed 里，碰都不碰
    for name in [n for n in managed if n not in seen]:
        d = os.path.join(dest, name)
        if not dry_run:
            for rel in ("SKILL.md", ".claude-plugin/plugin.json"):
                fp = os.path.join(d, rel)
                if os.path.isfile(fp):
                    os.remove(fp)
            for sub in (os.path.join(d, ".claude-plugin"), d):
                try:
                    os.rmdir(sub)
                except OSError:
                    pass      # 目录里还有别的东西就留着，不硬删
        managed.pop(name, None)
        removed.append(name)

    if not dry_run:
        with open(os.path.join(dest, MANIFEST), "w", encoding="utf-8") as f:
            json.dump({"managed": managed, "source": base}, f, ensure_ascii=False, indent=2)
    return added, updated, unchanged, removed


def main():
    ap = argparse.ArgumentParser(description="把 search4all 的 skill 同步到本地")
    ap.add_argument("--url", default=os.environ.get("SEARCH4ALL_URL") or DEFAULT_URL)
    ap.add_argument("--key")
    ap.add_argument("--dest", action="append",
                    help="目标 skill 目录，可重复。写成 <路径> 或 <路径>:<codex|claude>；"
                         "不带风格时按路径猜。不传则自动探测")
    ap.add_argument("--limit", type=int, default=30,
                    help="最多同步几个（客户端常驻清单有预算上限，默认 30）")
    ap.add_argument("--dry-run", action="store_true", help="只看会发生什么，不落盘")
    a = ap.parse_args()

    key = find_key(a.key)
    if a.dest:
        dests = []
        for spec in a.dest:
            if ":" in spec and spec.rsplit(":", 1)[1] in ("codex", "claude"):
                path, flavor = spec.rsplit(":", 1)
            else:
                path = spec
                flavor = "claude" if ".claude" in path else "codex"
            dests.append((os.path.expanduser(path), flavor))
    else:
        dests = detect_dests()
    if not dests:
        die("没探测到 Codex 或 Claude Code 的 skill 目录。用 --dest 指定一个。")

    data = api(a.url, key, "/skills/visible", {"limit": a.limit})
    skills = data.get("skills") or []
    if not skills:
        print("账号下没有可同步的 skill。到 search4all 网站的「Skill」板块添加。")
        return

    print(f"远端 {len(skills)} 个 skill，目标目录 {len(dests)} 处"
          + ("（dry-run，不落盘）" if a.dry_run else ""))
    for dest, flavor in dests:
        added, updated, unchanged, removed = sync_one(
            dest, flavor, skills, a.url, key, a.dry_run)
        print(f"\n{dest}  [{flavor}]")
        for label, items in (("新增", added), ("更新", updated),
                             ("移除", removed), ("未变", unchanged)):
            if items:
                print(f"  {label} {len(items)}: {', '.join(items)}")
        if not (added or updated or removed):
            print("  已是最新")
    print("\n完成。重启客户端（或开新会话）后这些 skill 才会被加载。")


if __name__ == "__main__":
    main()
