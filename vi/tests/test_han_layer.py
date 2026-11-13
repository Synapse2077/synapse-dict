#!/usr/bin/env python3
"""**汉字层闸（vi）** —— `han_spelling` / `nom_spelling` 对不对。2026-09-28。

判据 import 自 `han_sources.py`，**一条都不重写**
（ko 那道闸里我自己重写了收割器的判据，同一道闸判据写错两次、方向相反）。

═══ 🔴🔴 H6 是这道闸里最特别的一条：**它盯的是我的判据会不会过期** ═══
`han_sources.is_ideograph()` 先问 `unicodedata`，问不出来再落到一张码位表上。
那张码位表是**兜底，而兜底会过期** —— Python 自带的 `unicodedata` 是 14.0.0，
CJK 扩展 H 是 Unicode 15.0 才加的，扩展 I 是 15.1。
⇒ H6 扫库里每一个字符：**既不被 `unicodedata` 认识、又不在码位表里**的，当场红。
  那说明源头又出现了新平面的喃字，而我的兜底表该更新了。

⚠️ 这是 ko 那条教训的下一层：「别手抄码位、交给 Unicode 答」是对的，
   但 **Unicode 数据本身是个版本快照**，`[[external-anchor-gates]]` 的反面 ——
   锚在一份会更新的外部数据上，就必须有东西盯着它更没更新。

用法：
    python3 vi/tests/test_han_layer.py
    python3 vi/tests/test_han_layer.py --mutate
"""
import sqlite3
import sys
import unicodedata as ud
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                          # noqa: E402
import han_sources as HS                              # noqa: E402
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
from zh_t2s import t2s                                # noqa: E402  W1
from criteria import is_han_headword                  # noqa: E402

_RULES = ",".join("'%s'" % r for r in HS.RULES)


def _chars(c):
    for t, col in (("han_spelling", "han"), ("nom_spelling", "nom")):
        for (s,) in c.execute("SELECT %s FROM %s" % (col, t)):
            for ch in s:
                yield ch


def h6_unicode_ceiling(c):
    """库里有没有字符**连兜底码位表都兜不住** —— 那说明判据该更新了。"""
    bad = set()
    for ch in _chars(c):
        try:
            ud.name(ch)
        except ValueError:
            if not any(lo <= ord(ch) <= hi for lo, hi in HS._IDEO_BLOCKS):
                bad.add(ch)
    return len(bad)


def h7_unnamed_share(c):
    """**只报数不判红**的那一条：靠兜底表认出来的字符有多少。

    🔴 它必须存在，因为 H6 只在「连兜底都兜不住」时才响 ——
       而「兜底救回来了多少」这个数，是判断兜底表值不值得维护的唯一依据。
       0 就是 0，不是问题；涨起来说明源头在往新平面走。
    """
    n = 0
    for ch in set(_chars(c)):
        try:
            ud.name(ch)
        except ValueError:
            n += 1
    return n


# W1（2026-11-07）：`reading-meaning-v1` 的行数 —— **独立声明**（`[[expectation-must-be-declared]]`）。
#   首次落库：build_han_layer 的升级判据给出 449 行，`--resync-rule` 原地写入。改它必须写理由。
W1_UPGRADED = 449


def h11_w1_rows_satisfy(c):
    """W1：每一行 `reading-meaning-v1` 都必须真满足升级判据（`HS.reading_meaning_ok`，import 不重写）。
    读音表照建层时的口径重建：只取 S2/S4 两档的行。"""
    word = dict(c.execute("SELECT id, word FROM dict"))
    rd = HS.hv_readings([(word[w], h) for w, h in c.execute(
        "SELECT word_id, han FROM han_spelling WHERE rule_ver IN ('src-zh-etym-v1','src-en-etym-v1')")])
    zh = {}
    for w, t in c.execute("SELECT s.word_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
                          "WHERE g.lang='zh' AND COALESCE(s.hidden,0)=0"):
        zh[w] = zh.get(w, "") + " " + (t or "")
    return sum(1 for w, h in c.execute(
        "SELECT word_id, han FROM han_spelling WHERE rule_ver='reading-meaning-v1'")
        if not HS.reading_meaning_ok(word[w], h, rd, zh.get(w, ""), t2s))


