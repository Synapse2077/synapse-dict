#!/usr/bin/env python3
"""W11：移出源头倒进词源栏的**读音章节**（vi 版 `cá` 的三段）。vi，2026-11-02。

═══ 缺陷 ═══
`cá` 的词源栏印着 `(Quảng Nam) IPA^((ghi chú)): [kɑː˦˥]`／`Âm thanh (Hà Nội): (tập tin)`／
`Âm thanh (Thành phố Hồ Chí Minh): (tập tin)` —— 源头把读音章节放进了 `etymology_texts`。
判据是**逐字登记的名单** `etym_sources.PRON_SECTION_LEAKS`（形式上像音标的另外 9 段是真词源，见那里的注释）。
收割器已经按它拒收（外锚闸 import 同一个 `collect()`），本脚本删掉**已落库**的那 3 行。

⚠️ 不走 `build_etymology_layer.py --rebuild`：重建会让 `etymology.id` 整体变，而有裁决清单按 rowid 记（B29/markup_pub）。

跑（在仓库根）：
    python3 -u vi/fixes/fix_w11_pron_section.py            # 干跑
    python3 -u vi/fixes/fix_w11_pron_section.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import sqlite3

import dbtool
import paths
import etym_sources as ES


def plan(con):
    """→ 要删的 etymology 行 [(id, 词, 正文)]。"""
    return [(i, w, t) for i, w, t in con.execute(
        "SELECT e.id, d.word, e.text FROM etymology e JOIN dict d ON d.id = e.word_id")
        if (w, t) in ES.PRON_SECTION_LEAKS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = plan(con)
    cols = [r[1] for r in con.execute("PRAGMA table_info(etymology)")]
    con.close()
    for i, w, t in todo:
        print("   删 etymology.id=%d  %s  %r" % (i, w, t))
    print("■ 要删 %d 行（名单 %d 段）" % (len(todo), len(ES.PRON_SECTION_LEAKS)))
    if len(todo) > len(ES.PRON_SECTION_LEAKS):
        raise SystemExit("🔴 命中比名单多 —— 名单里的某一段在别处也出现了，逐条看过再删")
    if not a.apply or not todo:
        return
    exp = {"#etymology": -len(todo)}
    exp.update({"etymology.%s" % c: None for c in cols})
    with dbtool.session("vi-fix-w11-pron-section", expect=exp, invalidates=[], small=10) as s:
        s.executemany("DELETE FROM etymology WHERE id = ?", [(i,) for i, _w, _t in todo])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(plan(con))
    print("■ 写后回核：名单里的读音段还剩 %d 行（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
