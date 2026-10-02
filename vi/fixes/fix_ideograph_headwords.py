#!/usr/bin/env python3
"""**把纯表意词头从 `dict` 里清出去** —— 用户 2026-09-28 的决定被破了。2026-10-01。

═══ 它是怎么被逮到的 ═══
阶段 6 的关系层闸 **R19**（「关系目标不是纯汉字/喃字，那必然是死链」）报红 23 条。
顺着那 23 条查下去，是**一个根因、三个后果**：

根因：`is_ideograph` 当时有**两份实现** —— `han_sources.py` 那份 2026-09-28 加过
      扩展 H 的码位兜底（Python 的 `unicodedata` 是 14.0，不认识 Unicode 15.0 的扩展 H），
      而 **`criteria.py` 那份没加**。收词、S3 收割、骨架闸 S6 全都用的是没兜底那份。

后果①  `dict` 里躺着 **155 个纯表意词形**（139 个扩展 H 喃字 ＋ 16 个带汉字圈标点/IDS 的）
后果②  汉字层**唯一带权威标注的源 S3**（`chữ Hán/Nôm form of X`）跳过了这批词头 ⇒
       52 个喃字连「该喂进汉字层」这一半也没做成
后果③  🔴🔴 骨架闸 **S6 明写「表意文字词头一条都不许在 dict 里」而它报 0** ——
       断言和被断言的东西用同一个坏判据 ⇒ **双方一致报全绿**。
       与 ko 那天「词性表按 `pos_raw` 写而展示层读 `pos`」完全同形。

═══ 修的顺序，以及为什么是这个顺序 ═══
① 判据合并成一份（已做：兜底搬进 `criteria.py`，`han_sources` 改为 import）
② **先重跑 `build_han_layer.py`** —— 把这批喃字喂进汉字层（用户决定的另一半）。
   实测 S3 对数 10,534 → 11,560，`nom + src-label-v1` 3,952 → 4,056（**74 对从
   最弱的 `codepoint-v1` 升级成权威标注**），这是 W1 残留在缩小。
③ 再跑本脚本把那 155 行从 `dict` 清出去并级联。
   🔴 顺序反了也能跑，但②在前意味着**信息先落地再删载体**，中间任何一步失败
   都不会出现「载体删了而信息没搬」的状态（`[[prefer-reversible-designs]]`）。

═══ 删掉会丢什么（逐项量过，不是估的）═══
    entry 170 ／ sense 8 ／ sense_src 262 ／ sense_gloss 8 ／ example 40 ／ sense_relation 278
    pronunciation 0 ／ han_spelling 0 ／ nom_spelling 0 ／ audio 0 ／ noun_classifier 0
    另有 12 行 `sense_relation.target_id` 指向它们 ⇒ 置 NULL（目标文本留着，只是不做链接）

那 8 条可出版释义**逐条读过**（这是「会不会丢内容」的唯一验法）：
    𱎀 → `𱎀：字喃；讀法：tuyết`       ← 元描述，不是释义
    𱺵 → `𱺵：字喃；讀法：là`           ← 同上
    ⿵門⿱𭁈𰀁 → `:\n国语字：cửa`        ← 同上，而且词头是个 IDS 构造式
    𱦉 → `Biến thể của 瀝.`            ← 指针
    𱜢 → `which` / `not`               ← 真释义，但 `𱜢` 是 `nào` 的喃字，
    𱥯 → `some` / `and; with`             国语字词形自己在库里，读者不会因此少看见东西
⇒ **8 条里 5 条压根不是释义**，剩 3 条的内容读者在国语字词条上看得见。
  **不是「丢内容」，是「内容搬回它该在的那一层」**。
   `[[dont-say-source-lacks-what-we-skipped]]`：这是我们有意不收，不是源头没有。

用法：
    python3 vi/fixes/fix_ideograph_headwords.py            # 干跑
    python3 vi/fixes/fix_ideograph_headwords.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool                                                     # noqa: E402
import paths                                                      # noqa: E402
from criteria import is_han_headword                                # noqa: E402

F = lambda n: format(n, ",")                                      # noqa: E731

# 级联顺序：先删引用方，最后删 `dict`
CASCADE = [
    ("example_gloss", "example_id IN (SELECT id FROM example WHERE word_id IN (%s))"),
    ("example", "word_id IN (%s)"),
    ("sense_gloss", "sense_id IN (SELECT id FROM sense WHERE word_id IN (%s))"),
    ("sense_tag", "sense_id IN (SELECT id FROM sense WHERE word_id IN (%s))"),
    ("sense_src", "word_id IN (%s)"),
    ("sense", "word_id IN (%s)"),
    ("sense_relation", "word_id IN (%s)"),
    ("noun_classifier", "word_id IN (%s) OR classifier_id IN (%s)"),
    ("pronunciation", "word_id IN (%s)"),
    ("han_spelling", "word_id IN (%s)"),
    ("nom_spelling", "word_id IN (%s)"),
    ("audio", "word_id IN (%s)"),
    ("etymology_gloss", "etymology_id IN (SELECT id FROM etymology WHERE word_id IN (%s))"),
    ("etymology", "word_id IN (%s)"),
    ("entry", "word_id IN (%s)"),
    ("dict", "id IN (%s)"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = [(i, w) for i, w in con.execute("SELECT id, word FROM dict")
           if is_han_headword(w)]
    if not bad:
        print("■ `dict` 里没有纯表意词头 ✓（本脚本无事可做）")
        con.close()
        return
    ids = ",".join(str(i) for i, _w in bad)
    print("■ `dict` 里的纯表意词头 **%s 个**（用户 2026-09-28 定：不进 dict，只喂汉字层）"
          % F(len(bad)))
    print("   例：%s" % "、".join(w for _i, w in bad[:16]))

    plan = []
    for tbl, cond in CASCADE:
        sql = cond % tuple([ids] * cond.count("%s"))
        n = con.execute("SELECT COUNT(*) FROM %s WHERE %s" % (tbl, sql)).fetchone()[0]
        plan.append((tbl, sql, n))
    tgt = con.execute("SELECT COUNT(*) FROM sense_relation WHERE target_id IN (%s)"
                      % ids).fetchone()[0]
    print("\n■ 级联（逐表量过，不是估的）")
    for tbl, _s, n in plan:
        print("   %-18s %6s 行" % (tbl, F(n)))
    print("   %-18s %6s 行 ⇒ **置 NULL**（目标文本留着，只是不做链接）"
          % ("rel.target_id", F(tgt)))

    lost = con.execute(
        "SELECT COUNT(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
        "WHERE s.word_id IN (%s) AND s.hidden=0" % ids).fetchone()[0]
    print("\n■ 会随之消失的可出版释义：**%s 条**（逐条读过，见本文件头）" % F(lost))
    con.close()

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    expect = {"__rows__": -len(bad)}
    for tbl, _s, n in plan:
        if tbl == "dict" or not n:
            continue
        expect["#" + tbl] = -n
    # 被删的行上那些列的非空计数也要跟着声明，否则闸门报「未声明的列变了」
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    for col in ("word_norm", "entry_type", "is_lemma", "pos", "syllables"):
        n = con.execute("SELECT COUNT(*) FROM dict WHERE id IN (%s) AND %s IS NOT NULL"
                        % (ids, col)).fetchone()[0]
        if n:
            expect[col] = -n
    for tbl, cols in (("entry", ("pos", "etym_no")),
                      ("pronunciation", ("ipa", "dialect")),
                      ("han_spelling", ("han", "rule_ver")),
                      ("nom_spelling", ("nom", "rule_ver")),
                      ("noun_classifier", ("classifier",)),
                      ("audio", ("commons_key",))):
        for col in cols:
            n = con.execute(
                "SELECT COUNT(*) FROM %s WHERE word_id IN (%s) AND %s IS NOT NULL"
                % (tbl, ids, col)).fetchone()[0]
            if n:
                expect["%s.%s" % (tbl, col)] = -n
    con.close()

    with dbtool.session(
            "fix-vi-ideograph-headwords",
            expect=expect,
            invalidates=["`dict` 少了 %s 个词形 ⇒ **所有按词元算的覆盖率分母变小**，"
                         "每一道读者口径的闸都要重跑（骨架/汉字/音标/义项/例句/关系/录音）"
                         % F(len(bad))]) as s:
        # 🔴 先把指向它们的外键置 NULL，再删 —— 反过来会留下指向不存在行的 target_id
        s.execute("UPDATE sense_relation SET target_id=NULL WHERE target_id IN (%s)" % ids)
        for tbl, sql, n in plan:
            if not n and tbl != "dict":
                continue
            s.execute("DELETE FROM %s WHERE %s" % (tbl, sql))

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = sum(1 for (w,) in con.execute("SELECT word FROM dict") if is_han_headword(w))
    checks = [
        ("🔴 dict 里还剩几个纯表意词头", left, 0),
        ("没有 entry 指向不存在的 dict",
         con.execute("SELECT COUNT(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
                     "WHERE d.id IS NULL").fetchone()[0], 0),
        ("没有 sense 指向不存在的 dict",
         con.execute("SELECT COUNT(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id "
                     "WHERE d.id IS NULL").fetchone()[0], 0),
        ("没有 sense_gloss 指向不存在的 sense",
         con.execute("SELECT COUNT(*) FROM sense_gloss g LEFT JOIN sense s "
                     "ON s.id=g.sense_id WHERE s.id IS NULL").fetchone()[0], 0),
        ("没有 example 指向不存在的 dict",
         con.execute("SELECT COUNT(*) FROM example e LEFT JOIN dict d ON d.id=e.word_id "
                     "WHERE d.id IS NULL").fetchone()[0], 0),
        ("没有 example_gloss 指向不存在的 example",
         con.execute("SELECT COUNT(*) FROM example_gloss g LEFT JOIN example e "
                     "ON e.id=g.example_id WHERE e.id IS NULL").fetchone()[0], 0),
        ("没有 sense_relation.target_id 指向不存在的 dict",
         con.execute("SELECT COUNT(*) FROM sense_relation r LEFT JOIN dict d "
                     "ON d.id=r.target_id WHERE r.target_id IS NOT NULL "
                     "AND d.id IS NULL").fetchone()[0], 0),
    ]
    for name, got, want in checks:
        print("   %s %-42s %s（期望 %s）"
              % ("✅" if got == want else "🔴", name, F(got), F(want)))
    con.close()
    if any(g != w for _n, g, w in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
