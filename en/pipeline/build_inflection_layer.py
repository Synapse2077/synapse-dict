#!/usr/bin/env python3
"""阶段 2：`inflection` 变形层（2b）+ `sense_relation` 异体关系（2a）。2026-09-07。

计划见 `docs/EN_PLAN.md` 阶段表 2。零 API 成本、纯确定性。读 3a 的中间件。

═══ 本步只做「形式 → 词元」一个方向 ═══
另一个方向（词元 `forms` 变位表 → 形式）会**造出库里还没有的新词形**，那是**收词**，
按不变式必须等 3b 收完再做 ⇒ 归 **2c**（`EN_PLAN` §2.3）。
🔴 pt 那轮 46.2% 空白页就是 2c 缺位造成的，所以它在阶段表里是**一行**，不是"顺便"。

═══ 2a：`alt_of` 进 `sense_relation`，不进 `inflection` ═══
🔴 **异体拼写不是屈折**（3a 定 `is_lemma` 时已经用外锚验过这条）：
`Mobius strip` / `hang-around` / `SEB` 是**它自己的词头**，读者查得到。
把它塞进变形层会让 14 万个正经词头在展示层被印成「某词的变形」——
de 收尾单 C16 记的正是这个病（5.6 万行「变形」其实是异体拼写）。
⇒ `kind='alt_of'` 进 `sense_relation`，与同义/反义等语义关系同一张表。

═══ 材料（全量实测）═══
    带 `form_of` 的义项 536,409，目标落在 dict 上 **99.8%**
    带 `alt_of`  的义项 169,908，目标落在 dict 上 **84.7%**
    形态 tag 组合 900 种，前 30 覆盖 99.5%

中文说明由 `infl_compose.compose()` **组合式**拼（不枚举组合），拼不出的**不产生行**、
落 drop-ledger —— **绝不回退成泛泛的「变形」**（C16 那个病的根源）。

跑：
    cd en && python3 pipeline/build_inflection_layer.py
    cd en && python3 pipeline/build_inflection_layer.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import sqlite3

import dbtool
import paths
from infl_compose import compose

ENTRIES = paths.WORK / "ingest" / "entries.jsonl"
LEDGER = paths.WORK / "ingest" / "infl_uncomposed.tsv"
SRC = "en-edition"
REL_ALT = "alt_of"          # 🔴 字面量抽成常量：阶段 7 的闸要 import 它，不许手抄

DDL = """CREATE TABLE inflection (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id  INTEGER NOT NULL,        -- 变形词形 → dict.id
    entry_id INTEGER,                 -- 该变形属于哪个词条（SCHEMA §10）
    kind     TEXT NOT NULL,           -- inflection 屈折 / derivation 构词
    base     TEXT NOT NULL,           -- 原形词形，**原样存**不解析成外键
    base_id  INTEGER,                 -- 原形在库里的 dict.id；NULL = 悬空
    label_zh TEXT NOT NULL,           -- infl_compose 组合的中文语法说明
    desc_en  TEXT,                    -- dump 原文 gloss
    tags     TEXT,                    -- 源头 tags 的 JSON
    src      TEXT NOT NULL,
    src_ref  TEXT NOT NULL,
    UNIQUE(src_ref)
)"""
IDX = ["CREATE INDEX idx_infl_word ON inflection(word_id)",
       "CREATE INDEX idx_infl_base ON inflection(base_id)",
       "CREATE INDEX idx_infl_entry ON inflection(entry_id)",
       "CREATE INDEX idx_infl_kind ON inflection(kind)"]


def collect():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    eid = {}
    for i, ref in con.execute("SELECT id, src_ref FROM entry"):
        eid[ref] = i
    sid = {}
    for s, ref in con.execute("SELECT sense_id, src_ref FROM sense_src"):
        sid[ref] = s
    con.close()

    infl, rels = [], []
    ledger = collections.Counter()
    stat = collections.Counter()
    seen_key = collections.Counter()
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
        e_ref = "kk-en:%s:%s:%s:%d" % (w, praw, etym, eseq)
        e_id = eid.get(e_ref)
        for k, se in enumerate(d.get("senses") or []):
            g = se.get("g")
            if not g:
                continue
            s_ref = "%s:%s:%s:%s:%d#%d" % (SRC, w, praw, etym, eseq, k)
            s_id = sid.get(s_ref)

            # ── 2a：异体拼写 → sense_relation
            for t in (se.get("alt_of") or []):
                tw = (t or {}).get("word")
                if not tw:
                    continue
                rels.append((i, s_id, REL_ALT, tw,
                             json.dumps(se["tags"], ensure_ascii=False), SRC, s_ref))
                stat["alt"] += 1

            # ── 2b：屈折/构词 → inflection
            fo = se.get("form_of") or []
            if not fo:
                continue
            label, kind = compose(se["tags"])
            if label is None:
                ledger[tuple(sorted(x for x in se["tags"] if x != "form-of"))] += 1
                stat["uncomposed"] += 1
                continue
            for n, t in enumerate(fo):
                tw = (t or {}).get("word")
                if not tw:
                    continue
                infl.append((i, e_id, kind, tw, wid.get(tw), label, g,
                             json.dumps(se["tags"], ensure_ascii=False), SRC,
                             "%s#%d" % (s_ref, n)))
                stat["infl"] += 1
                if wid.get(tw) is None:
                    stat["dangling"] += 1
    return infl, rels, ledger, stat


def gates(con, stat):
    q = lambda s: con.execute(s).fetchone()[0]
    return [
        ("inflection 行数", q("SELECT COUNT(*) FROM inflection"), stat["infl"]),
        ("sense_relation 行数", q("SELECT COUNT(*) FROM sense_relation"), stat["alt_written"]),
        ("src_ref 唯一", q("SELECT COUNT(DISTINCT src_ref) FROM inflection"), stat["infl"]),
        ("word_id 全落在 dict 上",
         q("SELECT COUNT(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
           "WHERE d.id IS NULL"), 0),
        ("base_id 悬空数（源头真缺词头）",
         q("SELECT COUNT(*) FROM inflection WHERE base_id IS NULL"), stat["dangling"]),
        ("label_zh 无空", q("SELECT COUNT(*) FROM inflection WHERE TRIM(label_zh)=''"), 0),
        # 🔴🔴 **绝不回退成泛泛的「变形」**（de 收尾单 C16 那个病）
        ("label_zh 无一条是泛泛的「变形」",
         q("SELECT COUNT(*) FROM inflection WHERE label_zh='变形'"), 0),
        ("kind 只有两种",
         q("SELECT COUNT(*) FROM inflection WHERE kind NOT IN ('inflection','derivation')"), 0),
        # 🔴 异体拼写不许进变形层
        ("sense_relation 只有 alt_of",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind<>'%s'" % REL_ALT), 0),
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
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    nd = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    ns = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    nl = con.execute("SELECT COUNT(*) FROM legacy_dict").fetchone()[0]
    con.close()
    infl, rels, ledger, stat = collect()
    stat["dict_rows"], stat["sense_rows"], stat["legacy_rows"] = nd, ns, nl
    # sense_relation 的 UNIQUE(word_id,sense_id,kind,target) 会去重
    uniq_rel = {(r[0], r[1], r[2], r[3]): r for r in rels}
    stat["alt_written"] = len(uniq_rel)
    by_kind = collections.Counter(r[2] for r in infl)
    by_label = collections.Counter(r[5] for r in infl)

    print("═══ 阶段 2 计划 ═══")
    print("   2b inflection      %10s   （屈折 %s ／ 构词 %s）"
          % (format(stat["infl"], ","), format(by_kind["inflection"], ","),
             format(by_kind["derivation"], ",")))
    print("      悬空 base（源头真缺词头） %s" % format(stat["dangling"], ","))
    print("      🔴 拼不出中文说明、不产生行 %s" % format(stat["uncomposed"], ","))
    print("   2a sense_relation  %10s   （alt_of，去重前 %s）"
          % (format(stat["alt_written"], ","), format(stat["alt"], ",")))
    print("\n   中文说明分布（前 12）：")
    for lb, v in by_label.most_common(12):
        print("      %-24s %s" % (lb, format(v, ",")))
    LEDGER.write_text("\n".join("%s\t%d" % ("+".join(k) or "(无 tag)", v)
                                for k, v in ledger.most_common()), encoding="utf-8")
    print("\n   🔴 拼不出的 tag 组合 %d 种 → %s ；Top 8：" % (len(ledger), LEDGER))
    for k, v in ledger.most_common(8):
        print("      %-40s %s" % ("+".join(k) or "(无 tag)", format(v, ",")))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0

    with dbtool.session("keep-v3-2-inflection",
                        expect={"#inflection": stat["infl"],
                                "#sense_relation": stat["alt_written"]}) as s:
        if "inflection" not in have:
            s.execute(DDL)
            for i in IDX:
                s.execute(i)
        s.executemany(
            "INSERT INTO inflection (word_id, entry_id, kind, base, base_id, label_zh, "
            "desc_en, tags, src, src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)", infl)
        s.executemany(
            "INSERT INTO sense_relation (word_id, sense_id, kind, target, tags, src, src_ref) "
            "VALUES (?,?,?,?,?,?,?)", list(uniq_rel.values()))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = report(gates(con, stat))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
