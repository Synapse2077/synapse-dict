#!/usr/bin/env python3
"""**重音闸** —— 阶段 2 的不变量。ru，2026-10-08。

    python3 ru/tests/test_stress.py
    python3 ru/tests/test_stress.py --mutate      # 变异验证：闸的闸
    python3 ru/tests/test_stress.py --accept      # 把覆盖率现状锁成基线

═══ 这道闸为什么存在，以及它盯的是哪几件事 ═══
重音层是九门里第一次有的层，所以它没有「上一门怎么做的」可抄。盯四类：

① **出版值必须自己满足收它的那条判据**（T2）。判据一律 `import criteria`，
   闸不自己写一版 —— ko 的 K24／vi 的 R19 都是闸手写近似判据，**同时更宽又更窄**。
② **派生列与真值必须对得上，而且两个方向都断言**（T4）。`entry.stressed` 是从
   `stress.is_primary=1` 派生的展示列；只断言一个方向的话，「派生列全清空」
   或「真值全删而派生列留着」都能过（`[[expectation-must-be-declared]]`）。
③ **「没有信息的行」比空着更坏**（T5/T6）。源头把重音符写成游离的
   （`крем для бритья ́`），修掉之后剩下的串与词头一字不差 —— 印在读者页的
   「重音写法」栏里，它看起来正常而什么都没说。**错比缺更伤权威。**
④ **预组合与组合式两种编码不许混**（T6）。`ѐ`(U+0450) 与 `е`＋U+0300 看起来一样，
   而 `norm_ru` 剥的是组合符：预组合的那种**剥不掉**，重音符会活着流进检索键。
   这一条是写这道闸时逮到的，当场逼出 `criteria.to_combining_stress` 与一次 `--rebuild`。

═══ ⚠️ 覆盖率是**两个数**不是一个 ═══
`词元 37.18%` 这个数单独印出来会被读成「六成的词元源头没给重音」。而实测
**6.59% 的词元本来就不需要重音符**（含 ё／单音节）—— ё 永远重读、俄语词典惯例
不另标符。⇒ T10 同时锁两个口径，分桶判据的家在 `criteria.stress_not_needed`。
（vi 的 `coverage.blank_split()`：**返回两个数不是一个**。）
"""
import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.stress_layer import PROV_RANK                     # noqa: E402
from pipeline.build import SRC                                  # noqa: E402

# 🔴 **花名册独立声明**，不从代码里数（`[[expectation-must-be-declared]]`）——
#    ko 的 K31：改测试时把一条检查删掉而闸报「全绿」，而**没有任何东西数过
#    输出该有几条**。vi 那门同一件事在回归闸上又演了一遍。
ROSTER = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11")

# 已接受基线（覆盖率）。**锁数字不锁名字**，而且**只许涨不许跌**。
ACCEPT = HERE / ".stress_accept.json"

