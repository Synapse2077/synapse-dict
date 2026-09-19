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

import gzip
import json

import dbtool
import paths
# 🔴 `src_ref` 的构造**只许有这一个出处** —— 它依赖遍历顺序（`seq` 是运行计数器），
#    反解析字符串在词形本身带冒号时会静默漏配（见 `build_entry_layer` 文件头：
#    反解析那版 1,866 条只对上 1,091 条，对不上的 775 条不报错）。
from build_entry_layer import iter_kk          # noqa: E402
# ja/zh 两版：判据一律 import 收词器那一份，闸里/本文件里都不重写
from intake_edition_words import real_senses, clean_gloss, POINTER  # noqa: E402
from gloss_levels import split_levels                               # noqa: E402

f = lambda n: format(n, ",")
DROPPED = paths.WORK / "ingest" / "tag_dropped.tsv"

# 指针义项：tag 说的是「它是谁的什么形」，不是「这个义项怎么用」。
# 🔴 **与 `intake_edition_words.POINTER` 不是同一份，别合并**：那份是
#    `("form-of","alt-of","romanization")`，**没有 `no-gloss`**。
#    ja/zh 两版的过滤走 `real_senses`（它用那一份），无 gloss 的义项由
#    `split_levels` 返回空 spec 时天然跳过；en 版这边是直接按 tag 判，
#    所以要多一个 `no-gloss`。两份形状不同是**有理由的**，合并会静默改掉一版的行为。
POINTER_EN = ("alt-of", "form-of", "romanization", "no-gloss")

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
    # 🔴 ja/zh 两版带进来的（2026-09-18），**都回源看过样本**：
    #   `place`     `アスリート`「塞班的地名」/`境`「茨城县猿岛郡的町」⇒ 这条义项**是个地名**，
    #               与 `name` 同族（是词义类型，不是领域）
    #   `initialism` `AED`/`DD`(男子大生)/`JD`(女子大生) ⇒ 首字母缩写，与 `abbreviation` 同族
    "place", "initialism",
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
    # 🔴 ja/zh 两版带进来的（2026-09-18），回源看过样本：
    #   `Christian` 106 条 —— `天`「神がいる場所」/`祝福`「神からの恵み」/`クリスマス`
    #               ⇒ 基督教**领域**，与 Buddhism/Hinduism 同族（不是语域）
    #   `rhetoric`  10 条 —— `メタファー`「隠喩」/`オノマトペ`「擬音語…の総称」/`対偶`
    #               ⇒ 这些义项**本身就是修辞学术语** ⇒ 领域。
    #               ⚠️ 共享 `REGISTER_LABELS` 里有 `rhetoric:'修辞'`（当语域用），
    #                  **日语这批不是那个意思**，所以归 topic 不归 register。
    "Christian", "rhetoric",
    # 同族补全（宗教/思想领域），别只补 ledger 报出来的那一个
    "Jainism", "Protestant", "Sikhism", "Biblical", "Tao", "Nazism", "Confucianism",
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
    # 🔴 **ja 版特有的一族：标的是「这个词的意思跟那个地方/语言有关」，
    #    不是「这条义项用在那里」。** 回源看过样本：
    #      `仏語`＝フランス語（法语）带 `French`／`独語`＝ドイツ語 带 `Germany`
    #      `露語`＝ロシア語 带 `Russia`／`サハ`＝俄联邦的共和国 带 `Russia`
    #    当成 region 写进去，页面上会变成「仏語〔法国〕」—— 那是**假的**：
    #    这个词不是法国方言，它就是"法语"这个词本身。
    #    ⚠️ 与上面「他语地区」是**两种不同的错**，所以分开记族，别合并：
    #       那一族是"标注英文译词的地区"，这一族是"词义所涉的地名"。
    **{k: "词义所涉地名（不是使用地区）" for k in (
        "French", "Germany", "Russia", "Russian", "Spain", "Europe", "European",
        "Portugal", "Taipei", "Panama", "Rio-de-Janeiro", "Tibetan", "Africa",
        "Iran", "Uganda", "Tainan", "Kosovo", "Namibia", "Hanoi", "Latin",
        "Bogota", "Santiago", "Kinshasa", "Papua", "Aruba", "North-America",
        "Bohemia", "Aragon", "South-Korea", "Vietnam", "Thailand", "India")},
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


def topics_parallel(o):
    """与 `real_senses(o)` **逐项并行**的 topics 列表。

    🔴 `real_senses` 只返回 `(gloss, tags)`，**丢掉了 topics**，而 topics 在这一层
       是大头（ja 版 15,780 实例 / zh 版 3,351）。不能改它（那是收词器的判据），
       只能并行算一份。
    ⚠️ **两份过滤条件漂开 = 静默错配**（topics 挂到别的义项上）⇒ 调用方必须断言
       `len(real_senses(o)) == len(topics_parallel(o))`，不等就整条跳过并计数。
       实测全量 **0 条不等**。
    """
    out = []
    for s in (o.get("senses") or []):
        tg = s.get("tags") or []
        if s.get("form_of") or s.get("alt_of") or any(t in POINTER for t in tg):
            continue
        _umb, spec = split_levels(s.get("glosses"))
        if spec:
            out.append(s.get("topics") or [])
    return out


