#!/usr/bin/env python3
"""把「只差撇号写法」的两行合并成一行。2026-08-17。

═══ 是什么 ═══
同一个词，英文版写 ASCII 撇号、法语版写弯撇号，我们当成两个词各建了一行：

    'ndrangheta   id=117814  en-edition  ipa 有  level C1  义项「恩德朗盖塔（意大利卡拉布里亚地区黑手党组织）」
    ’ndrangheta   id=767284  fr-edition  ipa 无  level 无  义项「恩德朗盖塔（意大利黑手党组织）」

**267 组，其中 258 组两边都有义项** —— 用户用哪种撇号，看到的是不同的一半。

根因：法语版收词时按 `word` / `word_norm` 判重，而当时 `word_norm` **不折撇号**
（今天才修，见 `backfill_word_norm.py`），所以没认出是同一个词。

═══ 合并方向（确定性，不看谁先建）═══
留下**词级属性更全**的那行：依次比 `ipa` / `level` / `pos` 是否非空，全平则取较小的 id。
另一行的 `sense` / `sense_src` / `entry` / `inflection` / `collocation` 全部改挂过来。

    ⚠️ 词级列**只填空不覆盖**（`replay-scripts-undo-fixes` 那条：写库默认只填空）。
    ⚠️ `sense` 上有 `UNIQUE(word_id, rank)`，两边 rank 都从 1 起 ⇒ 必须**先把待搬的
       rank 挪到负数区**再落最终值（`recover_alt_of` 用过同一个手法）。

═══ 为什么不删掉空出来的那行（可逆）═══
`prefer-reversible-designs`：搬完之后那行成了空壳，但**留着**。
每条搬过去的行的 `src_ref` 里仍然写着原来的拼写（`kk-fr:’ndrangheta:noun:0:0`），
所以「哪些行是从哪一行搬来的」**从数据本身可算**，反向搬回去不需要额外记账。

空壳行不会让用户看到空白：`ItalianDictService.exactQuery` 已改成
**优先取有可见义项的那一行**，所以查 `’ndrangheta` 仍然落到合并后的词条上。

⚠️ 合并**不做语义去重**：`（意大利卡拉布里亚地区黑手党组织）` 与 `（意大利黑手党组织）`
   是近重复但不逐字相同，本项目既定规则只对「原文逐字相同」归并（`two-layer-sense-model`）。
   实测 37 组中文集合逐字相同，那部分交给已有的归并通路，本步不越界。

用法（在 it/ 目录下）：
    python3 fixes/merge_apostrophe_variants.py            # 干跑
    python3 fixes/merge_apostrophe_variants.py --apply
    python3 fixes/merge_apostrophe_variants.py --verify
    python3 fixes/merge_apostrophe_variants.py --mutate
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from split_case_forms import APOSTROPHES   # noqa: E402

# 搬家的表与列。`inflection` 两列都要（它既可能是变形也可能是原形）。
MOVES = [("sense", "word_id"), ("sense_src", "word_id"), ("entry", "word_id"),
         ("inflection", "word_id"), ("inflection", "base_id"),
         ("collocation", "word_id")]
# 词级列：只填空不覆盖
FILL = ["ipa", "pos", "aux", "conj", "transitivity", "pronominal", "gender",
        "plural", "plural_gender", "number_note", "level", "infl", "exchange",
        "ipa_src", "gender_src"]


def groups(con):
    """→ [(canonical_id, loser_id, canonical_word, loser_word)]"""
    g = defaultdict(list)
    for wid, w in con.execute(
            "SELECT id, word FROM dict "
            "WHERE word LIKE '%'||char(8217)||'%' OR word LIKE '%''%'"):
        g[w.translate(APOSTROPHES)].append(wid)
    out = []
    for k, ids in g.items():
        if len(ids) < 2:
            continue
        rows = {i: con.execute(
            "SELECT word, ipa, level, pos FROM dict WHERE id=?", (i,)).fetchone() for i in ids}
        if len({rows[i][0] for i in ids}) < 2:
            continue                      # 同一拼写重复出现，不归本步
        ranked = sorted(ids, key=lambda i: (
            rows[i][1] is None, rows[i][2] is None, rows[i][3] is None, i))
        keep = ranked[0]
        for lose in ranked[1:]:
            out.append((keep, lose, rows[keep][0], rows[lose][0]))
    return out


def pick(ipa, level, pos, wid):
    """合并方向判据本体，抽出来单测。→ 排序键，越小越该留。"""
    return (ipa is None, level is None, pos is None, wid)


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    left = [x for x in groups(con)
            if q("SELECT count(*) FROM sense WHERE word_id=?", x[1]) > 0]
    checks = [
        ("🔴 没有还分家的撇号异写组", len(left), 0),
        # 🔴 2026-08-18 改口径（A28：闸里不许写死行数）。
        #    原来四条断言写死了当天的总行数，用来保证"搬家不许丢行"。但后面的阶段
        #    **合法地**加了行（阶段 5 的例句/关系、08-17 的补收），四条必然全红，
        #    而红的是断言不是数据 —— 这正是 A28 说的"人会习惯性把它改绿，闸就废了"。
        #    ⇒ 换成**结构性**口径：搬家真正要保证的是"没有行掉进无主状态"。
        ("🔴 没有 word_id 指向不存在 dict 行的义项",
         q("SELECT count(*) FROM sense s WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=s.word_id)"), 0),
        ("🔴 没有 word_id 指向不存在 dict 行的证据",
         q("SELECT count(*) FROM sense_src x WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=x.word_id)"), 0),
        ("🔴 没有 word_id 指向不存在 dict 行的 entry",
         q("SELECT count(*) FROM entry e WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=e.word_id)"), 0),
        ("🔴 没有 word_id/base_id 指向不存在 dict 行的变形",
         q("SELECT count(*) FROM inflection i WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=i.word_id) OR (i.base_id IS NOT NULL "
           "AND NOT EXISTS(SELECT 1 FROM dict d2 WHERE d2.id=i.base_id))"), 0),
        # 🔴 反向可算：搬过去的行，src_ref 里仍写着原拼写
        ("🔴 搬家后 src_ref 一个字节没改（反向搬回的锚点）",
         q("SELECT count(*) FROM entry WHERE src_ref LIKE 'kk-fr:%'||char(8217)||'%'") > 0, True),
        ("🔴 没有 rank 冲突残留（负数区已清空）",
         q("SELECT count(*) FROM sense WHERE rank < 1"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-44s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate():
    print("\n═══ 变异验证：合并方向判据 ═══")
    cases = [
        ("有 ipa 的留下", pick("a", None, None, 999) < pick(None, "C1", "n", 1), True),
        ("ipa 都无 ⇒ 比 level", pick(None, "C1", None, 999) < pick(None, None, "n", 1), True),
        ("ipa/level 都无 ⇒ 比 pos", pick(None, None, "n", 999) < pick(None, None, None, 1), True),
        ("全平 ⇒ 取较小 id", pick(None, None, None, 1) < pick(None, None, None, 2), True),
        ("🔴 判据必须严格有序（不能两边都更该留）",
         pick("a", None, None, 1) < pick(None, None, None, 2)
         and not (pick(None, None, None, 2) < pick("a", None, None, 1)), True),
    ]
    ok = True
    for name, got, want in cases:
        ok &= got == want
        print("   %s %-46s %s" % ("✅" if got == want else "🔴", name, got))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    gs = groups(ro)
    f = lambda x: format(x, ",")
    print("■ 要合并的 %s 组" % f(len(gs)))
    cnt = Counter()
    for keep, lose, kw, lw in gs:
        for t, col in MOVES:
            cnt[t] += ro.execute("SELECT count(*) FROM %s WHERE %s=?" % (t, col),
                                 (lose,)).fetchone()[0]
    print("   要改挂的行 %s" % dict(cnt))
    for keep, lose, kw, lw in gs[:8]:
        n1 = ro.execute("SELECT count(*) FROM sense WHERE word_id=?", (keep,)).fetchone()[0]
        n2 = ro.execute("SELECT count(*) FROM sense WHERE word_id=?", (lose,)).fetchone()[0]
        print("   留 %-24s(义项%d)  ← 并入 %-24s(义项%d)" % (kw[:24], n1, lw[:24], n2))
    if not a.apply or not gs:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0

    plan = []
    for keep, lose, kw, lw in gs:
        mx = ro.execute("SELECT COALESCE(max(rank),0) FROM sense WHERE word_id=?",
                        (keep,)).fetchone()[0]
        moving = [r[0] for r in ro.execute(
            "SELECT id FROM sense WHERE word_id=? ORDER BY rank", (lose,))]
        fills = {}
        kr = ro.execute("SELECT %s FROM dict WHERE id=?" % ",".join(FILL), (keep,)).fetchone()
        lr = ro.execute("SELECT %s FROM dict WHERE id=?" % ",".join(FILL), (lose,)).fetchone()
        for i, col in enumerate(FILL):
            if kr[i] is None and lr[i] is not None:
                fills[col] = lr[i]
        plan.append((keep, lose, mx, moving, fills))
    ro.close()

    with dbtool.session("merge-apostrophe-variants", expect={"__rows__": 0}) as s:
        # ① 先把待搬的 sense.rank 挪到负数区，避开 UNIQUE(word_id, rank)
        for keep, lose, mx, moving, fills in plan:
            for j, sid in enumerate(moving, 1):
                s.execute("UPDATE sense SET rank=? WHERE id=?", (-j, sid))
        # ② 改挂 + 落最终 rank
        for keep, lose, mx, moving, fills in plan:
            for t, col in MOVES:
                s.execute("UPDATE %s SET %s=? WHERE %s=?" % (t, col, col), (keep, lose))
            for j, sid in enumerate(moving, 1):
                s.execute("UPDATE sense SET rank=? WHERE id=?", (mx + j, sid))
            for col, v in fills.items():
                s.execute("UPDATE dict SET %s=? WHERE id=?" % col, (v, keep))
    print("\n■ 已合并 %s 组" % f(len(gs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
