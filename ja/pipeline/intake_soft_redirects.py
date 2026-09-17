#!/usr/bin/env python3
"""阶段 5b-前置 —— 补收 `soft-redirect` 词形。零模型调用。2026-09-15。

═══ 这是阶段 0 白纸黑字欠下的账 ═══
阶段 0 的记录写着：

    🔴 `soft-redirect` 的词形**本步不收**：现在插进来只有词形、没有指向、没有义项，
       等于造 4.5 万个「搜得到、点进去空白页」⇒ **连同指向一起进阶段 3**。

阶段 3a 收词收的是「日语版/中文版**有真义项**而我们没有的词形」——
而 soft-redirect 的定义就是**它没有义项**（`tags=['no-gloss']`）。
⇒ 判据把它们整类排除在外，**阶段 3a 的闸全绿，账上那句话没人兑现**。
   `[[llm-as-evaluator-discipline]]` ⑫ 说的是判官取数会把一整类人排除在外；
   这里是**收词判据**把一整类词排除在外，形状一模一样。

═══ 代价是实打实的：这批词现在搜不到 ═══
    あいする → 愛する      いんりょく → 引力      あふりか → アフリカ
    AA      → アスキーアート  new       → ニュー     美德      → 美徳

全假名拼写、旧字体、罗马字缩写 —— **正是读者最可能敲进搜索框的那种写法**。
缺 31,202 个，其中 **30,988 个（99.3%）的目标就在库里**，接上就能用。

═══ 只收一对一那批 ═══
`JA_PLAN` §二.5：目标 ≥2 的是**同音索引页**（`いぬ → 犬 狗 戌 率寝 寝ぬ 去ぬ`），
当异体收进来是 7,288 条规模的错。本步与 `harvest_relations` 用**同一条判据**。

═══ 🔴 它们不是"空白页"，但要让闸也这么认为 ═══
P6 的空白页判据原来是「有义项 或 有变形」。这批词两样都没有，有的是**指向**。
读者点进去看到「→ 愛する」并不是空白页，那是**跳转页**，正是源头说它是的东西。
⇒ 判据要跟着改（`ja/tests/test_plan_ledger.py` 的 COVERAGE），
   但**必须是在这里把跳转关系真的建出来之后**才改 ——
   先改判据再补数据就是 `[[proxy-metric-gets-optimized]]`：为了让指标好看而动指标。

用法（在仓库根）：
    python3 -u ja/pipeline/intake_soft_redirects.py
    python3 -u ja/pipeline/intake_soft_redirects.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import json
import sqlite3

import dbtool
import paths
from pipeline.build import norm_ja

f = lambda n: format(n, ",")


def collect(have):
    """→ {词形: (目标, 来源)}，只含一对一且**词形不在库里**的。"""
    out, st = {}, collections.Counter()
    for name, op, lc in [("en-edition", lambda: open(paths.KK, encoding="utf-8"), None),
                         ("zh-edition", lambda: gzip.open(paths.ZH_EDITION, "rt",
                                                          encoding="utf-8"), "ja")]:
        with op() as fh:
            for line in fh:
                if '"soft-redirect"' not in line:
                    continue
                o = json.loads(line)
                if o.get("pos") != "soft-redirect":
                    continue
                if lc and o.get("lang_code") != lc:
                    continue
                r = o.get("redirects") or []
                w = o.get("word") or ""
                if not w:
                    continue
                if len(r) != 1:
                    st[name + "/⚪ 同音索引页（≥2 目标）有意不收"] += 1
                    continue
                if w in have:
                    st[name + "/词形已在库（只补关系，不插词）"] += 1
                    continue
                t = (r[0] or "").strip()
                if not t or t == w:
                    st[name + "/🔴 丢：目标空或指向自己"] += 1
                    continue
                if w not in out:
                    out[w] = (t, name)
                    st[name + "/⭐ 补收"] += 1
    return out, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()
    new, st = collect(have)
    for k in sorted(st):
        print("   %-46s %s" % (k, f(st[k])))
    hit = sum(1 for t, _ in new.values() if t in have)
    print("\n■ 补收词形 %s｜目标已在库 %s (%.1f%%)"
          % (f(len(new)), f(hit), 100 * hit / max(len(new), 1)))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        for w, (t, s) in list(new.items())[:8]:
            print("   %-12s → %-12s %s" % (w, t, s))
        return

    # 🔴 `is_lemma=1`：它是一个**词头**（读者会搜它），不是某个词的变形。
    #    变形层的 `is_lemma=0` 说的是"这是活用形"，跟异表记是两回事。
    # 🔴 `dict` 的行数键是 `__rows__`（打印成「总行」），**不是 `#dict`** ——
    #    `#` 前缀那一族是出版层各表。第一版我写 `"#dict": len(new)`，
    #    于是 expect 里多了一个谁也不认的键、而真正要授权的那个增量没被授权，
    #    闸当场拦下（「总行数变了 +31,202，期望 +0」）。**闸是对的，我写错了授权。**
    # 🔴 收词闸：本步插 3 万词形，它们没有义项/变形/读音，**只有指向** ——
    #    所以受影响的就是空白页那一项（当场从 98.17% 掉到 93.9%，P6 报红）。
    with dbtool.session("ja-intake-soft-redirects", invalidates=[
            "**不是**空白页的词形占比"], expect={
            "__rows__": len(new), "#entry": 0, "#sense": 0, "#sense_gloss": 0,
            "#inflection": 0, "#example": 0}) as con:
        con.executemany(
            "INSERT OR IGNORE INTO dict(word, word_norm, is_lemma) VALUES(?,?,1)",
            [(w, norm_ja(w)) for w in new])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("补收的词形都进库了", all(
            con.execute("SELECT 1 FROM dict WHERE word=?", (w,)).fetchone()
            for w in list(new)[:2000])),
        ("没有重复词形", q(
            "SELECT COUNT(*) FROM (SELECT word FROM dict GROUP BY word HAVING COUNT(*)>1)") == 0),
        ("word_norm 都非空", q("SELECT COUNT(*) FROM dict WHERE word_norm IS NULL "
                             "OR word_norm=''") == 0),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    print("\n⚠️ 关系还没建 —— **下一步必须马上跑 `harvest_relations.py --apply`**，")
    print("   否则这 %s 个词形就是货真价实的空白页（正是阶段 0 不肯收它们的理由）。" % f(len(new)))
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
