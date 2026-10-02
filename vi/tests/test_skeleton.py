#!/usr/bin/env python3
"""**骨架闸（vi）** —— 阶段 1 建出来的 `dict` / `entry` 还对不对。2026-09-28。

═══ 为什么它要单独存在 ═══
阶段 1 的 16 条回核写在 `build.py` / `build_entry_layer.py` 的 `--apply` 分支里。
那意味着**它们只在建库那一刻跑过一次**，之后谁改坏了库都没人说话。

`[[lesson-must-become-mechanism]]` 那条教训的第二半正是这个形状：
**「存在／有入口／覆盖这门语言／真被跑」是四道独立关卡。**
写在建库脚本里的检查连第一关都只过了一半 —— 它存在，但**再也不会被跑第二遍**。

⇒ 本文件把那些判据搬成可重跑的闸，并登记进 `vi/gates.py`，
  让「动了 dict 或 entry」这件事自动把它标成过期。

═══ 🔴 判据一律 import，不在这儿重写 ═══
`criteria.py` 是收词判据唯一的家，`build_entry_layer.POS_DOMAIN` 是词性值域唯一的家。
ko 建外锚闸时发现同一判据散在三个文件里（当时三份一样，但三份一定会漂）——
更狠的一次是**我自己重写了收割器的判据**，同一道闸里判据写错两次、方向相反
（例句太宽报 3 万假缺、读音太细报 7,163 假缺）。

═══ 🔴🔴 其中一条**恒绿**，已登记 ═══
`S2 src_ref 唯一` 注入不了变异 —— DDL 上有 `UNIQUE(src_ref)`，SQLite 直接抛。
它只在有人改掉 DDL 时才会说话。**留着，但不假装它在干活**：
`--mutate` 会把它单列出来，而不是混在「全过」里
（`[[permanently-red-gate-masks-real-reds]]` 的镜像 —— 恒绿的信号量同样是零）。

用法：
    python3 vi/tests/test_skeleton.py
    python3 vi/tests/test_skeleton.py --mutate    # 变异验证：永远通过的检查等于没检查
"""
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                             # noqa: E402
from criteria import is_han_headword, norm_vi            # noqa: E402
from build_entry_layer import POS_DOMAIN                 # noqa: E402

_DOM = ",".join("'%s'" % p for p in sorted(POS_DOMAIN))


# ── 检查表。每条 → (编号, 名字, 取数函数, 期望值) ─────────────────────────
def _han_in_dict(c):
    return sum(1 for (w,) in c.execute("SELECT word FROM dict") if is_han_headword(w))


def _norm_mismatch(c):
    return sum(1 for w, n in c.execute("SELECT word, word_norm FROM dict")
               if norm_vi(w) != n)


def _pos_seg_bad(c):
    """🔴 **读者口径的一条**：展示层读 `dict.pos` 要 `split('/')`。

    ko 的 K31：`dict.pos` 长码＋斜杠、映射表只维护 `entry.pos` 短码 ⇒
    **两边各查各的、一致报全绿，而每个徽标都是空的**。
    ⇒ 闸至少要有一条查「读者真正读的那一列」。
    """
    return sum(1 for (p,) in c.execute("SELECT DISTINCT pos FROM dict WHERE pos IS NOT NULL")
               if any(x not in POS_DOMAIN for x in p.split("/")))


CHECKS = [
    ("S1", "dict 非空", lambda c: c.execute("SELECT COUNT(*) FROM dict").fetchone()[0] > 0, True),
    ("S2", "src_ref 唯一", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT src_ref FROM entry GROUP BY src_ref HAVING COUNT(*)>1)"
    ).fetchone()[0], 0),
    ("S3", "word 唯一", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT word FROM dict GROUP BY word HAVING COUNT(*)>1)"
    ).fetchone()[0], 0),
    ("S4", "word_norm 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM dict WHERE TRIM(COALESCE(word_norm,''))=''").fetchone()[0], 0),
    ("S5", "word_norm 与 criteria.norm_vi 逐行一致", _norm_mismatch, 0),
    ("S6", "🔴 表意文字词头一条都不许在 dict 里（用户 2026-09-28 定）", _han_in_dict, 0),
    ("S7", "syllables ≥ 1", lambda c: c.execute(
        "SELECT COUNT(*) FROM dict WHERE syllables IS NULL OR syllables < 1").fetchone()[0], 0),
    ("S8", "entry_type 在值域内", lambda c: c.execute(
        "SELECT COUNT(*) FROM dict WHERE entry_type NOT IN "
        "('word','phrase','proverb','bound_morpheme','letter')").fetchone()[0], 0),
    ("S9", "entry.pos 在值域内", lambda c: c.execute(
        "SELECT COUNT(*) FROM entry WHERE pos NOT IN (%s)" % _DOM).fetchone()[0], 0),
    ("S10", "🔴 dict.pos 每个斜杠段都在值域内（**读者口径**）", _pos_seg_bad, 0),
    ("S11", "每条 entry 都挂得上 dict", lambda c: c.execute(
        "SELECT COUNT(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
        "WHERE d.id IS NULL").fetchone()[0], 0),
    ("S12", "没有 entry 的词形（＝搜得到点进去没词条）", lambda c: c.execute(
        "SELECT COUNT(*) FROM dict d LEFT JOIN entry e ON e.word_id=d.id "
        "WHERE e.id IS NULL").fetchone()[0], 0),
    # 🔴 **这条断言 2026-10-02 换了标的，不是放宽。**
    #    原来写的是「阶段 1 一列都不填 ⇒ 期望 0」—— 那是阶段 1 的现状，
    #    阶段 7a 一填就必然红（`[[fix-regression-and-gate]]`：旧闸红多半是断言过期）。
    #    但**不能就这么删掉它**（`[[gate-registers-status-quo-as-spec]]`）：
    #    它原本守的是「一个字段一个写入方」，那条意图现在有更准的说法 ——
    #    **`etym_type` 的信号只有 en 版有**（vi/zh 版实测 0 条 `etymology_templates`）
    #    ⇒ 它只许出现在 en 版建的 entry 上。
    #    ⭐ 换标的的当天这条就逮到一个真的：收割器第一版按 (词形, 词源号) 写，
    #      3 行落到了 vi/zh 版建的 entry 上 —— 两版的词源号都从 0 起编，
    #      **同号不等于同词源**。
    ("S13", "🔴 entry.etym_type 只出现在 en 版建的 entry 上（信号只有 en 版有）",
     lambda c: c.execute(
         "SELECT COUNT(*) FROM entry WHERE etym_type IS NOT NULL AND src<>'en-edition'"
     ).fetchone()[0], 0),
    ("S14", "freq_zipf 阶段 1 一列都不填", lambda c: c.execute(
        "SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL").fetchone()[0], 0),
]