CHECKS = [
    ("H1", "han_spelling 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM han_spelling").fetchone()[0] > 0, True),
    ("H2", "nom_spelling 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM nom_spelling").fetchone()[0] > 0, True),
    ("H3", "两张表里全是表意文字", lambda c: sum(
        1 for ch in _chars(c) if not HS.is_ideograph(ch)), 0),
    ("H4", "字数 ＝ 音节数（贯穿五源的硬约束）", lambda c: c.execute(
        "SELECT (SELECT COUNT(*) FROM han_spelling h JOIN dict d ON d.id=h.word_id "
        "        WHERE LENGTH(h.han)<>d.syllables)"
        "     + (SELECT COUNT(*) FROM nom_spelling n JOIN dict d ON d.id=n.word_id "
        "        WHERE LENGTH(n.nom)<>d.syllables)").fetchone()[0], 0),
    ("H5", "rule_ver 都在 han_sources.RULES 的值域里", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT rule_ver FROM han_spelling UNION ALL "
        "SELECT rule_ver FROM nom_spelling) WHERE rule_ver NOT IN (%s)" % _RULES
    ).fetchone()[0], 0),
    ("H6", "🔴 没有字符连兜底码位表都兜不住（判据过期预警）", h6_unicode_ceiling, 0),
    ("H8", "🔴 汉字层不许指向表意文字词头（用户 2026-09-28 定）", lambda c: sum(
        1 for (w,) in c.execute(
            "SELECT DISTINCT d.word FROM dict d "
            "WHERE d.id IN (SELECT word_id FROM han_spelling UNION "
            "               SELECT word_id FROM nom_spelling)")
        if is_han_headword(w)), 0),
    ("H9", "每条都挂得上 dict", lambda c: c.execute(
        "SELECT (SELECT COUNT(*) FROM han_spelling h LEFT JOIN dict d ON d.id=h.word_id "
        "        WHERE d.id IS NULL)"
        "     + (SELECT COUNT(*) FROM nom_spelling n LEFT JOIN dict d ON d.id=n.word_id "
        "        WHERE d.id IS NULL)").fetchone()[0], 0),
    ("H10", "entry_id 要么为空要么真指向一条 entry", lambda c: c.execute(
        "SELECT COUNT(*) FROM han_spelling h LEFT JOIN entry e ON e.id=h.entry_id "
        "WHERE h.entry_id IS NOT NULL AND e.id IS NULL").fetchone()[0], 0),
    ("H11", "W1：升到 reading-meaning-v1 的每一行都真满足「汉越音逐字对上 ∧ 与中文释义共字」",
     h11_w1_rows_satisfy, 0),
    ("H12", "W1：reading-meaning-v1 的行数（独立声明 W1_UPGRADED）", lambda c: c.execute(
        "SELECT COUNT(*) FROM han_spelling WHERE rule_ver='reading-meaning-v1'").fetchone()[0], W1_UPGRADED),
]
# 🔴 **H11 写了又删掉**：我本来加了一条「最弱那批确实带着 rule_ver」，
#    判据是 `rule_ver='codepoint-v1' AND rule_ver=''` —— **恒为 0，永远绿**。
#    `[[permanently-red-gate-masks-real-reds]]` 的镜像：恒绿的信号量同样是零，
#    留着只会让花名册看起来更长。真正要的是**读者口径**那一条
#    （展示层不许给 codepoint-v1 印「汉越字」），而展示层还不存在 ⇒ 记欠账 **W6**，
#    不在这儿放占位符。
ROSTER = ("H1", "H2", "H3", "H4", "H5", "H6", "H8", "H9", "H10", "H11", "H12")
# 🔴 H7 有意不进花名册：它**只报数不判红**。进了花名册就得有期望值，
#    而它要量的东西（兜底救回多少）**没有正确答案**，只有趋势。
#    写在这儿是为了让「想过了」和「漏了」分得开。
SKIP = {"H7": "只报数不判红 —— 兜底表救回了多少字符，没有正确答案，只有趋势"}

UNMUTABLE = {
    "H1": "要变异就得清空整张表，代价与收益不成比例；它拦的是「表空了而所有 0 值检查全绿」。",
    "H2": "同 H1。",
}


