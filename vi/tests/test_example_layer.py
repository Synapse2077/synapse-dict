#!/usr/bin/env python3
"""**例句层闸（vi）** —— `example` / `example_gloss` 对不对。2026-10-01。

判据 import 自 `stage6_sources.py`，一条都不重写。

═══ ⭐ X5 是**读者口径**的那一条 ═══
「库里有 7.8 万条例句」说明不了读者打开一个词能不能看见例句。
X5 量的是**有多少词形至少有一条可出版例句**（实测 36.76%），下限锁住当前水平。

═══ 🔴 X7：vi 版的 `translation` **不是译文**，这条守住它别被收回来 ═══
vi 版 709 条 `translation` 里一条真译文都没有（214 条整串是 `.`，290 条是
`(tục ngữ)` 这种出处）。它们该进 `example.ref`。
⇒ X7 查**出版层没有 vi 语的例句译文**。
   ⚠️ 这不是说「越南语不能当译文语种」—— 而是说源头目前没有一条越南语译文，
   有一条出现就意味着那个判据被改宽了。
   🔴 什么会推翻：源头真的开始给越南语释义式译文（那时 X7 要换成内容判据）。

═══ 🔴 X8：**出版层里不许有「译文挂在隐藏例句上」** ═══
隐藏的例句不出版，给它配译文就是白译 —— 而阶段 6e 若去买翻译，
按「有没有译文」挑行会把钱花在不出版的行上（ko 的 6d 正是按这个口径挑的）。

🔴🔴 **2026-10-03：我差点把这条闸调松去迁就我自己造成的矛盾。**
   6e 开跑前的清洗隐藏了 188 条例句，其中 67 条带着源头白送的译文 ⇒ X8 判红。
   我的第一反应是**收窄判据**（只查付费来源）＋新建一条基线把那 67 条锁住。
   写完才想起去问收割器：`build_example_layer.gloss_rows()` 的条件是 `r[4] is None`
   —— **隐藏的例句根本不产出译文行**，重建一次库那 67 行自己就没了。
   ⇒ 真正的问题不是判据太严，是**库里有收割器不会产出的行**。删掉它们，这条闸回到原样。
   ⭐ `[[gate-registers-status-quo-as-spec]]` 的反面用法：
     **红变绿之前先问「是不是把闸对准了别的东西」** —— 这次答案是「不是闸的问题」。
   ⭐ 而逼我去问的那一下是：收割器跑出来的 `want_g` 与库里的 `have_g` 差 69 行。
     **两个独立产物对不上，比任何一侧自己的断言都有用。**

用法：
    python3 vi/tests/test_example_layer.py
    python3 vi/tests/test_example_layer.py --mutate
"""
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                                      # noqa: E402
import stage6_sources as S6                                       # noqa: E402

# 🔴 下限按 2026-10-01 实测写死（ACCEPT 锁数字不锁名字）。
#    ⚠️ 距现状 ≤3 个点 —— 账的闸 V10 会查这件事（松弛会把退化藏起来）
COVER_FLOOR = 35.0          # 实测 36.76%（24,506 / 66,657 个词形有可出版例句）
NOM_HIDDEN_FLOOR = 1000     # 实测隐藏 1,243 条喃字正文
# 十二份切片都该有例句落进来。**写成数字而不是 `>0`** ——
# `[[expectation-must-be-declared]]`：期望值要独立声明，不能从现状推
SRC_COUNT = 12


def _cover(c):
    n = c.execute("SELECT COUNT(DISTINCT word_id) FROM example WHERE hidden=0").fetchone()[0]
    t = c.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    return 100.0 * n / max(t, 1)


def _dup_in_cell(c):
    """W24：**读者口径**的重复例句残留。→ 多余的行数

    判据 `S6.example_dup_key` import 自收割器那一侧，**这里不重写归一** ——
    拿 SQL 的 `LOWER(TRIM(...))` 近似它一定会漂开（关系闸 R19 第一版就这么栽的）。
    """
    seen, again = set(), 0
    for w, sid, pub in c.execute(
            "SELECT word_id, sense_id, text_pub FROM example WHERE hidden=0"):
        k = (w, sid, S6.example_dup_key(pub))
        if k in seen:
            again += 1
        seen.add(k)
    return again


