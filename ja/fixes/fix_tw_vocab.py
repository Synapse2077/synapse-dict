#!/usr/bin/env python3
"""修：台湾说法 → 大陆说法。2026-09-16（繁简转换的收尾）。

═══ 为什么 `t2s` 修不了这个 ═══
`opencc` 的 `t2s` 只转**字形**，不转**词汇**。转完之后仍有台湾说法：
`网路`／`影印机`／`资讯`／`义大利`／`计程车`／`卢安达`。

🔴 **不用 `opencc tw2sp`**（台湾词汇→大陆词汇的配置）。它是词表驱动、比 `t2s` 激进得多，
   大概率咬到日语引用 —— 而那正是上一步花整轮量出来要保护的东西
   （`【】` 内的日文词形、含假名的引文）。为 35 处引进一个更宽的判据不划算。

═══ 🔴 这是一张**手工清单**，不是从数据推出来的判据 ═══
所以它有一个结构性缺陷：**清单漏掉的，下次不会有人发现**。
⇒ 补偿办法是把它做成回归闸的一条断言（A7），锚在这张表上 ——
   至少"已知的这些不会回潮"是守得住的。
⚠️ **推翻/扩充它需要**：有人报出新的台湾说法，或者换一份中文版 dump。

═══ 有意不改的两类 ═══
① **源头自己就给了两种说法**（`出租车/计程车/的士`、`老挝/寮国`、
   `沙特阿拉伯/沙乌地阿拉伯`）—— 10 处，那是源头在列同义，改了反而丢信息。
② **`滑鼠蛇`** —— 这是正经的中文蛇名（Ptyas mucosa），大陆也叫滑鼠蛇，不是「鼠标蛇」。
   🔴 我第一版的检测清单把它算成了台湾词汇 —— **判据又比它要描述的东西宽了一次**。

跑：
    python3 -u ja/fixes/fix_tw_vocab.py
    python3 -u ja/fixes/fix_tw_vocab.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")

# 台湾说法 → 大陆说法。⚠️ 只列**确实不同**的；`滑鼠蛇` 有意不在表里（见文件头②）。
# 值是 (大陆说法, 还算"已经有大陆说法"的其它写法)。
TW2CN = {
    "网际网路": ("互联网", ("互联网",)),
    "网路": ("网络", ("网络", "互联网")),
    "影印机": ("复印机", ("复印机",)),
    "影印": ("复印", ("复印",)),
    "资讯": ("信息", ("信息",)),
    "义大利": ("意大利", ("意大利",)),
    "计程车": ("出租车", ("出租车", "出租汽车", "的士")),
    "卢安达": ("卢旺达", ("卢旺达",)),
}
# 🔴🔴 **按长度倒序匹配。** `网路` 比 `网际网路` 短，若先匹配就把长的挡住了：
#    `网际网路，互联网` 被改成 `网际网络，互联网`（而它本该整条不动 ——
#    源头已经用 `互联网` 给了大陆说法）。
#    正则/词表的 first-match 咬人，这是我记过的第四次（`[[regex-alternation-order]]`）。
TW_ORDER = sorted(TW2CN, key=len, reverse=True)
def apply_row(t):
    """→ 新文本。

    🔴 **「源头已经给了大陆说法」这件事要按含义判，不按分隔符判。**
       第一版写的是「整行含 `/` 或 `／` 就跳过」—— 那是个形式代理，当场出两条错：
           网际网路，互联网   → 网际网络，互联网    （源头用的是逗号，不是斜杠）
           意大利语，义大利语  → 意大利语，意大利语   （改完变成重复）
       ⇒ 判据改成**逐词问**：这条里已经有大陆说法了吗？有就不动这个词。
    """
    out = t
    for a in TW_ORDER:
        b, already = TW2CN[a]
        if a == b or a not in out:
            continue
        # 源头已给大陆说法（不管用什么分隔符、也不管用的是哪个同义写法）⇒ 保持原样。
        # `出租汽车，计程车` 就是这一类：`出租汽车` 已经是大陆说法了。
        if any(x in out for x in already):
            continue
        out = out.replace(a, b)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    jobs = []
    for tbl in ("sense_gloss", "example_gloss"):
        for rid, t in con.execute(
                "SELECT rowid, text FROM %s WHERE lang='zh'" % tbl):
            new = apply_row(t or "")
            if new != t:
                jobs.append((tbl, rid, t, new))
    con.close()
    print("■ 待改 %s 条" % f(len(jobs)))
    for tbl, _r, o, n in jobs[:12]:
        print("   %-14s %s\n   %-14s %s" % ("原", o[:50], "改", n[:50]))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        return
    with dbtool.session("ja-tw-vocab", expect={
            "__rows__": 0, "#sense_gloss": 0, "#example_gloss": 0,
            "#entry": 0, "#sense": 0, "#example": 0}) as con:
        for tbl in ("sense_gloss", "example_gloss"):
            con.executemany("UPDATE %s SET text=? WHERE rowid=?" % tbl,
                            [(n, r) for t, r, _o, n in jobs if t == tbl])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = sum(1 for tbl in ("sense_gloss", "example_gloss")
               for (t,) in con.execute("SELECT text FROM %s WHERE lang='zh'" % tbl)
               if apply_row(t or "") != t)
    keep = sum(1 for (t,) in con.execute(
        "SELECT text FROM sense_gloss WHERE lang='zh' AND text LIKE '%滑鼠蛇%'"))
    print("\n   %s 台湾说法清零（剩 %d）" % ("✅" if left == 0 else "🔴", left))
    print("   %s 滑鼠蛇没被误改（%d 条，**不该是 0**）" % ("✅" if keep else "🔴", keep))
    con.close()
    if left:
        _sys.exit(1)


if __name__ == "__main__":
    main()
