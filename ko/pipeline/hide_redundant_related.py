#!/usr/bin/env python3
"""K34：同一页同一目标既挂在 `related` 又挂在更具体的 kind 上 —— 藏掉兜底那条。2026-09-27。

═══ 起因：把数据渲染出来读 ═══
清 K11 落库后渲染 `풀다`，看见「派生词 … **풀리다**」紧跟着「近义词 **풀리다** …」。
回全库量，**词级可见边 220,718 条里有 19,860 组「同页同目标挂多个 kind」**。

🔴 **第一版判据宽了 13 倍。** 那 19,860 里 **18,408 组（92.7%）是 `hangeul`+`hanja_form_of`**
   这一族 —— 谚文拼写 vs 汉字表记是**两种不同信息**，展示层本来就分区印，**分开印是对的**。
   收窄到「语义关系之间互撞」后是 **1,452 组**。

═══ 判据：只动兜底的 `related` ═══
渲染读出来的形状高度一致 —— **`related`（相关词）是个兜底的袋子，重复了更具体的那些**：

    乾   反义词 地 坤 濕
         相关词 팔괘 天 兌 澤 離 火 震 雷 巽 風 坎 水 艮 山 坤 地   ← 地/坤/天 都重复了
         近义词 天
    上   派生词 향상 …   ／   相关词 … 向上 향상 …                ← 향상 重复

⇒ 同一个词同时印在「相关词」和一个更具体的类别下是**噪声**：具体的那个说得更多，
  兜底的那个不提供新信息。

⚠️ **只动 `related`，不动别的组合。** `derived`+`synonym` 那 140 组**两条都是真信息**
   （`이빨` 既是 `이` 的近义词、也是 `이`+`빨` 的派生形），印两遍是内容不是噪声。
   剩下 269 组「具体 vs 具体」有意保留。

═══ 代价单独量过（账上要求的）═══
`[[consult-two-models-on-rules]]` 记过：兜底分支「其余降为 related」在数据里是 41.8%，
照做＝**修好 0 弄坏 2,739**。所以这次先把代价摊开：

    词级可见 `related` 边              25,295
    要藏的（同页同目标已有更具体 kind）    1,219  （4.8%）
    `相关词` 整行消失的页面               155  （占有 related 的页面 1.78%）
    其中整页一条关系边都不剩的               0  ← 关键：一页都没有
    抽查三页（`국토`/`누나`/`발`）：消失的每一个目标都还在更具体的类别下印着 ⇒ **零信息损失**

═══ 处置 ═══
`hidden=1` ＋ `hidden_why`，不删（用户 2026-09-24：「我倾向保留数据」）。

跑（在仓库根）：
    python3 -u ko/pipeline/hide_redundant_related.py
    python3 -u ko/pipeline/hide_redundant_related.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")
WHY = "K34：同页同目标已有更具体的 kind，兜底的 `related` 不提供新信息"

# 🔴 这一族是**两种不同信息**，分区印是对的，不许进判据：
#    `hangeul`＝这个汉字条目的谚文读法；`hanja_form_of`＝这个词的汉字形；
#    `hanja_spelling`/`alt_hanja`＝汉字表记（目标是注不是词）。
#    18,408 组里全是它们，占 92.7% —— 第一版判据没排除它们，宽了 13 倍。
ANNOT_FAMILY = ("hangeul", "hanja_form_of", "hanja_spelling", "alt_hanja")


def plan(con):
    """→ (要藏的 id 列表, 统计)。判据：同页同目标上除 `related` 外还有别的语义 kind。"""
    rows = con.execute(
        "SELECT id, word_id, kind, COALESCE(target_norm, target) FROM sense_relation"
        " WHERE COALESCE(hidden,0)=0 AND sense_id IS NULL").fetchall()
    kinds = collections.defaultdict(set)
    rel = collections.defaultdict(list)
    for rid, wid, k, t in rows:
        kinds[(wid, t)].add(k)
        if k == "related":
            rel[(wid, t)].append(rid)
    drop, groups = [], 0
    for key, ids in rel.items():
        others = kinds[key] - {"related"} - set(ANNOT_FAMILY)
        if others:
            groups += 1
            drop += ids
    stat = {
        "词级可见边": len(rows),
        "词级可见 related 边": sum(1 for _r, _w, k, _t in rows if k == "related"),
        "撞上更具体 kind 的组": groups,
        "要藏的 related 边": len(drop),
    }
    return drop, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    drop, stat = plan(con)
    for k, v in stat.items():
        print("   %-24s %s" % (k, f(v)))

    # ══ 代价：整行消失的页面、以及会不会有页一条边都不剩 ══
    rows = con.execute(
        "SELECT id, word_id, kind FROM sense_relation WHERE COALESCE(hidden,0)=0").fetchall()
    rel_page = collections.Counter(w for _r, w, k in rows if k == "related")
    all_page = collections.Counter(w for _r, w, _k in rows)
    dropset = set(drop)
    drop_page = collections.Counter(w for r, w, _k in rows if r in dropset)
    gone = [w for w, n in drop_page.items() if rel_page[w] == n]
    naked = [w for w in gone if all_page[w] == drop_page[w]]
    print("\n■ 代价")
    print("   `相关词` 整行消失的页面      %s / %s（%.2f%%）"
          % (f(len(gone)), f(len(rel_page)), 100.0 * len(gone) / max(len(rel_page), 1)))
    print("   🔴 整页一条关系边都不剩的     %s" % f(len(naked)))
    if naked:
        raise SystemExit("🔴 有 %d 页会变成一条关系都没有 —— 那不是去重，那是删内容" % len(naked))

    # 🔴 **零信息损失要验，不是声称**：每一条要藏的目标，必须在同页别的 kind 下还印着
    lost = 0
    for rid in drop:
        wid, t = con.execute(
            "SELECT word_id, COALESCE(target_norm,target) FROM sense_relation WHERE id=?",
            (rid,)).fetchone()
        n = con.execute(
            "SELECT COUNT(*) FROM sense_relation WHERE word_id=? AND COALESCE(hidden,0)=0"
            " AND kind<>'related' AND COALESCE(target_norm,target)=?", (wid, t)).fetchone()[0]
        if not n:
            lost += 1
    print("   零信息损失核验：藏掉之后**在同页别处找不到**的目标 %d 个 %s"
          % (lost, "✅" if lost == 0 else "🔴"))
    if lost:
        raise SystemExit("🔴 有 %d 个目标会彻底从页面上消失" % lost)

    print("\n■ 抽 3 页看效果")
    for wid in gone[:3]:
        w = con.execute("SELECT word FROM dict WHERE id=?", (wid,)).fetchone()[0]
        rel = [t for t, in con.execute(
            "SELECT COALESCE(target_norm,target) FROM sense_relation WHERE word_id=?"
            " AND kind='related' AND COALESCE(hidden,0)=0", (wid,))]
        print("   %-12s 相关词 %s → 整行消失；这些词在：" % (w, rel))
        for t in rel:
            ks = [x[0] for x in con.execute(
                "SELECT DISTINCT kind FROM sense_relation WHERE word_id=?"
                " AND kind<>'related' AND COALESCE(hidden,0)=0"
                " AND COALESCE(target_norm,target)=?", (wid, t))]
            print("        %-10r %s" % (t, ks))

    n_hidden = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE COALESCE(hidden,0)=1").fetchone()[0]
    n_rows = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    con.close()

    if not drop:
        print("\n■ 没有要藏的")
        return
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-k34-hide-redundant-related",
            expect={"sense_relation.hidden_why": len(drop), "__rows__": 0},
            invalidates=[]) as s:
        s.executemany("UPDATE sense_relation SET hidden=1, hidden_why=? WHERE id=?",
                      [(WHY, r) for r in drop])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    left, _ = plan(con)
    checks = [
        ("hidden=1 的行数", q("SELECT COUNT(*) FROM sense_relation"
                             " WHERE COALESCE(hidden,0)=1"), n_hidden + len(drop)),
        ("关系边总数没变（一行没删）", q("SELECT COUNT(*) FROM sense_relation"), n_rows),
        ("🔴 再算一遍：还撞着的 `related` 边", len(left), 0),
        ("藏的都写了原因", q("SELECT COUNT(*) FROM sense_relation WHERE COALESCE(hidden,0)=1"
                       " AND (hidden_why IS NULL OR TRIM(hidden_why)='')"), 0),
        # 🔴 反向：**只藏了 `related`**，别的 kind 一条没动
        ("只藏了 related（本轮）", q("SELECT COUNT(*) FROM sense_relation"
                                " WHERE hidden_why=? AND kind<>'related'", WHY), 0),
        # 🔴 反向：`derived`+`synonym` 那 140 组**一条都没动**（那是真信息）
        ("具体 vs 具体的组一条没动",
         q("SELECT COUNT(*) FROM sense_relation WHERE hidden_why=?"
           " AND kind IN ('derived','synonym','antonym','alt_of','alternative')", WHY), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-34s %9s（期望 %s）" % ("✅" if good else "🔴", name[:34], f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
