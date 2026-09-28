#!/usr/bin/env python3
"""K16：例句译文的残差 —— 把**逐条读过的** 21 条重译一轮。ko，2026-09-26。

═══ 账上写的是「~30 条」，那是折算值不是清单 ═══
形状检查（`translate_examples` 里的 `HANGUL`/`LATIN`）在全量 37,433 条上报出
**谚文 374 ／ 拉丁 42 ／ 疑似只译词头 625**。账上从 22 条抽样里看到 4–6 条真坏，
折算成「~30 条」。**折算值不能拿来修** —— 要修得有清单。

⇒ 414 个候选（谚文 ∪ 拉丁，去重）**逐条读完**，分出四类：

    ① 压根没译（规范化后译文 ≡ 原文）      127 条
         ├ 复合词表（`珠算/주산, 珠板/주판…`）  89  ← **没有可译的东西，对的**
         ├ 关系数据被当例句收了（`Coordinate term: …`、`만나다 > 만남`） 27
         │                                     ← **不是翻译缺陷**（K15/K30 的形状）
         └ 🔴 韩语散文没译                     11  ← 真缺陷（9 条进名册，2 条见下）
    ② 词被劈成两半 / 助词残留 / 乱码         7 条  ← 真缺陷
    ③ 外文词留在中文句里                     6 条  ← 真缺陷（其中 2 条见下）
    ④ 加了源文没有的内容                     1 条  ← 真缺陷
    ⑤ 被讨论的对象（`非规范写法：섀시`、`한글 자모 중 와는…`）   ← **对的，不许动**

🔴🔴 **查证出处救了两条**：`[33129]`（维基简繁标记 `zh-hans:…; zh-hant:…;` 漏在译文里、
   整句繁体）和 `[36935]`（人名写成罗马字 `Youngsu和Yuseong`）的 `src` 是
   **`zh-edition-simp` / `zh-edition-trad`** —— 它们**不是我们译的，是中文维基自己那么写的**。
   ⇒ 重译等于拿模型改源头给的内容。按 `[[source-typo-fix-ours-not-quote]]`：
     `33129` 清掉转换标记（改**我们的出版文本**，引文与证据层一个字不动）；
     `36935` 的罗马字人名是源头的**体例选择**不是错字，**留着并记账**。
   ⚠️ 差一步就把这两条混进跑批里了。**动译文之前先问这条译文是谁写的。**

═══ 为什么不是「把 414 条全重译一轮」═══
那样更省事，而且花不到一毛钱 —— 但会**把对的弄坏**：`非规范写法：섀시` 里的谚文
是被讨论的对象，重译一定把它译掉，句子就毁了。
`[[consult-two-models-on-rules]]` 记过同一个形状：兜底分支「其余降为 related」
照做＝**修好 0 弄坏 2,739**。⇒ 先逐条裁决，再只动裁定过的那些。

═══ prompt 怎么改 ═══
🔴 原 `SYS` 的规矩 5 早就写着「不要留韩文」、规矩 3 写着「只输出译文」——
   **这 21 条是滑脱，不是 prompt 缺口**。所以不重写 `SYS`（那会把已经对的 33,118 条
   赖以产生的口径也改掉），而是 **import 它再追加**四条针对实测失败的：
     · 不许原样返回原文（①那一类的签名）
     · 古典韩语/옛한글/汉韩混写也要译出意思（实测 181 条里 172 条译得对，能译）
     · 一个词不许一半汉字一半韩文（`된酱汤`／`李문세`／`궨党`）
     · 简体中文；不许出现 wikitext / 简繁转换标记

跑（在仓库根）：
    python3 -u ko/pipeline/retranslate_examples.py            # 跑批（21 条，约半分钱）
    python3 -u ko/pipeline/retranslate_examples.py --review    # 只看答案，逐条读
    python3 -u ko/pipeline/retranslate_examples.py --load --apply
    python3 -u ko/pipeline/retranslate_examples.py --fix-wikitext --apply   # 33129 那一条
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import asyncio
import json
import re
import sqlite3
import unicodedata

import dbtool
import ds_batch
import paths
import translate_examples as T      # 🔴 判据与 prompt 的家，只 import 不重写

f = lambda n: format(n, ",")
OUT = paths.WORK / "example_zh_retry"       # 🔴 新目录：别和上一轮的答案文件混
                                            #    （`[[answer-file-is-the-ledger]]`）

# ══════════════════════════════════════════════════════════════════
# 裁定名册。**每一条都是逐条读过的**，不是判据算出来的 ——
# 判据（含谚文 / 含拉丁）在这件事上必然太宽：414 个候选里 390 个是对的。
# 🔴 名册锁 id，理由写在值里。哪天有人想扩这张表，得先读那一条。
ROSTER = {
    # ── ① 韩语散文压根没译（规范化后译文 ≡ 原文）──
    559:   "语法型例句 `어서는 안 되다, 으면 안 되다` 原样返回",
    293:   "汉韩混写古文 `汝(여)는 其(기)處(처)를 未(미)知(지)하는가?` 原样返回",
    2532:  "시조（酒色을 삼가란…）原样返回；옛한글 ᄅᆞ 等旧字母",
    3007:  "同上，另一个词条挂着同一首 시조",
    5408:  "`심바람꾼은 두울이우.` 方言句原样返回",
    5659:  "옛한글 시조（님 ᄎᆞ즈라 天上으로…）原样返回",
    6722:  "`吹𠼱 츄라(吹𠼱)를 바로 불면…` 汉韩混写原样返回",
    6723:  "同上的另一种拼写（쥬라ᄅᆞᆯ）",
    14511: "近代散文（장챠 渾身勇力을 奮發하야…）原样返回",

    # ── ② 一个词被劈成两半 / 助词残留 / 乱码 ──
    27843: "`된장찌개` → **`된酱汤`**：一个词一半韩文一半汉字",
    32499: "`이문세`（人名 李文世）→ **`李문세`**：人名被劈开",
    14105: "`궨당`（济州话「亲戚」）→ **`궨党`**：被劈开",
    1601:  "`참바`（粗绳）→ **`参바`**：被劈开",
    415:   "`有의眞空`：助词 `의` 留在中文句里",
    37817: "`스스로` → **`ススス`**：输出成片假名乱码",
    4403:  "`강라인` → **`姜line`**：一半汉字一半拉丁",

    # ── ③ 外文词留在中文句里（不是「品牌/技术名保留」那种正当情形）──
    411:   "`爷爷 unexpectedly 去世了`：英文副词没译",
    8239:  "`无法 pinpoint 其中一个`：英文动词没译",
    19088: "`实施的 neighborhood forecast（洞域预报）`：英文短语没译",
    22600: "`出于 Kriegsmarine 的实际需求`：德文没译（该是「德国海军」）",

    # ── ④ 加了源文没有的内容 ──
    8641:  "译文说「是一首R&B歌曲」，而源文没提 R&B —— 编造（规矩 7）",
}

# 🔴 **有意不进名册**，各带理由。别哪天「顺手」加进去。
NOT_IN_ROSTER = {
    33129: "src=`zh-edition-simp` —— 简繁转换标记是**源头**写的，不是我们译的。"
           "⇒ 走 `--fix-wikitext`，改我们的出版文本，不送模型",
    36935: "src=`zh-edition-trad` —— 人名写成罗马字（`Youngsu和Yuseong`）是源头的"
           "**体例选择**不是错字。改它＝拿模型改源头内容 ⇒ 留着并记账",
    32504: "原文 `{{유의어|ko|` **根本不是例句**（wikitext 模板碎片）⇒ 例句层的账",
    37413: "原文 `[[저녁노을` 同上",
    32574: "原文 `{{ux|ko|쑥이 한 데 넣고` 模板包裹漏进引文，而**译文是对的** ⇒ 例句层的账",
    1473:  "`黑싸리／红싸리` 是花牌（화투）的牌名，与 `똥`/`땡` 同族术语，保留韩文"
           "**站得住**；改不改是术语体例问题，不是半翻译",
    3803:  "同上（`通常称为똥`）",
}

# ══════════════════════════════════════════════════════════════════
# 🔴 跑完一轮之后：**模型修好 14/21**，剩下 7 条在这里逐条手改。
#
# 为什么不再跑第二轮：那 4 条「没修好」里有 3 条是**一字未改**（`411` 的
# `unexpectedly`、`8239` 的 `pinpoint`、`5408` 整句原样返回）—— 同一个模型、
# 同一条规矩（规矩 11 明写「外文词要译成中文」）已经失效过两次，再跑一轮没有
# 新信息（`[[retry-must-converge-or-drop-loud]]`：重试要么收敛要么大声放弃）。
#
# ⭐ **每一条的用词都锚在我们自己库里的释义上**，不是我的语感：
#      된장찌개 → 大酱汤（`sense_gloss`）   참바 → 绳     궨당 → 亲族
#      두울 → 二                           심부름꾼 → 跑腿的
#    ⇒ 译文与词典本身一致，这是**可复查**的，而「我觉得该这么译」不是。
HAND = {
    411: ("听说昨晚隔壁家的爷爷意外去世了。",
          "模型两轮都留着 `unexpectedly` 不译。`뜻하지 않게` ＝ 意外地"),
    8239: ("我的兴趣非常多样，无法精准指出其中一项。",
           "模型两轮都留着 `pinpoint` 不译。`콕 집다` ＝ 精准指出"),
    5408: ("跑腿的是两个。",
           "整句原样返回两轮。`심바람꾼`＝`심부름꾼` 的方言形（库里：跑腿的），"
           "`두울`＝`둘` 的方言形（库里：二），`-이우` 是方言系词结尾"),
    14105: ("战胜朴风（朴風）的济州“궨당（亲族）的力量”（CBS NoCut News 2006年6月1日一篇报道的标题）。",
            "`궨党` 是被劈开的词。这里 `궨당` 是**新闻标题里被引用的济州话词**，"
            "保留原词＋括号里给中文（库里：亲族）比硬译更准 —— 词头本身就是它"),
    1601: ("⇒ 绳 (chamba)、绳索 (batjul)",
           "模型把 `참바` 音译成无意义的 `参巴`。库里 `참바` ＝ 绳"),
    27843: ("砂锅里的大酱汤咕嘟咕嘟地煮着。",
            "模型把 `된酱汤`（韩＋汉）换成 `doenjang 汤`（拉丁＋汉）—— **同一个毛病"
            "换了一种写法**，仍然违反规矩 10。库里 `된장찌개` ＝ 大酱汤"),
}

# 🔴🔴 **我自己判错的一条，如实记下来。**
#    `8641` 我判成「译文说是 R&B 歌曲而源文没提」—— 那是看**截断**的源文判的，
#    完整源文里写着 `알앤비(R&B) 곡`。**旧译文是对的**，新译文反而印出 `R&B（R&B）`。
#    ⇒ 这一条**不写库**，保持原样。
#    `[[measure-landing-not-source]]` 的同一个形状：证据看不全就别下判断。
MISJUDGED = {
    8641: "我判错了：源文确实写着 `알앤비(R&B) 곡`，旧译文没有编造。新译文更差，不采用",
}

EXTRA = """

