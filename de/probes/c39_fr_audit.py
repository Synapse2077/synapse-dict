#!/usr/bin/env python3
"""收尾单 C39 —— **拿法语版当独立审核者**，复核我们已经在给读者看的德语音标。2026-09-05。

═══ 这一步与 C22/C41 的区别 ═══
C22/C41 问的是「**还能补多少**」（外部源当补充源）。
C39 问的是「**我们已经给出去的对不对**」（外部源当**审核者**）——
它审的是**已经在页面上的东西**，所以比补新词形值钱（`FRAMEWORK §一`：错比缺更伤权威）。

═══ 🔴🔴 为什么必须重跑，而不是直接用账上那个 36,090 ═══
那个数是 2026-09-05 上午用**当时那条归一链**跑出来的，而**当天下午 C41 证明了
那条链是不完整的**：`ipa_conventions` 的「⑨ 其他」桶是**残差**，
消去器少一条它就虚胖一块。补上四条实测的德语转写约定后，
英文版那一轮的「实质分歧」**16.8% → 3.3%**（`[[residual-bucket-is-not-evidence]]`）。
⇒ 同一条链算出来的 36,090 **必然也偏大**，先用新链重算，再谈要不要做。

⚠️ 本脚本**只读**：读真值集 `data/work/de/probe/fr_de_ipa_sets.tsv`
   （484,895 个词形，按词形聚合；外锚文件，`[[external-anchor-gates]]`：
   锚外部 dump 的闸不过期），不写库、不下载、不调模型。
🔴 旧真值集 `fr_de_ipa_pairs.tsv` **取数有错、已于 2026-09-06 删除** ——
   留着它的风险不是占 28 MB，是**下一个人会用错的那一份**（错在哪见 `rebuild()`）。
   要复现它：`--rebuild` 重扫法语版即可，它不是不可再生的东西。

═══ 🔴 已知的过度合并（`probes/ipa_conventions.py --gate` 全量跑过，逐条看过实样）═══
消去阶梯里合并最狠的两条是 `d_stress`（15,914 组）与 `d_long`（8,147 组）——
**而重音位置和元音长短恰恰是德语里会区别意义的东西**。这不是漏洞，是设计：
它们负责把「差异只跟重音符/长音符有关」圈出来，随后 `refine()` 再把这一桶劈成
「记法」（③a/④a）与「真分歧」（③b/④b）。⇒ **合并回来的，refine 又分开了。**

⚠️ **一条没修的**：`d_diacr` 先 NFD 再删组合符，于是把**鼻化元音**也抹平了
（`ɑ̃nyˈjiːɐ̯` ≡ `anyˈjiːɐ̯`）。德语外来词里鼻化是区别意义的（`Bonmot` bɔ̃ˈmoː）。
实测 77 组，全落在法语借词上，不影响本步的结论 ⇒ **记账不修**，
下次谁要拿这条阶梯做别的判断，先看这一段。

═══ 分歧不是一桶，至少是三桶 ═══
    ① **记法约定**       两个都对，选一个就行 ⇒ 不是缺陷
    ② **德语本身有争议** `-ig` 在词尾的 ich-/ach-Laut、外来词 `st-` ⇒ **也不是缺陷**
    ③ **真的有一边错**   ⇒ 这才是 C39 要交的东西
账上已经写明「判据得先能把真争议和真错分开，否则又是一次判据比它要描述的东西宽」。
本脚本负责把 ① 和 ② 尽量减干净，**剩下的才拿去逐条看**。

跑（在 de/ 目录下）：
    python3 -u probes/c39_fr_audit.py
    python3 -u probes/c39_fr_audit.py --bucket "⑨"   # 只看某一桶的样本
"""
import argparse
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

import paths                                                    # noqa: E402
from harvest_pronunciation import bare                          # noqa: E402
from ipa_conventions import (BUCKETS, bucket, refine, _nfc,      # noqa: E402
                             variants, full_key, d_space, d_syll, d_stress, d_legacy)

f = lambda n: format(n, ",")
SETS  = paths.WORK / "probe" / "fr_de_ipa_sets.tsv"    # 新真值集：按词形聚合

