#!/usr/bin/env python3
"""阶段 1c：`sense` 出版层 + `sense_src` 证据层 + `sense_gloss`(en)。2026-09-07。

计划见 `docs/EN_PLAN.md` 阶段表 1c。零 API 成本、纯确定性。读 3a 的中间件，不扫 dump。
（`sense_tag` 的标签分桶是 **1d**，本步不做 —— 一次只动一样东西。）

═══ 🔴🔴 本步最硬的一条：义项文本取 `glosses[-1]`，不是 `[0]` ═══
kaikki 的 `glosses` 是**从泛到specific 的一条路径**，不是并列的多条释义：

    free  adj  glosses = ["Unconstrained.", "Not imprisoned or enslaved."]
    free  adj  glosses = ["Unconstrained.", "Generous; liberal."]
    cat   noun glosses = ["Terms relating to animals.", "A mammal of the family Felidae"]

**de/pt/fr 的 `build.py` 取的是 `[0]`**（`de/pipeline/build.py:468`）。
放到英语上实测**会把 43,443 条义项压成重复** —— `free` 六条义项全变成 "Unconstrained."。

⭐ 为什么前几门没炸（我查了，不是它们对而是它们没撞上）：
    | 语言 | 义项 | 嵌套 | 取首会多造的重复 |
    | de | 631,694 | 52.24% | 232,701 |
    | pt | 514,166 | 20.49% |  52,926 |
    | fr | 457,902 | 14.04% |  32,423 |
    | **en** | 1,779,277 | 2.9% | **43,443** |
  de 的**嵌套率最高**，但它的义项主要来自**德语版**而非英文版 ⇒ 落库只留下 105 行重复
  （`Platte ×8 "Various short forms:"` 就是这个病的微量版）。**它们躲过去了，en 躲不过。**
  ⚠️ de 已封版，那 105 行不归本轮处理（`[[es-only-scope]]`：只动当前这门语言）。

⇒ **出版层印 `glosses[-1]`（最具体的那句），证据层留完整路径**，两边都不丢。

═══ 三张表的分工（`SCHEMA` §2.-1 两层义项）═══
  `sense`       出版层：一个义项一行，`rank` 是展示顺序（**主键才是契约，行号不是**）
  `sense_src`   证据层：源头原样 + 回源坐标 `src_ref`，`raw_tags` 存 tags/topics/嵌套路径
  `sense_gloss` 释义层：本步只写 `lang='en'`；中文归 **1.5**

🔴 `sense_src.sense_id` 本步 **100% 挂得上**（一条源义项 ⟶ 一条出版义项，不做合并）。
   将来收别的版本（zh 版）时才会出现「挂不上/需裁决」的行 —— 那是 1.5 的事。
   ⚠️ **不做自动判重**：`PLAYBOOK` 写死「下一门语言不要做自动判重」，
      es 那 186 条判重里 12.4% 是义项错配。**多一条义项是缺，错配是错。**

跑：
    cd en && python3 pipeline/build_sense_layer.py
    cd en && python3 pipeline/build_sense_layer.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import sqlite3

import dbtool
import paths
from pipeline.build_entry_layer import POS_MAP

ENTRIES = paths.WORK / "ingest" / "entries.jsonl"
SRC = "en-edition"


def collect():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    con.close()

    senses, srcs, glosses = [], [], []
    rank = collections.Counter()
    seen_key = collections.Counter()
    stat = collections.Counter()
    sid = 0
    for line in open(ENTRIES, encoding="utf-8"):
        d = json.loads(line)
        w = d["word"]
        i = wid.get(w)
        if i is None:
            stat["orphan"] += 1
            continue
        praw = d.get("pos") or "unknown"
        etym = str(d.get("etym") or "0")
        ekey = (w, praw, etym)
        eseq = seen_key[ekey]
        seen_key[ekey] += 1
        pos = POS_MAP.get(praw, praw)
        for k, se in enumerate(d.get("senses") or []):
            g = se.get("g")
            if not g:
                stat["no_gloss"] += 1
                continue
            sid += 1
            rank[i] += 1
            senses.append((sid, i, rank[i], pos))
            # 🔴 证据层留完整路径：`path` 只在嵌套时出现，能原样还原源头的分组
            raw = {"tags": se.get("tags") or [], "topics": se.get("topics") or []}
            if se.get("path"):
                raw["path"] = se["path"]
                stat["nested"] += 1
            srcs.append((i, sid, SRC,
                         "%s:%s:%s:%s:%d#%d" % (SRC, w, praw, etym, eseq, k),
                         "en", g, json.dumps(raw, ensure_ascii=False)))
            glosses.append((sid, "en", "definition", 0, g, SRC))
        stat["entries"] += 1
    stat["senses"] = len(senses)
    return senses, srcs, glosses, stat


def gates(con, stat):
    q = lambda s: con.execute(s).fetchone()[0]
    return [
        ("sense 行数", q("SELECT COUNT(*) FROM sense"), stat["senses"]),
        ("sense_src 行数", q("SELECT COUNT(*) FROM sense_src"), stat["senses"]),
        ("sense_gloss(en) 行数",
         q("SELECT COUNT(*) FROM sense_gloss WHERE lang='en'"), stat["senses"]),
        ("src_ref 唯一", q("SELECT COUNT(DISTINCT src_ref) FROM sense_src"), stat["senses"]),
        ("🔴 sense_src 全部挂上义项",
         q("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL"), 0),
        ("sense.word_id 全部落在 dict 上",
         q("SELECT COUNT(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id WHERE d.id IS NULL"), 0),
        ("(word_id,rank) 唯一",
         q("SELECT COUNT(*) FROM (SELECT word_id,rank FROM sense GROUP BY 1,2 HAVING COUNT(*)>1)"), 0),
        ("rank 从 1 连续",
         q("SELECT COUNT(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING MIN(rank)<>1 OR MAX(rank)<>COUNT(*))"), 0),
        ("sense_gloss 无空文本",
         q("SELECT COUNT(*) FROM sense_gloss WHERE TRIM(text)=''"), 0),
        # 🔴 取 glosses[-1] 的证据：同一词形下逐字相同的英文释义应当很少。
        #    取 [0] 的话这里会是 4 万量级 —— 这条断言就是那个决定的守卫。
        ("同词形下重复的英文释义（取首会到 4 万级）",
         q("SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM sense s "
           "JOIN sense_gloss g ON g.sense_id=s.id WHERE g.lang='en' "
           "GROUP BY s.word_id, g.text HAVING c>1)"), stat["dup_expect"]),
        ("本步不写中文", q("SELECT COUNT(*) FROM sense_gloss WHERE lang<>'en'"), 0),
        ("sense_tag 仍为空（归 1d）", q("SELECT COUNT(*) FROM sense_tag"), 0),
        ("dict 行数未变", q("SELECT COUNT(*) FROM dict"), stat["dict_rows"]),
        ("entry 行数未变", q("SELECT COUNT(*) FROM entry"), stat["entry_rows"]),
        ("legacy_dict 未被触碰", q("SELECT COUNT(*) FROM legacy_dict"), stat["legacy_rows"]),
    ]


def report(checks):
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-40s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    nd = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    ne = con.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
    nl = con.execute("SELECT COUNT(*) FROM legacy_dict").fetchone()[0]
    con.close()
    senses, srcs, glosses, stat = collect()
    stat["dict_rows"], stat["entry_rows"], stat["legacy_rows"] = nd, ne, nl
    # 预算：同一词形下逐字相同的英文释义（取末之后应当很少；取首会到 4 万级）
    tx = collections.Counter()
    for (_sid, _lang, _kind, _seq, text, _src), (_s2, w2, _r2, _p2) in zip(glosses, senses):
        tx[(w2, text)] += 1
    stat["dup_expect"] = sum(v - 1 for v in tx.values() if v > 1)

    print("═══ 阶段 1c 计划 ═══")
    print("   义项 sense          %10s" % format(stat["senses"], ","))
    print("   证据 sense_src      %10s" % format(len(srcs), ","))
    print("   英文释义 sense_gloss %10s" % format(len(glosses), ","))
    print("   其中嵌套义项         %10s   （证据层留完整 path）" % format(stat["nested"], ","))
    print("   无 gloss 跳过        %10s   孤儿 %s"
          % (format(stat["no_gloss"], ","), format(stat["orphan"], ",")))
    print("   取末后同词形重复释义  %10s   （取首会是 43,443 量级）"
          % format(stat["dup_expect"], ","))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0

    with dbtool.session("keep-v3-1c-sense",
                        expect={"#sense": stat["senses"], "#sense_src": len(srcs),
                                "#sense_gloss": len(glosses)}) as s:
        s.executemany("INSERT INTO sense (id, word_id, rank, pos) VALUES (?,?,?,?)", senses)
        s.executemany("INSERT INTO sense_src (word_id, sense_id, src, src_ref, lang, text, raw_tags) "
                      "VALUES (?,?,?,?,?,?,?)", srcs)
        s.executemany("INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src) "
                      "VALUES (?,?,?,?,?,?)", glosses)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = report(gates(con, stat))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
