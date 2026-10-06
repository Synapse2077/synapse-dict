#!/usr/bin/env python3
"""W15 的后一半：把指针义项**指向的那个词形**填进 `sense_src.pointer_target`。vi，2026-10-03。

═══ 为什么要一列，而不是在展示层抠 ═══
🔴 指针的 `text` 是**自由文本**：
      `initialism of Hoa Kỳ (= United States): a country in North America: US`
      `alternative form of 馭 (“chữ Nôm form of ngựa (“horse”)”)`
   从它里面用正则抠目标是**拿形式代理当内容判据**（`[[criteria-from-meaning-not-form]]`），
   而源头给了**结构字段** `form_of` / `alt_of` 的 `word`。
   词源层已经立过同一条规矩：`etym_type` 靠源头的 `etymology_templates` 不靠正则猜。

═══ 🔴🔴 规模：账上写的和实际能做的差一个数量级 ═══
`W15` 写的是「把指针印成可点链接」。实测（**量落点不量源头**）：

    只有指针的词形            16,305
      ▸ 至少一条指针跳得动       1,375  ( 8.4%)
      ▸ 目标是汉字/无结构字段    14,846  (91.1%)
      ▸ 其余                       84

    222 个真空白页里：有指针 222 ／ **跳得动 160（72%）**

那 91.1% 的目标是 `Sino-Vietnamese reading of 海` 这类**汉字**，而汉字按用户 2026-09-28
的决定**不进 `dict`** ⇒ 给它们做链接就是 **W9 刚清掉的那种死链**（`nhà` 的「相关」里
印着波兰语 `kościół`、`target_id` 解析得上的 0 行）。
⇒ **目标在 `dict` 里才可点，否则纯文本** —— 这是关系层 `target_id` 为 NULL 时的既有约定，
  不是我新发明的政策。
⚠️ 回报最高的那一块是 **222 个真空白页里的 160 个**：它们现在**整页一个字都没有**。

═══ 判据只有一个家 ═══
`criteria.is_pointer_sense()` 决定「哪条义项是指针」（阶段 5a 建的，三路取并）。
本脚本**不重判**，只在它说是指针的那些上取 `form_of`/`alt_of`。
键用 `sense_src.src_ref` 的同一个公式 —— ⚠️ **不许 `split(':')` 反解析**
（词形本身可能含冒号，ja 那边栽过：1,866 条只对上 1,091 而**对不上的静默漏修**）。

用法：
    python3 -u vi/fixes/fill_pointer_target.py            # 只报
    python3 -u vi/fixes/fill_pointer_target.py --apply
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import build_v3_schema as SCHEMA                          # noqa: E402
import dbtool                                             # noqa: E402
import paths                                              # noqa: E402
from criteria import (is_pointer_sense, is_han_headword,    # noqa: E402
                      pointer_class, PTR_POINTER, PTR_SPELLING, PTR_OTHER)

F = lambda n: format(n, ",")                              # noqa: E731

# 🔴 **只有这三版有义项**（三语方针），所以只有它们的指针义项在 `sense_src` 里。
#    ⚠️ 键里的版本名是**两字母**（`sense:en:…`），与 `S6.EDITIONS` 的全名不同 ——
#      这是阶段 5a 定的键格式，照它来。
PATH_OF = [("en", paths.KK), ("vi", paths.EDITION),
           ("zh", paths.ZH_TRAD), ("zh", paths.ZH_SIMP)]


def collect(con):
    """→ ({src_ref: 目标词形}, 统计)。**只读 dump，不判「是不是指针」**。"""
    want = {r[0] for r in con.execute(
        "SELECT src_ref FROM sense_src WHERE sense_id IS NULL")}
    stat = collections.Counter()
    out = {}
    for ed, p in PATH_OF:
        if not p.exists():
            stat["切片不在：%s" % p.name] += 1
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                w = (d.get("word") or "").strip()
                pos = d.get("pos")
                etym = str(d.get("etymology_number", "0") or "0")
                for si, s in enumerate(d.get("senses") or []):
                    # ⚠️ `gi` 要按 gloss 数展开 —— 一条义项可能有多条 gloss，
                    #    而 `src_ref` 的最后一节是 gloss 序号（阶段 5a 的键格式）。
                    for gi in range(max(1, len(s.get("glosses") or []))):
                        ref = "sense:%s:%s:%s:%s:%d:%d" % (ed, w, pos, etym, si, gi)
                        if ref not in want:
                            continue
                        if not is_pointer_sense(s):
                            # 🔴 库里是指针（`sense_id IS NULL`）而源头侧判据说不是 ⇒
                            #    两边口径不一致，必须报出来而不是静默跳过。
                            stat["🔴 库里是指针而源头判据说不是"] += 1
                            continue
                        fo = s.get("form_of") or s.get("alt_of")
                        t = (fo[0].get("word") or "").strip() if fo else ""
                        if t:
                            out[ref] = t
                            stat["源头给了结构性目标"] += 1
                        else:
                            stat["源头没给结构字段（多半目标是汉字）"] += 1
    stat["库里的指针义项"] = len(want)
    stat["对上的"] = stat["源头给了结构性目标"] + stat["源头没给结构字段（多半目标是汉字）"]
    return out, stat


def classify(con):
    """→ {src_ref: PTR_*}。**判据 import 自 `criteria.pointer_class`，这里不重判。**

    ⚠️ 判据要「这个词自己的表记」当第二个参数 ⇒ 先把表记按 word_id 取齐。
    """
    sp = collections.defaultdict(list)
    for wid, t in con.execute("SELECT word_id, han FROM han_spelling"):
        sp[wid].append(t)
    for wid, t in con.execute("SELECT word_id, nom FROM nom_spelling"):
        sp[wid].append(t)
    out, stat = {}, collections.Counter()
    for ref, wid, text in con.execute(
            "SELECT src_ref, word_id, text FROM sense_src WHERE sense_id IS NULL"):
        k = pointer_class(text, sp.get(wid, []))
        out[ref] = k
        stat[k] += 1
    return out, stat


def report(con, tgt):
    indict = {w for (w,) in con.execute("SELECT word FROM dict")}
    link = {r: t for r, t in tgt.items() if t in indict}
    han = sum(1 for t in tgt.values() if t not in indict and is_han_headword(t))
    print("\n■ 取到结构性目标 %s 条" % F(len(tgt)))
    print("   ▸ **目标在 `dict` 里 ⇒ 可点** %s 条" % F(len(link)))
    print("   ▸ 目标是汉字（有意不进 dict）    %s 条" % F(han))
    print("   ▸ 目标不在 dict 也不是汉字       %s 条  ← 这些印成纯文本" %
          F(len(tgt) - len(link) - han))
    # 🔴 **读者口径**：有多少「只有指针」的词形真的多出一条可点链接
    byw = collections.defaultdict(list)
    for r, t in tgt.items():
        wid = con.execute("SELECT word_id FROM sense_src WHERE src_ref=?", (r,)).fetchone()
        if wid:
            byw[wid[0]].append(t)
    only_ptr = {r[0] for r in con.execute(
        "SELECT d.id FROM dict d WHERE EXISTS(SELECT 1 FROM sense_src s "
        " WHERE s.word_id=d.id AND s.sense_id IS NULL) AND NOT EXISTS("
        " SELECT 1 FROM sense WHERE word_id=d.id AND hidden=0)")}
    gain = sum(1 for w in only_ptr if any(t in indict for t in byw.get(w, ())))
    print("\n■ **读者口径**：只有指针的 %s 个词形里，**%s 个**至少多出一条可点链接（%.1f%%）"
          % (F(len(only_ptr)), F(gain), 100.0 * gain / max(len(only_ptr), 1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(sense_src)")}
    if "pointer_target" not in cols:
        print("■ `sense_src.pointer_target` 还不存在 —— 它登记在 "
              "`build_v3_schema.ADD_COLUMNS` 里，由本脚本的写库事务补上。")
    tgt, stat = collect(con)
    for k, v in stat.most_common():
        print("   %-40s %8s" % (k, F(v)))
    report(con, tgt)
    cls, cstat = classify(con)
    print("\n■ `ptr_class`（展示层该怎么对待这一行）")
    for k, v in cstat.most_common():
        print("   %-12s %8s (%.2f%%)" % (k, F(v), 100.0 * v / max(len(cls), 1)))
    # 🔴 **读者口径**：只有指针的词形里，指针区真的印得出东西的有多少
    vis = con.execute(
        "SELECT COUNT(DISTINCT s.word_id) FROM sense_src s JOIN dict d ON d.id=s.word_id "
        "WHERE s.sense_id IS NULL AND NOT EXISTS("
        "  SELECT 1 FROM sense WHERE word_id=d.id AND hidden=0)").fetchone()[0]
    print("   ⇒ 只有指针的词形 %s 个；按新分类，指针区会**只印真指针**" % F(vis))
    con.close()
    if not a.apply:
        print("\n(只报不写。加 --apply。)")
        return
    rows = [(t, r) for r, t in sorted(tgt.items())]
    crows = [(k, r) for r, k in sorted(cls.items())]
    with dbtool.session("vi-w15-pointer-target",
                        expect={"__rows__": 0,
                                "sense_src.pointer_target": len(rows),
                                "sense_src.ptr_class": len(crows)},
                        invalidates=[]) as s:
        # 🔴 **列先补上再写**：`ADD_COLUMNS` 是建表那一侧的登记表，
        #    这里调它而不是自己写 `ALTER TABLE` —— 两份 DDL 迟早漂开。
        have = {r[1] for r in s.execute("PRAGMA table_info(sense_src)")}
        for tbl, col, typ in SCHEMA.ADD_COLUMNS:
            if tbl == "sense_src" and col not in have:
                s.execute("ALTER TABLE sense_src ADD COLUMN %s %s" % (col, typ))
        s.executemany("UPDATE sense_src SET pointer_target=? WHERE src_ref=?", rows)
        s.executemany("UPDATE sense_src SET ptr_class=? WHERE src_ref=?", crows)


if __name__ == "__main__":
    main()