# 🔴🔴 **花名册。别拿「编号连不连续」推。**
#    ko 实测：第一版 P0 写「编号从 1 起连续」，变异当场证明它**逮不到删掉最后一条**——
#    删掉最后一条之后上界跟着降，缺口自己消失了。而最后一条恰恰最容易被手滑删掉。
ROSTER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10",
          "S11", "S12", "S13", "S14")

# 注入不了变异的检查：**必须在这儿逐条说明为什么**，否则 `--mutate` 会把它当漏网的。
UNMUTABLE = {
    "S2": "DDL 上有 `UNIQUE(src_ref)`，SQLite 直接抛 IntegrityError ⇒ 注不进去。"
          "它是 DDL 之外的第二道，只在有人改掉 DDL 时才说话。",
    "S1": "「dict 非空」要变异就得清库，代价与收益不成比例。"
          "它的价值是**拦住「库是空的而所有 0 值检查全绿」**这种假通过。",
}


def roster_check():
    have = tuple(c[0] for c in CHECKS)
    # 🔴 比集合不比元组：顺序没有语义（见 test_pron_layer 里同一处的注释）
    if set(have) == set(ROSTER):
        return []
    return ["检查表与花名册对不上：少了 %s，多了 %s"
            % (sorted(set(ROSTER) - set(have)) or "无",
               sorted(set(have) - set(ROSTER)) or "无")]


def run(con):
    """→ [(编号, 说明)]，空 ＝ 全绿。"""
    red = [("S0", b) for b in roster_check()]
    for cid, name, fn, want in CHECKS:
        try:
            got = fn(con)
        except sqlite3.Error as e:
            red.append((cid, "%s —— 查不了：%s" % (name, e)))
            continue
        if got != want:
            red.append((cid, "%s：得到 %s，期望 %s" % (name, got, want)))
    return red