def run(con):
    red = []
    have = tuple(c[0] for c in CHECKS)
    # 🔴 比**集合**不比元组：顺序没有语义，而第一版按元组比，
    #    在往中间插一条检查时报出「少了 无，多了 无」—— 一个说不清楚的红。
    #    删掉一条仍然逮得到（集合会少一个），那才是这条检查要防的事。
    if set(have) != set(ROSTER):
        red.append(("H0", "检查表与花名册对不上：少了 %s，多了 %s"
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
    ("H3", "往 han 里塞一个拉丁字母",
     "UPDATE han_spelling SET han='aa' WHERE id=(SELECT MIN(id) FROM han_spelling)",
     {"H4": "'aa' 长度 2 而那个词的音节数不是 2"}),
    ("H4", "把一条的汉字改成字数对不上的",
     "UPDATE han_spelling SET han=han||han||han WHERE id=(SELECT MIN(id) FROM han_spelling)", {}),
    ("H5", "写一个不在值域里的 rule_ver",
     "UPDATE nom_spelling SET rule_ver='guess-v9' WHERE id=(SELECT MIN(id) FROM nom_spelling)", {}),
    ("H6", "🔴 塞一个私用区字符（unicodedata 不认识、码位表也兜不住）",
     "UPDATE nom_spelling SET nom=char(57344) WHERE id=(SELECT MIN(id) FROM nom_spelling)",
     {"H3": "私用区字符本来就不是表意文字", "H4": "换成 1 个字符后字数可能对不上"}),
    ("H8", "让一条汉字表记指向一个表意文字词头",
     "INSERT INTO dict(word,word_norm,pos,is_lemma,entry_type,syllables) VALUES('學生','學生','noun',1,'word',2);"
     "INSERT INTO han_spelling(word_id,han,rule_ver,src,src_ref) "
     "VALUES((SELECT id FROM dict WHERE word='學生'),'學生','codepoint-v1','t','t-1')", {}),
    ("H9", "让一条指向不存在的 dict",
     "UPDATE han_spelling SET word_id=99999999 WHERE id=(SELECT MIN(id) FROM han_spelling)",
     {"H4": "join 不上 dict 之后字数检查也够不着它"}),
    # W1：把一条**没有中文释义**的码位推定行硬升上去（判据不满足）⇒ H11 红；行数随之 +1 ⇒ H12 连带
    ("H11", "把一条不满足判据的 codepoint-v1 行升成 reading-meaning-v1",
     "UPDATE han_spelling SET rule_ver='reading-meaning-v1' WHERE id=(SELECT MIN(h.id) FROM han_spelling h "
     "WHERE h.rule_ver='codepoint-v1' AND NOT EXISTS(SELECT 1 FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
     "AND g.lang='zh' WHERE s.word_id=h.word_id))",
     {"H12": "多了一行 reading-meaning-v1"}),
    ("H12", "把一条 reading-meaning-v1 退回 codepoint-v1（升级被静默撤销的样子）",
     "UPDATE han_spelling SET rule_ver='codepoint-v1' WHERE id="
     "(SELECT MIN(id) FROM han_spelling WHERE rule_ver='reading-meaning-v1')", {}),
    ("H10", "让 entry_id 指向不存在的 entry",
     "UPDATE han_spelling SET entry_id=99999999 WHERE id=(SELECT MIN(id) FROM han_spelling)", {}),
]


def mutate():
    con = sqlite3.connect(paths.DB)
    base = run(con)
    if base:
        print("🔴 基线就不绿：")
        for c, w in base:
            print("   %s %s" % (c, w))
        return False
    ok = True
    covered = set()
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
        print("■ vi 汉字层闸：%d 条检查（跳号 %s）" % (len(CHECKS) + 1, "、".join(sorted(SKIP))))
        for cid, why in red:
            print("   🔴 %-5s %s" % (cid, why))
        if not red:
            print("   ✅ 全绿")
        # H7 只报数
        print("   ── H7（只报数）靠兜底码位表认出来的字符：%d 个 —— "
              "0 是正常，涨起来说明源头在往新平面走" % h7_unnamed_share(con))
        n_h = con.execute("SELECT COUNT(*) FROM han_spelling").fetchone()[0]
        n_n = con.execute("SELECT COUNT(*) FROM nom_spelling").fetchone()[0]
        weak = con.execute("SELECT COUNT(*) FROM han_spelling "
                           "WHERE rule_ver='codepoint-v1'").fetchone()[0]
        print("   ── 现状：han %s ／ nom %s ／ 其中最弱的 han+codepoint-v1 **%s（%.1f%%）**"
              % (format(n_h, ","), format(n_n, ","), format(weak, ","), 100 * weak / n_h))
    finally:
        con.close()
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
