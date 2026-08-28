#!/usr/bin/env python3
"""族 C 第二段 — 收法文版 `tags` 里的**领域 / 地区 / 语域**。2026-08-27。

第一段（`ingest_fr_topics.py`）收的是法文版的 `topics` 字段。
这一段收 `tags` 字段 —— 里面混着四种东西，**必须分桶**：

    法文版 tags：3,415 种 / 180,410 行（挂在可见义项上），现有各表只覆盖 41.8%

    ① 领域（法语写的）  `Cynologie` 犬学 / `Armement` 军械 / `Viticulture` 葡萄种植
    ② 地区（法语地名）  `Québec` / `Suisse` / `Normandie` / `La Réunion`
    ③ 语域 / 用法       `Anglicism` / `Extrêmement rare` / `Par plaisanterie` / `metonymically`
    ④ 🔴 **结构标记，不出版**  `alt-of`（12,753 行，全库最大的一个 tag）、
       及物性 / 代动词 / 前置后置 / 无冠词 / `Abréviation`、
       以及维基的待办标记 `information à préciser ou à vérifier`

🔴 ④ 为什么不能收：把 `alt-of` 或 `transitive` 印成义项旁边的胶囊，
   读者会以为那是词义的一部分。它们是**语法/元信息** ——
   及物性、代动词、形容词位置在**词条头徽标**里已经各有字段在渲染，
   `alt-of` 由「异体 →」那一行承担。在义项旁边再印一遍是同一个信息印两次。

═══ 分桶表住在 `packages/dict-labels/src/fr.ts` ═══
`FR_TAG_TOPIC` / `FR_TAG_REGION` / `FR_TAG_REGISTER` / `FR_TAG_SKIP`。
⭐ 三张表的值一律是**已有的规范键**（英文），中文只从 `TOPIC_LABELS` /
   `FR_REGION_LABELS` / `REGISTER_LABELS` 取 —— 在分桶表里再写一份中文，
   就是让同一个概念有两个译名慢慢漂开。

═══ 只出版映射得出中文的 ═══
与第一段同一条纪律：映射不出就记账、不出版。
渲染出 `Cynologie` 这种法文生标签比不收更坏。

用法（在 fr/ 目录下）：
    python3 -u pipeline/ingest_fr_tags.py            # 只报数
    python3 -u pipeline/ingest_fr_tags.py --apply    # 落库
    python3 -u pipeline/ingest_fr_tags.py --undo     # 撤回（删 src 标记的那批）
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402

f = lambda n: format(n, ",")
LAB = HERE.parent.parent / "packages" / "dict-labels" / "src"
# 🔴 `^` 必须开 `re.M`，且不能只匹配行首 —— 一行里有多个 `key: '值'`。
#    这两个坑第一段各踩过一次（先报"要补 135 个键"真值 12 个，再把刚加的
#    `linguistic` 报成"映射不出"）。判据抄过来的时候连注释一起抄。
KV = re.compile(r"(?:^|[{,])\s*'?([A-Za-z0-9À-ÿ' \-’.]+?)'?\s*:\s*'([^']*)'", re.M)


def table(fn, name):
    """读 dict-labels 里某张表 → {键: 值}。**表本身是唯一的一份**，这里不抄。

    🔴 必须锚在**声明**上（`export const X = {` / `Object.assign(X, {`），
       不能拿 `find(name)` 满文件找 —— 表名会出现在**注释**里，
       第一版从注释处开始读、一路读到下一个 `};`，把**别的表**的内容
       整个吞进来：`broadly` / `especially` / `physical` 这些语域值
       落进了地区桶（`region/broadly` 6,005 行）。
       同时 `REGISTER_LABELS` 因为先命中 import 列表而整张读空，
       闸 ② 报 10,130 条"指向不存在的中文键"。
    """
    s = (LAB / fn).read_text(encoding="utf-8")
    out = {}
    for pat, end in (("export const %s" % name, "\n};"),
                     ("Object.assign(%s," % name, "\n});")):
        i = 0
        while True:
            i = s.find(pat, i)
            if i < 0:
                break
            j = s.index(end, i)
            for m in KV.finditer(s[i:j]):
                out[m.group(1).strip().strip("'")] = m.group(2)
            i = j
    return out


def skip_set():
    s = (LAB / "fr.ts").read_text(encoding="utf-8")
    i = s.index("export const FR_TAG_SKIP")
    return {m.group(1) for m in re.finditer(r"'([^']+)'", s[i:s.index("]);", i)])}


def maps():
    topic = table("fr.ts", "FR_TAG_TOPIC")
    region = table("fr.ts", "FR_TAG_REGION")
    reg = table("fr.ts", "FR_TAG_REGISTER")
    zh_topic = table("common.ts", "TOPIC_LABELS")
    zh_region = table("fr.ts", "FR_REGION_LABELS")
    zh_reg = table("common.ts", "REGISTER_LABELS")
    return topic, region, reg, zh_topic, zh_region, zh_reg


def plan(con):
    topic, region, reg, zh_topic, zh_region, zh_reg = maps()
    skip = skip_set()
    vis = {s for (s,) in con.execute("SELECT id FROM sense WHERE hidden=0")}
    have = {(s, k, v) for s, k, v in con.execute(
        "SELECT sense_id, kind, value FROM sense_tag")}
    st, ledger, broken = Counter(), Counter(), Counter()
    seen = set()
    for sid, raw in con.execute(
            "SELECT sense_id, raw_tags FROM sense_src "
            "WHERE src='fr-edition' AND sense_id IS NOT NULL"):
        if sid not in vis:
            continue
        try:
            d = json.loads(raw or "{}")
        except ValueError:
            continue
        for t in (d.get("tags") or []) + (d.get("raw_tags") or []):
            if t in skip:
                st["📋 结构标记 ⇒ 不出版"] += 1
                continue
            if t in topic:
                kind, val, zh = "topic", topic[t], zh_topic
            elif t in region:
                kind, val, zh = "region", region[t], zh_region
            elif t in reg:
                kind, val, zh = "register", reg[t], zh_reg
            elif t in zh_topic:
                kind, val, zh = "topic", t, zh_topic
            elif t in zh_region:
                kind, val, zh = "region", t, zh_region
            elif t in zh_reg:
                kind, val, zh = "register", t, zh_reg
            else:
                ledger[t] += 1
                continue
            if val not in zh:
                broken[t + " → " + val] += 1      # 分桶表指向了不存在的中文键
                continue
            if (sid, kind, val) in have or (sid, kind, val) in seen:
                st["已有同样的行 ⇒ 跳过"] += 1
                continue
            seen.add((sid, kind, val))
            st["可新增 · " + kind] += 1
    return sorted(seen), ledger, broken, st


def gates(con, rows, ledger, broken):
    ok = True

    def g(name, bad, n):
        nonlocal ok
        print("  %s %s：%s / %s" % ("✅" if not bad else "🔴", name, f(bad), f(n)))
        if bad:
            ok = False

    _t, _r, _g, zh_topic, zh_region, zh_reg = maps()
    zh = {"topic": zh_topic, "region": zh_region, "register": zh_reg}
    g("① 每条新行都映射得出中文",
      sum(1 for _s, k, v in rows if v not in zh[k]), len(rows))
    g("② 分桶表指向了不存在的中文键", sum(broken.values()), len(rows))
    vis = {s for (s,) in con.execute("SELECT id FROM sense WHERE hidden=0")}
    g("③ 只挂在可见义项上", sum(1 for s, _k, _v in rows if s not in vis), len(rows))
    skip = skip_set()
    g("④ 结构标记一条都没混进来",
      sum(1 for _s, _k, v in rows if v in skip), len(rows))
    have = {(s, k, v) for s, k, v in con.execute(
        "SELECT sense_id, kind, value FROM sense_tag")}
    g("⑤ 不与已有行重复", sum(1 for r in rows if r in have), len(rows))
    tot = sum(ledger.values())
    print("  ℹ️ 映射不出、**不出版**的：%s 行 / %s 种（长尾）" % (f(tot), f(len(ledger))))
    for k, v in ledger.most_common(8):
        print("       %-32s %s" % (k, f(v)))
    if broken:
        print("  🔴 分桶表指向不存在的中文键：")
        for k, v in broken.most_common(10):
            print("       %-46s %s" % (k, f(v)))
    return ok


SRC_MARK = "fr-edition:tags"


def undo():
    with dbtool.session("keep-v3-fr-tags-undo", expect={}) as s:
        n = s.execute("SELECT COUNT(*) FROM sense_tag").fetchone()[0]
    print("🔴 `sense_tag` 没有 src 列，撤不了单批 —— 用备份回滚（见 dbtool 的 .bak）")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    if a.undo:
        return undo()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, ledger, broken, st = plan(con)
    print("■ 可新增 %s 行，涉及 %s 条可见义项"
          % (f(len(rows)), f(len({s for s, _k, _v in rows}))))
    for k, v in st.most_common(8):
        print("   %-30s %s" % (k, f(v)))
    c = Counter(k for _s, k, _v in rows)
    print("   分桶：%s" % dict(c))
    print("\n── 新增值分布（前 16）──")
    for k, v in Counter("%s/%s" % (k, v) for _s, k, v in rows).most_common(16):
        print("   %-30s %s" % (k, f(v)))
    print("\n══ 闸 ══")
    ok = gates(con, rows, ledger, broken)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-fr-tags", expect={"#sense_tag": len(rows)}) as s:
        s.executemany("INSERT INTO sense_tag(sense_id,kind,value) VALUES(?,?,?)", rows)
    print("✓ 写入 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