def iter_editions():
    """ja/zh 两版，**逐条产出 `(src_ref, tags, topics)`**。

    🔴 **顺序与去重必须与 `intake_edition_words.scan()` 逐字一致**，否则 `#k` 对不上：
       ① 先 ja 版后 zh 版；② 同词只取第一次（`w in seen` 跳过）；
       ③ zh 版的一条 gloss 会被 `clean_gloss` **拆成多条**，每条各占一个 `#k`。
    🔴 **构造 `src_ref`，不反解析**（`build_entry_layer` 文件头那条：反解析在词形带
       冒号时 775 条静默漏配）。构造不出的自然查不到库，等于天然处理了"这个词没被收"。
    ⭐ 实测：构造 237,278 条，**命中库里 154,777 条 —— 与已认领的证据行一条不差、无重复**。
    """
    seen = set()
    for src, path, isgz in [("ja-edition", paths.EDITION, False),
                            ("zh-edition", paths.ZH_EDITION, True)]:
        fh = (gzip.open(path, "rt", encoding="utf-8") if isgz
              else open(path, encoding="utf-8"))
        for line in fh:
            if isgz and '"lang_code": "ja"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isgz and o.get("lang_code") != "ja":
                continue
            w = (o.get("word") or "").strip()
            pos = o.get("pos")
            if not w or w in seen:
                continue
            ss = real_senses(o)
            tps = topics_parallel(o)
            if len(ss) != len(tps):
                yield None, None, None          # 判据漂开 —— 调用方计数并跳过
                continue
            if not ss:
                continue
            seen.add(w)
            k = 0
            for (g, tg), tp in zip(ss, tps):
                items = [g] if src == "ja-edition" else clean_gloss(g, w)
                for _x in items:
                    yield "%s:%s:%s:0:0#%d" % (src, w, pos, k), tg, tp
                    k += 1
        fh.close()


def scan():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ref2sense = {r: s for r, s in con.execute(
        "SELECT src_ref, sense_id FROM sense_src WHERE sense_id IS NOT NULL")}
    con.close()

    rows = set()
    stat = collections.Counter()
    dropped = collections.Counter()
    drop_why = {}

    def bucket(sid, tags, topics, tag_label):
        """把一条义项的 tags/topics 归桶。**三版共用这一段**，别各写一版。"""
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

    # ── ja/zh 两版（阶段 1e 回填了 sense_id 之后才做得了）──
    for ref, tags, topics in iter_editions():
        if ref is None:
            stat["🔴 real_senses 与并行 topics 长度不等（整条跳过）"] += 1
            continue
        if not tags and not topics:
            continue
        stat["ja/zh 版：带 tag/topic 的义项"] += 1
        sid = ref2sense.get(ref)
        if sid is None:
            stat["  该词形没被收词（标签无处可挂）"] += 1
            continue
        stat["  ✅ 挂得上"] += 1
        bucket(sid, tags, topics, None)

    # ── 英文版 ──
    for o, w, praw, etym, seq, ref in iter_kk():
        for i, s in enumerate(o.get("senses") or []):
            tags = s.get("tags") or []
            topics = s.get("topics") or []
            if not tags and not topics:
                continue
            stat["en 版：带 tag/topic 的义项"] += 1
            if any(t in POINTER_EN for t in tags):
                stat["  指针义项（整条跳过）"] += 1
                continue
            sid = ref2sense.get("%s#%d" % (ref, i))
            if sid is None:
                stat["  真义项但没编入出版层"] += 1
                continue
            stat["  ✅ 真义项且挂得上"] += 1
            # topics 字段：源头**已经按领域分好**，整族进 topic 桶。
            # 这是结构信号，不是拿拼写猜的。
            bucket(sid, tags, topics, None)
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

    # 🔴 `expect` 是**增量**不是总数（`dbtool` 文件头）。本脚本是 `DELETE` + 全量重插，
    #    所以增量 ＝ 新总数 − 旧总数。
    #    ⚠️ **第一次跑（en 版）时表是空的，`len(rows)` 恰好等于增量，于是写成总数也过了**；
    #       这次接进 ja/zh 两版、表里已有 60,469 条，闸当场报「+11,670，期望 +72,139」。
    #       **恰好对上的那一次最危险** —— 它让一个错的写法看起来是对的。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    before = con.execute("SELECT COUNT(*) FROM sense_tag").fetchone()[0]
    con.close()

    with dbtool.session("ja-sense-tags", expect={"#sense_tag": len(rows) - before},
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
