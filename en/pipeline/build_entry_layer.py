#!/usr/bin/env python3
"""阶段 1b：`entry` 词条层。2026-09-07。

计划见 `docs/EN_PLAN.md` 阶段表 1b。零 API 成本、纯确定性。
读 `data/work/en/ingest/entries.jsonl`（3a 产出的中间件），**不再扫 3.2 GB dump**。

═══ 为什么要有词条层 ═══
`dict` 一行是**词形**；但源头给的是**词条**——`record` 一个词形下有 noun/adj/verb
三个独立词条，`lead` 有「铅」和「引导」两个词源。读音、义项、变形都归词条，不归词形
（`SCHEMA` §十）。`[[schema-redesign-doc]]`：「我们把词形当成了词条」正是要修的。

═══ 身份键（全量实测，非抽样）═══
    src_ref = kk-en:<word_src>:<pos_raw>:<etym_no>:<seq>

  · `etymology_number` 源头是**字符串**（"1"/"2"…），且 **97.0% 为空**
    （1,442,915 / 1,487,422）⇒ 空的记 "0"（照 de 的约定）。
  · `(word, pos, etym_no)` **不唯一**：1,882 个键重复、涉及 3,803 个 entry，最大重复度 4
    （`FPS`/`PVS`/`Hryhorivka` ×4，`bad` adj etym=1 ×3）⇒ **必须有 `seq`**。
  · 🔴 `seq` 按**中间件里的出现顺序**给，而中间件保的是 dump 行序 ⇒ 可复现。
    解析 `src_ref` 一律 `rsplit(":", 3)`（词形自己可能含冒号）。

═══ 🔴 en 的 `entry` **不加任何语法一等字段** —— 量完的结论是不建 ═══
de 的 `entry` 带 12 个德语一等字段（性/属格/复数/助动词/强弱/可分…），因为德语那些
**确实是词条级**的。英语量下来完全相反（全量统计「同一 entry 内该 tag 是否所有义项一致」）：

    | tag              | 整条一致 | 条内混杂 | 混杂率 |
    | intransitive     |   3,773 |   5,672 | **60.1%** |
    | ambitransitive   |   1,077 |     754 | 41.2% |
    | transitive       |  15,829 |   6,605 | **29.4%** |
    | countable        |  46,564 |   5,499 | 10.6% |
    | uncountable      | 172,324 |   5,796 |  3.3% |

**及物性 29–60% 条内混杂 ⇒ 它是义项级不是词条级**；可数性 10.6% 也不能忽略
（`running` 名词同时标 countable + uncountable）。
⇒ 全部归 `sense_tag`（阶段 1c），`entry` 一列不加。
（`[[es-v3-structure-backfill]]`：照搬别的语言结构前先量这门语言有没有那个病。
  这一次量出来的结论是**不建**——那也是结论。）

═══ POS_MAP ═══
🔴 **一次找全**：英语 26 个 pos 取值已**全部**与 `packages/dict-labels/src/common.ts`
   的 `POS_LABELS` 对过，**一个不缺**，不等阶段 8 的契约闸一个个报
   （那张表里记着 `sym` 那次的教训：「别只补闸报出来的那一个」）。

跑：
    cd en && python3 pipeline/build_entry_layer.py
    cd en && python3 pipeline/build_entry_layer.py --run
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
SRC = "kk-en"

# kaikki 原始词性 → 展示短码。取值域与 `dict-labels` 的 `POS_LABELS` 对齐（已全量核过）。
POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv",
    "pron": "pron", "prep": "prep", "conj": "conj", "det": "det",
    "num": "num", "intj": "intj", "name": "name",
    "prefix": "pref", "suffix": "suf", "phrase": "phr",
    "proverb": "prov", "article": "art", "contraction": "contr",
    "particle": "part", "character": "char", "symbol": "sym",
    "interfix": "interfix", "punct": "punct",
    # 🔴 `prep_phrase` **不并进 `phr`**（de 那样做的）—— en 有 3,033 条，
    #    而 `POS_LABELS` 已有「介词短语」这个更准的标签（es 那轮定的），并进去是丢信息。
    "prep_phrase": "prep_phrase",
    "postp": "postp", "infix": "infix", "circumfix": "circumfix",
}

DDL = """CREATE TABLE entry (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id  INTEGER NOT NULL,        -- → dict.id
    word_src TEXT NOT NULL,           -- dump 里的真实拼写；🔴 en 不折叠 ⇒ 恒等于 dict.word
    pos      TEXT NOT NULL,           -- POS_MAP 映射后的展示值
    pos_raw  TEXT NOT NULL,           -- dump 原始词性，主键用它
    etym_no  TEXT NOT NULL,           -- 词源号；源头是字符串，没编号记 "0"
    seq      INTEGER NOT NULL,        -- 同键内序号，正常 0
    src      TEXT NOT NULL,
    src_ref  TEXT NOT NULL,           -- kk-en:<word_src>:<pos_raw>:<etym_no>:<seq>
                                      -- 🔴 解析一律 rsplit(":",3)
    UNIQUE(src_ref)
)"""
IDX = ["CREATE INDEX idx_entry_word ON entry(word_id)",
       "CREATE INDEX idx_entry_pos ON entry(pos)"]


def collect():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    con.close()
    rows, seen = [], collections.Counter()
    stat = collections.Counter()
    for line in open(ENTRIES, encoding="utf-8"):
        d = json.loads(line)
        w = d["word"]
        i = wid.get(w)
        if i is None:                      # dict 里没有 ⇒ 3a 与本步不同步，必须报
            stat["orphan"] += 1
            continue
        praw = d.get("pos") or "unknown"
        etym = str(d.get("etym") or "0")
        k = (w, praw, etym)
        seq = seen[k]
        seen[k] += 1
        if seq:
            stat["needed_seq"] += 1
        pos = POS_MAP.get(praw)
        if pos is None:
            stat["unmapped_pos"] += 1
            pos = praw                     # 不静默丢，透传并计数
            stat["unmapped:" + praw] += 1
        if not (d.get("senses") or []):
            stat["no_sense"] += 1
        rows.append((i, w, pos, praw, etym, seq, SRC,
                     "%s:%s:%s:%s:%d" % (SRC, w, praw, etym, seq)))
        stat["entries"] += 1
    return rows, stat


def gates(con, rows, stat):
    q = lambda s: con.execute(s).fetchone()[0]
    return [
        ("entry 行数 == 计划条数", q("SELECT COUNT(*) FROM entry"), len(rows)),
        ("src_ref 唯一", q("SELECT COUNT(DISTINCT src_ref) FROM entry"), len(rows)),
        ("word_id 全部落在 dict 上",
         q("SELECT COUNT(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id WHERE d.id IS NULL"), 0),
        # 🔴 en 不折叠大小写 ⇒ 这条必须恒成立；一旦不成立就是某处 lower() 了
        ("word_src 逐字节等于 dict.word",
         q("SELECT COUNT(*) FROM entry e JOIN dict d ON d.id=e.word_id WHERE e.word_src<>d.word"), 0),
        ("pos_raw 无空", q("SELECT COUNT(*) FROM entry WHERE TRIM(pos_raw)=''"), 0),
        ("etym_no 无空", q("SELECT COUNT(*) FROM entry WHERE TRIM(etym_no)=''"), 0),
        ("需要 seq>0 的条数", q("SELECT COUNT(*) FROM entry WHERE seq>0"), stat["needed_seq"]),
        ("每个 dict 词形至少一个 entry",
         q("SELECT COUNT(*) FROM dict d LEFT JOIN entry e ON e.word_id=d.id WHERE e.id IS NULL"), 0),
        ("未映射的 pos", stat["unmapped_pos"], 0),
        ("孤儿 entry（dict 里没有该词形）", stat["orphan"], 0),
        # 🔴 本步不许碰别的表
        ("dict 行数未变", q("SELECT COUNT(*) FROM dict"), stat["dict_rows"]),
        ("legacy_dict 未被触碰", q("SELECT COUNT(*) FROM legacy_dict"), stat["legacy_rows"]),
    ]


def report(checks):
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-34s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    nd = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    nl = con.execute("SELECT COUNT(*) FROM legacy_dict").fetchone()[0]
    con.close()

    rows, stat = collect()
    stat["dict_rows"], stat["legacy_rows"] = nd, nl
    npos = len({r[3] for r in rows})
    print("═══ 阶段 1b 计划 ═══")
    print("   entry             %10s" % format(len(rows), ","))
    print("   覆盖词形           %10s / %s" % (format(len({r[0] for r in rows}), ","), format(nd, ",")))
    print("   不同 pos_raw       %10s" % npos)
    print("   有词源号的          %10s" % format(sum(1 for r in rows if r[4] != "0"), ","))
    print("   需要 seq>0 的       %10s" % format(stat["needed_seq"], ","))
    print("   无义项的 entry      %10s" % format(stat["no_sense"], ","))
    print("   🔴 未映射 pos       %10s   孤儿 %s"
          % (format(stat["unmapped_pos"], ","), format(stat["orphan"], ",")))
    for k, v in stat.items():
        if str(k).startswith("unmapped:"):
            print("      %s %s" % (k, v))
    print("\n   身份键样本：")
    for r in rows[:3] + [r for r in rows if r[5] > 0][:3]:
        print("      %s" % r[7])
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0

    with dbtool.session("keep-v3-1b-entry", expect={"#entry": len(rows)}) as s:
        if "entry" not in have:
            s.execute(DDL)
            for i in IDX:
                s.execute(i)
        s.executemany(
            "INSERT INTO entry (word_id, word_src, pos, pos_raw, etym_no, seq, src, src_ref) "
            "VALUES (?,?,?,?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = report(gates(con, rows, stat))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