🔴 补充规矩（这一轮是**重译已经译坏的那几条**，下面四条针对实测到的坏法）：
9.  **不许原样返回原文**。原文是古典韩语、옛한글（ᄅᆞ／ᄉᆞ 这类旧字母）、
    汉韩混写的近代文、시조、方言句时，**照样译出意思**；看不懂的部分按上下文直译，
    但整句不许照抄回来。
10. **一个词不许一半汉字一半韩文**。人名地名要么用通行汉字（이문세＝李文世），
    要么整词音译，**不许 `李문세`／`된酱汤`／`궨党` 这种半截**。
    同理不许一半汉字一半拉丁（`姜line`）。
11. 句子里的**外文词要译成中文**（英文 unexpectedly／pinpoint、德文 Kriegsmarine
    ＝德国海军）。⚠️ 例外：中文里本来就那么写的品牌与技术名保留原样
    （Windows／YouTube／DIY／UFO／DNA／K-pop／iPhone）。
12. 输出**简体中文**。不许出现维基语法：`zh-hans:`／`zh-hant:`／`-{ }-`／
    `[[ ]]`／`{{ }}`／`'''`。"""


def rows_for(con, ids):
    qs = ",".join("?" * len(ids))
    return con.execute(
        "SELECT e.id, e.word, e.text,"
        " (SELECT g.text FROM example_gloss g WHERE g.example_id=e.id AND g.lang='en' LIMIT 1),"
        " (SELECT g.text FROM example_gloss g WHERE g.example_id=e.id AND g.lang='zh' LIMIT 1)"
        " FROM example e WHERE e.id IN (%s) ORDER BY e.id" % qs, list(ids)).fetchall()


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[\s，,。.、；;：:！!？?“”\"'‘’（）()／/]+", "", s)


WIKI = re.compile(r"zh-han[st]\s*:|-\{|\}-|\[\[|\]\]|\{\{|\}\}|'''")
MIXED = re.compile(r"(?:[가-힣][一-鿿])|(?:[一-鿿][가-힣])")
KATAKANA = re.compile(r"[ァ-ヿ]")


def answers():
    got = {}
    for p in sorted(OUT.glob("*.jsonl")):
        for line in p.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            k, zh = d.get("id"), (d.get("zh") or "").strip()
            if not k or str(k).startswith("__") or not zh:
                continue
            try:
                got[int(k)] = zh
            except (TypeError, ValueError):
                pass
    return got


def review(con):
    """逐条读 —— **形状检查看不出「译错了」，只有人眼看得出**。"""
    got = answers()
    rows = rows_for(con, sorted(ROSTER))
    print("■ 名册 %d 条，回来 %d 条" % (len(ROSTER), len(got)))
    lost = set(ROSTER) - set(got)
    if lost:
        print("   🔴 没回来：%s" % sorted(lost))
    red = []
    for eid, w, text, en, old in rows:
        new = got.get(eid)
        if new is None:
            continue
        # 机器能判的四条，判完还是要人眼看
        flags = []
        if norm(new) == norm(text):
            flags.append("🔴 还是原样返回")
        if MIXED.search(new):
            flags.append("⚠️ 汉字与谚文相邻（可能是被讨论的对象，也可能仍是半翻译）")
        if WIKI.search(new):
            flags.append("🔴 wikitext 标记")
        if KATAKANA.search(new) and not KATAKANA.search(text or ""):
            flags.append("🔴 凭空出现片假名")
        if norm(new) == norm(old):
            flags.append("⚠️ 与旧译文一模一样（这一条没改动）")
        if flags:
            red.append((eid, flags))
        print("\n[%s] %s   ← %s" % (eid, w, ROSTER[eid]))
        print("   原文  %s" % (text or "").replace("\n", " ")[:150])
        print("   旧译  %s" % (old or "").replace("\n", " ")[:150])
        print("   新译  %s" % new.replace("\n", " ")[:150])
        for x in flags:
            print("   %s" % x)
    print("\n═══ 机器能判的部分 ═══")
    if red:
        for eid, flags in red:
            print("   [%s] %s" % (eid, "／".join(flags)))
    print("   %s %d/%d 条没有机器可判的问题"
          % ("✅" if not red else "⚠️", len(got) - len(red), len(got)))
    print("\n🔴 **这不等于译对了** —— 上面每一条都要人眼读过才许 --apply。")
    return got


def load(con, dry=True):
    got = answers()
    rows = rows_for(con, sorted(ROSTER))
    # 🔴 三个来源合成最终值，**优先级写明**：
    #    ① `MISJUDGED` —— 我判错的，一个字不写
    #    ② `HAND`      —— 模型没修好 / 改坏了的，手改（用词锚在库里的释义上）
    #    ③ 模型答案
    final, why = {}, {}
    for eid, *_ in rows:
        if eid in MISJUDGED:
            continue
        if eid in HAND:
            final[eid], why[eid] = HAND[eid][0], "手改"
        elif eid in got:
            final[eid], why[eid] = got[eid], "模型"
    n_hand = sum(1 for e in final if why[e] == "手改")
    print("■ 名册 %d 条 → 写库 %d 条（模型 %d ／ 手改 %d ／ 我判错不写 %d）"
          % (len(ROSTER), len(final), len(final) - n_hand, n_hand, len(MISJUDGED)))
    for eid in sorted(MISJUDGED):
        print("   ⚪ [%s] 不写：%s" % (eid, MISJUDGED[eid]))
    # 🔴 写之前**再过一遍机器可判的四条**：手改的也要过，别因为是我写的就免检
    bad = []
    src = {eid: text for eid, _w, text, _en, _old in rows}
    for eid, new in sorted(final.items()):
        if norm(new) == norm(src[eid]):
            bad.append((eid, "还是原样返回"))
        if WIKI.search(new):
            bad.append((eid, "wikitext 标记"))
        if KATAKANA.search(new) and not KATAKANA.search(src[eid] or ""):
            bad.append((eid, "凭空出现片假名"))
        # 🔴 判据是 `T.LATIN`，而且**必须带上后半句**「原文里没有」——
        #    第一版我只写了前半句，当场误伤两条手改：`1601` 的 `(chamba)`/`(batjul)`
        #    是源文括号里就有的罗马字，`14105` 的 `CBS NoCut News` 是通讯社名。
        #    `[[criteria-narrower-than-you-think]]` 的又一次：判据比它要描述的东西更宽。
        if T.LATIN.search(new) and not T.LATIN.search(src[eid] or ""):
            bad.append((eid, "译文里出现了原文没有的拉丁词"))
    if bad:
        for eid, x in bad:
            print("   🔴 [%s] %s" % (eid, x))
        raise SystemExit("🔴 %d 条过不了写前检查 —— 不写库" % len(bad))
    print("   ✅ 写前检查：%d 条全过（原样返回／wikitext／片假名／手改残留拉丁）" % len(final))
    upd = [(final[eid], eid) for eid in sorted(final)]
    if not upd:
        return
    if dry:
        print("（干跑。确认后 --apply）")
        return
    # 🔴 只改 `text`，**不动 `src`**：这些行的出处仍然是那个模型，
    #    改了 src 就等于说它们换了来源。重译是同一个来源的第二次作答。
    with dbtool.session("ko-k16-retranslate-examples", expect={}, invalidates=[]) as s:
        s.executemany(
            "UPDATE example_gloss SET text=? WHERE example_id=? AND lang='zh'", upd)
    print("\n═══ 写后回核 ═══")
    con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = 0
    for eid, new in sorted(final.items()):
        cur = con2.execute(
            "SELECT text FROM example_gloss WHERE example_id=? AND lang='zh'", (eid,)
        ).fetchone()
        if not cur or cur[0] != new:
            print("   🔴 [%s] 库里不是新译文" % eid)
            bad += 1
    n_zh = con2.execute("SELECT COUNT(*) FROM example_gloss WHERE lang='zh'").fetchone()[0]
    print("   %s 逐条回读 %d/%d 条对得上" % ("✅" if not bad else "🔴", len(upd) - bad, len(upd)))
    print("   ■ zh 译文总行数 %s（应当**没变** —— 这一轮是 UPDATE 不是 INSERT）" % f(n_zh))
    con2.close()
    if bad:
        raise SystemExit("🔴 回核对不上")


def fix_wikitext(con, dry=True):
    """`33129`：源头（中文维基）把简繁转换标记写进了正文。

    🔴 `[[source-typo-fix-ours-not-quote]]`：改**我们的出版文本**，
       引文（`example.text`）与证据层一个字不动。
    ⚠️ 取哪一支不是随手：这条译文整句是**繁体**，所以留 `zh-hant` 那一支才自洽。
    """
    eid = 33129
    cur = con.execute(
        "SELECT text FROM example_gloss WHERE example_id=? AND lang='zh'", (eid,)).fetchone()
    if not cur:
        print("🔴 查不到 %d 的 zh 行" % eid)
        return
    old = cur[0]
    # `zh-hans:A; zh-hant:B;` → B（本条整句繁体）
    new = re.sub(r"zh-hans:[^;]*;\s*zh-hant:([^;]*);", r"\1", old)
    print("■ [%d] 清简繁转换标记" % eid)
    print("   旧  %s" % old)
    print("   新  %s" % new)
    if WIKI.search(new):
        raise SystemExit("🔴 清完还有 wikitext 标记 —— 判据没覆盖住，别写")
    if new == old:
        raise SystemExit("🔴 一个字都没变 —— 正则没匹配上（别静默通过）")
    if dry:
        print("（干跑。确认后 --apply）")
        return
    with dbtool.session("ko-k16-fix-wikitext-marker", expect={}, invalidates=[]) as s:
        s.executemany("UPDATE example_gloss SET text=? WHERE example_id=? AND lang='zh'",
                      [(new, eid)])
    con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    got = con2.execute(
        "SELECT text FROM example_gloss WHERE example_id=? AND lang='zh'", (eid,)).fetchone()[0]
    con2.close()
    print("   %s 回读：%s" % ("✅" if got == new else "🔴", got))
    if got != new:
        raise SystemExit("🔴 回核对不上")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--fix-wikitext", action="store_true")
    ap.add_argument("--conc", type=int, default=8)   # 21 条，并发再高也没意义
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.fix_wikitext:
        fix_wikitext(con, dry=not a.apply)
        return
    if a.review:
        review(con)
        return
    if a.load:
        load(con, dry=not a.apply)
        return

    rows = rows_for(con, sorted(ROSTER))
    print("■ 名册 %d 条（逐条读过的裁定，不是判据算的）" % len(ROSTER))
    print("■ 有意不进名册 %d 条，理由写在 `NOT_IN_ROSTER` 里" % len(NOT_IN_ROSTER))
    assert len(rows) == len(ROSTER), "🔴 库里只找到 %d 条" % len(rows)
    # 🔴 名册里的每一行都必须是**我们译的**（model:*）。源头给的中文不许送模型改。
    for eid, *_ in rows:
        src = con.execute(
            "SELECT src FROM example_gloss WHERE example_id=? AND lang='zh'", (eid,)).fetchone()
        if not src or not (src[0] or "").startswith("model:"):
            raise SystemExit(
                "🔴 [%s] 的译文出处是 %r，**不是我们译的** —— 不许送模型改。\n"
                "   源头给的中文要走 `[[source-typo-fix-ours-not-quote]]` 那条路"
                % (eid, src[0] if src else None))
    print("■ 出处检查：%d 条全部是 model:* ✓" % len(rows))
    batches, meta = T.build([(eid, w, text, en) for eid, w, text, en, _old in rows])
    print("■ %d 批（每批 %d 条＋1 条定题）" % (len(batches), T.PER_BATCH))
    con.close()
    asyncio.run(ds_batch.run(T.SYS + EXTRA, batches, meta, OUT / "retry.jsonl",
                             mode="flash", conc=a.conc, thinking="disabled"))
    print("\n⇒ 下一步：`--review` 逐条人眼读，读过再 `--load --apply`")


if __name__ == "__main__":
    main()
