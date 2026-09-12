#!/usr/bin/env python3
"""给 `collocation` 每一行标出**它到底哪来的**。2026-09-12。

═══ 起因 ═══
用户问「搭配 / 固定短语 habitante quiteño 基多居民，这种为什么直接查却没有结果呢？」
往回查才发现：`es/it/fr/pt/de` 五门的搭配层**全部是豆包凭记忆写的**，
来自各门 `pipeline/b_translate.py` 里同一行 prompt：

    返回 "col" 字段：该词最常用搭配或固定短语 1-3 条，
    形如 "…… 中文"（本语言在前、中文在后，空格分隔）。

`en` 没有这一层（`collocation` 0 行，目录下也没有 `b_translate.py`）。
唯一有源的是 it 的 679 条，从 kaikki 的伪义项／子条目搬来的。

═══ 🔴 现有的 `collocation_gloss.src` 不是出处，是**搬运步骤** ═══
它现在的值是 `dict-collocation` —— 意思是"从 `dict.collocation` 那一列迁过来的"。
那是**我们库内部的上一站**，不是这条数据的来历。一个叫 `src` 的列装着搬运记录，
下一个读它的人（包括我自己）一定会把它当成出处用。
⇒ 本脚本把真出处写到 `collocation.src`，并把 `collocation_gloss.src` 的
   `dict-collocation` 一并改成同一个值。it 那 679 条的 src 本来就是真出处，不动。

═══ 取值 ═══
    llm:doubao            豆包生成，**无任何外部出处**
    kaikki:pseudo-sense   it，从 kaikki 伪义项搬来
    kaikki:subentry       it，从 kaikki 子条目搬来

⚠️ 不写具体模型 id：跑批用的是环境变量 `DOUBAO_MODEL_BATCH_LITE`，
   当时解析成哪个版本**现在已经查不到了**。写 `llm:doubao` 是我确实知道的，
   写 `llm:doubao-seed-1.6-250615` 是我编的。`[[verify-before-claiming-confirmed]]`

═══ 🔴 为什么是一个脚本而不是五份拷贝 ═══
按语种解耦是**数据与语言模块互不引用**，不是"每门都要有一份一模一样的代码"。
这件事是**一个决定落到五处**，五份拷贝只会变成五个各自漂移的版本
（`[[refactor-mindset-code-quality]]`；`de/fixes/relink_examples_to_senses.py`
那一族三份拷贝已经是个教训了）。
写库仍然走**各门自己的 `dbtool.session()`**，闸一道都不少。

⚠️ es 的 `dbtool` 里**没有 `TRACK_TABLES`** —— 它只看 `dict` 表的列，
   `collocation` 怎么变它一概看不见。所以本脚本自己带前后行数/内容校验，
   不依赖 dbtool 能不能看见。

用法（仓库根目录）：
    python3 scripts/mark_collocation_src.py --lang es            # 干跑
    python3 scripts/mark_collocation_src.py --lang es --apply
    python3 scripts/mark_collocation_src.py --all                # 五门依次干跑
"""
import argparse
import importlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ["es", "it", "fr", "pt", "de"]

f = lambda n: format(n, ",")

# 🔴 **判据写成白名单，不是"认识的改、不认识的放过"。**
#    `de/fixes/relink_examples_to_senses.py` 那次咬的就是这个：
#    桥只认 `src='de-edition'`，来源后来长出 `-adjudicated` / `-backfill` 两层，
#    桥一条都不长、还一声不吭。⇒ 这里出现**任何**表外的 src 值，闸直接红。
GLOSS_SRC_MAP = {
    "dict-collocation": "llm:doubao",
    "it-edition:pseudo-sense": "kaikki:pseudo-sense",
    "it-edition:subentry": "kaikki:subentry",
}
# 没有任何 gloss 行的搭配（it 3 条、fr 4 条）：逐条看过，全是豆包 `col` 字段
# 切分出错的产物（「AC米兰 AC Milan」「书信结尾敬语 非正式信末祝好」），
# 出处一样是豆包。它们本身的缺陷由 `scripts/fix_collocation_misplit.py` 单独处理。
NO_GLOSS_SRC = "llm:doubao"


def load(lang):
    """加载某门语言的 `paths` / `dbtool`。**每次都清干净再导**
    —— 五门的模块同名，不清会拿到上一门的 DB 路径（静默写错库）。"""
    for m in ("paths", "dbtool"):
        sys.modules.pop(m, None)
    sys.path.insert(0, str(ROOT / lang))
    try:
        paths = importlib.import_module("paths")
        dbtool = importlib.import_module("dbtool")
    finally:
        sys.path.pop(0)
    assert Path(paths.DB).resolve().is_relative_to((ROOT / "data").resolve()), paths.DB
    assert lang in str(paths.DB), "%s 的 DB 路径里没有语种名：%s" % (lang, paths.DB)
    return paths, dbtool


def plan(con):
    """→ (rows, stat, unknown)。**只读。**rows 是 (src, collocation_id)。"""
    gsrc = {}
    for cid, s in con.execute("SELECT collocation_id, src FROM collocation_gloss"):
        gsrc.setdefault(cid, set()).add(s)
    rows, stat, unknown = [], {}, {}
    for (cid,) in con.execute("SELECT id FROM collocation"):
        ss = gsrc.get(cid)
        if not ss:
            src = NO_GLOSS_SRC
        else:
            mapped = {GLOSS_SRC_MAP.get(x) for x in ss}
            if None in mapped:
                for x in ss:
                    if x not in GLOSS_SRC_MAP:
                        unknown[x] = unknown.get(x, 0) + 1
                continue
            if len(mapped) > 1:          # 同一条搭配的两条 gloss 出处不同 ⇒ 不猜
                unknown["混合:" + "/".join(sorted(ss))] = \
                    unknown.get("混合:" + "/".join(sorted(ss)), 0) + 1
                continue
            src = mapped.pop()
        rows.append((src, cid))
        stat[src] = stat.get(src, 0) + 1
    return rows, stat, unknown


