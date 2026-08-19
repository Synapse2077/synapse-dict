#!/usr/bin/env python3
"""`-ectomia`（切除）与 `-tomia`（切开）译反了的：逐条判、逐条改。2026-08-16。

═══ 来历 ═══
我手工抽读时撞见 `imenectomia` 被译成「处女膜切开术」，实际该是「切除术」——
而且**法语源头自己就写错了**（写成 `-otomia`）。这是「源保真」与「事实正确」的分野：
中文忠实地翻译了一个错的来源。

请 v4-pro 想办法时，它建议用**医学词缀的确定性映射**整批捞：
`-ectomia`→切除术 / `-tomia`→切开术 / `-ite`→炎 / `-osi`→症 / `-oma`→瘤 …

═══ 🔴 但这条建议一碰数据就散了 ═══
按后缀做映射，实测 780 条命中、231 条"对不上"，而**对不上的几乎全是假阳性**：

    accademia   学院      ← 碰巧以 -emia 结尾，不是血症
    nostalgia   乡愁      ← 碰巧以 -algia 结尾，不是痛
    anatomia    解剖学    ← -tomia 在这里不是"切开术"
    spettroscopia 光谱学  ← -scopia 是"观测"不是"镜检"
    xerostomia  口干症    ← -stomia 是"口"不是"造口"
    plastica    塑料

后缀本身是**多义**的，不能拿来当映射表。⇒ 建议听着确定性，其实不是。

═══ 能救的只有一条：互为反义的那一对 ═══
`-ectomia`（切除，excision）与 `-tomia`（切开，incision）在外科上**方向相反**，
译反了就是硬错。判据从「必须映射到 X」收窄成「**不许映射到相反的那个词**」：

    -ectomia 的中文含「切开」  ⇒ 可疑
    -tomia   的中文含「切除」  ⇒ 可疑（先排除 -ectomia / -stomia 这两个更长的后缀）

实测只逮到 9 条，我逐条判过，6 条真错、3 条其实是对的：

    ✅ ovariotomia    卵巢切除术  —— ovariotomy 历史上就指摘除卵巢
    ✅ lobotomia      脑白质切断术 —— 已有"切断"
    ✅ sequestrotomia 死骨切除术  —— 死骨本就是取出，通行译名

⚠️ 产出很小（6 条），但这一类错**没有任何别的检查能抓到** ——
   它不违反任何结构不变量，中文也读得通，只有懂外科术语才看得出来。

用法（在 it/ 目录下）：
    python3 fixes/fix_surgical_suffix.py
    python3 fixes/fix_surgical_suffix.py --apply
    python3 fixes/fix_surgical_suffix.py --verify
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402

NEW_SRC_SUFFIX = "+fix:surgical"

# 逐条判的结果写在明处。键是词形，值是 (旧中文里要替换的片段, 新片段)；
# 值为 None 表示**判定原文是对的，不改**。
BY_HAND = {
    # -ectomia 是切除，不是切开
    "uretrectomia":     ("切开", "切除"),
    "sinfisiectomia":   ("切开", "切除"),
    "imenectomia":      ("切开", "切除"),
    # -tomia 是切开，不是切除
    "frenulotomia":     ("切除", "切开"),
    "stapedotomia":     ("切除", "切开"),   # 切除是 stapedectomia，另一个词
    "caudotomia":       ("切除", "切断"),
    # 判定为**对的**，不改
    "ovariotomia":      None,   # ovariotomy 历史上就指摘除卵巢
    "lobotomia":        None,   # 已有「切断」
    "sequestrotomia":   None,   # 死骨本就是取出，通行译名
}


def candidates(con):
    """→ [(word, sense_id, zh)]，命中「译成了相反那个词」的。"""
    out = []
    for w, sid, zh in con.execute(
            "SELECT d.word, g.sense_id, g.text FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0"):
        lw = w.lower()
        if lw.endswith(("ectomia", "ectomie")) and "切开" in zh:
            out.append((w, sid, zh))
        elif (lw.endswith(("tomia", "tomie"))
              and not lw.endswith(("ectomia", "ectomie", "stomia", "stomie"))
              and "切除" in zh):
            out.append((w, sid, zh))
    return out


def plan(con):
    rows, skipped = [], []
    for w, sid, zh in candidates(con):
        rule = BY_HAND.get(w, "UNJUDGED")
        if rule is None:
            skipped.append((w, zh, "判定原文正确"))
        elif rule == "UNJUDGED":
            skipped.append((w, zh, "🔴 新出现、我还没判过"))
        else:
            old, new = rule
            rows.append((w, sid, zh, zh.replace(old, new)))
    return rows, skipped


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    rows, skipped = plan(con)
    unjudged = [x for x in skipped if x[2].startswith("🔴")]
    checks = [
        ("🔴 已判为错的都已改掉", len(rows), 0),
        # 🔴 已接受基线 + 理由：3 条逐条判定为**原文正确**（见 BY_HAND 里的 None）
        ("🔴 没有我没判过的新候选（有就说明源头又进了新词）", len(unjudged), 0),
        ("改过的行仍是中文行",
         q("SELECT count(*) FROM sense_gloss WHERE src LIKE ? AND lang<>'zh'",
           "%" + NEW_SRC_SUFFIX), 0),
        ("🔴 改过的行不许再含相反的那个词",
         sum(1 for w, t in con.execute(
             "SELECT d.word, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
             "JOIN dict d ON d.id=s.word_id WHERE g.src LIKE ?", ("%" + NEW_SRC_SUFFIX,))
             if (w.lower().endswith("ectomia") and "切开" in t)
             or (w.lower().endswith("tomia") and not w.lower().endswith(("ectomia", "stomia"))
                 and "切除" in t)), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name, got, want))
    for w, zh, why in unjudged:
        print("     ⚠️ %-22s %s" % (w[:22], zh[:34]))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows, skipped = plan(ro)
    print("■ 将改 %d 条" % len(rows))
    for w, _sid, old, new in rows:
        print("   %-20s %-26s → %s" % (w[:20], old[:26], new[:30]))
    print("\n■ 判定原文正确、不改 %d 条" % len(skipped))
    for w, zh, why in skipped:
        print("   %-20s %-26s（%s）" % (w[:20], zh[:26], why))
    ro.close()
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)" if not a.apply else "")
        return 0
    with dbtool.session("fix-surgical-suffix", expect={"#sense_gloss": 0}) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=?, src=COALESCE(src,'unknown')||? "
            "WHERE sense_id=? AND lang='zh' AND seq=0",
            [(new, NEW_SRC_SUFFIX, sid) for _w, sid, _old, new in rows])
    print("\n■ 已改 %d 条" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
