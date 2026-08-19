#!/usr/bin/env python3
"""删掉 `example` 里「根本不是例句」的那 59 行。2026-08-18。

═══ 为什么是删行、不是重建表 ═══
判据（`ingest_examples.is_not_an_example`）是在**翻译跑完之后**才补全的
（关系笔记 `Coordinate term: stazione`、编辑请求 `(please add an English translation…)`、
占位符 `<>`、模板残渣 `:Modèle:€xemple` 这几族是靠**模型弃权**才被我发现的）。

此刻重跑 `ingest_examples` 会**重建整张表、重新分配 `example.id`**，
而 38,177 条中文是按 `example_id` 挂着的 —— 那正是
[[model-answer-files-key-by-id]] 记的那个事故的形状（答案按行号存，重放时贴错行）。
⇒ **删行不重建**：删行不动任何幸存行的 id。

判据与收词脚本**共用同一个函数**，所以下次重跑收词不会再把它们收回来
（`replay-scripts-undo-fixes`：重放式脚本会静默撤销已完成的修复）。

用法（在 it/ 目录下）：
    python3 fixes/drop_non_examples.py            # 干跑
    python3 fixes/drop_non_examples.py --apply
    python3 fixes/drop_non_examples.py --verify
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402
from ingest_examples import is_not_an_example   # noqa: E402

f = lambda n: format(n, ",")


def scan(con):
    return [(i, w, t) for i, w, t, r in
            con.execute("SELECT id, word, text, ref FROM example")
            if is_not_an_example(t, r)]


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("🔴 库里不许再有「不是例句」的行", len(scan(con)), 0),
        ("🔴 不许留下孤儿译文",
         q("SELECT count(*) FROM example_gloss g WHERE NOT EXISTS"
           "(SELECT 1 FROM example e WHERE e.id=g.example_id)"), 0),
        # 🔴 只删该删的：真例句一条都不许少（基线＝删之前的 38,203 − 59）
        ("🔴 例句总数 == 38,144", q("SELECT count(*) FROM example"), 38144),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-40s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    n_g = ro.execute(
        "SELECT count(*) FROM example_gloss WHERE example_id IN (%s)"
        % ",".join(str(i) for i, _w, _t in rows)).fetchone()[0] if rows else 0
    ro.close()
    print("■ 要删 %s 条例句（连带 %s 条译文）" % (f(len(rows)), f(n_g)))
    for i, w, t in rows[:12]:
        print("     %-16s %s" % (w[:16], t[:64]))
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)")
        return 0
    ids = ",".join(str(i) for i, _w, _t in rows)
    with dbtool.session("drop-non-examples",
                        expect={"__rows__": 0, "#example": -len(rows),
                                "#example_gloss": -n_g}) as s:
        s.execute("DELETE FROM example_gloss WHERE example_id IN (%s)" % ids)
        s.execute("DELETE FROM example WHERE id IN (%s)" % ids)
        s.written = len(rows) + n_g
    print("\n■ 已删 %s 条" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
