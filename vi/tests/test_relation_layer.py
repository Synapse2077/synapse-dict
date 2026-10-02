#!/usr/bin/env python3
"""**关系与量词闸（vi）** —— `sense_relation` / `noun_classifier`。2026-10-01。

判据 import 自 `stage6_sources.py`。两张表合一道闸是因为它们是同一件事的两面：
**「这个词和别的词是什么关系」**（量词关系也是关系，只是源头把它塞在 `forms` 里）。

═══ ⭐ R6 是**读者口径**的那一条 ═══
「库里有 14.5 万条关系」说明不了读者打开一个词能不能看见关系。
R6 量的是**有多少词形至少有一条可出版关系**（实测 30.09%）。

═══ 🔴 R8 守 B17，而它守的是**正确那一版判据** ═══
`BACKLOG` B17：兜底 `related` 撞上更具体的 kind 时，读者在两个标题下看见同一个词。
naive 判据（撞上任何 kind）会命中 14,547 对，正确判据（撞上**语义**更具体的 kind）
只有 1,317 对 —— **差 11 倍**，差的全是 `paronym+related`。
⇒ R8 两头都查：**该隐藏的真隐藏了**（量级），**不该隐藏的没被隐藏**
   （`paronym` 在场而没有语义 kind 的那些 `related` 必须还在出版层）。
🔴 只查前一半的话，把判据放宽成 naive 版照样全绿 —— 而那会吞掉一万三千条该留的。

═══ 🔴 R11：`target_id` 解析不了的必须留 NULL，而不是乱指 ═══
ko 那边「关系词 **34.6% 点下去空白页**」就是把解析不了的目标也做成了链接。
vi 的解析率 83.0%，剩下 16.9% 是派生复合词/短语，它们本来就没有词条。
⇒ `target_id IS NULL` 是一等信息。R11 查**没有一条 `target_id` 指向不存在的 dict 行**。
⚠️ 「展示层不许把 NULL 做成链接」是阶段 9 的展示层契约闸的事，这道闸管不到。

═══ 🔴 R13：量词**不许等于被修饰的名词自己** ═══
`cái` 的量词是 `cái` 这种自环，读者看见「量词：cái」而词本身就是 `cái`。
实测 0 条，但这是**反向断言**：它为 0 才说明收割没把词形自己当量词收进来。
"""
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                                      # noqa: E402
import stage6_sources as S6                                       # noqa: E402
from criteria import is_han_headword                              # noqa: E402

# 🔴 下限按 2026-10-01 实测写死。⚠️ 距现状 ≤3 个点（账的闸 V10 查这件事）
COVER_FLOOR = 28.5          # 实测 30.09%（20,055 / 66,657）
CLS_COVER_FLOOR = 4.0       # 实测 4.31%（2,875 个名词有量词）
B17_HIDDEN_FLOOR = 1200     # 实测隐藏 1,460 行
B17_HIDDEN_CEIL = 5000      # 🔴 上限：naive 判据会隐藏 14,547 对 ⇒ 超过就是判据被放宽了
KIND_COUNT = 18             # 实测库里 18 种 kind（源头给了 19 种字段，`instance` 一条都没有）
SRC_COUNT = 12
_KIND_DOM = ",".join("'%s'" % k for k in sorted(set(S6.KINDS.values())))


# 🔴 判据 import，不重写。`[[criteria-narrower-than-you-think]]`、ko 的 K10。
def _han_targets(c):
    return sum(1 for (t,) in c.execute(
        "SELECT target FROM sense_relation WHERE hidden=0") if is_han_headword(t))


def _foreign_targets(c):
    return sum(1 for (t,) in c.execute(
        "SELECT target FROM sense_relation WHERE hidden=0")
        if S6.has_non_vietnamese_script(t))


def _cover(c, sql):
    n = c.execute(sql).fetchone()[0]
    t = c.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    return 100.0 * n / max(t, 1)


def _rel_cover(c):
    return _cover(c, "SELECT COUNT(DISTINCT word_id) FROM sense_relation WHERE hidden=0")


def _cls_cover(c):
    return _cover(c, "SELECT COUNT(DISTINCT word_id) FROM noun_classifier")


