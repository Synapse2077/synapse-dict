#!/usr/bin/env python3
"""修正 `en_i` 越界判据：分母是**义项行数**，不是「非空英文行数」。2026-08-07。

═══ 我错在哪 ═══
`fixes/clear_invalid_en_i.py`（2026-08-06）用「非空英文释义条数」当分母判越界：

    def n_lines(s): return len([t for t in (s or "").split("\\n") if t.strip()])
    if eni >= n_lines(definition): 判为越界 → 清成 NULL

**分母取错了。** `en_i` 指的是「对应**第几条义项**」，不是「第几条英文释义」——
模型看到的输入是 `en` 与 `zh` 两个**按行号对齐**的数组（`translate_sense_es.nl()`
按 `\\n` 切，**保留空行**），它匹配的是义项行。铁证是 `mona`：

    行号  en                     zh
     [0]  drunkenness, fuddle    醉酒，醉态
     [1]  （空）                  母猴          ← 这一行英文缺，但义项存在
     [2]  copycat                模仿者，抄袭者

    sense_es[mona #0]「Hembra del mono / 雌猴」→ en_i=1 → 正好是「母猴」那一行 ✅

按旧判据，`n_lines(definition)` 数出 5（跳过空行），`en_i=1` 看似合法而侥幸没被清；
但对 `abia`/`adra`/`Guamán` 这类**英文整列近乎全空**的词，旧判据把有效对齐判成了越界。

    被旧脚本清掉的 1,109 条里：
      🔴 其实有效（按义项行数没越界）  286   ← 误删
      确实越界                        823

⭐ 这正是「量落点不量源头」那条铁律的又一次现形：我量的是 `definition` 这一列有几条
   非空文本，而真正的落点是**义项行**。两者只在「英文列没有空行」时相等。

═══ 怎么修 ═══
① 从 `WORK/sense_es_llm.jsonl`（模型原始返回，只追加、没被动过）恢复误删的 286 条
② 用正确分母（`translation` 的行数 —— 该列 100% 非空且与义项行一一对应）重新核一遍，
   确认没有残留越界

用法：
    python3 -m es.fixes.fix_en_i_criterion
    python3 -m es.fixes.fix_en_i_criterion --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

RAW = paths.WORK / "sense_es_llm.jsonl"


def n_senses(definition, definition_es, translation) -> int:
    """该词有几条义项行。三列按行号对齐，取最长的那一列。"""
    return max(len((x or "").split("\n")) if x else 0
               for x in (definition, definition_es, translation))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    dic = {w: n_senses(de, des, tr) for w, de, des, tr in con.execute(
        "SELECT word, definition, definition_es, translation FROM dict")}
    cur = {(w, i): e for w, i, e in con.execute(
        "SELECT word, idx, en_i FROM sense_es")}
    con.close()

    restore, still_bad = [], 0
    for line in RAW.open(encoding="utf-8"):
        d = json.loads(line)
        for i, s in zip(d["idx"], d["s"]):
            e = s.get("en_i")
            if not isinstance(e, int):
                continue
            if (d["w"], i) not in cur or cur[(d["w"], i)] is not None:
                continue                      # 没被清掉，不动
            if e < dic.get(d["w"], 0):
                restore.append((e, d["w"], i))
            else:
                still_bad += 1
    print(f"从 RAW 恢复误删的有效对齐：{len(restore):,}")
    print(f"  确实越界、维持 NULL：{still_bad:,}")

    # 反向核：现存的 en_i 里，按正确分母还有没有越界的
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    left = [(w, i, e) for w, i, e in con.execute(
        "SELECT word, idx, en_i FROM sense_es WHERE en_i IS NOT NULL")
        if e >= dic.get(w, 0)]
    con.close()
    print(f"  现存 en_i 里按正确分母越界的：{len(left)}   {left[:5]}")

    dbtool.sample_check(
        [(w, f"#{i}", f"en_i={e}") for e, w, i in restore[:10]], 10,
        ("词", "西语义项号", "恢复的对齐"))

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("fix-en-i-criterion", expect={}) as s:
        s.executemany("UPDATE sense_es SET en_i=? WHERE word=? AND idx=?", restore)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    hit = con.execute("SELECT COUNT(*) FROM sense_es WHERE en_i IS NOT NULL").fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM sense_es").fetchone()[0]
    bad = [(w, i, e) for w, i, e in con.execute(
        "SELECT word, idx, en_i FROM sense_es WHERE en_i IS NOT NULL")
        if e >= dic.get(w, 0)]
    con.close()
    print(f"\n落库后：{tot:,} 条义项，有效对齐 {hit:,}，残留越界 {len(bad)}")
    assert not bad


if __name__ == "__main__":
    main()
