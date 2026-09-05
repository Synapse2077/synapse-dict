#!/usr/bin/env python3
"""收尾单 C39 后续 —— 用「我们自己的同族词形」当裁判。**🔴 这个办法失败了，本文件是负面结果。**

═══ 🔴🔴 先说结论：别用它 ═══
它报出的 16 条「已确认我方缺陷」**全部是假阳性**，而**两条已知的真错一条都没召回**。
留着这个文件是为了记住**为什么**失败，不是为了给谁再跑一遍
（`[[record-the-negative-decision]]`：判定「不该做」也是结论，要落账）。

    假阳实样  `Kurpfuscher` 我们 `ˈkuːɐ̯ˌp͡fʊʃɐ` 被判成错 —— **而它是对的**
              （德语词尾 `-er` 就是元音化成 `ɐ`；两家模型在盲测里都独立指出
                法语版写 `[əʁ]` 才是那一侧的系统性错误）
    漏报实样  `Bretone`（真错）没被召回

═══ 两个根因，都是「判据比它要描述的东西宽/窄」═══
① **「同族」取 `base_id` 太窄。** `Bretone` 的 `inflection` 同族里**只有 `Bretonen`**，
   而**它俩犯的是同一个错**（都丢了长音）⇒ 族内一致，看不出问题。
   真正能证伪它的 `Bretonin`／`Bretonisch`／`bretonische…`（12 个全是 `bʁeˈtoːn…`）
   是**另外的词条**，不在 `base_id` 之下。
② **「词干」用「归一后截掉末 3 字符」是形式代理**（`[[criteria-from-meaning-not-form]]`）。
   `-er` 的元音化**恰恰取决于被截掉的那一截**：`Kurpfuscher` 的族里
   `Kurpfuschern/-s` 是 `ʃɐn/ʃɐs`，而 `Kurpfuscherin` 是 `ʃəʁɪn` —— 族自己就分两派，
   截尾之后反倒让法语版的 `əʁ` 对上了多数。

⭐ **可迁移的那一条**：手工那两条我确实是靠「同族自相矛盾」确认的，**判断本身没错**；
   错的是「把它规则化」这一步。**手工能做的判断，规则化之后不一定还成立** ——
   「哪些词算同族」「哪一截算词干」这两件事，人做的时候是看着意思做的，
   写成规则就只剩形状了。

───────────────────────────────────────────────────────────
（以下是当初的设计说明，保留以便读懂代码；结论以上面为准。）

原意 —— **用「我们自己的同族词形」当裁判，法语版只当指路的**。2026-09-05。

═══ 为什么需要这一步 ═══
盲测 28 条的结果（`data/work/de/probe/consult_c39_20260905.*.md`）逼出一个硬事实：

    我们这一侧真错          2 / 28 = **7.1%**
    豆包判错（判官自身错误率） 5 / 28 = **17.9%**
    deepseek-v4-pro 判错     2 / 28 = **7.1%**

🔴🔴 **判官的错误率 ≥ 被判集合的缺陷率 ⇒ 拿它去清洗，注入的错比清掉的多。**
   ⇒ 1,374 条不能送模型逐条判。这不是省钱，是**送了会更差**。

═══ 那两条真错是怎么被确认的：不靠外部权威，靠我们自己的数据自相矛盾 ═══
    Bretone        我们 `bʁeˈtonə`   而 `Bretonin`/`Bretonisch`/`bretonische`… **12 个同族全是 `bʁeˈtoːn…`**
    steigen hinab  我们 `hiˈnap`     而 `hinab` 本身以及 `baumel hinab`… **全是 `hɪˈnap`**

⇒ **法语版的价值不是「权威」，是「指路」**：它指出这一条可疑，
  而「到底谁对」由**我们自己的同族词形**多数决 —— 那是确定性的、免费的、可复算的。
  `[[verify-before-claiming-confirmed]]`：模型共识不是证据；这里连模型都不需要。

═══ 判据 ═══
一条进「已确认」当且仅当三条同时成立：
  ① 法语版与我们不一致（即它在 C39 的待看清单里）；
  ② 这个词形有 ≥3 个同族词形（同 `base_id`，或互为原形），它们的首选音标**高度一致**；
  ③ **法语版的值与同族一致，而我们这一条不一致** —— 我们是族里的孤例。
⚠️ ②的「高度一致」按**归一后的词干**比，不比整串（同族词形词尾必然不同）。

⚠️ 本脚本**只读**，不写库、不调模型。

跑：python3 -u probes/c39_family_check.py
"""
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

