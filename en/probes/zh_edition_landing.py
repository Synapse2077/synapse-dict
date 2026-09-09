#!/usr/bin/env python3
"""阶段 1.5a 探针：中文版 wiktionary 的英语条目，**义项级**能落多少。2026-09-07。

═══ 为什么必须量义项级，不能拿词级数 ═══
阶段 -1 量到「zh 版 85,625 个英语词头带汉字释义、落核心 29.6%」——
那是**词级**。`sense_gloss` 要的是**义项级**：123,905 条中文摊在 8.5 万词上 ＝ 1.4 条/词，
而这批词在我们库里的义项数远不止 1.4。**能不能落，取决于两边义项对不对得上。**

═══ 🔴 三档，只做第①档（判据照 de 阶段 1.5c）═══
    ① 库 1 条义项 · zh 版 1 条中文 · 词性相容  → **可做**，无歧义
    ② 库 n 条 · zh 版 n 条，按序位对            → 🔴 **不做**
    ③ 条数不同                                 → ⏳ 需判官，不在本步

**②为什么不做**：它靠「两版义项顺序一一对应」这个假设，而 de 那轮的 ③ 样本直接反证 ——
两版切分粒度根本不同，②只是**碰巧条数相同**。把下标当稳定契约，正是
`[[verification-gates-not-sampling]]` 骂的那件事：**别把义项和释义错配了，那才是真灾难**。
`PLAYBOOK` 也写死「下一门语言不要做自动判重」。

⚠️ 本探针**只读、不写库**，产出落点数字供报价用。

跑：cd en && python3 probes/zh_edition_landing.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import gzip
import json
import sqlite3

import paths
from dbtool import has_han
from pipeline.build_entry_layer import POS_MAP

ZH = paths.DUMPS / "zhwiktionary.jsonl.gz"


def main():
    # ── zh 版：word → {pos: [中文 gloss…]}
    zh = collections.defaultdict(lambda: collections.defaultdict(list))
    n_line = n_en = 0
    with gzip.open(ZH, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            n_line += 1
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("lang_code") != "en":
                continue
            w = (d.get("word") or "").strip()
            if not w:
                continue
            n_en += 1
            pos = POS_MAP.get(d.get("pos") or "", d.get("pos") or "?")
            for s in (d.get("senses") or []):
                for g in (s.get("glosses") or []):
                    if has_han(g):
                        zh[w][pos].append(g.strip())
    print("zh 版 %s 行，英语条目 %s ，带汉字释义的词 %s"
          % (format(n_line, ","), format(n_en, ","), format(len(zh), ",")))

    # ── 库侧：word → {pos: 义项数}，只看有 v3 义项的词
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ours = collections.defaultdict(lambda: collections.defaultdict(int))
    core = set()
    CORE = ("COALESCE(collins,0)>0 OR COALESCE(oxford,0)>0 OR COALESCE(bnc,0)>0 "
            "OR COALESCE(freq_rank,0)>0 OR COALESCE(TRIM(exam_tag),'')<>''")
    for (w,) in con.execute("SELECT word FROM dict WHERE " + CORE):
        core.add(w)
    for w, pos, n in con.execute(
            "SELECT d.word, s.pos, COUNT(*) FROM sense s JOIN dict d ON d.id=s.word_id "
            "GROUP BY d.word, s.pos"):
        ours[w][pos or "?"] = n
    con.close()

    t1 = t2 = t3 = 0
    t1_core = 0
    t1_ex = []
    for w, zp in zh.items():
        op = ours.get(w)
        if not op:
            continue
        for pos, gl in zp.items():
            n_ours = op.get(pos)
            if n_ours is None:
                continue
            if n_ours == 1 and len(gl) == 1:
                t1 += 1
                if w in core:
                    t1_core += 1
                if len(t1_ex) < 10:
                    t1_ex.append((w, pos, gl[0]))
            elif n_ours == len(gl):
                t2 += n_ours
            else:
                t3 += 1
    print("\n═══ 三档落点（按 (词, 词性) 配对）═══")
    print("  ① 库 1 条 · zh 1 条 · 词性相容   %8s   ✅ 可做（其中核心 %s）"
          % (format(t1, ","), format(t1_core, ",")))
    print("  ② n 对 n，按序位                 %8s   🔴 不做（下标不是契约）"
          % format(t2, ","))
    print("  ③ 条数不同                       %8s   ⏳ 需判官，不在本步"
          % format(t3, ","))
    print("\n  ①档样本：")
    for w, pos, g in t1_ex:
        print("     %-18s %-6s %s" % (w[:18], pos, g[:52]))

    # 分母：库里还没有中文的义项
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    tot = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    zhn = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh'").fetchone()[0]
    con.close()
    print("\n═══ 分母 ═══")
    print("  库内义项 %s ，已有中文 %s ⇒ 缺 %s"
          % (format(tot, ","), format(zhn, ","), format(tot - zhn, ",")))
    print("  ⇒ zh 版免费能补 **%s 条（%.2f%%）**" % (format(t1, ","), 100 * t1 / max(tot, 1)))


if __name__ == "__main__":
    main()