# ═══ 德语本身有争议的读法：**这一族不是缺陷，要单独摘出来** ═══
# 🔴 每一条都必须写清「争议在哪」，不许放一条「看着像方言差异」的模糊规则进来。
#    判据只对**同一个词的两条音标**用，不改数据（同 `[[residual-bucket-is-not-evidence]]`
#    那条边界：消去器只用于分类、不用于写库）。
#
# 🔴 **判据在消去阶梯归一之后才判**（2026-09-05 改）。第一版直接拿原串判，于是
#    `schmutzig` 我们 `ˈʃmʊt͡sɪk` / 法语版 `ʃmʊt͡sɪç` 因为**多一个重音符**就没命中
#    `-ig` 那条规则，落回残差桶。⇒ 争议规则问的是「音段上是不是那个已知对立」，
#    重音符/音节点这些记法差异**必须先减掉**，否则规则永远比它要描述的东西窄。
#
# ⭐ **可分/不可分前缀动词的重音对立是第四族，而且它不是「谁错」是「两个词」**：
#    `übersetzen` ˈyːbɐˌzɛt͡sn̩（摆渡，可分）≠ yːbɐˈzɛt͡sn̩（翻译，不可分）。
#    两条都对，我们只存了一条 —— 那是**缺**不是**错**，必须与真错分开记。
SEP_PREFIX = ("über", "unter", "durch", "um", "wider", "wieder", "hinter", "voll", "miss")
CONTESTED = [
    # `-ig` 词尾：标准德语读 ich-Laut [ɪç]，南德/奥地利读 [ɪk]。两读都载入词典。
    ("`-ig` 词尾 ç / k（南北分歧，两读都进词典）",
     lambda a, b: _swap(a, b, [("ɪç", "ɪk"), ("ɪg", "ɪk")])),
    # 外来词词首 `st-`/`sp-`：德语化读 [ʃt]，保留原语读 [st]。
    ("外来词词首 st-/sp- 读 ʃt / st（德语化程度分歧）",
     lambda a, b: _swap(a, b, [("ʃt", "st"), ("ʃp", "sp")])),
    # 词尾 `-r` 的元音化：[ɐ] vs [r/ʁ]，是语速/正式度的连续统，不是对错。
    ("词尾 r 元音化 ɐ / ʁ（语速与正式度的连续统）",
     lambda a, b: _swap(a, b, [("ɐ", "ʁ"), ("ɐ", "r"), ("ɐ̯", "ʁ")])),
]


def _marks(s):
    """争议规则用的归一：**只减记号，一个音段都不动。**

    🔴 第二版。第一版图省事直接用了整条消去阶梯的 `full_key()` —— **它把判据本身
       要看的那个区别抹掉了**：`d_diacr` 先 NFD 再删组合符，而 `ç` 分解出来正是
       `c` + 组合变音符 ⇒ `ɪç` 变成 `ɪc`，`-ig` 那条规则一条都命中不了
       （11,533 → 1，全掉回残差桶）。
    ⇒ **归一链要按「这条判据需要保留什么」裁剪，不是拿现成最长的那条套上去。**
      这里只减重音符/音节点/空白/同音异码四样，`ç`/`k`/`ʃ`/`s` 原样保留。
    """
    for fn in (d_space, d_syll, d_stress, d_legacy):
        s = fn(s)
    return s


def _swap(a, b, pairs):
    """→ a 与 b 的差异是否**只**由这组可互换的音串解释。"""
    for x, y in pairs:
        if a.replace(x, y) == b.replace(x, y):
            return True
        if a.replace(y, x) == b.replace(y, x):
            return True
    return False


