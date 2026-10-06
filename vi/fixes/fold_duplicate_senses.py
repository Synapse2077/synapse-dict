#!/usr/bin/env python3
"""W25：把**同一个义项被两版各描述了一遍**的那批折起来。vi，2026-10-05。

═══ 缺陷长什么样 ═══
读者在一个词条页上看见两条几乎一样的义项：

    qua   义项「幸存」[en 版]          ／ 义项「脱离死亡」[vi 版]
    be    义项「撑开袋口以便装满」[en]  ／ 义项「用手抬高斗口、桶口以量得更多」[vi]

⭐ 这笔账是做 W24（例句重复）时量出来的 —— W24 第一版那 1,569 组里 1,374 组挂的是
  **不同**义项，而读那些义项一眼看出根因不在例句层。

═══ 判据在 `criteria.py` §⑩，本脚本不重判 ═══
`dup_sense_groups()` 四次收窄（1,817 → 扣跨 entry 484 → 扣两条不同英文 72 →
**1,236 组 / 1,621 条**），每一次的理由都写在那边。

═══ 🔴🔴 折叠必须搬三样东西，少搬一样就是在页面上丢内容 ═══
① **释义**：622 组是互补的（一条只有英文、另一条只有越南语）⇒ 并到留下来那条。
   `sense_gloss` 有 `UNIQUE(sense_id, lang, text)` ⇒ 并过去天然幂等。
② **例句** 744 条可出版 ／ ③ **关系** 53 条：
   🔴 这两样**不在本脚本里搬**，由两个收割器过 `criteria.merged_sense_map()` 自己解析
   （`sense.merged_into` 这一列就是为此存在的）。理由见 `ADD_COLUMNS` 的注释：
   外锚闸的例句恒等式含 `sense_id`，直接 UPDATE 会判红而它会是对的。
   ⇒ 本脚本跑完**必须**接着跑：
        python3 -u vi/pipeline/build_example_layer.py  --sync --apply
        python3 -u vi/pipeline/build_relation_layer.py --sync --apply
   而「必须接着跑」做成了机制：`dbtool` 的 `invalidates` 会把两道闸标成过期。

═══ ⭐ 完全可逆 ═══
被折的义项 `hidden=1` 而**释义一条不删**（W12 定的「隐藏不删释义」，实测现有
186 条隐藏义项 186 条都带释义）。付费的中文一个字不丢，`merged_into` 清掉就全回来。

用法：
    python3 -u vi/fixes/fold_duplicate_senses.py            # 只报
    python3 -u vi/fixes/fold_duplicate_senses.py --apply
"""
import argparse
import collections
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import build_v3_schema as SCHEMA                          # noqa: E402
import dbtool                                             # noqa: E402
import paths                                              # noqa: E402
from criteria import dup_sense_groups, DUP_SENSE_WHY      # noqa: E402

F = lambda n: format(n, ",")                              # noqa: E731
# 并过去的释义用这个 `src` —— 与两个既有写入方（版本名 / `model:*`）分得开。
# 🔴 ko 的 **K14** 就是栽在「两个写入方在 `src` 列分不开」上。
MERGED_SRC = "merged:w25"


