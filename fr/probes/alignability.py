#!/usr/bin/env python3
"""阶段 1.5 开工前的**可对齐性实测** —— 法文版释义能不能确定性挂到我们的义项上。2026-08-22。

═══ 为什么必须先量这个 ═══
`FR_PLAN` 阶段 1.5 写着「**在这个数出来之前，不许给 1.5 写工期数字**」。
理由是 `IT_PLAN` 那轮：阶段 1.5 按 es 的印象写成"最贵、3–4 天"，
而意语版实测能大比例确定性对上 —— 工期估计整个是虚的。
fr 的法文版释义 **697,814 条**是 it 那轮（105,474）的 6.6 倍，**不能靠印象**。

⚠️ 计划里原话是「取 1% 切片」。**改成全量**：分桶只是一次只读扫描（约 10 分钟），
   而 1% 抽样会带来自己的误差。能全量确定性算的，就别抽样
   （`[[llm-as-evaluator-discipline]]` ⑩）。

═══ 分桶判据 ═══
对法文版的每一条**真释义**（判据＝没有 `form_of`/`alt_of`，用结构化字段不猜文本）：
  · 词形不在 `dict` 里            → 桶 0：阶段 3 收词的活，1.5 挂不上（`word_id` NOT NULL）
  · 我们没有这个词性               → 桶 ②：法文版讲的是我们没收的词类，不挂，记账
  · 该词性下我们**只有 1 条**义项   → 桶 ①：**确定性直接挂，不花钱**
  · 该词性下我们有多条义项          → 桶 ③：要语义对齐，**这一桶才花钱**

🔴 桶③的候选义项总数才是真实成本，不是桶③的条数 ——
   一条法语释义要和它那个词性下**所有**候选义项一起送进 prompt。

⚠️ **必须允许「一条都挂不上」**：it 那轮逮到 `sbandamento`，意语释义是「群体成员的四散」，
   而我们那 5 条义项一条都不是它 —— 那是**我们没收的义项**，硬挂就是错配。
   所以桶③的产出必然含「挂不上」这个选项，不能按"总能挂上一条"排预算。

跑：python3 probes/alignability.py            （在 fr/ 目录下，约 10 分钟）
    python3 probes/alignability.py --quick     （只扫前 100 万行看形状）
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths   # noqa: E402
from build_entry_layer import POS_MAP   # noqa: E402


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    limit = 1000000 if a.quick else None

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 我们的义项：折叠词形 → {映射后词性: [sense_id, …]}
    ours = defaultdict(lambda: defaultdict(list))
    n_ours = 0
    for sid, w, pos in con.execute(
            "SELECT s.id, d.word, s.pos FROM sense s JOIN dict d ON d.id=s.word_id"):
        ours[w.lower()][pos or ""].append(sid)
        n_ours += 1
    print("■ 我们的义项 %s（覆盖 %s 个折叠词形）" % (f"{n_ours:,}", f"{len(ours):,}"))

    st = Counter()
    cand_total = 0
    cand_hist = Counter()
    pos_unmatched = Counter()
    fr_pos = Counter()
    samples = []

    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                st["（截断）"] = 1
                break
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "fr":
                continue
            w0 = (e.get("word") or "").strip()
            if not w0:
                continue
            w = w0.lower()
            pos_raw = e.get("pos") or ""
            pos = POS_MAP.get(pos_raw, pos_raw)
            for s in e.get("senses") or []:
                # 🔴 判据＝结构化字段，不猜文本前缀（阶段 -1 那轮的教训）
                if s.get("form_of") or s.get("alt_of"):
                    continue
                g = norm((s.get("glosses") or [""])[0])
                if not g:
                    continue
                st["法文版真释义"] += 1
                if w not in ours:
                    st["桶0：词形不在 dict（阶段 3 的活）"] += 1
                    continue
                fr_pos[pos_raw] += 1
                cands = ours[w].get(pos, [])
                if not cands:
                    st["桶②：我们没有这个词性（不挂，记账）"] += 1
                    pos_unmatched[pos] += 1
                elif len(cands) == 1:
                    st["桶①：词性唯一 ⇒ 确定性挂，不花钱"] += 1
                else:
                    st["桶③：同词性多条 ⇒ 要语义对齐（花钱）"] += 1
                    cand_total += len(cands)
                    cand_hist[min(len(cands), 10)] += 1
                    if len(samples) < 5:
                        samples.append((w0, pos, g[:60], len(cands)))

    total = st["法文版真释义"]
    print("\n■ 分桶（全量%s）" % ("，已截断" if st.get("（截断）") else ""))
    for k in ("桶0：词形不在 dict（阶段 3 的活）",
              "桶②：我们没有这个词性（不挂，记账）",
              "桶①：词性唯一 ⇒ 确定性挂，不花钱",
              "桶③：同词性多条 ⇒ 要语义对齐（花钱）"):
        v = st[k]
        print("   %-40s %9s  %5.1f%%" % (k, f"{v:,}", 100.0 * v / total if total else 0))
    print("   %-40s %9s" % ("合计", f"{total:,}"))

    挂得上 = st["桶①：词性唯一 ⇒ 确定性挂，不花钱"] + st["桶③：同词性多条 ⇒ 要语义对齐（花钱）"]
    if 挂得上:
        print("\n■ 在**挂得上的** %s 条里" % f"{挂得上:,}")
        print("   确定性（桶①）  %9s  %5.1f%%"
              % (f'{st["桶①：词性唯一 ⇒ 确定性挂，不花钱"]:,}',
                 100.0 * st["桶①：词性唯一 ⇒ 确定性挂，不花钱"] / 挂得上))
        print("   要花钱（桶③）  %9s  %5.1f%%"
              % (f'{st["桶③：同词性多条 ⇒ 要语义对齐（花钱）"]:,}',
                 100.0 * st["桶③：同词性多条 ⇒ 要语义对齐（花钱）"] / 挂得上))
        print("\n   🔴 桶③的候选义项总数 %s（真实成本按这个算，不是按条数）"
              % f"{cand_total:,}")
        print("   候选数分布：", " ".join(
            "%s条:%s" % ("≥10" if k == 10 else k, f"{v:,}") for k, v in sorted(cand_hist.items())))

    print("\n── 桶②里我们没有的词性（前 12）──")
    for k, v in pos_unmatched.most_common(12):
        print("   %-10s %8s" % (k or "(空)", f"{v:,}"))
    print("\n── 桶③样本 ──")
    for w, p, g, n in samples:
        print("   %-16s [%s] 候选 %d 条 ← %s" % (w, p, n, g))


if __name__ == "__main__":
    sys.exit(main())
