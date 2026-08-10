#!/usr/bin/env python3
"""清掉短标签里三类确定性瑕疵。2026-08-07。

`gen_sense_labels.py` 落库 11,282 条短标签。三类**不需要判断**的瑕疵共 171 条（1.52%）：

  ① **纯领域标记**（5 条）：`（引出补语）` `（引出不定式）` `（贬义强调）` ——
     整条只有括注、没有对应词，等于没写。prompt 里明令禁止，仍漏了这几条。
  ② **与本次之前就有的标签重复**（143 条）：`ecuador` 已有「赤道」，新生成的又是「赤道」。
  ③ **本次生成的两条互相重复**（23 条）：`voz` 两条义项都标「声部」、`algo` 两条都标
     「稍微；有点」。⇒ 保留 rank 最小的那条。

🔴 ②③ 必须分开处理，第一版只做了 ③：新标签若与**本次之前就有**的重复，
   在「本次生成的行」之间去重是发现不了的 —— 那 143 条会全部漏网。

⭐ **删掉不是丢数据**：`sense_gloss` 里那条 `zh/definition` 还在，展示层取
   「最短的那条中文」会自然退回显示长定义。**长一点的正确定义** 严格优于
   **一个错的或重复的标题** —— 框架第一条判据「错比缺更伤权威」。

⚠️ 不动的两类（看着像瑕疵，其实不是）：
  · 「超 10 字」87 条：`原住民血统的奎卡舞女伴` 确实需要这么多字才说得清，
    强行砍到 10 字会丢信息
  · 「中英混排」28 条：`UNO牌戏` / `truco牌戏` / `里拉体（ABABB）` 里的拉丁字母
    是专名与韵式代号，prompt 本来就放行

用法：
    python3 -m es.fixes.drop_bad_labels
    python3 -m es.fixes.drop_bad_labels --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SRC = "llm-label-v4pro"
ONLY_PAREN = re.compile(r"^[（(][^）)]*[）)]$")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT g.sense_id, g.text, s.word_id, s.rank, d.word "
        "FROM sense_gloss g JOIN sense s ON s.id = g.sense_id "
        "JOIN dict d ON d.id = s.word_id WHERE g.src = ?", (SRC,)).fetchall()
    # 🔴 要分两种重复，第一版只做了前一种：
    #    (a) 本次生成的两条互相重复  → 留 rank 最小的
    #    (b) 本次生成的与**本次之前就有**的重复 → 新的那条一律删（旧的是既有事实）
    sib = collections.defaultdict(collections.Counter)   # 全部（含本次）
    old = collections.defaultdict(set)                   # 本次之前就有的
    for wid, t, src in con.execute(
            "SELECT s.word_id, g.text, g.src FROM sense_gloss g "
            "JOIN sense s ON s.id = g.sense_id "
            "WHERE g.lang='zh' AND g.kind='equivalent'"):
        sib[wid][t] += 1
        if src != SRC:
            old[wid].add(t)
    con.close()

    drop, stat, ex = [], collections.Counter(), collections.defaultdict(list)
    keep_first = {}
    for sid, txt, wid, rank, word in sorted(rows, key=lambda r: (r[2], r[3])):
        if ONLY_PAREN.match(txt):
            drop.append(sid)
            stat["① 纯领域标记，无对应词"] += 1
            ex["①"].append((word, txt))
            continue
        if txt in old[wid]:
            drop.append(sid)
            stat["② 与本次之前就有的标签重复"] += 1
            ex["②"].append((word, txt))
            continue
        if sib[wid][txt] > 1:
            if keep_first.get((wid, txt)) is None:
                keep_first[(wid, txt)] = sid          # rank 最小的留下
                stat["  （本次内重复：保留 rank 最小的）"] += 1
                continue
            drop.append(sid)
            stat["③ 本次生成的两条互相重复" ] += 1
            ex["③"].append((word, txt))

    for k, v in stat.most_common():
        print(f"  {k:<30}{v:>6,}")
    print(f"\n待删 {len(drop):,} 条 / 共 {len(rows):,}   {len(drop)/len(rows)*100:.2f}%")
    for k in ("①", "②", "③"):
        print(f"  {k} 样例：{ex[k][:6]}")

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("drop-bad-labels", expect={}) as s:
        s.executemany(
            "DELETE FROM sense_gloss WHERE sense_id=? AND lang='zh' AND kind='equivalent' "
            "AND src=?", [(i, SRC) for i in drop])

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    left = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE src=?", (SRC,)).fetchone()[0]
    # 删完之后，这些义项必须仍有中文（退回长定义），一条都不能变成空
    naked = con.execute(
        "SELECT COUNT(*) FROM sense s WHERE NOT EXISTS ("
        "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')").fetchone()[0]
    con.close()
    print(f"\n落库后：短标签剩 {left:,} 条；没有任何中文的义项 {naked}（必须为 0）")
    assert naked == 0


if __name__ == "__main__":
    main()
