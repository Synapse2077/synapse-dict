#!/usr/bin/env python3
"""补入中文版维基确认的缺失义项（核心层 9 条）。2026-08-02。

═══ 三列怎么写（双家咨询后我裁决）═══
    definition   **留空行**
    translation  中文版的释义原文（转简、剥词性前缀）
    meta         追加 {"pos":…, "src":"zh-wiktionary", "batch":"zh-core-20260802"}

🔴 **definition 留空、不写 `[zh-wiktionary]` 这类标记**（豆包选后者，我否了）：
   来源信息不进值里 —— 这与今天上午否掉 `phonetic_src="rule+es-edition"` 是同一条原则。
   `definition` 现在可以被证明是"英文版原值"，塞标记会永久破坏这个性质。
   "空值有对齐歧义"的顾虑由下面的行数强校验解决。
⚠️ 豆包还建议写 `def_confirm:"manual_cross_verify"` —— **否**，这 9 条是两家模型裁决
   + 我拿西语版核的，没有人工编纂环节。写 manual 是往数据里写谎话。

═══ 这 9 条是怎么筛出来的 ═══
1,275 条分歧 → 核心层 154 条(A1/A2/B1) → 两家**都**判需补 13 → 剔除**变形可达** 4 → 9。
剔除的 4 条（gata/buena/perra/maestra）全是"某词的阴性"，原形已带该义 ——
**两家都误报了，因为我的 payload 没给 `infl` 列**（纪律⑧ 又栽一次）。
保留的 9 条逐条经**西语版**（第三个独立源）确认。

用法（在 es/ 目录）：
    python3 fixes/append_zh_senses.py
    python3 fixes/append_zh_senses.py --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import json
import sqlite3

import dbtool
import paths

BATCH = "zh-core-20260802"

# 词 → 要补的中文义项。取两家 import 列表的**交集语义**、以西语版佐证为准；
# 四条变形可达的（gata/buena/perra/maestra）已剔除，不在此表。
APPEND = {
    "ring":        ["拳击场"],
    "ajustado":    ["公正的，合理的"],
    "comba":       ["弯曲，翘曲"],
    "expreso":     ["明确的，明白表示的", "快车"],
    "bohemia":     ["放荡不羁的生活"],
    "descubierto": ["暴露在外的，无遮掩的", "赤字，透支"],
    "facilidad":   ["（付款的）宽限，便利条件"],
    "ocurrencia":  ["主意，念头"],
    "turquí":      ["靛青色的，深蓝色的"],
}


def aligned(dfn, tr, meta):
    """三列逐行对齐校验 —— 两家都提的护栏，作为落库前置条件。"""
    return len(dfn.split("\n")) == len(tr.split("\n")) == len(meta)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word, pos, definition, translation, meta FROM dict "
        "WHERE is_lemma=1 AND word IN (%s)" % ",".join("?" * len(APPEND)),
        list(APPEND)).fetchall()
    conn.close()

    plan, samples, bad = [], [], []
    for rid, w, pos, dfn, tr, mj in rows:
        meta = json.loads(mj) if mj else []
        if not aligned(dfn or "", tr or "", meta):
            bad.append((w, "改前就没对齐", len((dfn or "").split("\n")),
                        len((tr or "").split("\n")), len(meta)))
            continue
        add = APPEND[w]
        new_d = (dfn or "") + "\n" * len(add)          # 每补一条 → 一个空的 definition 行
        new_t = (tr or "") + "".join("\n" + x for x in add)
        new_m = meta + [{"pos": (pos or "").split("/")[0], "src": "zh-wiktionary",
                         "batch": BATCH} for _ in add]
        if not aligned(new_d, new_t, new_m):
            bad.append((w, "改后不对齐", len(new_d.split("\n")),
                        len(new_t.split("\n")), len(new_m)))
            continue
        plan.append((new_d, new_t, json.dumps(new_m, ensure_ascii=False), rid))
        samples.append((w, str(len(meta)) + "→" + str(len(new_m)),
                        " / ".join(add)[:34], (tr or "").replace("\n", " / ")[:34]))

    print("■ 计划补 %d 个词、%d 个义项" % (len(plan), sum(len(v) for v in APPEND.values())))
    if bad:
        print("\n🔴 对齐校验未通过：")
        for x in bad:
            print("   %s %s  definition%d / translation%d / meta%d" % x)
    dbtool.sample_check(samples, n=9, cols=("词", "义项数", "补入", "原有译文"))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库)")
        return
    if bad:
        print("\n🔴 有未对齐的行，不落库。", file=_sys.stderr)
        raise SystemExit(1)
    # definition/translation/meta 三列非空计数都不变（只往已有内容后面追加）。
    with dbtool.session("append-zh-senses", expect={}) as s:
        s.executemany("UPDATE dict SET definition=?, translation=?, meta=? WHERE id=?", plan)


if __name__ == "__main__":
    main()
