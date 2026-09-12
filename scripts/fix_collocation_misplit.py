#!/usr/bin/env python3
"""修 7 条**切反了**的搭配。2026-09-12。

═══ 这 7 条是怎么来的 ═══
豆包的 `col` 字段约定是「本语言在前、中文在后，空格分隔」。它偶尔写反，
或者干脆只给一半。`build_v2/v3_schema.py` 的 `split_colloc()` 切不出本语言时，
按「阶段 0 只搬不改」的边界**原样搬进 `text`、不产生中文 gloss**，并记了账：

    stat["🔴 搭配切不出意语（原样搬，记账）"] += 1
    # 注释原话：「缺陷记账，交阶段 5 搭配层处理」

**阶段 5 从来没处理。** 结果是这 7 条今天还印在页面上，长这样：

    搭配 / 固定短语
      AC米兰 AC Milan              ← 中文当成了意语原文
      书信结尾敬语 非正式信末祝好      ← 整条都是中文，一个法语词都没有

═══ 判据：逐条列出，不写启发式 ═══
只有 7 条，全部人工看过。**不写"含中文就切"这类规则** ——
`Fórmula 1`、`AC Milan` 这种混合串会被误伤，而判据宽一点就多误伤一批
（`[[criteria-narrower-than-you-think]]`）。闸会断言"正好匹配 7 条"，
多一条少一条都红。

═══ 处置原则：宁可缺，不可错 ═══
· **能救出本语言原文的 → 改**（2 条）。中文只在原串里确实有时才补，**不编**。
· **整条都是中文、或整条是一句解释 → 删**（5 条）。
  它们不是搭配，留着就是把错的东西印在页面上；
  而「`pasticci` 的意语说法大概是 `fare pasticci`」是我的猜测，不是数据。
  `[[dict-framework-doc]]`：**错比缺更伤权威。**

用法（仓库根目录）：
    python3 scripts/fix_collocation_misplit.py --all
    python3 scripts/fix_collocation_misplit.py --all --apply
"""
import argparse
import importlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
f = lambda n: format(n, ",")

# (词头, 现在的 text, src) → None 表示删；("新 text", "中文" 或 None) 表示改。
#
# 🔴 **键里必须带 `src`。**第一版只用 (词头, text)，`psicoposturologia` 那条
#    匹配到 **2 行** —— 闸①当场报红，查出来是：
#        id 23214  llm:doubao       无译文   ← 豆包切错的空壳
#        id 23873  kaikki:subentry  it+zh    ← kaikki 的真子条目，原文就是这一整句
#    两行原文一字不差，**该删的只是前者**。没有 src 就分不开，
#    而"随便删一条"会把有译文的那条删掉。
#    ⚠️ 这正是 `[[primary-key-is-not-enough]]` 的形状：
#      键能唯一定位不等于它定位的是我想要的那一条。
PLAN = {
    "it": {
        # 中意写反了：`AC米兰` 是中文，`AC Milan` 才是原文
        ("AC", "AC米兰 AC Milan", "llm:doubao"): ("AC Milan", "AC米兰"),
        # 整条只有中文，救不出意语。`fare pasticci` 是我猜的，不写。
        ("pasticci", "弄出乱子", "llm:doubao"): None,
        # 豆包那条是空壳（无译文），与 kaikki 子条目原文重复 ⇒ 只删豆包这条
        ("psicoposturologia",
         "La psicoposturologia consiste nell'unione di due metodiche",
         "llm:doubao"): None,
    },
    "fr": {
        # 整条都是中文（词头本身就是 `bien à toi`，这条是它的中文解释被塞进了搭配位）
        ("bien à toi", "书信结尾敬语 非正式信末祝好", "llm:doubao"): None,
        ("bien à vous", "书信结尾敬语 正式/正式信末祝好", "llm:doubao"): None,
        # 法语原文是对的，后面跟的 `blah blah blah` 是**英文**释义不是中文。
        # ⇒ 原文留下，中文**不编**（这条就此没有译文，展示层本来就允许 zh 为空）。
        ("patati", "et patati et patata  blah blah blah", "llm:doubao"):
            ("et patati et patata", None),
        # 整条都是中文
        ("Ménilmontant", "梅尼蒙当 巴黎街区", "llm:doubao"): None,
    },
}
LANGS = list(PLAN)


def load(lang):
    """连归一函数一起加载 —— 改了 `text` 就必须同步改 `text_norm`，
    而那个函数只能从本门的 `pipeline/build.py` 拿（各门规则不同，de 还要 ä→ae）。"""
    for m in ("paths", "dbtool", "build"):
        sys.modules.pop(m, None)
    sys.path.insert(0, str(ROOT / lang))
    sys.path.insert(0, str(ROOT / lang / "pipeline"))
    try:
        paths = importlib.import_module("paths")
        dbtool = importlib.import_module("dbtool")
        build = importlib.import_module("build")
    finally:
        sys.path.pop(0)
        sys.path.pop(0)
    assert lang in str(paths.DB), paths.DB
    norm = getattr(build, "unaccent", None) or getattr(build, "norm_%s" % lang)
    return paths, dbtool, norm


