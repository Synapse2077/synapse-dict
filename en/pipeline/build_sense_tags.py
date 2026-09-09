#!/usr/bin/env python3
"""阶段 1d：`sense_tag` —— 把源头的 tags/topics 归桶。2026-09-07。

计划见 `docs/EN_PLAN.md` 阶段表 1d。零 API 成本、纯确定性。读 3a 的中间件。

═══ 🔴 第一条判据：指针义项的 tag 描述的是「关系」不是「词义」，整条跳过 ═══
第一版我打算逐个 tag 拉黑名单（`plural`/`past`/`participle`/`third-person`…）——
那是拿**拼写**当判据。正确的问法是「这条义项本身是不是指针」：

    指针义项   706,345 条，带 1,856,612 个 tag 实例（占全部的 **70%**）
    真义项   1,072,932 条，带   798,077 个

`birdnests` 的 `plural` 说的是"它是 birdnest 的复数"，不是"这个义项用于复数"。
那批信息归**变形层**（阶段 2），不归义项标签。
⇒ 一条规则挡掉 70% 的噪声，比 400 个 tag 的黑名单准，也不会漏。

═══ 归桶：按**看到的实际内容**定，不按拼写猜 ═══
几个一眼归不准的，逐条回源看过样本才定（`[[criteria-from-meaning-not-form]]`）：

    Greek/Roman/Norse/Japanese → topic     Thanatos 死神、Thor 雷神、furigana 振假名
                                           （这些义项本来就带 topics=['mythology']，
                                            标签补的是"哪一支传统"，丢了就分不清希腊/北欧）
    Internet / Polari / ethnic → register  robot（4chan）、naff（Polari 黑话）、crow（蔑称）
    letter/morpheme/relational/in-compounds → grammar
                                           A「英语字母表第一个字母」、a-「构成动词的前缀」、
                                           mental「与心智相关的」、odd「twenty-odd 的 odd」
    physical / capitalized     → usage     free「无阻碍的」（与抽象义相对）、
                                           brown「大写时指…」
🔴 **`Oxford`(302) 与 `English`(371) 有意不归** —— 看了样本仍判不准
   （`Oxford` 三条全是 `de-Christianize`，像是 Oxford 拼写约定；`English` 的样本互不相干）。
   **判不准就落 drop-ledger，不硬塞进某个桶。** 宁可缺，不可错。

⚠️ `error-lua-timeout`(179) 是**源头自己的报错标记**，不是词义属性 —— 单独计数、不入库。

═══ drop-ledger ═══
桶外的 tag **不静默丢**：逐个计数落 `data/work/en/ingest/tag_dropped.tsv`，
跑完打印 Top 20。de 的建库脚本就有这个（"全 tag 逐个归桶，桶外建库报警"）。

跑：
    cd en && python3 pipeline/build_sense_tags.py
    cd en && python3 pipeline/build_sense_tags.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import sqlite3

import dbtool
import paths

ENTRIES = paths.WORK / "ingest" / "entries.jsonl"
DROPPED = paths.WORK / "ingest" / "tag_dropped.tsv"

# 源头自己的报错标记，不是词义属性。
# 🔴 **用前缀不用枚举**：第一版枚举了三个，drop-ledger 立刻冒出 `error-lua-exec`
#    —— 照 `dict-labels` 里那条「别只补闸报出来的那一个」，改成整族。
def is_source_error(tag):
    return tag.startswith("error-")

GRAMMAR = {
    # 可数性与比较级
    "countable", "uncountable", "usually-uncountable", "comparable", "not-comparable",
    "uncomparable", "plural-only", "singular-only", "no-plural", "in-plural",
    "plural-normally", "plural", "singular", "invariable",
    # 及物性与配价
    "transitive", "intransitive", "ambitransitive", "ditransitive", "ergative",
    "reflexive", "impersonal", "copulative", "stative", "auxiliary", "modal",
    # 分布与句法位置
    "attributive", "predicative", "postpositional", "in-compounds", "relational",
    "with-definite-article", "no-present-participle", "collective", "personal",
    "imperative", "third-person", "second-person", "first-person",
    # 词类
    "particle", "pronoun", "letter", "morpheme", "onomatopoeic", "diminutive",
    "agent", "contraction", "abbreviation", "initialism", "acronym",
    # ── 补：格 / 语态 / 配价 / 缺陷范式 ──
    "interrogative", "nominative", "objective", "conjunctive", "passive",
    "defective", "comparative-only", "no-past-participle",
    "with-on", "with-of", "with-in", "with-to", "with-for",
    # 出现在**真义项**上的这三个不是指针标记（指针义项整条已跳过）
    "participle", "past", "gerund",
}

REGION = {
    "US", "UK", "Australia", "Canada", "Scotland", "Ireland", "India", "New-Zealand",
    "Philippines", "Northern-England", "South-Africa", "Singapore", "Commonwealth",
    "British", "Singlish", "Southern-US", "Multicultural-London-English", "Hong-Kong",
    "Geordie", "England", "Cockney", "Caribbean", "South-Asia", "Jamaica", "Yorkshire",
    "regional", "dialectal", "Malaysia", "Cornwall", "Nigeria", "Western", "West-Country",
    "Appalachia", "Pakistan", "Africa", "Manglish", "Northern-Ireland", "Wales", "Hawaii",
    "Indonesia", "New-England", "Canadian", "Newfoundland", "Northumbria", "Pennsylvania",
    "Irish", "Australian", "North", "American", "Scottish", "Welsh", "Midlands",
    # ── 2026-09-07 按 drop-ledger 前 72 名补（地名/方言区一族）──
    "Shetland", "Kenya", "Cumbria", "Trinidad-and-Tobago", "Ulster", "Quebec",
    "China", "Bangladesh", "California", "Devon", "New-York", "New-York-City",
    "Louisiana", "Guyana", "Maine", "Myanmar", "West-Midlands", "Philippine",
    "Japan", "East-Anglia", "Zimbabwe", "Orkney", "London", "Midwestern-US",
    "Texas", "Northern-US", "Southern-England", "Russia", "Europe",
    "East", "West", "South", "Southern", "Northeastern", "Southwestern",
}

REGISTER = {
    "obsolete", "archaic", "dated", "historical", "rare", "uncommon",
    "slang", "informal", "colloquial", "formal", "literary", "poetic",
    "vulgar", "derogatory", "offensive", "slur", "ethnic", "humorous", "euphemistic",
    "childish", "endearing", "sarcastic", "ironic", "emphatic",
    "nonstandard", "standard", "proscribed", "neologism", "nonce-word",
    "mildly", "excessive", "Internet", "Polari", "jargon", "technical",
    # ── 补：时代层 / 网络变体 / 亲疏 ──
    "Modern", "Early", "Leet", "familiar",
}

USAGE = {
    "usually", "often", "sometimes", "especially", "specifically", "broadly",
    "narrowly", "also", "possibly", "figuratively", "literally", "metonymically",
    "idiomatic", "capitalized", "physical", "by-extension", "generally",
    # ── 补：正字提示（与 capitalized 同族）/ 表述取向 ──
    "lowercase", "uppercase", "gender-neutral",
}

# 神话/文化传统 —— 与 `topics` 同一维度，补的是"哪一支"
TOPIC_TAG = {
    "Greek", "Roman", "Norse", "Japanese", "Chinese", "Judaism", "Hinduism",
    "Jewish", "Mormonism", "Marxism", "Ancient-Rome", "rhetoric", "Islam",
    "Christianity", "Buddhism", "Egyptian", "Celtic", "Hebrew", "Latin",
    # ── 补：学科 / 宗教 / 军种 / 战争 / 技术传统 ──
    "Germanic", "Indo-European-studies", "Jainism", "Sikhism", "Quakerism",
    "Rastafari", "World-War-I", "World-War-II", "Navy", "Unix",
}

BUCKETS = [("grammar", GRAMMAR), ("region", REGION), ("register", REGISTER),
           ("usage", USAGE), ("topic", TOPIC_TAG)]


def bucket_of(tag):
    for kind, s in BUCKETS:
        if tag in s:
            return kind
    return None


def collect():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # (word, entry 序, 义项序) → sense_id：照 1c 的顺序重建，保证对得上
    sid_of = {}
    for sid, ref in con.execute("SELECT sense_id, src_ref FROM sense_src"):
        sid_of[ref] = sid
    con.close()

    rows = set()
    dropped = collections.Counter()
    stat = collections.Counter()
    seen_key = collections.Counter()
    for line in open(ENTRIES, encoding="utf-8"):
        d = json.loads(line)
        w = d["word"]
        praw = d.get("pos") or "unknown"
        etym = str(d.get("etym") or "0")
        ekey = (w, praw, etym)
        eseq = seen_key[ekey]
        seen_key[ekey] += 1
        for k, se in enumerate(d.get("senses") or []):
            if not se.get("g"):
                continue
            ref = "en-edition:%s:%s:%s:%d#%d" % (w, praw, etym, eseq, k)
            sid = sid_of.get(ref)
            if sid is None:
                stat["no_sense"] += 1
                continue
            # 🔴 指针义项整条跳过：它的 tag 描述关系不描述词义
            if (se.get("form_of") or se.get("alt_of")
                    or "form-of" in se["tags"] or "alt-of" in se["tags"]):
                stat["pointer_skipped"] += 1
                continue
            stat["real"] += 1
            for t in se["tags"]:
                if is_source_error(t):
                    stat["source_error"] += 1
                    continue
                kind = bucket_of(t)
                if kind is None:
                    dropped[t] += 1
                    continue
                rows.add((sid, kind, t))
            for t in se["topics"]:
                rows.add((sid, "topic", t))
    stat["rows"] = len(rows)
    stat["dropped_kinds"] = len(dropped)
    stat["dropped_inst"] = sum(dropped.values())
    return sorted(rows), dropped, stat


def gates(con, stat):
    q = lambda s: con.execute(s).fetchone()[0]
    return [
        ("sense_tag 行数", q("SELECT COUNT(*) FROM sense_tag"), stat["rows"]),
        ("kind 取值只有五种",
         q("SELECT COUNT(*) FROM sense_tag WHERE kind NOT IN "
           "('grammar','region','register','usage','topic')"), 0),
        ("sense_id 全部落在 sense 上",
         q("SELECT COUNT(*) FROM sense_tag t LEFT JOIN sense s ON s.id=t.sense_id "
           "WHERE s.id IS NULL"), 0),
        ("value 无空", q("SELECT COUNT(*) FROM sense_tag WHERE TRIM(value)=''"), 0),
        # 🔴 指针义项一条标签都不该有 —— 这条守的就是本步最关键的那个判据
        ("指针义项零标签",
         q("SELECT COUNT(*) FROM sense_tag t JOIN sense_src c ON c.sense_id=t.sense_id "
           "WHERE c.raw_tags LIKE '%\"form-of\"%' OR c.raw_tags LIKE '%\"alt-of\"%'"), 0),
        ("源头报错标记未入库",
         q("SELECT COUNT(*) FROM sense_tag WHERE value LIKE 'error-%'"), 0),
        ("判不准的两个未入库（Oxford/English）",
         q("SELECT COUNT(*) FROM sense_tag WHERE value IN ('Oxford','English')"), 0),
        ("dict 行数未变", q("SELECT COUNT(*) FROM dict"), stat["dict_rows"]),
        ("sense 行数未变", q("SELECT COUNT(*) FROM sense"), stat["sense_rows"]),
        ("legacy_dict 未被触碰", q("SELECT COUNT(*) FROM legacy_dict"), stat["legacy_rows"]),
    ]


def report(checks):
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-38s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    nd = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    ns = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    nl = con.execute("SELECT COUNT(*) FROM legacy_dict").fetchone()[0]
    con.close()
    rows, dropped, stat = collect()
    stat["dict_rows"], stat["sense_rows"], stat["legacy_rows"] = nd, ns, nl
    by_kind = collections.Counter(k for _, k, _ in rows)

    print("═══ 阶段 1d 计划 ═══")
    print("   真义项 %s ｜ 指针义项跳过 %s ｜ 挂不上 %s"
          % (format(stat["real"], ","), format(stat["pointer_skipped"], ","),
             format(stat["no_sense"], ",")))
    print("   sense_tag 将写 %s 行：" % format(stat["rows"], ","))
    for k, v in by_kind.most_common():
        print("      %-10s %10s" % (k, format(v, ",")))
    print("   源头报错标记（不入库） %s" % format(stat["source_error"], ","))
    print("\n   🔴 drop-ledger：桶外 %s 种、%s 个实例（%.3f%% of 真义项 tag）"
          % (format(stat["dropped_kinds"], ","), format(stat["dropped_inst"], ","),
             100 * stat["dropped_inst"] / max(stat["dropped_inst"] + sum(
                 v for k, v in by_kind.items() if k != "topic"), 1)))
    DROPPED.write_text("\n".join("%s\t%d" % (t, v) for t, v in dropped.most_common()),
                       encoding="utf-8")
    print("      明细 → %s ；Top 20：" % DROPPED)
    for t, v in dropped.most_common(20):
        print("      %-30s %s" % (t, format(v, ",")))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0

    with dbtool.session("keep-v3-1d-tags", expect={"#sense_tag": stat["rows"]}) as s:
        s.executemany("INSERT INTO sense_tag (sense_id, kind, value) VALUES (?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = report(gates(con, stat))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
