#!/usr/bin/env python3
"""清掉 `sense_es.en_i` 里指向不存在的英文义项的无效值。2026-08-06。

═══ 怎么发现的 ═══
100 条对齐结果人工核验时，`esteticismo` 那条模型给了 `en_i=1`，
但该词的英文义项只有 1 条（下标只到 0）—— **越界**。

这类错误**不需要判断**，可以全库确定性算出来：

    有 en_i 的义项            80,284
    下标越界                     794   0.99%
    指了下标但英文义项为空         151   0.19%
    合计无效                     945   1.18%

⭐ 这正是项目铁律那条「能确定性回源比对的根本别问模型」的正面用例：
   同一批数据里，1.18% 靠算就能定性，剩下的才值得花人工去判。

═══ 为什么清成 null 而不是删行 ═══
`en_i = null` 的语义是「英文版没有对应义项」。越界指向本质上就是模型没找到对应，
只是把「没有」错写成了一个不存在的下标。清成 null 后：
  · 这条西语义项仍在，中文译文仍在（`en_i` 只是对齐关系，不是内容）
  · 它会被归入「英文版没有」那一档 —— 而那一档的错误方向是**安全**的
    （只会留下一条重复义项，不会把两个不同的意思焊在一起）

用法：
    python3 -m es.fixes.clear_invalid_en_i
    python3 -m es.fixes.clear_invalid_en_i --apply
"""
import argparse
import collections
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


def n_lines(s: str | None) -> int:
    return len([t for t in (s or "").split("\n") if t.strip()])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT s.id, s.word, s.idx, s.en_i, d.definition "
        "FROM sense_es s JOIN dict d ON d.id = s.dict_id "
        "WHERE s.en_i IS NOT NULL").fetchall()
    con.close()

    bad, stat, ex = [], collections.Counter(), []
    for sid, w, idx, eni, de in rows:
        c = n_lines(de)
        if c == 0:
            bad.append(sid); stat["英文义项为空"] += 1
        elif eni >= c:
            bad.append(sid); stat["下标越界"] += 1
            if len(ex) < 10:
                ex.append((w, idx, eni, c))

    print(f"有 en_i 的义项 {len(rows):,}")
    for k, v in stat.most_common():
        print(f"  {k:<16}{v:>6,}  {v/len(rows)*100:.2f}%")
    print(f"  合计待清 {len(bad):,}  = {len(bad)/len(rows)*100:.2f}%")
    print("\n越界样例（词 / 西语义项号 / 模型指向 / 英文实际条数）：")
    for w, i, e, c in ex:
        print(f"    {w:<20}[{i}] → [{e}]   英文只有 {c} 条")

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("clear-invalid-en-i", expect={}) as s:
        s.executemany("UPDATE sense_es SET en_i = NULL WHERE id = ?",
                      [(i,) for i in bad])

    # 复核：清完之后不该再有任何越界
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    left = 0
    for eni, de in con.execute(
            "SELECT s.en_i, d.definition FROM sense_es s JOIN dict d ON d.id = s.dict_id "
            "WHERE s.en_i IS NOT NULL"):
        if eni >= n_lines(de):
            left += 1
    tot = con.execute("SELECT COUNT(*) FROM sense_es").fetchone()[0]
    hit = con.execute("SELECT COUNT(*) FROM sense_es WHERE en_i IS NOT NULL").fetchone()[0]
    con.close()
    print(f"\n落库后：{tot:,} 条义项，有效对齐 {hit:,}，判为「英文版没有」{tot-hit:,}")
    print(f"  残留越界：{left}")
    assert left == 0


if __name__ == "__main__":
    main()
