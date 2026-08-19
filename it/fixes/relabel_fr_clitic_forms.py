#!/usr/bin/env python3
"""重算法语版变形的中文语法说明。2026-08-17。

═══ 修什么 ═══
`intake_fr_forms.parse_gloss` 第一版把整句法语散文喂进 `FR2TAG`，而合体形的散文里
`avec le pronom` **之后**描述的是**代词**，不是动词形式：

    Agglutination du verbe accintolare avec le pronom personnel masculin singulier lo
                                                       └──────────────────────────┘
                                           「阳性单数」说的是代词 lo

⇒ `accintolarlo` 标成「**单数**＋代词」，正确是「不定式＋代词」。**22,308 条**中招。
  对照组 `avec le pronom ne`（没有性数词）第一版就标对了 —— 这也是定位到根因的线索。

判据已在 `intake_fr_forms.PRONOUN_HALF` 修好并变异验证（10/10）。本脚本负责**回填已落库的行**。

═══ 为什么重算全部而不是只改那 22,308 条 ═══
「哪些行错了」是我按当前认知圈的；重算全部再逐行 diff，**范围由数据自己给出**。
实测差异确实不止 22,308 条那一族（截断也影响到少数别的措辞），只挑一族改会留残差。

⚠️ 判据与写入共用同一个 `parse_gloss` —— 闸和写库若各写一遍，改了一处另一处不动，
   就会出现"永远通过的检查"（`verification-gates-not-sampling`）。

用法（在 it/ 目录下）：
    python3 fixes/relabel_fr_clitic_forms.py            # 干跑，只报差异
    python3 fixes/relabel_fr_clitic_forms.py --apply
    python3 fixes/relabel_fr_clitic_forms.py --verify
"""
import argparse
import gzip
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from intake_en_forms import OK, deaccent_inner       # noqa: E402
from intake_fr_forms import DUMP, parse_gloss        # noqa: E402


def recompute():
    """扫 dump，→ {归一词形: {原形: 应有的中文说明}}。与收词时**同一个** parse_gloss。

    ⚠️ 键必须是 **(词形, 原形)** 两元组，不能只用词形：
       `contrarla` 在 dump 里出现三次（`du verbe contrare` / `du verbe contrarre` / 空 gloss），
       第一版用词形当键、后者覆盖前者 ⇒ 库里那行 base='contrare' 与重算的 'contrarre'
       对不上，被判成"没差异"而漏修 1 行。闸报红才发现。
       （同一个面：法语版有 2,914 个词形指向多个原形。）
    """
    want = defaultdict(dict)
    with gzip.open(DUMP, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("lang_code") != "it":
                continue
            w = d.get("word")
            if not w or not OK.match(w):
                continue
            s0 = (d.get("senses") or [None])[0]
            if not s0:
                continue
            base, lab = parse_gloss((s0.get("glosses") or [""])[0], s0.get("tags") or [])
            if base and lab:
                want[deaccent_inner(w)][base] = lab
    return want


def diffs(con):
    """→ [(inflection.id, 词形, 旧说明, 新说明)]，只看本流水线写的行。"""
    want = recompute()
    out = []
    for iid, w, base, lab in con.execute(
            "SELECT i.id, d.word, i.base, i.label_zh FROM inflection i "
            "JOIN dict d ON d.id = i.word_id WHERE i.src_ref LIKE 'kkform-fr:%'"):
        exp = want.get(w, {}).get(base)
        if exp and exp != lab:
            out.append((iid, w, lab, exp))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    d = diffs(con)
    checks = [
        ("🔴 重算与库内逐行一致", len(d), 0),
        # 🔴 这一族本来就不该存在：合体形的中文说明里不许只有代词的性数
        ("🔴 没有「单数＋代词」这种只描述代词的说明",
         q("SELECT count(*) FROM inflection WHERE src_ref LIKE 'kkform-fr:%' "
           "AND label_zh IN ('单数＋代词','复数＋代词','阴性单数＋代词','阳性单数＋代词')"), 0),
        ("🔴 label_zh 不许为空",
         q("SELECT count(*) FROM inflection WHERE src_ref LIKE 'kkform-fr:%' "
           "AND (label_zh IS NULL OR trim(label_zh)='')"), 0),
    ]
    ok = True
    for name, got, want_ in checks:
        ok &= got == want_
        print("   %s %-40s %s (期望 %s)" % ("✅" if got == want_ else "🔴", name, got, want_))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1

    d = diffs(ro)
    f = lambda x: format(x, ",")
    print("■ 需要改说明的 %s 行" % f(len(d)))
    c = Counter((o, n) for _, _, o, n in d)
    for (o, n), k in c.most_common(12):
        print("   %-22s → %-26s %s" % (o, n, f(k)))
    for iid, w, o, n in d[:6]:
        print("   %-24s %s → %s" % (w[:24], o, n))
    if not a.apply or not d:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0
    ro.close()
    with dbtool.session("relabel-fr-clitic-forms", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE inflection SET label_zh=? WHERE id=?",
                      [(n, iid) for iid, _, _, n in d])
    print("\n■ 已改 %s 行" % f(len(d)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
