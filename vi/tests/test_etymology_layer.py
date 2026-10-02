#!/usr/bin/env python3
"""**词源层闸（vi）** —— `etymology` ／ `entry.etym_type`。2026-10-02。

判据 import 自 `etym_sources.py`，一条都不重写。

═══ 🔴🔴 Y5 是这道闸最该有的那条：**裸表记一段都不许在词源层里** ═══
zh 版 26,230 段「词源」里 **21,239 段整段只是 `thư viện［書院］`** —— 那是汉字表记，
归阶段 2。把它们当词源收 ⇒ 读者在「词源」栏看见一串汉字，而页面上方的
「汉字表记」栏印着同一串。这正是 W2 在释义上治的那个病，换了个栏目。
🔴 Y5 **不查「有多少段被跳过了」而查「出版层里有没有」** —— 前者在判据被改宽时
   仍然为真（跳过的数只会涨），后者才是读者口径。

═══ 🔴 Y7：内嵌的 MediaWiki 魔术字 ═══
vi 版 5,390 段（它可出版段数的 **64.7%**）正文末尾带着 `__NOEDITSECTION__`。
⭐ 逮到它的不是形状检查而是 `dbtool.sample_check` 的抽样反验 ——
   形状检查问「这段该不该收」，而这段**该收，只是脏**。
⇒ Y7 查出版层**一个魔术字都没有**。判据是 `__[A-Z]+__`，不是只认 `__NOEDITSECTION__`
  （只认一个名字 ⇒ 源头换成 `__NOTOC__` 就静默穿过去）。

═══ ⚠️ Y9/Y10：`etym_type` 的两处值域改动必须真的在起作用 ═══
`compound` 是阶段 7 新加的值（9,361 条只有构词模板）；`unknown` **有意不用**
（源头没给信号就是 NULL）。两条都要有闸，否则「加了值域」和「值域是空的」长得一样。
"""
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import etym_sources as ES                                         # noqa: E402
import paths                                                      # noqa: E402

# 🔴 下限按 2026-10-02 实测写死。⚠️ 距现状 ≤3 个点（账的闸 V10 查这件事）
COVER_FLOOR = 36.5          # 实测 38.99%（25,926 / 66,502 个词形有词源散文）
ZH_FLOOR = 3000             # 实测 zh 版给了 3,453 个词形的**中文**词源（白送的）
TYPE_FLOOR = 25000          # 实测 entry.etym_type 填了 25,747 行（只算 en 版建的 entry）
# 🔴 Y15 的下限第一版写的是 300，**而那个数来自错的度量** —— 643 是「源头里有多段的
#    *条目*数」，过了跳过判据（`__NOEDITSECTION__` 整段型被剥掉）之后真值是 **65**。
#    `[[measure-landing-not-source]]`：量落点不量源头。
MULTI_FLOOR = 40            # 实测 65 组 (词, 词源号, 版) 有多段
# ⚠️ Y17 是**看守上界**不是删除判据：形式上「像音标/录音数据」的段共 12 段（0.03%），
#    逐条读过 **≥9 段是真词源在引用历史注音**
#    （`Attested as sắc ſỡ [ʂakᴮ¹ ʂəː^(C2)] in the Dictionarium Annamiticum`）。
#    真渣只有 3 段（`cá` 的 `Âm thanh (Hà Nội): (tập tin)` 那一族）。
#    ⇒ 按模式删 ＝ 为了去 3 段删掉 9 段真词源（`[[criteria-narrower-than-you-think]]`）
#      ⇒ **不删，设一个上界盯住它别长**。欠账 W11。
PRON_LEAK_CEIL = 20
_TYPE_DOM = ",".join("'%s'" % v for v in ES.ETYM_TYPE_DOMAIN)


def _cover(c):
    n = c.execute("SELECT COUNT(DISTINCT word_id) FROM etymology").fetchone()[0]
    t = c.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    return 100.0 * n / max(t, 1)


def _bare(c):
    """🔴 判据 import，不在 SQL 里手写近似版（阶段 6 的 R19 刚栽过这一跤）。"""
    return sum(1 for w, t in c.execute(
        "SELECT d.word, e.text FROM etymology e JOIN dict d ON d.id=e.word_id")
        if ES.is_bare_han_spelling(w, t))


_PRON_LEAK = re.compile(r"\bIPA\b|^\s*Âm thanh\b|\(tập tin\)"
                        r"|\[[^\]]*[ˈˌː˦˥˧˨˩][^\]]*\]")


def _pron_leak(c):
    """→ True ＝ 没变多。**判的是上界**：现在 12 段，≥9 段是真词源在引用历史注音。"""
    n = sum(1 for (t,) in c.execute("SELECT text FROM etymology") if _PRON_LEAK.search(t))
    return n <= PRON_LEAK_CEIL


def _dirty(c):
    return sum(1 for (t,) in c.execute("SELECT text FROM etymology")
               if ES.clean_etym_text(t) != (t or "").strip())