CHECKS = [
    ("R1", "sense_relation 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_relation").fetchone()[0] > 0, True),
    ("R2", "noun_classifier 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM noun_classifier").fetchone()[0] > 0, True),
    ("R3", "目标非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE TRIM(target)=''").fetchone()[0], 0),
    ("R4", "每条关系都挂得上 dict", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_relation r LEFT JOIN dict d ON d.id=r.word_id "
        "WHERE d.id IS NULL").fetchone()[0], 0),
    ("R5", "kind 都在 stage6_sources 的值域里", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE kind NOT IN (%s)" % _KIND_DOM
    ).fetchone()[0], 0),
    ("R6", "⭐ 读者口径：有可出版关系的词形占比不低于下限",
     lambda c: _rel_cover(c) >= COVER_FLOOR, True),
    ("R7", "src_ref 唯一", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT src_ref FROM sense_relation GROUP BY src_ref "
        "HAVING COUNT(*)>1)").fetchone()[0], 0),
    # 🔴 B17 的两头。单查「隐藏了多少」挡不住判据被放宽成 naive 版
    ("R8", "🔴 B17：该隐藏的真隐藏了（量级）", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE hidden_why=?",
        (S6.HIDDEN_REDUNDANT_RELATED,)).fetchone()[0] >= B17_HIDDEN_FLOOR, True),
    ("R9", "🔴 B17：**不该隐藏的没被隐藏**（naive 判据会多吞一万三）", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE hidden_why=?",
        (S6.HIDDEN_REDUNDANT_RELATED,)).fetchone()[0] <= B17_HIDDEN_CEIL, True),
    # 🔴 读者口径的那条反向断言：`paronym` 在场**不该**让 related 消失
    ("R10", "🔴 `paronym` 是语音关系，它在场时同一对的 `related` 必须还在出版层",
     lambda c: c.execute(
         "SELECT COUNT(*) FROM sense_relation a JOIN sense_relation b "
         "  ON b.word_id=a.word_id AND b.target=a.target "
         "WHERE a.kind='paronym' AND b.kind='related' AND b.hidden=0").fetchone()[0] > 0,
     True),
    ("R11", "🔴 target_id 要么空要么真指向一条 dict（ko 的「点下去空白页」）",
     lambda c: c.execute(
         "SELECT COUNT(*) FROM sense_relation r LEFT JOIN dict d ON d.id=r.target_id "
         "WHERE r.target_id IS NOT NULL AND d.id IS NULL").fetchone()[0], 0),
    ("R12", "sense_id 要么空要么真指向一条 sense", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_relation r LEFT JOIN sense s ON s.id=r.sense_id "
        "WHERE r.sense_id IS NOT NULL AND s.id IS NULL").fetchone()[0], 0),
    ("R13", "🔴 量词不是被修饰的那个名词自己（自环）", lambda c: c.execute(
        "SELECT COUNT(*) FROM noun_classifier n JOIN dict d ON d.id=n.word_id "
        "WHERE d.word = n.classifier").fetchone()[0], 0),
    ("R14", "classifier_id 要么空要么真指向一条 dict", lambda c: c.execute(
        "SELECT COUNT(*) FROM noun_classifier n LEFT JOIN dict d ON d.id=n.classifier_id "
        "WHERE n.classifier_id IS NOT NULL AND d.id IS NULL").fetchone()[0], 0),
    ("R15", "⭐ 读者口径：有量词的名词占比不低于下限",
     lambda c: _cls_cover(c) >= CLS_COVER_FLOOR, True),
    # 🔴 **关系的多值性真的存在**：34.6% 的名词配 ≥2 个量词，塌成单值的话这个数归零
    ("R16", "🔴 多量词名词真的存在（单值字段装不下，V5 的落点）", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT word_id FROM noun_classifier GROUP BY word_id "
        "HAVING COUNT(DISTINCT classifier)>=2)").fetchone()[0] > 500, True),
    ("R17", "隐藏的都写了为什么", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE hidden=1 AND "
        "(hidden_why IS NULL OR TRIM(hidden_why)='')").fetchone()[0], 0),
    ("R18", "🔴 十二份切片都有关系落进来", lambda c: c.execute(
        "SELECT COUNT(DISTINCT src) FROM sense_relation").fetchone()[0], SRC_COUNT),
    # 🔴🔴 关系目标**不许是汉字/喃字** —— 汉字词头有意不进 dict ⇒ 必然死链。
    #    **判据 import，不在 SQL 里手写近似版。**
    #    第一版写的是 `target GLOB '*[一-鿿]*' AND NOT target GLOB '*[a-zA-Z]*'`，
    #    它同时**比真判据宽**（把日语 `彼ら` 也算上）**又比真判据窄**
    #    （`一-鿿` 只覆盖通用区，扩展 B 的喃字整批漏掉）。
    #    ⇒ 闸与收割器必须用同一个函数，否则「闸绿了」说明不了「数据对了」。
    ("R19", "🔴 关系目标不是纯汉字/喃字（必然死链）", _han_targets, 0),
    # 🔴 第三类死链：假名/韩文字母（日语词 ／ 越南语词+韩语释义拼在一起 ／ 整段标签塞进 target）
    ("R21", "🔴 关系目标不含假名/韩文字母（不是越南语词形）", _foreign_targets, 0),
    ("R20", "🔴 kind 真的分了 18 种（塌成一种也会「表非空」）", lambda c: c.execute(
        "SELECT COUNT(DISTINCT kind) FROM sense_relation").fetchone()[0], KIND_COUNT),
]
ROSTER = tuple("R%d" % i for i in range(1, 22))
UNMUTABLE = {
    "R1": "要变异就得清空整张表；它拦的是「表空了而所有 0 值检查全绿」。",
    "R2": "同上，`noun_classifier` 这一侧。",
    "R7": "DDL 上有 `UNIQUE(src_ref)`，注不进去（恒绿已登记）。",
}


