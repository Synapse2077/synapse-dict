#!/usr/bin/env python3
"""**义项闸** —— 阶段 5a 的不变量。ru，2026-10-23。

    python3 ru/tests/test_sense.py
    python3 ru/tests/test_sense.py --mutate
    python3 ru/tests/test_sense.py --accept

═══ 这一层要守的四件事 ═══
① **归属**（E3）：义项挂的 entry 必须属于同一个词形；证据行与它出版的义项必须同词同条目。
② **出版边界**（E5/E6）：指针只进证据层；fr/vi/pl 只进证据层（三语方针）。
   ⚠️ 这两条是「**有意不出版**」的锁 —— 它们一松，读者会看到「лука́ 的复数属格」被当成释义、
      或者一条法语翻译混在中文释义里。
③ **藏不藏**（E4/E11）：E4 用 `criteria.sense_hidden_why` 从证据原文重算；**它对判据本身写坏是瞎的**
   ⇒ E11 钉已知答案（常量，B20）。
④ **R11 的锁**（E9）：两个数一起核 —— 落下的 ＋ 有意不落的 ＝ 阶段 1 的存档，**库里重数**。
"""
import argparse
import collections
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402

ROSTER = tuple("E%d" % i for i in range(1, 16))
ACCEPT = HERE / ".sense_accept.json"
SRC_DOMAIN = frozenset(criteria.SENSE_LANG)
BUCKETS = frozenset({"grammar", "label", "raw", "topic"})
STATS = paths.WORK / "stage5a_sense_stats.json"
R11_ARCHIVE = paths.WORK / "stage1_grammar_rows.json"

