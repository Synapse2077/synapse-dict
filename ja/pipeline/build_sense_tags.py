#!/usr/bin/env python3
"""阶段 1d：`sense_tag` —— 把源头的 tags/topics 归桶。零模型调用、零成本。2026-09-18。

⚠️ **ja 是七门里最后一个建这张表的**：表 2026-09-15 就建好了、`dbtool` 和回归闸
   都把它登记在 TABLES 里，但**从没有脚本往里写**，整整空了一个项目
   （对照 fr 415,279 / es 103,030 / it 36,463 / de 23,631 / pt 21,164）。

═══ 🔴 判据① 指针义项整条跳过 ═══
照 en 那门的第一条：tag 描述的是**关系**不是**词义**。
`alt-of`/`form-of`/`romanization`/`no-gloss` 那批归变形层与指针层，不归义项标签。
实测：51,250 条带 tag 的义项里 **17,066 条（33%）是指针**，一条规则挡掉，
比拉 269 个 tag 的黑名单准，也不会漏。

═══ 🔴 判据② 字种/字体族**不进这张表** —— 日语特有，另六门撞不上 ═══
最大的一族是它：`kanji` 9,370 ＋ `Hyōgai` 4,966 ＋ `Jinmeiyō` 989 ＋
`shinjitai` 793 ＋ `kyūjitai` 621 ≈ **16,700 ＝ tag 实例的 47%**。
它们**已经在库里另有住处**：

    字种等级（常用/教育/人名用/表外） → `entry.kanji_grade`（14,400 条）
    旧字体对应                        → `sense_relation.kyujitai`（625 条）

⇒ 收进来就是同一件事存两份（`[[refactor-mindset-code-quality]]`：
   同一文件里两张重复映射表已经发生过）。而且它是**字形的属性**，
   同一个汉字的每条义项都带着它 —— 挂到义项上等于把字的属性复制 N 份。

═══ 🔴🔴 判据③ **kaikki 会把一个复合标签拆成两个 tag**，单独归桶必错 ═══
两例，都是回源看样本才发现的（`[[criteria-from-meaning-not-form]]`）：

    Classical + Japanese  ＝ **Classical Japanese（文語）**
        `それ`/`し`/`丸` 三个样本全是这一对同现。单独一个 `Japanese` 挂上去，
        页面会印出一个孤零零的「日语」标签 —— 在日语词典里这是句废话。
    Western + Japan       ＝ **Western Japan（西日本）**
        `儂`「我」带 `[Japan, Western, mainly]`、`狸` 带 `[Japan, Kansai, Western]`。

⇒ `Classical` 留（它自己就说得清「文語」），`Japanese`/`Western`/`Japan` **一律丢**。
   ⚠️ 丢 `Western` 的损失可量：它同现 `Kansai` 时地区信息已由 `Kansai` 承载。

═══ 🔴 判据④ `US`/`UK` 标的是**英文译词**的地区，不是这条日语义项 ═══
`ファスナー` = "zipper (of jeans), (UK) zip fastener" 带 `US` ——
说的是"美式英语管这个叫 zipper"。把它当成日语义项的地区标签，
页面上会变成「ファスナー〔美国〕」，那是假的。⇒ 丢。

═══ drop-ledger：桶外的一个都不许静默丢 ═══
逐个计数落 `data/work/ja/ingest/tag_dropped.tsv`，跑完打印 Top 20。
🔴 **判不准就落 ledger，不硬塞进某个桶**（宁可缺不可错）：
`Shin`（`心`的人名读音？还是真言宗？样本互相矛盾）／`traditional`（一半同现
`Chinese` 指中医、一半指五声音阶）／`feminine`·`masculine`（`妾`是女性自称＝语域，
`雄`「雄性」是词义本身，两类混在一个 tag 里）／`regional`（只说"有地区性"
却不说哪个地区，空信息）。

⚠️ **本轮只做 en-edition。** 另两版的 `sense_src.sense_id` **全是 NULL**
（en 141,773 条已编入，ja/zh 各 84,783／70,029 条一条都没编）——
它们的义项是另一条路径进的 `sense`，没有现成的桥挂回去。
🔴 **推翻/开工它需要**：先把 ja/zh 两版的 `sense_src.sense_id` 回填，
   那是另一件事（证据层→出版层的认领），不该塞进本步顺手做。

跑（在仓库根）：
    python3 -u ja/pipeline/build_sense_tags.py
    python3 -u ja/pipeline/build_sense_tags.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import sqlite3

import dbtool
import paths
# 🔴 `src_ref` 的构造**只许有这一个出处** —— 它依赖遍历顺序（`seq` 是运行计数器），
#    反解析字符串在词形本身带冒号时会静默漏配（见 `build_entry_layer` 文件头：
#    反解析那版 1,866 条只对上 1,091 条，对不上的 775 条不报错）。
from build_entry_layer import iter_kk          # noqa: E402

f = lambda n: format(n, ",")
DROPPED = paths.WORK / "ingest" / "tag_dropped.tsv"

# 指针义项：tag 说的是「它是谁的什么形」，不是「这个义项怎么用」。
POINTER = ("alt-of", "form-of", "romanization", "no-gloss")

# ── 归桶表。**桶外的一律进 drop-ledger，不兜底** ──
# 🔴🔴 **成对的概念不许只收一半。** 第一版 drop-ledger 的「桶外」栏里露出
#    `narrowly`(3)／`standard`(3)／`common`(3) —— 而我已经收了它们的反义
#    `broadly`(523)／`nonstandard`(50)／`uncommon`(254)。
#    量差三个数量级，所以**靠翻 ledger 才看得见，靠读自己的表看不见**：
#    写表时想的是"有哪些标签"，而漏的是"这个标签的对面"。
#    ⇒ 下面每一组反义词都并排写，改一个必须看一眼它的对面。
REGISTER = {
    "archaic", "obsolete", "historical", "dated", "slang", "informal", "colloquial",
    "literary", "rare", "derogatory", "honorific", "humble", "formal",
    "polite", "impolite", "poetic", "vulgar", "euphemistic", "childish", "offensive",
    "humorous", "neologism", "proscribed", "slur", "familiar",
    "endearing", "ironic", "sarcastic", "jargon", "Internet", "Anglicism",
    "nonce-word",
    # ── 成对 ──
    "uncommon", "common",
    "nonstandard", "standard",
    # 文語 ↔ 現代語。⚠️ `Classical` 同现的那个 `Japanese` 要丢，见判据③
    "Classical", "modern",
    # `ちょん`/`毛唐人` 全部同现 derogatory+slur ⇒ 是蔑称的一种，不是"族群"领域
    "ethnic",
}
REGION = {
    # 🔴 **长音符两种写法都要收。** 我按拼写写了 `Kantō`，而源头用的是 `Kanto`
    #    —— drop-ledger 的桶外栏里露出来的（`[[criteria-narrower-than-you-think]]`：
    #    判据比它要描述的东西窄，而窄的那一侧不会报错，只会静默少收）。
    "Kansai", "Kagoshima", "Shikoku", "dialectal",
    "Kyūshū", "Kyushu", "Chūgoku", "Chugoku", "Kantō", "Kanto",
    "Tōhoku", "Tohoku", "Hokkaidō", "Hokkaido", "Tōkyō", "Tokyo",
    "Kyōto", "Kyoto", "Ōsaka", "Osaka", "Ryūkyū", "Ryukyu",
    "Okinawa", "Nagoya",
}
GRAMMAR = {
    "suru", "attributive", "conjunctive", "adverbial", "predicative",
    "in-compounds", "auxiliary", "particle", "sentence-final", "impersonal",
    "verb", "adjective", "noun", "suffix", "prefix", "morpheme", "name",
    "abbreviation", "deictically", "anaphorically", "term-of-address",
    "pronoun", "demonstrative", "numeral", "reflexive", "collective",
    "imperative", "genitive", "participle",
    # ── 成对 ──
    "intransitive", "transitive",
    "uncountable", "countable",
    "present", "past",
    "perfect", "imperfect",
    "negative", "interrogative",
    "first-person", "second-person", "third-person",
}
USAGE = {
    "idiomatic", "figuratively", "literally", "onomatopoeic",
    "ideophonic", "metonymically", "emphatic",
    # ── 成对 ──
    "broadly", "narrowly",
}
# 传统/神话体系：`心`「二十八宿之心宿」`井`「井宿」是中国天文，
# `パン`/`アキレウス`/`ケンタウロス` 是希腊神话 —— 都是**领域**不是地区。
TOPIC_TAG = {
    "Chinese", "Greek", "Roman", "Norse", "Egyptian", "Hinduism", "Judaism",
    "Marxism", "Buddhism", "Shinto", "Christianity", "Islam",
}

BUCKET = [(REGISTER, "register"), (REGION, "region"), (GRAMMAR, "grammar"),
          (USAGE, "usage"), (TOPIC_TAG, "topic")]

# ── 有意丢弃的，**按族分开记**，让 drop-ledger 读得出为什么 ──
DROP = {
    # 判据②：已在 `entry.kanji_grade` / `sense_relation.kyujitai`
    "kanji": "字种族", "Hyōgai": "字种族", "Jinmeiyō": "字种族", "Jōyō": "字种族",
    "Kyōiku": "字种族", "shinjitai": "字种族", "kyūjitai": "字种族",
    "hiragana": "字种族", "katakana": "字种族", "character": "字种族",
    # ateji（当て字）/ Rōmaji / diacritic 同族：说的是**这个字形怎么写**，
    # 不是这条义项怎么用。`ateji` 尤其像内容标签，实则是表记方式。
    "ateji": "字种族", "Rōmaji": "字种族", "diacritic": "字种族",
    # 判据③：拆开的复合标签
    "Japanese": "拆开的复合标签", "Western": "拆开的复合标签", "Japan": "拆开的复合标签",
    # 判据④：标的是英文译词的地区，不是这条日语义项的
    "US": "他语地区", "UK": "他语地区", "Australia": "他语地区",
    "Brazil": "他语地区", "Canadian": "他语地区", "Canada": "他语地区",
    "Ontario": "他语地区", "Hawaii": "他语地区", "Devon": "他语地区",
    "Taiwan": "他语地区", "China": "他语地区", "Korea": "他语地区",
    # 元话语：修饰释义本身的确定性/频率，不描述这条义项怎么用
    "possibly": "元话语", "usually": "元话语", "often": "元话语",
    "sometimes": "元话语", "especially": "元话语", "specifically": "元话语",
    "mildly": "元话语", "probably": "元话语", "mainly": "元话语", "chiefly": "元话语",
    # 判不准 —— 样本自相矛盾，宁可缺不可错
    "Shin": "判不准", "traditional": "判不准", "feminine": "判不准",
    "masculine": "判不准", "regional": "判不准",
}


def is_source_error(tag):
    """源头自己的报错标记，不是词义属性。**用前缀不用枚举** ——
    枚举会漏掉 `error-lua-exec` 这种同族新值（en 那门踩过）。"""
    return tag.startswith("error-")


def scan():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ref2sense = {r: s for r, s in con.execute(
        "SELECT src_ref, sense_id FROM sense_src"
        " WHERE src='en-edition' AND sense_id IS NOT NULL")}
    con.close()

    rows = set()
    stat = collections.Counter()
    dropped = collections.Counter()
    drop_why = {}
    for o, w, praw, etym, seq, ref in iter_kk():
        for i, s in enumerate(o.get("senses") or []):
            tags = s.get("tags") or []
            topics = s.get("topics") or []
            if not tags and not topics:
                continue
            stat["带 tag/topic 的义项"] += 1
            if any(t in POINTER for t in tags):
                stat["  指针义项（整条跳过）"] += 1
                continue
            sid = ref2sense.get("%s#%d" % (ref, i))
            if sid is None:
                stat["  真义项但没编入出版层"] += 1
                continue
            stat["  ✅ 真义项且挂得上"] += 1
            # topics 字段：源头**已经按领域分好**，整族进 topic 桶。
            # 这是结构信号，不是拿拼写猜的。
            for t in topics:
                rows.add((sid, "topic", t))
                stat["topic（来自 topics 字段）"] += 1
            for t in tags:
                if is_source_error(t):
                    stat["源头报错标记（不入库）"] += 1
                    continue
                if t in DROP:
                    dropped[t] += 1
                    drop_why[t] = DROP[t]
                    continue
                for names, kind in BUCKET:
                    if t in names:
                        rows.add((sid, kind, t))
                        stat["%s（来自 tags 字段）" % kind] += 1
                        break
                else:
                    dropped[t] += 1
                    drop_why[t] = "桶外"
    return sorted(rows), stat, dropped, drop_why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, stat, dropped, drop_why = scan()
    print("■ 扫英文版（%s）" % paths.KK.name)
    for k, v in stat.most_common():
        print("   %-30s %9s" % (k, f(v)))

    byk = collections.Counter(k for _s, k, _v in rows)
    print("\n■ 归桶（去重后）")
    for k, v in byk.most_common():
        vals = len({x for _s, kk, x in rows if kk == k})
        print("   %-10s %8s 条 ｜ %s 种取值" % (k, f(v), f(vals)))
    print("   %-10s %8s 条 ｜ 覆盖 %s 条义项"
          % ("合计", f(len(rows)), f(len({s for s, _k, _v in rows}))))

    DROPPED.parent.mkdir(parents=True, exist_ok=True)
    with open(DROPPED, "w", encoding="utf-8") as fh:
        fh.write("tag\tcount\twhy\n")
        for t, n in dropped.most_common():
            fh.write("%s\t%d\t%s\n" % (t, n, drop_why[t]))
    byw = collections.Counter()
    for t, n in dropped.items():
        byw[drop_why[t]] += n
    print("\n■ drop-ledger → %s" % DROPPED)
    for why, n in byw.most_common():
        print("   %-14s %8s 个实例" % (why, f(n)))
    # 🔴 **桶外这一栏要整栏打出来，不许截断。** 第一版写成
    #    `if n < 20: break`，于是第一个小于 20 的就停 —— 326 个实例只印了 1 行，
    #    而真正的漏（`Kanto` 长音符写法、`narrowly` 这些成对词的另一半）
    #    全在那 1 行后面。**截断的 ledger 不是 ledger。**
    out = [(t, n) for t, n in dropped.most_common() if drop_why[t] == "桶外"]
    print("   —— 桶外全部 %d 种 / %s 个实例（**这一栏是要读的**，桶漏了就在这里露头）——"
          % (len(out), f(sum(n for _t, n in out))))
    for t, n in out:
        print("      %-24s %6s" % (t, f(n)))

    dbtool.sample_check([(v, k, str(s)) for s, k, v in rows[::max(1, len(rows) // 16)]],
                        12, ("取值", "桶", "义项 id"))
    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("ja-sense-tags", expect={"#sense_tag": len(rows)},
                        invalidates=[]) as s:
        s.execute("DELETE FROM sense_tag")
        s.executemany("INSERT INTO sense_tag (sense_id, kind, value) VALUES (?,?,?)",
                      rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n■ 写后回核（全量，非抽样）")
    for name, got, want in [
        ("sense_tag 行数", q("SELECT COUNT(*) FROM sense_tag"), len(rows)),
        ("孤儿（sense_id 不在 sense）",
         q("SELECT COUNT(*) FROM sense_tag t LEFT JOIN sense s ON s.id=t.sense_id"
           " WHERE s.id IS NULL"), 0),
        ("kind 越界",
         q("SELECT COUNT(*) FROM sense_tag WHERE kind NOT IN"
           " ('topic','register','region','grammar','usage')"), 0),
        ("字种族漏进来了",
         q("SELECT COUNT(*) FROM sense_tag WHERE value IN"
           " ('kanji','Hyōgai','Jinmeiyō','Jōyō','Kyōiku','shinjitai','kyūjitai')"), 0),
        ("拆开的复合标签漏进来了",
         q("SELECT COUNT(*) FROM sense_tag WHERE value IN"
           " ('Japanese','Western','Japan')"), 0),
        ("挂到隐藏义项上",
         q("SELECT COUNT(*) FROM sense_tag t JOIN sense s ON s.id=t.sense_id"
           " WHERE s.hidden=1"), 0),
    ]:
        print("   %s %-30s %9s（期望 %s）" % ("✅" if got == want else "🔴", name,
                                            f(got), f(want)))
    print("   ⭐ 带标签的义项 %s / %s = %.1f%%"
          % (f(q("SELECT COUNT(DISTINCT sense_id) FROM sense_tag")),
             f(q("SELECT COUNT(*) FROM sense")),
             100.0 * q("SELECT COUNT(DISTINCT sense_id) FROM sense_tag")
             / q("SELECT COUNT(*) FROM sense")))
    con.close()


if __name__ == "__main__":
    main()
