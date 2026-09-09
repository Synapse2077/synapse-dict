#!/usr/bin/env python3
"""阶段 -1 探针 D：`pronunciation` 表要不要 `pos` / `entry_id` 列。2026-09-07。

═══ 为什么现在量 ═══
`PLAYBOOK`：**结构在写第一行业务代码前定死**。fr 是做到阶段 8 之后才发现读音要按词性归位，
补列是返工；de 因此一开始就带 `pos` + `entry_id`。
`[[es-v3-structure-backfill]]`：**照搬别的语言结构前，先量这门语言有没有那个病。**

🔴 **这两个探针从没在英语上跑过。** `DE_PLAN` §2.1 那张表里的「de 版 / en 版」
   是两个 **wiktionary 版本**（都在量德语词），不是「德语 / 英语」——
   我一度读成后者，差点把 72 / 276 当成英语的数字写进 `EN_PLAN` §2.2。

═══ 两个口径，缺一个就会做错决定 ═══
① 跨**词性**读音不同        → 需要 `pos` 列       （德语 `Job` 姓氏 vs 外来词）
② 同词性、跨**词条**不同    → 需要 `entry_id` 列   （德语 `übersetzen` 翻译 vs 摆渡）
口径①按 (词形,词性) 归并，**看不见②**。

═══ 英语的先验（只用来说明该量什么，不替代量）═══
英语有一整族**重音区分词性**的最小对立，而且**意思相关但不同**：
    récord /ˈɹɛkɔːd/ 名词  vs  recórd /ɹɪˈkɔːd/ 动词
    présent / presént ｜ óbject / objéct ｜ cónduct / condúct ｜ pérmit / permít
还有同形异读异义（`lead` 铅 /lɛd/ vs 引导 /liːd/、`bow` 弓 /baʊ/ vs 鞠躬 /boʊ/、`tear`、`read`）。
⇒ 先验很强，但**建不建列由数字决定**。

判据（照 de，一字不改）：
  · 音标逐字节比，**不归一** —— 归一会把要找的差异抹掉，那正是我们要数的东西
  · 同一 (词形,词性) 内部多读音是**正常的**（英美/方言），不算
  · 只有**集合不相等**才算；再滤一遍**互不为子集**（否则只是一版收得多一版收得少）
  · 占位符不当读音（`[[…]]` 那一族，本轮已在探针 B 上栽过一次）

跑：  cd en && python3 probes/pron_shape.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json

import paths
from probes.edition_english import real_ipas      # 判据只许一份：占位符怎么剔

OUT = paths.WORK / "probe"


def main():
    # ① (词形, 词性) → 该组所有读音；② (词形, 词性) → [每个条目自己的读音集合]
    bypos = collections.defaultdict(lambda: collections.defaultdict(set))
    groups = collections.defaultdict(list)
    for line in open(paths.KK, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        w, pos = d.get("word"), d.get("pos")
        if not w or not pos:
            continue
        ipas = real_ipas(d)
        if not ipas:
            continue
        bypos[w][pos] |= ipas
        groups[(w, pos)].append(frozenset(ipas))

    # ── 口径①
    multi = {w: v for w, v in bypos.items() if len(v) > 1}
    diff1 = {w: v for w, v in multi.items()
             if len({frozenset(s) for s in v.values()}) > 1}
    strict1 = {w: v for w, v in diff1.items()
               if not any(a < b or b < a
                          for a in map(frozenset, v.values())
                          for b in map(frozenset, v.values()) if a != b)}
    # ── 口径②
    multi2 = {k: v for k, v in groups.items() if len(v) > 1}
    diff2 = {k: v for k, v in multi2.items() if len(set(v)) > 1}
    strict2 = {k: v for k, v in diff2.items()
               if not any(a < b or b < a for a in set(v) for b in set(v) if a != b)}

    print("══ 口径① 跨词性读音不同（要不要 `pos` 列）══")
    print("   带音标的词形                %s" % format(len(bypos), ","))
    print("   跨 pos 出现（≥2 个词性）    %s" % format(len(multi), ","))
    print("   🔴 跨 pos 读音集合不相等    %s" % format(len(diff1), ","))
    print("   其中互不为子集（真对立）    %s" % format(len(strict1), ","))
    print("   样本：")
    for w in sorted(strict1)[:14]:
        print("      %-16s %s" % (w[:16], " ｜ ".join(
            "%s %s" % (k, "/".join(sorted(v))[:34]) for k, v in sorted(bypos[w].items()))))

    print("\n══ 口径② 同词性跨词条读音不同（要不要 `entry_id` 列）══")
    print("   带音标的 (词形,词性) 组     %s" % format(len(groups), ","))
    print("   同组 ≥2 个独立词条          %s" % format(len(multi2), ","))
    print("   🔴 同组各词条读音不同       %s 组 / %s 个词形"
          % (format(len(diff2), ","), format(len({w for w, _ in diff2}), ",")))
    print("   其中互不为子集（真对立）    %s" % format(len(strict2), ","))
    print("   样本：")
    for k in sorted(strict2, key=lambda x: (-len(groups[x]), x))[:14]:
        print("      %-14s %-6s %s" % (k[0][:14], k[1],
              "  ｜  ".join("/".join(sorted(s))[:24] for s in groups[k][:4])))

    (OUT / "pron_shape.json").write_text(json.dumps({
        "words_with_ipa": len(bypos),
        "cross_pos_multi": len(multi), "cross_pos_diff": len(diff1),
        "cross_pos_strict": len(strict1),
        "groups": len(groups), "multi_entry_groups": len(multi2),
        "entry_diff_groups": len(diff2), "entry_diff_words": len({w for w, _ in diff2}),
        "entry_diff_strict": len(strict2),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
