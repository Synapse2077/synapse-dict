#!/usr/bin/env python3
"""阶段 3b-0：把库里已有词形的撇号归一到直撇 `'`。2026-08-22。

═══ 为什么 ═══
两版的撇号约定**完全相反**（`probes/intake_preflight.py` 实测）：

| | 直撇 `'` | 弯撇 `’` |
|---|---:|---:|
| 我们库（英文版建的） | **2,429** | 3 |
| 法文版 | 23 | **20,198** |

3b-1 收词时会把法文版的 `’` 一律归一成 `'`。那库里现有的 7 个弯撇行也得跟着归一，
否则全库两套约定并存 —— 用户敲 `l'homme` 和 `l’homme` 各找到一半。

═══ 7 行里有 1 行不能改名，得合并 ═══
    Naʼvis / naʼvi / naʼvis / Naʼvi / c’est carré comme en Corée / nombre d’oxydation
        → 归一后**不与已有行冲突**，直接改名
    jaune d’oeuf  → 归一后是 `jaune d'oeuf`，**该行已存在**（英文版把两种撇号写法各收了一条）
        → 合并：entry / sense / inflection 搬过去，删掉弯撇那行

⚠️ 合并后两条义项内容**逐字相同**（都是「jaune d'œuf 的异体形式」）。
   不删第二条，改成 `sense.hidden=1` —— `[[prefer-reversible-designs]]`：
   隐藏可逆（清 hidden 即恢复），删行不可逆。

⚠️ `entry.word_src` 也要一起归一 —— 阶段 3a 立的规矩是
   **`entry.word_src` 与 `dict.word` 精确相等**，改了 `word` 不改 `word_src` 就破了那道闸。
   `src_ref` **不动**（它是回源坐标，记的是 dump 里的原样，本来就该保留弯撇）。

用法（在 fr/ 目录下）：
    python3 fixes/normalize_apostrophes.py            # 干跑
    python3 fixes/normalize_apostrophes.py --apply
"""
import argparse
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

APOS = {"’": "'", "ʼ": "'", "‘": "'"}


def norm_apos(s):
    for a, b in APOS.items():
        s = s.replace(a, b)
    return s