CHECKS = [
    ("Y1", "etymology 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM etymology").fetchone()[0] > 0, True),
    ("Y2", "正文非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM etymology WHERE TRIM(text)=''").fetchone()[0], 0),
    ("Y3", "每条都挂得上 dict", lambda c: c.execute(
        "SELECT COUNT(*) FROM etymology e LEFT JOIN dict d ON d.id=e.word_id "
        "WHERE d.id IS NULL").fetchone()[0], 0),
    ("Y4", "entry_id 要么空要么真指向一条 entry", lambda c: c.execute(
        "SELECT COUNT(*) FROM etymology x LEFT JOIN entry e ON e.id=x.entry_id "
        "WHERE x.entry_id IS NOT NULL AND e.id IS NULL").fetchone()[0], 0),
    # 🔴🔴 读者口径：出版层里有没有裸表记，不是「跳过了多少段」
    ("Y5", "🔴🔴 出版的词源里没有一段是 `词形［漢字］` 裸表记（那是阶段 2 的料）",
     _bare, 0),
    ("Y6", "src_field 只有源头那两个字段名（漏一个丢 42%）", lambda c: c.execute(
        "SELECT COUNT(*) FROM etymology WHERE src_field NOT IN (%s)"
        % ",".join("'%s'" % k for k in ES.ETYM_KEYS)).fetchone()[0], 0),
    # 🔴 内嵌魔术字：判据是 `__[A-Z]+__`，不是只认 `__NOEDITSECTION__`
    ("Y7", "🔴 出版的词源里一个 MediaWiki 魔术字都没有", _dirty, 0),
    ("Y8", "⭐ 读者口径：有词源散文的词形占比不低于下限",
     lambda c: _cover(c) >= COVER_FLOOR, True),
    # ⭐ 中文词源是白送的 —— 掉下去意味着 zh 版那一支没收或判据把它判成垃圾了
    ("Y9", "⭐ 中文词源真的收进来了（zh 覆盖词形的量级）", lambda c: c.execute(
        "SELECT COUNT(DISTINCT word_id) FROM etymology WHERE src LIKE 'zh-%'"
    ).fetchone()[0] >= ZH_FLOOR, True),
    ("Y10", "etym_type 都在值域里", lambda c: c.execute(
        "SELECT COUNT(*) FROM entry WHERE etym_type IS NOT NULL AND etym_type NOT IN (%s)"
        % _TYPE_DOM).fetchone()[0], 0),
    ("Y11", "⭐ etym_type 真的填了（量级）", lambda c: c.execute(
        "SELECT COUNT(*) FROM entry WHERE etym_type IS NOT NULL"
    ).fetchone()[0] >= TYPE_FLOOR, True),
    # 🔴 `compound` 是阶段 7 新加的值 —— 没有它就说明构词那一支被当成 NULL 吞了
    ("Y12", "🔴 `compound` 这个新值真的有行（9,361 条只有构词模板）", lambda c: c.execute(
        "SELECT COUNT(*) FROM entry WHERE etym_type='compound'").fetchone()[0] > 5000, True),
    # 🔴 `unknown` **有意不用**：源头没给信号就是 NULL。留着没人写＝ B7 那种死条目
    ("Y13", "🔴 `unknown` 有意不用（源头没给信号就是 NULL）", lambda c: c.execute(
        "SELECT COUNT(*) FROM entry WHERE etym_type='unknown'").fetchone()[0], 0),
    ("Y14", "src_ref 唯一", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT src_ref FROM etymology GROUP BY src_ref "
        "HAVING COUNT(*)>1)").fetchone()[0], 0),
    # 🔴 多段词源**全收不二选一**（fr 那轮静默挑一个还挑错了）⇒ 必须有多段的词
    ("Y15", "🔴 多段词源真的都收了（不是静默二选一）", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT word_id, etym_no, src FROM etymology "
        "GROUP BY word_id, etym_no, src HAVING COUNT(*)>1)").fetchone()[0] >= MULTI_FLOOR,
     True),
    ("Y16", "三语都有词源（en/vi/zh）", lambda c: c.execute(
        "SELECT COUNT(DISTINCT src) FROM etymology").fetchone()[0], 4),
    # ⚠️ 看守上界，不是删除判据。见 PRON_LEAK_CEIL 的注释与欠账 W11
    ("Y17", "⚠️ 「像音标/录音数据」的词源段没有变多（看守上界，不删）", _pron_leak, True),
]
ROSTER = tuple("Y%d" % i for i in range(1, 18))
UNMUTABLE = {
    "Y1": "要变异就得清空整张表；它拦的是「表空了而所有 0 值检查全绿」。",
    "Y14": "DDL 上有 `UNIQUE(src_ref)`，注不进去（恒绿已登记）。",
}


