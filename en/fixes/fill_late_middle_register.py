#!/usr/bin/env python3
"""B1：en 的 `Late`／`Middle` 两个语域标签 —— 代码 09-15 就认了，库里一直是 0 条。定点补录，不重跑标签层。2026-10-31。

═══ 缺陷 ═══
源头把「Late Modern English」「Middle English」拆成两个 tag（`ablatitious` 的 tags 是 `['Late','Modern','obsolete']`）。
`build_sense_tags.py` 第一版只收了 `Early`＋`Modern`，`Late`／`Middle` 落进 drop-ledger；09-15 把它俩补进了 `REGISTER`，
**但没重跑** ⇒ 页面上 `ablatitious` 印「现代英语 · 废弃」，丢了「晚期」（展示层映射 `Late→晚期` 早写好了，只等数据）。
（`Middle` 那一半见下一节：回源之后发现它根本不是时代层。）

═══ 为什么不重跑 `build_sense_tags.py` ═══
它是「清空重建」，会撤销建库后定点改过的那几轮（专名标记传播、`particle` 改判 —— 见它自己的文件头）。
`[[replay-scripts-undo-fixes]]`。

═══ 🔴🔴 回源之后改了方案：`Middle` 不是时代层 ═══
源头 10 条 `Middle` **全部**与 `East` 成对（`mandi` ['East','Middle','Yemen']）——是「Middle East」被拆开。
09-15 把它当成 `Late` 的兄弟项补进 `REGISTER` 是错的；照原账「重跑落地」会给中东用法印「中古」。
⇒ 标签层改了产出逻辑（`merge_split_tags()`：`Middle`＋`East` ⇒ 地区 `Middle-East`，展示「中东」），本脚本照它补库。

═══ 判据：调用标签层**自己的** `collect()`，不另写一份 ═══
补：新逻辑产出而库里没有的 `register:Late`、`region:Middle-East`。
撤：中东义项上单独挂着的 `region:East`（新逻辑不再产出，它是 Middle East 的一半，页面上印成「东部」）。
其余一行不碰。义项已不在 `sense` 表里的不补，单独印出来。

跑（在仓库根）：
    python3 -u en/fixes/fill_late_middle_register.py            # 干跑
    python3 -u en/fixes/fill_late_middle_register.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import sqlite3

import dbtool
import paths
from build_sense_tags import collect

ADD = {("register", "Late"), ("region", "Middle-East")}


def plan():
    """→ (要补的行, 要撤的行, 义项已不在库里的, 展示用)。两边都由 `collect()` 的产出决定。"""
    rows, _dropped, _stat = collect()
    want = set(rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = set(con.execute("SELECT sense_id, kind, value FROM sense_tag WHERE (kind, value) IN "
                           "(('register','Late'),('region','Middle-East'),('region','East'))"))
    alive = {r[0] for r in con.execute("SELECT id FROM sense")}
    add = sorted(r for r in want if (r[1], r[2]) in ADD and r not in have and r[0] in alive)
    gone = sorted(r for r in want if (r[1], r[2]) in ADD and r[0] not in alive)
    me = {r[0] for r in want if r[1:] == ("region", "Middle-East")}
    # 撤：中东义项上单独挂着的 `East` —— 新逻辑不再产出它（它是 Middle East 的一半）
    drop = sorted(r for r in have if r[1:] == ("region", "East") and r[0] in me and r not in want)
    show = {}
    for sid in {r[0] for r in add + drop}:
        w, tags = con.execute(
            "SELECT d.word, (SELECT group_concat(kind || ':' || value, ' ') FROM sense_tag WHERE sense_id=s.id "
            " AND kind IN ('register','region')) FROM sense s JOIN dict d ON d.id=s.word_id WHERE s.id=?", (sid,)).fetchone()
        show[sid] = (w, tags)
    con.close()
    return add, drop, gone, show


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    add, drop, gone, show = plan()
    for sid, k, v in add:
        print("   + %-17s 义项 %-8d %-20s 现有：%s" % ("%s:%s" % (k, v), sid, show[sid][0], show[sid][1]))
    for sid, k, v in drop:
        print("   - %-17s 义项 %-8d %-20s" % ("%s:%s" % (k, v), sid, show[sid][0]))
    print("■ 补 %d 行（晚期 %d／中东 %d）、撤 %d 行（中东义项上单独的 East）；义项已不在库里的 %d 行不补" % (
        len(add), sum(1 for r in add if r[2] == "Late"), sum(1 for r in add if r[2] == "Middle-East"),
        len(drop), len(gone)))
    if not a.apply or not (add or drop):
        return
    # 30 行的小修：小改动模式（不复制 5 GB 整库，写之前把要动的行存进撤销文件）
    with dbtool.session("en-b1-late-middle-east", expect={"#sense_tag": len(add) - len(drop)}, small=100) as s:
        s.executemany("INSERT INTO sense_tag (sense_id, kind, value) VALUES (?,?,?)", add)
        s.executemany("DELETE FROM sense_tag WHERE sense_id=? AND kind=? AND value=?", drop)
    a2, d2, _g, _s = plan()
    print("■ 写后回核：仍要补 %d、仍要撤 %d（期望 0／0）" % (len(a2), len(d2)))
    if a2 or d2:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
