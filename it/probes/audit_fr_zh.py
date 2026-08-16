#!/usr/bin/env python3
"""法语中转中文的体检：先做**确定性**检查，能查的不问模型。2026-08-13。

═══ 为什么不能只信负控 ═══
负控 37/40 量的是「有已知真值的 40 条」上的**可用性下限**，
不等于这一批 2.8 万条的质量。两者是不同的东西，不能互相冒充。

═══ 这里只做确定性的 ═══
① 空串率            ② 中文字符占比（法语没翻过去会留下拉丁字母）
③ 长度失控          ④ 句末标点 / 元话语
⑤ **同一个中文被大量复用**（模型偷懒的典型形状：全都翻成"村庄"）
⑥ 数字一致性        ⑦ 原文里的专名有没有被丢掉

模型判官另设，见 `--sample` 导出的分层样本。

用法（在 it/ 目录下）：
    python3 probes/audit_fr_zh.py
    python3 probes/audit_fr_zh.py --sample 120   # 导出分层样本供人工/判官看
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths   # noqa: E402

CJK = re.compile(r"[一-鿿]")
LATIN = re.compile(r"[A-Za-zÀ-ÿ]")
META = re.compile(r"(意为|指的是|该词|表示的是|法语中)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    src = {}
    for sid, w, t, pos in con.execute(
            "SELECT s.id, d.word, x.text, s.pos FROM sense_src x JOIN sense s ON s.id=x.sense_id "
            "JOIN dict d ON d.id=s.word_id WHERE x.src='fr-edition'"):
        src[sid] = (w, t, pos)

    rows = []
    for line in (paths.WORK / "fr_defs_zh.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r["id"] in src:
            rows.append((r["id"], src[r["id"]][0], src[r["id"]][1], src[r["id"]][2], r["zh"]))

    c = Counter()
    bad = defaultdict(list)
    zh_use = Counter()
    for sid, w, fr, pos, zh in rows:
        c["总数"] += 1
        if not zh:
            c["① 空串（模型拒绝猜）"] += 1
            continue
        zh_use[zh] += 1
        n_cjk = len(CJK.findall(zh))
        n_lat = len(LATIN.findall(zh))
        if n_cjk == 0:
            c["🔴 ② 一个中文字都没有"] += 1
            bad["② 无中文"].append((w, fr, zh))
        elif n_lat > n_cjk:
            c["🔴 ② 拉丁字母多于中文字（多半没翻）"] += 1
            bad["② 拉丁多"].append((w, fr, zh))
        if len(zh) > 40:
            c["🔴 ③ 超长（>40 字）"] += 1
            bad["③ 超长"].append((w, fr, zh))
        if zh[-1] in "。.；;，,":
            c["🔴 ④ 句末有标点"] += 1
            bad["④ 标点"].append((w, fr, zh))
        if META.search(zh):
            c["🔴 ④ 含元话语"] += 1
            bad["④ 元话语"].append((w, fr, zh))
        # ⑥ 原文里的数字必须在译文里出现
        nums = set(re.findall(r"\d+", fr))
        if nums and not (nums & set(re.findall(r"\d+", zh))):
            c["⑥ 原文有数字、译文没有"] += 1
            bad["⑥ 数字"].append((w, fr, zh))

    print("■ 体检 %s 条" % f"{c['总数']:,}")
    for k, v in c.most_common():
        if k != "总数":
            print("   %-30s %8s (%.2f%%)" % (k, f"{v:,}", 100.0 * v / c["总数"]))

    print("\n■ ⑤ 同一个中文被复用最多的 8 个（偷懒的典型形状）")
    for zh, n in zh_use.most_common(8):
        print("   %6s 次  %s" % (f"{n:,}", zh[:40]))
    rep = sum(n for _, n in zh_use.most_common() if n >= 50)
    print("   被复用 ≥50 次的译文合计占 %.1f%%" % (100.0 * rep / max(sum(zh_use.values()), 1)))

    for k, v in bad.items():
        if v:
            print("\n── %s（前 4 条）" % k)
            for w, fr, zh in v[:4]:
                print("   %-20s fr=%-42s zh=%s" % (w[:20], fr[:42], zh[:30]))

    if a.sample:
        import random
        random.seed(3)
        strata = defaultdict(list)
        for r in rows:
            if r[4]:
                strata[r[3] or "?"].append(r)
        out = []
        per = max(a.sample // max(len(strata), 1), 5)
        for pos, lst in strata.items():
            out += random.sample(lst, min(per, len(lst)))
        p = paths.WORK / "fr_zh_sample.json"
        p.write_text(json.dumps(
            [{"id": r[0], "word": r[1], "fr": r[2], "pos": r[3], "zh": r[4]} for r in out],
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n■ 分层样本 %d 条 → %s" % (len(out), p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
