#!/usr/bin/env python3
"""修字母 `x` 的音标：`ɡs` → `ks`（词首 x → `s`）。2026-08-02。

═══ 缺陷 ═══
库内 14,821 行音标含 `ɡs`，其中 14,681 行词形带 `x`：
    extremo  eɡsˈtɾeme      exterior  eɡsteˈɾjoɾ      box  ˈboɡs
`ɡs` 不是西语 x 的音位式写法。**这不是我们归一造出来的** —— 回 `pre-ipanorm` 备份查过，
源头（英文版）就是 `ɡs`（应是把 [ɣs] 这个西班牙口语的浊化实现当成了音位式）。

═══ 三条证据同向 ═══
① **权威源**：西语版对这批词写 `ks` 的 7,311，写 `ɡs` 的 **0**；
② **两家共识**：豆包 pro 与 v4-pro 在此前那轮 coda 规则评审里**各自独立**把
   「`x`→/ks/ 未纳入」标成 high 严重度；
③ **本词典约定**：我们处处选音位式、弃严式（见 ipa_norm.py），/ks/ 才是音位式。
⚠️ 上一次两家共识（coda 浊化、多词次重音）**被权威源推翻**过 —— 所以这里起决定作用的
   是 ①，不是 ②。②只是让我更早看向这里。

═══ 🔴 两个必须区分的情况（不分就会改坏）═══
· **词形不带 x 的 140 行不能动**：`blogs ˈbloɡs`、`gangs ˈɡanɡs`、`icebergs iˈθebeɾɡs`
  —— 那里的 ɡ 是字母 g 的真音，s 是复数。盲目字符串替换会全毁掉。
· **词首 x 读 /s/ 不是 /ks/**：`xerocopia` 库内 `ɡseɾoˈkopja`，西语版 `seɾoˈkopja`
  —— 这 83 行要**删掉 ɡ**，不是换成 k。（西语只有词首 x 这样；examen/extremo 都是 /ks/。）

═══ 判据：x 的个数必须等于 ɡs 的个数 ═══
对不齐就整条不动（同 ipa_norm.devoice_coda 的做法：从词形取字母序列，
长度相等才动手）。这是唯一能防住"词里同时有 x 和 g"那 1,235 行的办法。

用法（在 es/ 目录）：
    python3 fixes/fix_x_gs.py            # 试算 + 拿西语版算验收
    python3 fixes/fix_x_gs.py --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import re
import sqlite3

import dbtool
import paths
from pipeline.apply_edition_confirm import (canon_edition, glide_fold, pick,
                                            stress_fold)
import ipa_norm as N


def convert(word, ph):
    """→ 修后的音标；不该动或对不齐则返回 None。"""
    if "ɡs" not in ph:
        return None
    # 数的是 **x 的连续段**不是 x 的个数：`doxxear` 的 `xx` 只读一个 /ks/
    # （全库仅 doxxear、Oxxo 两条带 xx）。
    nx = len(re.findall(r"x+", word.lower()))
    # 🔴 右边必须数 `ɡs` **加上已经是 `ks` 的**，否则本脚本**跑第二遍会改坏**：
    #    `unboxings` = `umˈboksinɡs`，x 那处已修成 ks，剩下的 ɡs 是 `ng`+复数 s 的真音。
    #    只数 ɡs 的话 1==1 成立 → 会把它改成 `umˈboksinks`。
    #    数 ɡs+ks：1 != 2 → 正确跳过。**幂等性必须写进判据，不能靠"只跑一次"。**
    if nx == 0 or nx != ph.count("ɡs") + ph.count("ks"):
        return None                      # 无 x（blogs 类）或对不齐 → 不动
    if word.lower().startswith("x") and ph.lstrip("ˈˌ").startswith("ɡs"):
        # 词首 x = /s/：删掉 ɡ，其余 ɡs 仍按 ks
        head, _, rest = ph.partition("ɡs")
        return (head + "s" + rest.replace("ɡs", "ks"))
    return ph.replace("ɡs", "ks")


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
        "SELECT id, word, phonetic, phonetic_src FROM dict WHERE phonetic LIKE '%ɡs%'"
    ).fetchall()
    conn.close()

    plan, samples, stat = [], [], collections.Counter()
    fixed = broke = neutral = nodata = 0
    for rid, w, ph, src in rows:
        new = convert(w, ph)
        if new is None or new == ph:
            stat["不动"] += 1
            continue
        stat["词首 x → s" if w.lower().startswith("x") else "ɡs → ks"] += 1
        plan.append((new, rid))
        if len(samples) < 300:
            samples.append((w, ph, new, src))
        # ── 验收：拿西语版当尺子，改前 / 改后各算一次一致 ──
        v = ed.get(w)
        if not v:
            nodata += 1
            continue
        tgt = canon_edition(N.normalize(w, canon_edition(pick(v))))
        def agree(x):
            return x == tgt or glide_fold(x) == glide_fold(tgt) or \
                   stress_fold(x) == stress_fold(tgt)
        before, after = agree(ph), agree(new)
        if after and not before:
            fixed += 1
        elif before and not after:
            broke += 1
        else:
            neutral += 1

    for k, n in sorted(stat.items()):
        print("  %-14s %8s" % (k, format(n, ",")))
    print("\n■ 计划改 {:,} 行".format(len(plan)))
    print("\n■ 验收（尺子＝西语版，共 {:,} 行有对照）".format(fixed + broke + neutral))
    print("    ✅ 改后与西语版一致、改前不一致（修好）  {:,}".format(fixed))
    print("    🔴 改前一致、改后不一致（改坏）          {:,}".format(broke))
    print("    ·  两侧同状态（中性）                    {:,}".format(neutral))
    print("    ·  西语版无此词（无法验收）              {:,}".format(nodata))

    dbtool.sample_check(samples, n=14, cols=("词", "改前", "改后", "src"))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库)")
        return
    if broke:
        print("\n🔴 有改坏的行，先查清再落库。", file=_sys.stderr)
        raise SystemExit(1)

    # phonetic 非空计数不变（只改内容不改有无），故所有列都应为 0 变化。
    with dbtool.session("x-gs-to-ks", expect={}) as s:
        s.executemany("UPDATE dict SET phonetic=? WHERE id=?", plan)


if __name__ == "__main__":
    main()
