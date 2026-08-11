#!/usr/bin/env python3
"""把 `fix_x_gs.py` 的修复补到 **`pronunciation` 表**上。2026-08-11。

═══ 这不是新缺陷，是同一个缺陷的第二次现身 ═══
2026-08-02 `fixes/fix_x_gs.py` 把 `ɡs → ks` 修在 `dict.phonetic` 上。
2026-08-07 我新建 `pronunciation` 表，**从 kaikki dump 原样重建**，展示层跟着切过去
（`spanish.ts:530` 读 `notation='phonemic' AND is_primary=1`）。
修复留在旧列里，用户看到的是新表 ⇒ `extremo` 又变回 `eɡsˈtɾemo`。

这一类叫「**被绕过**」：数据还在原列、查那一列一切正常，只有查**读取路径**才看得见。
`tests/test_no_regression.py` 就是为这一类建的（同一判据在两列上各查一次）。

═══ 🔴 为什么只补这一族，另外 91 条不动 ═══
`fix_ipa_nonspanish.py` 写着一条硬规矩：
    「**不许动的白名单**：当前值与 kaikki 逐字相同的行。
      本项目既定策略是 IPA 归信人工源 kaikki，kaikki 写什么就是什么。」
`pronunciation` **整张表就是从 kaikki 建的** ⇒ 按这条规矩，
w̝(86) / 严式附加符(3) / 词首ɾ(1) / ʒ(1) 这 91 条**本来就不该动**，
它们进 `docs/KNOWN-ISSUES.md`，不进修复循环。

`ɡs` 是唯一的例外，因为它当初不是靠"看着不像西语"判的，是靠**跨版权威源裁决**：
西语版对这批词写 `ks`，写 `ɡs` 的是 0。2026-08-11 我重新回源核过一遍（见下方验收），
1,770 个对照词形里西语版仍然是 `ks` 0 个 `ɡs`。

═══ 判据完全复用 `fix_x_gs.convert`，一个字不改 ═══
不重写一套 —— 那个函数里有两条防改坏的关键判据，重写必丢：
  · 数的是 **x 的连续段**（`doxxear` 的 `xx` 只读一个 /ks/）；
  · 右边数 `ɡs` **加上已经是 `ks` 的**，所以**跑第二遍不会改坏**
    （`unboxings` umˈboksinɡs：只数 ɡs 会误判 1==1 改成 umˈboksinks）。
  · 不带 x 的行（`blogs ˈbloɡs`、`gangs`、`icebergs`）一律返回 None。

用法（在 es/ 目录）：
    python3 fixes/fix_pron_x_gs.py            # 试算 + 拿西语版验收
    python3 fixes/fix_pron_x_gs.py --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import json
import sqlite3

import dbtool
import paths
from fixes.fix_x_gs import convert          # ← 判据的唯一来源


def load_edition_ipa(words):
    """从西语版 dump 取这些词的音标，当**外部锚**验收尺子。"""
    low = {w.lower() for w in words}
    out = collections.defaultdict(set)
    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            if '"lang_code"' not in line:
                continue
            d = json.loads(line)
            if d.get("lang_code") != "es":
                continue
            w = (d.get("word") or "").lower()
            if w not in low:
                continue
            for s in d.get("sounds") or []:
                ip = (s.get("ipa") or "").strip().strip("/[]")
                if ip:
                    out[w].add(ip)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("""
        SELECT p.id, d.word, p.ipa, p.notation, p.is_primary
          FROM pronunciation p JOIN dict d ON d.id = p.word_id
         WHERE p.ipa LIKE '%ɡs%'""").fetchall()
    con.close()

    plan, skip = [], collections.Counter()
    for pid, word, ipa, notation, prim in rows:
        new = convert(word, ipa)
        if new is None:
            skip["判据不满足（无 x / 对不齐 / blogs 类）"] += 1
            continue
        if new == ipa:
            skip["已经是目标值"] += 1
            continue
        plan.append((new, pid, word, ipa, notation, prim))

    print("■ `pronunciation` 里含 ɡs 的行：%d" % len(rows))
    for k, n in skip.most_common():
        print("    跳过 · %-34s %6d" % (k, n))
    print("■ 计划改 %d 行（其中展示层真正读到的 %d 行）" % (
        len(plan), sum(1 for r in plan if r[4] == "phonemic" and r[5] == 1)))

    # ── 验收：拿西语版当尺子（外部锚，不是我们自己的转换器）
    ed = load_edition_ipa({r[2] for r in plan})
    fixed = broke = neutral = nodata = 0
    for new, pid, word, ipa, _n, _p in plan:
        cand = ed.get(word.lower())
        if not cand:
            nodata += 1
            continue
        # 判据放宽到"含 ks / 含 ɡs"，不逐字比 —— 西语版写的是严式（eksˈt̪ɾakt̪o），
        # 逐字比会把所有行都判成不一致，那样量的是记法差异不是本缺陷。
        # ⚠️ 第一版把 `was_ok` 写成 `… and "ɡs" in ipa`（该是 not in）⇒「修好」恒为 0、
        #    全部落进「中性」。**一条永远给同一个答案的验收＝没有验收**，
        #    幸好它给的是 0 而不是绿灯，否则就直接落库了。
        ed_says_ks = any("ɡs" not in c for c in cand)   # 西语版不写 ɡs
        was_ok = ed_says_ks and "ɡs" not in ipa
        now_ok = ed_says_ks and "ɡs" not in new
        if now_ok and not was_ok:
            fixed += 1
        elif was_ok and not now_ok:
            broke += 1
        else:
            neutral += 1

    print("\n■ 验收（尺子＝西语版 dump，%d 行有对照）" % (fixed + broke + neutral))
    print("    ✅ 改后与西语版同向、改前不同向（修好）  %6d" % fixed)
    print("    🔴 改前同向、改后不同向（改坏）          %6d" % broke)
    print("    ·  两侧同状态（中性）                    %6d" % neutral)
    print("    ·  西语版无此词（无法验收）              %6d" % nodata)

    dbtool.sample_check(
        [(w, ipa, new, notation) for new, _pid, w, ipa, notation, _p in plan],
        n=12, cols=("词", "改前", "改后", "记法"))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库)")
        return
    if broke:
        print("\n🔴 有改坏的行，先查清再落库。", file=_sys.stderr)
        raise SystemExit(1)

    # 只改内容不改有无 ⇒ 所有列的非空计数变化都应为 0。
    with dbtool.session("pron-x-gs-to-ks", expect={}) as s:
        s.executemany("UPDATE pronunciation SET ipa=? WHERE id=?",
                      [(new, pid) for new, pid, *_ in plan])


if __name__ == "__main__":
    main()
