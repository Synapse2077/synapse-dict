#!/usr/bin/env python3
"""**关系闸** —— 阶段 6b 的不变量。ru，2026-10-23。

    python3 ru/tests/test_relation.py
    python3 ru/tests/test_relation.py --mutate
    python3 ru/tests/test_relation.py --accept     # 把各 kind 的可出版行数锁成基线

═══ 这一层最容易出的错 ═══
① **值域漂**（R1/R9）：kind 只有登记表里那些；`word_family` 只许来自 ru 版、`aspect_pair` 只许来自
   en/zh 版的 `forms`；词族两个分组列只有一套键（ko K8/K10：一列两套值域）。
② **死链／错链**（R4）：`target_id` 有值 ⇒ 那个词形真是目标；为空 ⇒ dict 里真没有它（两个方向）。
③ **藏错**（R7/R8）：B17 两个方向都断言 —— 只断言「该藏的藏了」，「全都藏掉」也能满足它（vi 的教训）。
④ 判据本身写坏时两边一致报绿 ⇒ **R10 钉已知答案**（常量，B20）。
"""
import argparse
import collections
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline import relation_layer as RL                       # noqa: E402

ROSTER = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12")
ACCEPT = HERE / ".relation_accept.json"
SRC_DOMAIN = frozenset({"en-edition", "ru-edition", "zh-edition-simp", "zh-edition-trad",
                        "fr-edition", "vi-edition", "pl-edition"})
KIND_DOMAIN = frozenset(criteria.REL_KINDS.values()) | {"word_family", "aspect_pair"}
REL_GROUP_DOMAIN = frozenset(criteria.FAMILY_POS.values()) | {"adverbial-participle"}
SUBKIND_DOMAIN = frozenset(criteria.ASPECT_SUBKIND.values())
_REF = re.compile(r"^rel:kk-[a-z-]+:.+:(?:w|s\d+|forms):[a-z_]+:\d+$")

