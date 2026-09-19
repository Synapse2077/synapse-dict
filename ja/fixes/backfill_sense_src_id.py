#!/usr/bin/env python3
"""回填 ja/zh 两版 `sense_src.sense_id` —— 证据层 → 出版层的认领。2026-09-18。

═══ 为什么这两版是空的 ═══
`sense_src` 149,410 行里只有 **en-edition 141,773 条**编入了出版层
（阶段 1.5a 建 `sense` 时逐条回填），而 ja/zh 两版 **84,783 / 70,029 条全是 NULL**。
不是漏了一步，是阶段 3a 的 `intake_edition_words` **插入时就写死了 NULL**：

    s.executemany("INSERT INTO sense_src (…, sense_id, …) VALUES (?,NULL,?,…)", srcs)

它在**同一个循环**里同时攒 `srcs` 和 `senses`，两边的下标天然对齐，
所以当时不回填也能把 `sense_gloss` 挂对（它用 `JOIN … ON s.word_id=g.word_id AND s.rank=g.rank`）。
⇒ 代价是证据层与出版层之间**没有桥**，任何要「从证据行找到它出版成哪条义项」的活
（比如阶段 1d 的义项标签）在这两版上都做不了。

═══ 🔴 配对判据从**建库代码**推出来，不是从数据猜的 ═══
`intake_edition_words.py:241-250` 那个循环：

    for k, (g, tg) in enumerate(ss):
        srcs.append((…, "%s:%s:%s:0:0#%d" % (src, w, pos, k), …))   # src_ref 的 #k
        senses.append((wid[w], e, k + 1, …))                        # sense.rank = k+1

⇒ **`(word_id, rank) = (word_id, #k + 1)`**。这与 `sense_gloss` 当时用的是同一个对应，
  所以它本身是可以拿 `sense_gloss.text` 全量反验的 —— 见下面的回核。

🔴 **只取 `#` 后面那一段，不反解析整个 `src_ref`。**
   `build_entry_layer` 文件头记着：反解析那版在词形带冒号时崩，
   **1,866 条只对上 1,091 条，对不上的 775 条不报错、只静默漏修**。
   ⚠️ 这里的前提是量过的：词形含 `#` 的 **0 个**，154,812 条各含且仅含一个 `#`。

═══ ⭐ 全量回核：`sense_src.text` vs `sense_gloss.text`，**逐条比内容** ═══
配对这件事上计数型闸是结构性失明的（`[[primary-key-is-not-enough]]`：
主键保证认领得上，不保证配对对）。所以回核比的是**文本**：

    154,812 条证据行
      ├ 154,777 配上
      │   ├ 150,762  文本完全一致
      │   ├   3,985  文本不同 —— **100% 由两轮已知修复解释**，见下
      │   └      30  该义项没有这个语言的 definition
      └      35 配不上 —— **全部是出版层有意不出版的**
          ├ 30 条 `ONLY_BRACKET` 命中（整条只是【异写列表】，`fix_gloss_residue` 删的）
          └  5 条 文本是空串（回归闸 A2 盯的那一类，本来就不该出版）
    多配 0 条。

🔴 **那 3,985 条差异一条都不是错配，全是 `sense_gloss` 被改过的痕迹** ——
   证据层永不编辑，出版层被修过两轮：

       繁简转换（记账本 ⑦，`fix_traditional_to_simplified`）   3,978 条
       台湾用词（记账本 ⑩，`fix_tw_vocab`）                      7 条

   串起这两个转换器再比，**3,985 / 3,985 ＝ 100.00% 相等，0 条剩余**。
   ⚠️ 两个转换器都 import 生成侧那一份，闸里一个字不重写。

⚠️ **差点在这里栽一跤**：`convert()` 返回的是 `(新文本, 被保护片段数)` **元组**，
   我拿整个元组去比字符串，得到「0% 相等」⇒ 差点据此判定"配对全错"。
   救我的是**两个信号打架**：样本肉眼看就是繁简差异，而数字说全错。
   只信数字就会去"修"一个不存在的问题（`[[measure-landing-not-source]]`：
   新数字先假设我的度量错了）。

跑（在仓库根）：
    python3 -u ja/fixes/backfill_sense_src_id.py
    python3 -u ja/fixes/backfill_sense_src_id.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import collections
import sqlite3

import dbtool
import paths
# 🔴 判据只许一份：两轮修复的转换器都 import 生成侧那一个
from fix_traditional_to_simplified import convert as t2s_convert   # noqa: E402
from fix_tw_vocab import apply_row as tw_apply                     # noqa: E402
from fix_gloss_residue import ONLY_BRACKET                         # noqa: E402

f = lambda n: format(n, ",")

# `(word_id, #k + 1)` —— 见文件头，判据来自 `intake_edition_words.py` 那个循环。
PAIR = """
  SELECT x.id AS src_id, x.src, x.lang, x.text AS src_text, s.id AS sense_id,
         (SELECT g.text FROM sense_gloss g
           WHERE g.sense_id = s.id AND g.lang = x.lang AND g.kind = 'definition') AS gloss_text
  FROM sense_src x
  JOIN sense s ON s.word_id = x.word_id
     AND s.rank = CAST(substr(x.src_ref, instr(x.src_ref, '#') + 1) AS INTEGER) + 1
  WHERE x.src IN ('ja-edition', 'zh-edition') AND x.sense_id IS NULL
