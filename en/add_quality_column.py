#!/usr/bin/env python3
"""给 stardict 加质量/来源标记列 `qual`,供服务层分层服务。见对话 2026-07-28。

为什么需要:全库实际错译约 37 万(≈9.5%),但**能点出名字的只有几百条**
(抽样率极低:C6 仅 0.07%、C4 仅 0.18%)。逐条判完要几千万 token,不现实。
→ 退而求其次:**按"这条经过了什么处理/属于哪个桶"打标**,让产品层能分层服务
   (低可信加角标或干脆不返回),把决策从不可逆的"删不删"变成可逆的"显不显示"。
   零 API 成本,全部依据本地留痕 TSV 与桶分类。

标记等级(由高到低,后面的不覆盖前面的):
  core        59,137   常用核心。全量 judge + 修复,真实 bad ≈0.02%,音标 100%。**产品主力面。**
  judged      逐条判过 ok/warn 且仍在库(A1 全量 judge sweep_a1.jsonl)。
  fixed       本项目重写/回填并抽样验过(A1 回填、A1d、B1 三批、known_bad)。抽样 ok 96–98%。
  good        抽样 bad ≤5% 的桶:C1 3.5% / C2 0.3% / C4 5.0%。未改动,原本就合格。
  fair        抽样 bad 7–10% 的桶:C5 7.7% / C6 9.3%。可用但非成品。
  low         抽样 bad ≥14% 的桶:C3 14.4% / B2 22.3% / B1 剩余(单词形 50%、短语形 21.8%)。
              **建议产品层加"低可信"角标或不返回。**

用法:
  python3 en/add_quality_column.py            # dry-run,只统计
  python3 en/add_quality_column.py --run      # 备份后加列+回填
"""
import argparse, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import buckets as B

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"

# 本项目改动过的留痕(id 在第 1 列;reverted 类要扣除)
FILL_LOGS = ["a1a_fill.tsv", "a1d_fill.tsv", "a1_rewrite.tsv",
             "b1_kaikki_fill.tsv", "b1_rewrite.tsv", "b1_skips_pro.tsv",
             "b1_stuck_fill.tsv", "b1_ownreal_fill.tsv", "known_bad_fix.tsv"]
REV_LOGS = ["a1a_reverted.tsv", "a1d_reverted.tsv"]

BUCKET_QUAL = {"C1": "good", "C2": "good", "C4": "good",
               "C5": "fair", "C6": "fair",
               "C3": "low", "B1": "low", "B2": "low",
               "A1": "fair"}   # 剩余空壳:没用但不误导


def ids_of(files):
    s = set()
    for f in files:
        p = HERE / f
        if not p.exists():
            continue
        for i, ln in enumerate(open(p, encoding="utf-8")):
            if i:
                try:
                    s.add(int(ln.split("\t")[0]))
                except ValueError:
                    pass
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    fixed = ids_of(FILL_LOGS) - ids_of(REV_LOGS)
    judged = set()
    p = HERE / "sweep_a1.jsonl"
    if p.exists():
        import json
        for ln in open(p, encoding="utf-8"):
            d = json.loads(ln)
            if d.get("v") in ("ok", "warn"):
                judged.add(d["id"])
    core = {r[0] for r in conn.execute(f"SELECT id FROM stardict WHERE {B.CORE}")}
    print(f"core {len(core)} | judged(ok/warn) {len(judged)} | fixed(留痕净) {len(fixed)}")

    plan = {}
    for rid, w, t, bk in B.load_tail(conn):
        plan[rid] = BUCKET_QUAL.get(bk, "fair")
    for rid in fixed:
        if rid not in core:
            plan[rid] = "fixed"
    for rid in judged:
        if rid not in core:
            plan[rid] = "judged"
    for rid in core:
        plan[rid] = "core"

    tally = Counter(plan.values())
    tot = sum(tally.values())
    print(f"\n{'标记':8} {'数量':>10} {'占比':>7}   含义")
    meaning = {"core": "常用核心成品(bad≈0.02%)", "judged": "逐条判过 ok/warn",
               "fixed": "本项目重写/回填,抽样 ok 96-98%", "good": "抽样 bad ≤5%",
               "fair": "抽样 bad 7-10%,可用非成品", "low": "抽样 bad ≥14%,建议标低可信"}
    for k in ("core", "judged", "fixed", "good", "fair", "low"):
        print(f"  {k:8} {tally[k]:>10} {100*tally[k]/tot:6.1f}%   {meaning[k]}")
    print(f"  {'合计':8} {tot:>10}")

    if not a.run:
        print("\n(dry-run;加 --run 建列并回填)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-qual-{tag}.bak"))
    conn = sqlite3.connect(DB)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(stardict)")]
    if "qual" not in cols:
        conn.execute("ALTER TABLE stardict ADD COLUMN qual TEXT")
    conn.executemany("UPDATE stardict SET qual=? WHERE id=?",
                     [(v, k) for k, v in plan.items()])
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stardict_qual ON stardict(qual)")
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM stardict WHERE qual IS NULL").fetchone()[0]
    print(f"\n已建列 qual + 索引;未打标的剩 {n} 条(应为 0);备份 pre-qual-{tag}.bak")
    conn.close()


if __name__ == "__main__":
    main()
