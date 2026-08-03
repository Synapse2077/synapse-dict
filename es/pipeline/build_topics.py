#!/usr/bin/env python3
"""领域标注 topics：入 `meta` 的 `top` 字段。2026-08-02。

═══ 规则（2026-08-02 双家评审后我裁决）═══
· **只保留叶子节点，剔掉父类**（两家独立收敛）。`leva` 的 9 个标签里
  `natural-sciences`/`physical-sciences`/`government` 全是父节点噪声。
· **一个义项最多 2 个标签**（豆包 2 / v4-pro 3，取窄的：产品是划词弹窗）。
· **第一期只用英文版，西语版押后** —— 这条是我加的，两家都没意识到：
  英文版的义项数组**就是我们 `meta` 的对齐基准**，零对齐成本；
  西语版的 21,096 词形要先有跨源义项对齐能力才能并进来（英文版电学义在第 7 条，
  西语版在第 4/5 条）。两家都轻描淡写说"先做义项对齐"，但我们现在做不了。

═══ 🔴 层级从哪来：不查表，从数据里推 ═══
kaikki 不给父子表。用**共现包含**推：若每个带 A 的义项都同时带 B、且 B 比 A 常见，
则 B 是 A 的祖先。于是一个义项的标签集里，**凡是别的标签的祖先，一律删掉**。
这样 `[sciences, natural-sciences, physical-sciences, chemistry]` → `[chemistry]`，
不需要任何外部本体表，也不会因为本体表过时而错。

⚠️ 事实核查过：**topics 是逐义项挂的，不是词条级**（`tierra` 的 5 个义项各有各的，
   顶层没有 topics 键）。豆包评审时把这条说反了，回源查过才敢用。

用法（在 es/ 目录）：
    python3 pipeline/build_topics.py            # 推本体 + 试算
    python3 pipeline/build_topics.py --apply
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

MAX_LABELS = 2


def scan_senses():
    """→ {word: [topic集, ...]}，**与库内 `meta` 数组逐位对齐**。

    🔴 **对齐不能靠"把义项首尾相接"猜，只能复用 build.py 自己的筛选逻辑。**
    库里的 `meta` 不是 kaikki 义项的原样拼接 —— build.py 会
      ① 跳过变位义（能抽出 base 的），它们进 `infl` 不进 `meta`；
      ② 按 gloss 去重（`real_seen`）。
    我先后猜错两次：第一版只收"有 topics 的记录"（`cuenca` 6 个义项只对上 3 个）；
    第二版改成收全部记录，反而更差（10,029 → 9,851）——**因为漏的是筛选规则，不是记录**。
    现在直接 import build.py 的 `is_infl_sense` / `base_of` / `ABBR_TAGS` 照着走一遍。
    """
    from pipeline.build import ABBR_TAGS, base_of, is_infl_sense

    out = collections.defaultdict(list)
    seen_gloss = collections.defaultdict(set)
    for ln in open(paths.KK, encoding="utf-8"):
        e = json.loads(ln)
        w = e.get("word")
        if not w:
            continue
        pos = e.get("pos")
        is_affix = pos in ("suffix", "prefix", "infix", "interfix")
        for s in e.get("senses") or []:
            tags = s.get("tags", [])
            is_abbr = bool(set(tags) & ABBR_TAGS)
            base = (base_of(s) if (not is_affix and not is_abbr and is_infl_sense(s))
                    else None)
            if base:
                continue                                  # 变位义 → 进 infl，不占 meta 位
            g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
            if not g or g in seen_gloss[w]:
                continue                                  # 与 build.py 同样按 gloss 去重
            seen_gloss[w].add(g)
            out[w].append(set(s.get("topics") or []))
    return {w: lst for w, lst in out.items() if any(lst)}


def derive_ancestors(all_sets):
    """共现包含 → {子: {祖先, ...}}。

    A 的祖先 B 的判据：**每一个带 A 的义项都带 B**，且 B 的出现次数严格多于 A。
    严格多于这一条很关键 —— 否则完全同现的一对（如始终成对出现的两个标签）
    会互相认作祖先，双双被删光。
    """
    cnt = collections.Counter()
    co = collections.defaultdict(collections.Counter)
    for s in all_sets:
        for a in s:
            cnt[a] += 1
            for b in s:
                if a != b:
                    co[a][b] += 1
    anc = collections.defaultdict(set)
    for a, n in cnt.items():
        for b, m in co[a].items():
            if m == n and cnt[b] > n:
                anc[a].add(b)
    return anc, cnt


def prune(topics, anc, cnt):
    """删掉集合内部的祖先，再按"越罕见越具体"取前 MAX_LABELS 个。"""
    if not topics:
        return []
    drop = set()
    for t in topics:
        drop |= (anc.get(t, set()) & topics)
    leaves = topics - drop
    if not leaves:                       # 全互为祖先（理论上不该有）→ 退回原集合
        leaves = topics
    return sorted(leaves, key=lambda t: (cnt.get(t, 0), t))[:MAX_LABELS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    per_word = scan_senses()
    all_sets = [s for lst in per_word.values() for s in lst if s]
    anc, cnt = derive_ancestors(all_sets)

    print("■ 推出的本体（样例：最常见的 12 个标签各自的祖先）")
    for t, n in cnt.most_common(12):
        print("    %-22s 出现 %6d   祖先: %s" % (t, n, sorted(anc.get(t, set())) or "—（顶层）"))

    print("\n■ 剪枝效果（评审材料里的四个词）")
    for w in ("leva", "prolina", "tectónica", "cuenca"):
        for s in per_word.get(w, []):
            if s:
                print("    %-12s %-58s → %s" % (w, str(sorted(s))[:58], prune(s, anc, cnt)))

    # ── 落到库：按义项顺序写进 meta[i]["top"] ──────────────────────────
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word, meta FROM dict WHERE is_lemma=1 AND TRIM(COALESCE(meta,''))<>''"
    ).fetchall()
    conn.close()

    plan, samples = [], []
    n_sense = n_row = mismatch = 0
    for rid, w, mj in rows:
        lst = per_word.get(w)
        if not lst:
            continue
        try:
            meta = json.loads(mj)
        except Exception:
            continue
        flat = lst
        if len(flat) != len(meta):
            mismatch += 1
            continue                     # 对不齐就整条不动（同 devoice_coda 的做法）
        hit = False
        for i, s in enumerate(flat):
            p = prune(s, anc, cnt)
            if p:
                meta[i]["top"] = p
                n_sense += 1
                hit = True
        if hit:
            n_row += 1
            plan.append((json.dumps(meta, ensure_ascii=False), rid))
            if len(samples) < 300:
                samples.append((w, str([m.get("top") for m in meta if m.get("top")])[:46],
                                str(sorted(flat[0]))[:44]))

    print("\n■ 落点：lemma 行 %s 条获得 top（义项 %s 个）" % (
        format(n_row, ","), format(n_sense, ",")))
    print("    义项数对不齐、整条跳过：%s" % format(mismatch, ","))
    dbtool.sample_check(samples, n=12, cols=("词", "剪枝后 top", "原始 topics(首个义项)"))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库)")
        return
    # meta 全库非空数不变（只往已有 JSON 里加键）→ 所有列都应零变化。
    with dbtool.session("topics", expect={}) as s:
        s.executemany("UPDATE dict SET meta=? WHERE id=?", plan)


if __name__ == "__main__":
    main()
