#!/usr/bin/env python3
"""阶段 8 照出来的洞：**指针义项的中文**。2026-09-08。零 API、确定性。

═══ 现场（阶段 8 真渲染才看见的）═══
读者打开 `cats` 页看到的是：

    1.(n) plural of cat                                zh: 🔴 空
    2.(v) third-person singular simple present of cat  zh: 🔴 空

**706,345 条指针义项，中文覆盖 0。**占全部义项的 39.7% ——
读者每打开一个变形词，看到的就是一句英文加一片空白。

🔴 `[[it-display-layer-stage8]]` 第 N 次应验：**数据层三张表全绿，渲染出来才看见。**
   阶段 1.5 有意不翻指针义项（省了 706,345 条的钱，是对的），
   但**"不翻"不等于"不给中文"** —— 中文是现成的，只是没接上。

═══ 判据：确定性对接，零猜测 ═══
指针义项的 `sense_src.raw_tags.tags` 正是变形层拼 `label_zh` 用的那一套：

    sense 127972  tags=["form-of","plural"]   →（infl_compose）→ 复数
    inflection    word_id=cats  label_zh=复数  base=cat
    ⇒ 「cat 的复数」

⇒ 用 `(word_id, label_zh)` 对接。**不解析英文文本**（`plural of cat` 那句），
  拼不出或对不上的**留空不猜**（`[[dont-gate-facts-on-my-uncertainty]]`）。
⭐ 复用 `infl_compose`，**不另写一份拼装逻辑** —— 两份必然漂移
  （`[[refactor-mindset-code-quality]]`，今天已经在"重合"判据上栽过一次）。

    cd en && python3 -u pipeline/fill_pointer_gloss.py
    cd en && python3 -u pipeline/fill_pointer_gloss.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import sqlite3

import dbtool
import infl_compose
import paths

SRC = "template:form_of"

# 🔴 **第二条路：异体不是变形。**
#    实测拼不出标签的 16.8 万条里，前几名是 `alternative` 61,254 ／
#    `abbreviation initialism` 12,850 ／ `obsolete` 8,276 ／ `misspelling` 6,222 ——
#    它们是 `alt_of`（异体/缩写/古体/误拼），不是形态变化。
#    `infl_compose` 拒绝它们**是对的**（它只管形态），不该去改它来迁就这一族。
#    ⇒ 走 `sense_relation(kind='alt_of')` 拿目标，按 tag 选模板。
#    ⚠️ 模板按**含义**分，不按拼写：`initialism`/`acronym` 与 `abbreviation` 是一回事。
ALT_TEMPLATE = [
    (("misspelling",), "误拼"),
    (("obsolete",), "古体"),
    (("archaic",), "古体"),
    (("dated",), "旧式"),
    (("abbreviation", "initialism", "acronym", "short-form"), "缩写"),
    (("alternative",), "异体"),
]
ALT_DEFAULT = "异体"          # alt_of 本身的含义就是异体，兜底安全


def collect(con):
    q = con.execute
    have = {s for (s,) in q("SELECT sense_id FROM sense_gloss WHERE lang='zh'")}
    # (word_id, label_zh) → base
    infl = {}
    for wid, base, lab in q("SELECT word_id, base, label_zh FROM inflection"):
        infl.setdefault((wid, lab), base)
    # 异体目标：义项级 alt_of（en 实测词条级 0 条）
    alt = {}
    for sid, t in q("SELECT sense_id, target FROM sense_relation "
                    "WHERE kind='alt_of' AND sense_id IS NOT NULL"):
        alt.setdefault(sid, t)
    rows, stat = [], collections.Counter()
    for sid, wid, rt in q("SELECT sense_id, word_id, raw_tags FROM sense_src "
                          "WHERE raw_tags LIKE '%\"form-of\"%' OR raw_tags LIKE '%\"alt-of\"%'"):
        if sid is None:
            continue
        stat["指针义项"] += 1
        if sid in have:
            stat["已有中文（跳过）"] += 1
            continue
        try:
            tags = (json.loads(rt) or {}).get("tags") or []
        except Exception:
            stat["raw_tags 解析失败"] += 1
            continue
        lab, kind = infl_compose.compose(tags)
        if lab:
            base = infl.get((wid, lab))
            if base is None:
                stat["🔴 变形层里对不上（留空）"] += 1
                continue
            rows.append((sid, "%s 的%s" % (base, lab), SRC))
            stat["⭐ 可补·变形"] += 1
            continue
        # ── 第二条路：异体
        tgt = alt.get(sid)
        if tgt is None:
            stat["🔴 既拼不出变形、也没有异体目标（留空）"] += 1
            continue
        ts = set(tags)
        word = next((zh for keys, zh in ALT_TEMPLATE if ts & set(keys)), ALT_DEFAULT)
        rows.append((sid, "%s 的%s" % (tgt, word), SRC))
        stat["⭐ 可补·异体"] += 1
    return rows, stat


def gates(con, n_new, before):
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("模板中文行数", q("SELECT COUNT(*) FROM sense_gloss WHERE src='%s'" % SRC), n_new),
        ("🔴 只补指针义项，没碰实义项",
         q("SELECT COUNT(*) FROM sense_gloss g WHERE g.src='%s' AND g.sense_id NOT IN "
           "(SELECT sense_id FROM sense_src WHERE raw_tags LIKE '%%\"form-of\"%%' "
           " OR raw_tags LIKE '%%\"alt-of\"%%')" % SRC), 0),
        ("🔴 付费译文一条没被覆盖",
         q("SELECT COUNT(*) FROM sense_gloss WHERE src='model:def'"), before["model"]),
        ("🔴 免费贴的一条没被覆盖",
         q("SELECT COUNT(*) FROM sense_gloss WHERE src='ecdict-core'"), before["ecdict"]),
        ("模板中文里没有空串",
         q("SELECT COUNT(*) FROM sense_gloss WHERE src='%s' AND TRIM(text)=''" % SRC), 0),
        # 负控：`cats` 必须拿到「cat 的复数」
        ("负控 cats 拿到中文",
         q("SELECT COUNT(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
           "JOIN dict d ON d.id=s.word_id WHERE d.word='cats' AND g.lang='zh'"), 2),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-40s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, stat = collect(con)
    before = {
        "model": con.execute("SELECT COUNT(*) FROM sense_gloss WHERE src='model:def'").fetchone()[0],
        "ecdict": con.execute("SELECT COUNT(*) FROM sense_gloss WHERE src='ecdict-core'").fetchone()[0],
    }
    now = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE src=?", (SRC,)).fetchone()[0]
    con.close()
    print("═══ 指针义项中文（模板生成）═══")
    for k in ("指针义项", "已有中文（跳过）", "⭐ 可补·变形", "⭐ 可补·异体",
              "🔴 变形层里对不上（留空）", "🔴 既拼不出变形、也没有异体目标（留空）",
              "raw_tags 解析失败"):
        if stat[k]:
            print("   %-26s %9s" % (k, format(stat[k], ",")))
    cov = stat["⭐ 可补·变形"] + stat["⭐ 可补·异体"] + stat["已有中文（跳过）"]
    print("   ⇒ 指针义项中文覆盖 0%% → **%.1f%%**" % (100 * cov / max(stat["指针义项"], 1)))
    print("\n   样本：")
    for sid, txt, _ in rows[:6]:
        print("      %s" % txt)
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    with dbtool.session("keep-v3-pointer-gloss",
                        expect={"#sense_gloss": len(rows) - now}) as s:
        s.execute("DELETE FROM sense_gloss WHERE src=?", (SRC,))
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'zh','equivalent',0,?,?)", rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, len(rows), before)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
