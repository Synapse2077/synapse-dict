#!/usr/bin/env python3
"""清掉法语释义里的 wiktextract **引用脚注**残渣。2026-08-23。

    Variante orthographique de bardot ^([2]).      →  Variante orthographique de bardot.
    Nom de famille attesté en France ^([Ins]).     →  Nom de famille attesté en France.

═══ 🔴 判据是「带不带方括号」，不是「像不像噪声」═══
`^(...)` 在 wiktextract 里是**上标**，全库 52 种取值，两类截然不同：

  带方括号 = **引用脚注**，指向我们根本没存的参考文献列表 ⇒ 对查词的人零价值，删
      ^([1]) 3,090 · ^([2]) 200 · ^([Ins]) 72 · ^([Augé 1905]) 4 · ^([*]) 3 …

  不带方括号 = **真上标内容**，删了就错 ⇒ 一个都不动
      ^(ème) 187 · ^(ère) 10 · ^(ière) 3        序数词尾（`XIX^(ème) siècle`）
      ^(-0.5) · ^(Fe2+) · ^(iπ) · ^(3n + 3)     数学/化学上标，**尖角号本身带意义**
      ^(Linné-1758) · ^(Paláu - 1784)            命名人与年份

⚠️ 我差一点写成「删掉所有 `^(...)`」—— 那会把 `10^(-0.5)` 变成 `10-0.5`，
   把「19 世纪」变成「19 世纪」的错版。**先把 52 种取值全打出来看，再定判据。**

═══ 为什么现在做 ═══
下一步要把 433,967 条法语释义送模型翻译。`[[context-you-give-leaks-into-output]]`：
喂进去的噪声会漏进中文。在翻译**之前**清掉，比翻完再修便宜。

用法（在 fr/ 目录下）：
    python3 fixes/strip_footnote_refs.py           # 干跑
    python3 fixes/strip_footnote_refs.py --apply
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 只认**带方括号**的。`[^\]]*` 不跨方括号，`\s*` 连同前面的空格一起吃掉。
# `(?:\]\)|\]?$)` = 正常闭合，**或**在行尾截断。
# 🔴 源数据里有一条 `… siècle. ^([1]` —— `]` 在、`)` 缺。我头两版判据都写窄了：
#    第一版要求 `\]\)`，第二版要求 `\[[^\]]*$`（不许含 `]`），**都漏掉这一条**。
#    只在**行尾**才放宽，否则会吃掉后面的正文。
REF = re.compile(r"\s*\^\(\[[^\]]*(?:\]\)|\]?$)")
# 不带方括号的一律不动 —— 这条断言保证我没写宽
KEEP = re.compile(r"\^\((?!\[)")


def plan(con):
    out = []
    for gid_lang_kind_seq in con.execute(
            "SELECT sense_id, lang, kind, seq, text FROM sense_gloss WHERE lang='fr'"):
        sid, lang, kind, seq, t = gid_lang_kind_seq
        if not REF.search(t):
            continue
        new = REF.sub("", t).strip()
        if new != t:
            out.append((sid, lang, kind, seq, t, new))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = plan(con)
    print("■ 要改 %s 条法语释义" % format(len(rows), ","))
    print("   删掉的脚注取值：%s"
          % Counter(m for _, _, _, _, t, _n in rows for m in REF.findall(t)).most_common(6))

    # 不变量①：改完不许留下任何**带方括号**的上标
    bad = [n for *_x, n in rows if re.search(r"\^\(\[", n)]
    # 不变量②：**不带方括号**的上标一条都不许被碰
    lost = [(t, n) for *_x, t, n in rows if len(KEEP.findall(t)) != len(KEEP.findall(n))]
    # 不变量③：**除空白外一个字符都不许动**。
    #   第一版写的是「长度 == 原长 - 被删span长」，报红 8 条 —— 全是脚注在**句首**
    #   （`^([1]) Boutique de fripes…`），`.strip()` 多吃了一个空格，我的算术写窄了。
    #   ⇒ 判据改成「抹掉全部空白后逐字相等」，既不再误报，也比长度相等**更严**。
    nows = lambda x: re.sub(r"\s+", "", x)
    grew = [(t, n) for *_x, t, n in rows if nows(REF.sub("", t)) != nows(n)]
    print("\n── 不变量 ──")
    print("   ① 改完仍含 `^([`：%d" % len(bad))
    print("   ② 真上标被误删：%d" % len(lost))
    print("   ③ 非空白字符被改动：%d" % len(grew))
    for t, n in grew[:3]:
        print("      %r\n      → %r" % (t[:90], n[:90]))
    if bad or lost or grew:
        print("\n🔴 不变量红了，**不写**")
        return 1

    print("\n── 样本 8 条 ──")
    for *_x, t, n in rows[:8]:
        print("   %-84s\n   → %s" % (t[:84], n[:84]))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    # 原文落盘留痕：本操作不可逆，先把改前的值存下来
    bak = paths.WORK / "fr_footnote_refs_before.jsonl"
    bak.parent.mkdir(parents=True, exist_ok=True)
    bak.write_text("\n".join(
        json.dumps({"sense_id": s, "lang": l, "kind": k, "seq": q, "before": t},
                   ensure_ascii=False)
        for s, l, k, q, t, _n in rows), encoding="utf-8")
    print("\n■ 改前原文已留痕 → %s" % bak)

    with dbtool.session("keep-v3-strip-footnote", expect={}) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang=? AND kind=? AND seq=?",
            [(n, sid, l, k, q) for sid, l, k, q, _t, n in rows])
    print("✓ 改了 %s 条" % format(len(rows), ","))

    con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = con2.execute(
        "SELECT count(*) FROM sense_gloss WHERE lang='fr' AND text LIKE '%^([%'").fetchone()[0]
    keep = con2.execute(
        "SELECT count(*) FROM sense_gloss WHERE lang='fr' AND text LIKE '%^(%'").fetchone()[0]
    print("■ 回查：仍含 `^([` 的 %d 条（应为 0）；仍含 `^(` 的 %s 条（真上标，应保留）"
          % (left, format(keep, ",")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