def run(con):
    red = []
    have = tuple(c[0] for c in CHECKS)
    if set(have) != set(ROSTER):
        red.append(("Y0", "检查表与花名册对不上：少了 %s，多了 %s"
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
    ("Y2", "把一条词源正文清空",
     "UPDATE etymology SET text='' WHERE id=(SELECT MIN(id) FROM etymology)", {}),
    ("Y3", "让一条词源指向不存在的 dict",
     "UPDATE etymology SET word_id=99999999 WHERE id=(SELECT MIN(id) FROM etymology)", {}),
    ("Y4", "让 entry_id 指向不存在的 entry",
     "UPDATE etymology SET entry_id=99999999 WHERE id=(SELECT MIN(id) FROM etymology)", {}),
    ("Y5", "🔴🔴 往词源层塞一段 `词形［漢字］` 裸表记（阶段 2 的料跑错了栏目）",
     "INSERT INTO etymology(word_id,etym_no,text,src_field,src,src_ref) "
     "SELECT h.word_id,'0', d.word || '［' || h.han || '］','etymology_texts',"
     "       'zh-edition-trad','mut:y5' FROM han_spelling h "
     "JOIN dict d ON d.id=h.word_id LIMIT 1", {}),
    ("Y6", "写一个源头没有的 src_field",
     "UPDATE etymology SET src_field='etymology' "
     "WHERE id=(SELECT MIN(id) FROM etymology)", {}),
    ("Y7", "🔴 把内嵌魔术字塞回正文（清洗那一步被去掉的样子）",
     "UPDATE etymology SET text = text || CHAR(10) || '__NOEDITSECTION__' "
     "WHERE id=(SELECT MIN(id) FROM etymology)", {}),
    ("Y8", "⭐ 删掉九成词源（覆盖率掉下去）",
     "DELETE FROM etymology WHERE id % 10 <> 0",
     {"Y9": "zh 那一支也被删到量级以下", "Y15": "多段的也被删光了"}),
    ("Y9", "⭐ 把中文词源那一支整个删掉（白送的中文丢了）",
     "DELETE FROM etymology WHERE src LIKE 'zh-%'",
     {"Y15": "多段词源里 zh 占了一批", "Y16": "src 从 4 种掉到 2 种"}),
    ("Y10", "写一个值域外的 etym_type",
     "UPDATE entry SET etym_type='随手写的' WHERE id=(SELECT MIN(id) FROM entry "
     "  WHERE etym_type IS NOT NULL)", {}),
    ("Y11", "⭐ 把 etym_type 整列清空（这一列从阶段 0 建着、到阶段 6 一直是 0 行）",
     "UPDATE entry SET etym_type=NULL",
     {"Y12": "compound 也跟着归零"}),
    ("Y12", "🔴 把 `compound` 那一支降成 NULL（新值域被静默吞掉的样子）",
     "UPDATE entry SET etym_type=NULL WHERE etym_type='compound'",
     {"Y11": "compound 占 8,075 行，拿掉它总数 25,750→17,675 跌破 Y11 的下限"}),
    # ⚠️ 连带 Y10 是**声明过的，而且正是重点**：`unknown` 不在 `ETYM_TYPE_DOMAIN` 里 ——
    #    Y13 和 Y10 从两个方向说同一件事（「有意不用」＝「不在值域里」），两条都该响。
    ("Y13", "🔴 给 etym_type 写一个 `unknown`（有意不用的那个值）",
     "UPDATE entry SET etym_type='unknown' WHERE id=(SELECT MIN(id) FROM entry)",
     {"Y10": "`unknown` 不在值域里 —— Y10/Y13 从两个方向说同一件事，都该响"}),
    ("Y15", "🔴 多段词源**只留第一段**（fr 那轮静默二选一的样子）",
     "DELETE FROM etymology WHERE id NOT IN "
     "(SELECT MIN(id) FROM etymology GROUP BY word_id, etym_no, src)", {}),
    ("Y16", "把一整版的词源删掉",
     "DELETE FROM etymology WHERE src='zh-edition-simp'", {}),
    ("Y17", "⚠️ 让音标数据大批涌进词源栏（源头哪天把整个读音章节倒进来的样子）",
     "UPDATE etymology SET text = text || ' IPA: [kɑː˦˥]' WHERE id % 100 = 0", {}),
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
        print("■ vi 词源层闸：%d 条检查" % (len(CHECKS) + 1))
        for cid, why in red:
            print("   🔴 %-5s %s" % (cid, why))
        if not red:
            print("   ✅ 全绿")
        q = lambda x: con.execute(x).fetchone()[0]                  # noqa: E731
        print("   ── 读者口径词源覆盖 **%.2f%%**（下限 %.1f%%）／ 共 %s 段"
              % (_cover(con), COVER_FLOOR, format(q("SELECT COUNT(*) FROM etymology"), ",")))
        for lang, like in (("en", "en-%"), ("vi", "vi-%"), ("zh", "zh-%")):
            n = q("SELECT COUNT(DISTINCT word_id) FROM etymology WHERE src LIKE '%s'" % like)
            print("      %s 覆盖词形 %7s（%5.2f%%）"
                  % (lang, format(n, ","), 100.0 * n / q("SELECT COUNT(*) FROM dict")))
        print("   ── `entry.etym_type`：")
        for t, n in con.execute("SELECT etym_type, COUNT(*) FROM entry "
                                "WHERE etym_type IS NOT NULL GROUP BY etym_type "
                                "ORDER BY 2 DESC"):
            print("      %-18s %8s" % (t, format(n, ",")))
    finally:
        con.close()
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
