#!/usr/bin/env python3
"""阶段 1a：把**尺子**挂到 `dict` —— 词频与考纲。2026-09-07。

计划见 `docs/EN_PLAN.md` 阶段表 1。零 API 成本、纯确定性。

═══ 为什么这一步排在最前 ═══
`collins`/`oxford`/`exam_tag`/`bnc`/`freq_rank` **不是内容，是尺子**（`EN_PLAN` §2.3）：
  · 阶段 3b 用它给 ECDICT 补充词分层（哪些值得收）
  · 阶段 1.5 用它切「翻译买到哪条线为止」
  · 阶段 9 用它排搜索下拉（`freq_rank ASC`）
  · 阶段 5 的 `freq_zipf` 要跟它对照
放到后面 ＝ 中间每一步都没尺子，只能盲抽。而且它是**五门都没有的资产**。

═══ 🔴 判据：BINARY 精确匹配，不做忽略大小写 ═══
`legacy_dict.word` 无重复（3,929,564 行 = 3,929,564 个不同 word），连接无歧义。
NOCASE 能多挂 **12,834** 条 —— **实测这批一条都不该挂**（随机 20 条全是污染）：

    dict.Lead   ← legacy.lead    铅，考纲 zk gk cet4，frq 318
    dict.Trance ← legacy.trance  昏睡状态，frq 12432
    dict.das    ← legacy.DAS     双挂接站
    dict.arnot  ← legacy.Arnot   人名阿诺特
    dict.BU     ← legacy.bu      蒲式耳

`Lead`（姓氏/专名）与 `lead`（铅）**是两个词**，把后者的考纲等级和词频挂到前者身上，
既错又会污染阶段 9 的排序。这正是 `[[case-folding-contaminates-columns]]` 记的那个病。
⇒ **精确匹配，那 12,834 条有意不要**，记在收尾单上而不是偷偷挂。

═══ provenance 一并写 ═══
每挂一个字段就往 `field_src` 写一行 `(word_id, field, 'ecdict')`。
🔴 **表结构里不出现 ECDICT，来源里必须出现**（用户 2026-09-07 定）——
   `field_src` 正是"来源"该待的地方。de 那张表的 `src` 恒为 `unsourced`（它说不出来源），
   en 这批说得出，所以写实。

跑：
    cd en && python3 pipeline/attach_rulers.py
    cd en && python3 pipeline/attach_rulers.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import sqlite3

import dbtool
import paths

SRC = "ecdict"
# (dict 列名, legacy_dict 列名, 是不是数值列)
FIELDS = [("collins", "collins", True), ("oxford", "oxford", True),
          ("exam_tag", "tag", False), ("bnc", "bnc", True), ("freq_rank", "frq", True)]


def collect():
    """→ (plan, stat)；plan = [(collins, oxford, exam_tag, bnc, freq_rank, word_id)]"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # legacy 侧只取有尺子的行 —— 很小（5.9 万），全部进内存，避免在只有 NOCASE 索引的
    # 冻结表上做 BINARY 连接（`[[query-perf-collation-traps]]`：本项目已撞过五次）。
    L = {}
    for w, co, ox, tg, bn, fq in con.execute(
            "SELECT word, collins, oxford, tag, bnc, frq FROM legacy_dict "
            "WHERE COALESCE(collins,0)>0 OR COALESCE(oxford,0)>0 "
            "   OR COALESCE(TRIM(tag),'')<>'' OR COALESCE(bnc,0)>0 OR COALESCE(frq,0)>0"):
        L[w] = (co or None, ox or None, (tg or "").strip() or None, bn or None, fq or None)
    # 🔴 **幂等**：只写「现在还没有」的那些，`expect` 报的是**增量**不是总数。
    #    3b 收词之后 core 3,564 / judged 745 才进库，本步要能重跑一次把它们补上；
    #    重跑时已挂过的行必须一个都不动（否则闸会把"重复写同一个值"报成未声明变化）。
    plan, add_by_field = [], {f[0]: 0 for f in FIELDS}
    now_by_field = {f[0]: 0 for f in FIELDS}
    n_dict = 0
    for wid, w, co0, ox0, tg0, bn0, fq0 in con.execute(
            "SELECT id, word, collins, oxford, exam_tag, bnc, freq_rank FROM dict"):
        n_dict += 1
        cur = (co0, ox0, tg0, bn0, fq0)
        for i, (col, _, _) in enumerate(FIELDS):
            if cur[i] is not None:
                now_by_field[col] += 1
        v = L.get(w)                       # 🔴 BINARY，不 lower()
        if not v:
            continue
        if all(a == b for a, b in zip(cur, v)):
            continue                        # 已经是目标值，不动
        plan.append((v[0], v[1], v[2], v[3], v[4], wid))
        for i, (col, _, _) in enumerate(FIELDS):
            if v[i] is not None and cur[i] is None:
                add_by_field[col] += 1
    con.close()
    return plan, {"legacy_with_ruler": len(L), "dict_rows": n_dict,
                  "matched_words": len(plan), "by_field": add_by_field,
                  "now": now_by_field}