def run(con):
    red = []
    have = tuple(c[0] for c in CHECKS)
    if set(have) != set(ROSTER):
        red.append(("R0", "检查表与花名册对不上：少了 %s，多了 %s"
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
    ("R3", "把一条关系的目标清空",
     "UPDATE sense_relation SET target='' WHERE id=(SELECT MIN(id) FROM sense_relation)",
     {}),
    ("R4", "让一条关系指向不存在的 dict",
     "UPDATE sense_relation SET word_id=99999999 "
     "WHERE id=(SELECT MIN(id) FROM sense_relation)", {}),
    ("R5", "写一个值域外的 kind",
     "UPDATE sense_relation SET kind='随手写的' "
     "WHERE id=(SELECT MIN(id) FROM sense_relation)",
     {"R20": "kind 种数从 18 变成 19"}),
    ("R6", "⭐ 把九成关系隐藏掉（模拟判据写太宽）",
     "UPDATE sense_relation SET hidden=1, hidden_why='redundant-related' "
     "WHERE id % 10 <> 0", {"R9": "隐藏量冲破 naive 上限", "R10": "paronym 的对子也被吞了"}),
    ("R8", "🔴 B17 的判据被关掉（该隐藏的全放出来）",
     "UPDATE sense_relation SET hidden=0, hidden_why=NULL WHERE hidden_why='redundant-related'",
     {}),
    ("R9", "🔴 B17 换成 naive 判据（把 paronym 的对子也吞掉）",
     "UPDATE sense_relation SET hidden=1, hidden_why='redundant-related' "
     "WHERE kind='related' AND EXISTS (SELECT 1 FROM sense_relation x "
     "  WHERE x.word_id=sense_relation.word_id AND x.target=sense_relation.target "
     "    AND x.kind<>'related')",
     {"R10": "这正是 naive 判据的代价：paronym 的对子被吞了"}),
    # 🔴 R10 要有**自己**的变异 —— 只在别的变异的 `also` 里出现过，等于没验过它。
    #    删掉（而不是隐藏）那批 `paronym` 旁边的 `related`：R10 的计数归零而
    #    B17 的隐藏量一点不动 ⇒ 这一条验的正是「R8 绿着而 R10 能红」。
    ("R10", "🔴 把 `paronym` 旁边的 `related` 整批删掉（R8 不动而 R10 必须红）",
     "DELETE FROM sense_relation WHERE kind='related' AND hidden=0 AND EXISTS "
     "(SELECT 1 FROM sense_relation x WHERE x.word_id=sense_relation.word_id "
     "   AND x.target=sense_relation.target AND x.kind='paronym')", {}),
    ("R11", "让 target_id 指向不存在的 dict",
     "UPDATE sense_relation SET target_id=99999999 "
     "WHERE id=(SELECT MIN(id) FROM sense_relation)", {}),
    ("R12", "让 sense_id 指向不存在的 sense",
     "UPDATE sense_relation SET sense_id=99999999 "
     "WHERE id=(SELECT MIN(id) FROM sense_relation)", {}),
    ("R13", "🔴 塞一条自环量词（词形自己当量词）",
     "INSERT INTO noun_classifier(word_id,classifier,src,src_ref) "
     "SELECT id, word, 'en-edition', 'mut:r13' FROM dict LIMIT 1", {}),
    ("R14", "让 classifier_id 指向不存在的 dict",
     "UPDATE noun_classifier SET classifier_id=99999999 "
     "WHERE id=(SELECT MIN(id) FROM noun_classifier)", {}),
    ("R15", "⭐ 删掉九成量词行（覆盖率掉下去）",
     "DELETE FROM noun_classifier WHERE id % 10 <> 0",
     {"R16": "多量词名词也被删光了"}),
    ("R16", "🔴 把多量词塌成单值（像西语阴阳性那样）—— 行数掉而「表非空」还成立",
     "DELETE FROM noun_classifier WHERE id NOT IN "
     "(SELECT MIN(id) FROM noun_classifier GROUP BY word_id)",
     {"R15": "行数掉到 2,875 ⇒ 覆盖率不变，但这条声明一下更诚实"}),
    ("R17", "隐藏一条而不写为什么",
     "UPDATE sense_relation SET hidden=1, hidden_why=NULL "
     "WHERE id=(SELECT MIN(id) FROM sense_relation)", {}),
    ("R18", "🔴 把一整版的关系删掉（跨版收割缩水）",
     "DELETE FROM sense_relation WHERE src='ru-edition'", {}),
    ("R19", "🔴 塞一条纯汉字目标（必然死链）",
     "INSERT INTO sense_relation(word_id,kind,target,hidden,src,src_ref) "
     "SELECT MIN(id),'derived','兵馬',0,'en-edition','mut:r19' FROM dict", {}),
    ("R21", "🔴 塞一条日语目标（假名）",
     "INSERT INTO sense_relation(word_id,kind,target,hidden,src,src_ref) "
     "SELECT MIN(id),'derived','彼ら',0,'ja-edition','mut:r21' FROM dict", {}),
    ("R20", "🔴 把所有 kind 塌成一种",
     "UPDATE sense_relation SET kind='related'",
     {"R8": "related 塌成一种后 B17 的隐藏行 kind 也变了",
      "R10": "paronym 不存在了，R10 的对子找不到"}),
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
        print("■ vi 关系与量词闸：%d 条检查" % (len(CHECKS) + 1))
        for cid, why in red:
            print("   🔴 %-5s %s" % (cid, why))
        if not red:
            print("   ✅ 全绿")
        q = lambda x: con.execute(x).fetchone()[0]                  # noqa: E731
        print("   ── 读者口径：关系覆盖 **%.2f%%**（下限 %.1f%%）／ 量词覆盖 **%.2f%%**（下限 %.1f%%）"
              % (_rel_cover(con), COVER_FLOOR, _cls_cover(con), CLS_COVER_FLOOR))
        print("   ── 关系 %s（B17 隐藏 %s）／ %s 种 kind ／ 挂到义项 %s ／ 有链 %.1f%%"
              % (format(q("SELECT COUNT(*) FROM sense_relation"), ","),
                 format(q("SELECT COUNT(*) FROM sense_relation "
                          "WHERE hidden_why='redundant-related'"), ","),
                 q("SELECT COUNT(DISTINCT kind) FROM sense_relation"),
                 format(q("SELECT COUNT(*) FROM sense_relation "
                          "WHERE sense_id IS NOT NULL"), ","),
                 100.0 * q("SELECT COUNT(*) FROM sense_relation "
                           "WHERE hidden=0 AND target_id IS NOT NULL")
                 / max(q("SELECT COUNT(*) FROM sense_relation WHERE hidden=0"), 1)))
        print("   ── 量词 %s 行 / %s 个名词，其中配 ≥2 个的 %s"
              % (format(q("SELECT COUNT(*) FROM noun_classifier"), ","),
                 format(q("SELECT COUNT(DISTINCT word_id) FROM noun_classifier"), ","),
                 format(q("SELECT COUNT(*) FROM (SELECT word_id FROM noun_classifier "
                          "GROUP BY word_id HAVING COUNT(DISTINCT classifier)>=2)"), ",")))
    finally:
        con.close()
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