import paths                                                    # noqa: E402
from c39_fr_audit import CONTESTED, SEP_PREFIX, _marks, load    # noqa: E402
from ipa_conventions import (BUCKETS, bucket, full_key,         # noqa: E402
                             refine, variants)

f = lambda n: format(n, ",")
REAL = ("⑨", "③b", "④b")
MIN_FAMILY = 3


def pending(rows):
    """→ [(词形, 我们的, 法语版的, 桶名)]，即 C39 的待看清单。判据与 `c39_fr_audit` 同源。"""
    rank = {nn: j for j, (nn, _) in enumerate(BUCKETS)}
    out = []
    for w, P, A, B in rows:
        if {v for p in P for v in variants(p)} & {v for b in B for v in variants(b)}:
            continue
        if {v for x in A for v in variants(x)} & {v for b in B for v in variants(b)}:
            continue
        x, y, nm, best = sorted(P)[0], sorted(B)[0], None, 99
        for p in sorted(P):
            for b in sorted(B):
                raw = bucket(p, b)
                i = rank.get(raw, 98)
                if i < best:
                    best, nm, x, y = i, refine(raw, p, b), p, b
        if nm and nm.startswith("⑨"):
            nx, ny = _marks(x), _marks(y)
            if any(fn(nx, ny) for _c, fn in CONTESTED):
                continue
        elif nm and nm.startswith("③b") and w.lower().startswith(SEP_PREFIX):
            continue
        if nm and nm.startswith(REAL):
            out.append((w, x, y, nm))
    return out


def families(con):
    """→ {词形: 同族词形集合}。同族 = 同一个 `base_id` 之下（含原形自己）。"""
    fam = defaultdict(set)
    for base, w in con.execute(
            "SELECT b.word, d.word FROM inflection i "
            "  JOIN dict d ON d.id=i.word_id JOIN dict b ON b.id=i.base_id"):
        fam[base].add(w)
        fam[base].add(base)
    out = {}
    for base, members in fam.items():
        for m in members:
            out[m] = members
    return out


def stem(ipa):
    """归一后去掉末尾的屈折残余：同族词形词尾必然不同，比的是**词干**。"""
    k = full_key(ipa)
    return k[:-3] if len(k) > 6 else k


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    prim = {}
    for w, ipa in con.execute(
            "SELECT d.word, p.ipa FROM pronunciation p JOIN dict d ON d.id=p.word_id "
            " WHERE p.is_primary=1"):
        prim.setdefault(w, ipa)
    fam = families(con)
    con.close()

    todo = pending(load())
    print("■ C39 待看清单 %s 条" % f(len(todo)))
    print("■ 有同族词形（≥%d 个）的 %s 条"
          % (MIN_FAMILY, f(sum(1 for w, _, _, _ in todo if len(fam.get(w, ())) >= MIN_FAMILY))))

    confirmed, no_family, family_split, we_agree = [], 0, 0, 0
    for w, ours, fr, nm in todo:
        members = fam.get(w) or set()
        sibs = [prim[m] for m in members if m != w and m in prim]
        if len(sibs) < MIN_FAMILY - 1:
            no_family += 1
            continue
        c = Counter(stem(s) for s in sibs)
        top, n_top = c.most_common(1)[0]
        if n_top < max(2, int(0.7 * len(sibs))):     # 同族自己就不一致 ⇒ 说明不了问题
            family_split += 1
            continue
        ok_ours, ok_fr = stem(ours) == top, stem(fr) == top
        if ok_ours:
            we_agree += 1
        elif ok_fr:
            confirmed.append((w, ours, fr, nm, len(sibs)))

    print("\n■ 分流")
    print("   同族不够（<%d）              %s" % (MIN_FAMILY, f(no_family)))
    print("   同族自己就不一致（说明不了）    %s" % f(family_split))
    print("   我们与同族一致（法语版是孤例）  %s  ← 这些是**法语版错**" % f(we_agree))
    print("   🔴 **我们是孤例、法语版与同族一致** %s  ← 已确认的我方缺陷" % f(len(confirmed)))

    print("\n■ 已确认的我方缺陷（前 30 条）")
    for w, ours, fr, nm, n in confirmed[:30]:
        print("   %-26s 我们=%-22s 法语版=%-22s 同族 %2d  %s"
              % (w[:26], ours[:22], fr[:22], n, nm[:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
