#!/usr/bin/env python3
"""**例句闸** —— 阶段 6a 的不变量。ru，2026-10-23。

    python3 ru/tests/test_example.py
    python3 ru/tests/test_example.py --mutate     # 变异验证：闸的闸
    python3 ru/tests/test_example.py --accept     # 把覆盖率现状锁成基线

═══ 这一层最容易出的错 ═══
① **印出去的不是例句**（X3/X4）：收它的判据就是查它的判据 —— 闸调 `criteria.example_text_pub`
   ／`example_hidden_why` 逐行复核（33 万行不抽样）。🔴 而「判据本身写坏」时两边一致报绿
   （vi 的 S6）⇒ **X10 钉已知答案**（常量，不锚现状 —— B20）。
② **例句挂错义项**（X5/X6）：义项、entry、词形三者必须是同一个词的；
   `sense_id` 只许指向**可出版**的义项（藏的义项不渲染 ⇒ 例句跟着消失，vi 的 W25）。
③ **译文的语种按版定**（X7）：fr/vi/pl 的译文是第四语言，一条都不许进 `example_gloss`；
   zh 要有汉字、en 要有拉丁字母且不是占位串。
④ **借来的中文必须真的有出处**（X9）：`<版>:同句` 的译文，同词形下必须有一条一字不差的、
   带那条中文的可出版例句。
⑤ **读者口径的重复**（X8）：同一格（词形×义项，或词形×entry 的「例句」区）里不许印两条同一句。
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
from pipeline import example_layer as XL                        # noqa: E402

ROSTER = ("X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8", "X9", "X10", "X11", "X12", "X13")
ACCEPT = HERE / ".example_accept.json"
SRC_DOMAIN = frozenset({"en-edition", "ru-edition", "zh-edition-simp", "zh-edition-trad",
                        "fr-edition", "vi-edition", "pl-edition"})
HARVEST_WHY = frozenset({XL.DUP, XL.ZH_SPLIT_FAIL})     # 不由 example_hidden_why 产出的两种
_REF = re.compile(r"^kk-[a-z-]+:.+#s\d+#[xp]\d+$")

# X10 已知答案（全部取自 dump 原文，2026-10-23 逐条核过）：
#   (词形, 源, text 前缀, 期望 text_pub（None＝与 text 相同）, 期望 hidden_why, 期望 zh 译文 or None)
KNOWN = (
    ("беречь", "fr-edition", "беречь деньги : conserver", "беречь деньги", None, None),
    ("каркать", "zh-edition-simp", "Воро́на ～ает", None, None, "乌鸦哇哇叫。"),
    ("на-", "en-edition", "на- (na-) + идти́", None, "构词示意式（词缀页，不是句子）", None),
    ("шильбовый", "ru-edition", "... редкая рыба — гигантский", None, None, None),
    ("недобрать", "ru-edition", "◆ Отсутствует пример",
     "Отсутствует пример употребления (см. рекомендации).", "占位串（源头写着「缺例句」）", None),
)
COV_FLOOR = {"pub": 320000}      # 可出版例句不许少于这个数（2026-10-23 落库 329,970）


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def _accept():
    try:
        return json.loads(ACCEPT.read_text("utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def coverage(con):
    pub = con.execute("SELECT COUNT(*) FROM example WHERE hidden=0").fetchone()[0]
    zh = con.execute("SELECT COUNT(DISTINCT g.example_id) FROM example_gloss g JOIN example e "
                     "ON e.id=g.example_id WHERE e.hidden=0 AND g.lang='zh'").fetchone()[0]
    lem = con.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    lem_ex = con.execute("SELECT COUNT(DISTINCT e.word_id) FROM example e JOIN dict d ON d.id=e.word_id "
                         "WHERE e.hidden=0 AND d.is_lemma=1").fetchone()[0]
    return dict(pub=pub, zh=zh, zh_pct=100.0 * zh / max(pub, 1),
                lemma_pct=100.0 * lem_ex / max(lem, 1))


def checks(con):
    out = []
    acc = _accept()
    q = lambda s, *a: con.execute(s, a).fetchone()[0]                  # noqa: E731
    rows = con.execute("SELECT e.id, e.word_id, e.entry_id, e.sense_id, e.text, e.text_pub, e.hidden, "
                       "e.hidden_why, e.src, e.src_ref, d.word, e.ref FROM example e "
                       "JOIN dict d ON d.id=e.word_id").fetchall()
    n = q("SELECT COUNT(*) FROM example")

    # X1 七份源每一份都有行落进来（只查「表非空」的话少收六版也全绿，vi 的 X12）；每行都挂得上 dict
    by = collections.Counter(r[8] for r in rows)
    miss = sorted(SRC_DOMAIN - set(by))
    out.append(("X1", n > 0 and not miss and len(rows) == n and set(by) <= SRC_DOMAIN,
                "%s 行／%d 版／缺 %s／挂不上 dict %d／值域外 %s" % (
                    format(n, ","), len(by), miss, n - len(rows), sorted(set(by) - SRC_DOMAIN))))

    # X2 hidden ⟺ hidden_why 非空
    bad = q("SELECT COUNT(*) FROM example WHERE (hidden=1) <> (hidden_why IS NOT NULL AND "
            "TRIM(hidden_why)<>'')")
    out.append(("X2", bad == 0, "hidden 与 hidden_why 不一致 %d 行" % bad))

    # X3 出版正文 ＝ 收它的那个函数重算（zh-s 重切对 text_pub 必须为空）
    bad3, eg3 = 0, []
    for r in rows:
        if "#p" in r[9]:
            ok = r[5] is None
        elif r[7] == XL.ZH_SPLIT_FAIL:
            ok = r[5] is None
        else:
            # R24：首行出处搬进 ref ⇒ 正文是切过的，而且出处**必须真的落在 ref 里**（不是丢了）
            want, head = criteria.example_split_citation(r[8], criteria.example_text_pub(r[8], r[4]))
            ok = (r[5] or r[4]) == want and (r[5] is None or r[5] != r[4]) and \
                (head is None or head in (r[11] or ""))
        if not ok:
            bad3 += 1
            if len(eg3) < 3:
                eg3.append("%s：%s" % (r[10], (r[5] or r[4])[:40]))
    out.append(("X3", bad3 == 0, "出版正文与判据不一致 %d 行 %s" % (bad3, " ｜ ".join(eg3))))

    # X4 藏不藏 ＝ 判据重算（收割器自己加的两种除外）
    bad4, eg4 = 0, []
    for r in rows:
        if r[7] in HARVEST_WHY:
            continue
        want = criteria.example_hidden_why(r[8], r[10], r[5] or r[4])
        if want != r[7]:
            bad4 += 1
            if len(eg4) < 3:
                eg4.append("%s：%s ≠ %s" % (r[10], r[7], want))
    out.append(("X4", bad4 == 0, "藏不藏与判据不一致 %d 行 %s" % (bad4, " ｜ ".join(eg4))))

    # X5 sense_id 只指向可出版义项，且义项与例句是同一个词形、同一个 entry
    bad5 = q("SELECT COUNT(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id "
             "WHERE e.sense_id IS NOT NULL AND (s.id IS NULL OR s.hidden=1 OR s.word_id<>e.word_id "
             "OR s.entry_id IS NOT e.entry_id)")
    out.append(("X5", bad5 == 0, "例句挂在不存在/被藏/别的词的义项上 %d 行" % bad5))

    # X6 entry_id 全有、且属于同一个词形
    bad6 = q("SELECT COUNT(*) FROM example e LEFT JOIN entry n ON n.id=e.entry_id "
             "WHERE n.id IS NULL OR n.word_id<>e.word_id")
    out.append(("X6", bad6 == 0, "entry 缺失或属于别的词形 %d 行" % bad6))

    # X7 译文：语种按版定；只挂在可出版例句上；形状
    g = con.execute("SELECT g.example_id, g.lang, g.text, g.src, e.src, e.hidden FROM example_gloss g "
                    "LEFT JOIN example e ON e.id=g.example_id").fetchall()
    bad7 = collections.Counter()
    for eid, lang, text, gsrc, esrc, hid in g:
        if esrc is None:
            bad7["孤儿译文"] += 1
        elif hid:
            bad7["挂在被藏的例句上"] += 1
        elif lang not in ("zh", "en"):
            bad7["语种不在 zh/en"] += 1
        elif gsrc.startswith("model:"):
            pass
        elif gsrc.endswith(":同句"):
            if lang != "zh":
                bad7["借用的不是中文"] += 1
        elif gsrc != esrc or criteria.EX_TR_LANG.get(esrc) != lang:
            bad7["语种与版不符（%s→%s）" % (gsrc, lang)] += 1
        if lang == "zh" and not re.search(r"[㐀-鿿]", text or ""):
            bad7["zh 译文没有汉字"] += 1
        if lang == "en" and (not re.search(r"[A-Za-z]", text or "") or criteria._EN_PLACEHOLDER.search(text)):
            bad7["en 译文不像英文/是占位串"] += 1
    dupg = q("SELECT COUNT(*) FROM (SELECT 1 FROM example_gloss GROUP BY example_id, lang HAVING COUNT(*)>1)")
    if dupg:
        bad7["同一例句同一语种两条"] = dupg
    out.append(("X7", not bad7, "译文 %s 条；问题 %s" % (format(len(g), ","), dict(bad7))))

    # X8 读者口径：同一格里不印两条同一句
    cell = collections.Counter()
    for r in rows:
        if not r[6]:
            cell[(r[1], r[3] if r[3] is not None else -r[2], XL.dup_key(r[5] or r[4]))] += 1
    dup8 = sum(1 for v in cell.values() if v > 1)
    out.append(("X8", dup8 == 0, "同一格里重复的可出版例句 %d 组" % dup8))

    # X9 借来的中文必须有出处：同词形、同正文键、可出版、带同一条中文、来自前缀那一版
    have = collections.defaultdict(set)
    rid = {r[0]: r for r in rows}
    for eid, lang, text, gsrc, esrc, hid in g:
        if lang == "zh" and gsrc == esrc and not hid:
            r = rid[eid]
            have[(r[1], XL.dup_key(r[5] or r[4]))].add((text, gsrc))
    bad9 = 0
    nb = 0
    for eid, lang, text, gsrc, esrc, hid in g:
        if not gsrc.endswith(":同句"):
            continue
        nb += 1
        r = rid.get(eid)
        if r is None or (text, gsrc[:-3]) not in have.get((r[1], XL.dup_key(r[5] or r[4])), ()):
            bad9 += 1
    out.append(("X9", bad9 == 0, "借用的中文 %s 条，找不到出处 %d" % (format(nb, ","), bad9)))

    # X10 已知答案（常量）
    bad10 = []
    for w, src, pre, want_pub, want_why, want_zh in KNOWN:
        hit = con.execute(
            "SELECT e.id, e.text_pub, e.hidden_why FROM example e JOIN dict d ON d.id=e.word_id "
            "WHERE d.word=? AND e.src=? AND substr(e.text,1,?)=? ORDER BY e.id LIMIT 1",
            (w, src, len(pre), pre)).fetchone()
        if not hit:
            bad10.append("%s 找不到" % w)
            continue
        # 「期望 zh」指**源头给的**中文（含同句借用），不含 6d 的模型译文。
        # 🔴 B20：第一版没分 src，6d 落库后 `беречь`/`шильбовый` 「多了」模型中文而判红 —— 前提随现状推进过期了
        zh = con.execute("SELECT text FROM example_gloss WHERE example_id=? AND lang='zh' "
                         "AND src NOT LIKE 'model:%'", (hit[0],)).fetchone()
        got = (hit[1], hit[2], zh[0] if zh else None)
        if got != (want_pub, want_why, want_zh):
            bad10.append("%s：%s" % (w, got))
    out.append(("X10", not bad10, " ｜ ".join(bad10) or "%d 个已知答案全对" % len(KNOWN)))

    # X11 覆盖率：不许低于已接受基线，可出版例句不许低于下限
    cov = coverage(con)
    base = acc.get("coverage", {})
    bad11 = []
    if cov["pub"] < COV_FLOOR["pub"]:
        bad11.append("可出版 %d < 下限 %d" % (cov["pub"], COV_FLOOR["pub"]))
    for k in ("zh_pct", "lemma_pct"):
        if k not in base:
            bad11.append("没有已接受基线（先 --accept）")
            break
        if round(cov[k], 2) < base[k]:          # 基线存两位小数 ⇒ 同精度比（第一版拿全精度比自己判红）
            bad11.append("%s %.2f%% < 基线 %.2f%%" % (k, cov[k], base[k]))
    out.append(("X11", not bad11, " ｜ ".join(bad11) or "可出版 %s／有中文 %.2f%%／词元有例句 %.2f%%" % (
        format(cov["pub"], ","), cov["zh_pct"], cov["lemma_pct"])))

    # X12 src_ref 唯一且形状对（`<entry.src_ref>#s<si>#x<xi>` 或 zh-s 重切的 `#p<k>`）
    bad12 = sum(1 for r in rows if not _REF.match(r[9]) or ("#p" in r[9]) != (r[8] == "zh-edition-simp"
                                                                             and "#p" in r[9]))
    dup12 = n - q("SELECT COUNT(DISTINCT src_ref) FROM example")
    out.append(("X12", bad12 == 0 and dup12 == 0, "src_ref 形状不对 %d／重复 %d" % (bad12, dup12)))

    # X13 R29：中文译文的出版正文（简体）逐行 ＝ 判据；6d 模型译文 `text` 是模型原话（不是整段 t2s 过的）
    #   后一半问 `zh_pub.plan_model_text` 本身（同步脚本与闸同一个判据），它要改的行数必须是 0
    from pipeline import zh_pub
    bad13 = collections.Counter()
    for text, src, pub, lang in con.execute("SELECT text, src, text_pub, lang FROM example_gloss "
                                            "WHERE lang='zh' OR text_pub IS NOT NULL"):
        if lang != "zh":
            bad13["非 zh 行有 text_pub"] += 1
            continue
        z = criteria.zh_simp(text, src)
        if pub != (z if z != text else None):
            bad13["text_pub 与判据不一致"] += 1
    up, st = zh_pub.plan_model_text(con)
    if up:
        bad13["模型译文仍是整段 t2s 的产物"] = len(up)
    for k, v in st.items():
        if k.startswith("🔴"):
            bad13[k] = v
    out.append(("X13", not bad13, str(dict(bad13)) if bad13 else "简体出版正文 %s 条" % format(
        q("SELECT COUNT(*) FROM example_gloss WHERE text_pub IS NOT NULL"), ",")))
    return out


def roster_check(rows):
    got = [c for c, _o, _w in rows]
    bad = []
    if sorted(got) != sorted(ROSTER) or len(set(got)) != len(got):
        bad.append("花名册对不上：多 %s ／ 少 %s" % (sorted(set(got) - set(ROSTER)),
                                               sorted(set(ROSTER) - set(got))))
    return bad


def report():
    if not paths.DB.exists():
        print("🔴 库不存在：%s" % paths.DB)
        return 1
    con = _open()
    try:
        rows = checks(con)
    finally:
        con.close()
    print("■ 例句闸（ru 阶段 6a）—— 花名册 %d 条" % len(ROSTER))
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
    ACCEPT.write_text(json.dumps({"coverage": {k: round(v, 2) if isinstance(v, float) else v
                                               for k, v in cov.items()}},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 已接受基线：可出版 %s／有中文 %.2f%%／词元有例句 %.2f%%" % (
        format(cov["pub"], ","), cov["zh_pct"], cov["lemma_pct"]))
    return 0


def _mutations():
    """(编号, 说明, 允许的连带红, SQL[, 判据补丁])。合成行一律负 id（B20）。
    🔴 连带红**先跑一遍看实际、逐条确认为什么该红、再写进来**。"""
    return [
        ("X1", "删掉 pl 版全部例句（少收一版）",
         {"X11"},   # 有些词元只有 pl 版给了例句 ⇒ 「词元有例句」倒退
         ["DELETE FROM example_gloss WHERE example_id IN (SELECT id FROM example WHERE src='pl-edition')",
                 "DELETE FROM example WHERE src='pl-edition'"]),
        ("X2", "藏一行却不写为什么", set(),
         ["UPDATE example SET hidden=1 WHERE id=(SELECT MIN(id) FROM example WHERE hidden=0 AND id NOT IN "
          "(SELECT example_id FROM example_gloss))"]),
        ("X3", "把 fr 版的法语尾巴放回出版正文",
         # X10：`беречь` 是已知答案之一；X4：藏不藏是在出版正文上判的，正文变了结论跟着变
         # （`Согласен! : …` 不再「整条就是词头」）；X9：借中文的键是出版正文，键变了出处就找不到
         {"X10", "X4", "X9"},
         ["UPDATE example SET text_pub=NULL WHERE src='fr-edition' AND text_pub IS NOT NULL"]),
        ("X3", "R24：搬进 ref 的首行出处丢了（ref 清空）", set(),
         ["UPDATE example SET ref=NULL WHERE id=(SELECT MIN(id) FROM example WHERE src='en-edition' AND ref LIKE '1848, %' "
          "AND text LIKE '1848, %')"]),
        ("X4", "把「构词示意式」放出来印",
         # X10：`на-` 是已知答案之一；X8：词缀页上同一个示意式重复出现（藏的时候不参与去重）；
         # X11：可出版变多而中文没变 ⇒ 中文**比例**倒退（比例是有意的口径，见 coverage）
         {"X10", "X8", "X11"},
         ["UPDATE example SET hidden=0, hidden_why=NULL WHERE hidden_why='构词示意式（词缀页，不是句子）' "
          "AND id NOT IN (SELECT id FROM example e2 WHERE 0)"]),
        ("X5", "把一批例句挂到被藏的义项上", set(),
         ["UPDATE example SET sense_id=(SELECT MIN(id) FROM sense WHERE hidden=1) "
          "WHERE id IN (SELECT id FROM example WHERE sense_id IS NOT NULL LIMIT 50)"]),
        ("X6", "把 entry_id 挪到下一个 entry（张冠李戴）",
         {"X5"},   # 义项的 entry 不再等于例句的 entry
         ["UPDATE example SET entry_id=entry_id+1 WHERE id%97=0"]),
        ("X7", "把 vi 版的越南语译文收进来当中文", set(),
         ["INSERT INTO example_gloss(id,example_id,lang,text,src) SELECT -id,id,'zh','«变异»hàng hóa',"
          "'vi-edition' FROM example WHERE src='vi-edition' AND hidden=0 AND id NOT IN "
          "(SELECT example_id FROM example_gloss) LIMIT 20"]),
        ("X8", "把同一格里藏起来的重复行放出来",
         {"X11"},   # 同 X4：分母变大、中文比例倒退
         ["UPDATE example SET hidden=0, hidden_why=NULL WHERE hidden_why='%s'" % XL.DUP]),
        ("X9", "把一条借来的中文改成别的话", set(),
         ["UPDATE example_gloss SET text='«变异»借错了' WHERE id=(SELECT MIN(id) FROM example_gloss "
          "WHERE src LIKE '%:同句')"]),
        ("X10", "判据坏掉：`example_text_pub` 不再切 fr 尾巴（库与判据一起坏）",
         {"X3"},   # 库里那行与坏判据仍不一致的其余 fr 行 —— 只改了 KNOWN 那一行的库值，判据补丁让其余行也红
         ["UPDATE example SET text_pub=NULL WHERE src='fr-edition' AND text LIKE 'беречь деньги : %'"],
         lambda orig: (lambda src, text: text.strip() if src == "fr-edition" else orig(src, text))),
        ("X11", "藏掉一半中文例句（覆盖率倒退）",
         {"X2", "X7", "X9"},   # 只改 hidden 不写 why（X2）、译文挂在被藏例句上（X7）、借用的出处消失（X9）
         ["UPDATE example SET hidden=1 WHERE id IN (SELECT example_id FROM example_gloss WHERE lang='zh') "
          "AND id%2=0"]),
        ("X13", "R29：一条模型译文退回整段 t2s 的产物（`覆上→复上`）", set(),
         ["UPDATE example_gloss SET text=replace(text,'覆上','复上') WHERE id=(SELECT MIN(id) FROM example_gloss "
          "WHERE src='model:deepseek-v4-flash' AND text LIKE '%覆上%')"]),
        ("X12", "造一行 src_ref 形状不对的例句", set(),
         ["INSERT INTO example(id,word_id,entry_id,sense_id,text,text_pub,ref,hidden,hidden_why,src,src_ref) "
          # 合成行标成「同一格里重复」藏起来 ⇒ 只有 X12 该红（不藏的话 X8 也红，那是另一件事）
          "SELECT -1,word_id,entry_id,sense_id,text,text_pub,ref,1,'%s',src,'«变异»'||src_ref "
          "FROM example WHERE hidden=0 AND src='ru-edition' LIMIT 1" % XL.DUP]),
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
            orig = criteria.example_text_pub
            try:
                con = sqlite3.connect(cp)
                for s in sqls:
                    con.execute(s)
                con.commit()
                con.close()
                if patch:
                    criteria.example_text_pub = patch(orig)
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
                criteria.example_text_pub = orig
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
