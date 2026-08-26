#!/usr/bin/env python3
"""阶段 2a 补丁：按收紧后的判据重算 `alt_of` 中文标签。2026-08-22。

═══ 为什么有这个补丁而不是重跑 2a ═══
`recover_alt_of.py --apply` **不是幂等的**（它按 `max(sense.id)+1` 建新行）。
重跑会走到「库内 sense 数与复刻不符」那条分支上整词跳过，等于什么也不做。
⇒ 判据改了之后，用本补丁**重算全部 `template:alt_of` 标签、只更新与新判据不同的行**。
   幂等、可反复跑、跑第二遍应当 0 更新。
   （`recover_alt_of.py` 里的判据已同步改好，从备份重建时结果一致。）

═══ 改了哪两条判据（都来自事后随机抽样，不是读代码看出来的）═══
① **多目标**：kaikki 的 `alt_of` 是数组，96 条有多个元素。逐条读过，分三类：
   (a) 84 条 —— 其余元素是**英文释义/语法注记**（`z'ami → ['ami','friend']`），取 [0] 本来就对
   (b)  9 条 —— **真多目标**（`CBRN → ['chimique','biologique','radiologique','nucléaire']`）
   (c)  3 条 —— 模糊
   🔴 只用"目标是不是真法语词形"会错：`plaïe → ['plage','beach']` 的 `beach`、
      `z'étage` 的 `stage`（法语=实习）都碰巧在库里 ⇒ 假阳性。
   ⭐ 加一条**语义判据**就分干净了：**异体形式指向唯一的规范形式，缩写/缩略才展开成多个词**。
      那 9 条里 8 条是 initialism/abbreviation/clipping/apocopic，唯一错的正是 `alternative`。
② **脏目标**：3 条目标串里带模板残渣（`maj → 'major alternative form of Maj'`），
   拼出来是「major alternative form of Maj 的缩写」。⇒ **不生成中文**，留给阶段 1.5。
   宁可空着，也不给错的（`PLAYBOOK`：错比缺更伤权威）。

用法（在 fr/ 目录下）：
    python3 fixes/fix_altof_targets.py           # 干跑，列出所有将变更的行
    python3 fixes/fix_altof_targets.py --apply
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool   # noqa: E402
import paths    # noqa: E402
from recover_alt_of import classify, label_zh, pick_targets   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    known = {w.lower() for (w,) in con.execute("SELECT word FROM dict")}

    # 现有的模板中文：sense_id → 文本
    cur = dict(con.execute(
        "SELECT sense_id, text FROM sense_gloss "
        "WHERE lang='zh' AND src='template:alt_of'"))
    # 证据行：sense_id → (原文, tags, targets)
    ev = {}
    for sid, text, raw in con.execute(
            "SELECT sense_id, text, raw_tags FROM sense_src "
            "WHERE src='en-edition' AND sense_id IS NOT NULL"):
        o = json.loads(raw) if raw else {}
        if "__alt_of__" in o:
            ev[sid] = (text, set(o.get("tags") or []), o["__alt_of__"])

    upd, dele, st = [], [], Counter()
    for sid, old in cur.items():
        if sid not in ev:
            st["🔴 有模板中文却找不到证据行"] += 1
            continue
        text, tags, targets = ev[sid]
        k, mod, how = classify(text, tags)
        tgt = pick_targets(k, targets, known) if k else None
        new = label_zh(k, mod, tgt, how) if tgt else None
        if new == old:
            st["不变"] += 1
        elif new is None:
            dele.append(sid)
            st["🔴 撤销（目标串是模板残渣）"] += 1
        else:
            upd.append((new, sid))
            st["🔴 改写（多目标拼接）"] += 1

    print("■ 模板中文 %s 条" % f"{len(cur):,}")
    for k, v in sorted(st.items()):
        print("   %-32s %8s" % (k, f"{v:,}"))

    w_of = dict(con.execute(
        "SELECT s.id, d.word FROM sense s JOIN dict d ON d.id=s.word_id"))
    print("\n── 将改写 ──")
    for new, sid in upd:
        print("   %-10s %-42s → %s" % (w_of.get(sid, "?"), cur[sid][:42], new))
    print("\n── 将撤销（中文留空，等阶段 1.5）──")
    for sid in dele:
        print("   %-16s %s" % (w_of.get(sid, "?"), cur[sid]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    if not upd and not dele:
        print("\n✓ 无需改动（幂等）")
        return 0

    with dbtool.session("altof-targets", expect={"#sense_gloss": -len(dele)}) as s:
        s.executemany("UPDATE sense_gloss SET text=? "
                      "WHERE sense_id=? AND lang='zh' AND src='template:alt_of'", upd)
        s.executemany("DELETE FROM sense_gloss "
                      "WHERE sense_id=? AND lang='zh' AND src='template:alt_of'",
                      [(i,) for i in dele])

    con.close()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸 ═══")
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("没有任何 gloss 的 sense（撤销后不能有裸 sense）",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.sense_id IS NULL"), 0),
        ("模板中文条数 == 4,987 - 撤销数",
         q("SELECT count(*) FROM sense_gloss WHERE lang='zh' AND src='template:alt_of'"),
         len(cur) - len(dele)),
        ("🔴 中文里仍带英文模板残渣的",
         q("SELECT count(*) FROM sense_gloss WHERE lang='zh' AND src='template:alt_of' "
           "AND (text LIKE '% form of %' OR text LIKE '% spelling of %')"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %8s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
