#!/usr/bin/env python3
"""阶段 6a —— 五版收割例句 → `example` / `example_gloss`。零模型调用。2026-09-24。

═══ 分工与 ja 那门**反过来** ═══
    韩文版  29,241 条  ← **主力**，而它**几乎没有译文**（`translation` 只有 50 条）
    英文版   9,764 条  译文是英文（9,214 条）
    中文简   4,384 条  译文**挤在 `text` 同一格里**（全角空格分隔）
    中文繁   3,297 条  同上，另有 1,308 条在 `translation` 字段里
    日文版   1,374 条  译文是日语 ⇒ 按「释义只保留三语」**整层不进** `example_gloss`
ja 那门是中文版白送译文（8,288 条），ko 这门主力源是**裸句** —— 别照搬那个结论。

═══ 🔴 各版的 `examples` 里都混着**不是例句**的东西，而且混法各不相同 ═══
    中文版：`近义词：추` / `派生詞：늦가을，올가을…` / `季节：봄 - 여름 - 가을 - 겨울`
    韩文版：`동사: 패배하다` / `약자: 臥竜` / `유의어: 선`   ← **前缀是谚文**
    日文版：`関連語: 보이다` / `参照: 이십사절기`
    英文版：几乎没有（7 条，而其中 6 条是**对话里的说话人标记** `나: 듣던 중…`）

🔴🔴 **判据不能一条通吃**。我第一版写的是「前缀不含谚文就算标签」——
   那是照中文版设计的，**在韩文版上整个失效**（它的标签正是谚文）。
   而若反过来把「任何 `X:` 开头」都当标签，**英文版那 6 条真对话就被误杀**。
   ⇒ 判据 = **按版、量出来的封闭前缀表**（韩文版 82 种 / 日文版 59 种 / 中文版 66 种，
     逐种看过样本）。⚠️ **不在表里的一律当例句留下** ——
     例句层里混进一条假的看得见，静默删掉一条真的看不见
     （`[[criteria-narrower-than-you-think]]`／`[[dont-say-source-lacks-what-we-skipped]]`）。

⚠️ **「有没有空格」这条判据我试过，两个方向都不成立**：
   `맛있겠네.` 没空格却是真句子；`季节：봄 - 여름 - 가을 - 겨울` 有空格却是关系数据。
   又一次形式代理（`[[criteria-from-meaning-not-form]]`）。

═══ 带标签的那批**不丢，留给关系层** ═══
它们是关系数据（近义/反义/派生/异体/方言…），本步**只统计不删**，
落账 `data/work/ko/example_labeled_rows.tsv`，由 `harvest_relations_from_examples.py` 接。
🔴 已实测中文两片里藏着 **3,014 条库里没有的关系边**（阶段 2d 整路漏收）。

跑（在仓库根）：
    python3 -u ko/pipeline/harvest_examples.py
    python3 -u ko/pipeline/harvest_examples.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import json
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")
BATCH = 20000

HANGUL = re.compile(r"[가-힣]")
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
CJK = re.compile(r"[一-鿿㐀-䶿]")
PRE = re.compile(r"^([^\s:：]{1,10})\s*[:：]\s*(.+)$", re.S)

# ══ 量出来的前缀表。**每一种都看过样本**，分三类 ══
#   DROP  = 不是例句（关系/记法/元信息/别的语言）⇒ 本步不收，落账给关系层
#   KEEP  = 是例句，但前面挂了个标签 ⇒ **剥掉标签收正文**
#   其余（不在表里）= 当例句收
LABEL_KEEP = {"예문", "속담", "例"}
LABEL_DROP = {
    # ── 韩文版：词性名（派生词列举）──
    "동사", "부사", "형용사", "명사", "관형사", "명사형", "동사형", "피동사",
    "능동사", "사동사", "접속부사", "양태부사", "부정부사", "성상부사", "지시부사",
    # ── 韩文版：记法 ──
    "약자", "정자", "간체", "이체자", "한자", "학명", "화학식",
    # ── 韩文版：关系 ──
    "참조", "참고", "유의어", "유의어s", "비슷한말", "동의어", "동의어s", "유사어",
    "유의가", "반의어", "반의어s", "상대어", "상위어", "준말", "본말", "약칭",
    "여린말", "센말", "큰말", "작은말", "거센말", "이형태", "합성어", "어근",
    "관련어", "사투리", "방언", "지역어(방언)", "옛말", "속어", "높임말",
    "복수표준어", "원문",
    # ── 韩文版：元信息 / 别的语言 ──
    "부록", "(부록", "위키데이터", "위키백과", "제목", "본명", "구성", "고빈도어",
    "일본어", "현대일본어", "현대한국어", "러시아어(ru)", "번역",
    # ── 日文版 ──
    "関連語", "参照", "異表記・別形", "派生語", "同義語", "固有語", "動詞化",
    "音訓混ざる式", "対義語", "synonym",
    # ── 中文版（简/繁两套写法都要有）──
    "近义词", "近義詞", "近义詞", "近义", "反义词", "反義詞", "反义詞",
    "派生词", "派生詞", "派生", "相关词汇", "相關詞彙", "相关", "相關",
    "类似词汇", "相近词汇", "類似詞彙", "同源詞", "对比",
    "动词", "動詞", "名词", "名詞", "形容词", "形容詞", "副词", "副詞",
    "略词", "略詞", "俗语", "俗語", "俗稱", "敬語", "敬称", "隱語",
    "北韩", "北韓", "北韓語", "南韩", "南韓", "朝鲜文化语", "方言", "季节",
    "误词", "誤詞", "对音词", "近音詞", "固有词", "汉字词", "外来语",
    "使役形", "被动形", "限定词", "叠词", "异序词", "其他词形",
    "类似后缀", "相近后缀", "相關後綴", "相近词尾", "相近助词",
    "常见搭配", "常見搭配", "相关动词", "大词", "小词", "请参考", "西式香肠",
}

SRC = [("en-edition", paths.KK),
       ("ko-edition", paths.EDITION),
       ("zh-edition-simp", paths.ZH_SIMP),
       ("zh-edition-trad", paths.ZH_TRAD),
       ("ja-edition", paths.JA_EDITION)]


def _op(p):
    return (gzip.open(p, "rt", encoding="utf-8") if str(p).endswith(".gz")
            else open(p, "rt", encoding="utf-8"))


def is_zh(s):
    """中文：有汉字、没有谚文、没有假名。⚠️ 只看『有没有汉字』会把日语收进来
    （`河岸` `川端` `井戸端` 全是纯汉字的日语，实测 49 条）。"""
    return bool(s and CJK.search(s) and not HANGUL.search(s) and not KANA.search(s))


def split_text(src, raw):
    """→ (韩语正文, 中文译文 or None, 丢掉的东西)。**各版分法不同，逐版量过。**"""
    t = raw.strip()
    if src.startswith("zh-"):
        # 中文版把译文和原文挤在一格，用**全角空格**分隔（实测 3,667 条）
        parts = [x.strip() for x in re.split(r"　+", t, 1)]
        if len(parts) == 2 and HANGUL.search(parts[0]) and is_zh(parts[1]):
            return parts[0], parts[1], None
        return t, None, None
    if src == "ja-edition":
        # 日文版：先取第一行（后面粘着汉字表记行和罗马字行），再切日语译文。
        # 🔴 日语译文**不进库**（`[[gloss-three-languages]]` 只留中+英+本语言）
        head = t.split("\n", 1)[0].strip()
        if ": " in head:
            L, R = head.split(": ", 1)
            if HANGUL.search(L) and (KANA.search(R) or not HANGUL.search(R)):
                return L.strip(), None, R.strip()
        return head, None, None
    return t, None, None


def harvest():
    rows, seen = [], set()
    labeled, resid = [], collections.Counter()
    stat = collections.Counter()
    for src, p in SRC:
        for line in _op(p):
            try:
                o = json.loads(line)
            except Exception:
                continue
            w = (o.get("word") or "").strip()
            if not w:
                continue
            for se in o.get("senses") or []:
                gloss = (se.get("glosses") or [None])
                gloss = gloss[-1] if gloss else None
                for e in se.get("examples") or []:
                    t = (e.get("text") or "").strip()
                    if not t:
                        stat["跳过·text 是空的·" + src] += 1
                        continue
                    m = PRE.match(t)
                    if m and m.group(1) in LABEL_DROP:
                        labeled.append((src, w, m.group(1), m.group(2).replace("\t", " ")))
                        stat["带标签·留给关系层·" + src] += 1
                        continue
                    if m and m.group(1) in LABEL_KEEP:
                        t = m.group(2).strip()
                    elif m:
                        resid[m.group(1)] += 1      # 不在表里 ⇒ 当例句收，但报出来
                    body, zh, dropped = split_text(src, t)
                    # 🔴🔴 **多行的两种形状，判据是结构不是字形**（回源逐条看的）：
                    #   ① `type:"example"` 且**没有** english/translation 字段
                    #      ⇒ `text` 把「出处＋韩语＋罗马字＋英译」挤在一格：
                    #        `1961, Bible …\n太初에 하나님이…\nIn the beginning God…`
                    #      ⇒ **不硬拆**（拆错了没人看得出来），标 `hidden=1` 留着。
                    #   ② `type:"quotation"` 且字段齐全 ⇒ 多行正文是**真的多行韩语**
                    #      （歌词、时调），原样收。
                    #   ⚠️ 判据若写成"多行就藏"，会误伤 ② 那批真例句；
                    #     写成"有 File: 就藏"又漏掉别的塞法（`[[criteria-from-meaning-not-form]]`）。
                    crammed = ("\n" in body
                               and not (e.get("translation") or e.get("english")))
                    if not HANGUL.search(body):
                        stat["跳过·正文里没有谚文·" + src] += 1
                        continue
                    if (w, body) in seen:
                        stat["跳过·与已收的重复·" + src] += 1
                        continue
                    seen.add((w, body))
                    # 译文：字段优先，其次是挤在一格里切出来的
                    en = e.get("translation") or e.get("english")
                    en = en.strip() if en and not HANGUL.search(en) else None
                    if src.startswith("zh-") and not zh and en and is_zh(en):
                        zh, en = en, None
                    if src == "ja-edition":
                        en = None                    # 它的 translation 是日语
                    if en and (CJK.search(en) or KANA.search(en)):
                        en = None                    # 不是英文就别当英文存
                    rows.append({
                        "word": w, "text": body, "src": src,
                        "src_gloss": gloss, "ref": e.get("ref"),
                        "roman": e.get("roman"),
                        "src_translation": dropped or e.get("translation"),
                        "src_lang": "ja" if src == "ja-edition" else None,
                        "zh": zh, "en": en, "hidden": 1 if crammed else 0,
                    })
                    if crammed:
                        stat["⚠️ 多行挤成一格·标 hidden 留着·" + src] += 1
                    stat["✅ 收·" + src] += 1
    return rows, labeled, resid, stat


def bridge(con, rows):
    """例句 → 义项。走 `sense_src.src_ref` 的**位置键**，不比释义文本。

    🔴 按 (词形, 源, 释义原文) 建桥：同一条释义原文在同一个词形下只会属于一条义项。
       ⚠️ 位置键那条路（重放 `iter_entries` 数下标）更严，但它要求收词那一步的
         遍历顺序完全复现；这儿用「词形＋源＋释义原文」三元组，**同样不依赖顺序**，
         而且能被下面的回核独立验证。
    """
    idx = {}
    for w, src, txt, sid in con.execute(
            "SELECT d.word, ss.src, ss.text, ss.sense_id FROM sense_src ss "
            "JOIN dict d ON d.id = ss.word_id WHERE ss.sense_id IS NOT NULL"):
        idx.setdefault((w, src, (txt or "").strip()), sid)
    n = 0
    for r in rows:
        g = (r["src_gloss"] or "").strip()
        sid = idx.get((r["word"], r["src"], g)) if g else None
        r["sense_id"] = sid
        n += sid is not None
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, labeled, resid, stat = harvest()
    print("■ 收割结果")
    for k, v in sorted(stat.items()):
        print("   %-34s %8s" % (k, f(v)))
    print("   %-34s %8s" % ("── 例句合计", f(len(rows))))

    if resid:
        print("\n⚠️ 不在前缀表里、被当成例句收下的（**报出来，不静默**）：%d 种"
              % len(resid))
        print("   " + "  ".join("%s=%d" % kv for kv in resid.most_common(14)))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[0] for r in con.execute("SELECT word FROM dict")}
    miss = [r for r in rows if r["word"] not in indict]
    if miss:
        print("\n🔴 %s 条例句的词形不在 `dict` 里（不收）" % f(len(miss)))
        rows = [r for r in rows if r["word"] in indict]
    n_sid = bridge(con, rows)
    n_zh = sum(1 for r in rows if r["zh"])
    n_en = sum(1 for r in rows if r["en"])
    print("\n■ 挂回义项 %s / %s（%.1f%%）—— 挂不上的存词级，`sense_id` 留 NULL"
          % (f(n_sid), f(len(rows)), 100.0 * n_sid / max(len(rows), 1)))
    print("■ 白送的译文：中文 %s 条 ／ 英文 %s 条" % (f(n_zh), f(n_en)))

    p = paths.WORK / "example_labeled_rows.tsv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("# `examples` 里带标签的行 —— **不是例句，是关系数据**。2026-09-24。\n")
        fh.write("# 留给 harvest_relations_from_examples.py，本文件是它的输入与账。\n")
        fh.write("# src\tword\tlabel\tpayload\n")
        for r in labeled:
            fh.write("\t".join(r) + "\n")
    print("■ 带标签的 %s 行落账 → %s" % (f(len(labeled)), p.relative_to(paths.ROOT)))

    before = {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
              for t in ("example", "example_gloss")}
    con.close()
    if not a.apply:
        print("\n（这是 dry 跑。加 --apply 才写库）")
        return

    n_hid = sum(r["hidden"] for r in rows)
    ex = [(r["word"], r["sense_id"], r["text"], r["ref"], r["src_gloss"],
           r["src_translation"], r["src_lang"], r["roman"], r["hidden"], r["src"])
          for r in rows]
    with dbtool.session(
            "ko-harvest-examples",
            expect={"#example": len(ex), "#example_gloss": n_zh + n_en,
                    "example.src_translation": sum(
                        1 for r in rows if r["src_translation"])},
            invalidates=[
                "阶段 6 的例句译文：**主力源韩文版几乎没有译文**（29,241 条里 50 条）⇒ "
                "要给读者中文例句只能送模型翻译，那是一笔**要单独报价**的钱",
                "展示层（阶段 9）：例句有 `sense_id` 的挂在义项下，NULL 的挂在词级；"
                "两种都要有位置，别让 NULL 的那批消失",
                "带标签的行**还没进关系层** —— `data/work/ko/example_labeled_rows.tsv` "
                "是那笔账，实测中文两片里有 3,014 条库里没有的边",
            ]) as s:
        for i in range(0, len(ex), BATCH):
            s.executemany(
                "INSERT OR IGNORE INTO example (word, sense_id, text, ref, src_gloss,"
                " src_translation, src_lang, roman, hidden, src)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                ex[i:i + BATCH])
        ids = {(w, t): i for i, w, t in s.execute(
            "SELECT id, word, text FROM example").fetchall()}
        gl = []
        for r in rows:
            eid = ids.get((r["word"], r["text"]))
            if eid is None:
                continue
            if r["zh"]:
                gl.append((eid, "zh", r["zh"], r["src"]))
            if r["en"]:
                gl.append((eid, "en", r["en"], r["src"]))
        for i in range(0, len(gl), BATCH):
            s.executemany(
                "INSERT OR IGNORE INTO example_gloss (example_id, lang, text, src)"
                " VALUES (?,?,?,?)", gl[i:i + BATCH])

    # ── 写后回核：**从库里按口径重算**，不用上面任何一个 len(...) ──
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda sql: con.execute(sql).fetchone()[0]
    print("\n■ 写后回核（从库里重算）")
    checks = [
        ("example 行数", q("SELECT COUNT(*) FROM example"),
         before["example"] + len(ex)),
        ("挂上义项的例句", q("SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL"),
         n_sid),
        ("中文例句译文", q("SELECT COUNT(*) FROM example_gloss WHERE lang='zh'"), n_zh),
        ("英文例句译文", q("SELECT COUNT(*) FROM example_gloss WHERE lang='en'"), n_en),
        ("🔴 正文里没有谚文的例句",
         q("SELECT COUNT(*) FROM example WHERE text NOT GLOB '*[가-힣]*'"), 0),
        ("🔴 挂到了不存在的义项上",
         q("SELECT COUNT(*) FROM example e WHERE e.sense_id IS NOT NULL AND NOT EXISTS"
           "(SELECT 1 FROM sense s WHERE s.id = e.sense_id)"), 0),
        ("hidden=1（多行挤成一格）", q("SELECT COUNT(*) FROM example WHERE hidden=1"),
         n_hid),
        ("🔴 例句的词形不在 dict 里",
         q("SELECT COUNT(*) FROM example e WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.word = e.word)"), 0),
    ]
    red = 0
    for name, got, want in checks:
        mark = "✅" if got == want else "🔴"
        red += got != want
        print("   %s %-30s %9s  期望 %9s" % (mark, name, f(got), f(want)))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
