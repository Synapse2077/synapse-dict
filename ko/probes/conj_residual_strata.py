#!/usr/bin/env python3
"""K18 的结构性问题：**那 322 条按构造无法指认。能不能至少把它们圈小？** 2026-09-26。

═══ 为什么 K18 不能像别的账那样「挑出来修」═══
生成活用表的对象**恰恰是源头一张表都没有的词**（7,591 个用言）。
留出法量出的 0.043% 是在**有表的词**上测的 —— 换句话说：

    有真值的地方我们不生成；我们生成的地方没有真值。

⇒ 「把那 322 条挑出来」按构造做不到。账上写的结清条件里，能做的只剩
  「写明为什么可以不修」，而**那不该只是一句话**。

═══ 这个探针要回答一个可判的问题 ═══
`learn()` 只收「出现在 **≥50%** 训练词元上」的变体（`rule[k][v] >= 0.5*seen[k]`）。
那么**支持度刚过 50% 的变体**天然比 100% 的可疑。

    问题：**生成行的错误率，是不是随变体支持度下降而上升？**
      是  ⇒ 可以按支持度给 745,037 行分层，把风险圈进一小撮，值得单独复核
      否  ⇒ 残差**不可分层**，没有外部词典就是不可约的 —— 那就是 K18 的答案

判据在留出集上测（那里有真值），分层规则再套到全量生成行上。
⚠️ **不许用它去调阈值把 0.043% 做小** —— 那是 `[[proxy-metric-gets-optimized]]`。
   这个探针只回答「残差能不能分层」，不动任何阈值。

跑（在仓库根）：
    python3 -u ko/probes/conj_residual_strata.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import collections
import random
import sqlite3

import conj_generate as G
import paths


OLD_KEEP = 0.5     # 旧门槛（`>=`）—— 见 `learn_with_support` 的说明，有意不跟着改


def learn_with_support(con, info, only=None):
    """与 `G.learn` 同一套统计，**额外返回每个变体的支持度**（用了它的词元占比）。

    🔴 判据不重写：分组、键、`_lcp`、`jamo` 全部用 `G.` 里那一份。
       这里只是把 `learn()` 已经算过、然后丢掉的那个比值留下来。

    ⚠️🔴 **这里的门槛有意停在 `>= 0.5`，而 `G.learn()` 已经改成 `> 0.5`。**
       不是漂移，是**这个探针要诊断的正是旧门槛留下的东西** ——
       用新门槛去找，平局变体根本不会出现，就永远查不到已经落库的那 11 条。
       ⇒ 门槛写成常量 `OLD_KEEP` 并在这里说明；`prune_conj_tie_forms.py` 靠它找旧账。
       等那 11 条清掉、且确认全量生成集里再没有平局行之后，这份探针就可以
       跟着改成 `> 0.5`（那时它退化成「恒为空」的自检）。
    """
    rule = collections.defaultdict(collections.Counter)
    seen = collections.Counter()
    real = collections.defaultdict(set)
    for base, w, tags in con.execute(
            "SELECT i.base, d.word, i.tags FROM inflection i "
            "JOIN dict d ON d.id=i.word_id WHERE i.src <> ?", (G.SRC,)):
        if only is not None and base not in only:
            continue
        if G.keyof(info, base, tags) is None:
            continue
        real[base].add((tags, w))
    for base, items in real.items():
        ks = set()
        for tags, w in items:
            k = G.keyof(info, base, tags)
            ks.add(k)
            js, jw = G.jamo(base[:-1]), G.jamo(w)
            i = G._lcp(js, jw)
            rule[k][(len(js) - i, tuple(jw[i:]))] += 1
        for k in ks:
            seen[k] += 1
    R, support = {}, {}
    for k, d in rule.items():
        keepv = {v for v, n in d.items() if n >= OLD_KEEP * seen[k]}
        R[k] = keepv
        for v in keepv:
            support[(k, v)] = d[v] / max(seen[k], 1)
    return R, support, real


def generate_with_support(info, IDX, support, base, keep=None):
    """`G.generate` 的同构版本，每条产出带上它那个变体的支持度。"""
    k0 = G.keyof(info, base, None)
    if k0 is None:
        return []
    bucket = IDX.get((k0[0], k0[1], k0[3], k0[4], k0[5], k0[6]))
    if not bucket:
        return []
    out = []
    stem_j = G.jamo(base[:-1])
    isadj = info[base][1] == {"adj"}
    for tags, variants in bucket.items():
        if keep is not None and tags not in keep:
            continue
        if isadj and any(x in tags for x in G.ADJ_FORBIDDEN):
            continue
        for drop, suf in variants:
            if drop > len(stem_j):
                continue
            k = (k0[0], k0[1], tags, k0[3], k0[4], k0[5], k0[6])
            out.append((tags, G.unjamo(stem_j[:len(stem_j) - drop] + list(suf)),
                        support.get((k, (drop, suf)), 1.0)))
    return out


BUCKETS = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90),
           (0.90, 0.999), (0.999, 1.01)]


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    info = G.load_info(con)

    # 与 `G.holdout` 完全相同的切分（同一个随机种子）—— 结果可比
    _, _, real = learn_with_support(con, info)
    lemmas = sorted(real)
    random.Random(20260924).shuffle(lemmas)
    h = len(lemmas) // 2
    R, support, _ = learn_with_support(con, info, only=set(lemmas[:h]))
    IDX = G.index_rules(R)
    use, tot = G.tag_share(real, info, lemmas[:h])

    strata = collections.defaultdict(lambda: [0, 0])   # 桶 → [命中, 形式错]
    for b in lemmas[h:]:
        if info[b][0] not in G.SAFE:
            continue
        got = real[b]
        gottags = {t for t, _ in got}
        for tags, w, sup in generate_with_support(
                info, IDX, support, b, G.keepset(use, tot, info, b)):
            bk = next((lo for lo, hi in BUCKETS if lo <= sup < hi), 0.999)
            if (tags, w) in got:
                strata[bk][0] += 1
            elif tags in gottags:      # 同一个 tags 下形式不同 ＝ 真错
                strata[bk][1] += 1
            # tags 不在源头里 ＝ 源头没列，不是错（`G.holdout` 的 ① 类）

    print("■ 留出集上：生成行的错误率 vs 变体支持度（只看 SAFE 五类）\n")
    print("   支持度区间      命中      🔴形式错     错率      占比")
    print("   " + "-" * 58)
    tot_hit = sum(v[0] for v in strata.values())
    tot_bad = sum(v[1] for v in strata.values())
    for lo, hi in BUCKETS:
        hit, bad = strata.get(lo, [0, 0])
        if hit + bad == 0:
            continue
        print("   [%.2f,%.2f) %9s %10s %8.3f%% %8.1f%%"
              % (lo, hi, format(hit, ","), format(bad, ","),
                 100.0 * bad / max(hit, 1), 100.0 * (hit + bad) / max(tot_hit + tot_bad, 1)))
    print("   " + "-" * 58)
    print("   合计       %9s %10s %8.3f%%"
          % (format(tot_hit, ","), format(tot_bad, ","),
             100.0 * tot_bad / max(tot_hit, 1)))

    # 决定性的一问：低支持度那几桶的错率，是不是显著高于满支持度那桶？
    low = [strata.get(lo, [0, 0]) for lo, hi in BUCKETS if lo < 0.9]
    lh, lb = sum(x[0] for x in low), sum(x[1] for x in low)
    fh, fb = strata.get(0.999, [0, 0])
    rl = 100.0 * lb / max(lh, 1)
    rf = 100.0 * fb / max(fh, 1)
    print("\n■ 判决")
    print("   支持度 <0.90 的行：%s 条，错率 %.3f%%" % (format(lh + lb, ","), rl))
    print("   支持度 =1.00 的行：%s 条，错率 %.3f%%" % (format(fh + fb, ","), rf))
    if lh + lb == 0:
        print("   ⇒ 🔴 低支持度的行**一条都没有** —— `learn()` 的 ≥50% 门槛之上，"
              "实际留下来的变体几乎都是满支持度的。残差**不可按支持度分层**。")
    elif rl > 2 * rf and rl > 0.05:
        print("   ⇒ ✅ **可分层**：低支持度行的错率是满支持度的 %.1f 倍 ⇒ "
              "值得把它们挑出来单独复核。" % (rl / max(rf, 1e-9)))
    else:
        print("   ⇒ ❌ **不可分层**：低支持度并不明显更容易错（%.3f%% vs %.3f%%）。"
              % (rl, rf))
        print("      ⇒ 没有外部韩语词典，这 0.043%% 是**不可约**的 —— 这就是 K18 的答案。")
    con.close()


if __name__ == "__main__":
    main()