def gates(con, stat):
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [("%s 有值的行" % col, q("SELECT COUNT(*) FROM dict WHERE %s IS NOT NULL" % col),
               stat["now"][col] + stat["by_field"][col]) for col, _, _ in FIELDS]
    checks += [
        ("field_src 行数 == 挂上的字段总数",
         q("SELECT COUNT(*) FROM field_src"),
         sum(stat["now"].values()) + sum(stat["by_field"].values())),
        ("field_src 的 src 全是 ecdict",
         q("SELECT COUNT(*) FROM field_src WHERE src<>'%s'" % SRC), 0),
        ("field_src 的 word_id 都在 dict 里",
         q("SELECT COUNT(*) FROM field_src f LEFT JOIN dict d ON d.id=f.word_id "
           "WHERE d.id IS NULL"), 0),
        # 🔴 没挂上的行必须仍然全空 —— 防"顺手填了个默认值"
        ("没挂上的行 freq_rank 仍为空",
         q("SELECT COUNT(*) FROM dict WHERE freq_rank IS NOT NULL"),
         stat["now"]["freq_rank"] + stat["by_field"]["freq_rank"]),
        ("dict 行数未变", q("SELECT COUNT(*) FROM dict"), stat["dict_rows"]),
        ("legacy_dict 未被触碰", q("SELECT COUNT(*) FROM legacy_dict"),
         q("SELECT COUNT(*) FROM legacy_dict")),
        # 🔴 大小写污染的负控：`Lead` 不许拿到 `lead` 的考纲等级
        ("大小写污染负控（Lead 无考纲）",
         q("SELECT COUNT(*) FROM dict WHERE word='Lead' AND exam_tag IS NOT NULL"), 0),
        ("负控对照（lead 有考纲）",
         q("SELECT COUNT(*) FROM dict WHERE word='lead' AND exam_tag IS NOT NULL"), 1),
    ]
    return checks


def report(checks):
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-36s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    plan, stat = collect()
    print("═══ 阶段 1a 计划 ═══")
    print("   legacy 侧有尺子的词      %9s" % format(stat["legacy_with_ruler"], ","))
    print("   dict 词形                %9s" % format(stat["dict_rows"], ","))
    print("   🔴 本次要写的行（增量）    %9s" % format(stat["matched_words"], ","))
    print("      %-10s %9s %9s" % ("字段", "现有", "本次新增"))
    for col, _, _ in FIELDS:
        print("      %-10s %9s %9s"
              % (col, format(stat["now"][col], ","), format(stat["by_field"][col], ",")))
    print("   field_src 增量           %9s 行" % format(sum(stat["by_field"].values()), ","))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0

    fs = []
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    con.close()
    exp = {col: stat["by_field"][col] for col, _, _ in FIELDS}
    exp["#field_src"] = sum(stat["by_field"].values())
    with dbtool.session("keep-v3-1a-rulers", expect=exp) as s:
        s.executemany(
            "UPDATE dict SET collins=?, oxford=?, exam_tag=?, bnc=?, freq_rank=? WHERE id=?",
            plan)
        for row in plan:
            wid = row[5]
            for i, (col, _, _) in enumerate(FIELDS):
                if row[i] is not None:
                    fs.append((wid, col, SRC))
        # 幂等：(word_id, field) 是主键，重跑时已有的行原样保留
        s.executemany("INSERT OR IGNORE INTO field_src (word_id, field, src) VALUES (?,?,?)", fs)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = report(gates(con, stat))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
