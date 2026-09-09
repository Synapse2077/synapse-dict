#!/usr/bin/env python3
"""ECDICT 释义的**结构**：能不能拆成「词性 + 义项组」，拆不动的有多少。2026-09-09。

═══ 起因 ═══
用户 2026-09-09：「这个展示形式和其他几门语言不统一…你得弄清楚 ecdict 释义的
展示种类，如何变化」。

en 有 **2,421,239** 个词形（60.3%）只有 ECDICT 释义，现在是**原样展示一整块文本**：

    n. 传真
    vt. 发传真
    [计] 传真系统; 传真

而其余五门（和 en 的 v3 那 34.5%）是「词性徽章 + 逐条义项」。要统一就得先把这块文本拆开。

═══ 假设的语法 ═══
    <块>  := <行>（换行分隔，96.07% 只有一行）
    <行>  := [<词性>] <义项>；<义项>；…
    <义项> := [<类别>]* <中文>

⚠️ **本探针不改数据**，只回答一个问题：**这个假设能覆盖多少，剩下的是什么。**
   拆不动的比例高，就说明假设错了，不是数据脏。

    cd en && python3 -u probes/ecdict_shape.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import random
import re
import sqlite3

import paths

# 🔴 词性是**封闭集**（实测 278 种里有效的约 30 种，尾部是 `U.S.` 这类误命中）
POS = {"n.", "v.", "vt.", "vi.", "a.", "adj.", "adv.", "ad.", "abbr.", "un.", "na.",
       "phr.", "int.", "interj.", "pron.", "prep.", "conj.", "num.", "art.", "det.",
       "pref.", "prefix.", "suf.", "suff.", "comb.", "ph.", "phrase.", "idiom.",
       "st.", "pr.", "short.", "aux.", "modal."}
POS_RE = re.compile(r"^\s*([a-zA-Z]{1,7}\.)\s+")
# 类别标记：**短**方括号。`[=xxx]`（缩写展开）和长括号是内容，不是标记。
MARK_RE = re.compile(r"^\s*\[([^\]=]{1,6})\]\s*")
SPLIT = re.compile(r"[；;]")


def parse(text):
    """→ [(pos|None, [(marks, gloss)])]，以及没吃掉的残渣"""
    out, resid = [], []
    for ln in (text or "").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        pos = None
        m = POS_RE.match(ln)
        if m and m.group(1).lower() in POS:
            pos = m.group(1).lower().rstrip(".")
            ln = ln[m.end():]
        items = []
        for seg in SPLIT.split(ln):
            seg = seg.strip()
            if not seg:
                continue
            marks = []
            while True:
                mm = MARK_RE.match(seg)
                if not mm:
                    break
                marks.append(mm.group(1))
                seg = seg[mm.end():]
            seg = seg.strip()
            if seg:
                items.append((marks, seg))
            elif marks:
                resid.append("只有标记没有正文: " + str(marks))
        if items:
            out.append((pos, items))
        elif ln:
            resid.append(ln)
    return out, resid


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = [t for t, in con.execute(
        "SELECT text FROM legacy_gloss WHERE published=1")]
    con.close()
    n_pos = collections.Counter()
    n_group = collections.Counter()
    n_item = collections.Counter()
    n_mark = collections.Counter()
    resid_n = 0
    no_pos = 0
    for t in rows:
        groups, resid = parse(t)
        resid_n += len(resid)
        n_group[len(groups)] += 1
        tot_items = 0
        for pos, items in groups:
            n_pos[pos or "（无词性）"] += 1
            if pos is None:
                no_pos += 1
            tot_items += len(items)
            for marks, _ in items:
                for k in marks:
                    n_mark[k] += 1
        n_item[min(tot_items, 9)] += 1
    N = len(rows)
    print("═══ ECDICT 释义结构（出版的 %s 条）═══" % format(N, ","))
    print("\n① 拆成几组（＝几个词性块）：")
    for k in sorted(n_group)[:6]:
        print("   %d 组 %9s  %5.2f%%" % (k, format(n_group[k], ","),
                                         100 * n_group[k] / N))
    print("\n② 一共几条义项：")
    for k in sorted(n_item):
        lbl = "%d 条" % k if k < 9 else "≥9 条"
        print("   %-6s %9s  %5.2f%%" % (lbl, format(n_item[k], ","),
                                        100 * n_item[k] / N))
    print("\n③ 词性分布（组数 %s）：" % format(sum(n_pos.values()), ","))
    for k, v in n_pos.most_common(12):
        print("   %-10s %9s  %5.1f%%" % (k, format(v, ","),
                                         100 * v / sum(n_pos.values())))
    print("\n④ 类别标记（前 12）：")
    for k, v in n_mark.most_common(12):
        print("   [%s]%s %9s" % (k, " " * max(0, 6 - len(k)), format(v, ",")))
    print("\n⑤ 🔴 **拆不动的残渣：%s 处**（%.4f%%）" % (format(resid_n, ","),
                                                100 * resid_n / N))
    print("\n⑥ 随机 6 条拆解结果：")
    random.Random(7).shuffle(rows)
    for t in rows[:6]:
        g, _ = parse(t)
        print("   原文: %s" % t.replace("\n", " ⏎ ")[:74])
        for pos, items in g:
            print("     └ %-6s %s" % (pos or "—",
                                      " ／ ".join(("".join("[%s]" % x for x in m) + s)[:40]
                                                 for m, s in items)))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
