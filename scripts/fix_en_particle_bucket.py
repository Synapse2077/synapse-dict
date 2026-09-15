#!/usr/bin/env python3
"""en：把物理学的 `particle` 从 `grammar` 桶改判到 `topic` 桶。2026-09-15。

═══ 怎么发现的 ═══
在给 `grammar` 补中文映射时，逐个值回库看实际内容（`[[criteria-from-meaning-not-form]]`：
判据不许用形式代理，所以每个值都得看样本）。`particle` 的样本全是：

    [adj] blue     :: Having a colour charge of blue.        {topic=physics}
    [n]  positron  :: The antimatter equivalent of an electron. {topic=physics}
    [n]  charm     :: A quantum number of hadrons.            {topic=physics}

`build_sense_tags.py` 把 `particle` 放进了 `GRAMMAR` 集合，按拼写看它像「小品词」，
按内容看它是「粒子」。227 条里 **225 条带 `topic=physics`**，词性也是 n/adj 为主
（真的小品词词性不会是名词）。⇒ 归桶归错了。

═══ 🔴 判据是「带不带 topic=physics」，不是值本身 ═══
剩下 2 条是**真的语法小品词**，不能一起搬：
    venitive :: Indicating motion to or toward a thing.
    -ahh     :: Used to intensify an adjective…
第一版我打算整条 `value='particle'` 全改 —— 那又是一次「判据比它要描述的东西更宽」
（`[[criteria-narrower-than-you-think]]`）。

═══ 为什么在这儿修、不重跑建库 ═══
`build_sense_tags.py` 重跑会重建整张 `sense_tag`，而这张表在建库之后被
「专名标记传播」那一轮改过（`EN_PLAN` §15.3）—— 重跑等于把那个修复**静默撤销**
（`[[replay-scripts-undo-fixes]]`）。⇒ 这里做定点改判；
同时把 `GRAMMAR` 里的 `particle` 挪到 `TOPIC_TAG`，下次重跑才不会再造一遍。

跑：
    python3 scripts/fix_en_particle_bucket.py            # 预览
    python3 scripts/fix_en_particle_bucket.py --apply
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "en"))
import sqlite3                                                       # noqa: E402

import dbtool                                                        # noqa: E402


def ro():
    return sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)

SEL = """SELECT t.sense_id FROM sense_tag t
         WHERE t.kind='grammar' AND t.value='particle'
           AND EXISTS(SELECT 1 FROM sense_tag p
                      WHERE p.sense_id=t.sense_id AND p.kind='topic' AND p.value='physics')"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = ro()
    ids = [r[0] for r in con.execute(SEL)]
    keep = con.execute("SELECT COUNT(*) FROM sense_tag "
                       "WHERE kind='grammar' AND value='particle'").fetchone()[0] - len(ids)
    # 🔴 改判前先确认不会撞主键（PK 是 sense_id+kind+value）：
    #    已经有 topic=particle 的义项不能再插一条同名的。
    clash = con.execute(
        "SELECT COUNT(*) FROM sense_tag g WHERE g.kind='grammar' AND g.value='particle' "
        "AND EXISTS(SELECT 1 FROM sense_tag t WHERE t.sense_id=g.sense_id "
        "AND t.kind='topic' AND t.value='particle')").fetchone()[0]
    con.close()

    print(f"■ grammar=particle 改判到 topic：{len(ids)} 条")
    print(f"■ 留在 grammar 的真·小品词：{keep} 条（venitive / -ahh）")
    print(f"■ 会撞主键的：{clash} 条")
    if clash:
        sys.exit("🔴 有主键冲突，先看清楚再改")
    if not a.apply:
        print("\n(预览。确认后 --apply)")
        return

    # 行数不变（只换 kind），所以 `#sense_tag` 的期望增量是 0 ——
    # 不写进 expect 也行（没写的表默认要求零变化），显式写出来是给读的人看的。
    with dbtool.session("fix-en-particle-bucket", expect={"#sense_tag": 0}) as s:
        s.executemany("UPDATE sense_tag SET kind='topic' "
                      "WHERE sense_id=? AND kind='grammar' AND value='particle'",
                      [(i,) for i in ids])

    con = ro()
    g = con.execute("SELECT COUNT(*) FROM sense_tag "
                    "WHERE kind='grammar' AND value='particle'").fetchone()[0]
    t = con.execute("SELECT COUNT(*) FROM sense_tag "
                    "WHERE kind='topic' AND value='particle'").fetchone()[0]
    con.close()
    print(f"\n═══ 写后回核 ═══\n   grammar=particle {g}（期望 {keep}）"
          f"\n   topic=particle   {t}（期望 {len(ids)}）")
    if g != keep or t != len(ids):
        sys.exit("🔴 回核对不上")
    print("   ✅")


if __name__ == "__main__":
    main()
