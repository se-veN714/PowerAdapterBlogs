"""PAdif 句子级 diff 引擎。

核心思想：散文不分行的特性，使「按行 diff」几乎无用。
本模块以「句/标点」为最小单位切分文本，再基于 difflib 做序列对比，
从而精确呈现「这一版到底改了哪几句、句内改了哪几个字」。

分段边界：
  - 句末：。 ！ ？ . ! ? … 以及段落换行（空行）
  - 句中（次级对齐，暂不单独切分，仅作未来扩展点）：， ； 、 , ; :
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List

# 句末标点（中文 + 英文 + 省略号）。注意英文句号 "." 需配合「后接空格或结尾」才断句，
# 以免误切小数、缩写等。
SENT_ENDERS = set("。！？!?…")

# 段落分隔：一个或多个空行
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def segment(text: str) -> List[str]:
    """将正文切分为句子列表（保留句末标点，去除首尾空白）。

    段落边界天然成为句子边界；空段落被忽略。
    """
    if not text:
        return []
    text = text.replace("\r\n", "\n")
    sentences: List[str] = []
    for para in _PARAGRAPH_RE.split(text):
        para = para.strip()
        if not para:
            continue
        buf: List[str] = []
        for i, ch in enumerate(para):
            buf.append(ch)
            if ch in SENT_ENDERS:
                _flush(buf, sentences)
                buf = []
            elif ch == "." and (i + 1 == len(para) or para[i + 1] == " "):
                # 英文句末：句号后接空格或段尾
                _flush(buf, sentences)
                buf = []
        # 段落内剩余（无句末标点的尾句，如英文无标点结尾）
        if buf:
            _flush(buf, sentences)
    return sentences


def _flush(buf: List[str], out: List[str]) -> None:
    seg = "".join(buf).strip()
    if seg:
        out.append(seg)


@dataclass
class DiffOp:
    """一个 diff 操作。

    op: equal | insert | delete | replace | moved
    - equal/insert/delete 的 text 为整句（或句内片段）
    - replace 的 inner 为句内字符级 diff（list[DiffOp]），text 为原句整体
    - moved 表示「内容与另一版本某句完全相同，但位置发生了移动」（句子移动检测）
    """

    op: str
    text: str
    inner: List["DiffOp"] = field(default_factory=list)


def _char_diff(a: str, b: str) -> List[DiffOp]:
    """句内字符级 diff，用于 replace 时的词/字级高亮。"""
    sm = SequenceMatcher(None, list(a), list(b), autojunk=False)
    out: List[DiffOp] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.append(DiffOp("equal", a[i1:i2]))
        elif tag == "delete":
            out.append(DiffOp("delete", a[i1:i2]))
        elif tag == "insert":
            out.append(DiffOp("insert", b[j1:j2]))
        elif tag == "replace":
            out.append(DiffOp("delete", a[i1:i2]))
            out.append(DiffOp("insert", b[j1:j2]))
    return out


def _similar(x: str, y: str) -> float:
    """两句的字符级相似度（0~1），用于判断是否值得做句内字符级高亮。"""
    return SequenceMatcher(None, x, y).ratio()


def _align_blocks(del_list: List[str], ins_list: List[str],
                  del_skip: dict, ins_emit: dict) -> List[DiffOp]:
    """对齐 replace 块内的删/插句序列，复用全局移动预算（del_skip / ins_emit）。

    - 同文移动：插入侧渲染为 moved，删除侧抑制（避免同一句出现两次）；
    - 剩余句若长度相等且足够相似 → replace（句内字符级 diff，保留「行走→奔跑」级高亮）；
    - 若长度不等或相似度过低 → 退化为纯 delete / insert，避免把不相关句子做字符级误配。
    """
    out: List[DiffOp] = []
    # 插入侧：移动句渲染为 moved，其余留待对齐
    new_dj: List[str] = []
    for s in ins_list:
        if ins_emit.get(s, 0) > 0:
            ins_emit[s] -= 1
            out.append(DiffOp("moved", s))
        else:
            new_dj.append(s)
    # 删除侧：移动句抑制（不渲染），其余留待对齐
    new_di: List[str] = []
    for s in del_list:
        if del_skip.get(s, 0) > 0:
            del_skip[s] -= 1  # 移动句的旧位置不渲染，交给插入侧
        else:
            new_di.append(s)
    # 剩余做 1:1 对齐
    if len(new_di) == len(new_dj):
        for so, sn in zip(new_di, new_dj):
            if so == sn:
                out.append(DiffOp("moved", so))
            elif _similar(so, sn) >= 0.5:
                out.append(DiffOp("replace", so, _char_diff(so, sn)))
            else:
                out.append(DiffOp("delete", so))
                out.append(DiffOp("insert", sn))
    else:
        for s in new_di:
            out.append(DiffOp("delete", s))
        for s in new_dj:
            out.append(DiffOp("insert", s))
    return out


def diff_sentences(a: str, b: str) -> List[DiffOp]:
    """对比两个版本的正文，返回句子级操作序列（含移动检测）。

    - 替换（replace）类操作会额外携带 inner（句内字符级 diff）以便前端高亮。
    - 移动（moved）类操作表示「内容与另一版本某句完全相同、仅位置变化」：
      用于把段落重排产生的 del+ins 噪声收敛为中性提示，而非红绿噪声。
      判定方式：① 全局配对——删/插两端出现同文句互相配对为 moved（删除侧抑制、插入侧渲染）；
                ② 位置偏移——equal 块内句若绝对位置改变也判为 moved。
    """
    sa, sb = segment(a), segment(b)
    sm = SequenceMatcher(None, sa, sb, autojunk=False)
    # 第一遍：收集所有删 / 插句文本（含 replace 块），做全局「移动」配对
    del_pool, ins_pool = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "delete":
            del_pool.extend(sa[i1:i2])
        elif tag == "insert":
            ins_pool.extend(sb[j1:j2])
        elif tag == "replace":
            del_pool.extend(sa[i1:i2])
            ins_pool.extend(sb[j1:j2])
    move_count = {
        t: min(del_pool.count(t), ins_pool.count(t))
        for t in set(del_pool) | set(ins_pool)
    }
    # 删除侧的移动副本抑制（不渲染，避免内联视图里同一句出现两次）；
    # 插入侧的移动副本保留（在新位置以中性色展示）。两者独立计数，各消耗 move_count[t] 次。
    del_skip, ins_emit = dict(move_count), dict(move_count)

    ops: List[DiffOp] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k, s in enumerate(sa[i1:i2]):
                # 相同内容但绝对位置变化 → 移动
                if i1 + k != j1 + k:
                    ops.append(DiffOp("moved", s))
                else:
                    ops.append(DiffOp("equal", s))
        elif tag == "delete":
            for s in sa[i1:i2]:
                if del_skip.get(s, 0) > 0:
                    del_skip[s] -= 1
                    continue
                ops.append(DiffOp("delete", s))
        elif tag == "insert":
            for s in sb[j1:j2]:
                if ins_emit.get(s, 0) > 0:
                    ins_emit[s] -= 1
                    ops.append(DiffOp("moved", s))
                else:
                    ops.append(DiffOp("insert", s))
        elif tag == "replace":
            ops.extend(_align_blocks(sa[i1:i2], sb[j1:j2], del_skip, ins_emit))
    return ops


def _leaf_ops(op: DiffOp) -> List[DiffOp]:
    """展开 replace 的 inner，返回叶子级操作（equal/insert/delete）。"""
    if op.op == "replace" and op.inner:
        return op.inner
    return [op]


def build_stats(a: str, b: str) -> dict:
    """统计两版间的实际增删规模，供版本记录与统计摘要使用。

    基于移动感知的 diff：moved 不计入增删（重排不再虚增句数变化）；
    replace 按句内字符级差异分别计入字增/字删。
    """
    return stats_from_ops(diff_sentences(a, b))


def stats_from_ops(ops: List[DiffOp]) -> dict:
    """Reuse the exact existing statistics without computing the diff twice."""
    sentences_added = sum(1 for o in ops if o.op == "insert")
    sentences_removed = sum(1 for o in ops if o.op == "delete")
    chars_added = sum(len(x.text) for o in ops for x in _leaf_ops(o) if x.op == "insert")
    chars_removed = sum(len(x.text) for o in ops for x in _leaf_ops(o) if x.op == "delete")
    return {
        "chars_added": chars_added,
        "chars_removed": chars_removed,
        "sentences_added": sentences_added,
        "sentences_removed": sentences_removed,
    }


def summarize(text: str) -> dict:
    """绝对指标，用于统计摘要视图（字数 / 句数 / 段数 / 行数）。

    与 build_stats（增量）互补：前者描述两版「差多少」，本函数描述每版「有多少」。
    """
    if not text:
        return {"chars": 0, "sentences": 0, "paragraphs": 0, "lines": 0}
    text = text.replace("\r\n", "\n")
    paras = [p for p in _PARAGRAPH_RE.split(text) if p.strip()]
    # 字数：去除所有空白字符后的字符数，更接近中文「字数」直觉
    chars = len(re.sub(r"\s", "", text))
    return {
        "chars": chars,
        "sentences": len(segment(text)),
        "paragraphs": len(paras),
        "lines": text.count("\n") + 1,
    }


def to_dict(ops: List[DiffOp]) -> list:
    """将 DiffOp 序列序列化为 JSON 友好的 dict 列表。"""

    def conv(op: DiffOp) -> dict:
        d = {"op": op.op, "text": op.text}
        if op.inner:
            d["inner"] = [conv(x) for x in op.inner]
        return d

    return [conv(o) for o in ops]