# R10 已知答案（取自 dump 原文，2026-10-23 核过）：(词形, kind, 目标, 期望)
#   期望是 dict：sense_has（挂到的义项的 ru 释义含这串）／rel_group／form_group／subkind／absent（不许有这行）
KNOWN = (
    ("ё", "synonym", "йо", {"sense_has": "приветствие"}),       # ru 版 sense_index=2 落在「招呼语」
    ("банк", "word_family", "банкир", {"rel_group": "noun", "form_group": "closest"}),
    ("полвека", "word_family", "полпирога", {"rel_group": None}),  # 残渣标签 `, полпизды` ⇒ 分组记空
    ("показать", "aspect_pair", "пока́зывать", {"subkind": None}),
    ("скакать", "aspect_pair", "скакну́ть", {"subkind": "semelfactive"}),
    ("принудить", "aspect_pair", "принуди́ловка", {"absent": True}),  # noun-from-verb 不是体对
    ("шесть", "coordinate", "сто", {}),                          # en 数词框 `100: сто` 剥前缀
)


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def _accept():
    try:
        return json.loads(ACCEPT.read_text("utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def kind_counts(con):
    return dict(con.execute("SELECT kind, COUNT(*) FROM sense_relation WHERE hidden=0 GROUP BY kind"))


def checks(con):
    out = []
    q = lambda s, *a: con.execute(s, a).fetchone()[0]                  # noqa: E731
    n = q("SELECT COUNT(*) FROM sense_relation")

    # R1 值域：src／kind；word_family 只来自 ru 版、aspect_pair 只来自 en/zh 版
    srcs = {r[0] for r in con.execute("SELECT DISTINCT src FROM sense_relation")}
    kinds = {r[0] for r in con.execute("SELECT DISTINCT kind FROM sense_relation")}
    wf_bad = q("SELECT COUNT(*) FROM sense_relation WHERE kind='word_family' AND src NOT IN (%s)"
               % ",".join("'%s'" % s for s in criteria.WORD_FAMILY_SRC))
    ap_bad = q("SELECT COUNT(*) FROM sense_relation WHERE kind='aspect_pair' AND src NOT IN (%s)"
               % ",".join("'%s'" % s for s in criteria.ASPECT_PAIR_SRC))
    ru_rel = q("SELECT COUNT(*) FROM sense_relation WHERE kind='related' AND src IN (%s)"
               % ",".join("'%s'" % s for s in criteria.WORD_FAMILY_SRC))
    out.append(("R1", n > 0 and srcs == SRC_DOMAIN and kinds <= KIND_DOMAIN and not (wf_bad or ap_bad or ru_rel),
                "%s 行／版 %d／kind 值域外 %s／缺版 %s／词族来源错 %d／体对来源错 %d／ru 版仍有 related %d" % (
                    format(n, ","), len(srcs), sorted(kinds - KIND_DOMAIN), sorted(SRC_DOMAIN - srcs),
                    wf_bad, ap_bad, ru_rel)))

    # R2 hidden ⟺ hidden_why，且原因只有两种
    bad = q("SELECT COUNT(*) FROM sense_relation WHERE (hidden=1) <> (hidden_why IS NOT NULL AND "
            "TRIM(hidden_why)<>'')")
    why = {r[0] for r in con.execute("SELECT DISTINCT hidden_why FROM sense_relation WHERE hidden=1")}
    extra = why - {criteria.REL_DUP, criteria.REL_REDUNDANT}
    out.append(("R2", bad == 0 and not extra, "hidden/why 不一致 %d／原因值域外 %s" % (bad, sorted(extra))))

    # R3 目标形状：带西里尔（缩写除外）、没有标记残渣、没有数字前缀
    rows = con.execute("SELECT id, word_id, entry_id, sense_id, kind, target, target_id, hidden FROM "
                       "sense_relation").fetchall()
    bad3 = collections.Counter()
    for r in rows:
        t = r[5]
        if not t.strip():
            bad3["空"] += 1
        elif not criteria._has_cyrillic(t) and r[4] != "abbreviation":
            bad3["没有西里尔"] += 1
        elif criteria._TGT_MARKUP.search(t):
            bad3["标记残渣"] += 1
        elif criteria._TGT_NUM_PREFIX.match(t):
            bad3["数字前缀"] += 1
    out.append(("R3", not bad3, "目标形状问题 %s" % dict(bad3)))

    # R4 target_id 两个方向：有值 ⇒ 那个词形就是目标；为空 ⇒ dict 里真没有它
    words = {}
    for w, i in con.execute("SELECT word, id FROM dict ORDER BY id"):
        words.setdefault(w, i)
    idw = {i: w for w, i in words.items()}
    wrong = miss = 0
    for r in rows:
        want = words.get(r[5])
        if want is None:
            want = words.get(criteria.strip_stress(r[5]))
        if r[6] is None and want is not None:
            miss += 1
        elif r[6] is not None and r[6] != want:
            wrong += 1
    out.append(("R4", wrong == 0 and miss == 0, "target_id 指错 %d／该解析而没解析 %d" % (wrong, miss)))

    # R5 sense_id 只指可出版义项、同词形同 entry
    bad5 = q("SELECT COUNT(*) FROM sense_relation r LEFT JOIN sense s ON s.id=r.sense_id "
             "WHERE r.sense_id IS NOT NULL AND (s.id IS NULL OR s.hidden=1 OR s.word_id<>r.word_id "
             "OR s.entry_id IS NOT r.entry_id)")
    out.append(("R5", bad5 == 0, "挂在不存在/被藏/别的词的义项上 %d 行" % bad5))

    # R6 entry 全有且属于同一个词形
    bad6 = q("SELECT COUNT(*) FROM sense_relation r LEFT JOIN entry n ON n.id=r.entry_id "
             "WHERE n.id IS NULL OR n.word_id<>r.word_id")
    out.append(("R6", bad6 == 0, "entry 缺失或属于别的词形 %d 行" % bad6))

    # R7 去重：可出版行里同 (entry, 义项, kind, 目标) 只有一行；且每条 DUP 都真有一行可出版的同键
    keys = collections.Counter()
    for r in rows:
        if not r[7]:
            keys[(r[2], r[3], r[4], RL.norm_target(r[5]))] += 1
    dup = sum(1 for v in keys.values() if v > 1)
    # 「正本」＝ 同键下**不是因重复而藏**的那一行。🔴 第一版写成「正本必须可出版」，报 650 条假红：
    #    全是 related 被 B17 藏掉之后、它的重复行没有可出版的正本 —— 两行都不印，结果是对的，
    #    是断言把「正本」说窄了（2026-10-24，逐条分堆核过：650/650 正本的 why 都是 B17）。
    canon = set()
    for (e, s, k, t) in con.execute(
            "SELECT entry_id, sense_id, kind, target FROM sense_relation "
            "WHERE hidden_why IS NOT ? ", (criteria.REL_DUP,)):
        canon.add((e, s, k, RL.norm_target(t)))
    orphan_dup = 0
    for (rid, w, e, s, k, t) in con.execute(
            "SELECT id, word_id, entry_id, sense_id, kind, target FROM sense_relation WHERE hidden_why=?",
            (criteria.REL_DUP,)):
        if (e, s, k, RL.norm_target(t)) not in canon:
            orphan_dup += 1
    out.append(("R7", dup == 0 and orphan_dup == 0, "可出版重复 %d 组／藏成重复却没有正本 %d" % (dup, orphan_dup)))

    # R8 B17 两个方向
    spec = set()
    for r in rows:
        if not r[7] and r[4] in criteria.REL_SUBSUME:
            spec.add((r[1], RL.norm_target(r[5])))
    leak = sum(1 for r in rows if not r[7] and r[4] == "related" and (r[1], RL.norm_target(r[5])) in spec)
    over = 0
    for w, t in con.execute("SELECT word_id, target FROM sense_relation WHERE hidden_why=?",
                            (criteria.REL_REDUNDANT,)):
        if (w, RL.norm_target(t)) not in spec:
            over += 1
    out.append(("R8", leak == 0 and over == 0, "该藏没藏 %d／藏了却没有更具体的那条 %d" % (leak, over)))

    # R9 分组列/subkind 值域，且只出现在对应的 kind 上
    bad9 = collections.Counter()
    for k, rg, fg, sk in con.execute("SELECT kind, rel_group, form_group, subkind FROM sense_relation "
                                     "WHERE rel_group IS NOT NULL OR form_group IS NOT NULL OR subkind IS NOT NULL"):
        if (rg or fg) and k != "word_family":
            bad9["分组出现在非词族行"] += 1
        if sk and k != "aspect_pair":
            bad9["subkind 出现在非体对行"] += 1
        if rg and rg not in REL_GROUP_DOMAIN:
            bad9["rel_group 值域外:%s" % rg] += 1
        if fg:
            parts = fg.split("+")
            if any(p not in criteria.FAMILY_FORM_KEYS for p in parts) or \
                    parts != sorted(parts, key=criteria.FAMILY_FORM_KEYS.index):
                bad9["form_group 值域外/顺序错:%s" % fg] += 1
        if sk and any(p not in SUBKIND_DOMAIN for p in sk.split("+")):
            bad9["subkind 值域外:%s" % sk] += 1
    out.append(("R9", not bad9, "%s" % dict(list(bad9.items())[:6]) if bad9 else "值域都对"))

    # R10 已知答案
    bad10 = []
    for w, kind, tgt, want in KNOWN:
        hits = con.execute(
            "SELECT r.sense_id, r.rel_group, r.form_group, r.subkind FROM sense_relation r "
            "JOIN dict d ON d.id=r.word_id WHERE d.word=? AND r.kind=? AND r.target=? AND r.hidden=0",
            (w, kind, tgt)).fetchall()
        if want.get("absent"):
            if hits:
                bad10.append("%s→%s 不该有" % (w, tgt))
            continue
        if not hits:
            bad10.append("%s→%s 找不到" % (w, tgt))
            continue
        h = hits[0]
        if "sense_has" in want:
            g = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='ru'", (h[0],)).fetchone() \
                if h[0] else None
            if not g or want["sense_has"] not in g[0]:
                bad10.append("%s→%s 挂的义项不对（%s）" % (w, tgt, g[0][:30] if g else None))
        for col, i in (("rel_group", 1), ("form_group", 2), ("subkind", 3)):
            if col in want and h[i] != want[col]:
                bad10.append("%s→%s %s=%s" % (w, tgt, col, h[i]))
    out.append(("R10", not bad10, " ｜ ".join(bad10) or "%d 个已知答案全对" % len(KNOWN)))

    # R11 每个 kind 的可出版行数不许低于已接受基线（锁数字不锁名字）
    base = _accept().get("kinds")
    cur = kind_counts(con)
    if not base:
        out.append(("R11", False, "没有已接受基线（先 --accept）"))
    else:
        low = {k: (cur.get(k, 0), v) for k, v in base.items() if cur.get(k, 0) < v}
        out.append(("R11", not low, "倒退 %s" % low if low else "%d 种 kind 都不低于基线" % len(base)))

    # R12 src_ref 唯一且形状对
    bad12 = sum(1 for (s,) in con.execute("SELECT src_ref FROM sense_relation") if not _REF.match(s))
    dup12 = n - q("SELECT COUNT(DISTINCT src_ref) FROM sense_relation")
    out.append(("R12", bad12 == 0 and dup12 == 0, "src_ref 形状不对 %d／重复 %d" % (bad12, dup12)))
    return out


def roster_check(rows):
    got = [c for c, _o, _w in rows]
    if sorted(got) != sorted(ROSTER) or len(set(got)) != len(got):
        return ["花名册对不上：多 %s ／ 少 %s" % (sorted(set(got) - set(ROSTER)), sorted(set(ROSTER) - set(got)))]
    return []


def report():
    if not paths.DB.exists():
        print("🔴 库不存在：%s" % paths.DB)
        return 1
    con = _open()
    try:
        rows = checks(con)
    finally:
        con.close()
    print("■ 关系闸（ru 阶段 6b）—— 花名册 %d 条" % len(ROSTER))
    for cid, ok, why in rows:
        print("   %s %-4s %s" % ("✅" if ok else "🔴", cid, why))
    rb = roster_check(rows)
    for b in rb:
        print("   🔴🔴 花名册自检：" + b)
    red = [r for r in rows if not r[1]]
    print("■ %s（%d/%d）" % ("全绿 ✓" if not red and not rb else "有红", len(rows) - len(red), len(rows)))
    return len(red) + len(rb)


def accept():
    con = _open()
    try:
        cur = kind_counts(con)
    finally:
        con.close()
    ACCEPT.write_text(json.dumps({"kinds": cur}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 已接受基线：%s" % cur)
    return 0


def _mutations():
    """(编号, 说明, 允许的连带红, SQL)。合成行一律负 id、`«变异»` 前缀（B20）。"""
    return [
        ("R1", "把一批 en 版 related 改成 word_family（词族来源错）",
         {"R11", "R8"},   # related 计数倒退；新冒出来的词族会吞掉别的 related（B17 该藏没藏）
         ["UPDATE sense_relation SET kind='word_family' WHERE id IN (SELECT id FROM sense_relation "
          "WHERE src='en-edition' AND kind='related' AND hidden=0 LIMIT 30)"]),
        ("R2", "藏一行却不写为什么", {"R11"},   # 那个 kind 的可出版数少了 1
         ["UPDATE sense_relation SET hidden=1 WHERE id=(SELECT MIN(id) FROM sense_relation WHERE hidden=0)"]),
        ("R3", "目标塞进数字前缀（en 数词框没剥）", {"R4", "R10"},
         ["UPDATE sense_relation SET target='100: '||target WHERE id IN (SELECT id FROM sense_relation "
          "WHERE kind='coordinate' AND src='en-edition' LIMIT 40)"]),
        ("R4", "把一批 target_id 清空（该解析的没解析）", set(),
         ["UPDATE sense_relation SET target_id=NULL WHERE id IN (SELECT id FROM sense_relation "
          "WHERE target_id IS NOT NULL LIMIT 100)"]),
        ("R5", "把一批关系挂到被藏的义项上", set(),
         ["UPDATE sense_relation SET sense_id=(SELECT MIN(id) FROM sense WHERE hidden=1) WHERE id IN "
          "(SELECT id FROM sense_relation WHERE sense_id IS NOT NULL LIMIT 50)"]),
        ("R6", "entry_id 挪到下一个（张冠李戴）",
         {"R7"},   # 挪过去的行与那个 entry 原有的同目标撞成重复／重复行找不到正本
         ["UPDATE sense_relation SET entry_id=entry_id+1 WHERE id%997=0 AND sense_id IS NULL"]),
        ("R7", "把重复行放出来",
         {"R8"},   # 放出来的里面有 related，它的正本被 B17 藏了 ⇒ 该藏没藏
         ["UPDATE sense_relation SET hidden=0, hidden_why=NULL WHERE hidden_why='%s'" % criteria.REL_DUP]),
        ("R8", "B17 整个关掉（该藏的 related 全放出来）", set(),
         ["UPDATE sense_relation SET hidden=0, hidden_why=NULL WHERE hidden_why='%s'" % criteria.REL_REDUNDANT]),
        ("R9", "词族分组写成源头原文（一列两套值域）", set(),
         ["UPDATE sense_relation SET rel_group='существительные' WHERE rel_group='noun' AND id%50=0"]),
        ("R10", "体对把 noun-from-verb 也收进来",
         {"R12", "R4"},   # 合成行的 src_ref 带「«变异»」、target_id 有意留空
         ["INSERT INTO sense_relation(id,word_id,entry_id,sense_id,kind,subkind,rel_group,form_group,target,"
          "target_id,hidden,hidden_why,src,src_ref) SELECT -1,r.word_id,r.entry_id,NULL,'aspect_pair',NULL,NULL,"
          "NULL,'принуди́ловка',NULL,0,NULL,'en-edition',r.src_ref||'«变异»' FROM sense_relation r JOIN dict d "
          "ON d.id=r.word_id WHERE d.word='принудить' AND r.kind='aspect_pair' LIMIT 1"]),
        ("R11", "删掉 pl 版全部关系（少收一版）",
         {"R1", "R8"},   # 缺一版（R1）；pl 的具体关系没了 ⇒ 被它吞掉的 related 失去对应（R8 的「藏了却没有」）
         ["DELETE FROM sense_relation WHERE src='pl-edition'"]),
        ("R12", "造一行 src_ref 形状不对的关系（藏成重复，免得别的条红）", set(),
         ["INSERT INTO sense_relation(id,word_id,entry_id,sense_id,kind,subkind,rel_group,form_group,target,"
          "target_id,hidden,hidden_why,src,src_ref) SELECT -2,word_id,entry_id,sense_id,kind,subkind,rel_group,"
          "form_group,target,target_id,1,'%s',src,'«变异»'||src_ref FROM sense_relation WHERE hidden=0 "
          "AND kind='synonym' LIMIT 1" % criteria.REL_DUP]),
    ]


def mutate():
    if report():
        print("\n🔴 基线就不绿，先修基线")
        return 1
    muts = _mutations()
    print("\n■ 变异验证（%d 条，跑在库的副本上）" % len(muts))
    real = paths.DB
    fails = []
    for cid, why, also, sqls in muts:
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / real.name
            shutil.copy2(real, cp)
            paths.DB = cp
            try:
                con = sqlite3.connect(cp)
                for s in sqls:
                    con.execute(s)
                con.commit()
                con.close()
                con = _open()
                try:
                    got = {c for c, ok, _ in checks(con) if not ok}
                finally:
                    con.close()
                undecl = sorted(got - {cid} - set(also))
                if cid in got and not undecl:
                    print("   ✅ %-4s %s%s" % (cid, why, "（连带红 %s，已逐条声明）" % sorted(got - {cid})
                                             if got - {cid} else ""))
                elif cid in got:
                    print("   🔴 %-4s 逮到了，**但有没声明的连带红 %s** —— %s" % (cid, undecl, why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-4s **没逮到**（红的是 %s）—— %s" % (cid, sorted(got), why))
                    fails.append(cid)
            finally:
                paths.DB = real
    if report():
        print("\n🔴🔴 反控制失败：真库基线不绿了")
        return 1
    print("\n%s" % ("■ 变异验证全过 ✓，反控制：真库基线仍全绿" if not fails
                    else "🔴 %d 条没过：%s" % (len(fails), fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--accept", action="store_true")
    a = ap.parse_args()
    if a.accept:
        return accept()
    return mutate() if a.mutate else (1 if report() else 0)


if __name__ == "__main__":
    raise SystemExit(main())