# ── 变异验证 ────────────────────────────────────────────────────────────
# 🔴🔴 **锚一律钉常量，别锚在会变的行文上。** 一天内四条变异静默失效过：
#    `replace` 空操作、**什么都没注入而检查「通过」**。
#    这里注入的是 SQL，且每条都**先验证它真的改了行数**（`changes()`），
#    改了 0 行就当场判这条变异自己坏了。
#
# 每条是 (目标检查, 描述, SQL, **预期的连带**)。
# 🔴 第四项不是为了让变异好过 —— 恰恰相反。第一版要求「只许打中自己那一条」，
#    4 条变异因为连带而判红。查下来**连带是对的**：
#    往 `dict` 插一行新词形，它天然还没有 entry ⇒ S12 必然跟着红。
#    ⚠️ 这时候有两条路：把判据放宽成「打中就算」，或者**把连带逐条声明出来**。
#    放宽 ＝ 从此再也发现不了真正的误伤（`[[proxy-metric-gets-optimized]]`：
#    判据写成目的的可观测代理，它就优化代理）。
#    ⇒ 选后者：**没声明的连带一律判红**，声明了的要写清为什么它是必然的。
MUTATIONS = [
    ("S3", "复制一行造成 word 重复",
     "INSERT INTO dict(word,word_norm,pos,is_lemma,entry_type,syllables) "
     "SELECT word||'',word_norm,pos,is_lemma,'phrase',syllables FROM dict LIMIT 1",
     {"S12": "新插的 dict 行天然没有 entry"}),
    ("S4", "把一行的 word_norm 清空",
     "UPDATE dict SET word_norm='' WHERE id=(SELECT MIN(id) FROM dict)",
     {"S5": "空串当然也不等于 norm_vi(word)"}),
    ("S5", "把 word_norm 改成**去掉声调**的（这正是 vi 最怕的那种改动）",
     "UPDATE dict SET word_norm='ma' WHERE id=(SELECT MIN(id) FROM dict)", {}),
    ("S6", "注入一个表意文字词头 `學生`",
     "INSERT INTO dict(word,word_norm,pos,is_lemma,entry_type,syllables) "
     "VALUES('學生','學生','noun',1,'word',1)",
     {"S12": "新插的 dict 行天然没有 entry"}),
    ("S7", "把一行 syllables 改成 0",
     "UPDATE dict SET syllables=0 WHERE id=(SELECT MIN(id) FROM dict)", {}),
    ("S8", "注入一个不在值域里的 entry_type（`han_form`）",
     "INSERT INTO dict(word,word_norm,pos,is_lemma,entry_type,syllables) "
     "VALUES('zzq-mut','zzq-mut','noun',1,'han_form',1)",
     {"S12": "新插的 dict 行天然没有 entry"}),
    ("S9", "entry.pos 写成 ko 那套短码 `n`",
     "UPDATE entry SET pos='n' WHERE id=(SELECT MIN(id) FROM entry)", {}),
    ("S10", "🔴 K31 原形：往 dict.pos 塞一个短码段 `noun/n`",
     "UPDATE dict SET pos='noun/n' WHERE id=(SELECT MIN(id) FROM dict)", {}),
    ("S11", "让一条 entry 指向不存在的 dict",
     "UPDATE entry SET word_id=99999999 WHERE id=(SELECT MIN(id) FROM entry)", {}),
    ("S12", "删掉某个词形的全部 entry",
     "DELETE FROM entry WHERE word_id=(SELECT MIN(word_id) FROM entry)", {}),
    ("S13", "🔴 给 vi 版建的 entry 填 etym_type（信号只有 en 版有）",
     "UPDATE entry SET etym_type='sino_vietnamese' "
     "WHERE id=(SELECT MIN(id) FROM entry WHERE src='vi-edition')", {}),
    ("S14", "偷偷填一列 freq_zipf",
     "UPDATE dict SET freq_zipf=3.5 WHERE id=(SELECT MIN(id) FROM dict)", {}),
]


def mutate():
    """每条检查注入一个真缺陷，它必须**且只**打中自己那一条。"""
    con = sqlite3.connect(paths.DB)
    base = run(con)
    if base:
        print("🔴 基线就不绿，变异验证没有意义：")
        for c, w in base:
            print("   %s %s" % (c, w))
        con.close()
        return False
    ok = True
    covered = set()
    print("═══ 变异验证：%d 条注入 ═══" % len(MUTATIONS))
    for cid, desc, sql, also in MUTATIONS:
        con.execute("SAVEPOINT m")
        con.execute(sql)
        changed = con.execute("SELECT changes()").fetchone()[0]
        red = run(con)
        hit = set(c for c, _ in red)
        undeclared = hit - {cid} - set(also)
        # 🔴 三个条件缺一不可：
        #    ① 变异**真的改了行**（锚没失效）② 目标检查红了 ③ 没有**未声明**的连带
        good = changed > 0 and cid in hit and not undeclared
        ok &= good
        covered.add(cid)
        note = ""
        if changed == 0:
            note = "  🔴🔴 **这条变异什么都没改** —— 变异自己坏了（锚失效）"
        elif cid not in hit:
            note = "  🔴 没逮到"
        elif undeclared:
            note = "  🔴 **未声明的连带** %s —— 要么是误伤，要么该登记" % sorted(undeclared)
        elif also:
            note = "  （连带 %s，已声明）" % "、".join(sorted(also))
        print("   %s %-5s %s%s" % ("✅" if good else "🔴", cid, desc, note))
        con.execute("ROLLBACK TO m")
        con.execute("RELEASE m")
    con.rollback()

    # 花名册里没被变异覆盖的，必须在 UNMUTABLE 里说明
    miss = [c for c in ROSTER if c not in covered]
    print("\n── 没有变异覆盖的检查（必须逐条说明为什么）")
    for c in miss:
        why = UNMUTABLE.get(c)
        if why:
            print("   ⚠️ %-5s %s" % (c, why))
        else:
            ok = False
            print("   🔴 %-5s **没有变异、也没写为什么** —— 它可能是一条永远通过的检查" % c)
    extra = [c for c in UNMUTABLE if c not in ROSTER]
    if extra:
        ok = False
        print("   🔴 UNMUTABLE 里有花名册之外的编号：%s（名单漂了）" % extra)
    con.close()
    return ok


def main():
    if "--mutate" in sys.argv:
        raise SystemExit(0 if mutate() else 1)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = run(con)
    finally:
        con.close()
    print("■ vi 骨架闸：%d 条检查" % (len(CHECKS) + 1))
    for cid, why in red:
        print("   🔴 %-5s %s" % (cid, why))
    if not red:
        print("   ✅ 全绿")
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
