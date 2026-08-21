#!/usr/bin/env python3
"""同一个词形里**原文逐字相同**的义项并排显示 —— 藏掉多余的那几条。2026-08-19。

═══ 用户直接看得到 ═══
    Sutherland   「萨瑟兰」显示 10 遍
    medioevo     「中世纪」「陈旧观念」各显示 2 遍
    carenati     「龙骨胸鸟类」显示 2 遍

═══ 本脚本只处理**能确定性判定**的那一族：原文逐字相同 ═══
470 个重复组里，152 组的 `en` 与 `it` 原文**逐字相同** —— 那就是同一条义项被收了两遍，
不是两条意思相同的义项。成因两种，`src_ref` 一看便知：

    A1 大小写重收   kk-it:medioevo:noun#0.0  +  kk-it:Medioevo:noun#0.0
                    意语版把 `medioevo` 与 `Medioevo` 当两个条目，我们按折叠后的词形挂到了同一行
    A2 源头自重复   kk-fr:ch’:pron#0.0       +  kk-fr:ch’:pron#1.0
                    同一版同一词的两次出现，文本一模一样

剩下的 318 组是**中文翻粗了**（原文不同、中文相同，`essere` 的 being/existence 都译成「存在」），
那要重译，不在本脚本范围 —— **两件事分开做**，否则"藏掉重复"会把真义项藏没。

═══ 判据与可逆性 ═══
· 判据：同一 `word_id`，`(en 原文, it 原文, 中文)` 三元组逐字相同
· 处理：**藏**（`hidden=1`）不删 —— 证据层与 `src_ref` 全部保留，随时可翻回来
· 保留哪条：`rank` 最小的那条（也就是源头顺序里第一个出现的）
· 🔴 每组必须至少留一条可见 —— 闸里有专门断言

用法（在 it/ 目录下）：
    python3 fixes/hide_duplicate_senses.py            # 干跑
    python3 fixes/hide_duplicate_senses.py --apply
    python3 fixes/hide_duplicate_senses.py --verify
    python3 fixes/hide_duplicate_senses.py --mutate
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

SQL = """
SELECT s.id, s.word_id, s.rank,
       COALESCE((SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='en' AND seq=0),'') en,
       COALESCE((SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='it'
                 AND kind='definition' AND seq=0),'') it,
       COALESCE((SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh'
                 AND kind='equivalent' AND seq=0),'') zh
