#!/usr/bin/env python3
"""按新的归一规则回填 `dict.word_norm`（撇号折成 `'`）。2026-08-17。

═══ 用户会看到什么 ═══
划词选中 `all'alba`（直撇号）→ **查不到**，因为库里存的是 `all’alba`（弯撇号）。

    弯撇号 ’ 的词形   1,333
    直撇号 ' 的词形   1,257
    两种写法都收了的     267      ← 其余约 2,000 个只有一种

网页正文里普遍用 `’`（排版撇号），用户手打用 `'`。意语撇号又是**词形的一部分**
（`all'alba` `sant'Antonio` `d'accordo` `l'Aquila`），所以这不是边角情况。

═══ 判据 ═══
`word_norm = 小写 + 去重音符 + 撇号折成 '`（`split_case_forms.norm`，写入与闸共用同一个函数）。
`dict.word` **一个字节不动** —— 源头怎么写就怎么留，归一只进检索列。

实测：1,334 行的 `word_norm` 会变；268 个键因此合并，**逐对看过全是同一个词的两种写法**
（`Valle d'Aosta` / `Valle d’Aosta`、`L'Aquila` / `L’Aquila`），没有把不同的词并到一起。

⚠️ 只回填还不够：`ItalianDictService.getEntry` 当时只按 `word` 精确匹配，**连 word_norm 都不查**。
   本步之后必须同时改 TS 侧（加 word_norm 回落 + 输入同样归一），否则数据对了界面还是查不到。

用法（在 it/ 目录下）：
    python3 fixes/backfill_word_norm.py            # 干跑
    python3 fixes/backfill_word_norm.py --apply
    python3 fixes/backfill_word_norm.py --verify
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from split_case_forms import norm   # noqa: E402  🔴 与写入共用同一个函数


def scan(con):
    return [(i, w, n, norm(w))
            for i, w, n in con.execute("SELECT id, word, word_norm FROM dict")
            if norm(w) != n]


def gate(con):
    print("\n═══ 闸 ═══")
    left = scan(con)
    checks = [
        ("🔴 word_norm 与归一函数逐行一致", len(left), 0),
        ("🔴 word 列一个字节都没动（撇号仍是源头写法）",
         con.execute("SELECT count(*) FROM dict WHERE word LIKE '%'||char(8217)||'%'")
            .fetchone()[0], 1333),
        ("🔴 归一后能用直撇号查到弯撇号的词",
         con.execute("SELECT count(*) FROM dict WHERE word_norm = ?",
                     ("all'alba",)).fetchone()[0] > 0, True),
        ("（记账）word_norm 有重复的键（改前 18,042）",
         con.execute("SELECT count(*) FROM (SELECT word_norm FROM dict "
                     "GROUP BY word_norm HAVING count(*)>1)").fetchone()[0], 18303),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-44s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    f = lambda x: format(x, ",")
    print("■ word_norm 要改的 %s 行" % f(len(rows)))
    for i, w, o, n in rows[:8]:
        print("   %-30s %-30s → %s" % (w[:30], o[:30], n[:30]))
    merged = defaultdict(set)
    for w, in ro.execute("SELECT word FROM dict"):
        merged[norm(w)].add(w)
    newm = [(k, sorted(v)) for k, v in merged.items() if len(v) > 1 and len({x.lower() for x in v}) > 1]
    print("\n■ 合并到同一 word_norm 的键（抽看是不是同一个词）")
    for k, v in newm[:8]:
        print("   %-28s ← %s" % (k[:28], v[:3]))
    if not a.apply or not rows:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0
    ro.close()
    with dbtool.session("backfill-word-norm", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE dict SET word_norm=? WHERE id=?", [(n, i) for i, _, _, n in rows])
    print("\n■ 已回填 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
