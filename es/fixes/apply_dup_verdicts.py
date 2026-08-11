#!/usr/bin/env python3
"""把判重合并的复核判决落成数据：`sense_add.dup_verdict`。2026-08-11。

═══ 缺陷 ═══
2026-08-10 补收 1,963 条义项时，让模型顺带判「这条与该词已有的哪条义项重复」，
判重的那 186 条里 **21 条是错配、28 条存疑**（v4-pro 全量普查，186/186 覆盖）：

    peón            pawn / piece, checker      ⇒ 并进「行人。」
    fierro          car, especially a race car ⇒ 并进「油门，加速踏板」
    llamar          to call (on the telephone) ⇒ 并进「祈求；呼唤」
    culantrillo     Lemna gibba（浮萍）         ⇒ 并进「铁线蕨类草本植物」
    barra americana pole dance（钢管舞）        ⇒ 并进「钢管舞舞杆」

这是**义项错配**，用户 2026-08-07 原话：「不要把义项和释义错配了，那才是真灾难。」

═══ 🔴 为什么是加一列，不是清掉 `dup_zh` ═══
项目原则（[[prefer-reversible-designs]]）：**不可逆往往是方案设计窄造成的，不是数据属性。**
- 清 `dup_zh` = 把模型的判断**销毁**，将来想复核「当初它到底判了什么」就没有了；
- 存 `dup_verdict` = 判断和复核结论**并存**，重建时由一条规则决定采不采纳。
  想改主意（比如把 weak 也放行）只要改那条规则，不用重跑判官、不用回滚数据。

═══ 判据 ═══
`build_sense_layer.py` 的 C① 分支只在 `dup_verdict` ∉ {bad, weak} 时才合并。
⚠️ **C⓪ 不受影响** —— 那是「中文逐字相同」的确定性去重，不是模型判断，
   与本轮复核无关（`Cretáceo` 两条都译作「白垩纪」，不并就显示两遍）。

═══ 尺子 ═══
判决来自 `probes/audit_sense_gap_zh.py`，**只采信 v4-pro**：
负控 28/28 = 100%、正控自噪 1/16。豆包同批负控只抓住 4/30（13%），整家作废。

用法（在 es/ 目录）：
    python3 fixes/apply_dup_verdicts.py            # 试算
    python3 fixes/apply_dup_verdicts.py --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths

AUDIT = paths.WORK / "runs" / "sense_gap_zh_audit.json"
BLOCK = ("bad", "weak")          # 这两档不采纳合并


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    verdicts = {int(k): v[0] for k, v in
                json.loads(AUDIT.read_text(encoding="utf-8"))["merge_v4"].items()}

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT id, word, gloss, zh, dup_zh FROM sense_add "
        "WHERE dup_zh IS NOT NULL AND dup_zh<>'' AND dup_zh<>zh").fetchall()
    con.close()

    stat = collections.Counter()
    plan, blocked = [], []
    for rid, word, gloss, zh, dup in rows:
        v = verdicts.get(rid)
        stat[v or "（判官没覆盖）"] += 1
        if v:
            plan.append((v, rid))
        if v in BLOCK:
            blocked.append((word, gloss, dup, v))

    print("■ 判重合并共 %d 条，判决分布：" % len(rows))
    for k, n in stat.most_common():
        print("    %-14s %4d  (%.1f%%)" % (k, n, 100 * n / len(rows)))
    print("\n■ 将标记为不采纳（bad + weak）：%d 条" % len(blocked))
    for w, g, d, v in blocked[:20]:
        print("    %-4s %-18s %-42s ⇒「%s」" % (v, w, (g or "")[:42], (d or "")[:20]))
    if len(blocked) > 20:
        print("    …… 另 %d 条" % (len(blocked) - 20))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库；落库后需重跑 build_sense_layer.py 才生效)")
        return

    # `sense_add` 不在 dbtool.TRACK 里（那张表跟踪的是 dict 的列），
    # 所以 dict 的所有不变量都应当纹丝不动 ⇒ expect={}。
    with dbtool.session("apply-dup-verdicts", expect={}) as s:
        cols = {r[1] for r in s.execute("PRAGMA table_info(sense_add)")}
        if "dup_verdict" not in cols:
            s.execute("ALTER TABLE sense_add ADD COLUMN dup_verdict TEXT")
            print("■ 已加列 sense_add.dup_verdict")
        s.executemany("UPDATE sense_add SET dup_verdict=? WHERE id=?", plan)

    print("\n🔴 下一步必须重跑：python3 -m es.pipeline.build_sense_layer --apply")
    print("   （判决只有在出版层重建时才生效）")


if __name__ == "__main__":
    main()
