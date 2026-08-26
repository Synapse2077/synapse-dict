#!/usr/bin/env python3
"""阶段 4 开工前：**量音标的覆盖上限**，量出来再定验收线。2026-08-25。

═══ 为什么先量 ═══
`FR_PLAN` §阶段 4 的原话：「**先量覆盖上限**：kaikki 自带 + `forms` 收割 + 跨版并集，
一共能覆盖多少词形。量出来再定验收线，**不定"要达到 X%"这种拍脑袋的线**。」

🔴 这条对 fr 尤其硬，因为 **fr 明确不造 G2P**（用户七月已定）。
   `[[it-pronunciation-layer]]`：it 那轮 120 万行音标里 **73.4% 是我们自己 G2P 算的** ——
   也就是说"照搬 it 的覆盖率"是**不可能**的，fr 的天花板完全由源头决定。
   不先量就开工，等于把一个做不到的目标写进验收线。

═══ 量什么 ═══
按**四个源**依次求并集，每一步报边际增量（不是各自的总数 —— 那会重复计数）：
  ① 库内 `dict.ipa` 现状
  ② 法文版 dump 的 `sounds[].ipa`（词条级）
  ③ 法文版 dump 的 `forms[].ipa`（**变形级** —— it 那轮变形层是最大缺口）
  ④ 其余各版切片（英文版 / el / tr / ru / ja / nl）

再按**四个切面**分层看 —— 总覆盖率是个会骗人的数：
  · 像词头 vs 变形（变形占库里 86%，混在一起算会把词头的缺口稀释掉）
  · 有可见义项的 vs 没有的（没义项的词形，音标价值低）
  · 有 `freq_zipf` 的 vs 没有的（查得到的词才是产品面）

跑（在 fr/ 目录下，只读，不写库）：
    python3 -u probes/ipa_ceiling.py            # 全量扫，约几分钟
    python3 -u probes/ipa_ceiling.py --limit 200000   # 先小样看看形状
"""
import argparse
import gzip
import io
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths   # noqa: E402

# 其余各版切片：文件名 → 标签。⚠️ 只收**法语词条**（这些切片本身已经是 French-only）。
OTHERS = [
    ("kaikki.org-elwiktionary-French.jsonl.gz", "el"),
    ("kaikki.org-trwiktionary-French.jsonl.gz", "tr"),
    ("kaikki.org-ruwiktionary-French.jsonl.gz", "ru"),
    ("kaikki.org-nlwiktionary-French.jsonl.gz", "nl"),
    ("kaikki.org-jawiktionary-French.jsonl.gz", "ja"),
]


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if str(p).endswith(".gz") \
        else io.open(p, encoding="utf-8")


def harvest(path, limit=0):
    """→ (词条级 {词形: 音标}, 变形级 {词形: 音标})。只取第一个非空 IPA。"""
    head, forms = {}, {}
    if not Path(path).exists():
        return head, forms
    n = 0
    with opener(path) as f:
        for ln in f:
            n += 1
            if limit and n > limit:
                break
            try:
                o = json.loads(ln)
            except Exception:
                continue
            if o.get("lang_code") not in (None, "fr"):
                continue
            w = o.get("word")
            if not w:
                continue
            if w not in head:
                for s in o.get("sounds") or []:
                    if s.get("ipa"):
                        head[w] = s["ipa"]
                        break
            for fm in o.get("forms") or []:
                fw, ip = fm.get("form"), fm.get("ipa")
                if fw and ip and fw not in forms:
                    forms[fw] = ip
    return head, forms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="每个 dump 只读前 N 行（看形状用）")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ 读库…")
    # ⚠️ fr 还没有 `freq_zipf` 列（那是阶段 5 的事）⇒ 「高频词切面」本轮量不了，
    #    等阶段 5 落了频次再补。**不用 `level` 顶替**：`[[wordfreq-ruler-traps]]` /
    #    `[[es-audio-and-examples-wip]]` —— `level` 只给内容词打标、语法词全 NULL，
    #    es 那轮按它挑词，六个最常用词一个都没挑中。
    rows = con.execute("""
        SELECT d.word, d.is_lemma,
               CASE WHEN TRIM(COALESCE(d.ipa,''))<>'' THEN 1 ELSE 0 END
        FROM dict d""").fetchall()
    have = {w for w, _l, ip in rows if ip}
    lemma = {w for w, l, _i in rows if l}
    allw = {w for w, _l, _i in rows}
    print("   词形 %s ｜ 像词头 %s ｜ **已有音标 %s（%.1f%%）**"
          % (format(len(allw), ","), format(len(lemma), ","),
             format(len(have), ","), 100.0 * len(have) / len(allw)))

    # 有可见义项的词形（产品面最要紧的一层）
    sensed = {w for (w,) in con.execute("""
        SELECT DISTINCT d.word FROM dict d
        JOIN sense s ON s.word_id = d.id AND s.hidden = 0""")}
    print("   有可见义项的词形 %s" % format(len(sensed), ","))

    print("\n■ 扫 dump…（法文版 %s MB）"
          % format(int(Path(paths.EDITION).stat().st_size / 1048576), ","))
    src = []
    fr_head, fr_forms = harvest(paths.EDITION, a.limit)
    src.append(("法文版 sounds[]（词条级）", fr_head))
    src.append(("法文版 forms[]（变形级）", fr_forms))
    kk_head, kk_forms = harvest(paths.KK, a.limit)
    src.append(("英文版 sounds[]", kk_head))
    src.append(("英文版 forms[]", kk_forms))
    for fn, tag in OTHERS:
        h, f = harvest(paths.DUMPS / fn, a.limit)
        if h or f:
            src.append(("%s 版（sounds+forms）" % tag, dict(f, **h)))

    print("\n══ 边际增量（依次求并集，**顺序固定：贵的/权威的在前**）══")
    print("%-30s %12s %12s %12s" % ("源", "本源命中", "**新增**", "累计覆盖"))
    print("-" * 70)
    cum = set(have)
    print("%-30s %12s %12s %12s"
          % ("① 库内现状", "—", "—", format(len(cum), ",")))
    for name, tbl in src:
        hit = allw & set(tbl)
        new = hit - cum
        cum |= new
        print("%-30s %12s %12s %12s"
              % (name, format(len(hit), ","), format(len(new), ","), format(len(cum), ",")))

    print("\n══ 上限（四个切面分层看）══")
    for tag, universe in (("全部词形", allw), ("像词头", lemma),
                          ("有可见义项", sensed & allw)):
        n = len(universe)
        h0 = len(universe & have)
        h1 = len(universe & cum)
        print("   %-12s %9s ｜ 现状 %9s (%5.1f%%) → **上限 %9s (%5.1f%%)**  提升 %s"
              % (tag, format(n, ","), format(h0, ","), 100.0 * h0 / max(n, 1),
                 format(h1, ","), 100.0 * h1 / max(n, 1), format(h1 - h0, ",")))

    gap = (sensed & allw) - cum
    print("\n══ 补完之后仍然没有音标的（有义项那层，抽 12 个看形状）══")
    for w in sorted(gap)[:12]:
        print("     %s" % w)
    print("   共 %s 个" % format(len(gap), ","))
    print("\n🔴 fr **不造 G2P** ⇒ 上面的「上限」就是终点，验收线只能定在它以下。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
