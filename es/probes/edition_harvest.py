#!/usr/bin/env python3
"""西语版 dump 一次扫完：**人工音标 + Commons 录音**，只测落点、不写库。2026-08-01。

═══ 为什么合成一趟 ═══
用户 2026-08-01 定的工程纪律：**按语种成批做，不按字段横切** ——
一个语种轮到了就把该语种能做的一次做完，避免同一份 dump 反复扫、同一张表反复写。
所以音标(①)和录音(④)共用这一趟扫描。

═══ 🔴 只测落点，不测源头 ═══
今天同一个错误犯了十次：报「源头有 X 万」而不是「能落到我们库里 Y 行」。
本脚本**所有数字都以库里的行为分母**。

═══ 已知必须处理的坑 ═══
· `sounds` 是列表，第一个不代表全部 —— 西语版同时给 seseante / 非 seseante 两种变体，
  只取第一个曾让我断言"西语版没用"。用 `sounds_variants` 看全貌。
· 音位式与严式可能拼在一串（`/ˈɡɾaθjas/ [ˈɡɾa.θjas]`）→ `parse_ipa` 只取第一对定界符内。
· X-SAMPA 是**标签**不是格式，`DROP_TAGS` 排除。
· 语言版是**多语种**词典（es 版 853 种语言，西语占 84.5%）→ 按 lang_code 过滤。

用法（在 es/ 目录）：
    python3 probes/edition_harvest.py --scan     # 扫 dump → work/es_edition_harvest.jsonl
    python3 probes/edition_harvest.py --report   # 对着库算落点
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3
import time

import ipa_norm
import kaikki_util as K
import paths

CACHE = paths.WORK / "es_edition_harvest.jsonl"


def scan():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    total = kept = 0
    agg = {}
    for w, e in K.iter_edition():
        total += 1
        if e.get("lang_code") != "es":
            continue
        kept += 1
        var = K.sounds_variants(e)
        aud = K.audio_urls(e)
        if not var and not aud:
            continue
        r = agg.setdefault(w, {"word": w, "var": [], "aud": [], "seen": set()})
        for ip, tags in var:
            if ip not in r["seen"]:
                r["seen"].add(ip)
                r["var"].append([ip, list(tags)])
        for u, fn, tags in aud:
            r["aud"].append([u, fn, list(tags)])
    with open(CACHE, "w", encoding="utf-8") as f:
        for r in agg.values():
            r.pop("seen")
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"■ 扫 {total:,} 行，西语条目 {kept:,}（{time.time()-t0:.0f}s）")
    print(f"    有音标或录音的词形 {len(agg):,}")
    print(f"→ {CACHE}")


def load_cache():
    d = {}
    for ln in open(CACHE, encoding="utf-8"):
        r = json.loads(ln)
        d[r["word"]] = r
    return d


def report():
    ed = load_cache()
    conn = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT word, is_lemma, phonetic, phonetic_src FROM dict").fetchall()
    conn.close()
    n = len(rows)

    # ── 变体 tag 全貌（决定 seseo 取哪一条，先看清再定）──────────────
    tagc = collections.Counter()
    nvar = collections.Counter()
    for r in ed.values():
        nvar[len(r["var"])] += 1
        for _, tags in r["var"]:
            tagc[tuple(tags) or ("(无 tag)",)] += 1
    print("■ 西语版读音变体 —— 每词变体数分布")
    for k in sorted(nvar):
        print(f"    {k} 个变体 : {nvar[k]:8,} 词")
    print("\n■ 变体 tag 组合 top15（**决定 seseo 取哪条之前必须先看这个**）")
    for t, c in tagc.most_common(15):
        print(f"    {c:8,}  {'+'.join(t)}")

    # ── 落点：以库里的行为分母 ────────────────────────────────────────
    have_ipa = sum(1 for r in ed.values() if r["var"])
    have_aud = sum(1 for r in ed.values() if r["aud"])
    print(f"\n■ 西语版侧：有音标的词形 {have_ipa:,} | 有录音的词形 {have_aud:,}")

    land_ipa = collections.Counter()
    land_aud = collections.Counter()
    same = diff = 0
    for w, lem, ph, src in rows:
        e = ed.get(w)
        key = (("lemma" if lem else "变形"), src or "(NULL)")
        if e and e["var"]:
            land_ipa[key] += 1
            new = ipa_norm.normalize(w, e["var"][0][0])
            if ph:
                if new == ph:
                    same += 1
                else:
                    diff += 1
        if e and e["aud"]:
            land_aud[key] += 1

    print(f"\n■ 落点 —— 音标（分母＝库里 {n:,} 行）")
    tot = sum(land_ipa.values())
    for k in sorted(land_ipa, key=lambda x: -land_ipa[x]):
        print(f"    {k[0]:5} / 现 src={k[1]:12} {land_ipa[k]:8,}")
    print(f"    合计 {tot:,}  ({tot*100/n:.1f}% 的库行能拿到西语版人工音标)")
    print(f"    其中与现值**逐字相同** {same:,} / 不同 {diff:,}")

    print(f"\n■ 落点 —— 录音（分母＝库里 {n:,} 行）")
    tota = sum(land_aud.values())
    for k in sorted(land_aud, key=lambda x: -land_aud[x]):
        print(f"    {k[0]:5} / 现 src={k[1]:12} {land_aud[k]:8,}")
    print(f"    合计 {tota:,}  ({tota*100/n:.1f}%)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.scan or not CACHE.exists():
        scan()
    if a.report:
        report()


if __name__ == "__main__":
    main()