def rebuild():
    """重建真值集 → `fr_de_ipa_sets.tsv`：**按词形聚合**，我们这一侧分「首选」和「全部」。

    🔴🔴 **旧真值集 `fr_de_ipa_pairs.tsv` 有一个致命的取数错误，而它是账上 36,090 的来源。**
       它一个词形只放**一条**我们的音标，而且**不是首选那条**：

           du   我们=daɪ̯n   法语版=duː      ← 我们首选其实是 `duː`，完全一致
                                              `daɪ̯n` 是德语版在同一页列的 `dein` 的读音
           H    我们=f      法语版=haː      ← 我们首选其实是 `haː`
           ich  我们=ɪx     法语版=ɪç       ← 我们首选其实是 `ɪç`

       ⇒ 那份清单里**排在最前面的几条「我们错了」，其实我们全是对的**。
         它比的既不是读者看见的东西，也不是我们数据的全貌。
       `[[measure-landing-not-source]]`：**新数字先假设我的度量错了** —— 这次错了两处，
       消去阶梯不全（残差虚胖）＋ 取数取错了行，而且两处都让分歧看起来更多。

    ⇒ 新真值集按词形聚合，并且**同时给两个口径**：
         读者口径：我们的**首选**读音 vs 法语版任一 ← C39 要审的就是读者看见的
         集合口径：我们的**任一** vs 法语版任一     ← 说明「数据里有没有」
    """
    import gzip
    import json
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ours, prim = {}, {}
    for w, ipa, is_p in con.execute(
            "SELECT d.word, p.ipa, p.is_primary FROM pronunciation p JOIN dict d ON d.id=p.word_id"):
        v = _nfc(bare(ipa))
        if not v:
            continue
        ours.setdefault(w, set()).add(v)
        if is_p:
            prim.setdefault(w, set()).add(v)
    con.close()
    print("■ 我们有音标的词形 %s（其中有首选标记的 %s）" % (f(len(ours)), f(len(prim))))

    fr, n = {}, 0
    with gzip.open(paths.DUMPS / "frwiktionary.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            n += 1
            if '"de"' not in line or '"sounds"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "de":
                continue
            w = e.get("word") or ""
            if w not in ours:
                continue
            for s in e.get("sounds") or []:
                v = _nfc(bare(s.get("ipa") or ""))
                if v:
                    fr.setdefault(w, set()).add(v)
    print("■ 扫完法语版 %s 行，两版都有音标的词形 %s" % (f(n), f(len(fr))))

    SETS.parent.mkdir(parents=True, exist_ok=True)
    with open(SETS, "w", encoding="utf-8") as out:
        for w in sorted(fr):
            out.write("%s\t%s\t%s\t%s\n" % (w, "|".join(sorted(prim.get(w, ()))),
                                            "|".join(sorted(ours[w])), "|".join(sorted(fr[w]))))
    print("■ 写出 %s" % SETS)


def load():
    """→ [(词形, 我们的首选集, 我们的全部集, 法语版集)]。"""
    if not SETS.exists():
        sys.exit("🔴 真值集 %s 不存在 —— 先跑 `--rebuild`" % SETS)
    out = []
    with open(SETS, encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) != 4:
                continue
            sp = lambda s: {x for x in s.split("|") if x}
            P, A, B = sp(p[1]), sp(p[2]), sp(p[3])
            if A and B:
                out.append((p[0], P or A, A, B))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", help="只打印这一桶的样本")
    ap.add_argument("--samples", type=int, default=6)
    ap.add_argument("--rebuild", action="store_true", help="重扫法语版，重建真值集")
    ap.add_argument("--families", action="store_true", help="待看清单按最小替换聚族")
    a = ap.parse_args()

    if a.rebuild:
        rebuild()
        return 0
    rows = load()
    print("■ 真值集 %s 个词形（两版都给了音标）" % f(len(rows)))
    print("■ 口径：**我们的首选读音 vs 法语版任一读音** —— C39 审的是读者看见的那一条")
    print("■ 消去阶梯：**已列 %d 类记法约定** + %d 类德语争议读法"
          % (len(BUCKETS), len(CONTESTED)))
    print("   ⚠️ 「⑨ 其他」是**残差**，它的大小 = 我还没写到的类别有多少"
          "（`[[residual-bucket-is-not-evidence]]`）")

    agree, c, ex, saved = 0, Counter(), {}, 0
    for w, P, A, B in rows:
        # 一致的判据：**任一首选** 与 **任一法语版读音** 逐字相同（可选成分展开后比）
        if {v for p in P for v in variants(p)} & {v for b in B for v in variants(b)}:
            agree += 1
            continue
        # ⭐ 首选对不上、但我们**别的读音**对得上 ⇒ 不是「我们错了」，是「首选排序可议」
        if {v for x in A for v in variants(x)} & {v for b in B for v in variants(b)}:
            c["⓪ 首选对不上、我们另一条读音对得上（排序问题，不是错）"] += 1
            ex.setdefault("⓪ 首选对不上、我们另一条读音对得上（排序问题，不是错）",
                          []).append((w, sorted(P)[0], sorted(B)[0]))
            saved += 1
            continue
        # 取「最像的一对」归类：**用未细分的桶名在阶梯里的序号排**，序号越小越像。
        # ⚠️ 不能拿细分后的名字（③a/③b/④a/④b）去 `BUCKETS` 里找序号 —— 那些名字
        #    根本不在 `BUCKETS` 里，找不到就一律记 98，于是「最像」退化成「第一个」。
        _rank = {nn: j for j, (nn, _) in enumerate(BUCKETS)}
        x, y, nm, best = sorted(P)[0], sorted(B)[0], None, 99
        for p in sorted(P):
            for b in sorted(B):
                raw = bucket(p, b)
                i = _rank.get(raw, 98)
                if i < best:
                    best, nm, x, y = i, refine(raw, p, b), p, b
        if nm and nm.startswith("⑨"):
            # 🔴 在**归一之后**判争议读法（见 CONTESTED 上面那段）
            nx, ny = _marks(x), _marks(y)
            for cname, fn in CONTESTED:
                if fn(nx, ny):
                    nm = "⑩ " + cname
                    break
        elif nm and nm.startswith("③b") and w.lower().startswith(SEP_PREFIX):
            nm = "⑩ 可分/不可分前缀动词的重音对立（两个词，不是谁错）"
        c[nm] += 1
        ex.setdefault(nm, []).append((w, x, y))

    n = max(len(rows), 1)
    print("\n■ 分歧归类（每对只进第一个命中的桶）")
    print("   ✅ 逐字有交集（无分歧）            %9s  %5.2f%%" % (f(agree), 100.0 * agree / n))
    for k in sorted(c, key=lambda s: (s.startswith("⑨"), s)):
        print("   %-36s %9s  %5.2f%%" % (k[:36], f(c[k]), 100.0 * c[k] / n))
        if not a.bucket:
            w, x, y = ex[k][0]
            print("        %-22s 我们=%-24s 法语版=%s" % (w[:22], x[:24], y[:24]))

    # 🔴 待看清单 = 残差 ⑨ ＋ **被 ③/④ 吞掉的真分歧**（主重音位置、元音长短）
    REAL = ("⑨", "③b", "④b")
    resid = sum(v for k, v in c.items() if k.startswith(REAL))
    print("\n■ **剩下要逐条看的** %s（%.2f%%）—— 账上写的是 36,090"
          % (f(resid), 100.0 * resid / n))

    if a.families:
        # ⭐ **残差别只看条目，先按「差在哪个字符上」聚族。** 同音异码会自己浮到最上面：
        #    `ɡ → g`（U+0261 / ASCII）第一次跑就以 294 条排第一 —— 一眼看得出
        #    那不是 294 个读音分歧。两条同音异码（`ɡ/g`、音节化符 U+030D/U+0329）
        #    都是这么逼出来的，不是读代码看出来的。
        import difflib
        fam, fex = Counter(), {}
        for k in ex:
            if not k.startswith(REAL):
                continue
            for w, x, y in ex[k]:
                A2, B2 = full_key(x), full_key(y)
                op = [(A2[i1:i2], B2[j1:j2])
                      for t, i1, i2, j1, j2 in
                      difflib.SequenceMatcher(None, A2, B2, autojunk=False).get_opcodes()
                      if t != "equal"]
                key = ("%s → %s" % (op[0][0] or "∅", op[0][1] or "∅")
                       if len(op) == 1 else "（%d 处改动）" % len(op))
                fam[key] += 1
                fex.setdefault(key, (w, x, y))
        print("\n■ 待看清单按「最小替换」聚族（共 %d 族）" % len(fam))
        for k, v in fam.most_common(a.samples):
            w, x, y = fex[k]
            print("   %-18s %5s   %-20s 我们=%-24s 法语版=%s"
                  % (k[:18], f(v), w[:20], x[:24], y[:24]))
        return 0

    if a.bucket:
        for k in sorted(c):
            if not k.startswith(a.bucket):
                continue
            print("\n── %s 的样本 %d 条 ──" % (k, a.samples))
            for w, x, y in ex[k][:a.samples]:
                print("   %-28s 我们=%-26s 法语版=%s" % (w[:28], x[:26], y[:26]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
