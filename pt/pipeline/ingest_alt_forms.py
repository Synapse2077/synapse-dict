#!/usr/bin/env python3
"""阶段 2f：**空白词形的异体指针接进关系层** —— 空白页的第二块。2026-08-31。

═══ 这批为什么不在 2c 里 ═══
2c（变形层补链）读各版的 `forms` 表，但它有三条**有意的**判据，其中一条是
`is_inflection(tags)` —— **非屈折不收**。`['alternative']` 正是非屈折：
`Affonso` 不是 `Afonso` 的变位形式，是它的**旧拼写异体**。
所以这批不是「2c 漏了」，是**它们的家在关系层不在变形层**（`sense_relation.kind='alt_of'`）。

⇒ 本步只做一件事：把「空白词形 → 有内容的父词」这条异体指针补进关系层。

═══ 判据（四条，都要）═══
① 源头 `forms` 行的 tags 含 `alternative`（结构化字段，不解析散文）
② **父词页面不是"纯指针页"** —— 判据 import 自 2c 的同一段逻辑（变形页的变位表里
   列的是**兄弟形式**，照收会写出「A 是 B 的异体」而两个都是变形）
③ **父词自己有可见义项** —— 否则等于把空白指向空白，读者点过去还是空
④ 词形当前是**空白页**（无可见义项、无变形行、无 entry）—— 本步的目的是让空白页有内容，
   不是把源头每条 alternative 都搬进来（同 2d 的范围判据）

⚠️ 回源逐条核过三条：`taxa` 的 forms 里确实写着 `dassa ['alternative']`、
   `colchete → corchete`、`cachemir → caxemir`，**原样对上**。

🔴 **接之前先补了展示层**：`dict-core` 的 `altOf` 一直在返回，而
   `PortugueseEntryView` **那一行漏了写** ⇒ 库里 7,947 条 `alt_of`
   从阶段 8 那天起一个用户都没看见（与 it 那次同一形状）。
   先让它渲染、并加契约闸断言，再灌新数据 —— 否则这一步等于往看不见的地方倒东西。

用法（在 pt/ 目录下）：
    python3 -u pipeline/ingest_alt_forms.py
    python3 -u pipeline/ingest_alt_forms.py --apply
"""
import argparse
import collections
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from link_table_forms import EDITIONS, opener, is_inflection   # noqa: E402
from intake_edition_words import norm_apos                     # noqa: E402


def scan(con):
    blank = {w: i for w, i in con.execute("""
        SELECT d.word, d.id FROM dict d
         WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id
                           AND COALESCE(s.hidden,0)=0)
           AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)
           AND NOT EXISTS(SELECT 1 FROM entry e WHERE e.word_id=d.id)""")}
    have = {w for (w,) in con.execute(
        "SELECT DISTINCT d.word FROM dict d JOIN sense s ON s.word_id=d.id "
        " WHERE COALESCE(s.hidden,0)=0")}
    stat, cand = collections.Counter(), {}
    for ed, (path, filt) in EDITIONS.items():
        if not path.exists():
            continue
        with opener(path) as fh:
            for ln in fh:
                if '"forms"' not in ln:
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if filt and e.get("lang_code") != "pt":
                    continue
                w = norm_apos((e.get("word") or "").strip())
                sn = e.get("senses") or []
                # ② 判据与 2c 同一条：整页只有指针 ⇒ 它的 forms 表列的是兄弟形式
                if all(bool(x.get("form_of") or x.get("alt_of")) for x in sn):
                    stat["② 父词是纯指针页（不收）"] += 1
                    continue
                for fm in (e.get("forms") or []):
                    x = norm_apos(fm.get("form") or "")
                    if x == w or x not in blank:      # ④ 只管空白页
                        continue
                    tags = set(fm.get("tags") or [])
                    if is_inflection(tags):
                        stat["屈折（2c 的地盘，不在这里收）"] += 1
                    elif "alternative" not in tags:
                        stat["① 不是 alternative（不收）"] += 1
                    elif w not in have:
                        stat["③ 父词自己也是空的（不收）"] += 1
                    else:
                        stat["✅ 可接"] += 1
                        cand.setdefault(x, (blank[x], w, ed))
    return cand, stat


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    f = lambda n: format(n, ",")
    cand, stat = scan(con)
    for k, v in stat.most_common():
        print("   %9s  %s" % (f(v), k))
    print("\n■ 可接异体 %s 个空白词形" % f(len(cand)))
    random.seed(11)
    print("\n■ 抽 12 条人眼核（父词的中文一并打出来 —— 读者真正要的是它）：")
    for x, (_i, w, ed) in random.sample(list(cand.items()), min(12, len(cand))):
        zh = con.execute(
            "SELECT g.text FROM sense s JOIN dict d ON d.id=s.word_id "
            "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' "
            " WHERE d.word=? AND COALESCE(s.hidden,0)=0 LIMIT 1", (w,)).fetchone()
        print("   %-22s → %-16s %s [%s]" % (x[:22], w[:16], (zh[0] if zh else "（无中文）")[:24], ed))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    rows = [(wid, w, ed, "alt-form:%d:%s" % (wid, w)) for _x, (wid, w, ed) in cand.items()]
    with dbtool.session("ingest-pt-alt-forms",
                        expect={"#sense_relation": len(rows)}) as s:
        s.executemany(
            "INSERT INTO sense_relation(word_id, sense_id, kind, target, src, src_ref) "
            "VALUES(?,NULL,'alt_of',?,?,?)", rows)
    print("\n✓ 关系层 +%s 条 alt_of" % f(len(rows)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
