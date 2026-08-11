#!/usr/bin/env python3
"""
search4all MCP server —— 把实验室生信知识库接进 Claude Code。

只用 Python 标准库，不依赖 mcp SDK：实验室机器的 pip/uv 环境参差不齐，
多一个依赖就多一批装不上的人。协议面只需 initialize / tools/list / tools/call
三个方法，手写的成本远低于让每个用户先配好 Python 环境。

传输：stdio 上的行分隔 JSON-RPC 2.0（MCP stdio 规范，非 LSP 的 Content-Length 分帧）。
"""
import json
import os
import re
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request

SERVER_NAME = "search4all"
SERVER_VERSION = "0.1.2"
# 必须显式设 UA：urllib 默认发 "Python-urllib/3.x"，Cloudflare 免费版的 bot 规则
# 直接 403 拦掉。服务挂在 CF 后面时，不设这个头插件全线连不上。
USER_AGENT = f"search4all-mcp/{SERVER_VERSION} (Claude Code plugin)"
# 客户端没报版本时的兜底；正常情况下我们回显客户端请求的版本，跟着它走
FALLBACK_PROTOCOL = "2025-06-18"

BASE_URL = (os.environ.get("SEARCH4ALL_URL") or "http://localhost:8800").rstrip("/")
API_KEY = (os.environ.get("SEARCH4ALL_API_KEY") or "").strip()
HTTP_TIMEOUT = int(os.environ.get("SEARCH4ALL_TIMEOUT") or "120")

# /query 流式响应的分段标记（与 web/src/app/utils/parse-streaming.ts 一致）
LLM_SPLIT = "__LLM_RESPONSE__"
SOURCES_UPDATE = "__SOURCES_UPDATE__"
RELATED_SPLIT = "__RELATED_QUESTIONS__"
IMAGES_SPLIT = "__IMAGES__"

# 返回给模型的上下文预算：来源太多会把 agent 的上下文吃光，宁可少而准
DEFAULT_MAX_SOURCES = 8
SNIPPET_CHARS = 300


def log(msg):
    """诊断信息只能走 stderr——stdout 是协议通道，写脏了会让客户端解析失败。"""
    print(f"[search4all-mcp] {msg}", file=sys.stderr, flush=True)


# ---------- HTTP ----------

def _request(method, path, body=None, params=None, timeout=None):
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "*/*", "User-Agent": USER_AGENT}
    if data:
        headers["Content-Type"] = "application/json"
    if API_KEY:
        headers["X-Api-Key"] = API_KEY
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout or HTTP_TIMEOUT) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def _http_error_text(e):
    """把后端的 JSON 错误体翻成人话；配额 429 要给出可操作的下一步。"""
    raw = ""
    try:
        raw = e.read().decode("utf-8", "replace")
    except Exception:
        pass
    detail = raw
    try:
        d = json.loads(raw)
        detail = d.get("error") or raw
    except Exception:
        pass
    if e.code == 401:
        return ("鉴权失败：API key 无效或已被吊销。请到搜索页右上角「🔐 API Key」"
                "重新生成，并更新插件配置。")
    if e.code == 403:
        return f"没有权限：{detail}"
    if e.code == 429:
        return f"额度或并发受限：{detail}"
    return f"HTTP {e.code}: {detail}"


# ---------- /query 流式响应解析 ----------

def _parse_query_stream(text):
    """
    切出 (sources, answer, related)。分段顺序：
      [本地来源 JSON] __SOURCES_UPDATE__ [完整来源 JSON] __LLM_RESPONSE__
      [正文] __RELATED_QUESTIONS__ [JSON] __IMAGES__ [JSON]
    每一段都可能缺省（未联网时没有 __IMAGES__，追问轮可能没有相关问题）。
    """
    if LLM_SPLIT not in text:
        # 没有正文标记 = 后端在生成前就返回了（多为错误体）
        return [], text.strip(), []
    head, rest = text.split(LLM_SPLIT, 1)
    src_raw = head.split(SOURCES_UPDATE)[-1] if SOURCES_UPDATE in head else head
    try:
        sources = json.loads(src_raw.strip())
    except Exception:
        sources = []

    cuts = [i for i in (rest.find(RELATED_SPLIT), rest.find(IMAGES_SPLIT)) if i >= 0]
    answer = rest[:min(cuts)] if cuts else rest

    related = []
    ridx = rest.find(RELATED_SPLIT)
    if ridx >= 0:
        iidx = rest.find(IMAGES_SPLIT)
        end = iidx if iidx > ridx else len(rest)
        try:
            related = json.loads(rest[ridx + len(RELATED_SPLIT):end].strip())
        except Exception:
            related = []
    return sources, answer.strip(), related


