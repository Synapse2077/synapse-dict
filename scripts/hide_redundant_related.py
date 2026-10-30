#!/usr/bin/env python3
"""B17：藏掉兜底的冗余 `related`（`hidden=1`，不删）。2026-10-27。

判据只有一个家：`scripts/redundant_related.py`（本脚本与跨门闸都 import 它）。
写库走各门自己的 `dbtool.session`（备份＋行数闸＋写后回归闸）。

    python3 -u scripts/hide_redundant_related.py --lang de            # 只报代价
    python3 -u scripts/hide_redundant_related.py --lang de --write    # 写库

写之前三笔代价必须摊开（ko K34 的做法，`[[consult-two-models-on-rules]]`「兜底分支要单独量」）：
  ① 「相关词」整行消失的页面数；② 一条关系都不剩的页面（必须 0）；
  ③ 零信息损失：每个被藏的目标在同页还在别的可见 kind 下（必须全中）。
⚠️ 「页面上真的印了两遍」由渲染核对过（2026-10-27 每门 300 页：de 741/741、ja 536/536、es 339/339；
   de 那次先逮到服务层 `LIMIT 200` 截断，去掉后才全中）—— 那一步读 HTML，不在本脚本里。
"""
import argparse
import collections
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from redundant_related import REGISTRY, redundant, _fold  # noqa: E402

f = lambda n: format(n, ",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=sorted(REGISTRY))
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / a.lang))
    import dbtool  # 各门自己的写库闸门
    reg = REGISTRY[a.lang]

    con = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    rows = con.execute("SELECT id, word_id, sense_id, kind, target FROM sense_relation"
                       " WHERE COALESCE(hidden,0)=0").fetchall()
    drop = redundant(rows, reg["subsume"], reg["floated"])
    dropset = set(drop)
    print("■ %s：可见关系 %s ／ 可见 related %s ／ 冗余 related %s"
          % (a.lang, f(len(rows)), f(sum(1 for r in rows if r[3] == "related")), f(len(drop))))

    rel_page = collections.Counter(w for _i, w, _s, k, _t in rows if k == "related")
    all_page = collections.Counter(w for _i, w, _s, _k, _t in rows)
    drop_page = collections.Counter(w for i, w, _s, _k, _t in rows if i in dropset)
    gone = [w for w, n in drop_page.items() if rel_page[w] == n]
    naked = [w for w, n in drop_page.items() if all_page[w] == n]
    print("   ① 「相关词」整行消失的页面   %s / %s（%.2f%%）"
          % (f(len(gone)), f(len(rel_page)), 100.0 * len(gone) / max(len(rel_page), 1)))
    print("   ② 一条关系都不剩的页面       %s %s" % (f(len(naked)), "✅" if not naked else "🔴"))
    left = collections.defaultdict(set)
    for i, w, _s, k, t in rows:
        if i not in dropset and k in reg["subsume"]:
            left[w].add(_fold(t))
    lost = [i for i, w, _s, _k, t in rows if i in dropset and _fold(t) not in left[w]]
    print("   ③ 藏掉后同页再也看不到的目标 %s %s" % (f(len(lost)), "✅" if not lost else "🔴"))
    if naked or lost:
        raise SystemExit("🔴 代价不成立，不写库")

    kinds = collections.Counter()
    by = collections.defaultdict(set)
    for _i, w, s, k, t in rows:
        if k != "related":
            by[(w, _fold(t))].add(k)
    for i, w, _s, _k, t in rows:
        if i in dropset:
            for k in by[(w, _fold(t))] & reg["subsume"]:
                kinds[k] += 1
    print("   被哪些更具体的 kind 覆盖：" + "  ".join("%s %s" % (k, f(n)) for k, n in kinds.most_common()))
    con.close()

    if not a.write:
        print("\n(未加 --write，未写库)")
        return
    before = sqlite3.connect(dbtool.DB).execute(
        "SELECT COUNT(*) FROM sense_relation WHERE COALESCE(hidden,0)<>0").fetchone()[0]
    with dbtool.session("keep-b17-redundant-related", expect={}) as s:
        s.executemany("UPDATE sense_relation SET hidden=1 WHERE id=?", [(i,) for i in drop])
    c2 = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    after = c2.execute("SELECT COUNT(*) FROM sense_relation WHERE COALESCE(hidden,0)<>0").fetchone()[0]
    rest = redundant(c2.execute("SELECT id, word_id, sense_id, kind, target FROM sense_relation"
                                " WHERE COALESCE(hidden,0)=0").fetchall(), reg["subsume"], reg["floated"])
    print("\n■ 写后核对：hidden 行 %s → %s（%+d，期望 %+d）%s ／ 剩余冗余 %s %s"
          % (f(before), f(after), after - before, len(drop),
             "✅" if after - before == len(drop) else "🔴", f(len(rest)), "✅" if not rest else "🔴"))


if __name__ == "__main__":
    main()
