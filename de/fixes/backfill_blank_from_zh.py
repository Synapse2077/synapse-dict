#!/usr/bin/env python3
"""把中文版给的中文释义补到**空白页**上。de 版，2026-09-18。零模型调用、不花钱。

═══ 病灶：账按两版算，词从七版收 ═══
用户 2026-09-18 报「`Freunde in der Not gehen hundert auf ein Lot.` 没有详情页」。
回源查清：

    英文版切片   `…auf ein Lot`（**不带句点**，proverb，1 条义项）  ← 好的那一页
    德语版整包   这个串**一行都没有**
    中文版整包   `…auf ein Lot.`（**带句点**）+ senses[0].glosses = ["患难见真情"]

阶段 3「收词」是从**七个版**收的（de 736,097／en 60,537／zh 32,073／fr 20,690／
pt 1,902／it 1,354／es 505），而义项只从 **de 版和 en 版**收过 ——
中文版白给的那句中文，我们**收了词头、没收释义**。

🔴🔴 而回归闸 B5 给这 49,364 个空白页写的免责理由是
「①源头**两版** `forms` 里根本没有归属 45,119」——
**「两版」就是漏洞**：账按 de+en 两版算，词却是从七版收的。
`[[dont-say-source-lacks-what-we-skipped]]`：「源头没写」和「我们没抽」
被混成了一个数，于是一个**我们自己造成的缺口**顶着「源头没有」的名义躺了半个月。

═══ 落点已实测（全量非抽样，五版各扫一遍）═══

    zh 版  德语条目 172,286 ｜ 能补上我们空白页的  32,036   ← **本步只做这一档**
    fr 版           528,627 ｜                      9,406
    it 版            13,380 ｜                      1,481
    es 版             4,348 ｜                        484
    pt 版             4,801 ｜                        212
    ─────────────────────────────────────────────────────
    五版并集                                       42,636 / 49,364 ＝ 86.4%

🔴 **只做 zh 这一档，判据是语言不是数量。** fr/it/es/pt 版给德语词的释义是
**法语/意语/西语/葡语**（`Flachheit → Platitude, banalité.`），而
`[[gloss-three-languages]]` 定的是「释义只保留三语：中文＋英文＋本语言」——
它们上不了页，要用就得付费翻译，而且那是**译文的译文**，比中文版直给的低一档。
⇒ 那 10,600 条单独记账（DE_PLAN 欠账），不在本步。

═══ 繁简 ═══
中文版本身繁简混排，而库里两批付费翻译是纯简体 ⇒ 不转就是同一页两种字形。
**德语这边比日语简单**：日语那轮要保护 `【…】` 里被引用的**日文词形**
（`[[source-typo-fix-ours-not-quote]]`），而德语词是拉丁字母，`t2s` 本来就不动它
⇒ 全量转，不需要保护段。⚠️ `opencc` 的 `t2s` 不幂等，照 ja 的写法转到收敛。

═══ 顺带修掉用户报的那一条本身 ═══
7 个空白词形，**去掉句末标点之后就是一个已有的好页面**：

    Freunde in der Not gehen hundert auf ein Lot. → …auf ein Lot
    Not kennt kein Gebot. ／ Not macht erfinderisch. ／ der Apfel fällt nicht weit vom Stamm.
    So? → So ／ Was ist das? → Was ist das ／ pst! → pst

中文版给谚语条目标题带句末标点，英文版不带 —— **同一条谚语两个页面，一个是好的、
一个是空的，而搜索把两个都递出来**（`So?`/`pst!` 甚至进了预计算下拉表）。
⇒ 这 7 条**不补释义，直接并掉**：删空壳，只留好页面。
   已逐条核过它们在 entry/sense/sense_src/sense_relation/inflection/
   pronunciation/collocation/field_src 里**引用数全为 0**，删了不会留悬空。

跑（在仓库根）：
    python3 -u de/fixes/backfill_blank_from_zh.py            # 干跑 + 诊断
    python3 -u de/fixes/backfill_blank_from_zh.py --apply
    python3 -u de/pipeline/build_search_prefix.py --apply    # 删了词形，预计算表要重跑
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import gzip
import json
import random
import re
import sqlite3
from collections import Counter, defaultdict

import dbtool
import paths
from build import POS_MAP                                    # noqa: E402
from ingest_de_senses import is_real_sense                   # noqa: E402  判据只许一份

import opencc

_T2S = opencc.OpenCC("t2s")

# 句末标点：中文版给谚语条目的标题带，英文版不带。
TAIL_PUNCT = ".!?"

# ══════════════════════════════════════════════════════════════════
# 中文版的释义**前面粘着结构标记**，80.9%（25,917/32,049）的行都有。
# 🔴 白名单**逐条量过**才写进来，不许用「开头一个括号组就剥」那种宽判据：
#    实测 181 种前导标记，其中 157 种出现不到 10 次，而**多数是学科标签**
#    （`[植物]` `[医]` `(编程)` `(希腊神话)`）—— 那是**内容**，剥掉就是丢信息。
#    `[[criteria-narrower-than-you-think]]`：判据比它要描述的东西宽，剥了不该剥的。
#    同样地 `ABC 阿巴卡韦`／`BeO 氧化铍` 开头那截拉丁串**是释义的一部分**，不许剥。
#
# 逐条的实测数（全量非抽样，32,049 行）：
#   ① 性别 `〈阴〉〈阳〉〈中〉`        22,047 行，`pos_raw` **100% 是 noun**，零例外
#   ② 复数 `pl.<形式>`               1,435 行 —— `〈阴〉 pl.Ausstaffierungen 穿着，装备`
#   ③ 词性缩写（带点/不带点）         2,839 + 33 行；其中 503 行 `pos_raw='unknown'`，
#                                    这个标记是它**唯一的词性信号** ⇒ 用它补
#   ④ 冠词 `der/die/das` 开头           16 行 —— 也是性别
#   ⑤ 坏模板 `{{{1}}}`                 66 行，整条就是它
#   ⑥ `==章节==` 整页正文漏进来         15 行
#   ⑦ 「X的变格形式」型指针              17 行
# ══════════════════════════════════════════════════════════════════
# 性别：`〈阴〉` 粘在中文前面是**结构**不是释义 —— 库里别处的性别是徽章，
#      只有这一批会印成「〈阴〉 电汇」。抽进 `sense.gender`（服务层 `sensesOf` 读这列）。
GENDER_MARK = {"〈阴〉": "f", "〈阳〉": "m", "〈中〉": "n"}
GENDER_ART = re.compile(r"^(der|die|das)\s+(?=[一-鿿①-⑳\[【(（])")
_ART_GENDER = {"der": "m", "die": "f", "das": "n"}
# 复数形式。**整个 `pl.<形式>` 一起剥** —— 只剥 `pl.` 会把德语复数留在中文最前面
#   （`Ausstaffierungen 穿着，装备`），那正是抽样反验第二轮逮到的残留。
#   ⚠️ 形式本身**不写进 `dict.plural`**：实测有 `Abschaetzern`（三格复数、ae 改写）
#      这类，它不是「复数」这一格该放的东西，编一个进去比空着坏。
#      源头原文整条躺在 `sense_src` 里，一个字没丢（`[[two-layer-sense-model]]`）。
PLURAL_MARK = re.compile(r"^(?:pl|Pl|PL)\.\s*[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]*\s*")
# 词性缩写。带点与不带点两种写法都实测到了。
POS_MARK = {
    "adj.": "adj", "adv.": "adv", "v.": "v", "vt.": "v", "vi.": "v", "vr.": "v",
    "(vt)": "v", "(vi)": "v", "n.pr.": "name", "n.": "n", "pron.": "pron",
    "int.": "intj", "interj.": "intj", "pat.": None, "pl.": "n", "Pl.": "n", "PL.": "n", "(pl)": "n", "{pl}": "n",
    "fpl.": "n", "mpl.": "n", "npl.": "n",
    # 语法标记，不是词性也不是释义：`unz.`＝unzählbar 不可数，`relf.`＝源头把
    # refl.（反身）拼错了。**照收不改源头的拼写**，只是不让它上页。
    "unz.": None, "relf.": None, "refl.": None,
}
POS_BARE = {"adj": "adj", "adv": "adv", "vt": "v", "vi": "v", "vr": "v",
            "Num": "num", "Pl": "n", "pl": "n"}
# 🔴 「后面跟着中文」这个先行断言**不能只写汉字**：实测 `adj ①各种各样`、
#    `vi ①…`、`n. [技]…` —— 圈号和方括号开头的同样是释义正文，漏掉它们
#    就等于这几十条的标记剥不掉（判据比它要描述的东西窄的那一面）。
AFTER = r"[一-鿿①-⑳\[【(（]"
POS_BARE_RE = re.compile(r"^(%s)[\s.]+(?=%s)"
                         % ("|".join(sorted(POS_BARE, key=len, reverse=True)), AFTER))
# 变格词尾。源头写成 `〈阴〉 -en 传染危险` / `〈阳〉 pl.-e 煎，熬` ——
# `-en`／`-e` 是**词尾**不是释义。实测 146 行（en 65／e 31／n 25／s 25）。
# ⚠️ 判据要求**带那个连字符**：光写 `^(en|e|n|s)\s` 会误伤以这些字母开头的正常词。
ENDING_MARK = re.compile(r"^-(?:e|n|en|s|es|er|ns|nen|se|ien)(?=[\s.,]|$)[\s.,]*")
# 剥完标记后**留在最前面的标点**（`.[医]异位的`／`，流水线`／`..-e 仲裁条约`）。实测 5 行。
LEAD_PUNCT = re.compile(r"^[\s.,;:，。；：、\-]+")
# 坏掉的 wiki 模板参数：整条就是它，剥完变空 ⇒ 由「清完没东西」那条丢掉。
JUNK_MARK = ("{{{1}}}",)
# `==章节==`：中文版整页正文漏进了 `glosses`（`Maracaibo` 后面跟着整段西班牙语节）。
# ⚠️ 其中 3 行截断后只剩词头本身（`Casio` 的中文「卡西欧」躺在 `==== 翻译 ====`
#    那张 wiki 列表里）—— **不去解析那张列表**，3 行按「缺」丢掉。
SECTION = re.compile(r"={2,}")
# **指针不是释义。** 中文版把变格形式写成中文散文（`Adolph的变格形式`），
# `is_real_sense` 的 `form_of`/`alt_of` 标签在中文版上是空的，挡不住它。
# de 的阶段 2a 专门做过「7,739 个词形从只有一句假的『X 的 变形』变成有真义项」——
# 现在把同样的句子当**释义**灌回去，是把那一步撤销。⇒ 整条丢掉；它们该走
# `inflection`/`sense_relation`（本步不做，记账）。
# ⚠️ 判据**整串锚定**，不许写成「含『的变格形式』」：那会误伤正常释义里恰好出现该词的情况。
# 🔴 中文版里**混着英文/德语释义**（`Ankergrund → anchorage ground`、`vgl → vergleiche`）。
#    实测 71 行（0.22%）一个汉字都没有。**不收**：`lang` 该标 en 还是 de 分不出来，
#    而标错语言是**错**，丢掉只是**缺**（`docs/FRAMEWORK.md`：错比缺更伤权威）。
#    要用得先判语种 ⇒ 记账，不在本步。
HAS_CJK = re.compile(r"[一-鿿㐀-䶿]")
# 🔴 **以冒号结尾 ＝ 把小标题当定义**（`星级酒店，如：`／`…的性质，形式：`）——
#    中文版把例子放在冒号后面的另一个结构里，收过来就只剩个引子。
#    de 的收尾单 C38 已经把这类清过一轮，本步导入又带回来 3 条（账的闸当场逮到）。
#    ⇒ 砍掉末尾那个引子小句；砍完没东西剩就整条丢。
#    ⚠️ 只在**整串以冒号收尾**时动手，冒号在中间的（`比喻：…`）一个字不碰。
TRAIL_COLON = re.compile(r"(?:[，,、]\s*[^，,、。；;：:]{0,10})?[：:]\s*$")
FORM_OF = re.compile(
    r"^.+?的(变格形式|变位形式|复数形式|复数|比较级|最高级|分词|过去式|现在分词"
    r"|过去分词|阴性形式|阳性形式|中性形式|指小形式|变体|另一种写法|缩写)[。.]?$")


def clean_gloss(g, word):
    """→ (中文, 性别 or None, 词性 or None)。清不出东西返回 (None, …)。"""
    gender = pos = None
    s = SECTION.split(g, 1)[0].strip()
    changed = True
    while changed:
        changed = False
        for mark, val in GENDER_MARK.items():
            if s.startswith(mark):
                gender, s, changed = gender or val, s[len(mark):].strip(), True
                break
        if changed:
            continue
        m = GENDER_ART.match(s)
        if m:
            gender, s, changed = gender or _ART_GENDER[m.group(1)], s[m.end():].strip(), True
            continue
        m = PLURAL_MARK.match(s)
        if m:
            pos, s, changed = pos or "n", s[m.end():].strip(), True
            continue
        m = ENDING_MARK.match(s)
        if m:
            pos, s, changed = pos or "n", s[m.end():].strip(), True
            continue
        for mark, val in POS_MARK.items():
            if s.startswith(mark):
                pos, s, changed = pos or val, s[len(mark):].strip(), True
                break
        if changed:
            continue
        m = POS_BARE_RE.match(s)
        if m:
            pos, s, changed = pos or POS_BARE[m.group(1)], s[m.end():].strip(), True
            continue
        for mark in JUNK_MARK:
            if s.startswith(mark):
                s, changed = s[len(mark):].strip(), True
                break
    s = LEAD_PUNCT.sub("", s).strip()
    while s.endswith(("：", ":")):
        cut = TRAIL_COLON.sub("", s).strip()
        if cut == s:
            s = s[:-1].strip()
        else:
            s = cut
    if not s or s == word or FORM_OF.match(s) or not HAS_CJK.search(s):
        return None, gender, pos
    return s, gender, pos


def t2s(s, cap=6):
    """繁→简，转到收敛。🔴 `opencc` 的 `t2s` 不幂等（ja 那轮实测跑一遍还剩 2 条会变）。

    德语这边比日语简单：ja 那轮要保护 `【…】` 里被引用的**日文词形**
    （`[[source-typo-fix-ours-not-quote]]`），而德语词是拉丁字母，`t2s` 本来就不动它。
    """
    for _ in range(cap):
        out = _T2S.convert(s)
        if out == s:
            return s
        s = out
    raise RuntimeError("opencc 转换 %d 轮仍不收敛：%r" % (cap, s[:60]))


def _assert_de():
    assert paths.DB.name == "synapse-dict-de.sqlite", "🔴 paths 不是 de 的：%s" % paths.DB


def blank_pages(con):
    """判据与回归闸 `_blank_pages` 同口径：无义项、无变形、无老 `exchange` 指针。"""
    return {w: i for i, w in con.execute(
        "SELECT id, word FROM dict d"
        " WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
        "   AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)"
        "   AND COALESCE(d.exchange,'')=''")}


def punct_dupes(con):
    """→ [(空壳 id, 空壳词形, 好页面 id, 好页面词形)]。

    判据：**去掉句末标点之后恰好等于一个有义项的词形**。
    ⚠️ 不写成「含标点的空白页」—— 那是 79 条，其中 72 条（`z.Z.`/`Pech gehabt!`）
       并没有一个好页面在对面，它们是正经的独立词条，只是还没有释义。
       判据必须问「**对面有没有人**」，不是「长什么样」。
    """
    return con.execute(
        "SELECT b.id, b.word, g.id, g.word FROM dict b JOIN dict g"
        "  ON g.word = rtrim(b.word, '" + TAIL_PUNCT + "')"
        " WHERE b.word <> g.word"
        "   AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=b.id)"
        "   AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=b.id)"
        "   AND COALESCE(b.exchange,'')=''"
        "   AND EXISTS(SELECT 1 FROM sense s WHERE s.word_id=g.id)").fetchall()


REFERRERS = ("entry", "sense", "sense_src", "sense_relation", "inflection",
             "pronunciation", "collocation", "field_src")


def dangling(con, ids):
    """删词形前逐表核引用。→ {表: 行数}，非空就不许删。"""
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    out = {}
    for t in REFERRERS:
        n = con.execute("SELECT count(*) FROM %s WHERE word_id IN (%s)" % (t, ph),
                        ids).fetchone()[0]
        if n:
            out[t] = n
    return out


def scan(targets):
    """扫中文版 → {词形: [(中文, pos_raw, 第几条)]}。只保留 `targets` 里的词形。"""
    out = defaultdict(list)
    stat = Counter()
    with gzip.open(paths.DUMPS / "zhwiktionary.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            if '"de"' not in line:                 # 便宜预筛，避免整行 JSON 解析
                continue
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            if e.get("lang_code") != "de":
                continue
            stat["中文版德语条目"] += 1
            w = (e.get("word") or "").strip()
            if w not in targets:
                continue
            pos_raw = e.get("pos") or "unknown"
            for i, s in enumerate(e.get("senses") or []):
                if not is_real_sense(s):
                    stat["跳过·指针义项（form_of/alt_of）"] += 1
                    continue
                g = (s.get("glosses") or [""])[0].strip()
                if not g:
                    continue
                out[w].append((g, pos_raw, i))
                stat["收·义项"] += 1
    return out, stat


def move_gender(apply):
    """把已落库的 `sense.gender` 搬到 `dict.gender`（一次性）。

    🔴 第一版把中文版的 `〈阴〉〈阳〉〈中〉` 抽进了 `sense.gender` —— 列是存在的，
       写进去也不报错，**而 de 的展示层根本不读那一列**（它读 `dict.gender`）。
       数据在库里、页面上看不见，是「被绕过」那一类里最安静的一种。
       ⇒ 搬到 `dict.gender` 并把 `sense.gender` 清回 NULL（de 的约定：性别是词条级的）。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT DISTINCT s.word_id, s.gender FROM sense s JOIN sense_src x"
        " ON x.sense_id = s.id WHERE x.src_ref LIKE 'kk-zh:%' AND s.gender IS NOT NULL"
    ).fetchall()
    clash = con.execute(
        "SELECT count(*) FROM (SELECT s.word_id FROM sense s JOIN sense_src x"
        " ON x.sense_id = s.id WHERE x.src_ref LIKE 'kk-zh:%' AND s.gender IS NOT NULL"
        " GROUP BY s.word_id HAVING count(DISTINCT s.gender) > 1)").fetchone()[0]
    taken = con.execute(
        "SELECT count(DISTINCT s.word_id) FROM sense s JOIN sense_src x"
        " ON x.sense_id = s.id JOIN dict d ON d.id = s.word_id"
        " WHERE x.src_ref LIKE 'kk-zh:%' AND s.gender IS NOT NULL"
        " AND d.gender IS NOT NULL").fetchone()[0]
    con.close()
    print("   要搬的性别            %9s" % format(len(rows), ","))
    print("   同一词形内性别打架    %9s（须 0）" % clash)
    print("   `dict.gender` 已有值  %9s（须 0，否则不许覆盖）" % taken)
    assert clash == 0 and taken == 0, "🔴 有冲突，先看清楚"
    if not apply:
        print("\n(干跑。确认后 --move-gender --apply)")
        return
    with dbtool.session("de-move-gender-to-dict", expect={
            "gender": len(rows), "gender_src": len(rows)}) as s:
        s.executemany("UPDATE dict SET gender=?, gender_src='zh-edition' WHERE id=?",
                      [(g, w) for w, g in rows])
        s.execute("UPDATE sense SET gender=NULL WHERE id IN"
                  " (SELECT sense_id FROM sense_src WHERE src_ref LIKE 'kk-zh:%')")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = con.execute(
        "SELECT count(*) FROM sense s JOIN sense_src x ON x.sense_id=s.id"
        " WHERE x.src_ref LIKE 'kk-zh:%' AND s.gender IS NOT NULL").fetchone()[0]
    got = con.execute(
        "SELECT count(*) FROM dict WHERE gender_src='zh-edition'").fetchone()[0]
    con.close()
    print("   %s sense.gender 已清空（剩 %d）" % ("✅" if left == 0 else "🔴", left))
    print("   %s dict.gender 拿到 %s 个" % ("✅" if got == len(rows) else "🔴", format(got, ",")))
    assert left == 0 and got == len(rows)


