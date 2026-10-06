#!/usr/bin/env python3
"""W16 的后一半：把**中文译文**里跟着译出来的本版外语释义切掉。vi，2026-10-05。

═══ 为什么这一步必须有，而且必须在这里 ═══
`build_example_layer.py --sync` 已经把 `example.text_pub`（出版正文）填好了 ——
页面上不再印 `Nắng to : il fait grand soleil.` 的法语尾巴。
🔴🔴 **但中文译文那一列是 6e 花钱买的，它买的时候是按整格买的。** 实测 52 条里：

    ①两半都译 ⇒ **中文说两遍**        18  `大官：大人物，大人物。` `大树：一棵大树。`
    ②尾巴没译 ⇒ **法语漏进中文列**     4  `网球：balle de tennis。`
  🔴③头没译 ⇒ **越南语漏进中文列**     2  `Ang nước：水罐。`（方向反过来，更坏）
    ④模型自己丢了尾巴（对的）           7  `制动鼓`

⇒ 不修的话：页面上越南语正文已经干净了，而紧挨着的中文还在说两遍／还印着法语。
  **只修一半比不修更难发现** —— 读者看不见原文里有尾巴，只看见中文莫名重复。

═══ 🔴 为什么是免费的（`[[prove-free-path-before-quoting]]`）═══
重译 52 条的成本约 0.0002 元，可以忽略 —— **但钱不是重点，重点是不该重译**：
译文已经在那里了，要的那一半就是分隔符前面那一段。**确定性切分比重新问模型可靠**
（重译会引入新的不确定性，而 W21 那 17 条刚证明重译可能**不收敛**）。

四种情形里：
  ①② 留分隔符**前面**那一段（它是越南语正文的中文）
  ③  留分隔符**后面**那一段 —— 逐条读过，`水罐` 正是 `Ang nước`、
     `老吝啬鬼` 正是 `ông già ke`，中文本身是对的，错的只是模型把越南语原文抄了上来。
     ⚠️ 这不是推的，是**两条都读了原文和法语释义核过**。
  ④  一段 ⇒ 不动

═══ ⚠️ 判据只有一个家 ═══
「哪些行被切了」**不重判** —— 直接问库：`text_pub != text`。
那一列是 `S6.split_edition_gloss()` 的产物，本脚本不许自己再调一遍判据
（调一遍就有两份口径，而 ko 的外锚闸正是栽在这上面）。

用法：
    python3 -u vi/fixes/fix_w16_edition_gloss.py            # 只报，逐条打印
    python3 -u vi/fixes/fix_w16_edition_gloss.py --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool                                             # noqa: E402
import paths                                              # noqa: E402
import stage6_sources as S6                               # noqa: E402

F = lambda n: format(n, ",")                              # noqa: E731

# 中文译文里，模型用来对应源头分隔符的那几个符号。
# ⚠️ 全角半角都要（模型在中文里多半用全角），破折号那一族跟着源头走。
# ⚠️ 破折号那一支**不要求两侧有空格** —— 中文不用空格分词，模型写的是
#    `轻飘飘――失重`。要求空格的话这个切点看不见，只剩括号里面那个 `：`，
#    于是切出 `轻飘飘――失重（字面意思`（第一版就是这么坏的）。
_ZH_SEP = re.compile(r"\s*[:：]\s*|\s*[—―–]{1,2}\s*")
# 🔴 「有没有汉字」交给 Unicode 的区段，**不手抄范围** ——
#    ko 那边手写字符类差点删掉 5 条正确释义（化学元素汉字名在 CJK 扩展平面）。
_HAN = re.compile(r"[㐀-䶿一-鿿\U00020000-\U0003ffff豈-﫿]")


def _decide(zh):
    """中文译文该留哪一段。→ (新中文, 情形)；不动时新中文 is None

    🔴🔴 **按分隔符位置从左到右试，取第一个「切完括号还配对」的切点。**
       第一版图省事用 `_ZH_SEP.split()` 一次切完再取 `segs[0]`，当场切坏一条：
           `轻飘飘――失重（字面意思：“非常轻”）`  →  `轻飘飘――失重（字面意思`
       模型在括号**里面**又写了一个 `：`，而 `segs[0]` 认的是**最左边**那个分隔符
       —— 可它刚好不是括号外面那个。按位置逐个试就自然挑中 `――`。
    ⚠️ `brackets_balanced` **import 自 `stage6_sources`**，与源头侧切割用的是
       同一个函数（`[[criteria-from-meaning-not-form]]`：判据只有一个家）。
    """
    t = (zh or "").strip()
    cuts = list(_ZH_SEP.finditer(t))
    if not cuts:
        return None, "④模型自己丢了尾巴 ⇒ 不动"
    # ①② 前半是中文 ⇒ 留前半
    for m in cuts:
        head = t[:m.start()].strip()
        if not head or not S6.brackets_balanced(head):
            continue
        if _HAN.search(head):
            rest = t[m.end():]
            kind = ("①两半都译 ⇒ 留前半" if _HAN.search(rest)
                    else "②尾巴没译（外语漏进中文列）⇒ 留前半")
            return head.strip(" 。，、"), kind
    # ③ 前半不是中文（模型把越南语原文抄上来了）⇒ 留后半
    for m in cuts:
        head, rest = t[:m.start()].strip(), t[m.end():].strip()
        if head and not _HAN.search(head) and _HAN.search(rest) \
                and S6.brackets_balanced(rest):
            return rest.strip(" 。，、"), "🔴③头没译（越南语漏进中文列）⇒ 留后半"
    return None, "⚠️ 没有安全的切点 ⇒ 不动，另记"


def plan(con):
    """→ [(gloss 行 rowid, example_id, 词, 原文, 出版正文, 旧中文, 新中文, 情形)]"""
    rows = []
    for gid, eid, w, t, pub, zh in con.execute(
            "SELECT g.rowid, x.id, d.word, x.text, x.text_pub, g.text "
            "  FROM example x JOIN dict d ON d.id = x.word_id "
            "  JOIN example_gloss g ON g.example_id = x.id AND g.lang = 'zh' "
            " WHERE x.hidden = 0 AND x.text_pub IS NOT NULL AND x.text_pub <> x.text "
            " ORDER BY x.id"):
        new, kind = _decide(zh)
        rows.append((gid, eid, w, t, pub, zh, new if new else zh, kind))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cut = con.execute("SELECT COUNT(*) FROM example "
                      "WHERE text_pub IS NOT NULL AND text_pub <> text").fetchone()[0]
    pubcut = con.execute("SELECT COUNT(*) FROM example WHERE hidden=0 "
                         "AND text_pub IS NOT NULL AND text_pub <> text").fetchone()[0]
    print("■ 出版正文与证据层不同的行：%s（其中可出版 %s）" % (F(cut), F(pubcut)))
    rows = plan(con)
    con.close()
    k = collections.Counter(r[7] for r in rows)
    print("\n■ 中文译文要怎么处理（%s 条有中文）" % F(len(rows)))
    for a_, b in k.most_common():
        print("   %-42s %3d" % (a_, b))
    # 🔴 **52 条全部打出来逐条读** —— 这个量级不抽样。
    #    `[[verification-gates-not-sampling]]`：别把义项和释义错配了。
    print("\n■ 逐条（改了的）")
    for gid, eid, w, t, pub, zh, new, kind in rows:
        if new == zh:
            continue
        print("   %-12s 原文 %s" % (w, t[:72]))
        print("   %-12s 出版 %s" % ("", pub[:72]))
        print("   %-12s 中文 %s  ⇒  %s   [%s]" % ("", zh[:46], new[:40], kind))
    upd = [(r[6], r[0]) for r in rows if r[6] != r[5]]
    print("\n■ 要改 %s 条中文译文" % F(len(upd)))
    if not a.apply:
        print("\n(只报不写。加 --apply。)")
        return
    if not upd:
        return
    with dbtool.session("vi-w16-trim-zh-gloss",
                        expect={"__rows__": 0, "example_gloss.text": 0},
                        invalidates=[]) as s:
        s.executemany("UPDATE example_gloss SET text=? WHERE rowid=?", upd)


if __name__ == "__main__":
    main()
