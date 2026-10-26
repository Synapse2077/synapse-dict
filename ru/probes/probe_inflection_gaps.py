#!/usr/bin/env python3
"""阶段 3 收尾探针：**没有变位表的那批词元，是源头没给，还是我们没收？** ru，2026-10-23。

    python3 -u ru/probes/probe_inflection_gaps.py > data/work/ru/probe/probe_inflection_gaps.txt

屈折闸 I10 只锁「覆盖率不许跌」（43.05%），**没有一条回答剩下那 57% 为什么没有**。
`[[dont-say-source-lacks-what-we-skipped]]`：「源头没写」和「我们没抽」要在结构上分开。

做法：从库里取出「有词元身份、而一行屈折都没有」的词，回七源逐个看：
  · 这个词在哪几份源里**以词元身份**出现（`criteria.entry_accept` ＋ 非屈折形）
  · 它那一行的 `forms` 有没有东西
  · 有的话，**每一行被 `criteria.inflection_rows` 判进哪个桶**（判据 import，不重写）
⇒ 三个数：源头一条 forms 都没给／给了但全被拒（按桶）／**给了 ok 行而库里没有**（＝收割器 bug）。
"""
import collections
import gzip
import json
import random
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC                                  # noqa: E402


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    gap = {}   # word → set(pos)
    for w, pos in con.execute(
            "SELECT d.word, e.pos FROM dict d JOIN entry e ON e.word_id=d.id "
            "WHERE d.is_lemma=1 AND NOT EXISTS (SELECT 1 FROM entry e2 "
            "JOIN inflection i ON i.entry_id=e2.id WHERE e2.word_id=d.id)"):
        gap.setdefault(w, set()).add(pos)
    con.close()
    print("■ 没有变位表的词元 %s 个" % format(len(gap), ","))

    # word → src → {"lemma_rows":n, "forms":n, "kinds":Counter}
    seen = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {"lemma_rows": 0, "form_rows": 0, "kinds": collections.Counter()}))
    as_form_only = collections.Counter()      # 在某源里只以屈折形身份出现
    kind_eg = collections.defaultdict(list)
    for src, p in SRC:
        n = 0
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                w = e.get("word")
                if w not in gap:
                    continue
                ok, _skip, pos = criteria.entry_accept(e)
                if not ok:
                    continue
                n += 1
                is_form, _via = criteria.is_inflected_form(e)
                if is_form:
                    as_form_only[src] += 1
                    continue
                rec = seen[w][src]
                rec["lemma_rows"] += 1
                forms = e.get("forms") or []
                tt = None
                for fm in forms:
                    if "inflection-template" in (fm.get("tags") or []):
                        tt = tt or (fm.get("form") or "").strip()
                for fm in forms:
                    rec["form_rows"] += 1
                    kind, _rows = criteria.inflection_rows(
                        w, fm.get("form") or "", fm.get("tags") or [], pos=pos,
                        table_tag=tt)
                    rec["kinds"][kind] += 1
                    if len(kind_eg[kind]) < 4:
                        kind_eg[kind].append("%s → %s %s" % (
                            w, (fm.get("form") or "")[:30], (fm.get("tags") or [])[:4]))
        print("  · %-16s 命中 %s 行" % (src, format(n, ",")), file=sys.stderr)

    # ── 分类：每个缺口词元一个结论 ─────────────────────────────────
    verdict = collections.Counter()
    verdict_pos = collections.defaultdict(collections.Counter)
    eg = collections.defaultdict(list)
    reject_kinds = collections.Counter()
    for w, pset in gap.items():
        srcs = seen.get(w, {})
        lemma_rows = sum(r["lemma_rows"] for r in srcs.values())
        form_rows = sum(r["form_rows"] for r in srcs.values())
        ok_rows = sum(r["kinds"].get("ok", 0) for r in srcs.values())
        if lemma_rows == 0:
            v = "A 七源里都没有以词元身份出现（只是 is_lemma 的或运算标的）"
        elif form_rows == 0:
            v = "B 源头以词元身份给了，但 forms 一条都没有"
        elif ok_rows == 0:
            v = "C 源头给了 forms，全被判据拒掉"
            for r in srcs.values():
                reject_kinds.update(r["kinds"])
        else:
            v = "D 🔴 判据说 ok 而库里没有（收割器 bug）"
        verdict[v] += 1
        for p in pset:
            verdict_pos[v][p] += 1
        if len(eg[v]) < 400:
            eg[v].append(w)

    print("\n§1 每个缺口词元的结论")
    for v, n in sorted(verdict.items()):
        print("   %-48s %9s  %5.2f%%" % (v, format(n, ","), 100.0 * n / len(gap)))
        print("      词性：%s" % verdict_pos[v].most_common(8))
        rnd = random.Random(20261023)
        print("      样本：%s" % " ".join(rnd.sample(eg[v], min(15, len(eg[v])))))

    print("\n§2 C 类被拒的桶（完整值域，不截断）")
    for k, n in reject_kinds.most_common():
        print("   %9s  %s" % (format(n, ","), k))
        for x in kind_eg.get(k, [])[:3]:
            print("              %s" % x)

    print("\n§3 B 类按源：词元行出现在哪些源")
    bsrc = collections.Counter()
    for w in gap:
        srcs = seen.get(w, {})
        if srcs and sum(r["form_rows"] for r in srcs.values()) == 0:
            bsrc[tuple(sorted(s for s, r in srcs.items() if r["lemma_rows"]))] += 1
    for k, n in bsrc.most_common(12):
        print("   %9s  %s" % (format(n, ","), k))
    print("\n   只以屈折形身份出现的命中行（按源）：%s" % dict(as_form_only))


if __name__ == "__main__":
    main()
