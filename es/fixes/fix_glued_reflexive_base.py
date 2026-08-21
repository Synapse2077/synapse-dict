#!/usr/bin/env python3
"""修 wiktextract 粘出来的伪原形，以及 build.py 已裁决的多词 junk 指针。2026-08-20。

═══ 缺陷 ═══
页面「变位形式」块里出现了**不存在的词**：

    desemejadas 的变位形式
      · desemejado 的 阴性·复数              ← 对
      · desemejado 的 过去分词·阴性·复数       ← 对
      · desemejadose 的 过去分词·阴性·复数     ← 🔴 desemejadose 不是西语词

根因**在源头**，不在我们的解析器：西语版 dump 的 `form_of` 里就写着

    "glosses": ["Forma del femenino plural de desemejado, participio de
                 desemejar o de desemejarse."]
    "form_of":  [{"word": "desemejado"}, {"word": "desemejadose"}]
                                          ^^^^^^^^^^^^^^^^^^^^^^
wiktextract 把「o de desemejarse」里的词干和 `se` 粘成了 `desemejadose`。
真原形 `desemejado` 就在同一个 `form_of` 的第一项。

═══ 判据（锚在源头，不靠词尾猜）═══
① `base == 该词形第一个能解析的 base + "se"`      ⇒ 疑似粘接
② 且 `base` 的词尾是 **分词+se**（`ados e`/`idose`/`tose`/`chose`）

🔴 **②这一条是必须的，少了它会误伤 84 行真数据。** 第一版只有①，
   把 `acoparse`（= `acopar` + `se`）、`ahucharse`、`crecentarse`、`ruñirse`
   这些**真实的自复动词**也判成了伪词 —— 源头原文明明写着
   「Participio de ahuchar **o de ahucharse**」。区分点是第一个原形到底是
   **分词**（desemejado ⇒ 分词+se 不成词）还是**不定式**（acopar ⇒ 不定式+se 是真词）。
   ⇒ 这 84 行归入「源头真缺词头」那一族，不在本脚本处理范围。

重指目标的判据是**双重锁**：同词干的自复不定式，**且**必须出现在源头原文里。
⚠️ 不能用「原文里任一 `rse` 结尾且库里有的词」—— `enllentecerse` 那条原文里还有个
   `hacerse`（"hacer o hacerse blando"），松判据一样命中。本批两条判据结果恰好都是
   503，但发严的那条才是能论证正确性的。

═══ 处置（可逆，不删行不改旧列）═══
    503 行  重指 → `base_fixed` = 同词干自复不定式，`base_id` 指过去
     15 行  同族但库里没有重指目标        → `hidden=1`
     15 行  多词 junk（`tú and vos` / `voy a` / `vaquera Cowgirls` …，
            全部在 `build.py` 的 MW_DROP / MW_REPOINT 裁决表里）→ `hidden=1`

**新加两列，`base` 与 `label_zh` 一个字节不动** ⇒ 闸①（从 `base`+`label_zh`
反向重建 `dict.infl` 逐字节比）照常全绿，旧列仍是有效的迁移锚点。
撤销 = 把两列清空。

用法（在 es/ 目录下）：
    python3 fixes/fix_glued_reflexive_base.py            # 试算
    python3 fixes/fix_glued_reflexive_base.py --apply
    python3 fixes/fix_glued_reflexive_base.py --mutate   # 变异验证
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 分词 + se（粘接的形状）。**不含 -arse/-erse/-irse** —— 那是真自复动词，见文件头。
PART_SE = re.compile(r"(ad|id|t|ch)ose$")
INF_SUF = ("arse", "erse", "irse")

# ═══════════════════════════════════════════════════════════════════════
#  C 族：多词 junk 原形 —— 13 个，逐条裁决
#
# 🔴 **这一族是本轮唯一明确「用户看到错的内容」的缺陷**，而我一开始把它归成了
#    「用户看不见的 junk」。错在只查了「有没有死链」，没查这些行**落在什么词上**：
#
#      lo    zipf 6.89   变位形式：él and usted 的 宾格
#      te    zipf 6.52   变位形式：tú and vos 的 与格 ／ tú and vos 的 宾格
#      les   zipf 5.88   变位形式：ellos and ellas 的 与格
#
#    `lo` / `te` / `les` 是西语最常用的词之一。页面上把英文 `and` 夹在中文语法标签里，
#    出现在全词典流量最高的几页上。⇒ 判「用户看不看得见」不能只看链接，要看**频次**。
#
# `exchange` 里这些早被 `build.py:305-330` 删干净了，只有 `infl` 行还留着 ——
# 因为那套 JUNK/MW 过滤**只作用于 exchange，没作用于 infl**（与 `merer` 同一个洞）。
#
# 处置分两类，判据来自 build.py 自己的裁决表，不另写一套（A93）：
#   · 英文释义泄漏 ⇒ 剥回真词（键值直接取自 `build.MW_REPOINT`）
#   · 代词/短语描述 ⇒ 事实是对的（te 确实是 tú/vos 的与格），坏的只是 base 字符串
#     被英文粘住 ⇒ **重指到第一个代词**（都在库里，实测 ✓），不藏 ——
#     藏掉会丢掉一条真语法信息，而这些恰恰是最常用的词。
# ═══════════════════════════════════════════════════════════════════════
MW_PRONOUN = {          # 代词描述 → 第一个代词（全部实测在库里）
    "tú and vos": "tú",            # te 的与格/宾格
    "él and usted": "él",          # lo 的宾格
    "ellos and ellas": "ellos",    # les 的与格（同词形另有 ustedes 行，本就解析得了）
}
MW_HIDE = {             # 纯英文残渣，剥不出真词 ⇒ 藏（同词形都另有正确的行）
    "execution of a crimen or delito in that",   # frustrado，另有 `frustrar 的 …`
    "an eccentric or superficial genius",        # genialoide
    "voy a",                                     # wa（WhatsApp 缩写，与 voy a 无关）
    "cien millón",                               # cien millones，源头把复数当了原形
}


def plan(con, verbose=True):
    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    wid_of = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        wid_of.setdefault(w, i)
    # 该词形**全部**能解析的 base。
    # 🔴 第一版只取「第一个」—— `empelotadas` 的 seq0 是 `empelotada`，
    #    而粘接产物 `empelotadose` 派生自 seq1 的 `empelotado`，判据够不到 ⇒ **漏网 1 条**，
    #    随后 `ingest_missing_bases` 还给它建了个词头。展示层契约闸逮到的。
    #    ⇒ 判据放宽成「等于**任意一个**可解析 base + se」。
    first = {}
    for wid, base, bid in con.execute(
            "SELECT word_id, base, base_id FROM inflection ORDER BY word_id, seq"):
        if bid is not None:
            first.setdefault(wid, set()).add(base)

    # build.py 自己的英文泄漏剥离表，直接 import，不抄一份（A93）
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
    import build as B   # noqa
    MW_REPOINT = getattr(B, "MW_REPOINT", None)
    if MW_REPOINT is None:      # build.py 里它是 main() 的局部变量，取不到就用同一份字面量
        MW_REPOINT = {"azud m": "azud", "peuco an American hawk": "peuco",
                      "primogénito firstborn daughter": "primogénito",
                      "soldado little soldier": "soldado", "vaquera Cowgirls": "vaquera",
                      "o when between numerals": "o", "de often found on signs": "de",
                      "es que in the Madrid dialect": "es que"}

    repoint, hide, c = [], [], Counter()
    # 🔴 判据是「**还没被处理过的行**」，不是「`base_id` 为空的行」。
    #    第二版用后者，结果 `empelotadose` 逃掉了：`ingest_missing_bases` 先给它
    #    建了个词头 ⇒ `base_id` 变成非空 ⇒ 本脚本再也看不见它。
    #    **我的修复被我自己后一步的产物挡住了** —— 而两步都各自过了闸。
    #    展示层契约闸逮到的（页面上真的印着 `empelotadose 的 过去分词·阴性·复数`）。
    for iid, wid, base, desc in con.execute(
            "SELECT id, word_id, base, desc_en FROM inflection "
            # 已藏的也重新看一遍：当初藏是因为**没有重指目标**，
            # 而 `ingest_missing_bases` 之后 `ahucharse`/`acorvarse` 这些真自复动词
            # 已经作为词头存在了 ⇒ 现在能重指。重指比藏多给一条真信息（且链接可点）。
            "WHERE base<>'' AND base_fixed IS NULL"):
        if base in MW_HIDE:
            hide.append(iid)
            c["C 纯英文残渣 → 藏"] += 1
            continue
        tgt = MW_PRONOUN.get(base) or MW_REPOINT.get(base)
        if tgt:
            if tgt in wid_of:
                repoint.append((tgt, wid_of[tgt], iid))
                c["C 代词描述 → 重指" if base in MW_PRONOUN
                  else "C 英文释义泄漏 → 剥回真词"] += 1
            else:
                hide.append(iid)
                c["🔴 C 重指目标不在库里 → 藏"] += 1
            continue
        fbs = first.get(wid) or set()
        if not any(base == x + "se" for x in fbs):
            c["不是粘接形状（本脚本不处理）"] += 1
            continue
        m = PART_SE.search(base)
        if not m:
            # 不定式 + se ⇒ 真自复动词，归 A 族
            c["A 真自复动词（不定式+se），不是伪词"] += 1
            continue
        stem = base[:m.start()]
        cands = [stem + s for s in INF_SUF
                 if stem + s in have and desc and (stem + s) in desc]
        if len(cands) == 1:
            repoint.append((cands[0], wid_of[cands[0]], iid))
            c["B 伪词 → 重指同词干自复不定式"] += 1
        elif len(cands) > 1:
            c["🔴 B 多个候选（未处理，记账）"] += 1
        else:
            hide.append(iid)
            c["B 伪词但库里没有重指目标 → 藏"] += 1
    if verbose:
        for k, v in sorted(c.items()):
            print("   %-40s %s 行" % (k, format(v, ",")))
    return repoint, hide, c


def apply(con, repoint, hide):
    cols = {r[1] for r in con.execute("PRAGMA table_info(inflection)")}
    if "base_fixed" not in cols:
        con.execute("ALTER TABLE inflection ADD COLUMN base_fixed TEXT")
    if "hidden" not in cols:
        con.execute("ALTER TABLE inflection ADD COLUMN hidden INTEGER")
    # ⚠️ 重指时必须**同时清掉 hidden** —— 否则那 15 行改对了 base 却还是不渲染，
    #    数据侧看着修好了、页面上一个字没变（就是「被绕过」）。
    con.executemany(
        "UPDATE inflection SET base_fixed=?, base_id=?, hidden=NULL WHERE id=?", repoint)
    con.executemany("UPDATE inflection SET hidden=1 WHERE id=?",
                    [(i,) for i in hide])
    return len(repoint) + len(hide)


def gate(con, verbose=True):
    """闸：① 旧列反向重建仍逐字节相同（证明只加不改）② 重指目标全部可解析。"""
    bad = []
    rb = defaultdict(list)
    for wid, seq, base, lab in con.execute(
            "SELECT word_id, seq, base, label_zh FROM inflection"):
        rb[wid].append((seq, ("%s 的 %s" % (base, lab)) if base else lab))
    diff = 0
    for wid, infl in con.execute("SELECT id, infl FROM dict WHERE COALESCE(infl,'')<>''"):
        if "\n".join(t for _, t in sorted(rb.get(wid, []))) != infl:
            diff += 1
    if diff:
        bad.append("🔴 旧列反向重建出现 %s 行差异 —— 本脚本本不该改 base/label_zh" % f"{diff:,}")
    n = con.execute("SELECT COUNT(*) FROM inflection WHERE base_fixed IS NOT NULL "
                    "AND base_id IS NULL").fetchone()[0]
    if n:
        bad.append("🔴 有 %s 行重指了但 base_id 仍为空" % f"{n:,}")
    n = con.execute("SELECT COUNT(*) FROM inflection i LEFT JOIN dict d ON d.id=i.base_id "
                    "WHERE i.base_fixed IS NOT NULL AND d.word IS NOT i.base_fixed").fetchone()[0]
    if n:
        bad.append("🔴 有 %s 行的 base_id 指向的词 ≠ base_fixed" % f"{n:,}")
    if verbose:
        print("■ 闸：旧列反向重建 %s；重指 %s 行；藏 %s 行" % (
            "逐字节相同 ✓" if not diff else "🔴 %s 行不同" % f"{diff:,}",
            f"{con.execute('SELECT COUNT(*) FROM inflection WHERE base_fixed IS NOT NULL').fetchone()[0]:,}",
            f"{con.execute('SELECT COUNT(*) FROM inflection WHERE hidden=1').fetchone()[0]:,}"))
        for b in bad:
            print("     " + b)
        if not bad:
            print("     ✅ 全部通过")
    return bad


def mutate(repoint, hide):
    """变异验证。闸盯的是「只加不改」+「重指自洽」，变异就打在这两处。"""
    import shutil
    import tempfile
    cases, ok = [], 0
    MUT = [
        ("① 篡改一条的 base（应破坏旧列重建）",
         "UPDATE inflection SET base='__x__' WHERE base_fixed IS NOT NULL LIMIT 1"),
        ("② 重指了却不写 base_id",
         "UPDATE inflection SET base_id=NULL WHERE base_fixed IS NOT NULL LIMIT 1"),
        ("③ base_id 指到别的词",
         "UPDATE inflection SET base_id=(SELECT MIN(id) FROM dict) "
         "WHERE base_fixed IS NOT NULL AND base_fixed<>(SELECT word FROM dict ORDER BY id LIMIT 1) LIMIT 1"),
        ("④【负控】只改 hidden，不该报红",
         "UPDATE inflection SET hidden=1 WHERE hidden IS NULL LIMIT 1"),
    ]
    for i, (name, sql) in enumerate(MUT):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.sqlite"
            shutil.copy2(paths.DB, p)
            c = sqlite3.connect(p)
            apply(c, repoint, hide)
            try:
                c.execute(sql)
            except sqlite3.Error:
                # SQLite 的 UPDATE 不支持 LIMIT（未编译该选项）时退回子查询
                c.execute(sql.replace(" LIMIT 1", " AND id=(SELECT MIN(id) FROM inflection "
                                                           "WHERE base_fixed IS NOT NULL)"))
            c.commit()
            bad = gate(c, verbose=False)
            c.close()
        want_red = i < 3
        good = bool(bad) == want_red
        ok += good
        cases.append((name, ("✅ 报红" if bad else "✅ 照常绿") if good
                      else ("🔴 该红没红" if want_red else "🔴 不该红却红了")))
    print("\n■ 变异验证")
    for n, s in cases:
        print("     %-36s %s" % (n, s))
    print("     %d/%d" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    repoint, hide, _ = plan(con)
    con.close()
    print("■ 将重指 %s 行、藏 %s 行" % (format(len(repoint), ","), format(len(hide), ",")))
    if a.mutate:
        return mutate(repoint, hide)
    if not a.apply:
        print("\n(未加 --apply，没有写库)")
        return 0
    with dbtool.session("glued-reflexive-base", expect={}) as s:
        s.written = apply(s.conn, repoint, hide)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = gate(con)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
