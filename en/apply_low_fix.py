#!/usr/bin/env python3
"""把 rewrite_low_pilot.py 产出的 fix 落库。见对话 2026-07-30。

只写 a=="fix" 的条目;keep/skip 一律不动库(skip 里 40.8% 是 bad,但那是**下一轮**的活,
不是这一轮能碰的 —— v4-pro 对它们的判断是"我不认识",硬写等于编造)。

实测质量(20,001 条那轮,800 条前后配对,pro 判官):
  fix 组 改前 bad 19.3% → 改后 bad 1.3%,其中"把对的改坏" 0.7%。
  → 0.7% 是**已知且接受**的代价(如 ABAA 美国古书商协会被改成"可鄙的"),
    本地判不出来,靠 LOG 留痕可回滚。

五道本地闸(纯确定性,挡的是格式事故不是知识错误):
  ① 译文里得有汉字             —— 挡纯英文/纯符号
  ② 不含 [网络]                —— 这批的存在意义就是洗掉它
  ③ 不是空壳(buckets.is_shell) —— 挡"X 的复数"这类元描述回显
  ④ 归一化后与原文不同         —— 挡纯 no-op
  ⑤ 库里现值必须仍等于 jsonl 的 before —— 挡"这行已被别的流水线改过"

⚠️ **幂等**:LOG 存在时先按 LOG 把上一轮写回去(连 qual 一起,第 5 列存的是原 qual),
   再写本轮。所以重跑安全,且 before 不会被上一轮污染。

用法:
  python3 en/apply_low_fix.py low_pilot_deepseek-v4-pro_20001_20260730-1418.jsonl
  python3 en/apply_low_fix.py <jsonl> --run
"""
import argparse, json, re, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import buckets as B

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
LOG = HERE / "ledgers/low_fix.tsv"
HAN = re.compile(r"[一-鿿]")
esc = lambda s: (s or "").replace("\t", "\\t").replace("\n", "\\n")
une = lambda s: (s or "").replace("\\t", "\t").replace("\\n", "\n")
norm = lambda s: re.sub(r"[\s;；,，.。]", "", re.sub(r"\[网络\]", "", s or ""))


def main():
    ap = argparse.ArgumentParser()
    # ⚠️ 多份一起传:LOG 是**全量回滚账本**,幂等回滚会先把 LOG 里的行全部还原。
    #   若第二次只传新一份,上一份已落库的修复会被还原掉却不再写回 —— 静默丢失。
    #   所以每次都要把**历轮 jsonl 一并列出**。
    ap.add_argument("jsonl", nargs="+", help="rewrite_low_pilot.py 的输出(可多份,按序去重)")
    ap.add_argument("--run", action="store_true", help="真写库(默认 dry-run)")
    a = ap.parse_args()

    recs, seen = [], set()
    for fn in a.jsonl:
        got = 0
        for ln in open(HERE / fn, encoding="utf-8"):
            r = json.loads(ln)
            if r.get("_meta") or r["id"] in seen:
                continue
            seen.add(r["id"]); recs.append(r); got += 1
        print(f"[{fn}] {got:,} 条", flush=True)
    print(f"合计 {len(recs):,} 条", flush=True)

    conn = sqlite3.connect(DB)
    if LOG.exists():                      # 幂等:先把上一轮原样写回
        n = 0
        for i, ln in enumerate(open(LOG, encoding="utf-8")):
            if not i:
                continue
            c = ln.rstrip("\n").split("\t")
            if len(c) >= 5:
                conn.execute("UPDATE stardict SET translation=?, qual=? WHERE id=?",
                             (une(c[2]), c[4] or None, int(c[0])))
                n += 1
        conn.commit()
        print(f"  [幂等] 已按 {LOG.name} 回滚上一轮 {n:,} 条", flush=True)

    cur = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
        "SELECT id, word, translation, COALESCE(qual,'') FROM stardict")}

    gate = Counter(); fixes = []
    for r in recs:
        if r["a"] != "fix":
            gate["非 fix,不动"] += 1
            continue
        new = (r["after"] or "").strip()
        row = cur.get(r["id"])
        if not new:
            gate["✗ after 为空"] += 1
        elif not HAN.search(new):
            gate["✗ 闸①无汉字"] += 1
        elif "[网络]" in new:
            gate["✗ 闸②仍含[网络]"] += 1
        elif B.is_shell(new):
            gate["✗ 闸③是空壳"] += 1
        elif row is None:
            gate["✗ id 不在库"] += 1
        elif (row[1] or "").strip() != (r["before"] or "").strip():
            gate["✗ 闸⑤库内现值已变"] += 1
        elif norm(new) == norm(r["before"]):
            gate["· 闸④与原文等价,跳过"] += 1
        else:
            gate["✓ 写入"] += 1
            fixes.append((r["id"], row[0], (row[1] or "").strip(), new, row[2]))

    print()
    for k, v in gate.most_common():
        print(f"  {k:22} {v:>7,}")

    if not fixes:
        print("\n无可写入的改写。")
        conn.close()
        return
    print(f"\n  样例:")
    for rid, w, old, new, q0 in fixes[:8]:
        print(f"    {w[:24]:26} 前:{old.replace(chr(10),' / ')[:26]:28} 后:{new[:34]}")

    if not a.run:
        print(f"\n[dry-run] 将写入 {len(fixes):,} 条。加 --run 真写。")
        conn.close()
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    bak = DB.with_name(f"synapse-dict-en.pre-lowfix-{tag}.bak")
    shutil.copy2(DB, bak)
    conn = sqlite3.connect(DB)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tbefore\tafter\tqual0\n")
        for rid, w, old, new, q0 in fixes:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            conn.execute("UPDATE stardict SET qual='fixed' WHERE id=? "
                         "AND qual NOT IN ('core','judged')", (rid,))
            f.write(f"{rid}\t{w}\t{esc(old)}\t{esc(new)}\t{q0}\n")
    conn.commit()
    conn.close()
    print(f"\n已写入 {len(fixes):,} 条(qual → fixed),留痕 → {LOG.name}")
    print(f"备份 → {bak.name}")


if __name__ == "__main__":
    main()