CHECKS = [
    ("X1", "example 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM example").fetchone()[0] > 0, True),
    ("X2", "文本非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM example WHERE TRIM(text)=''").fetchone()[0], 0),
    ("X3", "每条都挂得上 dict", lambda c: c.execute(
        "SELECT COUNT(*) FROM example e LEFT JOIN dict d ON d.id=e.word_id "
        "WHERE d.id IS NULL").fetchone()[0], 0),
    ("X4", "sense_id 要么空要么真指向一条 sense", lambda c: c.execute(
        "SELECT COUNT(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id "
        "WHERE e.sense_id IS NOT NULL AND s.id IS NULL").fetchone()[0], 0),
    ("X5", "⭐ 读者口径：有可出版例句的词形占比不低于下限",
     lambda c: _cover(c) >= COVER_FLOOR, True),
    ("X6", "src_ref 唯一", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT src_ref FROM example GROUP BY src_ref "
        "HAVING COUNT(*)>1)").fetchone()[0], 0),
    # 🔴 vi 版的 `translation` 不是译文 —— 收回来的话这个数会从 0 变成七百
    ("X7", "🔴 出版层没有 vi 语的例句译文（那个字段装的是出处）", lambda c: c.execute(
        "SELECT COUNT(*) FROM example_gloss WHERE lang='vi'").fetchone()[0], 0),
    # 🔴 判据与收割器的 `gloss_rows()` 是同一条规矩的两面：
    #    收割器不给隐藏的例句产译文行，这条闸查库里有没有混进来。见文件头 X8 那段。
    ("X8", "🔴 隐藏的例句不带译文（白译 ＝ 白花钱）", lambda c: c.execute(
        "SELECT COUNT(*) FROM example_gloss g JOIN example e ON e.id=g.example_id "
        "WHERE e.hidden=1").fetchone()[0], 0),
    ("X9", "译文只有三语（`[[gloss-three-languages]]`）", lambda c: c.execute(
        "SELECT COUNT(*) FROM example_gloss WHERE lang NOT IN ('zh','en','vi')"
    ).fetchone()[0], 0),
    # 🔴 喃字正文判据真的在起作用 —— 掉到量级以下说明它被改坏或汉字层空了
    ("X10", "🔴 喃字正文判据在起作用（隐藏的量级）", lambda c: c.execute(
        "SELECT COUNT(*) FROM example WHERE hidden_why=?",
        (S6.HIDDEN_NO_LATIN,)).fetchone()[0] >= NOM_HIDDEN_FLOOR, True),
    ("X11", "隐藏的都写了为什么", lambda c: c.execute(
        "SELECT COUNT(*) FROM example WHERE hidden=1 AND "
        "(hidden_why IS NULL OR TRIM(hidden_why)='')").fetchone()[0], 0),
    # 🔴 **跨版收割真的收了十二版**。只查「表非空」的话，少收十一版也全绿
    ("X12", "🔴 十二份切片都有例句落进来", lambda c: c.execute(
        "SELECT COUNT(DISTINCT src) FROM example").fetchone()[0], SRC_COUNT),
    ("X13", "hidden_why 都在值域里", lambda c: c.execute(
        "SELECT COUNT(*) FROM example WHERE hidden_why IS NOT NULL AND hidden_why NOT IN "
        "(%s)" % ",".join("'%s'" % w for w in sorted(
            # 🔴 2026-10-03 加 `HIDDEN_KO_LABEL`：ko 版 45 条韩语标签行
            #    （`같은 말 : yêu thương` ＝「同义词」，是**关系数据**不是例句）。
            #    ⭐ **这一条当场判红了**，而它正是为此存在的 ——
            #      新值域不登记就不许落库（与 `classify()` 的 unknown-value 同一条规矩）。
            # 🔴 2026-10-03 再加三个：阶段 6e 开跑前的清洗（`fix_example_defects.py`）。
            #    ⭐ **这一条第二次当场判红**，第一次是 `HIDDEN_KO_LABEL`。
            #      同一道闸在两次不同的改动上都尽了责 ⇒ 它不是「如实登记现状」。
            (S6.HIDDEN_NO_LATIN, S6.HIDDEN_SAME_AS_WORD,
             S6.HIDDEN_TOO_SHORT, S6.HIDDEN_SRC_CHINESE,
             S6.HIDDEN_KO_LABEL, S6.HIDDEN_META_NOT_EXAMPLE,
             S6.HIDDEN_CITATION_ONLY, S6.HIDDEN_NO_VIETNAMESE,
             # 🔴 2026-10-05 加 `HIDDEN_DUP_IN_CELL`（W24，429 条同格跨版重复）。
             #    ⭐ **这一条第三次当场判红**（前两次：`HIDDEN_KO_LABEL`、6e 的三个值）。
             #      三次都是「我往这一列写了新值而忘了登记」⇒ 它确实不是在
             #      「如实登记现状」，它每次都先于我想起来。
             # 🔴 2026-10-06 加 `HIDDEN_JS_RESIDUE`（W20，fr 版 2 条 JS 实参残渣）。
             #    ⭐ **这一条第四次当场判红。** 四次都是同一个形状：
             #      我往这一列写了新值、而登记是另一个动作。
             #      ⇒ 这就是「值域检查」存在的全部理由：它不问「现状对不对」，
             #        它问「你有没有在往一列里塞没人认识的东西」。
             S6.HIDDEN_DUP_IN_CELL, S6.HIDDEN_JS_RESIDUE)))).fetchone()[0], 0),
    # ── 🔴🔴 **X15（W24）：读者口径 —— 同一格里不许有重复例句。** ──
    # ⚠️ 判据 `S6.example_dup_key` **import，不在 SQL 里手写归一**：
    #    它要做压空白＋去首尾标点＋小写三件事，SQL 里拿 `LOWER(TRIM(...))` 近似
    #    一定会与收割器漂开（关系闸 R19 的第一版就是这么栽的）。
    # 🔴 **分组键必须带 `sense_id`** —— 这就是读者口径：展示层把带义项的例句印在
    #    各自义项下、`sense_id IS NULL` 的印在末尾「例句」区。
    #    不带 `sense_id` 分组会得到 1,569 组（大 3.8 倍），而那不是读者看见的东西。
    ("X15", "🔴 W24：同一格（同义项／同「例句」区）里没有重复例句", _dup_in_cell, 0),
    # 🔴 出版层的例句**不许整条就是该词本身**（零信息，判据的落点）
    ("X14", "🔴 出版的例句不是该词本身", lambda c: c.execute(
        "SELECT COUNT(*) FROM example e JOIN dict d ON d.id=e.word_id "
        "WHERE e.hidden=0 AND LOWER(TRIM(e.text, ' .!?'))=LOWER(d.word)").fetchone()[0], 0),
]
ROSTER = ("X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8", "X9",
          "X10", "X11", "X12", "X13", "X14", "X15")