def _format_result(sources, answer, related, max_sources):
    out = [answer or "(后端没有返回正文)"]
    if sources:
        out.append("\n\n## 来源")
        for i, s in enumerate(sources[:max_sources], 1):
            name = (s.get("name") or "").strip() or "(无标题)"
            url = (s.get("url") or "").strip()
            snippet = " ".join((s.get("snippet") or "").split())
            if len(snippet) > SNIPPET_CHARS:
                snippet = snippet[:SNIPPET_CHARS] + "…"
            line = f"[{i}] {name}"
            if url:
                line += f" — {url}"
            if snippet:
                line += f"\n    {snippet}"
            out.append(line)
        if len(sources) > max_sources:
            out.append(f"(另有 {len(sources) - max_sources} 条来源未列出)")
    if related:
        qs = [r.get("question") or r.get("query") or "" for r in related]
        qs = [q for q in qs if q]
        if qs:
            out.append("\n## 相关问题\n" + "\n".join(f"- {q}" for q in qs))
    return "\n".join(out)


# ---------- 工具实现 ----------

def tool_search_library(args):
    query = (args.get("query") or "").strip()
    if not query:
        return "query 不能为空。", True
    body = {"query": query, "search_uuid": uuid.uuid4().hex}
    libs = args.get("libraries")
    if libs:
        body["libraries"] = libs if isinstance(libs, list) else [libs]
    if args.get("web"):
        body["web"] = True
    max_sources = int(args.get("max_sources") or DEFAULT_MAX_SOURCES)
    _status, text = _request("POST", "/query", body=body)
    sources, answer, related = _parse_query_stream(text)
    return _format_result(sources, answer, related, max_sources), False


def tool_list_libraries(_args):
    _status, text = _request("GET", "/libraries", timeout=30)
    d = json.loads(text)
    items = d.get("libraries") or []
    if not items:
        return "当前身份看不到任何库（key 可能无检索权限，或库未对你的团队开放）。", False
    lines = [f"默认库：{d.get('default')}", "可用库："]
    lines += [f"- {i.get('id')}: {i.get('name')}" for i in items]
    return "\n".join(lines), False


def _compact_citations(md):
    """
    把正文里的 `[\\[N\\]](完整URL)` 压成 `[N]`，末尾的参考来源清单原样保留。

    实体页约七成字符是引用管道而非内容：同样那二十来个 URL 会在正文里重复出现几十次，
    单页实测 9858 字符里行内标记就占 4112(42%)、参考清单 2744(28%)、正文只有 3002。
    压掉重复 URL 后编号仍能在末尾清单里查到出处，引用能力不受影响——这是无损的。
    正文本身不截断：一页里最有价值的「关联」和「存疑与矛盾」都在尾部，从头截会截错方向。
    """
    return re.sub(r'\[\\?\[(\d+)\\?\]\]\(https?://[^)\s]+\)', r'[\1]', md or "")


def tool_get_entity(args):
    name = (args.get("name") or "").strip()
    if not name:
        return "name 不能为空。", True
    _status, text = _request("GET", "/wiki/entities", timeout=30)
    ents = json.loads(text).get("entities") or []
    if not ents:
        return "你的知识 Wiki 里还没有实体页。", False
    low = name.lower()
    match = (next((e for e in ents if (e.get("title") or "").lower() == low), None)
             or next((e for e in ents if low in (e.get("title") or "").lower()), None))
    if not match:
        titles = ", ".join((e.get("title") or "") for e in ents[:20])
        return f"没找到实体「{name}」。现有实体：{titles}", False
    _status, text = _request("GET", "/wiki/entity",
                             params={"slug": match.get("slug")}, timeout=60)
    e = json.loads(text)
    parts = [f"# {e.get('title')}"]
    if e.get("aliases"):
        parts.append(f"别名：{', '.join(e['aliases'])}")
    parts.append(_compact_citations(e.get("markdown")) or "(空)")
    if e.get("backlinks"):
        parts.append("\n反向链接：" + ", ".join(
            b.get("title") or b.get("src_slug") or "" for b in e["backlinks"]))
    return "\n\n".join(parts), False


