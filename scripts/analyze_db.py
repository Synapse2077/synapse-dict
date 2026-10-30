#!/usr/bin/env python3
"""B11：给 es／fr／it 跑 `ANALYZE`（另七门早已有 `sqlite_stat1`）。2026-10-27。

═══ 为什么不走 `dbtool.session` ═══
ko 那次走了 session，而 session 会先**整库备份**：es/fr/it 合计 5.5 GB，复制一遍会触发备份的
8 GB 字节封顶去删旧备份（`[[backup-retention]]` 咬过七次的地方）。`ANALYZE` **一行业务数据都不动**，
且完全可逆（`DROP TABLE sqlite_stat1` ＝ 回到原来的计划器行为）—— 为它冒丢历史备份的险不值。
⇒ 等价的保护：写前写后各取一次本门 `dbtool.snapshot()`（全部被追踪的列与表的计数），**逐项相等**，否则报红。

═══ 结论不预设 ═══
ko：`ANALYZE` 一条 51 ms → 0.04 ms；vi：没有可测变化，真正起作用的是索引。
⇒ 跑前跑后用 `scripts/query_plans_probe.py`（计划形状）＋ 页面计时（读者口径）各量一次，如实记。

回滚：  sqlite3 <库> "DROP TABLE sqlite_stat1; DROP TABLE IF EXISTS sqlite_stat4;"

用法：
    python3 scripts/analyze_db.py --lang es [--apply]
"""
import argparse
import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def dbtool_of(lang):
    sys.path.insert(0, str(ROOT / lang))
    spec = importlib.util.spec_from_file_location("dbtool_" + lang, ROOT / lang / "dbtool.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=("es", "fr", "it"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    dbt = dbtool_of(a.lang)
    db = Path(dbt.DB)
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    have = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'").fetchone()[0]
    con.close()
    print("■ %s  %s  统计信息：%s" % (a.lang, db.name, "已有" if have else "没有"))
    if not a.apply:
        print("（干跑。加 --apply 才跑 ANALYZE）")
        return
    before = dbt.snapshot()
    t0 = time.time()
    rw = sqlite3.connect(db)
    rw.execute("ANALYZE")
    rw.commit()
    rw.close()
    print("   ANALYZE 用时 %.1f 秒" % (time.time() - t0))
    after = dbt.snapshot()
    diff = {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if before.get(k) != after.get(k)}
    if diff:
        raise SystemExit("🔴 业务数据计数变了（ANALYZE 不该动任何一行）：%s" % diff)
    print("   ✅ 写前写后快照逐项相等（%d 项）" % len(before))
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    print("   sqlite_stat1 %d 行" % con.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0])


if __name__ == "__main__":
    main()
