#!/usr/bin/env python3
"""阶段 5a —— 三版收割例句 → `example` / `example_gloss`。零模型调用。2026-09-15。

═══ 三版都有例句，而且**中文版白送译文** ═══
    英文版  22,178 条  译文是**英文**（20,680 条）
    日语版  25,592 条  几乎没有译文（215 条，且多数是 kaikki 字段错位）
    中文版  12,361 条  译文是**中文**（8,288 条）⇒ **免费的例句中文译文，零模型调用**

⇒ 全量约 6 万条，比 `JA_PLAN` §一 估的 26,352 多一倍多 —— 那个估算只量了一版。

═══ 🔴🔴 de 的两条筛选判据，在日语上**一条都不能照抄** ═══
de 的 `harvest_examples` 判据②是「`bold_text_offsets` 缺失且词形不出现在句中 ⇒ 挂错了词」。
照搬到日语上会丢 **6,539 条（11%）**，而实测那 6,539 条里绝大多数是**对的**：

    痛い   → 「痛っ！」        用言**活用**了，词元当然不原样出现
    いろ   → 「色をなす」      **假名词头的例句用汉字写**，词元当然不出现
    国     → 「どうして？」     漫画对白**多行引文**，词出现在同一块的别的行
    明るい → 「Near-synonym: 通じる」  这条才是真该丢的

而且 `w.lower() in t.lower()` 里的 `.lower()` 在日语上**是个空操作**（只折 ASCII）——
判据看着通用，实际只对拉丁语言成立（`[[decision-not-propagated-across-editions]]`）。
⇒ **本步不设「词必须出现在句中」这条判据。** 证据不足就别装作有证据。

═══ 🔴 中文版的 `text` 有时装的是**中文**，不是日语例句 ═══
    見せる → text 「让我看一下。」    ← 这是译文，被 kaikki 放进了 text
    中     → text 「组词：中心(ちゅうしん)/…」 ← 这是编者注

**判据按结构，不按字形**（量过才这么定）：

    有 translation   8,288 条 ── 含简体专用字     1 条（0.01%）
    无 translation   4,073 条 ── 含简体专用字 1,716 条（**42%**）

⇒ 中文版给了译文的，`text` 就是日语原句；没给译文的那批才要查。

⚠️ **「没有假名 ⇒ 是中文」这条判据我试过，比它要描述的东西宽得多**：
   `青空。` `核兵器` `二時間` `数百人` 全是纯汉字的正经日语例句，会被误杀 2,490+2,201 条。
   `[[criteria-narrower-than-you-think]]` 第 N 次。

═══ 简体专用字表**从数据里推**，不手写 ═══
`c` 是简体专用字 ⟺ `opencc.s2t(c) != c`（有不同的繁体形）**且** `c` 在
**英文版+日语版的 25 万词头里一次都没出现过**。

🔴 参照语料**必须排除中文版收进来的那批词**。第一版我拿整张 `dict` 当参照 ——
   而 `dict` 里有 6 万个中文版收来的词形，于是 `显`/`让` 这些字"在日语里出现过" ⇒
   判据自己把自己废了。**拿被污染的语料当参照，量出来的是污染。**

用法（在仓库根）：
    python3 -u ja/pipeline/harvest_examples.py
    python3 -u ja/pipeline/harvest_examples.py --apply
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
_simp = set()
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
# 日语版的编者注行，不是例句。⚠️ 判据写全角冒号和半角两种。
NOTE = re.compile(r"^(用法|語源|参考|類義語|対義語|関連語|派生語|語義)\s*[:：]")
# 「日语例句　　中文译文」挤在一格 —— 全角空格或 ≥2 个空白当分隔
CRAM = re.compile(r"[\u3000]+|\s{2,}")


def editions():
    """→ [(src 名, 打开器, 语言过滤, 译文语言)]。译文语言 None＝那一版的译文不可信。"""
    return [
        ("en-edition", lambda: open(paths.KK, encoding="utf-8"), None, "en"),
        # 🔴 日语版的 `translation` 只有 215 条，抽样看**装的是日语不是译文**
        #    （`保護` 那条 translation 是日语说明、ref 是另一段日语，连 text 都没有）。
        #    ⇒ 不当译文收，只记数。一个字段名叫 translation 不等于里面是译文。
        ("ja-edition", lambda: open(paths.EDITION, encoding="utf-8"), None, None),
        ("zh-edition", lambda: gzip.open(paths.ZH_EDITION, "rt", encoding="utf-8"),
         "ja", "zh"),
    ]


def simplified_only(con):
    """简体专用字集合 —— **从数据推，不手写**。见文件头。"""
    import opencc
    cv = opencc.OpenCC("s2t").convert
    seen = collections.Counter()
    for (w,) in con.execute(
            "SELECT word_src FROM entry WHERE src IN ('en-edition','ja-edition')"):
        seen.update(w)
    # 🔴 判据是「出现 **< 3 次**」不是「一次都没有」。英文版/日语版里夹着少量
    #    中文词条，`么`(4次)／`门`(1)／`过`(1)／`办`(1) 因此"在日语里出现过" ⇒
    #    整张字表被四个孤例掏出洞，49 条中文句子照样进了日语例句列。
    #    ⚠️ 代价是 1-2 次那档里少数真·罕用日语汉字（`侭`）会被误判 ——
    #       这是**丢**，而留下中文句子是**错**，错比缺更伤权威（`docs/FRAMEWORK.md`）。
    return {c for c in map(chr, range(0x4E00, 0xA000)) if cv(c) != c and seen[c] < 3}


def bridges(con):
    """→ {src: {(词形, 该版释义原文): sense_id}}。

    🔴 桥按**该版自己写的释义原文**建，不按语言建。de 那轮把桥写死成一个 `src`，
       后来同语言多了两层新释义，桥一条没跟上 ⇒ **漏挂 189,931 条例句**，
       而页面上看起来只是「这个词没有义项级例句」—— 静默。
    ⚠️ 所以下面那条断言在：**每一个非模型的 gloss src 都必须有桥**，
       将来多一层新来源、桥没跟上，当场红。
    """
    out = collections.defaultdict(dict)
    for src, word, text, sid in con.execute(
            "SELECT g.src, d.word, g.text, g.sense_id FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.src NOT LIKE 'model:%'"):
        out[src].setdefault((word, text), sid)
    have = {r[0] for r in con.execute(
        "SELECT DISTINCT src FROM sense_gloss WHERE src NOT LIKE 'model:%'")}
    missing = have - set(out)
    assert not missing, "有 gloss 来源没建桥：%s（de 正是这么漏掉 19 万条例句的）" % missing
    return out


def harvest(con):
    words = {r[0] for r in con.execute("SELECT word FROM dict")}
    br = bridges(con)
    simp = simplified_only(con)
    rows, stat, best = [], collections.Counter(), {}
    # 🔴 例句的**身份**（一行 `example`）和它的**译文**（多行 `example_gloss`）是两回事。
    #    第一版把两者绑在一起：同词同句多版都有时留信息最多的那一条，**另一版的译文被一起丢掉**
    #    ⇒ 免费中文译文从 8,288 掉到 3,739，因为英文版先到、英文译文占住了那一行。
    #    而 `example_gloss` 的主键是 `(example_id, lang)` —— 它本来就装得下两种语言。
    #    ⇒ 译文单独攒，按 (词,句,语言) 收全；去重只去**例句**，不去译文。
    glosses = {}
    for src, op, lc, tlang in editions():
        bridge = br.get(src, {})
        with op() as fh:
            for line in fh:
                if '"examples"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if lc and o.get("lang_code") != lc:
                    continue
                w = o.get("word") or ""
                if w not in words:
                    stat[src + "/词形不在库里"] += 1
                    continue
                for s in o.get("senses") or []:
                    gl = ((s.get("glosses") or [""])[0] or "").strip()
                    sid = bridge.get((w, gl))
                    for x in s.get("examples") or []:
                        t = (x.get("text") or "").strip()
                        tr = (x.get("translation") or "").strip()
                        stat[src + "/源头例句"] += 1
                        if not t or not any(c.isalpha() for c in t):
                            stat[src + "/🔴 丢：空句或只有标点"] += 1
                            continue
                        if NOTE.match(t):
                            stat[src + "/🔴 丢：编者注不是例句"] += 1
                            continue
                        # 🔴 只对中文版查，且**只查它没给译文的那批**（见文件头的数）
                        if src == "zh-edition" and not tr and any(c in simp for c in t):
                            # 🔴 **丢之前先问里面有没有别的层要的料**（阶段 4b 的教训：
                            #    3a 把中文版 gloss 抬头当残渣洗掉了，而那里面是读音）。
                            #    这里有 317 条是**日语例句　　中文译文挤在一格**，
                            #    kaikki 没拆开。整条丢＝既丢例句又丢一条免费译文。
                            part = [x for x in CRAM.split(t) if x.strip()]
                            if (len(part) == 2
                                    and not any(c in simp for c in part[0])
                                    and any(c in simp for c in part[1])):
                                t, tr, tlang = part[0].strip(), part[1].strip(), "zh"
                                stat[src + "/⭐ 拆出「例句　　译文」"] += 1
                            else:
                                stat[src + "/🔴 丢：text 装的是中文不是日语例句"] += 1
                                continue
                        # 🔴 攒译文必须在**去重之前** —— 第一版放在 `continue` 后面，
                        #    重复的那一版直接跳过，中文译文照样丢（8,288 → 3,739 没动）。
                        #    改对了一半等于没改：位置错和逻辑错，症状一模一样。
                        if tr and tlang:
                            glosses.setdefault((w, t, tlang), (tr, src))
                        k = (w, t)
                        cur = best.get(k)
                        # 同词同句多版都有 ⇒ **留信息最多的那条**（有译文 > 没译文），
                        # 不是"先到先得"。判据确定、可复现。
                        score = (2 if (tr and tlang) else 0) + (1 if sid else 0)
                        if cur is not None:
                            stat[src + "/重复（同词同句）"] += 1
                            if score <= cur[0]:
                                continue
                        ruby = x.get("ruby") or None
                        best[k] = (score, (
                            w, sid, t,
                            json.dumps(x.get("bold_text_offsets"), ensure_ascii=False)
                            if x.get("bold_text_offsets") else None,
                            (x.get("ref") or "").strip() or None,
                            gl or None,
                            tr or None,
                            tlang if tr else None,
                            (x.get("roman") or "").strip() or None,
                            json.dumps(ruby, ensure_ascii=False) if ruby else None,
                            0, src))
                        stat[src + "/收下"] += 1
                        if sid:
                            stat[src + "/  其中挂上了义项"] += 1
    rows = [v[1] for v in best.values()]
    return rows, glosses, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    global _simp
    _simp = simplified_only(con)
    rows, glosses, stat = harvest(con)
    con.close()
    for k in sorted(stat):
        print("   %-46s %s" % (k, f(stat[k])))
    tr = sum(1 for k in glosses if k[2] == "zh")
    en = sum(1 for k in glosses if k[2] == "en")
    sid = sum(1 for r in rows if r[1])
    print("\n■ 去重后 %s 条｜挂上义项 %s (%.1f%%)｜**免费中文译文 %s**｜英文译文 %s"
          % (f(len(rows)), f(sid), 100 * sid / max(len(rows), 1), f(tr), f(en)))
    print("■ 带罗马字 %s｜带振假名 %s"
          % (f(sum(1 for r in rows if r[8])), f(sum(1 for r in rows if r[9]))))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        for r in rows[:6]:
            print("   %-10s %s" % (r[0], r[2][:46]))
        return

    old_e, old_g = (sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
                    .execute("SELECT (SELECT COUNT(*) FROM example),"
                             "(SELECT COUNT(*) FROM example_gloss)").fetchone())
    # 本步**可重跑**：先清空再灌，`expect` 记的是净变化（`[[answer-file-is-the-ledger]]`）
    with dbtool.session("ja-harvest-examples", expect={
            "#example": len(rows) - old_e, "#example_gloss": tr + en - old_g,
            "#dict": 0, "#entry": 0, "#sense": 0}) as con:
        con.execute("DELETE FROM example_gloss")
        con.execute("DELETE FROM example")
        for col in ("roman", "ruby"):
            try:
                con.execute("ALTER TABLE example ADD COLUMN %s TEXT" % col)
            except sqlite3.OperationalError:
                pass
        con.executemany(
            "INSERT OR IGNORE INTO example(word,sense_id,text,bold,ref,src_gloss,"
            "src_translation,src_lang,roman,ruby,hidden,src) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        ids = {(w, t): i for i, w, t in
               con.execute("SELECT id, word, text FROM example")}
        con.executemany(
            "INSERT OR IGNORE INTO example_gloss(example_id,lang,text,src) VALUES(?,?,?,?)",
            [(ids[(w, t)], lang, txt, src)
             for (w, t, lang), (txt, src) in glosses.items() if (w, t) in ids])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("sense_id 不指向不存在的义项", q(
            "SELECT COUNT(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id "
            "WHERE e.sense_id IS NOT NULL AND s.id IS NULL") == 0),
        ("挂上的义项与例句是同一个词", q(
            "SELECT COUNT(*) FROM example e JOIN sense s ON s.id=e.sense_id "
            "JOIN dict d ON d.id=s.word_id WHERE d.word<>e.word") == 0),
        # 🔴 **断言必须和抽取器用同一条规则**。第一版我在这儿手写了 13 个字
        #    （`让这么们对东车马门书说过还`）—— 那是判据的一个**形式代理**，
        #    比判据窄得多，报红/报绿都说明不了问题。阶段 1 的罗马字断言犯过同一个病。
        # 🔴 断言的**范围**也必须和判据一样。第二版我把范围写成「中文版的全部例句」，
        #    而判据只作用在**中文版里没给译文的那批**（给了译文的，text 已被证明是日语）。
        #    结果报红 9 条，逐条读全是真日语：万葉仮名（`伊祢都氣波…`）、`蒋経国`、
        #    `蜀ノ刘備`、源头用异体字的 `調理师`/`渊`/`气`。
        #    判据对、范围宽 —— 症状和判据本身写宽一模一样（`[[criteria-narrower-than-you-think]]`）。
        #    ⚠️ 那 9 条里确实有 1 条是坏的（`を` 的 text 是中文注解），但它**有译文**，
        #       不在本判据的责任范围内，记进欠账而不是让这道闸长期报红。
        ("中文版「无译文」那批没有简体专用字残留（与抽取器同范围同判据）", sum(
            1 for (t,) in con.execute(
                "SELECT text FROM example WHERE src='zh-edition' AND src_translation IS NULL")
            if any(c in _simp for c in t)) == 0),
        ("每条 example_gloss 都指向存在的例句", q(
            "SELECT COUNT(*) FROM example_gloss g LEFT JOIN example e ON e.id=g.example_id "
            "WHERE e.id IS NULL") == 0),
        ("免费中文译文 > 8,000 条", q(
            "SELECT COUNT(*) FROM example_gloss WHERE lang='zh'") > 8000),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