def unaccent(s):
    nfd = unicodedata.normalize("NFD", s.lower())
    out = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return out.replace("œ", "oe").replace("æ", "ae")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ids = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    curly = sorted(w for w in ids if norm_apos(w) != w)
    rename, merge = [], []
    for w in curly:
        t = norm_apos(w)
        (merge if t in ids else rename).append((w, t))

    print("■ 库里弯撇词形 %d：改名 %d / 合并 %d" % (len(curly), len(rename), len(merge)))
    for w, t in rename:
        print("   改名 %-32r → %r" % (w, t))
    for w, t in merge:
        print("   合并 %-32r → %r (id=%d → %d)" % (w, t, ids[w], ids[t]))

    # entry.word_src 也带弯撇的
    src_curly = [(i, ws) for i, ws in con.execute("SELECT id, word_src FROM entry")
                 if norm_apos(ws) != ws]
    print("   entry.word_src 带弯撇的 %d 行（一并归一；src_ref 不动，它记的是 dump 原样）"
          % len(src_curly))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    mv_entry, mv_sense, mv_infl, mv_src, ranks, hide, dele = [], [], [], [], [], [], []
    for w, t in merge:
        src, dst = ids[w], ids[t]
        mv_entry += [(dst, r[0]) for r in con.execute(
            "SELECT id FROM entry WHERE word_id=?", (src,))]
        mv_sense += [(dst, r[0]) for r in con.execute(
            "SELECT id FROM sense WHERE word_id=?", (src,))]
        mv_infl += [(dst, r[0]) for r in con.execute(
            "SELECT id FROM inflection WHERE word_id=?", (src,))]
        # 🔴 2026-08-22 补：第一版**漏了 `sense_src`** —— 它也带 `word_id`。
        #    删掉源行之后那条证据成了孤儿（`word_id` 指向已删的 id，
        #    而它的 `sense_id` 指对了）。当天被 1.5 第一段的闸逮到，1 行。
        #    ⇒ 凡是带 `word_id` 的表都要搬：entry / sense / inflection / **sense_src**。
        mv_src += [(dst, r[0]) for r in con.execute(
            "SELECT id FROM sense_src WHERE word_id=?", (src,))]
        dele.append((src,))
        # 合并后重排 rank，并把**内容逐字相同**的重复义项隐藏（不删）
        allsids = [r[0] for r in con.execute(
            "SELECT id FROM sense WHERE word_id IN (?,?) ORDER BY word_id, rank", (dst, src))]
        seen = {}
        for r, sid in enumerate(allsids, 1):
            ranks.append((r, sid))
            key = tuple(sorted(con.execute(
                "SELECT lang, text FROM sense_gloss WHERE sense_id=?", (sid,))))
            if key in seen:
                hide.append((sid,))
            else:
                seen[key] = sid
    print("\n■ 将搬 entry %d / 义项 %d / 变形 %d / 证据 %d；删行 %d；隐藏重复义项 %d"
          % (len(mv_entry), len(mv_sense), len(mv_infl), len(mv_src), len(dele), len(hide)))
    con2 = con

    # 🔴 删行会让它身上每个非空列的计数掉 1 —— 必须**逐列从被删的行算出来**再声明。
    #    第一版只声明了 `__rows__`，闸报出 pos/gender/plural/translation/infl/exchange
    #    六列「未声明的列变了」并 rollback。那正是它该拦的：删错行就是这个形状。
    expect = {"__rows__": -len(dele)}
    if dele:
        ph = ",".join("?" * len(dele))
        ids_ = [i for (i,) in dele]
        for c in dbtool.TRACK:
            n = con2.execute(
                "SELECT count(*) FROM dict WHERE id IN (%s) "
                "AND TRIM(COALESCE(%s,''))<>''" % (ph, c), ids_).fetchone()[0]
            if n:
                expect[c] = -n
        print("■ 被删行带走的非空列：%s"
              % ", ".join("%s %+d" % (k, v) for k, v in expect.items() if k != "__rows__"))

    with dbtool.session("keep-v3-apos", expect=expect) as s:
        for w, t in rename:
            s.execute("UPDATE dict SET word=?, word_norm=? WHERE word=?", (t, unaccent(t), w))
        s.executemany("UPDATE entry SET word_id=? WHERE id=?", mv_entry)
        s.executemany("UPDATE inflection SET word_id=? WHERE id=?", mv_infl)
        s.executemany("UPDATE sense_src SET word_id=? WHERE id=?", mv_src)
        # 🔴 顺序要紧：`UNIQUE(word_id, rank)` 在**搬 word_id 的那一刻**就会撞
        #    （源行的 rank=1 撞上目标行已有的 rank=1）。
        #    ⇒ 必须**先**把两边的 rank 全挪进负数区，**再**搬 word_id，最后落最终值。
        #    第一版把"挪负数区"写在搬之后，闸当场 IntegrityError 并 rollback（干净，无损）。
        # 🔴 而且临时值必须**唯一**：`rank=-rank` 之后两边都是 -1，搬过去照样撞。
        #    用 `rank=-id`（主键唯一 ⇒ 临时 rank 必唯一）。第二版才过。
        s.executemany("UPDATE sense SET rank=-id WHERE id=?", [(i,) for _, i in ranks])
        s.executemany("UPDATE sense SET word_id=? WHERE id=?", mv_sense)
        s.executemany("UPDATE sense SET rank=? WHERE id=?", ranks)
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", hide)
        s.executemany("DELETE FROM dict WHERE id=?", dele)
        for eid, ws in src_curly:
            s.execute("UPDATE entry SET word_src=? WHERE id=?", (norm_apos(ws), eid))

    con2.close()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸 ═══")
    q = lambda x: con.execute(x).fetchone()[0]
    left = sum(1 for (w,) in con.execute("SELECT word FROM dict")
               if any(c in w for c in APOS))
    lsrc = sum(1 for (w,) in con.execute("SELECT word_src FROM entry")
               if any(c in w for c in APOS))
    checks = [
        ("dict.word 里还有弯撇的", left, 0),
        ("entry.word_src 里还有弯撇的", lsrc, 0),
        ("🔴 entry.word_src != dict.word（3a 立的规矩）",
         sum(1 for x, y in con.execute(
             "SELECT e.word_src, d.word FROM entry e JOIN dict d ON d.id=e.word_id")
             if x != y), 0),
        ("词形重复",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
        ("rank 不从 1 连续的词形",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("孤儿 sense", q("SELECT count(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id "
                         "WHERE d.id IS NULL"), 0),
        ("孤儿 entry", q("SELECT count(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
                         "WHERE d.id IS NULL"), 0),
        # 🔴 这条是补的 —— 第一版没查 sense_src，漏搬了 1 行没被发现
        ("孤儿 sense_src", q("SELECT count(*) FROM sense_src x "
                             "LEFT JOIN dict d ON d.id=x.word_id WHERE d.id IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-42s %8s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    print("\n%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