def resolve(con, lang):
    """把 (词头, text) 解析成具体行。→ (dels, fixes, adds, misses)"""
    dels, fixes, adds, misses = [], [], [], []
    for (word, text, src), how in PLAN[lang].items():
        rows = con.execute(
            "SELECT c.id FROM collocation c JOIN dict d ON d.id=c.word_id "
            "WHERE d.word=? AND c.text=? AND c.src=?", (word, text, src)).fetchall()
        if len(rows) != 1:
            misses.append((word, text[:32], len(rows)))
            continue
        cid = rows[0][0]
        if how is None:
            dels.append((cid,))
        else:
            new_text, zh = how
            fixes.append((new_text, cid))
            if zh:
                adds.append((cid, "zh", zh, "llm:doubao"))
    return dels, fixes, adds, misses


def run(lang, apply_):
    paths, dbtool, norm = load(lang)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n_before = con.execute("SELECT COUNT(*) FROM collocation").fetchone()[0]
    g_before = con.execute("SELECT COUNT(*) FROM collocation_gloss").fetchone()[0]
    dels, fixes, adds, misses = resolve(con, lang)

    print("\n" + "═" * 62)
    print("══ %s  搭配 %s 条" % (lang, f(n_before)))
    for cid, in dels:
        t = con.execute("SELECT text FROM collocation WHERE id=?", (cid,)).fetchone()[0]
        print("   删  %s" % t)
    for new, cid in fixes:
        t = con.execute("SELECT text FROM collocation WHERE id=?", (cid,)).fetchone()[0]
        print("   改  %-46s → %s" % (t, new))
    for cid, _l, zh, _s in adds:
        print("   补中文  %s" % zh)

    # 🔴 负控必须真的能红：这 7 条**被删掉的那些行本来就没有中文 gloss**，
    #    所以"删了不会孤立 gloss"这条得实际查，不能靠我记得。
    orphan = 0
    for cid, in dels:
        orphan += con.execute(
            "SELECT COUNT(*) FROM collocation_gloss WHERE collocation_id=?", (cid,)).fetchone()[0]
    checks = [
        ("🔴 有条目没在库里精确匹配上（或匹配到多条）", len(misses), 0),
        ("要处理的条数", len(dels) + len(fixes), len(PLAN[lang])),
        ("🔴 要删的行还挂着中文译文（会变孤儿）", orphan, 0),
    ]
    print("\n═══ 闸①：写库之前 ═══")
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-44s %s / %s" % ("✅" if ok else "🔴", name, f(got), f(want)))
    for w, t, n in misses:
        print("      🔴 %-22s %-34s 匹配到 %d 行" % (w, t, n))
    con.close()
    if bad:
        print("\n🔴 闸红，不写。")
        return 1
    if not apply_:
        print("\n(干跑。--apply 才写库)")
        return 0

    expect = {"#collocation": -len(dels)}
    if adds:
        expect["#collocation_gloss"] = len(adds)
    with dbtool.session("colloc-misplit", expect=expect) as s:
        s.executemany("DELETE FROM collocation WHERE id=?", dels)
        # 🔴 **`text` 与 `text_norm` 在同一条 UPDATE 里改。**
        #    第一版只改 `text`，然后在结尾打印一句「接下来必须重跑
        #    build_collocation_search.py」—— 那是**写成文字的约定**，
        #    而 `[[lesson-must-become-mechanism]]` 的账很清楚：
        #    做成机制的全守住了、写成文字的一条没守住。
        #    不同步的话，搜「et patati」会搜不到 —— 而且**一声不吭**。
        s.executemany("UPDATE collocation SET text=?, text_norm=? WHERE id=?",
                      [(t, norm(t), cid) for t, cid in fixes])
        if adds:
            s.executemany("INSERT INTO collocation_gloss (collocation_id,lang,text,src) "
                          "VALUES (?,?,?,?)", adds)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = con.execute
    left = sum(q("SELECT COUNT(*) FROM collocation c JOIN dict d ON d.id=c.word_id "
                 "WHERE d.word=? AND c.text=? AND c.src=?",
                 (w, t, sr)).fetchone()[0] for w, t, sr in PLAN[lang])
    # 🔴 派生值对不对 —— 全表查，不只查改过的那两行：
    #    「改过的行同步了」和「全表都是同步的」是两个问题，后者才是读者的口径
    #    （`[[correct-steps-can-compose-a-hole]]`）。
    stale = sum(1 for t, n in q("SELECT text, text_norm FROM collocation") if norm(t) != n)
    checks = [("原来那 %d 条一条都不剩" % len(PLAN[lang]), left, 0),
              ("总行数少了正好这么多", n_before - q("SELECT COUNT(*) FROM collocation")
               .fetchone()[0], len(dels)),
              ("译文行数多了正好这么多", q("SELECT COUNT(*) FROM collocation_gloss")
               .fetchone()[0] - g_before, len(adds)),
              ("🔴 全表 text_norm 与 text 不同步", stale, 0)]
    print("\n═══ 闸②：写库之后 ═══")
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-44s %s / %s" % ("✅" if ok else "🔴", name, f(got), f(want)))
    con.close()
    print("\n%s %s：删 %d 改 %d" % ("🔴 闸红" if bad else "✅", lang, len(dels), len(fixes)))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=LANGS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not a.lang and not a.all:
        ap.error("要么 --lang <xx>，要么 --all")
    bad = sum(run(l, a.apply) for l in (LANGS if a.all else [a.lang]))
    print("\n%s" % ("🔴 有语种未通过" if bad else "✅ 全部通过"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
