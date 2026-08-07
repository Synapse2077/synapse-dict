#!/usr/bin/env python3
"""删掉重跑收录时「复活」的 13 条已删残渣。2026-08-06。

═══ 怎么发生的 ═══
`ingest_es_senses.py` 去掉 `is_lemma=1` 闸门后重跑，预期净增 8,506 条（= 缺陷清单
里那个数），实际增了 **8,519**。差 13 —— 差额必须解释清楚，不能放过。

查下去是：`sense_es` 的去重约束是 `UNIQUE(word, idx)`，而库里的行早已被
  · `clean_sense_es_residue.py`  删掉 87 条 wikitext 残渣
  · `fix_sense_es_residue2.py`   拆分 / 重编号
修过，**缓存文件却仍是 dump 的原样快照**。两边 idx 于是错开：

    caer 原本 25 条，[23] 是残渣 → 清掉重编号后只剩 [0..23]
    重跑时 idx=24 空着 ⇒ `INSERT OR IGNORE` 把缓存里的第 25 条又塞了回来

🔴 UNIQUE 约束保证的是「不重复」，**不保证「不倒退」**。
   已在 `ingest_es_senses.py` 把续跑判据改成**词级**（对重编号免疫）；
   本脚本清理这次已经灌进去的 13 条。

═══ 判据（确定性，不需要判断）═══
本轮新插的行 `zh IS NULL`（旧行 100% 有中文）。其中属于**原本就已有义项**的词
（同一个 word 下存在 `zh IS NOT NULL` 的行）就是复活行 —— 因为真正的 8,506 条
新义项全都属于此前一条都没收过的词。

用法：
    python3 -m es.fixes.drop_resurrected_residue
    python3 -m es.fixes.drop_resurrected_residue --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SQL = """
SELECT id, word, idx, gloss FROM sense_es
WHERE zh IS NULL
  AND word IN (SELECT word FROM sense_es WHERE zh IS NOT NULL)
ORDER BY word, idx
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows = con.execute(SQL).fetchall()
    total = con.execute("SELECT COUNT(*) FROM sense_es").fetchone()[0]
    n_null = con.execute("SELECT COUNT(*) FROM sense_es WHERE zh IS NULL").fetchone()[0]
    con.close()

    print(f"sense_es {total:,} 行，其中本轮新插（zh 为空）{n_null:,}")
    print(f"判定为复活行：{len(rows)}\n")
    for _id, w, i, g in rows:
        print(f"  {w:<14}[{i:>2}]  {g[:66]}")
    print(f"\n删除后 zh 为空的行应为 {n_null - len(rows):,}"
          f"（= 缺陷清单里的 8,506 条真新增）")

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("drop-resurrected-residue", expect={}) as s:
        s.executemany("DELETE FROM sense_es WHERE id = ?", [(r[0],) for r in rows])

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    left = con.execute(SQL).fetchall()
    tot2 = con.execute("SELECT COUNT(*) FROM sense_es").fetchone()[0]
    null2 = con.execute("SELECT COUNT(*) FROM sense_es WHERE zh IS NULL").fetchone()[0]
    dup = con.execute(
        "SELECT COUNT(*) FROM (SELECT word, idx FROM sense_es "
        "GROUP BY 1,2 HAVING COUNT(*)>1)").fetchone()[0]
    con.close()
    print(f"\n落库后：sense_es {tot2:,} 行，待翻中文 {null2:,}，残留复活行 {len(left)}，"
          f"(word,idx) 重复 {dup}")
    assert not left and dup == 0


if __name__ == "__main__":
    main()
