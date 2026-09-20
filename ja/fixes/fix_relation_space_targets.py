#!/usr/bin/env python3
"""关系目标里**含空格**的 2,029 条，一条判据管不了。2026-09-19。零模型调用。（JA_PLAN 欠账 16）

═══ 四种形状，四种处置 ═══
判据全在 `pipeline/harvest_relations.clean_targets()` 的文档串里，**本脚本 import 它，不重写**：

    ① 并列表 `縞馬, 斑馬`          ⇒ 拆成多个目标（422 个串）
    ② 罗马字回显 `女郎 (jorō)`     ⇒ 剥括号（278 个串，欠账 13 清过**串尾**回显，这是带括号的变体）
    ③ 箭头 `兄様 → 兄さん`         ⇒ 沿箭头切，两边都留
    ④ `ごみ箱 rubbish bin`/`あたし 30%` ⇒ 取前半（其后全无日文字符）
    ⑤ 活用构成公式 `stem + い`、整句散文 ⇒ **挂 `hidden=1` 不删**（289 个串）

🔴 **拆出来的每一片都要单独过判据**，否则 `割符(historically read as かちふ, today read as…)`
   这种带逗号的散文会被拆成两段垃圾（实测 5 条，全部正确落到 ⑤）。

🔴 生成侧已同步改掉（`clean_target` → `clean_targets`，返回列表），
   不改的话下次重跑原样长回来（`[[replay-scripts-undo-fixes]]`）。

跑（在仓库根）：
    python3 -u ja/fixes/fix_relation_space_targets.py
    python3 -u ja/fixes/fix_relation_space_targets.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import sqlite3

import dbtool
import paths
from pipeline.harvest_relations import clean_targets


def plan(con):
    """→ (改写, 新插, 挂起, 理由)。改写/新插都要**避开已经存在的同组目标**。

    🔴🔴 **洗完等于词头本身的一律不要。** `MHD 発電` 洗成 `発電`，而它就挂在 `発電` 页上 ⇒
       自指。生成侧的 `add()` 一直有这条检查，**是本脚本漏了** ——
       第一版落库时回归闸 **F2 当场报了 19 条**（欠账 13 那轮清洗 `死(し)ぬ` 造出 86 条自指，
       也是 F2 逮的、也不是我）。**同一个形状第二次，两次都靠同一道闸。**
    """
    self_w = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
    have = {(w, k, t) for w, k, t in con.execute(
        "SELECT word_id, kind, target FROM sense_relation")}
    rewrite, insert, hide, drop = [], [], [], []
    why = collections.Counter()      # 挂起的两种理由要分开报
    seen_new = set()
    for rid, wid, sid, kind, tgt, src, ref in con.execute(
            "SELECT id, word_id, sense_id, kind, target, src, src_ref FROM sense_relation"
            " WHERE target LIKE '% %' AND hidden=0"):
        ts = clean_targets(tgt)
        if not ts:
            hide.append(rid)
            why["判为不是词（活用公式/表格残渣/整句散文）"] += 1
            continue
        ts = [t for t in ts if t != self_w.get(wid)]     # 🔴 洗完＝词头本身 ⇒ 丢
        if not ts:
            drop.append(rid)
            why["洗完等于词头本身（自指）⇒ **删**不是挂起"] += 1
            continue
        keep = None
        for t in ts:
            if t == tgt:
                keep = t
                continue
            key = (wid, kind, t)
            if key in have or key in seen_new:
                continue          # 这一片本来就有了 ⇒ 不重复插
            if keep is None:
                keep, rewrite_t = t, t
                rewrite.append((rid, t))
            else:
                insert.append((wid, sid, kind, t, src, "%s+split:%s" % (ref, t)))
            seen_new.add(key)
        if keep is None:
            hide.append(rid)      # 拆出来的片全都已存在 ⇒ 原行没有存在价值
            why["洗完与已有目标重复（不丢信息）"] += 1
    return rewrite, insert, hide, drop, why


def main():
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的"
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rewrite, insert, hide, drop, why = plan(con)
    n = con.execute("SELECT COUNT(*) FROM sense_relation"
                    " WHERE target LIKE '% %' AND hidden=0").fetchone()[0]
    con.close()
    print("   含空格且未隐藏的行 %s ＝ 改写 %s ＋ 挂起 %s（另新插 %s 片）"
          % (format(n, ","), format(len(rewrite), ","), format(len(hide), ","),
             format(len(insert), ",")))
    print("   挂起的理由：%s" % dict(why))
    print("   其中**删除**（自指，生成侧根本不会产生这种行）%s" % format(len(drop), ","))
    assert len(rewrite) + len(hide) + len(drop) == n, "🔴 桶没装全：%d+%d+%d≠%d" % (len(rewrite), len(hide), len(drop), n)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    old = {i: t for i, t in con.execute("SELECT id, target FROM sense_relation")}
    con.close()
    dbtool.sample_check([(old[i], t) for i, t in rewrite[::max(1, len(rewrite) // 16)]],
                        12, ("改前", "改后"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return
    with dbtool.session("ja-relation-space-targets", expect={
            "#sense_relation": len(insert) - len(drop),
            "sense_relation.target": len(insert) - len(drop)}, invalidates=[]) as s:
        s.executemany("UPDATE sense_relation SET target=? WHERE id=?",
                      [(t, i) for i, t in rewrite])
        s.executemany("UPDATE sense_relation SET hidden=1 WHERE id=?", [(i,) for i in hide])
        # 🔴 自指是**删**不是挂起：`hidden` 说的是「真数据但不展示」，
        #    而自指行不是数据、是清洗的副产物 —— 回归闸 F2 不看 `hidden`，那是对的，
        #    把闸放宽去迁就我造出来的行，等于把闸变成背书。
        s.executemany("DELETE FROM sense_relation WHERE id=?", [(i,) for i in drop])
        s.executemany(
            "INSERT INTO sense_relation (word_id, sense_id, kind, target, tags, hidden,"
            " src, src_ref) VALUES (?,?,?,?,NULL,0,?,?)", insert)


if __name__ == "__main__":
    main()
