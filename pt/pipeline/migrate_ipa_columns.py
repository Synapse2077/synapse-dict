#!/usr/bin/env python3
"""阶段 4a：把 `dict.ipa_br` / `dict.ipa_pt` 两列迁进 `pronunciation` 表。2026-08-29。

结构照 `docs/SCHEMA.md` §2.2 与 `docs/lang/pt-CONVENTIONS.md` §四（已定案）。

═══ 为什么迁 ═══
两列装不下 pt 的音标现实（`pt-CONVENTIONS` §四实测）：
  · 巴葡/欧葡二分 —— 两列能装
  · **巴西内部方言**（`Carioca`/`Paulistana`/`Caipira`/`Gaúcha`）—— 两列装不下
  · **法语版那 179,722 条不标地区** —— 灌进哪一列都是错的
`pronunciation` 表的 `region`（null = 通用或判不出）+ `tags` + `src` 三个字段全能装。

═══ 落点 ═══
    ipa_br  84,786 → region='pt-BR'
    ipa_pt  84,625 → region='pt-PT'
    两列都有的 84,307 行里 **逐字节不同 76,921 行 = 91.2%**（真音系差异，见 §四）
    ⇒ 迁完 pronunciation 约 169,411 行，覆盖 85,104 个词形

═══ 🔴 顺手把欠了很久的账结掉：`_src` 四列建了从没回填（收尾单 C1）═══
`[[ipa-provenance-columns]]` 定的规矩：**回填证明不了就写 unknown，不猜。**
判据 = 这个值能不能在英文版 dump 里找到（那是建库主源，唯一能证明的来源）：

    ipa_br  可证 en-edition 61,938 (73.1%) ／ 证不了 22,848
    ipa_pt  可证 en-edition 60,690 (71.7%) ／ 证不了 23,935

⚠️ 证不了的那批**不是比对口径的问题**（今天已经栽过三次"量的是我的工具不是数据"，
   所以特意查了）：22,848 条里 **21,861 条（95.7%）是英文版对该词根本没给任何音标**
   （`gratis` / `abassi` / `google`）⇒ 那些值来自我们自己的流水线
   （当年 `b_translate.py` 的豆包兜底 / `fill_ipa_dual.py`）。
   能证明的是「**不是 dump 给的**」，但证不明是哪一个写的 ⇒ 一律 `unknown`。

⭐ 这个数本身是质量事实：**pt 的无源背书音标约 26.9%**（es 那轮是 3.1%）。

═══ 🔴 `notation` 怎么定 ═══
`SCHEMA` 的值域是 `phonemic | narrow`。两列存的都是**音位式**（建库时从 `sounds[].ipa`
取的，kaikki 的 `/…/` 已剥）⇒ 一律 `phonemic`。
⚠️ **不猜 narrow** —— 音值式（`[…]`）的引入归 4b 跨版收割，那时按定界符判。

═══ 闸 ═══
① **可逆性回核**：从 `pronunciation` 重建 `ipa_br`/`ipa_pt` 两列，与原列**逐字节**比对。
   100% 非抽样。这是本步唯一能证明"没搬错"的东西。
② 不变量断言：行数守恒 / 无孤儿 / `region` 只有两个值 / `notation` 全是 phonemic /
   UNIQUE(word_id,ipa,notation) 没有把不同的值合并掉。
③ 抽样反验：随机打印，人眼看。

⚠️ **原列不删**（冻结成迁移锚点，同阶段 0 对 `definition` 的处置）——
   `portuguese.ts` 还在读它们，阶段 8 才重写。在那之前它们是**只读的**。

用法（在 pt/ 目录下）：
    python3 pipeline/migrate_ipa_columns.py            # 干跑 + 闸
    python3 pipeline/migrate_ipa_columns.py --apply
    python3 pipeline/migrate_ipa_columns.py --verify
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

COLS = [("ipa_br", "pt-BR"), ("ipa_pt", "pt-PT")]


def en_pool():
    """英文版 dump 里每个词形的 ipa 集合 —— 唯一能证明来源的东西。"""
    pool = defaultdict(set)
    with open(paths.KK, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "pt":
                continue
            w = (e.get("word") or "").strip()
            for s in (e.get("sounds") or []):
                if s.get("ipa"):
                    pool[w].add(s["ipa"].strip("/[]"))
    return pool


def collect(con, pool):
    """→ rows, stat。**只搬不改**：音标字符串一个字节都不动。"""
    rows, stat = [], Counter()
    for rid, w, br, pt in con.execute(
            "SELECT id, word, ipa_br, ipa_pt FROM dict "
            "WHERE TRIM(COALESCE(ipa_br,''))<>'' OR TRIM(COALESCE(ipa_pt,''))<>'' ORDER BY id"):
        br = (br or "").strip() or None
        pt = (pt or "").strip() or None
        # 🔴 两种读音**逐字节相同**时存一条 `region=NULL`，不是两条。
        #    起因：第一版直接按列插两行，撞了 `UNIQUE(word_id, ipa, notation)` ——
        #    那两行只差 `region`，而 UNIQUE 不含它。
        #    ⚠️ 正确的处置**不是放宽 UNIQUE**（那会把"通用"和"两地碰巧一样"混为一谈），
        #      是**承认语义**：两个变体读音相同时地区区分没有意义，
        #      而 schema 注释原文就是「null = **通用**或判不出」。
        #    实测这样的行 7,386 条（两列都有值的 84,307 行里 8.8%）。
        #    ⭐ 可逆性不受影响：回核时 `region=NULL` 同时重建两列（见 `rebuild()`）。
        if br is not None and br == pt:
            pairs = [(br, None)]
            stat["两地读音相同（存一条 region=NULL）"] += 1
        else:
            pairs = [(v, r) for v, (c, r) in zip((br, pt), COLS) if v]
        for val, region in pairs:
            col = "ipa_br" if region == "pt-BR" else "ipa_pt" if region == "pt-PT" else "both"
            provable = val.strip("/[]") in pool.get(w, set())
            src = "en-edition" if provable else "unknown"
            stat["%s·总" % col] += 1
            stat["%s·%s" % (col, src)] += 1
            # src_ref：可证的指回 dump 坐标；证不了的**如实写没有坐标**，不编一个
            ref = ("kk-en:%s#ipa" % w) if provable else "legacy:dict.%s#%d" % (col, rid)
            rows.append((rid, val, "phonemic", region, None, None, 0, src, ref))
    return rows, stat


def rebuild(con):
    """从 `pronunciation` 反推两列 → {列: {dict.id: 值}}。**不读原列**，否则回核是自证。"""
    out = {c: {} for c, _ in COLS}
    for wid, ipa, region in con.execute(
            "SELECT word_id, ipa, region FROM pronunciation WHERE notation='phonemic'"):
        if region is None:                 # 通用：两列都由它重建（见 collect() 那段注释）
            for col, _ in COLS:
                out[col][wid] = ipa
        else:
            for col, r in COLS:
                if region == r:
                    out[col][wid] = ipa
    return out


def gate1(con, orig):
    print("\n═══ 闸① 可逆性回核（全量，非抽样）═══")
    got = rebuild(con)
    ok = True
    for col, _ in COLS:
        o, g = orig[col], got[col]
        bad = [k for k in set(o) | set(g) if o.get(k) != g.get(k)]
        ok &= not bad
        print("   %-8s %s" % (col, "✓ 逐字节一致（%s 行）" % f"{len(o):,}"
                              if not bad else "🔴 %d 行对不上" % len(bad)))
        for k in bad[:5]:
            print("      id=%s 原=%r 建=%r" % (k, o.get(k), g.get(k)))
    return ok


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("pronunciation 行数 == 期望", q("SELECT count(*) FROM pronunciation"), expect),
        ("孤儿 pronunciation",
         q("SELECT count(*) FROM pronunciation p LEFT JOIN dict d ON d.id=p.word_id "
           "WHERE d.id IS NULL"), 0),
        # region 允许三个值：pt-BR / pt-PT / NULL（通用，两地读音相同）
        ("region 不是 pt-BR/pt-PT/NULL 的",
         q("SELECT count(*) FROM pronunciation "
           "WHERE region IS NOT NULL AND region NOT IN ('pt-BR','pt-PT')"), 0),
        ("notation 不是 phonemic 的",
         q("SELECT count(*) FROM pronunciation WHERE notation<>'phonemic'"), 0),
        ("🔴 ipa 首尾带定界符（应已剥）",
         q("SELECT count(*) FROM pronunciation WHERE ipa LIKE '/%' OR ipa LIKE '[%'"), 0),
        ("src 不在 {en-edition, unknown}",
         q("SELECT count(*) FROM pronunciation WHERE src NOT IN ('en-edition','unknown')"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-40s %10s  期望 %s" % ("✓" if good else "🔴", name,
                                            f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    orig = {c: {} for c, _ in COLS}
    for rid, br, pt in con.execute("SELECT id, ipa_br, ipa_pt FROM dict"):
        for val, (col, _) in zip((br, pt), COLS):
            if val and val.strip():
                orig[col][rid] = val

    if a.verify:
        ok1 = gate1(con, orig)
        n = con.execute("SELECT count(*) FROM pronunciation").fetchone()[0]
        ok2 = gate2(con, n)          # verify 时行数以现状为准，只查结构不变量
        print("\n%s" % ("✓ 闸全过" if ok1 and ok2 else "🔴 有闸未通过"))
        return 0 if (ok1 and ok2) else 1

    print("■ 扫英文版 dump 定来源（唯一能证明的来源）…")
    pool = en_pool()
    rows, stat = collect(con, pool)
    for k in sorted(stat):
        print("   %-26s %10s" % (k, f"{stat[k]:,}"))
    for col, _ in COLS:
        t, p = stat["%s·总" % col], stat["%s·en-edition" % col]
        print("   ⇒ %s 可证 %.1f%% ／ 证不了 %s 条写 unknown"
              % (col, 100.0 * p / max(t, 1), f"{t - p:,}"))
    print("\n   → pronunciation 行 %s（覆盖 %s 个词形）"
          % (f"{len(rows):,}", f"{len({r[0] for r in rows}):,}"))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    # 🔴 幂等重跑：只删**本脚本产出的行**，用 `src_ref` 认领，不是清空整张表 ——
    #    4b 跨版收割之后再跑这个脚本，它不许碰别人的行。
    #    （起因：4a 第一次落库后闸②逮到 3 条粘着两个音标的值，源列修好要重迁。）
    OWNED = "src_ref LIKE 'legacy:dict.%' OR src_ref LIKE 'kk-en:%#ipa'"
    old = con.execute("SELECT count(*) FROM pronunciation WHERE " + OWNED).fetchone()[0]
    con.close()
    if old:
        print("■ 幂等重跑：先删本脚本上次产出的 %s 行" % f"{old:,}")
    with dbtool.session("keep-v3-ipa-migrate",
                        expect={"#pronunciation": len(rows) - old}) as s:
        if old:
            s.execute("DELETE FROM pronunciation WHERE " + OWNED)
        s.executemany(
            "INSERT INTO pronunciation "
            "(word_id,ipa,notation,region,tags,pos,is_primary,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok1 = gate1(con, orig)
    ok2 = gate2(con, len(rows))
    dbtool.sample_check(
        [(con.execute("SELECT word FROM dict WHERE id=?", (r[0],)).fetchone()[0], r[3], r[1])
         for r in rows[:4000]], n=10, cols=("词", "地区", "音标"))
    print("\n%s" % ("✓ 两道闸全过" if ok1 and ok2 else "🔴 有闸未通过"))
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
