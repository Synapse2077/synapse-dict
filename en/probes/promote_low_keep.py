#!/usr/bin/env python3
"""把 v4-pro 判 keep 的条目从 low 升到 good。见对话 2026-07-30。

为什么单独做:`low` 这个标签是产品层加"低可信角标"的依据,里面混着两拨性质相反的东西 ——
  skip「模型不认识」 ~20.6 万,实测 bad **39.3%**  → 该降权
  keep「模型看过,能用」 ~3.5 万,实测 bad **1.5%**(两轮 2/135) → 挂 low 是冤枉
不摘出来,角标就会打在一批好条目上,角标本身的可信度先垮了。

⚠️ 只动 qual 列,**一个字的译文都不改**。判据是 v4-pro 逐条看过 + 两轮抽样验过。
   keep 的可信度是本轮最硬的一个信号:20,001 条那轮 n=62 bad 0%,386,071 条那轮 n=73 bad 2.7%。

⚠️ 闸:库内现值必须仍等于 jsonl 里的 before。若这行已被别的流水线改过,说明它已不是
   当初被判 keep 的那条内容,不能拿旧判决给新内容背书。

用法:
  python3 en/promote_low_keep.py <jsonl> [<jsonl>...]         # dry-run
  python3 en/promote_low_keep.py <jsonl> [<jsonl>...] --run
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, json, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
LOG = paths.WORK / "ledgers/low_keep_promoted.tsv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", nargs="+")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--to", default="good", help="升到哪一档(默认 good)")
    a = ap.parse_args()

    recs, seen = [], set()
    for fn in a.jsonl:
        got = 0
        for ln in open(HERE / fn, encoding="utf-8"):
            r = json.loads(ln)
            if r.get("_meta") or r["id"] in seen or r.get("a") != "keep":
                continue
            seen.add(r["id"]); recs.append(r); got += 1
        print(f"[{fn}] keep {got:,} 条", flush=True)
    print(f"合计 keep {len(recs):,} 条", flush=True)

    conn = sqlite3.connect(DB)
    cur = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT id, word, translation, COALESCE(qual,'') FROM stardict")}

    gate = Counter(); hits = []
    for r in recs:
        row = cur.get(r["id"])
        if row is None:
            gate["✗ id 不在库"] += 1
        elif (row[1] or "").strip() != (r["before"] or "").strip():
            gate["✗ 译文已被别处改过"] += 1
        elif row[2] != "low":
            gate[f"· 当前不是 low(={row[2]}),跳过"] += 1
        else:
            gate[f"✓ low → {a.to}"] += 1
            hits.append((r["id"], row[0], row[2]))

    for k, v in gate.most_common():
        print(f"  {k:26} {v:>7,}")
    if not hits:
        print("\n无可提级条目。")
        conn.close(); return

    if not a.run:
        print(f"\n[dry-run] 将把 {len(hits):,} 条 low → {a.to}。加 --run 真写。")
        conn.close(); return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    bak = HERE / "backups" / f"synapse-dict-en.pre-promote-{tag}.bak"
    shutil.copy2(DB, bak)
    conn = sqlite3.connect(DB)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tqual_before\tqual_after\n")
        for rid, w, q0 in hits:
            conn.execute("UPDATE stardict SET qual=? WHERE id=?", (a.to, rid))
            f.write(f"{rid}\t{w}\t{q0}\t{a.to}\n")
    conn.commit(); conn.close()
    print(f"\n已提级 {len(hits):,} 条 low → {a.to},留痕 → {LOG.name}")
    print(f"备份 → {bak.name}")


if __name__ == "__main__":
    main()