def plan(con):
    """→ (折叠行, 要并的释义行, 统计, 逐条清单)"""
    groups, stat = dup_sense_groups(con)
    g = collections.defaultdict(dict)
    sids = [s for keep, drop in groups for s in [keep] + drop]
    if sids:
        for sid, lang, t in con.execute(
                "SELECT sense_id, lang, text FROM sense_gloss WHERE sense_id IN (%s)"
                % ",".join(map(str, sids))):
            g[sid][lang] = (t or "").strip()
    fold, add, listed = [], [], []
    for keep, drop in groups:
        for d in drop:
            fold.append((keep, d))
        # ① 释义并过去：留下来那条**缺哪一语就补哪一语**，已有的一个字不动
        #    （已有的多半是付费的，拿免费的盖掉付费的是反方向）
        for lang in ("en", "vi", "zh"):
            if g[keep].get(lang):
                continue
            for d in drop:
                if g[d].get(lang):
                    add.append((keep, lang, g[d][lang], MERGED_SRC))
                    stat["并过去的释义：%s" % lang] += 1
                    break
        listed.append((keep, drop, g[keep].get("zh", "")))
    return fold, add, stat, listed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    fold, add, stat, listed = plan(con)
    for k, v in stat.most_common():
        print("   %-46s %6s" % (k, F(v)))
    print("\n■ 要折 %s 条义项（并进 %s 条留下来的），要并 %s 条释义"
          % (F(len(fold)), F(len({k for k, _d in fold})), F(len(add))))
    # 🔴 **读者口径**：折完之后这些词条页上少印几条义项
    wids = {r[0] for r in con.execute(
        "SELECT word_id FROM sense WHERE id IN (%s)"
        % ",".join(str(d) for _k, d in fold))} if fold else set()
    print("   ⇒ 涉及 %s 个词形的页面" % F(len(wids)))
    # 🔴 **被折的义项上挂着什么**：不搬走就在页面上消失
    if fold:
        q = ",".join(str(d) for _k, d in fold)
        ex = con.execute("SELECT COUNT(*) FROM example WHERE hidden=0 "
                         "AND sense_id IN (%s)" % q).fetchone()[0]
        rel = con.execute("SELECT COUNT(*) FROM sense_relation WHERE hidden=0 "
                          "AND sense_id IN (%s)" % q).fetchone()[0]
        print("   ⚠️ 它们身上挂着 **%s 条可出版例句 ／ %s 条关系** —— "
              "由两个收割器过 `merged_sense_map()` 解析，**不在本脚本里搬**" % (F(ex), F(rel)))
    print("\n■ 抽 %d 组看（留下来的 ← 被折的）" % a.show)
    for keep, drop, zh in listed[:a.show]:
        w = con.execute("SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id "
                        "WHERE s.id=?", (keep,)).fetchone()[0]
        print("   %-16s 中文「%s」  留 #%s ← 折 %s"
              % (w, zh[:24], keep, ", ".join("#%s" % d for d in drop)))
    con.close()
    if not a.apply:
        print("\n(只报不写。加 --apply。)")
        return
    if not fold:
        return
    with dbtool.session(
            "vi-w25-fold-duplicate-senses",
            expect={"__rows__": 0,
                    "sense.hidden_why": len(fold),
                    "sense.merged_into": len(fold),
                    "#sense_gloss": len(add),
                    "sense_gloss.sense_id": len(add),
                    "sense_gloss.lang": len(add),
                    "sense_gloss.text": len(add),
                    "sense_gloss.src": len(add)},
            invalidates=[]) as s:
        # 🔴 列先补上再写：`ADD_COLUMNS` 是建表那一侧的登记表，这里调它而不是
        #    自己写 `ALTER TABLE`（两份 DDL 迟早漂开）。
        have = {r[1] for r in s.execute("PRAGMA table_info(sense)")}
        for tbl, col, typ in SCHEMA.ADD_COLUMNS:
            if tbl == "sense" and col not in have:
                s.execute("ALTER TABLE sense ADD COLUMN %s %s" % (col, typ))
        # ⚠️ **先并释义再折** —— 反过来的话 `dup_sense_groups()` 下一次重算时
        #    被折的那条已经 `hidden=1`，它的释义就取不到了（而我要的正是它）。
        #    `[[expectation-must-be-declared]]` 的操作版：do 需要的东西在 do 之前取齐。
        s.executemany("INSERT OR IGNORE INTO sense_gloss (sense_id, lang, text, src) "
                      "VALUES (?,?,?,?)", add)
        s.executemany("UPDATE sense SET hidden=1, hidden_why=?, merged_into=? WHERE id=?",
                      [(DUP_SENSE_WHY, k, d) for k, d in fold])


if __name__ == "__main__":
    main()
