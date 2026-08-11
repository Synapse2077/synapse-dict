#!/usr/bin/env python3
"""建 `sense_relation`：同义 / 反义 / 上下位 / 派生。2026-08-07。

见 `docs/SCHEMA.md` §2。这是 v2 十二张表的**最后一张**。
源头一直有这批数据，**一条没用过**。

═══ 源头给了什么（实测，非记忆）═══
扫 kaikki 西语切片 807,155 个条目：

    义项级 synonyms      52,545      条目级 derived        30,098   ← `pie` → `a contrapié`（习语/派生）
    义项级 related       20,969      条目级 related        13,081
    义项级 antonyms       2,510      条目级 hyponyms        1,068
    其余（上下位/整体部分/并列词）合计约 3,000

⚠️ 记忆里记的「同义词 8.5 万 / 习语 4.6 万」与实测对不上，以本文数字为准。

═══ 🔴 义项级关系怎么挂：用 gloss 原文，不用 kaikki 的义项下标 ═══
kaikki 的 `senses[i].synonyms` 天然带一个下标 i，但**下标是行号契约的又一个变体**：
我们的义项经过归并、去重、重编号，i 早就对不上了。

⇒ 判据是 **gloss 原文精确匹配** `sense_src.text`（lang='en'）。
   实测 **76,325 / 78,290 = 97.5% 精确命中**，匹配不上的 1,958 条降级挂到词级。

条目级关系（`derived` 等）本来就没有义项归属，一律挂词级（`sense_id` 为 NULL）。

═══ 结构 ═══
    sense_relation(id, word_id, sense_id, kind, target, tags, src, src_ref)

  · `kind` synonym / antonym / hypernym / hyponym / holonym / meronym /
           coordinate / related / derived
  · `target` 目标词形（原样）。**不解析成 target_word_id** ——
    源头给的可能是短语（`a cuatro pies`）或库里没有的词，硬指会造出悬空外键。
    展示层拿 `target` 去查，查得到就给链接，查不到就纯文本。
  · `src_ref` 回源坐标：`kk:<word>#sense:<gloss 前 40 字>` 或 `kk:<word>#entry`

═══ 三道闸 ═══
① 可逆性回核：与 dump **双向**集合比对（全量，非抽样）
② 不变量断言：主键无重、无孤儿、sense_id 必属于同一个 word_id
③ 抽样：确定性转换，不适用

用法（在仓库根）：
    python3 -m es.pipeline.build_relation_layer
    python3 -m es.pipeline.build_relation_layer --apply
"""
import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

TABLE = "sense_relation"
# kaikki 的键 → 我们的 kind。**单数**，与 sense_tag.kind 的风格一致。
KINDS = {"synonyms": "synonym", "antonyms": "antonym",
         "hypernyms": "hypernym", "hyponyms": "hyponym",
         "holonyms": "holonym", "meronyms": "meronym",
         "coordinate_terms": "coordinate", "related": "related",
         "derived": "derived"}
# 🔴 `derived` **两级都有**，第一版只把它放进 ENTRY_KEYS ⇒ 义项级的一条没收，
#    漏掉 20,460 条（`agente` 的 17 个派生词 `agente comercial`/`agente de bolsa`…
#    全挂在义项级，条目级是空的）。2026-08-10 由外锚闸
#    `verify_vs_dump.py` 逮到 —— 库内自证的闸永远发现不了这种漏：
#    收进来的每一条都对得上，只是少了两万条。
# ⇒ 两个集合都取 KINDS 全集。同一条关系两级都出现时由末尾的
#    `(did, sid, kind, target)` 去重收掉。
SENSE_KEYS = tuple(KINDS)
ENTRY_KEYS = tuple(KINDS)

DDL = """CREATE TABLE sense_relation (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id  INTEGER NOT NULL,        -- → dict.id（关系的出发点）
  sense_id INTEGER,                 -- → sense.id；NULL = 只知道属于这个词，不知道哪条义项
  kind     TEXT NOT NULL,           -- synonym / antonym / hypernym / … / derived
  target   TEXT NOT NULL,           -- 目标词形原样，不解析成外键（见 docstring）
  tags     TEXT,                    -- 源头 tags 的 JSON 数组（slang / Mexico 等）
  src      TEXT NOT NULL,
  src_ref  TEXT NOT NULL,
  UNIQUE(word_id, sense_id, kind, target)
)"""
IDX = ["CREATE INDEX idx_rel_word ON sense_relation(word_id)",
       "CREATE INDEX idx_rel_sense ON sense_relation(sense_id)",
       "CREATE INDEX idx_rel_target ON sense_relation(target)",
       "CREATE INDEX idx_rel_kind ON sense_relation(kind)"]


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def collect(con):
    dictid = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    # 词 → {英文 gloss 原文: sense_id}
    gl = collections.defaultdict(dict)
    for w, txt, sid in con.execute(
            "SELECT d.word, sr.text, sr.sense_id FROM sense_src sr "
            "JOIN dict d ON d.id = sr.word_id WHERE sr.lang='en'"):
        gl[w].setdefault(txt.strip(), sid)

    rows, stat = [], collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        e = json.loads(line)
        if e.get("lang_code") != "es":
            continue
        w = (e.get("word") or "").strip()
        did = dictid.get(w)
        if did is None:
            continue

        def add(kind, items, sid, ref):
            for it in items or []:
                t = norm(it.get("word") if isinstance(it, dict) else it)
                if not t or t == w:            # 自指没有意义
                    stat["  空或自指（丢）"] += 1
                    continue
                tg = [x for x in (it.get("tags") or []) if x] if isinstance(it, dict) else []
                rows.append((did, sid, kind, t,
                             json.dumps(tg, ensure_ascii=False) if tg else None,
                             "en-edition", ref))
                stat[("义项级 " if sid else "词级   ") + kind] += 1

        for s in e.get("senses", []):
            g = norm((s.get("glosses") or [""])[0])
            sid = gl.get(w, {}).get(g)
            if sid is None and any(s.get(k) for k in SENSE_KEYS):
                stat["🔴 gloss 匹配不上，降级挂词级"] += 1
            ref = f"kk:{w}#sense:{g[:40]}"
            for k in SENSE_KEYS:
                add(KINDS[k], s.get(k), sid, ref)
        for k in ENTRY_KEYS:
            add(KINDS[k], e.get(k), None, f"kk:{w}#entry")
    return rows, stat