# `stress.src` 的登记表：`<源>/<来源身份>`。
# 🔴 **问登记表不写形状** —— vi 那门 `src.endswith('-edition')` 认不出
#    `zh-edition-trad`，判据一律问名单。
SRC_DOMAIN = frozenset("%s/%s" % (s, p) for s, _ in SRC for p in PROV_RANK)


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def _accept():
    try:
        return json.loads(ACCEPT.read_text("utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def coverage(con):
    """→ 覆盖率的**两个口径**。分桶判据 `import` 不重写。"""
    rows = con.execute(
        "SELECT d.word, MAX(CASE WHEN e.stressed IS NOT NULL "
        "AND TRIM(e.stressed)<>'' THEN 1 ELSE 0 END) "
        "FROM dict d JOIN entry e ON e.word_id=d.id "
        "WHERE d.is_lemma=1 GROUP BY d.id").fetchall()
    tot = len(rows)
    got = sum(h for _w, h in rows)
    need = [(w, h) for w, h in rows if criteria.stress_not_needed(w) is None]
    return dict(
        lemmas=tot, lemmas_with=got,
        pct_all=100.0 * got / max(tot, 1),
        need=len(need), need_with=sum(h for _w, h in need),
        pct_need=100.0 * sum(h for _w, h in need) / max(len(need), 1),
        not_needed=tot - len(need),
    )


def checks(con):
    """→ [(编号, 是否通过, 说明)]。"""
    out = []
    acc = _accept()

    def q(sql, *a):
        return con.execute(sql, a).fetchone()[0]

    # ── T1 这一层非空 ──────────────────────────────────────────────
    n = q("SELECT COUNT(*) FROM stress")
    out.append(("T1", n > 0, "" if n else "`stress` 是空的 —— 阶段 2 声明 ✅ 而一行都没有"))

    # ── T2 出版值必须满足收它的那条判据（判据 import，闸不重写）────────
    bad2, eg2 = 0, []
    for sid, st, w in con.execute(
            "SELECT s.id, s.stressed, d.word FROM stress s JOIN dict d ON d.id=s.word_id"):
        ok, kind, _v = criteria.stressed_spelling(w, st)
        if not ok:
            bad2 += 1
            if len(eg2) < 5:
                eg2.append("#%d %s → %s〔%s〕" % (sid, w, st, kind))
    out.append(("T2", bad2 == 0,
                "" if not bad2 else
                "%s 行出版值过不了 `criteria.stressed_spelling` —— "
                "**收它的判据和查它的判据必须是同一个函数**：%s"
                % (format(bad2, ","), " ｜ ".join(eg2))))

    # ── T3 `is_primary` 唯一，**且两个方向都断言** ──────────────────
    multi = q("SELECT COUNT(*) FROM (SELECT entry_id FROM stress WHERE is_primary=1 "
              "GROUP BY entry_id HAVING COUNT(*)>1)")
    none_ = q("SELECT COUNT(*) FROM (SELECT entry_id FROM stress GROUP BY entry_id "
              "HAVING SUM(is_primary)=0)")
    out.append(("T3", multi == 0 and none_ == 0,
                "" if not (multi or none_) else
                "`is_primary` 不唯一：%s 个 entry 有多行主行、%s 个 entry **一行主行都没有**"
                "（只查前者的话「全都不是主行」会静默通过）"
                % (format(multi, ","), format(none_, ","))))

    # ── T4 派生列 `entry.stressed` ↔ 真值，**两个方向** ──────────────
    mismatch = q("SELECT COUNT(*) FROM entry e JOIN stress s "
                 "ON s.entry_id=e.id AND s.is_primary=1 "
                 "WHERE COALESCE(e.stressed,'')<>s.stressed")
    orphan = q("SELECT COUNT(*) FROM entry e WHERE e.stressed IS NOT NULL "
               "AND TRIM(e.stressed)<>'' AND NOT EXISTS("
               "SELECT 1 FROM stress s WHERE s.entry_id=e.id AND s.is_primary=1)")
    missing = q("SELECT COUNT(*) FROM stress s WHERE s.is_primary=1 AND EXISTS("
                "SELECT 1 FROM entry e WHERE e.id=s.entry_id "
                "AND (e.stressed IS NULL OR TRIM(e.stressed)=''))")
    out.append(("T4", mismatch == 0 and orphan == 0 and missing == 0,
                "" if not (mismatch or orphan or missing) else
                "派生列与真值对不上：值不同 %s ／ 派生列有值而无主行 %s ／ "
                "有主行而派生列空 %s —— **三个方向都要断言**，只查一个的话"
                "「真值全删」和「派生列全清」各能过一个"
                % (format(mismatch, ","), format(orphan, ","), format(missing, ","))))

    # ── T5 出版值**不许等于词头**（没有信息的行比空着更坏）────────────
    same = q("SELECT COUNT(*) FROM stress s JOIN dict d ON d.id=s.word_id "
             "WHERE s.stressed = d.word")
    out.append(("T5", same == 0,
                "" if not same else
                "%s 行的带重音拼写**与词头一字不差** —— 它一个比特的信息都不带，"
                "而印在「重音写法」栏里看起来是正常的（**错比缺更伤权威**）。"
                "成因通常是源头把重音符写成了游离的，修掉之后什么都不剩"
                % format(same, ",")))

    # ── T6 出版值必须带重音信息，**且只许一种编码** ──────────────────
    nomark, pre, eg6 = 0, 0, []
    import unicodedata as ud
    for sid, st in con.execute("SELECT id, stressed FROM stress"):
        if not criteria.has_any_stress(st):
            nomark += 1
            if len(eg6) < 4:
                eg6.append("#%d %s" % (sid, st))
            continue
        # 预组合的重音字母（`ѐ` U+0450 / `ó` U+00F3）：`norm_ru` 剥不掉它
        if any(len(ud.normalize("NFD", ch)) == 2
               and ud.normalize("NFD", ch)[1] in criteria.MARKS for ch in st):
            pre += 1
            if len(eg6) < 8:
                eg6.append("#%d %s（预组合）" % (sid, st))
    out.append(("T6", nomark == 0 and pre == 0,
                "" if not (nomark or pre) else
                "%s 行不带任何重音符、%s 行用**预组合**重音字母 —— 后者 `strip_stress` "
                "剥不掉，于是重音符会活着流进 `norm_ru` 的检索键。"
                "判据的家是 `criteria.to_combining_stress`：%s"
                % (format(nomark, ","), format(pre, ","), " ｜ ".join(eg6))))

    # ── T7 `src` 值域 ⊆ 登记表（问名单不写形状）──────────────────────
    uns = [r[0] for r in con.execute(
        "SELECT DISTINCT src FROM stress") if r[0] not in SRC_DOMAIN]
    out.append(("T7", not uns,
                "" if not uns else
                "`stress.src` 出现没登记的值 %s —— 判据问登记表（`SRC` × `PROV_RANK`），"
                "不写形状（vi 的 `endswith('-edition')` 认不出 `zh-edition-trad`）"
                % uns[:5]))

    # ── T8 外键 ＋ `word_id` 与它 entry 的 `word_id` 必须一致 ─────────
    fk_d = q("SELECT COUNT(*) FROM stress s LEFT JOIN dict d ON d.id=s.word_id "
             "WHERE d.id IS NULL")
    fk_e = q("SELECT COUNT(*) FROM stress s WHERE s.entry_id IS NOT NULL "
             "AND NOT EXISTS(SELECT 1 FROM entry e WHERE e.id=s.entry_id)")
    disagree = q("SELECT COUNT(*) FROM stress s JOIN entry e ON e.id=s.entry_id "
                 "WHERE e.word_id<>s.word_id")
    out.append(("T8", fk_d == 0 and fk_e == 0 and disagree == 0,
                "" if not (fk_d or fk_e or disagree) else
                "外键/一致性坏了：word_id 悬空 %s ／ entry_id 悬空 %s ／ "
                "两处 word_id 不一致 %s（R13 合并 dict 行时不重映射就会留下这种）"
                % (format(fk_d, ","), format(fk_e, ","), format(disagree, ","))))

    # ── T9 `variant_seq` 每个 entry 从 0 连续 ────────────────────────
    gap = q("SELECT COUNT(*) FROM (SELECT entry_id FROM stress GROUP BY entry_id "
            "HAVING MIN(variant_seq)<>0 OR MAX(variant_seq)<>COUNT(*)-1 "
            "OR COUNT(DISTINCT variant_seq)<>COUNT(*))")
    out.append(("T9", gap == 0,
                "" if not gap else
                "%s 个 entry 的 `variant_seq` 不是从 0 起的连续序号 —— "
                "展示层按它排变体，有洞就会漏印一个" % format(gap, ",")))

    # ── T10 覆盖率：**两个口径一起锁**，只许涨不许跌 ──────────────────
    cov = coverage(con)
    base = acc.get("coverage")
    if base is None:
        ok10, why10 = False, (
            "词元覆盖 %.2f%%（需要标注的那批 %.2f%%），而**还没有已接受基线** —— "
            "跑一次 `--accept` 把它锁下来" % (cov["pct_all"], cov["pct_need"]))
    else:
        drop = [k for k in ("pct_all", "pct_need")
                if cov[k] < base[k] - 0.01]
        ok10 = not drop
        why10 = ("" if ok10 else
                 "覆盖率跌了：%s（现 全体 %.2f%% / 需标注 %.2f%%，"
                 "基线 %.2f%% / %.2f%%）—— 「已接受」≠「不再看」"
                 % (drop, cov["pct_all"], cov["pct_need"],
                    base["pct_all"], base["pct_need"]))
        # ⚠️ 100.00% 是假闸的签名（分母套了分子）
        if ok10 and abs(cov["pct_need"] - 100.0) < 1e-9:
            ok10, why10 = False, "需标注覆盖恒等 100.00% —— **假闸的签名**（分母套了分子）"
    out.append(("T10", ok10, why10))

    # ── T11 R13 已结清：`dict.word` 不许带重音符（带锁的豁免一条）──────
    # 🔴 `◌́` 是维基词典给 U+0301 **本身**建的条目，合法 —— 这是豁免，
    #    而豁免**写成白名单**（不是「数量 ≤ 1」那种会把下一个漏进来的写法）。
    #    ⚠️ 它的真身是 **U+25CC（虚位圆圈）＋ U+0301**，不是裸的 U+0301 ——
    #      白名单写错一个码位，这条豁免就会「看起来在白名单里」而照样判红。
    R13_EXEMPT = {"◌́"}
    marked = [r[0] for r in con.execute("SELECT word FROM dict")
              if criteria.has_any_stress(r[0]) and r[0] not in R13_EXEMPT]
    out.append(("T11", not marked,
                "" if not marked else
                "%s 个 `dict.word` 带着重音符：%s —— 重音不是拼写的一部分"
                "（这是本层的前提），它该进 `stress` 不该留在身份单位里。"
                "豁免只有 `◌́`（U+0301 自己的条目）"
                % (len(marked), marked[:6])))
    return out


def roster_check(rows):
    """闸自己的闸：输出的条数/编号必须与独立声明的花名册一致。"""
    bad = []
    got = [c for c, _ok, _w in rows]
    if len(got) != len(ROSTER):
        bad.append("输出 %d 条，花名册声明 %d 条 —— 有检查被删掉或没登记"
                   % (len(got), len(ROSTER)))
    if sorted(got) != sorted(ROSTER):
        bad.append("编号对不上：多 %s ／ 少 %s"
                   % (sorted(set(got) - set(ROSTER)), sorted(set(ROSTER) - set(got))))
    if len(set(got)) != len(got):
        bad.append("有重复编号 %s" % got)
    return bad


def report():
    if not paths.DB.exists():
        print("🔴 库不存在：%s" % paths.DB)
        return 1
    con = _open()
    try:
        rows = checks(con)
        cov = coverage(con)
    finally:
        con.close()
    print("■ 重音闸（ru 阶段 2）—— 花名册 %d 条" % len(ROSTER))
    for cid, ok, why in rows:
        print("   %s %-5s %s" % ("✅" if ok else "🔴", cid, why))
    rb = roster_check(rows)
    for b in rb:
        print("   🔴🔴 花名册自检：" + b)
    print("   覆盖率两个口径：词元 %s/%s = **%.2f%%**；"
          "而**需要标注的**词元 %s/%s = **%.2f%%**（%s 个本来无需标注）"
          % (format(cov["lemmas_with"], ","), format(cov["lemmas"], ","), cov["pct_all"],
             format(cov["need_with"], ","), format(cov["need"], ","), cov["pct_need"],
             format(cov["not_needed"], ",")))
    red = [r for r in rows if not r[1]]
    print("■ %s（%d/%d）" % ("全绿 ✓" if not red and not rb else "有红",
                            len(rows) - len(red), len(rows)))
    return len(red) + len(rb)


def accept():
    con = _open()
    try:
        cov = coverage(con)
    finally:
        con.close()
    ACCEPT.write_text(json.dumps({"coverage": {
        "pct_all": round(cov["pct_all"], 2), "pct_need": round(cov["pct_need"], 2),
        "lemmas": cov["lemmas"], "need": cov["need"],
    }}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 已接受基线写入 %s：词元 %.2f%% ／ 需标注 %.2f%%"
          % (ACCEPT.name, cov["pct_all"], cov["pct_need"]))
    return 0


def _mutations():
    """(编号, 说明, **允许的连带红**, 在副本上执行的 SQL)。**每条自带前提**（B20）。

    🔴🔴 第三个字段是 2026-10-08 补的，补的理由是**这道闸的报告在撒谎**：
       第一版无条件印「连带红 […]，**已声明**」，而我根本没有声明过任何一条 ——
       「已声明」这三个字是报告自己编出来的。vi 那门同一课写着
       「变异报告要把两种失败分开印」，而**撒谎的报告比没有报告更坏**：
       它让一个没人审过的连带红看起来是审过的。
       ⇒ 连带红必须逐条列出来，**没列的当红处理**。

    🔴🔴 合成行一律**负 id ＋ `«变异»` 词头** —— B20 在 2026-10-07 一天内咬了三次：
       「我造的那一行不会撞」本身就是一个关于现状的假设，而 `наследовать`
       是个真俄语动词、`id=9001` 在阶段 1 之后已经被占掉了。
    """
    return [
        ("T2", "把一行出版值改成过不了判据的串（混进拉丁散文）", {"T4", "T6"},
         ["UPDATE stress SET stressed='abc def' WHERE id=(SELECT MIN(id) FROM stress)"]),
        ("T3", "给一个 entry 造第二行主行", {"T9"},
         ["INSERT INTO stress(id,word_id,entry_id,stressed,variant_seq,is_primary,"
          "src,src_ref) SELECT -1, word_id, entry_id, stressed, 9, 1, src, "
          "src_ref||'#mut' FROM stress WHERE is_primary=1 LIMIT 1"]),
        # 🔴 T3 的另一半方向：**一行主行都没有**。只断言「不许多」的闸，
        #    遇到「全都不是主行」会静默通过（`[[expectation-must-be-declared]]`）。
        ("T3", "把所有 `is_primary` 置 0（一行主行都不剩）", {"T4"},
         ["UPDATE stress SET is_primary=0"]),
        ("T4", "把派生列 `entry.stressed` 全清空（真值还在）", {"T10"},
         ["UPDATE entry SET stressed=NULL"]),
        ("T5", "把一行出版值改成与词头一字不差（没有信息的行）", {"T2", "T4", "T6"},
         ["UPDATE stress SET stressed=(SELECT word FROM dict WHERE id=word_id) "
          "WHERE id=(SELECT MIN(id) FROM stress)"]),
        ("T6", "把一行的组合式重音符换成**预组合**的（`е`＋U+0300 → `ѐ`）", {"T2"},
         ["INSERT INTO stress(id,word_id,entry_id,stressed,variant_seq,is_primary,"
          "src,src_ref) SELECT -2, id, NULL, '«变异»сѐро', 0, 1, "
          "'ru-edition/stressed', 'mut-pre' FROM dict LIMIT 1"]),
        ("T7", "往 `src` 塞一个没登记的值", set(),
         ["UPDATE stress SET src='xx-edition/canonical' "
          "WHERE id=(SELECT MIN(id) FROM stress)"]),
        ("T8", "让 `word_id` 与它 entry 的 `word_id` 不一致", {"T2"},
         ["UPDATE stress SET word_id=(SELECT MIN(id) FROM dict)+1 "
          "WHERE id=(SELECT MIN(id) FROM stress)"]),
        ("T9", "把一个 entry 的 `variant_seq` 从 0 改成 5（序号出洞）", set(),
         ["UPDATE stress SET variant_seq=5 WHERE id=(SELECT MIN(id) FROM stress)"]),
        # 🔴 变异必须动**判据真正读的那个量**。T10 读的是「词元里有多少拿到了重音」，
        #    所以要清掉一批 `entry.stressed` —— 而**不能**全清（那会先把 T4 打红，
        #    两种失败混在一起就分不开了）。按 `word_id` 取模删一半。
        ("T10", "清掉一半词元的 `entry.stressed`（覆盖率跌破基线）", {"T4"},
         ["UPDATE entry SET stressed=NULL WHERE id IN "
          "(SELECT e.id FROM entry e JOIN dict d ON d.id=e.word_id "
          " WHERE d.is_lemma=1 AND e.id%2=0)",
          # 连带把真值也删掉，否则 T4 会先红
          "DELETE FROM stress WHERE entry_id IN (SELECT e.id FROM entry e "
          " JOIN dict d ON d.id=e.word_id WHERE d.is_lemma=1 AND e.id%2=0)"]),
        ("T11", "造一个带重音符的词头（R13 复发）", {"T8"},
         ["INSERT INTO dict(id,word,word_norm,entry_type,is_lemma) "
          "VALUES (-3,'«变异»ко́шка','«变异»кошка','word',1)"]),
    ]


def mutate():
    if not paths.DB.exists():
        print("🔴 库不存在，变异没法做")
        return 1
    if report():
        print("\n🔴 基线就不绿，先修基线（否则分不清是变异还是旧红）")
        return 1
    muts = _mutations()
    print("\n■ 变异验证（%d 条，跑在库的副本上，真库一个字节不动）" % len(muts))
    # 🔴 T1 没有变异档，**显式说**不许沉默跳过：把 `stress` 清空会让 T3/T4/T9/T10
    #    一起红，两种失败混在一起分不开。
    print("   ⚠️ T1    无变异档：清空 `stress` 会让 T3/T4/T9/T10 连带红，分不开")
    real = paths.DB
    fails = []
    for cid, why, also, sqls in muts:
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / real.name
            shutil.copy2(real, cp)
            paths.DB = cp
            try:
                con = sqlite3.connect(cp)
                for s in sqls:
                    con.execute(s)
                con.commit()
                con.close()
                con = _open()
                try:
                    got = {c for c, ok, _ in checks(con) if not ok}
                finally:
                    con.close()
                if cid in got:
                    undecl = sorted(got - {cid} - set(also))
                    if undecl:
                        print("   🔴 %-5s 逮到了，**但还有没声明的连带红 %s** —— "
                              "要么补进声明，要么它是个真问题：%s"
                              % (cid, undecl, why))
                        fails.append(cid)
                    else:
                        extra = sorted(got - {cid})
                        print("   ✅ %-5s %s%s" % (cid, why, "" if not extra else
                                                   "（连带红 %s，已逐条声明）" % extra))
                elif got:
                    print("   🔴 %-5s 红了，但红的是 %s，不是它自己 —— %s"
                          % (cid, sorted(got), why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-5s **一条都没红** —— 判据是假的或变异是空操作：%s"
                          % (cid, why))
                    fails.append(cid)
            finally:
                paths.DB = real
    if report():
        print("\n🔴🔴 反控制失败：真库基线不绿了 —— 副本隔离破了")
        return 1
    print("\n%s" % ("■ 变异验证全过 ✓，反控制：真库基线仍全绿" if not fails
                    else "🔴 %d 条没逮到：%s" % (len(fails), fails)))
    return 1 if fails else 0


def check_brief():
    if not paths.DB.exists():
        return [("T?", "库不存在")]
    con = _open()
    try:
        return [(c, w) for c, ok, w in checks(con) if not ok]
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--accept", action="store_true",
                    help="把覆盖率现状锁成基线（锁数字不锁名字）")
    a = ap.parse_args()
    if a.accept:
        raise SystemExit(accept())
    raise SystemExit(mutate() if a.mutate else (1 if report() else 0))


if __name__ == "__main__":
    main()