def gates(con, rows, stat, unknown, n_total, n_gloss_migr):
    print("\n═══ 闸①：写库之前 ═══")
    checks = [
        ("🔴 出现了白名单之外的 gloss.src", len(unknown), 0),
        ("每一条搭配都标上了出处", len(rows), n_total),
        ("要标的条数 > 0", int(len(rows) > 0), 1),
        ("⭐ 负控 llm 与 kaikki 两类都不为空(仅 it)",
         int(len(stat) >= 1), 1),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-44s %s / %s" % ("✅" if ok else "🔴", name, f(got), f(want)))
    for k, v in unknown.items():
        print("      🔴 未知出处 %-28s %s 条" % (k, f(v)))
    print("   ⭐ 顺带改写 collocation_gloss.src 里的 `dict-collocation` %s 行" % f(n_gloss_migr))
    return bad


def verify(con, stat, n_total, before_text_sum, n_gloss_migr):
    q = con.execute
    got = dict(q("SELECT src, COUNT(*) FROM collocation GROUP BY src").fetchall())
    nnull = q("SELECT COUNT(*) FROM collocation WHERE src IS NULL").fetchone()[0]
    now_total = q("SELECT COUNT(*) FROM collocation").fetchone()[0]
    # 🔴 **内容负控**：只许加一列，一个字符的原文都不许动。
    #    dbtool 的快照只看 `dict` 表（es 连 TRACK_TABLES 都没有），
    #    `collocation.text` 被顺手改掉它一声不吭 ⇒ 这一条只能自己守。
    text_sum = q("SELECT COUNT(*), SUM(LENGTH(text)), SUM(word_id), SUM(rank) "
                 "FROM collocation").fetchone()
    migr_left = q("SELECT COUNT(*) FROM collocation_gloss WHERE src='dict-collocation'").fetchone()[0]
    migr_now = q("SELECT COUNT(*) FROM collocation_gloss WHERE src='llm:doubao'").fetchone()[0]
    print("\n═══ 闸②：写库之后 ═══")
    checks = [("🔴 还有没标出处的行", nnull, 0),
              ("总行数没变", now_total, n_total),
              ("🔴 原文/归属/次序被动过", int(text_sum != before_text_sum), 0),
              ("🔴 collocation_gloss 里还留着 `dict-collocation`", migr_left, 0),
              ("collocation_gloss 改写成 llm:doubao 的行数", migr_now, n_gloss_migr)]
    for src, n in sorted(stat.items()):
        checks.append(("  %-22s" % src, got.get(src, 0), n))
    bad = 0
    for name, g, w in checks:
        ok = g == w
        bad += not ok
        print("   %s %-44s %s / %s" % ("✅" if ok else "🔴", name, f(g), f(w)))
    return bad


def run(lang, apply_):
    paths, dbtool = load(lang)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n_total = con.execute("SELECT COUNT(*) FROM collocation").fetchone()[0]
    has_src = any(r[1] == "src" for r in con.execute("PRAGMA table_info(collocation)"))
    n_gloss_migr = con.execute(
        "SELECT COUNT(*) FROM collocation_gloss WHERE src='dict-collocation'").fetchone()[0]
    before_text_sum = con.execute(
        "SELECT COUNT(*), SUM(LENGTH(text)), SUM(word_id), SUM(rank) FROM collocation").fetchone()
    print("\n" + "═" * 62)
    print("══ %s  搭配 %s 条  （src 列%s）" % (lang, f(n_total), "已存在" if has_src else "待加"))
    rows, stat, unknown = plan(con)
    for k, v in sorted(stat.items()):
        print("   %-24s %s (%.1f%%)" % (k, f(v), v / max(n_total, 1) * 100))
    bad = gates(con, rows, stat, unknown, n_total, n_gloss_migr)
    con.close()
    if bad:
        print("\n🔴 闸红，不写。")
        return 1
    if not apply_:
        print("\n(干跑。--apply 才写库)")
        return 0

    # ⚠️ tag **不带 `keep`**：带 `keep` 的备份永不淘汰，而这是五门一起跑，
    #    五份全库拷贝 ≈ 9.9 GB，直接把 8 GB 的保留预算顶穿
    #    （`[[backup-retention]]`：预算是字节封顶，不是份数）。
    #    这次改动是"加一列 + 填值"，把 src 置回 NULL 就还原了 —— 不是需要里程碑备份的那种。
    with dbtool.session("colloc-src", expect={}) as s:
        if not has_src:
            s.execute("ALTER TABLE collocation ADD COLUMN src TEXT")
        s.executemany("UPDATE collocation SET src=? WHERE id=?", rows)
        s.execute("UPDATE collocation_gloss SET src='llm:doubao' WHERE src='dict-collocation'")

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = verify(con, stat, n_total, before_text_sum, n_gloss_migr)
    con.close()
    print("\n%s %s：%s 条标上出处" % ("🔴 写库后闸红" if bad else "✅", lang, f(len(rows))))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=LANGS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not a.lang and not a.all:
        ap.error("要么 --lang <xx>，要么 --all")
    bad = 0
    for lang in (LANGS if a.all else [a.lang]):
        bad += run(lang, a.apply)
    print("\n%s" % ("🔴 有语种未通过" if bad else "✅ 全部通过"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