UNMUTABLE = {
    "X1": "要变异就得清空整张表；它拦的是「表空了而所有 0 值检查全绿」。",
    "X6": "DDL 上有 `UNIQUE(src_ref)`，注不进去（与骨架闸 S2 同一情形，恒绿已登记）。",
}


def run(con):
    red = []
    have = tuple(c[0] for c in CHECKS)
    if set(have) != set(ROSTER):
        red.append(("X0", "检查表与花名册对不上：少了 %s，多了 %s"
                    % (sorted(set(ROSTER) - set(have)) or "无",
                       sorted(set(have) - set(ROSTER)) or "无")))
    for cid, name, fn, want in CHECKS:
        try:
            got = fn(con)
        except sqlite3.Error as e:
            red.append((cid, "%s —— 查不了：%s" % (name, e)))
            continue
        if got != want:
            red.append((cid, "%s：得到 %s，期望 %s" % (name, got, want)))
    return red


MUTATIONS = [
    ("X2", "把一条例句文本清空",
     "UPDATE example SET text='' WHERE id=(SELECT MIN(id) FROM example)", {}),
    ("X3", "让一条例句指向不存在的 dict",
     "UPDATE example SET word_id=99999999 WHERE id=(SELECT MIN(id) FROM example)", {}),
    ("X4", "让 sense_id 指向不存在的 sense",
     "UPDATE example SET sense_id=99999999 WHERE id=(SELECT MIN(id) FROM example)", {}),
    ("X5", "⭐ 把九成例句隐藏掉（模拟判据写太宽）",
     "UPDATE example SET hidden=1, hidden_why='nom-script-quotation' WHERE id % 10 <> 0",
     {"X8": "被隐藏的行里有带译文的"}),
    ("X7", "🔴 把 vi 版那批「出处」当译文收回来",
     "INSERT INTO example_gloss(example_id,lang,text,src) "
     "SELECT MIN(id),'vi','(tục ngữ)','vi-edition' FROM example WHERE hidden=0", {}),
    ("X8", "🔴 给一条隐藏的例句配译文",
     "INSERT INTO example_gloss(example_id,lang,text,src) "
     "SELECT MIN(id),'zh','白译的','en-edition' FROM example WHERE hidden=1", {}),
    ("X9", "写一条第四种语言的译文",
     "UPDATE example_gloss SET lang='fr' WHERE id=(SELECT MIN(id) FROM example_gloss)", {}),
    ("X10", "🔴 把喃字正文那批放出来（判据被改坏的样子）",
     "UPDATE example SET hidden=0, hidden_why=NULL WHERE hidden_why='nom-script-quotation'",
     {"X14": "放出来的那批里有「整条就是该词本身」的",
      # 🔴 2026-10-05 新出现的连带，**而它是真的**：那 1,210 条喃字正文一放出来，
      #    其中一批与别版同格的例句撞上 ⇒ X15 当场报残留。
      #    ⭐ **连带声明要跟着检查表一起长**（这是本仓库第四次记这句话）。
      "X15": "放出来的那批里有与别版同格重复的"}),
    # ⚠️ 连带 X8 是**声明过的**：`MIN(id)` 那条例句正好带着英文译文，
    #    一隐藏就触发「隐藏的例句不带译文」。声明它，不去把 X8 放宽 ——
    #    放宽会让这套闸对真正的连带损害永久失明。
    ("X11", "隐藏一条而不写为什么",
     "UPDATE example SET hidden=1, hidden_why=NULL WHERE id=(SELECT MIN(id) FROM example)",
     {"X8": "MIN(id) 那条带着英文译文，隐藏它就触发 X8"}),
    ("X12", "🔴 把一整版的例句删掉（跨版收割缩水）",
     "DELETE FROM example WHERE src='pl-edition'", {}),
    ("X13", "写一个值域外的 hidden_why",
     "UPDATE example SET hidden=1, hidden_why='随手写的' "
     "WHERE id=(SELECT MIN(id) FROM example)",
     {"X8": "同 X11：MIN(id) 那条带着英文译文"}),
    # 🔴 X15（W24）：把一条同格重复的例句放回出版层 ⇒ 页面上那一句又印两遍。
    #    ⚠️ **`hidden_why` 也要一起清掉**，否则 X11（隐藏的都写了为什么）不受影响
    #      但 X13（值域）会去看一个 hidden=0 的行 —— 两种写法都能让 X15 响，
    #      而「放回出版层」才是这个缺陷真正的样子（判据被关掉时就是这样）。
    ("X15", "🔴 把一条同格重复的例句放回出版层（W24 的判据被关掉的样子）",
     "UPDATE example SET hidden=0, hidden_why=NULL WHERE id="
     "(SELECT MIN(id) FROM example WHERE hidden_why='duplicate-in-same-cell')", {}),
    ("X14", "🔴 往出版层塞一条「例句就是该词本身」",
     # ⚠️ `src` 必须用一个**已有**的值 —— 写 `'t'` 会顺带让 X12（十二份切片）
     #    变成十三份而连带报红，那样这条变异就同时注入了两个缺陷
     "INSERT INTO example(word_id,text,hidden,src,src_ref) "
     "SELECT id, word, 0, 'en-edition', 'mut:x14' FROM dict LIMIT 1", {}),
]


