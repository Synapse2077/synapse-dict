#!/usr/bin/env python3
"""阶段 5c 探路：en 的搭配层能不能从现有数据里做出来。2026-09-08。零 API、只读。

用户 2026-09-08 问「搭配和已有的词组有什么关系，搭配不也是词组吗？」——
量出来它们是两样东西，判据是**目标是不是独立词条**：

    en  derived 多词目标 339,285 ／ 是独立词条 303,996 = **89.6%**   ← 交叉引用「去看那个词条」
    de  collocation 目标  16,783 ／ 是独立词条   2,005 = **11.9%**   ← 用法示范「常跟什么一起用」

    field → playing field   `playing field` 自己是词条，有自己的义项
    frei  → frei haben      `frei haben` 不是词条，查 frei 的人跳不过去

⇒ 两个候选源，都零成本：
  ① `derived` 里那 10.4% **不是词条**的多词目标 —— 它们正好是"不是词条的词组"
  ② 例句里统计高频共现 —— 语料事实，但要防"高频≠搭配"（`the of` 也高频）

🔴 **不用模型生成搭配** —— 生成的搭配是编的，不是语料事实
   （`FRAMEWORK §一` 错比缺更伤权威）。

    cd en && python3 -u probes/collocation_source.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import re
import sqlite3

import paths

STOP = set("a an the of to in on at for with by from as is are was were be been being "
           "and or but if then than that this these those it its he she they them his her "
           "not no do does did have has had will would can could shall should may might "
           "i you we who whom which what when where how".split())


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = con.execute
    words = {w for (w,) in q("SELECT word FROM dict")}
    wid = dict(q("SELECT word, id FROM dict"))

    # ── ① derived 里不是词条的多词目标
    cand = collections.defaultdict(list)
    n_multi = 0
    for w, t in q("SELECT d.word, r.target FROM sense_relation r JOIN dict d ON d.id=r.word_id "
                  "WHERE r.kind='derived' AND r.target LIKE '% %'"):
        n_multi += 1
        if t not in words:
            cand[w].append(t)
    n_cand = sum(len(v) for v in cand.values())
    print("═══ ① `derived` 里**不是词条**的多词目标 ═══")
    print("   多词目标 %s ／ 其中不是词条 %s = %.1f%% ／ 涉及 %s 个词"
          % (format(n_multi, ","), format(n_cand, ","), 100 * n_cand / n_multi,
             format(len(cand), ",")))
    print("   样本（挑常用词，**避开只看一个词那个错**）：")
    for w in ("hand", "water", "run", "light", "book", "time"):
        if cand.get(w):
            print("      %-8s %s" % (w, "、".join(cand[w][:6])))
    # 这批里有多少其实是**短语动词/固定搭配**（含虚词），有多少是复合名词
    with_stop = sum(1 for v in cand.values() for t in v
                    if any(x in STOP for x in t.lower().split()))
    print("   含虚词（多半是短语动词/介词搭配）%s = %.1f%%"
          % (format(with_stop, ","), 100 * with_stop / max(n_cand, 1)))

    # ── ② 例句里的共现（只做可行性判断，不建库）
    print("\n═══ ② 例句共现能不能当搭配源 ═══")
    ex = q("SELECT word, text FROM example WHERE sense_id IS NOT NULL LIMIT 200000").fetchall()
    pair = collections.Counter()
    for w, t in ex:
        lw = w.lower()
        toks = re.findall(r"[A-Za-z']+", t.lower())
        for i, x in enumerate(toks):
            if x != lw:
                continue
            for j in (i - 1, i + 1):
                if 0 <= j < len(toks):
                    o = toks[j]
                    if o in STOP or len(o) < 2:
                        continue
                    pair[(lw, o if j > i else o)] += 1
    top = pair.most_common(12)
    print("   扫了 %s 条例句，共现对 %s 组" % (format(len(ex), ","), format(len(pair), ",")))
    print("   前 12：%s" % "  ".join("%s+%s(%d)" % (a, b, n) for (a, b), n in top))
    print("\n   ⚠️ 这条路的问题：**高频共现 ≠ 搭配**。要判「这两个词是不是固定搭配」")
    print("      得有互信息/对数似然一类的统计量，而且还要人验 —— 不是一步能做完的。")
    con.close()
    return 0


if __name__ == "__main__":
    _sys.exit(main())
