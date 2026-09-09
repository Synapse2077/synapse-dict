#!/usr/bin/env python3
"""v3 义项一条中文都没有的词，**放行 ECDICT 人工中文**。2026-09-08（阶段 7 照出来的）。

═══ 怎么发现的 ═══
阶段 7 的回归闸 F1「核心词一条中文都没有」报 13 条，其中有 **`oneself`（freq_rank 7,598）**。
回源一读，机制是三条正确的决定叠在一起产生的洞：

  ① 阶段 3b：「对已有 v3 义项的词，`legacy_gloss.published=0`」
     —— 对的，v3 义项层比 ECDICT 的词条级释义精细。
  ② 阶段 1.5：**指针义项有意不花钱翻**（省了 70 万条）—— 对的。
  ③ 阶段 8：`fill_pointer_gloss.py` 用模板补到 **99.5%** —— 也对的。

    但 ①**默认了「有 v3 义项 ⇒ 就有中文」**。落在 ③ 那 0.5% 缺口里的词，
    v3 侧没中文、ECDICT 侧被 ① 压着 ⇒ **读者看到的是空的**，
    而中文就躺在旁边（`oneself` → `pron. 自己, 亲自`）。

🔴 **三个决定各自都对，合起来产生一个谁都没负责的洞。**
   闸的价值正在这里：它不问「你这一步做对了吗」，问「**读者现在看得到吗**」。

═══ 判据 ═══
词形**有** v3 义项 ＋ 这些义项**一条 `lang='zh'` 都没有** ＋ 有 `published=0` 的 ECDICT 释义
⇒ 放行（`published=1`）。

实测 3,008 个词形没有任何中文，其中 **2,494 个**手上有 ECDICT 人工中文（零成本可救），
剩下 514 个连 ECDICT 也没有（**真·无处可救，留空不造**，
`[[blind-gloss-inference-ceiling]]`：无源可查让模型按构词猜，错误率卡在 24-25%）。

    cd en && python3 -u fixes/publish_legacy_when_no_zh.py
    cd en && python3 -u fixes/publish_legacy_when_no_zh.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import sqlite3

import dbtool
import paths

# 🔴 判据只写一次，闸和写库共用
NO_ZH = """EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)
       AND NOT EXISTS(SELECT 1 FROM sense s JOIN sense_gloss g
                      ON g.sense_id=s.id AND g.lang='zh' WHERE s.word_id=d.id)"""
# 🔴🔴 **只放行说得出来源、且不是豆包写的那三档。**
#    第一版没写这个条件，2,494 条里混进去 567 条不该出版的，闸没逮到 ——
#    因为我写了三条负控（有中文的没被顺手放行／无处可救的仍为空／oneself 有中文了），
#    **唯独没写「放出去的东西质量够不够」**。
#      · `low` 26 条 ＝ ECDICT 的网络抓取垃圾（`Bilzerian → '[网络] 平底锅'`，
#        那是个姓氏不是平底锅）。阶段 3b 有意压着 20.8 万条 `low`，
#        我这一步等于从后门放了 26 条出去 —— **错比缺更伤权威**（`[[dict-framework-doc]]`）。
#      · `fixed`/`judged` 541 条 ＝ **豆包写的**。§八 白纸黑字「放弃老库豆包写的那批」，
#        把它们印给读者与那个决定直接冲突。
#    ⇒ 判据加一档 `qual`。**负控要覆盖每一个输出维度，不只是"有没有多放/少放"，
#      还要问"放出去的是什么"**（`[[control-must-cover-every-output-field]]`）。
PUBLISHABLE = ("core", "good", "fair")

TARGET = """SELECT d.id FROM dict d WHERE %s
            AND EXISTS(SELECT 1 FROM legacy_gloss lg
                       WHERE lg.word_id=d.id AND lg.published=0
                         AND lg.qual IN %s)""" % (NO_ZH, str(PUBLISHABLE))


def gates(con, before, n_word, n_row):
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("再没有「有中文可放却压着」的词",
         len(con.execute(TARGET).fetchall()), 0),
        # 期望值 ＝ 原有 − **本次收回的**（上一版误放的 low/豆包） ＋ 本次放行的。
        # 🔴 少了中间那一项，这条闸在"修一个自己造的错"的那一轮必然红，
        #    而它红得毫无信息量 —— 闸的算术必须把每一个写动作都算进去。
        ("出版行数正好多了这么多",
         q("SELECT COUNT(*) FROM legacy_gloss WHERE published=1"),
         before["pub"] - before["revert"] + n_row),
        ("🔴 总行数没变（改标志不删行）",
         q("SELECT COUNT(*) FROM legacy_gloss"), before["tot"]),
        # 🔴 负控①：已经有中文的词，一个都不许被放行
        ("🔴 负控 有中文的词没被顺手放行",
         q("""SELECT COUNT(*) FROM legacy_gloss lg JOIN dict d ON d.id=lg.word_id
              WHERE lg.published=1 AND EXISTS(SELECT 1 FROM sense s
                JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh'
                WHERE s.word_id=d.id)"""), before["pub_with_zh"]),
        # 🔴 负控②：连 ECDICT 都没有的那 514 个，本来就救不了，数不许变
        ("🔴 负控 真·无处可救的仍然是空的",
         q("""SELECT COUNT(*) FROM dict d WHERE %s
              AND NOT EXISTS(SELECT 1 FROM legacy_gloss lg WHERE lg.word_id=d.id)"""
           % NO_ZH), before["hopeless"]),
        # 🔴 负控④（第一版漏掉的那条）：放出去的**只能**是这三档
        ("🔴 负控 没放出 low／豆包写的",
         q("""SELECT COUNT(*) FROM legacy_gloss lg JOIN dict d ON d.id=lg.word_id
              WHERE lg.published=1 AND lg.qual NOT IN %s AND %s"""
           % (str(PUBLISHABLE), NO_ZH)), 0),
        ("🔴 负控 oneself 现在有中文了",
         q("""SELECT COUNT(*) FROM legacy_gloss lg JOIN dict d ON d.id=lg.word_id
              WHERE d.word='oneself' AND lg.published=1"""), 1),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-34s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = con.execute
    ids = [i for (i,) in q(TARGET)]
    n_row, = q("SELECT COUNT(*) FROM legacy_gloss WHERE published=0 AND word_id IN "
               "(%s)" % ",".join("?" * len(ids)), ids).fetchone() if ids else (0,)
    before = {
        "tot": q("SELECT COUNT(*) FROM legacy_gloss").fetchone()[0],
        "pub": q("SELECT COUNT(*) FROM legacy_gloss WHERE published=1").fetchone()[0],
        "pub_with_zh": q(
            """SELECT COUNT(*) FROM legacy_gloss lg JOIN dict d ON d.id=lg.word_id
               WHERE lg.published=1 AND EXISTS(SELECT 1 FROM sense s
                 JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh'
                 WHERE s.word_id=d.id)""").fetchone()[0],
        "revert": q("""SELECT COUNT(*) FROM legacy_gloss lg JOIN dict d ON d.id=lg.word_id
              WHERE lg.published=1 AND lg.qual NOT IN %s AND %s"""
                    % (str(PUBLISHABLE), NO_ZH)).fetchone()[0],
        "hopeless": q("""SELECT COUNT(*) FROM dict d WHERE %s
              AND NOT EXISTS(SELECT 1 FROM legacy_gloss lg WHERE lg.word_id=d.id)"""
                      % NO_ZH).fetchone()[0],
    }
    print("═══ 放行 ECDICT 人工中文（v3 侧一条中文都没有的词）═══")
    print("   词形 %s ／ 释义行 %s" % (format(len(ids), ","), format(n_row, ",")))
    print("   ⚠️ 真·无处可救（连 ECDICT 也没有）%s —— **留空不造**"
          % format(before["hopeless"], ","))
    print("\n   频次最高的几个：")
    for w, fr, g in q(
            "SELECT d.word, d.freq_rank, lg.text FROM dict d "
            "JOIN legacy_gloss lg ON lg.word_id=d.id WHERE d.id IN (%s) "
            "AND d.freq_rank IS NOT NULL ORDER BY d.freq_rank LIMIT 5"
            % ",".join("?" * len(ids)), ids):
        print("      %-16s #%-6s %s" % (w, fr, (g or "").split("\n")[0][:52]))
    con.close()
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    # `expect` 是增量：本次放行的行数（`legacy_gloss` 总行数不变，只改标志位，
    #  所以 `#legacy_gloss` 增量为 0 —— 不变量快照数的是行数不是标志）
    with dbtool.session("keep-v3-publish-legacy-no-zh", expect={}) as s:
        # 先把上一版误放的收回来（`low`/豆包三档），再按新判据放行
        s.execute("""UPDATE legacy_gloss SET published=0
                     WHERE published=1 AND qual NOT IN %s
                       AND word_id IN (SELECT d.id FROM dict d WHERE %s)"""
                  % (str(PUBLISHABLE), NO_ZH))
        s.executemany("UPDATE legacy_gloss SET published=1 "
                      "WHERE word_id=? AND published=0 AND qual IN %s"
                      % str(PUBLISHABLE), [(i,) for i in ids])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, before, len(ids), n_row)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
