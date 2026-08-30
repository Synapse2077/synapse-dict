#!/usr/bin/env python3
"""C21 的一半：源头用**散文**写着的屈折关系，补进变形层；随后隐掉变冗余的指针义项。2026-08-30。

═══ 怎么发现的 ═══
C20 免费补完中文后渲染 `gamões`，页面上是：

    释义   名词   （待补）        ← 这一条
    PT     plural de gamão
    词形变化  gamão 的 复数        ← 正下方已经把答案说全了
    gamão  名词 阳性 双陆棋

于是问：这 541 条名词性指针，变形层到底覆盖了多少？——**只有 105 条**。
剩下 436 条里，源头明明白白写着 `Cipiões → plural de Cipião`，
**而这条屈折关系从没进过 `inflection`** —— 阶段 2b 只读结构化的 `form_of`，
阶段 2c 只读变位表 `forms`，**没有任何一步读过"写成散文的 form_of"**。

⇒ 这不是"隐掉噪声"，是**免费捞回 433 条真结构**。

═══ 判据（按含义）═══
① 只收**屈折**（plural / feminino / masculino / singular），
   **不收** `diminutivo`(23) / `aumentativo`(16) —— 指小指大是**构词**不是屈折，
   与收尾单 C26 同一条待决问题，不在这里顺手定。
② 原形必须在 `dict` 里（否则是悬空链接）。
③ **不收指向自己的**（`Adães → plural de Adães`，源头错，23 条）。
④ 变形层已有同一条 ⇒ 不重复收。

═══ 然后才隐 ═══
隐掉指针义项的判据是「**变形层已经把这件事说清楚**」——
不是"这句话长得像指针"。上一版 `hide_conjugation_pointers` 的反向查已经证明过
「指针句式 ≠ 该隐藏」（会误伤 1,379 条交叉引用）。
⇒ 先补结构、再按"补完之后还冗余吗"隐，**顺序不能反**。

用法（在 pt/ 目录下）：
    python3 fixes/ingest_prose_inflections.py
    python3 fixes/ingest_prose_inflections.py --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 只收屈折。指小/指大是构词，留给 C26 一起定。
KIND_ZH = {"plural": "复数", "feminino": "阴性", "masculino": "阳性", "singular": "单数"}
PTR = re.compile(r"^\s*(%s)\s+d[eoa]s?\s+(?:sufixo\s+|prefixo\s+)?(\S[^,;.:()]*)"
                 % "|".join(KIND_ZH), re.I)
# 判据要认出**全部**名词性指针（含不收的那些），否则"该不该隐"会算错
ANY_PTR = re.compile(r"^\s*(plural|feminino|masculino|singular|diminutivo|aumentativo"
                     r"|superlativo)\s+d[eoa]s?\s+(?:sufixo\s+|prefixo\s+)?(\S[^,;.:()]*)", re.I)


def plan(con):
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    infl = collections.defaultdict(set)
    for w, b, lab in con.execute("SELECT d.word, i.base, i.label_zh FROM inflection i "
                                 "JOIN dict d ON d.id=i.word_id"):
        infl[w].add((b, lab))
    rows = con.execute(
        "SELECT s.id, s.word_id, d.word, ss.text FROM sense s "
        "  JOIN dict d ON d.id=s.word_id JOIN sense_src ss ON ss.sense_id=s.id "
        " WHERE COALESCE(s.hidden,0)=0 AND ss.lang='pt'").fetchall()
    add, stat, seen = [], collections.Counter(), set()
    ptr_senses = []
    for sid, wid, w, t in rows:
        m = ANY_PTR.match(t)
        if not m:
            continue
        ptr_senses.append((sid, w, m.group(1).lower(), m.group(2).strip()))
        m2 = PTR.match(t)
        if not m2:
            stat["构词（指小/指大/最高级）—— 不收，见 C26"] += 1
            continue
        kind, base = m2.group(1).lower(), m2.group(2).strip()
        lab = KIND_ZH[kind]
        if base == w:
            stat["指向自己（源头错）"] += 1
            continue
        if base not in ids:
            stat["原形不在 dict 里（会是悬空链接）"] += 1
            continue
        if (base, lab) in infl[w]:
            stat["变形层已有"] += 1
            continue
        if (wid, base, lab) in seen:
            stat["同一条在多个义项里重复出现"] += 1
            continue
        seen.add((wid, base, lab))
        add.append((wid, base, ids[base], lab, sid))
        stat["✅ 可免费补进变形层"] += 1

    return add, stat, ptr_senses, infl, ids


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    add, stat, ptr_senses, infl, ids = plan(con)
    f = lambda n: format(n, ",")
    print("■ 源头写成散文的屈折关系")
    for k, v in stat.most_common():
        print("   %6s  %s" % (f(v), k))
    for wid, base, _bid, lab, _sid in add[:8]:
        w = con.execute("SELECT word FROM dict WHERE id=?", (wid,)).fetchone()[0]
        print("     %-24s → %-20s [%s]" % (w[:24], base[:20], lab))

    # 补完之后再判「该不该隐」
    after = collections.defaultdict(set)
    for k, v in infl.items():
        after[k] = set(v)
    for wid, base, _bid, lab, _sid in add:
        w = con.execute("SELECT word FROM dict WHERE id=?", (wid,)).fetchone()[0]
        after[w].add((base, lab))
    # 🔴 **只隐没有中文的。** 反向查（第三次立功）逮到 21 条会被误伤 ——
    #    源头写的是「指针**加**释义」，分号后面才是真内容：
    #        cento e uma  `feminino de cento e um; representa…`  → 中文「一百零一」
    #        caxienses    `plural de caxiense: residentes de…`   → 中文「卡希亚斯居民」
    #    隐掉＝把读者的答案抹了。判据：**读者会因此少看到东西，就不隐。**
    zh = {r[0] for r in con.execute("SELECT sense_id FROM sense_gloss WHERE lang='zh'")}
    hide, spared = [], 0
    for sid, w, kind, base in ptr_senses:
        lab = KIND_ZH.get(kind)
        if not (lab and (base, lab) in after[w]):
            continue
        if sid in zh:
            spared += 1
            continue
        hide.append(sid)
    hide = sorted(set(hide))
    print("\n   ✓ 反向查：判据命中但**已有中文**、因而放过的 %d 条" % spared)
    print("\n■ 补完之后**变形层已经说清楚**、因而冗余的指针义项 ⇒ 隐掉：%s" % f(len(hide)))
    print("   ⚠️ 判据是「变形层已经说清楚」，不是「这句话长得像指针」——")
    print("      上一版反向查已证明「指针句式 ≠ 该隐藏」（会误伤 1,379 条交叉引用）")
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("ingest-pt-prose-inflections",
                        expect={"#inflection": len(add)}) as s:
        s.executemany(
            "INSERT INTO inflection(word_id, base, base_id, label_zh, src, src_ref) "
            "VALUES(?,?,?,?,'pt-edition-prose',?)",
            [(wid, base, bid, lab, "sense:%d" % sid) for wid, base, bid, lab, sid in add])
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", [(i,) for i in hide])
    print("\n✓ 变形层 +%s ／ 隐掉冗余指针义项 %s" % (f(len(add)), f(len(hide))))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
