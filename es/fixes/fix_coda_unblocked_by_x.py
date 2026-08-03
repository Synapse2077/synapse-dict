#!/usr/bin/env python3
"""补跑 coda 清音：修 `x` 之后才对得齐的那批行。2026-08-02。

═══ 来历 ═══
`fixes/fix_x_gs.py` 把 `eɡsˈtɾeme` 改成 `eksˈtɾeme` 之后，给 `ipa_norm` 的
`_coda_stops_from_spelling` 补上了字母 `x`（x=/ks/，那个 k 永远在 coda）。
补完才发现两批行**一直被挡在门外**：

  ① `ɡ` 与 `s` 之间隔着重音符 —— `seɡˈswal`、`aleɡˈsandeɾ`、`eɡˈsile`。
     fix_x_gs.py 找的是**字面量 `ɡs`**，隔一个 ˈ 就匹配不上，**漏了这一批**。
     （又一次：我的匹配器比数据窄。）
  ② 词里的其它 coda 塞音被那个假 ɡ 顶掉了对齐 —— `ekspeɡtoˈɾate` 里 `ct` 的浊化。

两批都由 `devoice_coda` 的既有算法处理（按序对齐、长度不等整条跳过），
本脚本只负责把它跑到库上并验收。

验收尺子仍是西语版：修好 N / 改坏 0 才落库。

用法（在 es/ 目录）：
    python3 fixes/fix_coda_unblocked_by_x.py
    python3 fixes/fix_coda_unblocked_by_x.py --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import json
import sqlite3

import dbtool
import ipa_norm as N
import paths
from pipeline.apply_edition_confirm import (canon_edition, glide_fold, pick,
                                            stress_fold)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    ed = {}
    for ln in open(paths.WORK / "es_edition_harvest.jsonl", encoding="utf-8"):
        r = json.loads(ln)
        if r["var"]:
            ed[r["word"]] = [(v, tuple(t)) for v, t in r["var"]]

    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word, phonetic, phonetic_src FROM dict "
        "WHERE TRIM(COALESCE(phonetic,''))<>''").fetchall()
    conn.close()

    plan, samples = [], []
    fixed = broke = neutral = nodata = 0
    for rid, w, ph, src in rows:
        new = N.devoice_coda(w, ph)
        if new == ph:
            continue
        plan.append((new, rid))
        if len(samples) < 300:
            samples.append((w, ph, new, src))
        v = ed.get(w)
        if not v:
            nodata += 1
            continue
        tgt = canon_edition(N.normalize(w, canon_edition(pick(v))))
        def agree(x):
            return x == tgt or glide_fold(x) == glide_fold(tgt) or \
                   stress_fold(x) == stress_fold(tgt)
        b, af = agree(ph), agree(new)
        if af and not b:
            fixed += 1
        elif b and not af:
            broke += 1
        else:
            neutral += 1

    print("■ 计划改 {:,} 行".format(len(plan)))
    print("\n■ 验收（尺子＝西语版，{:,} 行有对照）".format(fixed + broke + neutral))
    print("    ✅ 修好                    {:,}".format(fixed))
    print("    🔴 改坏                    {:,}".format(broke))
    print("    ·  中性                    {:,}".format(neutral))
    print("    ·  西语版无此词（无法验收） {:,}".format(nodata))
    dbtool.sample_check(samples, n=14, cols=("词", "改前", "改后", "src"))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库)")
        return
    if broke:
        print("\n🔴 有改坏的行，先查清再落库。", file=_sys.stderr)
        raise SystemExit(1)
    with dbtool.session("coda-unblocked-by-x", expect={}) as s:
        s.executemany("UPDATE dict SET phonetic=? WHERE id=?", plan)


if __name__ == "__main__":
    main()