TOOLS = [
    {
        "name": "search_library",
        "description": (
            "检索实验室内部生信知识库并返回带来源的答案。遇到基因、通路、测序分析流程、"
            "R/Python 生信代码、实验方案一类问题时优先用这个，而不是公网搜索——"
            "库里是本实验室整理和验证过的资料。返回正文 + 引用来源列表。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言问题，中英文都行"},
                "libraries": {
                    "type": "array", "items": {"type": "string"},
                    "description": "限定检索的库 id（先用 list_libraries 查）。不传则跨全部可见库。"},
                "web": {
                    "type": "boolean",
                    "description": "是否叠加公网检索。默认 false；库内查不到时才开，会额外消耗额度。"},
                "max_sources": {
                    "type": "number",
                    "description": f"最多返回几条来源，默认 {DEFAULT_MAX_SOURCES}"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_libraries",
        "description": "列出当前 API key 可检索的知识库及其 id。想限定检索范围时先调这个。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_entity",
        "description": (
            "按名称读取「知识 Wiki」里某个实体的完整研究页（深度研究管线生成的长文）。"
            "适合需要某个主题的系统性综述而不是零散片段时使用。"),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "实体名称或其中一部分"}},
            "required": ["name"],
        },
    },
]

HANDLERS = {
    "search_library": tool_search_library,
    "list_libraries": tool_list_libraries,
    "get_entity": tool_get_entity,
}


# ---------- JSON-RPC ----------

def _result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(msg):
    """返回要回给客户端的字典；通知（无 id）返回 None。"""
    method = msg.get("method")
    rid = msg.get("id")
    if rid is None:  # 通知，不需要响应
        return None

    if method == "initialize":
        # 回显客户端请求的协议版本：我们只用 initialize/tools 这几个稳定方法，
        # 跟着客户端走比钉死一个版本更耐得住协议演进
        client_ver = (msg.get("params") or {}).get("protocolVersion") or FALLBACK_PROTOCOL
        return _result(rid, {
            "protocolVersion": client_ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "ping":
        return _result(rid, {})

    if method == "tools/list":
        return _result(rid, {"tools": TOOLS})

    if method == "tools/call":
        params = msg.get("params") or {}
        fn = HANDLERS.get(params.get("name"))
        if not fn:
            return _error(rid, -32602, f"未知工具: {params.get('name')}")
        if not API_KEY:
            text, is_err = ("未配置 API key。请在 /plugin 里填入 search4all 的 API Key："
                            "登录搜索页 → 右上角「🔐 API Key」→ 生成。"), True
        else:
            try:
                text, is_err = fn(params.get("arguments") or {})
            except urllib.error.HTTPError as e:
                text, is_err = _http_error_text(e), True
            except urllib.error.URLError as e:
                text, is_err = (f"连不上 search4all（{BASE_URL}）：{e.reason}。"
                                f"检查服务地址配置和网络。"), True
            except Exception as e:
                log(f"tool {params.get('name')} failed: {e!r}")
                text, is_err = f"调用失败：{e}", True
        return _result(rid, {"content": [{"type": "text", "text": text}], "isError": is_err})

    return _error(rid, -32601, f"未实现的方法: {method}")


def main():
    log(f"started, backend={BASE_URL}, key={'已配置' if API_KEY else '缺失'}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            log(f"跳过无法解析的行: {line[:120]}")
            continue
        try:
            out = handle(msg)
        except Exception as e:
            log(f"handler crashed: {e!r}")
            out = _error(msg.get("id"), -32603, str(e))
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