def mutate():
    con = sqlite3.connect(paths.DB)
    base = run(con)
    if base:
        print("🔴 基线就不绿：")
        for c, w in base:
            print("   %s %s" % (c, w))
        return False
    ok, covered = True, set()
    print("═══ 变异验证：%d 条注入 ═══" % len(MUTATIONS))
    for cid, desc, sql, also in MUTATIONS:
        con.execute("SAVEPOINT m")
        changed = 0
        for stmt in sql.split(";"):
            if stmt.strip():
                con.execute(stmt)
                changed += con.execute("SELECT changes()").fetchone()[0]
        hit = set(c for c, _ in run(con))
        undeclared = hit - {cid} - set(also)
        good = changed > 0 and cid in hit and not undeclared
        ok &= good
        covered.add(cid)
        note = ""
        if changed == 0:
            note = "  🔴🔴 **什么都没改** —— 变异自己坏了"
        elif cid not in hit:
            note = "  🔴 没逮到"
        elif undeclared:
            note = "  🔴 **未声明的连带** %s" % sorted(undeclared)
        elif also:
            note = "  （连带 %s，已声明）" % "、".join(sorted(also))
        print("   %s %-5s %s%s" % ("✅" if good else "🔴", cid, desc, note))
        con.execute("ROLLBACK TO m")
        con.execute("RELEASE m")
    con.rollback()
    print("\n── 没有变异覆盖的（必须逐条说明）")
    for c in [x for x in ROSTER if x not in covered]:
        why = UNMUTABLE.get(c)
        if why:
            print("   ⚠️ %-5s %s" % (c, why))
        else:
            ok = False
            print("   🔴 %-5s **没有变异、也没写为什么**" % c)
    con.close()
    return ok


