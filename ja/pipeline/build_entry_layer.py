#!/usr/bin/env python3
"""阶段 1：`entry` 词条层 + `sense_src` 证据层。2026-09-15。

═══ 主键就是前六门那套，读音**不进键** ═══
`src_ref = kk-ja:<word_src>:<pos_raw>:<etym_no>:<seq>`

实测（`JA_PLAN` §二.1）：`(词形,词性,etym_no)` 单独就分开 85.5% 的多条目组，加 `seq` 归零。
🔴 **读音是属性不是主键分量**：3,951 条 entry 一条里就有 ≥2 个读音
（`爺` = じい/じじ/じじい）。多值的东西当不了键。

═══ 读音抽取：三个来源，一个不能用 ═══
    head_templates 里**第一个纯假名的数字位参数**   69,997 条   ← 权威
    forms[canonical].ruby 拼起来                   8,322 条   ← 兜底
    纯假名词头 = 它自己                                        ← 同一性
    🔴 sounds[].other                              **一条都不用**

最后那条是回源裁决的结果（两位专家意见相反）：`other` 与权威读音都在的 43,096 条里
**只有 66.3% 一致**；不一致的 14,516 条中 **91.7% 是长音改写**（みょうにち→みょーにち、
ちょう→ちょー），而 `馬` 的 `other` 是 `[ùmáꜜ]` —— 那根本是**声调标记不是读音**。
⇒ 它混着音位改写和声调标记两种东西，进读音列就是往库里写错的假名。

⚠️ `args["1"]` **不是**读音字段：34,993 条那里装的是词性名（`proper` 18,060 /
   `adverb` 1,789 / `suffix` 625…），`ja-pos` 的读音在 `args["2"]`。
   判据必须是「第一个**纯假名**的数字位参数」，不是「第一个数字位参数」。

═══ `kanji_grade` 在 `senses[].categories`，不在顶层 `categories` ═══
顶层只有约 300 条；`senses[].categories` 有 jōyō 3,637 / kyōiku 1,692 /
hyōgai 13,023 / jinmeiyō 1,159。
🔴 **绝不从 `forms[].form` 取**：那里带等级字样的 898 条**全被打上了 `romanization` 标签**，
   任何通用的罗马字抽取器都会把 "Jōyō kanji" 当成 898 个汉字的罗马字写进库。

跑（在仓库根）：
    python3 -u ja/pipeline/build_entry_layer.py
    python3 -u ja/pipeline/build_entry_layer.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import re
import sqlite3
import unicodedata

import dbtool
import paths
from pipeline.build import NOT_A_WORD, norm_ja, is_pointer_sense

KANA_ONLY = re.compile(r"^[ぁ-ゖァ-ヺー%]+$")
HAS_KANJI = re.compile(r"[一-鿿]")
GRADES = (("jōyō", "常用"), ("kyōiku", "教育"), ("jinmeiyō", "人名用"), ("hyōgai", "表外"))

# 展示用词性。🔴 `character` 不走共享的 `POS_LABELS`（那里 `character: '字母'`，
#    对日语的「犬」「馬」是错的），日语的展示名由 `ja` 自己的表给 —— 见 JA_PLAN §三①。
POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv", "name": "name",
    "pron": "pron", "prefix": "pref", "suffix": "suf", "affix": "affix",
    "particle": "part", "conj": "conj", "intj": "intj", "num": "num",
    "counter": "counter", "adnominal": "adnom", "phrase": "phr",
    "proverb": "prov", "character": "kanji", "syllable": "kana",
    "symbol": "sym", "punct": "punct", "combining_form": "comb",
    "root": "root", "infix": "infix", "postp": "postp",
    # 🔴 2026-09-16 补六个：**日语版/中文版才出现的取值**。
    #    它们漏掉的后果不是"少个标签"，而是**同一个概念在库里有两个码** ——
    #    `prov` 218 / `proverb` 99、`adnom` 96 / `adnominal` 23、`kana` 789 / `syllable` 4、
    #    `sym` 100 / `symbol` 37 —— 展示层会把它们分成两组，其中一组印英文。
    #    ⚠️ 根因是 `intake_edition_words` 里**另写了一张更短的 POS_MAP**
    #       （`[[refactor-mindset-code-quality]]`：同一个映射表两份，改一份另一份静默漂开）。
    #       那一份已删，改成 import 本表。
    # ⚠️ `adj_noun` 只在**局部那张表**里有、正本没有。合并两张表必须**两个方向都查**：
    #    只把正本往局部补，会把形容动词（ナ形容词）1,137 条弄丢成原始码。
    "adj_noun": "adj",
    "abbrev": "abbr",          # 4R／JIS／うなどん（「うなぎどんぶり」の略）
    "classifier": "counter",   # キロバール／デシグラム＝单位，与 counter 同一类
    "proverb": "prov", "adnominal": "adnom", "syllable": "kana", "symbol": "sym",
    "romanization": "romaji",  # 阶段 0 从英文版剔了 32,062 条，中文版漏进来 31 条
}


def reading_of(o):
    """→ (假名读音, 来源)。拿不到返回 (None, None)。判据见文件头。"""
    for h in (o.get("head_templates") or []):
        args = h.get("args") or {}
        for k in sorted((k for k in args if str(k).isdigit()), key=int):
            v = str(args[k] or "")
            if v and KANA_ONLY.match(v):
                return v, "head_templates"
    for f in (o.get("forms") or []):
        if "canonical" in (f.get("tags") or []) and f.get("ruby"):
            return "".join(k for _, k in f["ruby"]), "ruby"
    w = o.get("word") or ""
    if w and KANA_ONLY.match(w):
        return w, "identity"          # 纯假名词头：读音就是它自己
    return None, None


def hist_kana_of(o):
    for h in (o.get("head_templates") or []):
        v = (h.get("args") or {}).get("hhira")
        if v:
            return str(v)
    return None


# 🔴 **被标成 `romanization` 却其实是字种等级的那批。**
#    源头把 "Jōyō kanji" / "Third grade kyōiku kanji" 这类标签也放进 `forms[]`
#    并打上 `tags:["romanization"]` —— 实测 **1,739 条 / 15 种**。
#    ⚠️ 我在本文件开头写了这条警告，然后**照样踩了**：写了警告没写守卫，
#       干跑抽样里 `常` 的罗马字是 "Fifth grade kyōiku kanji"。
#       ⇒ `[[lesson-must-become-mechanism]]`：交付物是一道会自己响的东西，不是一句提醒。
#    ⚠️ 判据要**带词界空格**：`漢字` 的真罗马字就是单词 `kanji`，
#       只查「含不含 kanji」会把它误伤 —— 又一次「判据比它要描述的东西更宽」。
#    ⚠️ 不能只挡 `pos=character`：1,739 条里有 9 条在 `noun`/`name` 上。
GRADE_LABEL = re.compile(r"^(jōyō|jinmeiyō|hyōgai|\w+ grade kyōiku)\s+kanji$", re.I)


def romaji_of(o, kana, stat=None):
    """源头给的修正ヘボン式。🔴 **存源头的不自己算** —— 算的与源头严格一致率仅 64.27%，
    算不出的是词界空格和 おう→ō/ou 的形态判断，规则天生够不着。

    🔴 判据收窄到第三版才对。前两版都栽在「判据比它要描述的东西更宽」：
       v1 不设防              ⇒ `常` 的罗马字写成 "Fifth grade kyōiku kanji"（1,732 条）
       v2 见 grade/kanji 就挡 ⇒ 误伤 7 条真罗马字（`教育漢字`→kyōiku kanji、
                                `寛治`→Kanji 是人名）
       v3 全串匹配等级标签     ⇒ 仍误伤 2 条：`常用漢字` 的**正确罗马字就是** "jōyō kanji"，
                                与等级标签字面完全一样
       v4（本版）**再加一条「有没有读音」** —— 罗马字是「读音的拉丁转写」，
          **没有读音就不可能有罗马字**。`常`（character）读音为 None ⇒ 那串是等级标签；
          `常用漢字`（noun）读音是 じょうようかんじ ⇒ 那串是真罗马字。
       ⚠️ 判据用**它是什么**（有没有可转写的读音），不用**它长什么样**
          —— `[[criteria-from-meaning-not-form]]`。
    """
    for f in (o.get("forms") or []):
        if "romanization" in (f.get("tags") or []) and f.get("form"):
            v = f["form"]
            if GRADE_LABEL.match(v) and not kana:
                if stat is not None:
                    stat["剔除·字种等级冒充罗马字"] += 1
                return None
            return v
    return None


def grade_of(o):
    for s in (o.get("senses") or []):
        for c in (s.get("categories") or []):
            nm = (c.get("name") or "").lower()
            for key, zh in GRADES:
                if key in nm:
                    return zh
    return None


def scan(word_id):
    entries, srcs = [], []
    stat = collections.Counter()
    seen = collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        if o.get("pos") in NOT_A_WORD:
            continue
        w = o.get("word") or ""
        if not w.strip():
            continue
        wid = word_id.get(w)
        if wid is None:
            stat["词形不在 dict（不该发生）"] += 1
            continue
        praw = o.get("pos") or "unknown"
        etym = str(o.get("etymology_number") or "0")
        key = (w, praw, etym)
        seq = seen[key]
        seen[key] += 1
        ref = "kk-ja:%s:%s:%s:%d" % (w, praw, etym, seq)
        kana, ksrc = reading_of(o)
        # `%` 是源头标的**形态边界**（`ジー%ディー%ピー`，26 条）。罗马字的连字符靠它推，
        # 但我们**存源头的罗马字不自己推** ⇒ 它在读音列里只会妨碍精确匹配，剥掉。
        if kana:
            kana = kana.replace("%", "")
        entries.append((wid, w, POS_MAP.get(praw, praw), praw, etym, seq,
                        kana, ksrc, hist_kana_of(o), romaji_of(o, kana, stat), grade_of(o),
                        "en-edition", ref))
        stat["entry"] += 1
        if kana:
            stat["有读音·" + ksrc] += 1
        for i, se in enumerate(o.get("senses") or []):
            gs = [g for g in (se.get("glosses") or []) if g]
            if not gs:
                stat["义项无 gloss（不入证据层）"] += 1
                continue
            srcs.append((wid, None, "en-edition", "%s#%d" % (ref, i), "en", gs[0],
                         json.dumps(se.get("tags") or [], ensure_ascii=False) or None))
            stat["sense_src"] += 1
            if is_pointer_sense(se):
                stat["  其中指针义项"] += 1
    return entries, srcs, stat


def verify(n_entry, n_src):
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    kanji_tot = q("SELECT COUNT(*) FROM entry WHERE pos_raw<>'character'"
                  " AND word_src GLOB '*[一-鿿]*'")
    kanji_hit = q("SELECT COUNT(*) FROM entry WHERE pos_raw<>'character'"
                  " AND word_src GLOB '*[一-鿿]*' AND kana IS NOT NULL")
    checks = [
        ("entry 行数", q("SELECT COUNT(*) FROM entry"), n_entry if n_entry is not None else q("SELECT COUNT(*) FROM entry")),
        ("sense_src 行数", q("SELECT COUNT(*) FROM sense_src"), n_src if n_src is not None else q("SELECT COUNT(*) FROM sense_src")),
        ("孤儿 entry（word_id 不在 dict）",
         q("SELECT COUNT(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id WHERE d.id IS NULL"), 0),
        ("孤儿 sense_src",
         q("SELECT COUNT(*) FROM sense_src x LEFT JOIN dict d ON d.id=x.word_id WHERE d.id IS NULL"), 0),
        ("word_src 与 dict.word 不一致（ja 不折叠）",
         q("SELECT COUNT(*) FROM entry e JOIN dict d ON d.id=e.word_id WHERE e.word_src<>d.word"), 0),
        ("读音里混进汉字（抽错字段就会这样）",
         q("SELECT COUNT(*) FROM entry WHERE kana GLOB '*[一-鿿]*'"), 0),
        # 🔴 这条盯的是我自己踩过的那个坑：`romaji` 里混进 "Jōyō kanji" 这类字种等级。
        #    ⚠️ **断言必须和 `romaji_of` 的 v4 判据用同一条规则**：
        #       第一版写成 `romaji LIKE '% kanji'`，当场报 6 条红 —— 而那 6 条
        #       （`教育漢字`/`常用漢字`/`当用漢字`…）全是**真词真罗马字**。
        #       又一次「判据比它要描述的东西更宽」，而且这次宽的是**闸**不是抽取器。
        #       ⇒ 判据同 v4：是等级标签**且没有读音**才算错。
        ("罗马字里混进字种等级",
         q("SELECT COUNT(*) FROM entry WHERE kana IS NULL AND romaji LIKE '% kanji'"), 0),
        ("读音里残留形态边界 %",
         q("SELECT COUNT(*) FROM entry WHERE kana LIKE '%|%%' ESCAPE '|'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-34s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    print("   ⭐ 含汉字非 character 条目的读音覆盖：%s / %s = %.2f%%"
          % (format(kanji_hit, ","), format(kanji_tot, ","), 100 * kanji_hit / kanji_tot))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="只跑写后回核（写库之后重跑断言用，不插行）")
    a = ap.parse_args()

    if a.verify:
        return verify(None, None)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    word_id = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    con.close()

    entries, srcs, stat = scan(word_id)
    print("■ 扫 %s" % paths.KK.name)
    for k, v in stat.most_common():
        print("   %-26s %9s" % (k, format(v, ",")))

    # 主键唯一性 —— 🔴 **建完立刻验，不等做到义项层**（es 的结构返工就是做了一半才暴露的）
    refs = collections.Counter(e[-1] for e in entries)
    dup = {k: v for k, v in refs.items() if v > 1}
    k3 = collections.Counter((e[1], e[3], e[4]) for e in entries)
    print("\n═══ 主键检查 ═══")
    print("   (词形,词性,词源号,seq) 即 src_ref 冲突   %d" % len(dup))
    print("   (词形,词性,词源号) 三元组冲突             %d 组（seq 就是为它们准备的）"
          % sum(1 for v in k3.values() if v > 1))
    if dup:
        raise SystemExit("🔴 src_ref 不唯一：%r" % list(dup)[:5])

    dbtool.sample_check(
        [(e[1], e[3], e[4], e[6], e[9], e[10]) for e in entries[:6000:611]],
        10, ("词形", "词性", "词源号", "假名", "罗马字", "字种"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("ja-entry-layer",
                        expect={"#entry": len(entries), "#sense_src": len(srcs)}) as s:
        s.executemany(
            "INSERT INTO entry (word_id, word_src, pos, pos_raw, etym_no, seq,"
            " kana, kana_src, kana_hist, romaji, kanji_grade, src, src_ref)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", entries)
        s.executemany(
            "INSERT INTO sense_src (word_id, sense_id, src, src_ref, lang, text, raw_tags)"
            " VALUES (?,?,?,?,?,?,?)", srcs)

    verify(len(entries), len(srcs))


if __name__ == "__main__":
    main()
