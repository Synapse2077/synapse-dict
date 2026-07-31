#!/usr/bin/env python3
"""b_ipa.py G2P 规则**体检** —— 拿 kaikki 当真值,量出规则的系统性偏差。零成本,不调模型。
见对话 2026-07-31(用户要求"别再独自判断"之后的第一步)。

⭐ 为什么这一步必须排在花钱问模型之前:
   kaikki 有 14 万条人工音位式,是现成的真值。规则错在哪、错多少、什么音境下错,
   **确定性逐字比对能给出判官永远给不出的精度**。见 [[llm-as-evaluator-discipline]] ⑩
   「能确定性回源比对的根本别问模型」。问模型只该问那些**真值本身也说不清**的点。

⚠️ 一个已知刺眼样例(普查里发现,正是本脚本的由来):
     acceptable   kaikki akθepˈtable   规则 aɡθebˈtable
   规则把 coda 浊化套到了 /p/ 上,kaikki 没有。而上午的结论是"规则对齐 kaikki、98.42% 一致"。
   到底谁对、差在哪几类音境 —— 本脚本给出全量答案,而不是靠抽样印象。

判据:对**每个 kaikki 有音位式的词**跑 `b_ipa.word_to_ipa`,逐字比。不一致的用 difflib
      对齐,抽出 (kaikki 片段 → 规则片段) 的替换对并计数 —— 得到系统性偏差排行。

read-only。用法(在 es/ 目录):
  python3 rule_audit.py                 # 全量体检
  python3 rule_audit.py --top 40        # 多看几类偏差
  python3 rule_audit.py --pair 'p→b'    # 钻取某一类偏差的例词
"""
import argparse, difflib, sqlite3, time
from collections import Counter, defaultdict
from pathlib import Path

import kaikki_util
from b_ipa import word_to_ipa

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-es.sqlite"


def diff_pairs(src, dst):
    """(kaikki, 规则) → [(kaikki片段, 规则片段)]。相等段跳过,只留替换/增删。"""
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, src, dst, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.append((src[i1:i2] or "∅", dst[j1:j2] or "∅"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--pair", help="钻取某类偏差,格式 'kaikki片段→规则片段'")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT word, phonetic, is_lemma FROM dict WHERE TRIM(COALESCE(phonetic,''))<>''"
    ).fetchall()
    conn.close()
    layer = {}
    for w, p, isl in rows:
        layer.setdefault(w, "lemma" if isl else "变形层")
    dbval = {}
    for w, p, isl in rows:
        dbval.setdefault(w, p)
    print(f"库内有音标的词形 {len(layer):,},取 kaikki 真值中…", flush=True)

    t0 = time.time()
    kk = kaikki_util.phonemic_ipa(set(layer))
    print(f"  kaikki 音位式 {len(kk):,} 词 ({time.time()-t0:.0f}s)", flush=True)

    tally = Counter()          # (layer, 结果)
    pairs = Counter()          # (kaikki片段, 规则片段)
    pair_ex = defaultdict(list)
    side = Counter()           # 规则与 kaikki 不一致时,库里站哪边
    for w, kv in kk.items():
        rv = word_to_ipa(w)
        if rv is None:
            tally[(layer[w], "规则算不出")] += 1
            continue
        rv = rv.strip("/")
        if rv == kv:
            tally[(layer[w], "规则与kaikki一致")] += 1
            continue
        tally[(layer[w], "规则与kaikki不一致")] += 1
        side["库=kaikki" if dbval[w] == kv else
             "库=规则" if dbval[w] == rv else "库=第三种值"] += 1
        for pr in diff_pairs(kv, rv):
            pairs[pr] += 1
            if len(pair_ex[pr]) < 5:
                pair_ex[pr].append((w, kv, rv))

    if a.pair:
        s, d = a.pair.split("→")
        print(f"\n■ 偏差 {s}→{d} 的例词({pairs[(s,d)]:,} 处):")
        for w, kv, rv in pair_ex[(s, d)]:
            print(f"    {w[:26]:28} kaikki {kv[:30]:32} 规则 {rv[:30]}")
        return

    print("\n" + "=" * 74)
    print(f"{'':22}{'lemma':>12}{'变形层':>14}{'合计':>12}{'占比':>9}")
    print("=" * 74)
    tot = sum(tally.values())
    for k in ("规则与kaikki一致", "规则与kaikki不一致", "规则算不出"):
        l, i = tally[("lemma", k)], tally[("变形层", k)]
        print(f"{k:22}{l:>12,}{i:>14,}{l+i:>12,}{100*(l+i)/tot:>8.2f}%")
    print("-" * 74)
    cmp_tot = sum(tally[(x, k)] for x in ("lemma", "变形层")
                  for k in ("规则与kaikki一致", "规则与kaikki不一致"))
    ok = tally[("lemma", "规则与kaikki一致")] + tally[("变形层", "规则与kaikki一致")]
    print(f"可比对 {cmp_tot:,} 词,规则逐字准确率 {100*ok/cmp_tot:.2f}%")

    print(f"\n■ 规则与 kaikki 不一致时,**库里现在站哪边**(共 {sum(side.values()):,} 词):")
    for k, v in side.most_common():
        print(f"    {k:14}{v:>10,}{100*v/sum(side.values()):>8.1f}%")

    print(f"\n■ 系统性偏差排行(kaikki 片段 → 规则片段),前 {a.top}:")
    print(f"  {'kaikki':>10} → {'规则':10}{'处数':>9}   例词")
    for (s, d), n in pairs.most_common(a.top):
        w, kv, rv = pair_ex[(s, d)][0]
        print(f"  {s:>10} → {d:10}{n:>9,}   {w[:20]:22} {kv[:26]:28} {rv[:26]}")


if __name__ == "__main__":
    main()
