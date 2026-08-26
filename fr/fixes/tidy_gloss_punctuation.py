#!/usr/bin/env python3
"""法语释义的**标点残渣**：句读前多余空格、句首孤立标点。2026-08-24。

    Escroquer, abuser , tromper, enfumer.   →  Escroquer, abuser, tromper, enfumer.
    , Variante orthographique de cenelle.   →  Variante orthographique de cenelle.

═══ 🔴 「空格+标点」这个判据一写就宽了 8,672 条，而对的只有 542 条 ═══
法语排版**本来就在 `;` `:` `!` `?` 前面留空格** —— `Variante de bi : travail fait en commun.`
是**正确的法语**，全库 8,135 条。只有 `.` 和 `,` 前面不留空格。
`[[criteria-narrower-than-you-think]]`：先把两类都打出来数一遍，再定判据。

再窄一层：`Microsoft .NET` 里那个空格是**对的**（产品名），`(Pavetta indica) ,` 里的不对。
⇒ 判据加上「后面必须是空白 / `)` / 行尾」，把 `.NET` `.com` 这类词首点排除掉。

句首孤立标点 152 条（`,` 102 / `.` 23 / `:` 23 / 其他 4）—— 全是抽取残渣，删。

═══ 为什么在翻译之前做 ═══
`[[context-you-give-leaks-into-output]]`：喂进去的噪声会漏进中文。
542 + 152 条不算多，但**改前是确定性的、改后要靠读中文才发现**。

用法（在 fr/ 目录下）：
    python3 fixes/tidy_gloss_punctuation.py           # 干跑
    python3 fixes/tidy_gloss_punctuation.py --apply
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

# `.` `,` 前的空格，且该标点后面是空白/右括号/行尾 ⇒ 是句读，不是 `.NET` 的词首点
SPACE_PUNCT = re.compile(r"\s+([\.,])(?=\s|\)|$)")
# 句首孤立标点（后面必须跟空白，否则 `...` 开头的省略号会被误伤）
LEAD = re.compile(r"^[\.,;:…\-–—]+\s+")
# 连续重复的逗号 `, , ,`
DUP = re.compile(r"(,\s*){2,}")


def fix(t):
    s = " ".join(t.split())
    s = DUP.sub(", ", s)
    s = SPACE_PUNCT.sub(r"\1", s)
    for _ in range(3):                       # 删掉句首标点后可能又露出一个
        n = LEAD.sub("", s)
        if n == s:
            break
        s = n
    return re.sub(r"\s+", " ", s).strip(" ,")


def plan(con):
    out = []
    for sid, lang, kind, seq, t in con.execute(
            "SELECT sense_id, lang, kind, seq, text FROM sense_gloss WHERE lang='fr'"):
        n = fix(t)
        if n != " ".join(t.split()):
            out.append((sid, lang, kind, seq, t, n))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = plan(con)
    print("■ 要改 %s 条" % format(len(rows), ","))
    print("   句首标点取值：%s"
          % Counter(m.group(0).strip() for *_x, t, _n in rows
                    for m in [LEAD.match(" ".join(t.split()))] if m).most_common())

    # ① 只许删空白和标点，**一个字母/数字都不许动**
    word = lambda x: re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]", "", x)      # noqa: E731
    moved = [(t, n) for *_x, t, n in rows if word(t) != word(n)]
    # ② 法语正确排版（`;` `:` `!` `?` 前的空格）一个都不许被碰
    fr_sp = lambda x: len(re.findall(r"\s[;:!?»]", x))            # noqa: E731
    hurt = [(t, n) for *_x, t, n in rows if fr_sp(t) != fr_sp(n)]
    # ③ 词首点（`.NET` / `.com`）不许被吃掉
    dot = lambda x: len(re.findall(r"\s\.[A-Za-z]", x))           # noqa: E731
    ate = [(t, n) for *_x, t, n in rows if dot(t) != dot(n)]
    # ④ 改完不许还剩
    left = [n for *_x, n in rows if SPACE_PUNCT.search(n) or LEAD.match(n)]
    print("\n── 不变量 ──")
    print("   ① 字母/数字被改动：%d" % len(moved))
    print("   ② 法语正确排版被误伤：%d" % len(hurt))
    print("   ③ 词首点被吃掉：%d" % len(ate))
    print("   ④ 改完仍有残渣：%d" % len(left))
    for t, n in (moved + hurt + ate)[:4]:
        print("      %r\n      → %r" % (t[:96], n[:96]))
    if moved or hurt or ate or left:
        print("\n🔴 不变量红了，**不写**")
        return 1

    print("\n── 样本 12 条 ──")
    for *_x, t, n in rows[:12]:
        print("   %-92s\n   → %s" % (" ".join(t.split())[:92], n[:92]))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    bak = paths.WORK / "fr_gloss_punct_before.jsonl"
    bak.parent.mkdir(parents=True, exist_ok=True)
    bak.write_text("\n".join(
        json.dumps({"sense_id": s, "lang": l, "kind": k, "seq": q, "before": t},
                   ensure_ascii=False) for s, l, k, q, t, _n in rows), encoding="utf-8")
    print("\n■ 改前原文已留痕 → %s" % bak)

    with dbtool.session("keep-v3-gloss-punct", expect={}) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang=? AND kind=? AND seq=?",
            [(n, sid, l, k, q) for sid, l, k, q, _t, n in rows])
    print("✓ 改了 %s 条" % format(len(rows), ","))

    con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rest = sum(1 for (t,) in con2.execute("SELECT text FROM sense_gloss WHERE lang='fr'")
               if SPACE_PUNCT.search(t) or LEAD.match(t))
    good = sum(1 for (t,) in con2.execute("SELECT text FROM sense_gloss WHERE lang='fr'")
               if re.search(r"\s[;:!?]", t))
    print("■ 回查：仍有残渣 %d 条（应为 0）；法语正确排版 %s 条（应仍在）"
          % (rest, format(good, ",")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
