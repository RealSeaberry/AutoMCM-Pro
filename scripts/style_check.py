#!/usr/bin/env python3
"""
style_check.py — 论文写作风格检查（AutoMCM_SOP.md §16）

目标：给"降低 AI 生成感"这件事一套客观、可检查的判据，而不是"让它读起来自然
一点"这种没法验证的模糊指令——跟 Kaizen（§13）同一套哲学：主观判断配合客观脚本，
不是只靠 AI 自己觉得好不好。

检查四类常见的 AI 写作特征：
  1. 分点罗列感——叙述性章节（背景/问题分析/模型评价/结论）里 itemize/enumerate
     密度过高；假设/符号说明/算法步骤这类本来就该用列表的章节不算在内
  2. 套话/口水连接词——"值得注意的是""综上所述""不难发现"这类 AI 高频填充语，
     偶尔用不是问题，同一篇论文里反复用同一句才是真正的"AI 味"
  3. 机械化过渡骨架——"首先...其次...最后..."这套三段式如果在多个章节里被
     逐字重复使用，是最明显的模板化标志
  4. 句长均匀度——同一段落内句子长度过于整齐（标准差/均值 过小）是 AI 生成文本
     的已知统计特征，人类写作句长天然参差

用法：
  python scripts/style_check.py scan --file CUMCM_Workspace/latex/main.tex
退出码：0 = 无需处理的问题，1 = 发现需要打磨的风格问题（不是"编译失败"级别的错，
是建议性质，配合 AutoMCM_SOP.md §16 的写作打磨轮次使用）
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

# 允许保留列表形式的章节关键词——这些章节按 CUMCM 论文惯例本来就该用列表
_LIST_OK_SECTION_KEYWORDS = (
    "假设", "符号", "参数", "变量说明", "算法步骤", "记号", "附录", "数据来源",
    "优点", "局限性", "缺点", "创新点", "改进方向",
)

# 参考文献是结构化的条目列表（作者-年份-标题-期刊-DOI），不是叙述性段落，
# 句长/段落长度均匀度这类"叙述文字"检查对它没有意义，直接整节排除
_NON_PROSE_SECTION_KEYWORDS = ("参考文献",)

_STOCK_PHRASES = [
    "值得注意的是", "值得一提的是", "不难发现", "不难看出", "综上所述",
    "总而言之", "由此可见", "众所周知", "毋庸置疑", "显而易见",
    "在某种程度上", "从某种意义上说", "换句话说", "需要指出的是",
    "可以看出", "由此可知", "更为重要的是", "不言而喻", "可想而知",
    "不可忽视", "不容忽视", "举足轻重",
]
_STOCK_PHRASE_THRESHOLD = 3   # 同一短语全文出现超过这个次数才算"反复套话"

_MECHANICAL_TRANSITION_RE = re.compile(r"首先.{2,60}?其次.{2,80}?最后")

_SENTENCE_SPLIT_RE = re.compile(r"[。！？]")
_MIN_SENTENCES_FOR_VARIANCE_CHECK = 3
# 人类写作句长变异系数(CV=标准差/均值)一般在 0.5~1.0，AI 生成文本常落在 0.1~0.3
# （参见 mrshibly/Humanizer 项目的统计口径）；中文学术写作本身比日常写作整齐，
# 门槛设在两者之间，避免对正常技术性表述过度敏感。
_CV_THRESHOLD = 0.20

_MIN_PARAS_FOR_LENGTH_VARIANCE_CHECK = 4
_PARA_CV_THRESHOLD = 0.25   # 段落长度变异系数低于此值视为"每段长度过于整齐"

_NGRAM_N = 6                # 中文没有天然词边界，用定长字符 n-gram 近似"短语"
_NGRAM_REPEAT_THRESHOLD = 4  # 同一 n-gram 全文出现次数达到此值才算可疑
_NGRAM_MIN_SECTIONS = 2      # 且至少跨这么多个不同章节出现，避免误伤局部术语反复
# 数字、纯标点、常见功能词组合会产生大量无意义 n-gram 噪音，直接跳过
_NGRAM_SKIP_RE = re.compile(r"^[\d\s，。、；：（）()%.\-]+$")


def _strip_latex_noise(text: str) -> str:
    """去掉公式/代码块/表格/注释等不该纳入"叙述性文字"统计的部分，保留正文。"""
    # 整行/行尾的 LaTeX 注释（% 开头，排除转义的 \%）——不去掉的话，
    # "%% ==== 4. 模型假设 ====" 这类分节分隔线会被当成反复出现的正文短语。
    text = re.sub(r"(?<!\\)%.*", "", text)
    text = re.sub(r"\\begin\{equation\*?\}.*?\\end\{equation\*?\}", "", text, flags=re.DOTALL)
    text = re.sub(r"\$\$.*?\$\$", "", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\\)\$[^$]*\$", "", text)
    text = re.sub(r"\\begin\{lstlisting\}.*?\\end\{lstlisting\}", "", text, flags=re.DOTALL)
    text = re.sub(r"\\lstinputlisting(\[[^\]]*\])?\{[^}]*\}", "", text)
    text = re.sub(r"\\begin\{tabular\}.*?\\end\{tabular\}", "", text, flags=re.DOTALL)
    text = re.sub(r"\\includegraphics(\[[^\]]*\])?\{[^}]*\}", "", text)
    text = re.sub(r"\\(label|ref|cite|bibitem)\{[^}]*\}", "", text)
    return text


def _split_sections(text: str) -> list[tuple[str, str]]:
    """按 \\section/\\subsection 切分，返回 [(标题, 该节正文), ...]。"""
    parts = re.split(r"(\\(?:sub)*section\*?\{[^}]*\})", text)
    sections = []
    current_title = "（前言/摘要）"
    buf = []
    for p in parts:
        m = re.match(r"\\(?:sub)*section\*?\{([^}]*)\}", p)
        if m:
            if buf:
                sections.append((current_title, "".join(buf)))
            current_title = m.group(1)
            buf = []
        else:
            buf.append(p)
    if buf:
        sections.append((current_title, "".join(buf)))
    return sections


def _is_list_ok_section(title: str) -> bool:
    return any(kw in title for kw in _LIST_OK_SECTION_KEYWORDS)


def _count_list_density(body: str) -> tuple[int, int]:
    """返回 (itemize/enumerate 环境内的 \\item 数, 段落数量估计)。"""
    items = len(re.findall(r"\\item\b", body))
    paragraphs = len([p for p in re.split(r"\n\s*\n", body) if p.strip()])
    return items, max(paragraphs, 1)


def _check_stock_phrases(full_text: str) -> list[str]:
    findings = []
    for phrase in _STOCK_PHRASES:
        n = full_text.count(phrase)
        if n > _STOCK_PHRASE_THRESHOLD:
            findings.append(f'"{phrase}" 全文出现 {n} 次（阈值 >{_STOCK_PHRASE_THRESHOLD}），'
                             f'反复使用同一句套话是常见 AI 写作特征，建议替换成不同表述或删去')
    return findings


def _check_mechanical_transition(sections: list[tuple[str, str]]) -> list[str]:
    findings = []
    hit_sections = [title for title, body in sections if _MECHANICAL_TRANSITION_RE.search(body)]
    if len(hit_sections) >= 2:
        findings.append(
            f'"首先...其次...最后..."这套机械过渡骨架在 {len(hit_sections)} 个章节'
            f'（{", ".join(hit_sections)}）里逐字重复出现，是最典型的模板化标志，'
            f'建议至少改写掉其中几处，换成更自然的论述顺序'
        )
    return findings


def _is_non_prose_section(title: str) -> bool:
    return any(kw in title for kw in _NON_PROSE_SECTION_KEYWORDS)


def _check_sentence_variance(sections: list[tuple[str, str]]) -> list[str]:
    findings = []
    for title, body in sections:
        if _is_non_prose_section(title):
            continue
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if not para or para.startswith("\\"):
                continue
            sentences = [s for s in _SENTENCE_SPLIT_RE.split(para) if len(s.strip()) >= 4]
            if len(sentences) < _MIN_SENTENCES_FOR_VARIANCE_CHECK:
                continue
            lengths = [len(s) for s in sentences]
            mean = statistics.mean(lengths)
            if mean == 0:
                continue
            cv = statistics.pstdev(lengths) / mean
            if cv < _CV_THRESHOLD:
                snippet = para[:24].replace("\n", "")
                findings.append(
                    f'【{title}】段落"{snippet}…"句长变异系数仅 {cv:.2f}'
                    f'（阈值 <{_CV_THRESHOLD}，{len(sentences)} 句长度分别为 {lengths}），'
                    f'句子长度过于整齐，人类写作通常长短参差，建议合并/拆分几句制造变化'
                )
    return findings


def _check_paragraph_variance(sections: list[tuple[str, str]]) -> list[str]:
    """段落长度（字符数）的变异系数——AI 生成文本常见"每段都差不多长"，
    人类写作段落长短天然不均（有的段落一句话点题，有的段落层层展开）。"""
    findings = []
    for title, body in sections:
        if _is_non_prose_section(title):
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n", body)
                 if p.strip() and not p.strip().startswith("\\")]
        if len(paras) < _MIN_PARAS_FOR_LENGTH_VARIANCE_CHECK:
            continue
        lengths = [len(p) for p in paras]
        mean = statistics.mean(lengths)
        if mean == 0:
            continue
        cv = statistics.pstdev(lengths) / mean
        if cv < _PARA_CV_THRESHOLD:
            findings.append(
                f'【{title}】{len(paras)} 个段落长度变异系数仅 {cv:.2f}'
                f'（阈值 <{_PARA_CV_THRESHOLD}，各段字数 {lengths}），'
                f'段落长度过于整齐，建议让部分段落更短促、部分更展开'
            )
    return findings


def _check_ngram_repetition(sections: list[tuple[str, str]]) -> list[str]:
    """定长字符 n-gram 重复检测——不依赖预先列好的套话清单，直接抓这次写作
    实际反复使用的任何短语，跨章节重复出现才计入（避免误伤局部术语讨论）。"""
    ngram_sections: dict[str, set[str]] = {}
    ngram_counts: Counter[str] = Counter()

    for title, body in sections:
        if _is_non_prose_section(title):
            continue
        # 只在纯中文/标点的连续片段上取 n-gram，跳过夹杂公式残留、命令残片的位置
        for chunk in re.split(r"[a-zA-Z0-9_\\{}\[\]$^]+", body):
            chunk = chunk.strip()
            for i in range(len(chunk) - _NGRAM_N + 1):
                gram = chunk[i:i + _NGRAM_N]
                if _NGRAM_SKIP_RE.match(gram) or len(set(gram)) <= 2:
                    continue
                ngram_counts[gram] += 1
                ngram_sections.setdefault(gram, set()).add(title)

    def _shares_long_overlap(a: str, b: str, min_overlap: int = 4) -> bool:
        """两个等长 n-gram 是否是同一处更长重复片段的相邻滑动窗口——比如
        "容量感知可服"和"量感知可服务"其实是同一个词"容量感知可服务率"错开
        一位的两个窗口，直接判子串不够（谁都不是谁的子串），要按位移对齐比对。"""
        n = len(a)
        for shift in range(-(n - 1), n):
            matches = sum(
                1 for i in range(n)
                if 0 <= i + shift < n and a[i] == b[i + shift]
            )
            if matches >= min_overlap:
                return True
        return False

    findings = []
    reported: list[str] = []
    for gram, count in ngram_counts.most_common():
        if count < _NGRAM_REPEAT_THRESHOLD:
            break  # most_common 已按频次降序，后面只会更低
        if len(ngram_sections[gram]) < _NGRAM_MIN_SECTIONS:
            continue
        if any(_shares_long_overlap(gram, r) for r in reported):
            continue
        reported.append(gram)
        findings.append(
            f'短语"{gram}"全文出现 {count} 次，跨 {len(ngram_sections[gram])} 个章节'
            f'（{", ".join(sorted(ngram_sections[gram]))}）。'
            f'⚠ 这条是纯频次统计，分不清"论文核心术语/自定义指标名"（大概率是这种，'
            f'正常且不用改）和"真的是习惯性套话"——先判断是不是本文定义的专有名词'
            f'或方法名，是的话直接跳过，只有确认是可以自由替换的表述才动手改'
        )
        if len(findings) >= 5:   # 一次扫描最多报 5 条，避免刷屏
            break
    return findings


def cmd_scan(args):
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"[style] 文件不存在: {path}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = _strip_latex_noise(raw)
    sections = _split_sections(text)

    all_findings: list[str] = []

    # 1. 分点罗列感（仅叙述性章节）
    for title, body in sections:
        if _is_list_ok_section(title):
            continue
        items, paras = _count_list_density(body)
        density = items / paras
        if items >= 4 and density > args.list_density_threshold:
            all_findings.append(
                f'【{title}】列表密度 {items} 个 \\item / {paras} 段（{density:.2f}），'
                f'超过阈值 {args.list_density_threshold}——这类叙述性章节堆砌列表是常见'
                f'"分点罗列感"，建议把部分要点改写成连贯段落'
            )

    # 2. 套话/口水连接词
    all_findings.extend(_check_stock_phrases(text))

    # 3. 机械化过渡骨架
    all_findings.extend(_check_mechanical_transition(sections))

    # 4. 句长均匀度
    all_findings.extend(_check_sentence_variance(sections))

    # 5. 段落长度均匀度
    all_findings.extend(_check_paragraph_variance(sections))

    # 6. 跨章节短语重复（不依赖预设清单，通用 n-gram 检测）
    all_findings.extend(_check_ngram_repetition(sections))

    print(f"[style] 扫描 {path}（{len(sections)} 个章节）")
    if not all_findings:
        print("[style] ✓ 未发现需要处理的风格问题")
        sys.exit(0)

    print(f"[style] 发现 {len(all_findings)} 处建议打磨的风格问题：\n")
    for i, f in enumerate(all_findings, 1):
        print(f"  {i}. {f}")
    sys.exit(1)


def main():
    p = argparse.ArgumentParser(description="AutoMCM-Pro 论文写作风格检查")
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("scan", help="扫描 main.tex 的风格问题")
    ps.add_argument("--file", required=True)
    ps.add_argument("--list-density-threshold", type=float, default=0.35,
                     dest="list_density_threshold",
                     help="叙述性章节 item/段落 比例超过此值视为列表过密（默认0.35）")

    args = p.parse_args()
    if args.cmd == "scan":
        cmd_scan(args)
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