# E11 已知答案（2026-10-23 逐条核过）：(词形, 语言, 文本开头, 期望 hidden_why 或 None)
# R29 `zh_simp` 的已知答案（(原文, src), 应得）—— 每条都是一次实测栽过的
ZH_SIMP_KNOWN = (
    (("头发覆上了一片银白", "model:deepseek-v4-flash"), "头发覆上了一片银白"),   # OpenCC 短语表 覆上→复上
    (("重複，反覆", "zh-edition-trad"), "重复，反复"),                          # 同一个字，这里该转
    (("“乾”的意义", "model:deepseek-v4-flash"), "“乾”的意义"),                  # 简体文本里的乾卦
    (("乳臭未乾", "zh-edition-trad"), "乳臭未干"),                              # 繁体文本里的乾
    (("芸薹属", "model:deepseek-v4-flash"), "芸薹属"),                          # OpenCC 字表错
    (("麻鳽", "model:deepseek-v4-flash"), "麻鳽"),                              # 目标在扩展平面
    (("汉语姓氏 習 /习 (Xí) 的音译", "model:deepseek-v4-flash"), "汉语姓氏 習 /习 (Xí) 的音译"),  # 繁简对举
    (("主帆和後桅帆", "model:deepseek-v4-flash"), "主帆和后桅帆"),              # 简体文本里漏转的後
    (("кни́га (kníga) 的賓格單數", "zh-edition-simp"), "кни́га (kníga) 的宾格单数"),
)
KNOWN = (
    ("голубь", "zh", "鴿子", None),
    ("голубь", "en", "dove, pigeon", None),
    ("бочечка", "zh", "复二-чек", "zh-元描述（zh_gloss_kind=meta）"),
    ("дегтярный", "zh", ",", "没有字母（整串是标点/符号）"),
    ("за", "en", "[with accusative] to", None),          # 父释义拼进来了（sense_text）
    # ru-crit-14：只有领域缩写、源头漏写了释义 ⇒ 藏（不花钱译、不印成「〈体〉」）
    ("прыжок с шестом", "ru", "спорт.", "只有语体/领域标签、没有释义（源头漏写）"),
)
# 指针只进证据层，且目标是结构字段
POINTER = ("лук", "en-edition", "лука́")


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def _accept():
    try:
        return json.loads(ACCEPT.read_text("utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def coverage(con):
    """三个口径：词元有可印义项（任一语言）／有可印中文／**空白页的三种成因**。"""
    q = lambda s: con.execute(s).fetchone()[0]                    # noqa: E731
    lem = q("SELECT COUNT(*) FROM dict WHERE is_lemma=1")
    anyp = q("SELECT COUNT(DISTINCT s.word_id) FROM sense s JOIN dict d ON d.id=s.word_id "
             "WHERE d.is_lemma=1 AND s.hidden=0")
    zh = q("SELECT COUNT(DISTINCT s.word_id) FROM sense s JOIN dict d ON d.id=s.word_id "
           "JOIN sense_gloss g ON g.sense_id=s.id WHERE d.is_lemma=1 AND s.hidden=0 AND g.lang='zh'")
    # 空白页（词元、无可印义项）按证据层分三类 —— 「源头没给」和「我们没出版」要分开
    blank = con.execute(
        "SELECT CASE "
        " WHEN EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id) THEN 'b·有出版义项但全藏' "
        " WHEN EXISTS(SELECT 1 FROM sense_src x WHERE x.word_id=d.id AND x.pointer_target IS NOT NULL) "
        "      THEN 'c·只有指针' "
        " WHEN EXISTS(SELECT 1 FROM sense_src x WHERE x.word_id=d.id) THEN 'd·只有 fr/vi/pl 证据或无目标指针' "
        " ELSE 'e·源头一条义项都没有' END k, COUNT(*) "
        "FROM dict d WHERE d.is_lemma=1 AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id "
        "AND s.hidden=0) GROUP BY k").fetchall()
    return dict(lemmas=lem, any=anyp, zh=zh, any_pct=100.0 * anyp / max(lem, 1),
                zh_pct=100.0 * zh / max(lem, 1), blank=dict(blank))


def checks(con):
    out = []
    acc = _accept()
    q = lambda s, *a: con.execute(s, a).fetchone()[0]             # noqa: E731

    n = q("SELECT COUNT(*) FROM sense")
    out.append(("E1", n > 0, "" if n else "`sense` 是空的"))

    # ── E2 每条出版义项恰好一条**源头** gloss（破例义项恰好 0 条），与证据层同语言 ─────
    # 🔴 5b 之后一条义项可以有两条 gloss：源头原文 ＋ 模型中文（`src=model:…`）。
    #    破例义项（证据是 fr/vi/pl）**不出版原文**（三语方针在原文这一层不破）⇒ 源头 gloss 恰好 0。
    a = q("SELECT COUNT(*) FROM sense s JOIN sense_src x ON x.sense_id=s.id "
          "WHERE (SELECT COUNT(*) FROM sense_gloss g WHERE g.sense_id=s.id AND g.src LIKE '%-edition%') "
          "<> CASE WHEN x.lang IN ('en','ru','zh') THEN 1 ELSE 0 END")
    b = q("SELECT COUNT(*) FROM sense_gloss WHERE lang NOT IN ('en','ru','zh')")
    c = q("SELECT COUNT(*) FROM sense_gloss g JOIN sense_src x ON x.sense_id=g.sense_id "
          "WHERE g.src LIKE '%-edition%' AND x.lang<>g.lang")
    out.append(("E2", not (a or b or c), "" if not (a or b or c) else
                "gloss 条数≠1 的义项 %s ／ 三语之外的 gloss %s ／ 与证据层语言不一致 %s" % (a, b, c)))

    # ── E3 归属：entry 属于同一个词形；证据行与出版义项同词同条目 ────────────
    a = q("SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id WHERE e.word_id<>s.word_id")
    b = q("SELECT COUNT(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
          "WHERE x.word_id<>s.word_id OR x.entry_id<>s.entry_id")
    c = q("SELECT COUNT(*) FROM sense s WHERE NOT EXISTS(SELECT 1 FROM sense_src x WHERE x.sense_id=s.id)")
    out.append(("E3", not (a or b or c), "" if not (a or b or c) else
                "entry 属于别的词形 %s ／ 证据与出版不同词或不同条目 %s ／ **出版义项没有证据** %s"
                % (a, b, c)))

    # ── E4 hidden_why 从证据原文重算一致 ───────────────────────────────
    bad, eg = 0, []
    for sid, h, w, lang, text in con.execute(
            "SELECT s.id, s.hidden, s.hidden_why, x.lang, x.text FROM sense s "
            "JOIN sense_src x ON x.sense_id=s.id"):
        want = criteria.sense_hidden_why(lang, text)
        if (want != w) or (h != (1 if want else 0)):
            bad += 1
            if len(eg) < 4:
                eg.append("#%d %s/%s≠%s" % (sid, h, w, want))
    out.append(("E4", bad == 0, "" if not bad else
                "%s 条 hidden/hidden_why 与重算不一致：%s" % (format(bad, ","), " ｜ ".join(eg))))

    # ── E5 指针只进证据层；出版义项的证据行没有指针目标 ──────────────────────
    a = q("SELECT COUNT(*) FROM sense_src WHERE pointer_target IS NOT NULL AND sense_id IS NOT NULL")
    out.append(("E5", a == 0, "" if not a else
                "%s 条指针被出版成了义项 —— 读者会把「лука́ 的复数属格」当成释义" % format(a, ",")))

    # ── E6 三语方针：fr/vi/pl 只在**破例条件**下出版（用户 2026-10-23 拍板）─────────
    # 破例＝词元、**除破例义项外**一条可印义项都没有、证据不是指针、只挂模型中文。任一条不满足 ⇒ 红。
    a = q("SELECT COUNT(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id JOIN dict d ON d.id=x.word_id "
          "WHERE x.lang NOT IN ('en','ru','zh') AND ("
          " d.is_lemma<>1 OR x.pointer_target IS NOT NULL"
          " OR EXISTS(SELECT 1 FROM sense s2 JOIN sense_src x2 ON x2.sense_id=s2.id WHERE s2.word_id=d.id "
          "           AND s2.hidden=0 AND x2.lang IN ('en','ru','zh'))"
          " OR NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.src LIKE 'model:%'))")
    out.append(("E6", a == 0, "" if not a else
                "%s 条 fr/vi/pl 证据在破例条件之外被出版了 —— 三语方针（`gloss-three-languages`）"
                % format(a, ",")))

    # ── E7 src ⊆ 登记，且每个源都有证据行 ─────────────────────────────────
    got = {r[0] for r in con.execute("SELECT DISTINCT src FROM sense_src")}
    uns, miss = sorted(got - SRC_DOMAIN), sorted(SRC_DOMAIN - got)
    out.append(("E7", not (uns or miss), "" if not (uns or miss) else
                "没登记的源 %s ／ 一行证据都没有的源 %s" % (uns, miss)))

    # ── E8 标签：bucket 值域；源头自己的 grammar 必须在 GRAMMAR_TAGS 里 ───────
    bk = {r[0] for r in con.execute("SELECT DISTINCT bucket FROM sense_tag")}
    bad_b = sorted(bk - BUCKETS)
    bad_g = q("SELECT COUNT(*) FROM sense_tag WHERE bucket='grammar' AND src NOT LIKE 'entry:%%' "
              "AND value NOT IN (%s)" % ",".join("'%s'" % t for t in criteria.GRAMMAR_TAGS))
    out.append(("E8", not (bad_b or bad_g), "" if not (bad_b or bad_g) else
                "bucket 值域外 %s ／ 义项级 grammar 不在 GRAMMAR_TAGS 里 %s" % (bad_b, bad_g)))

    # ── E9 🔴 R11：库里重数「落下的」＋ 统计里「有意不落的」＝ 存档（逐个标签）──────
    try:
        arch = json.loads(R11_ARCHIVE.read_text("utf-8"))["tags"]
        stats = json.loads(STATS.read_text("utf-8"))
        landed = collections.Counter(dict(con.execute(
            "SELECT t.value, COUNT(DISTINCT s.entry_id) FROM sense_tag t JOIN sense s ON s.id=t.sense_id "
            "WHERE t.bucket='grammar' AND (t.src LIKE 'entry:%' OR t.src LIKE '%+entry') "
            "GROUP BY t.value").fetchall()))
        skipped = collections.Counter(stats["r11_skipped"])
        bad9 = ["%s：库里落 %d ＋ 不落 %d ≠ 存档 %d" % (t, landed[t], skipped[t], arch.get(t, 0))
                for t in sorted(set(arch) | set(landed) | set(skipped))
                if landed[t] + skipped[t] != arch.get(t, 0)]
    except Exception as e:                       # noqa: BLE001
        bad9 = ["查不了：%s" % e]
    out.append(("E9", not bad9, " ｜ ".join(bad9[:4])))

    # ── E10 zh 出版文本：没有行首 wiki 标记、没有重复行 ──────────────────────
    bad, eg = 0, []
    for sid, t in con.execute("SELECT sense_id, text FROM sense_gloss WHERE lang='zh'"):
        lines = t.split("\n")
        if any(ln[:1] in "#*" for ln in lines) or len(set(lines)) != len(lines):
            bad += 1
            if len(eg) < 3:
                eg.append("#%d %s" % (sid, t[:40].replace("\n", "⏎")))
    out.append(("E10", bad == 0, "" if not bad else
                "%s 条 zh 出版文本带 wiki 标记或重复行：%s" % (bad, " ｜ ".join(eg))))

    # ── E11 已知答案 ＋ 指针样例 ─────────────────────────────────────────
    bad11 = []
    for w, lang, head, why in KNOWN:
        rows = con.execute(
            "SELECT s.hidden_why FROM sense s JOIN sense_gloss g ON g.sense_id=s.id JOIN dict d "
            "ON d.id=s.word_id WHERE d.word=? AND g.lang=? AND g.text LIKE ?||'%'",
            (w, lang, head)).fetchall()
        if not rows:
            bad11.append("%s/%s「%s」不在出版层" % (w, lang, head))
        elif not any(r[0] == why for r in rows):
            bad11.append("%s/%s「%s」期望 %s 实为 %s" % (w, lang, head, why, [r[0] for r in rows]))
    pw, ps, pt = POINTER
    r = q("SELECT COUNT(*) FROM sense_src x JOIN dict d ON d.id=x.word_id WHERE d.word=? AND x.src=? "
          "AND x.pointer_target=? AND x.sense_id IS NULL", pw, ps, pt)
    if not r:
        bad11.append("指针样例 %s（%s）→ %s 不在证据层或被出版了" % (pw, ps, pt))
    out.append(("E11", not bad11, " ｜ ".join(bad11)))

    # ── E12 覆盖率两个口径只许涨 ────────────────────────────────────────
    cov = coverage(con)
    base = acc.get("coverage")
    if base is None:
        out.append(("E12", False, "还没有已接受基线 —— 跑一次 `--accept`"))
    else:
        drops = [k for k in ("any_pct", "zh_pct") if cov[k] < base[k] - 0.01]
        out.append(("E12", not drops, "" if not drops else
                    "覆盖率跌了 %s：现 %.2f/%.2f 基线 %.2f/%.2f" % (
                        drops, cov["any_pct"], cov["zh_pct"], base["any_pct"], base["zh_pct"])))

    # ── E13 空白页按成因分类 —— 「源头一条义项都没有」与「我们没出版」分开锁 ──────
    bb = acc.get("blank")
    if bb is None:
        out.append(("E13", False, "还没有已接受基线 —— 跑一次 `--accept`"))
    else:
        grew = {k: (cov["blank"].get(k, 0), bb.get(k, 0)) for k in set(cov["blank"]) | set(bb)
                if cov["blank"].get(k, 0) > bb.get(k, 0)}
        out.append(("E13", not grew, "" if not grew else
                    "空白页某一类涨了（现, 基线）：%s" % grew))
    # ── E14 模型中文：每条义项至多一条、必须含汉字、只挂在可印义项上 ──────────────
    a = q("SELECT COUNT(*) FROM (SELECT sense_id FROM sense_gloss WHERE src LIKE 'model:%' "
          "GROUP BY sense_id HAVING COUNT(*)>1)")
    b = sum(1 for (t,) in con.execute("SELECT text FROM sense_gloss WHERE src LIKE 'model:%'")
            if not any("\u3400" <= ch <= "\u9fff" for ch in t))
    c = q("SELECT COUNT(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
          "WHERE g.src LIKE 'model:%' AND s.hidden=1")
    d = q("SELECT COUNT(*) FROM sense_gloss WHERE src LIKE 'model:%' AND src<>'model:deepseek-v4-flash'")
    out.append(("E14", not (a or b or c or d), "" if not (a or b or c or d) else
                "一条义项多条模型中文 %s ／ 模型中文没有汉字 %s ／ 挂在隐藏义项上（钱花在不出版的行上）%s"
                " ／ 没登记的模型 %s" % (a, b, c, d)))
    # ── E15 R29 中文出版正文（简体）：逐行 ＝ 判据；非 zh 行不许有；判据本身过已知答案 ──────
    #    🔴 只比「库 ＝ 判据」逮不到判据本身写坏（两边一起坏仍相等）⇒ 已知答案是另一半：
    #       `覆上` 不许变 `复上`（OpenCC 短语表的错）、繁简对举不转、扩展平面不转、真繁体要转
    bad15, eg15 = collections.Counter(), []
    for tbl in ("sense_gloss", "sense_src"):
        for rid, lang, text, src, pub in con.execute("SELECT id, lang, text, src, text_pub FROM %s "
                                                     "WHERE lang='zh' OR text_pub IS NOT NULL" % tbl):
            if lang != "zh":
                bad15["%s 非 zh 行有 text_pub" % tbl] += 1
                continue
            z = criteria.zh_simp(text, src)
            if pub != (z if z != text else None):
                bad15["%s 与判据不一致" % tbl] += 1
                if len(eg15) < 2:
                    eg15.append("%s→%s" % (text[:16], (pub or "NULL")[:16]))
    for src_t, want in ZH_SIMP_KNOWN:
        if criteria.zh_simp(*src_t) != want:
            bad15["已知答案错：%s" % src_t[0]] += 1
    out.append(("E15", not bad15, "" if not bad15 else "%s %s" % (dict(bad15), " ｜ ".join(eg15))))
    return out


def roster_check(rows):
    got = [c for c, _o, _w in rows]
    return [] if sorted(got) == sorted(ROSTER) and len(set(got)) == len(got) else [
        "花名册对不上：多 %s ／ 少 %s" % (sorted(set(got) - set(ROSTER)), sorted(set(ROSTER) - set(got)))]


def report():
    if not paths.DB.exists():
        print("🔴 库不存在")
        return 1
    con = _open()
    try:
        rows = checks(con)
        cov = coverage(con)
    finally:
        con.close()
    print("■ 义项闸（ru 阶段 5a）—— 花名册 %d 条" % len(ROSTER))
    for cid, ok, why in rows:
        print("   %s %-4s %s" % ("✅" if ok else "🔴", cid, why))
    for b in roster_check(rows):
        print("   🔴🔴 花名册自检：" + b)
    print("   词元有可印义项 %.2f%% ／ 有可印中文 %.2f%% ／ 空白页 %s"
          % (cov["any_pct"], cov["zh_pct"], cov["blank"]))
    red = [r for r in rows if not r[1]]
    print("■ %s（%d/%d）" % ("全绿 ✓" if not red and not roster_check(rows) else "有红",
                            len(rows) - len(red), len(rows)))
    return len(red) + len(roster_check(rows))


def accept():
    con = _open()
    try:
        cov = coverage(con)
    finally:
        con.close()
    ACCEPT.write_text(json.dumps({"coverage": {"any_pct": round(cov["any_pct"], 2),
                                               "zh_pct": round(cov["zh_pct"], 2)},
                                  "blank": cov["blank"]}, ensure_ascii=False, indent=1), "utf-8")
    print("■ 已接受基线：可印义项 %.2f%% ／ 中文 %.2f%% ／ 空白页 %s"
          % (cov["any_pct"], cov["zh_pct"], cov["blank"]))
    return 0


def _mutations():
    """(编号, 说明, 允许的连带红, SQL)。

    🔴 连带红**先跑一遍看实际、逐条确认为什么该红、再写进来**，不许先猜后写。
    """
    return [
        ("E2", "给一条出版义项多塞一条 gloss", set(),
         ["INSERT INTO sense_gloss(sense_id,lang,text,src) SELECT id,'en','«变异»','en-edition' "
          "FROM sense LIMIT 1"]),
        ("E3", "把一批义项挂到别的词形的 entry 上",
         {"E9"},                                  # R11 按 entry 重数，entry 变了就对不上
         ["UPDATE sense SET entry_id=entry_id+1 WHERE id%100=0"]),
        ("E4", "把所有 hidden 清零",
         # E11：`бочечка` 的元描述露出来；E6（5b 之后才有）：藏着的义项放出来 ⇒ 破例义项所在的词元
         #   「有了别的可印义项」⇒ 不再满足破例条件 —— 正是 E6 盯的事
         {"E6", "E11"},
         ["UPDATE sense SET hidden=0, hidden_why=NULL"]),
        ("E5", "把一条指针证据出版出来",
         {"E3"},                                  # 那条证据属于另一个词
         ["UPDATE sense_src SET sense_id=(SELECT MIN(id) FROM sense) WHERE id=(SELECT MIN(id) FROM "
          "sense_src WHERE pointer_target IS NOT NULL)"]),
        ("E6", "把一条 fr 证据出版出来",
         {"E2", "E3"},                            # 语言对不上证据层／属于另一个词
         ["UPDATE sense_src SET sense_id=(SELECT MIN(id) FROM sense) WHERE id=(SELECT MIN(id) FROM "
          "sense_src WHERE lang='fr')"]),
        ("E7", "删掉 pl 版全部证据（少收一版）",
         # E13：只有 pl 证据的词从 d 类变成 e 类；E3（5b 之后才有）：来自 pl 证据的破例义项没了证据
         {"E3", "E13"},
         ["DELETE FROM sense_src WHERE src='pl-edition'"]),
        ("E8", "往 sense_tag 塞一个值域外的 bucket", set(),
         ["UPDATE sense_tag SET bucket='«变异»' WHERE id=(SELECT MIN(id) FROM sense_tag)"]),
        ("E9", "删掉一批 R11 落下的 entry 级标签", set(),
         ["DELETE FROM sense_tag WHERE (src LIKE 'entry:%' OR src LIKE '%+entry') AND value='reflexive'"]),
        ("E10", "往一条 zh 出版文本里塞回 wiki 标记", set(),
         ["UPDATE sense_gloss SET text='#::'||text WHERE id=(SELECT MIN(id) FROM sense_gloss WHERE lang='zh')"]),
        # 🔴 第一版只改了数据、没改判据 ⇒ E4 拿原文一重算就看见了，**这条变异测的不是它自称的东西**。
        #    E11 存在的理由是「判据函数**本身**写坏时 E4 跟着坏而报绿」——用一条 SQL 模拟不出来。
        #    ⇒ 第 5 个元素：检查期间把 `criteria.sense_hidden_why` 换成同样坏掉的版本
        #       （「鴿子」也判成元描述），E4 与坏数据一致而绿，**E11 必须单独红**。
        ("E11", "判据本身坏了（把「鴿子」也判成元描述）—— E4 跟着坏而报绿，只有已知答案拦得住", set(),
         ["UPDATE sense SET hidden=1, hidden_why='zh-元描述（zh_gloss_kind=meta）' WHERE id IN "
          "(SELECT g.sense_id FROM sense_gloss g JOIN sense s ON s.id=g.sense_id JOIN dict d ON "
          "d.id=s.word_id WHERE d.word='голубь' AND g.text='鴿子')"],
         lambda orig: (lambda lang, text: "zh-元描述（zh_gloss_kind=meta）" if text == "鴿子"
                       else orig(lang, text))),
        ("E12", "删掉一半词元的中文义项",
         {"E9", "E11", "E13"},                    # 删掉的义项挂着 R11 标签／样例／空白页涨
         ["DELETE FROM sense WHERE id IN (SELECT g.sense_id FROM sense_gloss g WHERE g.lang='zh') "
          "AND word_id%2=0"]),
        ("E14", "给一条模型中文造一条重复", set(),
         ["INSERT INTO sense_gloss(sense_id,lang,text,src) SELECT sense_id,'zh',text||'«变异»',src "
          "FROM sense_gloss WHERE src LIKE 'model:%' LIMIT 1"]),
        ("E15", "R29：一条简体出版正文被清空（页面回到繁体）", set(),
         ["UPDATE sense_src SET text_pub=NULL WHERE id=(SELECT MIN(id) FROM sense_src WHERE text_pub IS NOT NULL)"]),
        ("E13", "把一批词元的出版义项全部删掉（空白页涨）",
         {"E9", "E11", "E12"},                    # 同上，覆盖率跌
         ["DELETE FROM sense WHERE word_id IN (SELECT id FROM dict WHERE is_lemma=1 AND id%7=0)"]),
    ]


def mutate():
    if report():
        print("\n🔴 基线就不绿，先修基线")
        return 1
    muts = _mutations()
    print("\n■ 变异验证（%d 条，跑在库的副本上）" % len(muts))
    print("   ⚠️ E1   无变异档：清空会让几乎每条连带红，分不开")
    real = paths.DB
    fails = []
    for m in muts:
        cid, why, also, sqls = m[:4]
        patch = m[4] if len(m) > 4 else None
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
                orig = criteria.sense_hidden_why
                if patch:
                    criteria.sense_hidden_why = patch(orig)
                con = _open()
                try:
                    got = {c for c, ok, _ in checks(con) if not ok}
                finally:
                    con.close()
                    criteria.sense_hidden_why = orig
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
