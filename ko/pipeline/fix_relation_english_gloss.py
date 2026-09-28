#!/usr/bin/env python3
"""K30-①：关系目标是「词 ＋ 英文注」的，把链接落点解出来。ko，2026-09-27。

═══ 这一类是什么 ═══
英文版把词和它的英文释义写在同一个 `word` 字段里：

    related  '伯 eldest brother'      derived  '意味 meaning'
    related  '甲 armor'               derived  '슬기롭다 be wise'

于是 `target_norm` 解不出来 ⇒ 页面上印成**不可点的纯文本**，而 `伯`/`甲`/`意味`
这些词**库里都有**。也就是说这 131 条不是「目标不是词」，是**目标带了个尾巴**。

═══ 判据（收窄过一次，反向证据逮到的）═══
    ^(<谚文或汉字的词>)\\s+(<拉丁注，≥3 字符>)$

🔴 第一版尾段写的是「≥1 字符」，**反向证据当场逮到 7 条误伤**：
   `비타민 C`／`비타민 A`／`비타민 B`／`비타민 D` —— 那个 `C` **是词的一部分**，不是英文注。
   ⇒ 尾段要求 **≥3 字符**。收窄后在 **168,477 条已解析的边**上误伤 **0 条**。
   （另试过「且非全大写」，一分不挣 ⇒ 不加，判据取最简的那个。）

═══ 🔴 只补 `target_norm`，**不动 `target`** ═══
`target` 的约定是「源头原文，展示用，一个字不许动」（见 `dbtool.TRACK` 那条注释）。
英文注要不要从**显示**上去掉，是展示层的问题，且与 **K27**（括号内容该放哪）同一个决定 ——
那条账上明写「⚠️ 不许整批塞进 `tags`」，而 `tags` 实测是**源头标签的 JSON 数组**
（`["hangeul"]`/`["Gyeongsang"]`，27,529 条），往里塞自由文本会毁掉它的值域。
⇒ 本步**只做无损的一半**：把链接接通。显示怎么排版留给 K27 一起定。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_relation_english_gloss.py
    python3 -u ko/pipeline/fix_relation_english_gloss.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")
ANNOT = ("hanja_spelling", "alt_hanja")     # 目标是「注」不是词，有意不解析

_HEAD = r"[가-힣一-鿿㐀-䶿][가-힣一-鿿㐀-䶿·]*"
# 尾段 **≥3 字符**：见文件头（`비타민 C` 那 7 条误伤）
GLOSSED = re.compile(r"^\s*(%s)\s+([A-Za-z][A-Za-z\s,'\"\-().]{2,})$" % _HEAD)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w for w, in con.execute("SELECT word FROM dict")}

    # 🔴 **反向证据先跑**：判据打到已解析的边就是误伤，那时不许继续
    mis = [t for t, in con.execute(
        "SELECT target FROM sense_relation WHERE target_norm IS NOT NULL"
        " AND kind NOT IN (?,?)", ANNOT) if GLOSSED.match(t or "")]
    n_res = con.execute("SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL"
                        " AND kind NOT IN (?,?)", ANNOT).fetchone()[0]
    print("■ 反向证据：判据在 %s 条**已解析**的边上命中 %d 条" % (f(n_res), len(mis)))
    if mis:
        raise SystemExit("🔴 判据误伤已解析的边（%s…）—— 收窄之后再来" % mis[:5])
    print("   ✅ 零误伤")

    rows = con.execute(
        "SELECT id, kind, target FROM sense_relation WHERE target_norm IS NULL"
        " AND kind NOT IN (?,?)", ANNOT).fetchall()
    upd, unres = [], collections.Counter()
    for rid, kind, t in rows:
        m = GLOSSED.match(t or "")
        if not m:
            continue
        head = m.group(1)
        if head in words:
            upd.append((head, rid))
        else:
            unres[head] += 1
    print("\n■ 命中 %s 条；前段在 `dict` 里、可以接通链接的 **%s 条**"
          % (f(len(upd) + sum(unres.values())), f(len(upd))))
    print("   前段不在 dict 的 %s 条（%s 种）—— 那是 K21「词没收进来」，不是本步的事"
          % (f(sum(unres.values())), f(len(unres))))
    for h, n in unres.most_common(6):
        print("      %d× %r" % (n, h))

    print("\n■ 接通之后会不会造出「同一页同目标印两遍」（K34 的形状）")
    dup = 0
    for head, rid in upd:
        wid = con.execute("SELECT word_id, kind FROM sense_relation WHERE id=?", (rid,)).fetchone()
        n = con.execute("SELECT COUNT(*) FROM sense_relation WHERE word_id=? AND id<>?"
                        " AND (target=? OR target_norm=?)", (wid[0], rid, head, head)).fetchone()[0]
        dup += 1 if n else 0
    print("   %s 会撞上同页已有的同名目标 %d 条 %s"
          % ("⚠️" if dup else "✅", dup, "（记进 K34 一起处理）" if dup else ""))

    n_norm = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL").fetchone()[0]
    print("\n■ 样例 12 条：")
    for head, rid in upd[:12]:
        k, t = con.execute("SELECT kind, target FROM sense_relation WHERE id=?", (rid,)).fetchone()
        print("   %-16s %-32r → target_norm=%r" % (k, t[:32], head))
    con.close()

    if not upd:
        print("\n■ 没有要改的")
        return
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-k30-relation-english-gloss",
            expect={"sense_relation.target_norm": len(upd), "__rows__": 0},
            invalidates=[]) as s:
        s.executemany("UPDATE sense_relation SET target_norm=? WHERE id=?", upd)

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    checks = [
        ("target_norm 非空总数",
         q("SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL"),
         n_norm + len(upd)),
        # 🔴 反向：新填的 `target_norm` **一条都不许悬空**
        ("新填的落点都在 dict 里",
         q("SELECT COUNT(*) FROM sense_relation sr WHERE sr.id IN (%s)"
           " AND NOT EXISTS (SELECT 1 FROM dict d WHERE d.word = sr.target_norm)"
           % ",".join(str(r) for _h, r in upd)), 0),
        # 🔴 反向：`target` 一个字没动
        ("`target` 一条没改（仍带英文注）",
         q("SELECT COUNT(*) FROM sense_relation WHERE id IN (%s) AND target LIKE '%% %%'"
           % ",".join(str(r) for _h, r in upd)), len(upd)),
    ]
    for head, rid in [upd[0], upd[len(upd) // 2], upd[-1]]:
        got = q("SELECT target_norm FROM sense_relation WHERE id=?", rid)
        checks.append(("样例 id=%d 的落点是 `%s`" % (rid, head), got == head, True))
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-38s %9s（期望 %s）" % ("✅" if good else "🔴", name[:38], got, want))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