def main():
    if "--mutate" in sys.argv:
        raise SystemExit(0 if mutate() else 1)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = run(con)
        print("■ vi 例句层闸：%d 条检查" % (len(CHECKS) + 1))
        for cid, why in red:
            print("   🔴 %-5s %s" % (cid, why))
        if not red:
            print("   ✅ 全绿")
        q = lambda x: con.execute(x).fetchone()[0]                 # noqa: E731
        print("   ── 读者口径例句覆盖 **%.2f%%**（下限 %.1f%%）" % (_cover(con), COVER_FLOOR))
        print("   ── 例句 %s（隐藏 %s）／ 译文 %s ／ 出处 %s ／ 挂到义项 %s"
              % (format(q("SELECT COUNT(*) FROM example"), ","),
                 format(q("SELECT COUNT(*) FROM example WHERE hidden=1"), ","),
                 format(q("SELECT COUNT(*) FROM example_gloss"), ","),
                 format(q("SELECT COUNT(*) FROM example WHERE ref IS NOT NULL"), ","),
                 format(q("SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL"), ",")))
        for lang in ("zh", "en"):
            n = q("SELECT COUNT(DISTINCT e.word_id) FROM example e JOIN example_gloss g "
                  "ON g.example_id=e.id WHERE e.hidden=0 AND g.lang='%s'" % lang)
            print("      译文 %s 覆盖词形 %6s（%.2f%%）"
                  % (lang, format(n, ","), 100.0 * n / q("SELECT COUNT(*) FROM dict")))
    finally:
        con.close()
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