FROM sense s WHERE COALESCE(s.hidden,0)=0
"""


def groups(con):
    """→ [(留下的 id, [要藏的 id], 词形)]，只含**全部可得原文**逐字相同的组。

    🔴 "全部可得原文" = en gloss + it gloss + **`sense_src.text`**。
       第一版只比前两个，结果 152 组里只逮到 29 —— 差的 123 组是 fr 版来的，
       **法语原文根本不落 `sense_gloss`，它在 `sense_src.text` 里**
       （`ch’` 两条的法语都是 `Élision de « che » devant une voyelle.`，逐字相同）。
       少比一处证据就等于拿不完整的依据判"是不是同一条"—— 这正是 A28 那类错误。
    """
    src_of = defaultdict(list)
    for sid, t in con.execute(
            "SELECT sense_id, text FROM sense_src WHERE sense_id IS NOT NULL"):
        if (t or "").strip():
            src_of[sid].append(t.strip())
    by = defaultdict(list)
    for sid, wid, rank, en, it, zh in con.execute(SQL):
        key = (wid, en, it, zh, "\u0000".join(sorted(src_of.get(sid, []))))
        by[key].append((rank, sid))
    out = []
    for key, rows in by.items():
        if len(rows) < 2:
            continue
        wid, en, it, zh, src = key
        # 🔴 一点原文都没有的不参与：那种情况下"逐字相同"证明不了是同一条义项
        if not (en or it or src) or not zh:
            continue
        rows.sort()
        out.append((rows[0][1], [r[1] for r in rows[1:]], wid))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    left = groups(con)
    checks = [
        ("🔴 原文逐字相同的重复义项组", len(left), 0),
        # 🔴 藏过头的反面：每个原来有可见义项的词形，现在仍要有
        ("🔴 藏完之后一条可见义项都不剩的词形",
         q("SELECT count(*) FROM (SELECT s.word_id FROM sense s GROUP BY s.word_id "
           "HAVING sum(CASE WHEN COALESCE(s.hidden,0)=0 THEN 1 ELSE 0 END)=0 "
           "AND sum(CASE WHEN COALESCE(s.hidden,0)=1 THEN 1 ELSE 0 END)>0 "
           "AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh'))"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-40s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def mutate():
    """判据变异：拿构造数据验「什么算重复、什么不算」。"""
    print("═══ 变异验证：判据本体 ═══")
    import tempfile
    db = Path(tempfile.mkdtemp()) / "m.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
      CREATE TABLE sense(id INTEGER PRIMARY KEY, word_id INT, rank INT, hidden INT DEFAULT 0);
      CREATE TABLE sense_gloss(sense_id INT, lang TEXT, kind TEXT, seq INT, text TEXT);
      CREATE TABLE sense_src(sense_id INT, text TEXT);
    """)
    def add(sid, wid, rank, en, it, zh):
        con.execute("INSERT INTO sense VALUES(?,?,?,0)", (sid, wid, rank))
        for lang, kind, t in (("en", "equivalent", en), ("it", "definition", it),
                              ("zh", "equivalent", zh)):
            if t:
                con.execute("INSERT INTO sense_gloss VALUES(?,?,?,0,?)", (sid, lang, kind, t))
    add(1, 10, 1, "arm", "", "手臂")
    add(2, 10, 2, "arm", "", "手臂")          # 逐字相同 ⇒ 该藏
    add(3, 10, 3, "upper arm", "", "手臂")    # 中文相同但原文不同 ⇒ **不该藏**（翻粗了，另修）
    add(4, 11, 1, "", "", "只有中文")          # 一点原文都没有 ⇒ 不参与
    add(5, 11, 2, "", "", "只有中文")
    # 🔴 只有 sense_src 有原文（fr 版就是这样）：法语逐字相同 ⇒ 该藏
    add(6, 12, 1, "", "", "省音形式")
    add(7, 12, 2, "", "", "省音形式")
    con.execute("INSERT INTO sense_src VALUES(6,'Élision de « che »')")
    con.execute("INSERT INTO sense_src VALUES(7,'Élision de « che »')")
    # 同上但法语不同 ⇒ 不许藏
    add(8, 13, 1, "", "", "省音形式")
    add(9, 13, 2, "", "", "省音形式")
    con.execute("INSERT INTO sense_src VALUES(8,'Élision de « che »')")
    con.execute("INSERT INTO sense_src VALUES(9,'Élision de « di »')")
    con.commit()
    got = groups(con)
    cases = [
        # ⚠️ 期望值是**全局要藏的 id 列表**：加了 sense_src 那两族用例之后，7 也该在里面。
        #    第一版没改期望，报「判据有问题」—— 是用例过期，不是判据错。
        ("🔴 原文+中文都相同 → 藏一条", sorted(x for g in got for x in g[1]), [2, 7]),
        ("🔴 中文相同但原文不同 → 不许藏", 3 in [x for g in got for x in g[1]], False),
        ("🔴 一点原文都没有的不参与判定", 5 in [x for g in got for x in g[1]], False),
        ("🔴 原文只在 sense_src 里也要比（fr 版）", 7 in [x for g in got for x in g[1]], True),
        ("🔴 sense_src 原文不同 → 不许藏", 9 in [x for g in got for x in g[1]], False),
        ("保留的是 rank 最小那条", sorted(g[0] for g in got), [1, 6]),
    ]
    ok = True
    for name, a, b in cases:
        good = a == b
        ok &= good
        print("   %s %-40s → %s" % ("✅" if good else "🔴", name, a))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate", "all"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    gs = groups(ro)
    hide = [i for _k, ids, _w in gs for i in ids]
    print("■ 重复组 %s，要藏 %s 条义项" % (f(len(gs)), f(len(hide))))
    seen = 0
    for keep, ids, wid in gs:
        if seen >= (999 if a.all else 15):
            break
        w = ro.execute("SELECT word FROM dict WHERE id=?", (wid,)).fetchone()[0]
        zh = ro.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' "
                        "AND seq=0", (keep,)).fetchone()
        print("   %-22s 「%s」留 1 条、藏 %d 条"
              % (w[:22], (zh[0] if zh else "")[:18], len(ids)))
        seen += 1
    ro.close()
    if not a.apply or not hide:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("hide-duplicate-senses", expect={"__rows__": 0}) as s:
        s.execute("UPDATE sense SET hidden=1 WHERE id IN (%s)"
                  % ",".join(str(i) for i in hide))
        s.written = len(hide)
    print("\n■ 已藏 %s 条" % f(len(hide)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
