#!/usr/bin/env python3
"""阶段 4：收词 —— 把越南文版 / 中文版独有的词形收进 `dict` ＋ `entry`。2026-09-28。

`VI_PLAN` §4.1 定的第三种分工，这一步是它的下半句：

    两版都有的词 ⇒ en 定 entry 切分与 pos（阶段 1 做完了）
    **只有一版有的词 ⇒ 那一版自建 entry**   ← 本步

═══ 🔴🔴 收词会让三件事同时过期，`invalidates` **必须非空**（B3）═══
pt 就是栽在这里：变形层建在收词之前，**35.7 万个新收的词形从此没人给它们连过线**，
46.2% 的词形搜得到、点进去是空白页，而中间隔了整整两个阶段才被发现。
vi 这边过期的是：
    ① 汉字层  —— 阶段 2 有 19,133 对因为词形不在 dict 里被推迟
    ② 音标层  —— 阶段 3 有 106,638 条同理
    ③ 音标闸的覆盖率下限（P5）—— 新收的词里有一批没音标，**行数会涨而覆盖率会掉**

═══ 🔴 不收哪些，以及为什么 ═══
    表意文字词头        用户 2026-09-28 定，只喂汉字层（判据在 `criteria.is_han_headword`）
    一条 gloss 都没有   与阶段 1 同一条规则
    **gloss 全是「汉字：…」对照表**  1,789 个词形。抽 8 条全部确认：`bặng → 汉字：𠶉`。
                       那是音节→汉字表，不是释义。收进来 ＝ 读者点开看见
                       「汉字：𠶉」当释义 —— **ko 的 K10 正是这么被用户在页面上看见的**。
    **gloss 全是模板残渣** 3 个词形：`met → :Template:越參/met`
⚠️ 判据窄得刻意：只认 `汉字：` 开头与模板前缀，**绝不顺手判「中文 gloss 是不是元描述」**——
   那是欠账 **W2**，已经量过三次得到三个数，不许在这儿写第四版。

═══ ⚠️ 大小写：**421 个新词形归一后与库里已有的撞**，而这次不会丢 ═══
`Hệ Mặt Trời`（太阳系，专名）vs 库里已有的 `hệ mặt trời`（普通名词）。
es 那次按小写去重**丢了 573 个专名词头**。vi 的 `UNIQUE` 是 `(word, entry_type)`，
**大小写不同就是两行** ⇒ 结构上不会丢。
⚠️ 代价转移到检索侧：搜索必须把「精确大小写」当第一排序键，那是阶段 9 的活。

跑（在仓库根）：
    python3 -u vi/pipeline/ingest_editions.py
    python3 -u vi/pipeline/ingest_editions.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import gzip
import json
import sqlite3

import dbtool
import paths
from criteria import (is_han_headword, is_not_a_gloss, is_pointer_sense,
                      norm_vi, syllables, entry_type_of)
from build_entry_layer import POS_DOMAIN

SRC = [("vi-edition", paths.EDITION),
       ("zh-edition-trad", paths.ZH_TRAD),
       ("zh-edition-simp", paths.ZH_SIMP)]


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def scan(indict):
    words = {}
    stat = collections.Counter()
    for src, p in SRC:
        for o in rd(p):
            stat["原始行"] += 1
            w = (o.get("word") or "").strip()
            if not w:
                stat["剔除·词形是空白"] += 1
                continue
            if is_han_headword(w):
                stat["剔除·表意文字词头（→ 汉字层）"] += 1
                continue
            if w in indict:
                stat["跳过·已在 dict 里（阶段 1 收的）"] += 1
                continue
            e = words.setdefault(w, {"pos": collections.Counter(), "lemma": False,
                                     "gloss": 0, "junk": 0, "entries": []})
            e["pos"][o.get("pos")] += 1
            for se in (o.get("senses") or []):
                for g in (se.get("glosses") or []):
                    if not g.strip():
                        continue
                    if is_not_a_gloss(g):
                        e["junk"] += 1
                        continue
                    e["gloss"] += 1
                    if not is_pointer_sense(se):
                        e["lemma"] = True
            e["entries"].append((src, o.get("pos"),
                                 str(o.get("etymology_number", "0") or "0")))

    rows, ent_rows, dropped = [], [], collections.Counter()
    for w, e in sorted(words.items()):
        if not e["gloss"]:
            dropped["gloss 全是「汉字：…」对照表 / 模板残渣" if e["junk"]
                    else "一条 gloss 都没有"] += 1
            continue
        poss = [p for p, _ in e["pos"].most_common() if p]
        rows.append((w, norm_vi(w), "/".join(poss), 1 if e["lemma"] else 0,
                     entry_type_of(w, poss), syllables(w)))
        seen = collections.Counter()
        for src, pos, etym in e["entries"]:
            k = (src, pos, etym)
            seq = seen[k]
            seen[k] += 1
            ent_rows.append((w, pos, etym, seq, src,
                             "kk-%s:%s:%s:%s:%d" % (src.split("-")[0], w, pos, etym, seq)))
    stat["扫到的新词形"] = len(words)
    stat["本步收"] = len(rows)
    stat["新建 entry"] = len(ent_rows)
    return rows, ent_rows, stat, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {w for (w,) in con.execute("SELECT word FROM dict")}
    before = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    con.close()

    rows, ent_rows, stat, dropped = scan(indict)
    print("■ 扫三份本语言/中文源")
    for k in ("原始行", "剔除·词形是空白", "剔除·表意文字词头（→ 汉字层）",
              "跳过·已在 dict 里（阶段 1 收的）", "扫到的新词形", "本步收", "新建 entry"):
        if stat[k]:
            print("   %-36s %9s" % (k, format(stat[k], ",")))

    # 🔴 不收的那批要**说得出它们是什么**，否则「不收」就变成了「丢掉」
    print("\n■ 扫到了但**本步不收**的 %s 个词形：" % format(sum(dropped.values()), ","))
    for k, v in dropped.most_common():
        print("   %-38s %8s" % (k, format(v, ",")))
    print("   ⚠️ 这是**我们这一步不收**，不是源头没有。那 1,789 个的汉字表记在源头里，"
          "但它们自己进不了 `dict` ⇒ 表记也就没有落脚点，**这是有意的**。")

    et = collections.Counter(r[4] for r in rows)
    print("\n■ 新词形的 `entry_type`：%s"
          % "、".join("%s %s" % (k, format(v, ",")) for k, v in et.most_common()))
    bad = sorted({p for _, p, _, _, _, _ in ent_rows} - POS_DOMAIN)
    print("■ 新 entry 的 `pos` 落在值域外的：%s" % (bad or "无 ✅"))
    onlyunk = sum(1 for r in rows if r[2] == "unknown")
    print("   ⚠️ **词性只有 `unknown` 的新词形 %s（%.1f%%）** —— 源页面没写词性。"
          % (format(onlyunk, ","), 100 * onlyunk / len(rows)))
    print("      存成 `unknown` 而不是 NULL，是为了把「源头没写」和「我们没抽」分开。")

    print("\n■ 库的变化：dict %s → **%s**（+%s，%.0f%%）"
          % (format(before, ","), format(before + len(rows), ","),
             format(len(rows), ","), 100 * len(rows) / before))

    dbtool.sample_check(rows, 10, ("词形", "归一", "词性", "词元", "类型", "音节"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    nd, ne = len(rows), len(ent_rows)
    # 🔴🔴 `invalidates` 必须非空（B3）—— 收词让三件事同时过期
    with dbtool.session(
            "ingest-vi-editions",
            expect={"__rows__": nd, "word_norm": nd, "entry_type": nd, "is_lemma": nd,
                    "pos": nd, "syllables": nd,
                    "#entry": ne, "entry.pos": ne, "entry.etym_no": ne},
            invalidates=[
                "汉字层：阶段 2 推迟的 19,133 对里，有一批的词形这一步收进来了 ⇒ 重跑 build_han_layer.py",
                "音标层：阶段 3 推迟的 106,638 条同理 ⇒ 重跑 build_pronunciation.py",
                "音标闸 P5：新收的词里有一批没音标，**行数会涨而覆盖率会掉** ⇒ 重跑 test_pron_layer.py 并决定是补 G2P 还是调下限",
            ]) as s:
        s.executemany(
            "INSERT INTO dict (word, word_norm, pos, is_lemma, entry_type, syllables) "
            "VALUES (?,?,?,?,?,?)", rows)
        wid = {w: i for i, w in s.execute("SELECT id, word FROM dict")}
        s.executemany(
            "INSERT INTO entry (word_id, pos, etym_no, seq, src, src_ref) VALUES (?,?,?,?,?,?)",
            [(wid[w], p, e, q, sr, rf) for w, p, e, q, sr, rf in ent_rows])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), before + nd),
        ("word 唯一", q("SELECT COUNT(*) FROM (SELECT word FROM dict GROUP BY word "
                        "HAVING COUNT(*)>1)"), 0),
        ("表意词头 0 条", sum(1 for (w,) in con.execute("SELECT word FROM dict")
                              if is_han_headword(w)), 0),
        ("word_norm 与判据一致",
         sum(1 for w, n in con.execute("SELECT word, word_norm FROM dict")
             if norm_vi(w) != n), 0),
        ("没有 entry 的词形",
         q("SELECT COUNT(*) FROM dict d LEFT JOIN entry e ON e.word_id=d.id "
           "WHERE e.id IS NULL"), 0),
        ("entry.pos 在值域内",
         q("SELECT COUNT(*) FROM entry WHERE pos NOT IN (%s)"
           % ",".join("'%s'" % p for p in sorted(POS_DOMAIN))), 0),
        ("src_ref 唯一",
         q("SELECT COUNT(*) FROM (SELECT src_ref FROM entry GROUP BY src_ref "
           "HAVING COUNT(*)>1)"), 0),
        # ⚠️ 大小写那 421 个：两边都必须还在（es 那次丢了 573 个专名）
        ("大小写不同的两行都在",
         q("SELECT COUNT(*) FROM (SELECT word_norm FROM dict GROUP BY word_norm "
           "HAVING COUNT(*)>1)") > 0, True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-24s %10s（期望 %s）"
              % ("✅" if good else "🔴", name,
                 format(got, ",") if isinstance(got, int) else got,
                 format(want, ",") if isinstance(want, int) else want))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
