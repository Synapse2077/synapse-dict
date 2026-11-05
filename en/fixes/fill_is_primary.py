#!/usr/bin/env python3
"""填 `pronunciation.is_primary`（EN_PLAN §16.7①）。en，2026-11-02。

═══ 缺陷 ═══
阶段 4 建了这一列、一行都没填（498,477 行全是 0），而展示层按 `ipa` 字母序排读音 ⇒ 每个地区「印在第一、做成可点按钮」的
那一条是任意的：`curious` 英式第一条是边缘转写 `/ˈkjɵːɹɪjəs/`，源头列在第一位的标准读音 `/ˈkjʊə.ɹi.əs/` 被排到后面。

═══ 判据：「主读音」＝源头列在第一位的那条 ═══
每个（词形, 地区）一组 —— 地区为空的也自成一组 —— 恰好一行 `is_primary=1`：
  · 源头（`en-edition`）给了这个地区的读音 ⇒ 取源头列出的**第一条**（行号顺序＝源头 `sounds[]` 顺序，2026-11-02 拿 `tomato` 回 dump 对过）；
  · 源头一条都没给 ⇒ 才轮到我们自己生成的（`en-selfgen`）那条。
⚠️ 「源头列在第一位」是维基词典编辑的约定（通行的写在前），不是源头的结构字段 —— 列名叫 primary，注释说清它是**顺序推出来的**。
⚠️ 依赖 `region` 的分法：§16.7⑤（一条读音带几个地区标签只记了第一个）修好、读音层按地区拆行重建之后，
   本脚本要重跑一次 —— 回归闸 A16 逐行比判据，到时会红，逼人重跑。

跑（在仓库根）：
    python3 -u en/fixes/fill_is_primary.py            # 干跑
    python3 -u en/fixes/fill_is_primary.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3

import dbtool
import paths
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))
from build_pronunciation import PRIMARY_SQL  # noqa: E402  —— 判据只有这一份


def plan(con):
    """→ 应当 `is_primary=1` 的行号集合。回归闸 A16 import 它重算。判据的家在 `build_pronunciation.PRIMARY_SQL`。"""
    return {i for (i,) in con.execute(PRIMARY_SQL)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    want = plan(con)
    have = {i for (i,) in con.execute("SELECT id FROM pronunciation WHERE is_primary = 1")}
    total = con.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0]
    con.close()
    on, off = sorted(want - have), sorted(have - want)
    print("■ 读音 %s 行／（词形, 地区）%s 组 ⇒ 主读音应有 %s 行；要标 %s ／要取消 %s"
          % (format(total, ","), format(len(want), ","), format(len(want), ","),
             format(len(on), ","), format(len(off), ",")))
    if not a.apply or not (on or off):
        return
    with dbtool.session("en-fill-is-primary") as s:
        s.executemany("UPDATE pronunciation SET is_primary = 1 WHERE id = ?", [(i,) for i in on])
        s.executemany("UPDATE pronunciation SET is_primary = 0 WHERE id = ?", [(i,) for i in off])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(plan(con) ^ {i for (i,) in con.execute("SELECT id FROM pronunciation WHERE is_primary = 1")})
    print("■ 写后回核：与判据不一致 %d 行（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