def verify(con) -> None:
    """闸① 与 dump 双向集合比对（全量，非抽样）。"""
    print("\n═══ 闸① 可逆性回核（全量，非抽样）═══")
    have = collections.defaultdict(set)
    for w, kind, target in con.execute(
            "SELECT d.word, r.kind, r.target FROM sense_relation r "
            "JOIN dict d ON d.id = r.word_id"):
        have[w].add((kind, target))
    dictw = {w for (w,) in con.execute("SELECT word FROM dict")}
    want = collections.defaultdict(set)
    for line in open(paths.KK, encoding="utf-8"):
        e = json.loads(line)
        if e.get("lang_code") != "es":
            continue
        w = (e.get("word") or "").strip()
        if w not in dictw:
            continue
        for s in e.get("senses", []):
            for k in SENSE_KEYS:
                for it in (s.get(k) or []):
                    t = norm(it.get("word") if isinstance(it, dict) else it)
                    if t and t != w:
                        want[w].add((KINDS[k], t))
        for k in ENTRY_KEYS:
            for it in (e.get(k) or []):
                t = norm(it.get("word") if isinstance(it, dict) else it)
                if t and t != w:
                    want[w].add((KINDS[k], t))
    miss = sum(len(want[w] - have[w]) for w in want)
    extra = sum(len(have[w] - want.get(w, set())) for w in have)
    n = sum(len(v) for v in want.values())
    print(f"  回 dump 核对 {n:,} 组去重后的 (kind, target)")
    print(f"    dump 有、库里没：{miss}")
    print(f"    库里有、dump 没：{extra}   ← 凭空多出来的关系")
    assert miss == 0 and extra == 0
    print("  ✅ 闸① 通过：与 dump 双向一致")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows, stat = collect(con)
    # sense_id 必须属于同一个 word_id
    owner = dict(con.execute("SELECT id, word_id FROM sense"))
    con.close()

    seen, uniq = set(), []
    for r in rows:
        k = (r[0], r[1], r[2], r[3])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    print(f"待写 {len(uniq):,} 条（去重前 {len(rows):,}）")
    for k, v in stat.most_common():
        print(f"  {k:<34}{v:>8,}")

    print("\n═══ 闸② 不变量断言 ═══")
    cross = [r for r in uniq if r[1] is not None and owner.get(r[1]) != r[0]]
    print(f"  sense_id 不属于该 word_id 的：{len(cross)}")
    assert not cross
    orphan = [r for r in uniq if r[1] is not None and r[1] not in owner]
    print(f"  悬空 sense_id：{len(orphan)}")
    assert not orphan
    n_sense = sum(1 for r in uniq if r[1] is not None)
    print(f"  挂到义项的 {n_sense:,}  {n_sense/len(uniq)*100:.1f}%   "
          f"只挂到词的 {len(uniq)-n_sense:,}")

    dbtool.sample_check(
        [(r[2], r[3][:26], "义项级" if r[1] else "词级") for r in uniq[:12]],
        12, ("关系", "目标", "挂载"))

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("build-relation-layer", expect={}) as s:
        s.execute(f"DROP TABLE IF EXISTS {TABLE}")
        s.execute(DDL)
        for i in IDX:
            s.execute(i)
        s.executemany(
            "INSERT INTO sense_relation (word_id,sense_id,kind,target,tags,src,src_ref)"
            " VALUES (?,?,?,?,?,?,?)", uniq)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    q = lambda x: con.execute(x).fetchone()[0]          # noqa: E731
    print(f"\n落库核对：sense_relation {q('SELECT COUNT(*) FROM sense_relation'):,} 条 / "
          f"{q('SELECT COUNT(DISTINCT word_id) FROM sense_relation'):,} 个词")
    for r in con.execute("SELECT kind, COUNT(*) FROM sense_relation GROUP BY 1 ORDER BY 2 DESC"):
        print(f"    {r[0]:<12}{r[1]:>8,}")
    hit = q("SELECT COUNT(*) FROM sense_relation WHERE target IN (SELECT word FROM dict)")
    print(f"  target 在库里查得到的（可给链接）：{hit:,}  "
          f"{hit/q('SELECT COUNT(*) FROM sense_relation')*100:.1f}%")
    verify(con)
    con.close()


if __name__ == "__main__":
    main()
