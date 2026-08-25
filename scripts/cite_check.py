#!/usr/bin/env python3
"""
cite_check.py — 文献引用的注册、真实性验证、BibTeX 导出（AutoMCM_SOP.md §15）

解决四个问题：
  1. 引用真实性——LLM 最常见的坑是自己编 DOI/论文标题。目前 gate_literature
     只检查"有没有 DOI/URL 形状的字符串"，不检查那个 DOI 是不是真的存在。
     本脚本用 CrossRef API（免费、无需 key）对 DOI 做真实性核验，arXiv/一般
     URL 用 HEAD 请求核验可达性。
  2. 跨子问题共享/去重——单一 CUMCM_Workspace/memory/citations.bib 作为全项目
     共享的引用池，注册时按 DOI/URL/标题去重，同一篇文献不会被不同子问题
     重复搜索、重复注册。
  3. 结构化引用管理——标准 BibTeX 字段（author/title/year/journaltitle/doi/url），
     而不是散落在 thought_process.md 里的自由文本。
  4. 搜索广度——见 LOS_ALAMOS_METHOD_CATALOG.md，本脚本不负责搜索本身（搜索
     仍是 Agent 用运行时的网络检索工具做），只负责"找到之后怎么登记、怎么核验、
     怎么导出"。

子命令：
  register          注册一条引用（去重后返回 citation_key）
  verify            对已注册的引用做真实性核验（DOI→CrossRef / arXiv→HEAD / URL→HEAD）
  list              列出已注册的引用（可按 --problem-n 过滤）
  export-bibitems   把已验证的引用渲染成 \\bibitem{...} 文本块，供粘贴进 main.tex

不直接维护另一套真相来源——citations.bib 本身就是唯一的持久化状态，
用标准 BibTeX 格式，人类/其他工具都能直接读。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

WORKSPACE = Path("CUMCM_Workspace")
BIB_FILE = WORKSPACE / "memory" / "citations.bib"

_TIMEOUT = 8  # 秒，网络核验的超时，网络不可用时不应该卡住整个流程


# ── BibTeX 极简读写（不依赖第三方库，只支持本脚本自己写的固定格式）───────────

_ENTRY_RE = re.compile(
    r"@(\w+)\{(?P<key>[^,]+),\s*(?P<body>.*?)\n\}",
    re.DOTALL,
)
_FIELD_RE = re.compile(r"(\w+)\s*=\s*\{(.*?)\}\s*,?\s*$", re.MULTILINE)


def _load_entries() -> dict[str, dict]:
    if not BIB_FILE.exists():
        return {}
    text = BIB_FILE.read_text(encoding="utf-8")
    entries = {}
    for m in _ENTRY_RE.finditer(text):
        key = m.group("key").strip()
        fields = {"_type": text[m.start():m.start() + 20].split("{")[0].lstrip("@")}
        for fm in _FIELD_RE.finditer(m.group("body")):
            fields[fm.group(1)] = fm.group(2)
        entries[key] = fields
    return entries


def _save_entries(entries: dict[str, dict]) -> None:
    BIB_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, fields in entries.items():
        etype = fields.get("_type", "misc")
        lines.append(f"@{etype}{{{key},")
        for k, v in fields.items():
            if k == "_type":
                continue
            lines.append(f"  {k} = {{{v}}},")
        lines.append("}\n")
    BIB_FILE.write_text("\n".join(lines), encoding="utf-8")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _dedup_key(fields: dict) -> str | None:
    """去重判据：DOI 相同，或 URL 相同，或标题标准化后相同，命中任一视为同一篇。"""
    entries = _load_entries()
    for key, e in entries.items():
        if fields.get("doi") and e.get("doi") and fields["doi"].lower() == e["doi"].lower():
            return key
        if fields.get("url") and e.get("url") and fields["url"] == e["url"]:
            return key
        if fields.get("title") and e.get("title") and _norm(fields["title"]) == _norm(e["title"]):
            return key
    return None


def _make_key(fields: dict) -> str:
    author = re.sub(r"[^A-Za-z]", "", (fields.get("author") or "Anon").split(",")[0].split(" and ")[0])
    year = fields.get("year") or "n.d."
    base = f"{author}{year}" or "ref"
    entries = _load_entries()
    key = base
    suffix = ord("a")
    while key in entries:
        key = f"{base}{chr(suffix)}"
        suffix += 1
    return key


# ── 子命令：register ─────────────────────────────────────────────────────────

def cmd_register(args):
    fields = {
        "_type": args.entry_type,
        "title": args.title,
        "author": args.author or "",
        "year": args.year or "",
    }
    if args.journal:
        fields["journaltitle"] = args.journal
    if args.doi:
        fields["doi"] = args.doi
    if args.url:
        fields["url"] = args.url
    if args.problem_n:
        fields["note"] = f"problem{args.problem_n}"
    fields["verified"] = "unchecked"

    existing = _dedup_key(fields)
    if existing:
        print(f"[cite] ↺ 已存在，去重命中: {existing}（未新增重复条目）")
        # 若这次多提供了 problem_n，追加到已有条目的 note，标记跨问题复用
        entries = _load_entries()
        note = entries[existing].get("note", "")
        tag = f"problem{args.problem_n}" if args.problem_n else ""
        if tag and tag not in note:
            entries[existing]["note"] = (note + "," + tag).strip(",")
            _save_entries(entries)
            print(f"  已标记复用于 problem{args.problem_n}")
        print(existing)
        return

    key = _make_key(fields)
    entries = _load_entries()
    entries[key] = fields
    _save_entries(entries)
    print(f"[cite] ✓ 新注册: {key}")
    print(key)


# ── 子命令：verify（真实性核验）───────────────────────────────────────────────

def _check_doi(doi: str) -> tuple[bool, str]:
    url = f"https://api.crossref.org/works/{doi}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AutoMCM-Pro/cite_check"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            title = data.get("message", {}).get("title", ["(无标题)"])
            title = title[0] if title else "(无标题)"
            return True, f"CrossRef 确认存在，标题: {title}"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "CrossRef 查无此 DOI（很可能是编造的引用，禁止用于论文）"
        return None, f"CrossRef 返回 HTTP {e.code}，无法判定"
    except Exception as e:
        return None, f"网络错误，无法核验（{type(e).__name__}），不代表引用有问题"


def _check_url(url: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="HEAD",
                                      headers={"User-Agent": "Mozilla/5.0 AutoMCM-Pro/cite_check"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return True, f"HTTP {resp.status}，可达"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "HTTP 404，页面不存在"
        # 部分服务器不支持 HEAD 或对爬虫返回 403，不直接判定为假
        return None, f"HTTP {e.code}，无法确定判定"
    except Exception as e:
        return None, f"网络错误，无法核验（{type(e).__name__}），不代表引用有问题"


def cmd_verify(args):
    entries = _load_entries()
    if args.doi:
        targets = {k: e for k, e in entries.items() if e.get("doi") == args.doi}
    elif args.key:
        targets = {args.key: entries[args.key]} if args.key in entries else {}
    else:
        targets = entries

    if not targets:
        print("[cite] 没有匹配的条目可核验")
        sys.exit(1)

    n_confirmed = n_fake = n_unknown = 0
    for key, fields in targets.items():
        if fields.get("doi"):
            ok, msg = _check_doi(fields["doi"])
        elif fields.get("url"):
            ok, msg = _check_url(fields["url"])
        else:
            ok, msg = None, "无 DOI/URL，无法核验（仅凭标题不足以核实）"

        status = "verified" if ok is True else ("fake" if ok is False else "unchecked")
        fields["verified"] = status
        icon = {"verified": "✓", "fake": "✗", "unchecked": "?"}[status]
        print(f"  {icon} {key}: {msg}")
        n_confirmed += ok is True
        n_fake += ok is False
        n_unknown += ok is None

    _save_entries(entries)
    print(f"\n[cite] 核验完成: {n_confirmed} 确认真实 / {n_fake} 疑似编造 / {n_unknown} 无法判定")
    if n_fake:
        print(f"[cite] ⚠ 发现 {n_fake} 条疑似编造的引用，禁止用于论文，需要删除或替换成真实文献")
        sys.exit(1)
    sys.exit(0)


# ── 子命令：list / export-bibitems ───────────────────────────────────────────

def cmd_list(args):
    entries = _load_entries()
    if args.problem_n:
        tag = f"problem{args.problem_n}"
        entries = {k: e for k, e in entries.items() if tag in (e.get("note") or "")}
    if not entries:
        print("[cite] 无匹配记录")
        return
    for key, e in entries.items():
        v = e.get("verified", "unchecked")
        icon = {"verified": "✓", "fake": "✗", "unchecked": "?"}.get(v, "?")
        print(f"  {icon} [{key}] {e.get('title', '')} ({e.get('year', 'n.d.')}) "
              f"— {e.get('doi') or e.get('url') or '无DOI/URL'}")


_LATEX_ESCAPE = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_LATEX_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _LATEX_ESCAPE))


def _tex_escape(s: str) -> str:
    """引用的标题/DOI/作者来自真实文献原文，常见 `_`（DOI 里很常见）、`&`、`%`
    这类 LaTeX 特殊字符——不转义直接拼进 \\bibitem 会让 xelatex 编译报
    'Missing $ inserted' 之类的 fatal error（真实踩过的坑，见 SOP §15 变更记录）。"""
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_ESCAPE[m.group(0)], s)


def cmd_export_bibitems(args):
    entries = _load_entries()
    if args.problem_n:
        tag = f"problem{args.problem_n}"
        entries = {k: e for k, e in entries.items() if tag in (e.get("note") or "")}
    if args.verified_only:
        entries = {k: e for k, e in entries.items() if e.get("verified") == "verified"}

    if not entries:
        print("% [cite] 无匹配记录可导出")
        return

    for key, e in entries.items():
        author = _tex_escape(e.get("author", ""))
        year = _tex_escape(e.get("year", "n.d."))
        title = _tex_escape(e.get("title", ""))
        journal = _tex_escape(e.get("journaltitle", ""))
        doi = _tex_escape(e.get("doi", ""))
        tail = f" {journal}." if journal else ""
        if doi:
            tail += f" DOI: {doi}."
        elif e.get("url"):
            tail += f" {_tex_escape(e['url'])}."
        print(f"\\bibitem{{{key}}}")
        print(f"{author} ({year}). {title}.{tail}")
        print()


def main():
    p = argparse.ArgumentParser(description="AutoMCM-Pro 文献引用注册/核验/导出")
    sub = p.add_subparsers(dest="cmd")

    pr = sub.add_parser("register", help="注册一条引用（自动去重）")
    pr.add_argument("--title", required=True)
    pr.add_argument("--author", default="")
    pr.add_argument("--year", default="")
    pr.add_argument("--journal", default="")
    pr.add_argument("--doi", default="")
    pr.add_argument("--url", default="")
    pr.add_argument("--entry-type", default="article", dest="entry_type")
    pr.add_argument("--problem-n", type=int, default=0, dest="problem_n")

    pv = sub.add_parser("verify", help="核验真实性（DOI→CrossRef，URL→HEAD 请求）")
    pv.add_argument("--doi", default="")
    pv.add_argument("--key", default="")

    pl = sub.add_parser("list", help="列出已注册引用")
    pl.add_argument("--problem-n", type=int, default=0, dest="problem_n")

    pe = sub.add_parser("export-bibitems", help="渲染为 \\bibitem 文本，供粘贴进 main.tex")
    pe.add_argument("--problem-n", type=int, default=0, dest="problem_n")
    pe.add_argument("--verified-only", action="store_true", dest="verified_only")

    args = p.parse_args()
    dispatch = {
        "register": cmd_register, "verify": cmd_verify,
        "list": cmd_list, "export-bibitems": cmd_export_bibitems,
    }
    if args.cmd in dispatch:
        dispatch[args.cmd](args)
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
