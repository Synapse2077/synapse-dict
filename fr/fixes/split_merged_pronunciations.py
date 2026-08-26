#!/usr/bin/env python3
"""一行里塞了两个读音 ⇒ 拆成两行。2026-08-26（阶段 7 收尾）。

═══ 🔴 这是回归闸逮到的、由**我自己上一个修复**变出形状的缺陷 ═══
`fixes/fix_gate_reds.py` 的 A1 把没配对的定界符盲删了，于是

    源头   `\\ka.ʁe\\ \\kɑ.ʁe\\`     ← 一行里两个读音，靠定界符分隔
    我修完  `ka.ʁe  kɑ.ʁe`          ← 变成一个带双空格的畸形串

底层缺陷**在我修之前就存在**（`build_pronunciation_layer` 的 `MULTI` 只按
逗号切多读音，没管**空格分隔**这种写法）。我的修复没有制造它，
只是把它从「有定界符」换成了「有双空格」—— 两种都是错的。

⭐ 值得记：**闸逮到了「因闸而做的那次修复」留下的尾巴**。
   如果 A1 修完就收工不复跑闸，这 21 条会一直躺着，
   而且比原来更难发现（原来至少 `\\` 一眼可见）。

═══ 判据 ═══
`\\s{2,}` —— 归一后的音标里**不该有连续空格**（单空格是多词词条的正常分隔，
如 `mɔ̃ ʁwa.jom`）。21 条逐条看过，全部是「两个完整读音并排」：

    carré      ka.ʁe  kɑ.ʁe          两个法语变体（a / ɑ 对立）
    pénis      pe.nis  ˈpiːnɪs       法语 + 英语读音（跨版残留）
    août       u  ut                 两个法语变体（词尾 t 读不读）

用法（在 fr/ 目录下）：
    python3 -u fixes/split_merged_pronunciations.py           # 只报数
    python3 -u fixes/split_merged_pronunciations.py --apply   # 落库
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402

f = lambda n: format(n, ",")
GAP = re.compile(r"\s{2,}")


def plan(con):
    """→ [(旧行 id, word_id, 词形, 旧串, [拆出来的读音], notation, region, tags, src, src_ref, 是否主)]"""
    out = []
    for pid, wid, word, ipa, nota, reg, tags, src, ref, prim in con.execute(
            "SELECT p.id, p.word_id, d.word, p.ipa, p.notation, p.region, p.tags, "
            "p.src, p.src_ref, p.is_primary FROM pronunciation p JOIN dict d ON d.id=p.word_id"):
        if not ipa or not GAP.search(ipa):
            continue
        parts = [x for x in (s.strip() for s in GAP.split(ipa)) if x]
        if len(parts) < 2:
            continue
        out.append((pid, wid, word, ipa, parts, nota, reg, tags, src, ref, prim))
    return out


def gates(con, rows):
    ok = True

    def g(name, bad, n):
        nonlocal ok
        print("  %s %s：%s / %s" % ("✅" if not bad else "🔴", name, f(bad), f(n)))
        if bad:
            ok = False

    # ① 拆出来的每一段都不许再有连续空格
    g("① 拆出来的段不含连续空格",
      sum(1 for r in rows for p in r[4] if GAP.search(p)), sum(len(r[4]) for r in rows))
    # ② 🔴 **只许拆，不许丢**：拆出来的段拼回去（去掉空白）必须等于原串去掉空白
    g("② 拆完拼回去与原串逐字相同（没丢音）",
      sum(1 for r in rows if "".join(r[4]).replace(" ", "")
          != r[3].replace(" ", "")), len(rows))
    # ③ 每段都得像个音标（非空、不含定界符）
    g("③ 每段非空且不含定界符",
      sum(1 for r in rows for p in r[4] if not p or any(c in p for c in "\\/[]")),
      sum(len(r[4]) for r in rows))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = plan(con)
    print("■ 一行塞了多个读音：%s 行 → 拆成 %s 行"
          % (f(len(rows)), f(sum(len(r[4]) for r in rows))))
    for pid, wid, word, ipa, parts, *_rest in rows:
        print("   【%-20s】 %-34r → %s" % (word[:20], ipa[:34], " ｜ ".join(parts)))
    print("\n══ 闸 ══")
    ok = gates(con, rows)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1

    # 净增行数 = 拆出来的段数 - 原行数。⚠️ 可能与已有行撞 UNIQUE 而被 IGNORE 掉，
    #   所以**先算实际会插进去几条**，不能想当然（上一个脚本就是在这里翻的车）。
    have = {(w, i, n) for w, i, n in con.execute(
        "SELECT word_id, ipa, notation FROM pronunciation")}
    ins = []
    for pid, wid, word, ipa, parts, nota, reg, tags, src, ref, prim in rows:
        for k, p in enumerate(parts):
            if (wid, p, nota) in have:
                continue
            have.add((wid, p, nota))
            ins.append((wid, p, nota, reg, tags, 1 if (prim and k == 0) else 0, src, ref))
    print("\n■ 实际插入 %s 行、删除 %s 行（净 %+d）"
          % (f(len(ins)), f(len(rows)), len(ins) - len(rows)))
    with dbtool.session("keep-v3-split-pron",
                        expect={"#pronunciation": len(ins) - len(rows)}) as s:
        s.executemany(
            "INSERT INTO pronunciation (word_id,ipa,notation,region,tags,is_primary,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?)", ins)
        s.executemany("DELETE FROM pronunciation WHERE id=?", [(r[0],) for r in rows])
        # 🔴 原行若是主读音，删掉后这个词形就没主读音了（破 F4）⇒ 重选
        for pid, wid, word, ipa, parts, nota, *_r, prim in rows:
            if not prim:
                continue
            if s.execute("SELECT COUNT(*) FROM pronunciation WHERE word_id=? AND is_primary=1",
                         (wid,)).fetchone()[0] == 0:
                row = s.execute("SELECT id FROM pronunciation WHERE word_id=? "
                                "ORDER BY (notation<>'phonemic'), id LIMIT 1", (wid,)).fetchone()
                if row:
                    s.execute("UPDATE pronunciation SET is_primary=1 WHERE id=?", (row[0],))
    print("✓ 写入完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
