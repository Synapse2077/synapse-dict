#!/usr/bin/env python3
"""es 变形层**确定性**核对:拿 kaikki 当真值,逐条比对原形指针。见对话 2026-07-31。

⭐ 为什么不再问模型:2026-07-31 一天之内,模型报的"缺陷"**连续三族**在回源核对后全部不成立:
     ① coda 塞音浊化 31,890 条 —— kaikki 自己就写 /ˈaɡto/,99.9% 逐字一致;
     ② 多词非末词次重音 7,889 条 —— 96.8% 与 kaikki 一致;
     ③ 变形层"过去分词原形指针错"≈8,800 条 —— kaikki 对 `performados` 的 tags 就是
        `['form-of','masculine','participle','plural']` + form_of=`performado`,
        我们存的"performado 的 过去分词·阳性·复数"是**逐字忠实渲染**,根本没错。
   判官还量出**自噪 45%**(同一把尺对同一批没变的数据前后自相矛盾)。
   → 变形层的原形指针**本来就是从 kaikki 的 form_of 确定性组合出来的**,
     那么"它对不对"就该**回 kaikki 比对**,不该问模型。模型在这件事上没有信息优势,只会引入噪声。

判据(纯确定性,无模型):
  对每个变形词形 w,取库内 exchange 的 `0:原形` 指针集合 P_db,
  与 kaikki 中所有 w 条目的 form_of 指针集合 P_kk 比。
    P_db ⊆ P_kk        → ok(忠实)
    P_db ∩ P_kk = ∅    → 指针冲突(真缺陷候选)
    w 不在 kaikki       → 无从核对(多为 build 期派生形,单独计数,不算缺陷)

read-only。用法(在 es/ 目录):
  python3 verify_infl_vs_kaikki.py              # 全量核对(约 2-3 分钟,扫一遍 1GB dump)
  python3 verify_infl_vs_kaikki.py --show 40
"""
import argparse, sqlite3, time
from collections import Counter, defaultdict
from pathlib import Path

import kaikki_util

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-es.sqlite"
KK = HERE / "kaikki.org-dictionary-Spanish.jsonl"


def db_pointers():
    """word → {原形}(来自 exchange 的 0: 行)。只取变形层。"""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = defaultdict(set)
    rows = conn.execute("SELECT word, COALESCE(exchange,'') FROM dict WHERE is_lemma=0")
    n = 0
    for w, ex in rows:
        n += 1
        for ln in ex.split("\n"):
            ln = ln.strip()
            if ln.startswith("0:"):
                v = ln[2:].strip()
                if v:
                    out[w].add(v)
    conn.close()
    return out, n


def kaikki_pointers(words):
    """🔴 必须走 kaikki_util —— 自己写正则抓 word 会抓到嵌套的 forms/descendants,
    2026-07-31 因此把 estar 这类词整条漏掉。见 kaikki_util.py 文件头。"""
    t0 = time.time()
    out = kaikki_util.form_of_pointers(words)
    print(f"  kaikki 扫完:覆盖 {len(out):,} 个词形 ({time.time()-t0:.0f}s)", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=25)
    a = ap.parse_args()

    print("读库内变形层指针…", flush=True)
    dbp, nrows = db_pointers()
    print(f"  变形层 {nrows:,} 行,带原形指针的词形 {len(dbp):,} 个", flush=True)

    print("扫 kaikki dump(1GB,约 2-3 分钟)…", flush=True)
    kkp = kaikki_pointers(set(dbp))

    tally = Counter()
    conflicts = []
    for w, pdb in dbp.items():
        pkk = kkp.get(w)
        if not pkk:
            tally["kaikki无此词形"] += 1
        elif pdb <= pkk:
            tally["✅忠实(库⊆kaikki)"] += 1
        elif pdb & pkk:
            tally["部分重合"] += 1
            conflicts.append((w, pdb, pkk, "部分"))
        else:
            tally["❌指针冲突"] += 1
            conflicts.append((w, pdb, pkk, "冲突"))

    tot = sum(tally.values())
    print("\n" + "=" * 72)
    print(f"变形层原形指针 · 拿 kaikki 当真值确定性核对 · {tot:,} 个词形")
    print("=" * 72)
    for k, v in tally.most_common():
        print(f"  {k:22} {v:>8,}  ({100*v/max(tot,1):5.2f}%)")
    checkable = tot - tally["kaikki无此词形"]
    bad = tally["❌指针冲突"]
    print(f"\n  可核对的 {checkable:,} 个词形中,指针冲突 {bad:,} "
          f"= **{100*bad/max(checkable,1):.3f}%**")
    if conflicts:
        print(f"\n  样例(前 {a.show}):")
        for w, pdb, pkk, kind in conflicts[:a.show]:
            print(f"    [{kind}] {w:22} 库→{sorted(pdb)}  kaikki→{sorted(pkk)}")


if __name__ == "__main__":
    main()
