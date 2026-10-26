#!/usr/bin/env python3
"""**词源闸** —— 阶段 7 的不变量。ru，2026-10-24。

    python3 ru/tests/test_etymology.py
    python3 ru/tests/test_etymology.py --mutate
    python3 ru/tests/test_etymology.py --accept

═══ 这一层最容易出的错 ═══
① **把占位印成词源**（Y3/Y7）：ru 版 29.6 万段是 `От ??`；收它的函数逐行复核 ＋ 出版正文里一个占位/挂件残渣都不许有
   （两条独立：Y3 对判据、Y7 对读者看见什么 —— 判据写坏时 Y3 与它一致，Y7 不一致）。
② **三语方针**（Y6）：fr/vi/pl 进证据层、一条都不许出版。
③ **挂错 entry**（Y5）：词源号必须与那条 entry 的一致。
④ 判据写坏两边一致 ⇒ **Y9 钉已知答案**（常量，B20）。
⑤ **「源头没给」不许冒充覆盖**（Y10）：读者口径只数可出版段。
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

ROSTER = ("Y1", "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9", "Y10", "Y11", "Y12")
ACCEPT = HERE / ".etymology_accept.json"
SRC_DOMAIN = frozenset({"en-edition", "ru-edition", "zh-edition-simp", "zh-edition-trad",
                        "fr-edition", "vi-edition", "pl-edition"})
_REF = re.compile(r"^kk-[a-z-]+:.+#etym\d+$")
# Y7：读者在出版正文里**绝不该看见**的东西（与判据独立写 —— 它对的是「看见什么」，不是「判据怎么判」）
_RESIDUE = re.compile(r"\?\?|^(?:Происходит от|От|Из)\s*$|Etymology tree|詞源樹|词源树|\{\{\{|__[A-Z]+__|\[\[|\]\]"
                      r"|^PIE word$|Статья нуждается в доработке", re.M)
# Y9 已知答案（取自 dump，2026-10-24 核过）：(词形, 源, 期望：出版正文前缀 or None=该源不许有可出版段, 期望 hidden_why)
KNOWN = (
    ("мурыжить", "ru-edition", "Стены древних городов", None),     # 首行 `Происходит от ??` 剥掉、后面的真内容留下
    ("в", "en-edition", "Inherited from Old East Slavic въ", None),  # PIE word ＋ 词源树挂件剥掉
    # 整段 `От ??` ⇒ 源头没给、不落库。🔴 第一版写的是 `переводить` —— 它另一个 entry 有真词源，
    #    探针里看到的 `От ??` 是另一条（已知答案要先回 dump 逐 entry 核，2026-10-24）
    ("тараса", "ru-edition", None, None),
    ("конь", "zh-edition-trad", "继承自古东斯拉夫语 конь", None),      # zh 的词源树；R29 起出版正文是简体（dump 原文繁体）
    ("звон", "ru-edition", None, None),                             # 只为确认：不该冒出 `далее от ??` 尾巴（见 Y7）
)


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def _accept():
    try:
        return json.loads(ACCEPT.read_text("utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def coverage(con):
    lem = con.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    got = con.execute("SELECT COUNT(DISTINCT y.word_id) FROM etymology y JOIN dict d ON d.id=y.word_id "
                      "WHERE y.hidden=0 AND d.is_lemma=1").fetchone()[0]
    zh = con.execute("SELECT COUNT(DISTINCT y.word_id) FROM etymology y JOIN dict d ON d.id=y.word_id "
                     "WHERE y.hidden=0 AND d.is_lemma=1 AND y.src LIKE 'zh-%'").fetchone()[0]
    return dict(lemma_pct=round(100.0 * got / max(lem, 1), 2), zh_pct=round(100.0 * zh / max(lem, 1), 2))


def checks(con):
    out = []
    q = lambda s, *a: con.execute(s, a).fetchone()[0]                  # noqa: E731
    n = q("SELECT COUNT(*) FROM etymology")
    rows = con.execute("SELECT y.id, y.word_id, y.entry_id, y.etym_no, y.etym_sub, y.text, y.text_pub, y.src_field, "
                       "y.etym_type, y.hidden, y.hidden_why, y.src, y.src_ref, d.word FROM etymology y "
                       "LEFT JOIN dict d ON d.id=y.word_id").fetchall()
    srcs = collections.Counter(r[11] for r in rows)
    out.append(("Y1", n > 0 and set(srcs) == SRC_DOMAIN and all(r[13] for r in rows),
                "%s 段／%d 版／缺 %s／挂不上 dict %d" % (format(n, ","), len(srcs), sorted(SRC_DOMAIN - set(srcs)),
                                                    sum(1 for r in rows if not r[13]))))
    bad2 = q("SELECT COUNT(*) FROM etymology WHERE (hidden=1) <> (hidden_why IS NOT NULL AND TRIM(hidden_why)<>'')")
    out.append(("Y2", bad2 == 0, "hidden 与 hidden_why 不一致 %d" % bad2))
    bad3, eg3 = 0, []
    for r in rows:
        want = criteria.etymology_text_pub(r[5], r[11])
        got = r[6] if r[6] is not None else r[5]
        if not want or got != want or (r[6] is not None and r[6] == r[5]):
            bad3 += 1
            if len(eg3) < 3:
                eg3.append("%s：%s" % (r[13], got[:30]))
    out.append(("Y3", bad3 == 0, "出版正文与判据不一致（或为空）%d 段 %s" % (bad3, " ｜ ".join(eg3))))
    bad4 = sum(1 for r in rows if criteria.etymology_hidden_why(r[11], r[13], r[6] if r[6] is not None else r[5])
               != r[10])
    out.append(("Y4", bad4 == 0, "藏不藏与判据不一致 %d 段" % bad4))
    bad5 = q("SELECT COUNT(*) FROM etymology y LEFT JOIN entry n ON n.id=y.entry_id WHERE n.id IS NULL "
             "OR n.word_id<>y.word_id OR n.etym_no<>y.etym_no OR n.etym_sub<>y.etym_sub OR n.src<>y.src")
    out.append(("Y5", bad5 == 0, "entry 缺失／属于别的词形／词源号或版对不上 %d 段" % bad5))
    pub_bad = q("SELECT COUNT(*) FROM etymology WHERE hidden=0 AND src NOT IN ('en-edition','ru-edition',"
                "'zh-edition-simp','zh-edition-trad')")
    out.append(("Y6", pub_bad == 0, "fr/vi/pl 出版了 %d 段（三语方针）" % pub_bad))
    bad7, eg7 = 0, []
    for r in rows:
        if r[9]:
            continue
        t = r[6] if r[6] is not None else r[5]
        if _RESIDUE.search(t):
            bad7 += 1
            if len(eg7) < 3:
                eg7.append("%s：%s" % (r[13], t[:40].replace("\n", "⏎")))
    out.append(("Y7", bad7 == 0, "出版正文里有占位/挂件/标记残渣 %d 段 %s" % (bad7, " ｜ ".join(eg7))))
    et = {r[0] for r in con.execute("SELECT DISTINCT etym_type FROM etymology WHERE etym_type IS NOT NULL")}
    et_src = q("SELECT COUNT(*) FROM etymology WHERE etym_type IS NOT NULL AND src<>'en-edition'")
    out.append(("Y8", et <= criteria.ETYM_TYPE_DOMAIN and et_src == 0,
                "etym_type 值域外 %s／非 en 版有值 %d" % (sorted(et - criteria.ETYM_TYPE_DOMAIN), et_src)))
    bad9 = []
    for w, src, pre, why in KNOWN:
        hits = con.execute("SELECT COALESCE(y.text_pub, y.text), y.hidden_why FROM etymology y JOIN dict d "
                           "ON d.id=y.word_id WHERE d.word=? AND y.src=? AND y.hidden=0", (w, src)).fetchall()
        if pre is None:
            if w == "тараса" and hits:
                bad9.append("%s 不该有可出版段" % w)
            continue
        if not any(h[0].startswith(pre) for h in hits):
            bad9.append("%s：%s" % (w, [h[0][:25] for h in hits][:2]))
    out.append(("Y9", not bad9, " ｜ ".join(bad9) or "%d 个已知答案全对" % len(KNOWN)))
    base = _accept().get("coverage")
    cov = coverage(con)
    if not base:
        out.append(("Y10", False, "没有已接受基线（先 --accept）"))
    else:
        low = [k for k in base if cov[k] < base[k]]
        out.append(("Y10", not low, "倒退 %s" % low if low else "词元有词源 %.2f%%／有中文词源 %.2f%%" % (
            cov["lemma_pct"], cov["zh_pct"])))
    bad11 = sum(1 for r in rows if not _REF.match(r[12]))
    dup11 = n - q("SELECT COUNT(DISTINCT src_ref) FROM etymology")
    out.append(("Y11", bad11 == 0 and dup11 == 0, "src_ref 形状不对 %d／重复 %d" % (bad11, dup11)))
    bad12 = sum(1 for r in rows if r[7] not in criteria.ETYM_FIELDS or
                (r[11] == "en-edition") != (r[7] == "etymology_text"))
    out.append(("Y12", bad12 == 0, "src_field 与版对不上 %d（en 单数、其余复数）" % bad12))
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
    print("■ 词源闸（ru 阶段 7）—— 花名册 %d 条" % len(ROSTER))
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
        cov = coverage(con)
    finally:
        con.close()
    ACCEPT.write_text(json.dumps({"coverage": cov}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 已接受基线：%s" % cov)
    return 0


def _mutations():
    return [
        ("Y1", "删掉 vi 版全部词源（少收一版）", set(),
         ["DELETE FROM etymology WHERE src='vi-edition'"]),
        ("Y2", "藏一段却不写为什么", {"Y4", "Y10"},
         ["UPDATE etymology SET hidden=1 WHERE id=(SELECT MIN(id) FROM etymology WHERE hidden=0)"]),
        ("Y3", "把清洗过的段放回 dump 原文（`, далее от ??` 尾巴回来）", {"Y4", "Y7", "Y9"},
         ["UPDATE etymology SET text_pub=NULL WHERE text_pub IS NOT NULL AND src='ru-edition'"]),
        ("Y4", "把指针段放出来印", set(),
         ["UPDATE etymology SET hidden=0, hidden_why=NULL WHERE hidden_why LIKE '指针%'"]),
        ("Y5", "词源挂到下一个 entry 上", set(),
         ["UPDATE etymology SET entry_id=entry_id+1 WHERE id%101=0"]),
        ("Y6", "fr 版词源放出来印", {"Y4"},
         ["UPDATE etymology SET hidden=0, hidden_why=NULL WHERE src='fr-edition'"]),
        ("Y7", "判据坏掉：占位行不再剥（库与判据一起坏）",
         # Y3：坏判据作用于所有含 `??` 的段，库里清洗过的那批与它对不上；Y11：合成行的 src_ref 带「«变异»」
         {"Y9", "Y10", "Y3", "Y11"},
         ["INSERT INTO etymology(id,word_id,entry_id,etym_no,etym_sub,text,text_pub,src_field,etym_type,hidden,"
          "hidden_why,src,src_ref) SELECT -1,word_id,entry_id,etym_no,etym_sub,'Происходит от ??',NULL,src_field,"
          "NULL,0,NULL,src,src_ref||'«变异»' FROM etymology WHERE src='ru-edition' LIMIT 1"],
         lambda orig: (lambda t, src="": (t or "").strip() if "??" in (t or "") else orig(t, src))),
        ("Y8", "en 以外的版也填 etym_type", set(),
         ["UPDATE etymology SET etym_type='borrowed' WHERE src='ru-edition' AND id%50=0"]),
        ("Y9", "`мурыжить` 的首行占位没剥（只坏这一行）",
         {"Y3", "Y7"},   # 占位行回到出版正文 ⇒ 读者看见 `Происходит от ??`
         ["UPDATE etymology SET text_pub=NULL WHERE src='ru-edition' AND word_id=(SELECT id FROM dict "
          "WHERE word='мурыжить') AND text LIKE 'Происходит от ??%'"]),
        ("Y10", "删掉一半 ru 版词源（覆盖率倒退）",
         {"Y9"},   # 删掉的那一半里可能有已知答案的段
         ["DELETE FROM etymology WHERE src='ru-edition' AND id%2=0"]),
        ("Y11", "造一行 src_ref 形状不对的词源（藏起来免得别的条红）", set(),
         ["INSERT INTO etymology(id,word_id,entry_id,etym_no,etym_sub,text,text_pub,src_field,etym_type,hidden,"
          "hidden_why,src,src_ref) SELECT -2,word_id,entry_id,etym_no,etym_sub,text,text_pub,src_field,etym_type,"
          "1,'%s',src,'«变异»' FROM etymology WHERE src='fr-edition' LIMIT 1" % criteria.ETYM_NOT_PUBLISHED]),
        ("Y12", "ru 版的 src_field 写成单数", set(),
         ["UPDATE etymology SET src_field='etymology_text' WHERE src='ru-edition' AND id%97=0"]),
    ]


def mutate():
    if report():
        print("\n🔴 基线就不绿，先修基线")
        return 1
    muts = _mutations()
    print("\n■ 变异验证（%d 条，跑在库的副本上）" % len(muts))
    real = paths.DB
    fails = []
    for m in muts:
        cid, why, also, sqls = m[:4]
        patch = m[4] if len(m) > 4 else None
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / real.name
            shutil.copy2(real, cp)
            paths.DB = cp
            orig = criteria.etymology_text_pub
            try:
                con = sqlite3.connect(cp)
                for s in sqls:
                    con.execute(s)
                con.commit()
                con.close()
                if patch:
                    criteria.etymology_text_pub = patch(orig)
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
                criteria.etymology_text_pub = orig
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