def recheck(apply):
    """判据改了之后，拿**同一个 `clean_gloss`** 回洗已落库的那批。

    🔴 生成侧改了、落库的行不改 ＝ 修了一半（`[[replay-scripts-undo-fixes]]` 的反面）。
       而两边各写一套清洗逻辑 ＝ 闸在报自己的 bug ⇒ 这里 import 的就是上面那一个函数。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT g.rowid, g.sense_id, g.text, d.word FROM sense_gloss g"
        " JOIN sense s ON s.id = g.sense_id JOIN dict d ON d.id = s.word_id"
        " JOIN sense_src x ON x.sense_id = g.sense_id"
        " WHERE g.lang='zh' AND x.src_ref LIKE 'kk-zh:%'").fetchall()
    con.close()
    fix, drop = [], []
    for rid, sid, txt, word in rows:
        new, _g, _p = clean_gloss(txt, word)
        if new is None:
            drop.append((rid, sid, txt))
        elif t2s(new) != txt:
            fix.append((t2s(new), rid, txt))
    print("   已落库的这批       %9s" % format(len(rows), ","))
    print("   判据改了之后要改的 %9s" % format(len(fix), ","))
    print("   清完没东西、要删的 %9s" % format(len(drop), ","))
    for n, _r, old_t in fix[:8]:
        print("      %r → %r" % (old_t[:40], n[:40]))
    for _r, _s, t in drop[:5]:
        print("      删 %r" % t[:40])
    if not apply:
        print("\n(干跑。确认后 --recheck --apply)")
        return
    if not fix and not drop:
        print("   没有要改的。")
        return
    with dbtool.session("de-recheck-zh-glosses", expect={
            "#sense": -len(drop), "#sense_gloss": -len(drop),
            "#sense_src": -len(drop)}) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE rowid=?",
                      [(n, r) for n, r, _o in fix])
        for _r, sid, _t in drop:
            s.execute("DELETE FROM sense_gloss WHERE sense_id=?", (sid,))
            s.execute("DELETE FROM sense_src WHERE sense_id=?", (sid,))
            s.execute("DELETE FROM sense WHERE id=?", (sid,))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = con.execute(
        "SELECT count(*) FROM sense_gloss WHERE lang='zh'"
        " AND (TRIM(text) LIKE '%：' OR TRIM(text) LIKE '%:')").fetchone()[0]
    con.close()
    print("   %s 中文释义以冒号结尾的还剩 %d（C38 要求 0）"
          % ("✅" if left == 0 else "🔴", left))
    assert left == 0


def main():
    _assert_de()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rescan", action="store_true", help="忽略缓存，重扫中文版整包")
    ap.add_argument("--recheck", action="store_true",
                    help="拿当前的 clean_gloss 回洗**已落库**的那批（判据改了之后用）")
    ap.add_argument("--move-gender", action="store_true", dest="move_gender",
                    help="把已落库的 sense.gender 搬到 dict.gender（一次性）")
    a = ap.parse_args()

    if a.move_gender:
        return move_gender(a.apply)
    if a.recheck:
        return recheck(a.apply)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    blanks = blank_pages(con)
    dupes = punct_dupes(con)
    dup_ids = [r[0] for r in dupes]
    bad = dangling(con, dup_ids)
    con.close()

    print("   空白页词形            %9s" % format(len(blanks), ","))
    print("   句末标点重复（并掉）  %9s" % format(len(dupes), ","))
    for _bid, bw, _gid, gw in dupes:
        print("      %-46s → %s" % (bw, gw))
    print("   它们的悬空引用        %9s %s" % (len(bad), bad or "（无，可删）"))
    assert not bad, "🔴 这些词形还被引用着，不许删：%s" % bad

    # 并掉的那批不参与补释义
    targets = {w for w in blanks if w not in {r[1] for r in dupes}}
    # 扫一遍 215 MB 要两分钟，而判据要改好几轮 ⇒ 落盘缓存，`--rescan` 强制重扫。
    cache = paths.WORK / "zh_blank_scan.json"
    if cache.exists() and not a.rescan:
        raw = json.loads(cache.read_text(encoding="utf-8"))
        found = {w: [tuple(x) for x in v] for w, v in raw["found"].items() if w in targets}
        stat = Counter(raw["stat"])
        print("   （用缓存 %s，要重扫加 --rescan）" % cache.name)
    else:
        found, stat = scan(targets)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"found": found, "stat": dict(stat)},
                                    ensure_ascii=False), encoding="utf-8")
    for k, v in stat.most_common():
        print("   %-28s %9s" % (k, format(v, ",")))

    # ── 组装（清洗在这里做，干跑与真跑走**同一段代码**，免得两套判据）──
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    sid0 = con.execute("SELECT max(id) FROM sense").fetchone()[0]
    con.close()

    sid = sid0
    senses, glosses, srcs = [], [], []
    dropped, trad_n, gen_n, pos_n, sec_n, multi_n = [], 0, 0, 0, 0, 0
    ref_seq = Counter()
    gender_of = {}
    for w in sorted(found):
        wid = blanks[w]
        seen = set()
        rank = 0
        for g, pos_raw, i in found[w]:
            if "==" in g:
                sec_n += 1
            # 🔴 **换行 ＝ 源头把好几条义项塞进了一个字符串**
            #    （`vt.截住，抓住\nvi.中断 迅速弹开`）。实测 78 行、拆开多出 126 条义项。
            #    不拆的话页面上一条义项里挂着两个词性，而每一半各自是完整的释义。
            parts = [x for x in g.split("\n") if x.strip()] or [g]
            if len(parts) > 1:
                multi_n += 1
            got = False
            for part in parts:
                zh, gender, pos_mark = clean_gloss(part, w)
                if zh is None:
                    continue
                got = True
                simp = t2s(zh)
                if simp != zh:
                    trad_n += 1
                if gender:
                    gen_n += 1
                pos = POS_MAP.get(pos_raw, pos_raw)
                if pos in (None, "unknown") and pos_mark:
                    pos = pos_mark
                    pos_n += 1
                if simp in seen:      # 同一个词形被中文版拆成多条、中文一样 ⇒ 只留一条
                    continue
                seen.add(simp)
                rank += 1
                sid += 1
                # 🔴 **性别写 `dict` 不写 `sense`。** de 的性别是**词条级**的
                #    （`der/das/die Band` 是三个词条），`sense.gender` 那一列的建表注释
                #    自己写着「本步全 NULL」，而 `GermanEntryView` 只读 `entry.gender`
                #    （＝`dict.gender`）⇒ 写进 `sense.gender` 等于数据在库里、读者看不见。
                #    第一版就是这么错的，靠渲染成品逮到（`[[fix-regression-and-gate]]` 第二种机制）。
                if gender:
                    gender_of.setdefault(wid, gender)
                senses.append((sid, wid, rank, pos, None))
                glosses.append((sid, "zh", "equivalent", 0, simp, "zh-edition"))
                # 🔴 源坐标要**认得出是哪一片**：一条 gloss 拆成多条义项时它们共用
                #    `(词形, 词性, 第几条)`，直接拿它当 `src_ref` 会撞唯一约束
                #    —— 第一次 `--apply` 正是这么红的（闸拦住并 rollback 了）。
                #    同理，同一个词形在中文版可能有两个同词性条目，`i` 会从 0 重来
                #    ⇒ 再挂一个该键的出现序号。
                key = "kk-zh:%s:%s#%d" % (w, pos_raw, i)
                ref_seq[key] += 1
                srcs.append((wid, sid, "zh-edition",
                             "%s.%d" % (key, ref_seq[key]), "zh", g, None))
            if not got:
                dropped.append((w, g))
            continue

    filled = len({r[1] for r in senses})
    print("\n   中文版给的义项行      %9s" % format(sum(len(v) for v in found.values()), ","))
    print("   清洗后要写的义项行    %9s" % format(len(senses), ","))
    print("   ⇒ 真能填上的空白页    %9s" % format(filled, ","))
    print("   繁转简                %9s" % format(trad_n, ","))
    print("   抽出性别进 sense      %9s" % format(gen_n, ","))
    print("   用词性缩写补 unknown  %9s" % format(pos_n, ","))
    print("   截掉 ==章节== 的      %9s" % format(sec_n, ","))
    print("   一条拆成多条义项的    %9s" % format(multi_n, ","))
    print("   清完没东西可写、丢掉  %9s" % format(len(dropped), ","))
    for w, g in dropped[:6]:
        print("      %-26s %r" % (w[:26], g[:56]))

    # 🔴 落库前自己先查唯一性 —— 让约束在**写之前**说话，而不是写到一半 rollback。
    refs = [r[3] for r in srcs]
    dup_ref = len(refs) - len(set(refs))
    print("   src_ref 重复（须为 0）%9s" % dup_ref)
    assert dup_ref == 0, "🔴 src_ref 有 %d 个重复" % dup_ref

    random.seed(7)
    idx = random.sample(range(len(senses)), min(16, len(senses)))
    dbtool.sample_check(
        [(next(x for x in sorted(found) if blanks[x] == senses[k][1]),
          glosses[k][4], senses[k][3] or "-", senses[k][4] or "-") for k in idx],
        14, ("空白页词形", "清洗后的中文", "词性", "性别"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    print("\n■ 将写入 sense %s ／ sense_gloss %s ／ sense_src %s ／ 删 dict %s"
          % (format(len(senses), ","), format(len(glosses), ","),
             format(len(srcs), ","), len(dup_ids)))

    # 🔴 `pos` 必须显式声明。de 的 `dict.pos` **每一行都非空**（1,202,933/1,202,933）
    #    ⇒ 删 7 行词形，它的非空计数就跟着掉 7。第一次 `--apply` 正是栽在这里：
    #    数据全对，闸照样红 —— 它问的是「**你有没有预料到**」，不是「数据对不对」。
    with dbtool.session("de-backfill-blank-from-zh", expect={
            "__rows__": -len(dup_ids), "pos": -len(dup_ids),
            "gender": len(gender_of), "gender_src": len(gender_of),
            "#sense": len(senses), "#sense_gloss": len(glosses),
            "#sense_src": len(srcs)}) as s:
        s.executemany("UPDATE dict SET gender=?, gender_src='zh-edition'"
                      " WHERE id=? AND gender IS NULL",
                      [(g, w) for w, g in gender_of.items()])
        s.executemany("INSERT INTO sense (id,word_id,rank,pos,gender) VALUES (?,?,?,?,?)",
                      senses)
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src)"
                      " VALUES (?,?,?,?,?,?)", glosses)
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags)"
                      " VALUES (?,?,?,?,?,?,?)", srcs)
        # 预计算下拉表里也有它们（`So?`/`pst!` 各 2 行）⇒ 一起删，之后重跑 build_search_prefix
        s.executemany("DELETE FROM search_prefix WHERE word_id=?", [(i,) for i in dup_ids])
        s.executemany("DELETE FROM dict WHERE id=?", [(i,) for i in dup_ids])

    # ── 回核：写入列与读取路径各查一次（`[[it-regression-gate]]`）──
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("空白页真的降下来了", len(blank_pages(con)) == len(blanks) - len(found) - len(dupes)),
        ("新义项都挂在存在的词形上",
         q("SELECT count(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id"
           " WHERE d.id IS NULL") == 0),
        ("证据行都挂上了义项",
         q("SELECT count(*) FROM sense_src x LEFT JOIN sense s ON s.id=x.sense_id"
           " WHERE s.id IS NULL") == 0),
        ("出版层没有繁体残留（新写的这批）",
         all(t == t2s(t) for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE src='zh-edition' AND lang='zh'"))),
        ("并掉的 7 条不在了，好页面还在",
         q("SELECT count(*) FROM dict WHERE word='Freunde in der Not gehen hundert auf ein Lot.'") == 0
         and q("SELECT count(*) FROM dict WHERE word='Freunde in der Not gehen hundert auf ein Lot'") == 1),
        ("没有词形被删成悬空引用", not dangling(con, dup_ids)),
    ]
    con.close()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    assert all(ok for _, ok in checks), "🔴 回核不过"
    print("\n🔴 下一步必须跑：python3 -u de/pipeline/build_search_prefix.py --apply")


if __name__ == "__main__":
    main()