"""


def check_shape(con):
    """前提：词形不含 `#`，每条 src_ref 恰好一个 `#`。不成立就别往下走。"""
    bad = []
    if con.execute("SELECT COUNT(*) FROM dict WHERE word LIKE '%#%'").fetchone()[0]:
        bad.append("有词形含 `#`，`substr(…,instr(…,'#'))` 不再安全")
    n = con.execute(
        "SELECT COUNT(*) FROM sense_src WHERE src IN ('ja-edition','zh-edition')"
        " AND length(src_ref)-length(replace(src_ref,'#','')) <> 1").fetchone()[0]
    if n:
        bad.append("%s 条 src_ref 的 `#` 不是恰好一个" % f(n))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = check_shape(con)
    if bad:
        print("🔴 前提不成立，停：")
        for b in bad:
            print("   " + b)
        return

    tot = con.execute("SELECT COUNT(*) FROM sense_src WHERE src IN"
                      " ('ja-edition','zh-edition') AND sense_id IS NULL").fetchone()[0]
    rows = con.execute(PAIR).fetchall()

    # ── 全量回核（非抽样）：文本比对，串起两轮已知修复 ──
    import opencc
    cv = opencc.OpenCC("t2s").convert
    stat = collections.Counter()
    resid = []
    pairs = []
    for src_id, src, lang, src_text, sense_id, gloss_text in rows:
        pairs.append((sense_id, src_id))
        if gloss_text is None:
            stat["该义项没有这个语言的 definition"] += 1
        elif gloss_text == src_text:
            stat["文本完全一致"] += 1
        elif tw_apply(t2s_convert(src_text, cv)[0]) == gloss_text:
            stat["文本不同，由两轮已知修复完全解释（繁简→台湾用词）"] += 1
        else:
            stat["🔴 文本对不上，且解释不了"] += 1
            resid.append((src, src_text, gloss_text))

    dup = [k for k, v in collections.Counter(s for _s, s in pairs).items() if v > 1]
    miss = con.execute(
        "SELECT x.src, x.text FROM sense_src x WHERE x.src IN ('ja-edition','zh-edition')"
        " AND x.sense_id IS NULL AND NOT EXISTS(SELECT 1 FROM sense s"
        "  WHERE s.word_id=x.word_id AND s.rank ="
        "    CAST(substr(x.src_ref, instr(x.src_ref,'#')+1) AS INTEGER)+1)").fetchall()
    con.close()

    print("■ 待回填 %s 条（ja-edition + zh-edition）" % f(tot))
    print("   配上 %s ｜ 配不上 %s ｜ 一个证据行配多个义项 %s"
          % (f(len(rows)), f(len(miss)), f(len(dup))))
    print("\n■ 全量回核：`sense_src.text` vs `sense_gloss.text`（**比内容，不比条数**）")
    for k, v in stat.most_common():
        print("   %-46s %9s" % (k, f(v)))
    if resid:
        print("   —— 解释不了的（**这一栏必须是空的**）——")
        for s, a_, b_ in resid[:10]:
            print("      %s  src=%r\n          glo=%r" % (s, a_[:48], b_[:48]))

    print("\n■ 配不上的 %s 条 —— 出版层**有意不出版**的那些" % f(len(miss)))
    bracket = [t for _s, t in miss if ONLY_BRACKET.match(t)]
    empty = [t for _s, t in miss if not t.strip()]
    print("   %-46s %9s" % ("整条只是【异写列表】（fix_gloss_residue 删的）", f(len(bracket))))
    print("   %-46s %9s" % ("文本是空串（回归闸 A2 盯的那一类）", f(len(empty))))
    other = len(miss) - len(bracket) - len(empty)
    print("   %-46s %9s%s" % ("🔴 其他（说不出理由的）", f(other),
                              "   ← 必须是 0" if other else ""))

    ok = not resid and not dup and other == 0
    print("\n%s 回核结论：%s" % ("✅" if ok else "🔴",
                             "配对可信，可以写" if ok else "**有说不清的，别写**"))
    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return
    if not ok:
        print("🔴 回核没全绿，拒绝写库。")
        return

    # 🔴 判据锚在「**前后不变**」上，不锚在具体数字上。第一版把 141,773 写死在
    #    断言里，**字面量闸当场报警** —— 写死的期望值会过期，过期之后它要么假红、
    #    要么被人调大一次就永远绿了。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    en_before = con.execute("SELECT COUNT(*) FROM sense_src WHERE src='en-edition'"
                            " AND sense_id IS NOT NULL").fetchone()[0]
    dangling = con.execute(
        "SELECT COUNT(*) FROM sense_src x LEFT JOIN sense s ON s.id=x.sense_id"
        " WHERE x.sense_id IS NOT NULL AND s.id IS NULL").fetchone()[0]
    con.close()
    if dangling:
        print("\n⚠️ 顺带清掉 %s 条**悬空认领**（指向已被删除的义项）——"
              " en-edition 的历史遗留，本步的回核逮到的" % f(dangling))

    # 🔴 `expect` 是**增量**不是总数（`dbtool` 文件头）。`sense_src.sense_id` 2026-09-18
    #    刚列进 `TRACK` —— 列进去的第一件事就是它当场拦住了本脚本：清悬空那一步
    #    让这一列 **-1**，而我没声明。**那正是这道闸的用处**，不是它烦人。
    #    ⇒ 净变化 ＝ 新认领 len(pairs) − 清掉的悬空 dangling。幂等重跑时两者都是 0。
    with dbtool.session("ja-backfill-sense-src-id",
                        expect={"sense_src.sense_id": len(pairs) - dangling},
                        invalidates=[]) as s:
        s.executemany("UPDATE sense_src SET sense_id=? WHERE id=?", pairs)
        # ⚠️ **顺带清掉全库唯一一条悬空引用**（`kk-ja:和:character:2:0#0`，
        #    文本是 wikitext 残渣 `===Etymology 4===`）。它是 en-edition 的历史遗留：
        #    阶段 1.5a 认领过，后来那条出版义项被清洗删掉，而引用没跟着清。
        #    🔴 **是本步的写后回核逮到的，不是我去找的** —— 它本来会一直躺着，
        #       因为此前没有任何一条断言问过「认领指向的义项还在不在」。
        #    置 NULL 才是事实：这条证据没有编入出版层。
        s.execute("UPDATE sense_src SET sense_id=NULL WHERE sense_id IS NOT NULL"
                  " AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.id=sense_src.sense_id)")

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n■ 写后回核（全量，非抽样）")
    for name, got, want in [
        ("ja/zh 仍未认领的",
         q("SELECT COUNT(*) FROM sense_src WHERE src IN ('ja-edition','zh-edition')"
           " AND sense_id IS NULL"), len(miss)),
        ("sense_id 指向不存在的义项",
         q("SELECT COUNT(*) FROM sense_src x LEFT JOIN sense s ON s.id=x.sense_id"
           " WHERE x.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        ("认领到了别的词的义项（word_id 对不上）",
         q("SELECT COUNT(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id"
           " WHERE s.word_id <> x.word_id"), 0),
        # 🔴 期望值是**跑之前量的那个数**，不是写死的字面量（字面量闸报过一次）。
        #    ⚠️ 减 1 是那条悬空引用：它属于 en-edition，被上面顺带清掉了。
        ("en-edition 的认领数（本步只许少掉那 1 条悬空的）",
         q("SELECT COUNT(*) FROM sense_src WHERE src='en-edition' AND sense_id IS NOT NULL"),
         en_before - dangling),
    ]:
        print("   %s %-40s %9s（期望 %s）" % ("✅" if got == want else "🔴", name,
                                            f(got), f(want)))
    print("   ⭐ 三版认领率：%s"
          % " ｜ ".join("%s %.1f%%" % (r[0], r[1]) for r in con.execute(
              "SELECT src, 100.0*SUM(sense_id IS NOT NULL)/COUNT(*) FROM sense_src"
              " GROUP BY src ORDER BY src")))
    con.close()


if __name__ == "__main__":
    main()
