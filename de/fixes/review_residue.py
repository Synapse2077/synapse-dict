#!/usr/bin/env python3
"""收尾单 C38：外审残单一次清（de，2026-09-05）。

外审那两份材料里，除 C29 / C36 / C37 之外还剩九条。逐条回源之后：
**四条是我们的错（本脚本修），五条不是**。不是的那五条也写在这里 ——
`[[record-the-negative-decision]]`：「查过、判定不该改」和「改了」一样要留痕，
否则下一轮重新查一遍。

═══ 本脚本修的四族 ═══
① **中文释义是把德语版的「小标题」当定义翻译了**（7 条）
   德语版用「小标题 + 子义项」结构，kaikki 把它拍平成并列的 `senses[]`：
       son  [0] umgangssprachlich:      ← 小标题
            [1] auf eine … Eigenschaft  ← 真义项
   `Aibi` 的义项 #129224 中文写着「巴西（南里奥格兰德州）：」—— 那不是释义，是个地区标签。
   🔴 **判据按含义写：中文释义永远不会以冒号结尾。** 不用「德语原文以冒号结尾」——
     那条量出 49 条，其中大多是 C29 给**已有正确义项**多挂的一条德语原文，
     那些义项的中文（`brauchen 需要，要`）完全正确。**同一个形式特征，两种完全不同的东西。**
   ⚠️ 七条所在的词**每个都还剩别的义项**（逐条查过），删掉不会把词清空。

② **义项的德语原文是 wikitext 残渣**（20 条）
   `==== Worttrennung ====\\n:russ` —— 小标题连同换行整段漏进了释义栏。
   这 20 条的义项**中英文全空** ⇒ 页面上就是一条空行。连义项一起删。

③ **使役派生被当成变形**（5 条，全在高流量动词上）
   `stellen ← stehen 弱变化`、`legen ← liegen`、`setzen ← sitzen`、`erlegen ← erliegen`。
   英文版 tags 是 `[causative, form-of, transitive, weak]` —— kaikki 打了 `form-of`，
   我们就当成了变形。但 `stellen` **不是 `stehen` 的一个形式**，是它的使役派生词。
   ⇒ `kind='derivation'`（展示层 C13 之后构词与变形分区渲染），标签「使役派生」。

④ **关系的目标是德语版的词类小标题**（33 条）
   `stehen` 的「派生」栏印着 `Adjektive` / `Substantive` / `Verben` —— 那是源页面上的
   分组标题，不是派生词。`hidden=1`（同 C37：留行留证据，不展示）。

⑤ 外加一条独立的用词错：`machen` #7730「（与否定、**量词**连用）」——
   `nichts`/`viel` 是不定代词，不是中文语法里的量词（个/张/条）。
   ⚠️ 全库 7 条中文含「量词」，**只有这一条用错**，其余 6 条是 `Quantor`（逻辑量词）
   `Zähleinheitswort`（量词），用对了。判据不能写成「含量词就改」。

═══ 查过、**判定不改**的五条 ═══
· `dat` 音标 `/dɑ̃t/` —— **源头德语版自己就是这么写的**（同一页荷兰语条目是 `[dɑt]`，
  几乎肯定是上游笔误）。2 行。不拿我的判断覆盖源头。
· 全库 3,507 条带鼻化符的音标 —— 抽 24 条**全是德语里真有的法语借词**
  （Chanson/Branche/Pension/Fonds/Département/Saison）。德语确实鼻化。
  ⚠️ 我差点拿「有鼻化符」这个形式代理圈掉 3,507 条正确数据。
· `Haubenlerche` 第 2 义「某修会的女性成员」—— **源头就有这一义**（戴头巾的修女的谑称）。
· `machen`「来吧，走吧」—— 英文版原文就是 `come on, let's go`，我们的中文是忠实翻译。
  要改得回英文版去争，不是我们这边的错。
· `sich befinden` / `zu verkaufen` 标「不定式」—— 那**就是**反身动词与 zu 不定式的形式，对的。

用法：
    python3 fixes/review_residue.py          # 试算
    python3 fixes/review_residue.py --write
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths                                                    # noqa: E402

f = lambda n: format(n, ",")

# ① 中文释义以冒号结尾 = 把小标题当定义了。**判据只许这一份**，闸 import 它。
HEADER_ZH = ("SELECT g.sense_id FROM sense_gloss g WHERE g.lang='zh' "
             "AND (TRIM(g.text) LIKE '%：' OR TRIM(g.text) LIKE '%:')")
# ② 德语原文是 wikitext 残渣，且该义项没有任何中英文
WIKI_RESIDUE = (
    "SELECT g.sense_id FROM sense_gloss g WHERE g.lang='de' AND g.text LIKE '%====%' "
    "AND NOT EXISTS(SELECT 1 FROM sense_gloss z WHERE z.sense_id=g.sense_id "
    "               AND z.lang IN ('zh','en'))")
# ④ 德语版的词类小标题，被当成了关系目标
SECTION_TARGETS = ("Adjektive", "Substantive", "Verben", "Adverbien",
                   "Wortbildungen", "Konversionen", "Redewendungen",
                   "Sprichwörter", "Charakteristische Wortkombinationen")


def dead_senses(con):
    """→ (该删的义项 id, 被护栏挡下的)。

    🔴 **护栏只给 ① 用，不给 ② 用。** 第一版我给两族都套了「删完该词还得剩别的义项」，
       结果挡下 15 条 —— 而那 15 条**全是** `==== Worttrennung ====` 这种纯残渣
       （`russ`/`russend`/`Strassendirne`…，中英文全空），页面上正把它当释义印着。
       ⇒ 护栏比它要保护的东西更宽：它想护住「这个词仅有的内容」，
         而**残渣不是内容**，删掉是净收益（词仍在 `dict` 里，词形还原那一栏照常工作）。
       ① 那一族不同：中文是把小标题当定义翻的，但同一条义项**可能**另有真内容，
         所以那边保留护栏。
    """
    hdr = {i for (i,) in con.execute(HEADER_ZH)}
    wiki = {i for (i,) in con.execute(WIKI_RESIDUE)}      # 零信息，无条件删
    drop, blocked = list(wiki), []
    for sid in sorted(hdr - wiki):
        r = con.execute("SELECT word_id FROM sense WHERE id=?", (sid,)).fetchone()
        if not r:
            continue
        rest = con.execute("SELECT COUNT(*) FROM sense WHERE word_id=? AND id NOT IN (%s)"
                           % ",".join(str(x) for x in hdr | wiki), (r[0],)).fetchone()[0]
        (drop if rest > 0 else blocked).append(sid)
    return sorted(drop), blocked


def causative_rows(con):
    """→ 该改成构词的变形行。判据 = 源头 tags 里有 `causative`。"""
    out = []
    for iid, t in con.execute("SELECT id, tags FROM inflection WHERE tags LIKE '%causative%'"):
        try:
            if "causative" in json.loads(t):
                out.append(iid)
        except Exception:
            pass
    return out


def section_rels(con):
    qs = ",".join("?" * len(SECTION_TARGETS))
    return [i for (i,) in con.execute(
        "SELECT id FROM sense_relation WHERE target IN (%s) AND hidden=0" % qs,
        SECTION_TARGETS)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    drop, kept = dead_senses(con)
    caus = causative_rows(con)
    rels = section_rels(con)
    # ⚠️ `sense_gloss` 没有 `id` 列（主键是 `(sense_id, lang, kind, seq)`）—— 按义项号改
    quant = [i for (i,) in con.execute(
        "SELECT g.sense_id FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
        "JOIN dict d ON d.id=s.word_id WHERE g.lang='zh' AND d.word='machen' "
        "AND g.text LIKE '%量词%'")]

    print("■ ①② 该删的义项 %s（跳过会把词清空的 %s）" % (f(len(drop)), f(len(kept))))
    for sid, w, zh, de in con.execute(
            "SELECT s.id, d.word,"
            " (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' LIMIT 1),"
            " (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='de' LIMIT 1)"
            " FROM sense s JOIN dict d ON d.id=s.word_id WHERE s.id IN (%s) LIMIT 12"
            % ",".join(str(x) for x in drop or [0])):
        print("     #%-7s %-16s %-24s | %s"
              % (sid, w[:16], (zh or "-")[:24], (de or "-").replace("\n", "⏎")[:40]))
    print("■ ③ 使役派生被当成变形 %s" % f(len(caus)))
    for iid, w, b, lab in con.execute(
            "SELECT i.id,(SELECT word FROM dict WHERE id=i.word_id),i.base,i.label_zh "
            "FROM inflection i WHERE i.id IN (%s)" % ",".join(str(x) for x in caus or [0])):
        print("     %-14s ← %-26s %s" % (w[:14], (b or "")[:26], lab))
    print("■ ④ 关系目标是词类小标题 %s（改 hidden=1）" % f(len(rels)))
    print("■ ⑤ machen 的「量词」用词错 %s 条" % f(len(quant)))
    con.close()

    if not a.write:
        print("\n(未加 --write，未写库)")
        return 0

    import dbtool
    # 义项一删，挂在它下面的证据/释义/标签/关系/例句/搭配都要跟着走
    ids = ",".join(str(x) for x in drop) or "0"
    with dbtool.session("keep-v3-c38-review-residue",
                        expect={"#sense": -len(drop), "#sense_gloss": None,
                                "#sense_src": None, "#sense_tag": None,
                                "#sense_relation": None, "#example": None,
                                "#example_gloss": None, "#collocation": None,
                                "#collocation_gloss": None}) as s:
        s.execute("DELETE FROM example_gloss WHERE example_id IN "
                  "(SELECT id FROM example WHERE sense_id IN (%s))" % ids)
        s.execute("DELETE FROM collocation_gloss WHERE collocation_id IN "
                  "(SELECT id FROM collocation WHERE sense_id IN (%s))" % ids)
        s.execute("DELETE FROM example WHERE sense_id IN (%s)" % ids)
        s.execute("DELETE FROM collocation WHERE sense_id IN (%s)" % ids)
        s.execute("DELETE FROM sense_relation WHERE sense_id IN (%s)" % ids)
        s.execute("DELETE FROM sense_tag WHERE sense_id IN (%s)" % ids)
        s.execute("DELETE FROM sense_gloss WHERE sense_id IN (%s)" % ids)
        s.execute("UPDATE sense_src SET sense_id=NULL WHERE sense_id IN (%s)" % ids)
        s.execute("DELETE FROM sense WHERE id IN (%s)" % ids)
        s.executemany("UPDATE inflection SET kind='derivation', label_zh='使役派生' WHERE id=?",
                      [(i,) for i in caus])
        s.executemany("UPDATE sense_relation SET hidden=1 WHERE id=?", [(i,) for i in rels])
        s.executemany(
            "UPDATE sense_gloss SET text='（与否定词、不定代词 nichts／viel 等连用）重要，有意义' "
            "WHERE sense_id=? AND lang='zh'", [(i,) for i in quant])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, a=(): con.execute(x, a).fetchone()[0]
    print("\n═══ 闸：五族各查一次（每条都是「真做了才成立」的数据事实）═══")
    checks = [
        ("🔴 ① 中文释义仍以冒号结尾", q("SELECT COUNT(*) FROM (%s)" % HEADER_ZH), 0),
        ("🔴 ② wikitext 残渣且无中英文", q("SELECT COUNT(*) FROM (%s)" % WIKI_RESIDUE), 0),
        ("🔴 ③ causative 仍算变形",
         q("SELECT COUNT(*) FROM inflection WHERE tags LIKE '%causative%' "
           "AND kind<>'derivation'"), 0),
        ("🔴 ④ 词类小标题仍可见",
         q("SELECT COUNT(*) FROM sense_relation WHERE target IN (%s) AND hidden=0"
           % ",".join("?" * len(SECTION_TARGETS)), SECTION_TARGETS), 0),
        ("🔴 ⑤ machen 仍写「量词」",
         q("SELECT COUNT(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
           "JOIN dict d ON d.id=s.word_id WHERE g.lang='zh' AND d.word='machen' "
           "AND g.text LIKE '%量词%'"), 0),
        ("🔴 删义项留下的孤儿释义",
         q("SELECT COUNT(*) FROM sense_gloss g LEFT JOIN sense s ON s.id=g.sense_id "
           "WHERE s.id IS NULL"), 0),
        ("🔴 删义项留下的孤儿例句",
         q("SELECT COUNT(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id "
           "WHERE e.sense_id IS NOT NULL AND s.id IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-38s %8s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    con.close()
    print("\n%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
