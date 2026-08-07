#!/usr/bin/env python3
"""西语版义项补收：把 es.wiktionary 的单语义项收成结构化的一张表。2026-08-05。

═══ 为什么会漏，漏了多少 ═══
`ingest_edition.py`（2026-08-03）的第一行写着「把西语版里**我们没有的词形**收进库」——
它是一次**词汇**收录，不是**释义**收录。对已经存在的词，西语版的释义一条没取。
2026-08-05 实测这个缺口：

    两边都有的词                    100,448
    其中 definition_es 为空          46,373   (46.2%)   ← 完全没收
    这批词西语版共有义项            100,838 条
    我们手上对应的英文义项           76,127 条

差距集中在**最常用的词**上，而且性质不同——不是「更多」，是「更像词典」：

    hacer  (A1)   我们 15 条英文  vs  西语版 59 条
    correr (A1)   我们 13 条      vs  西语版 37 条
    ojo    (A1)   我们  4 条      vs  西语版 25 条

`ojo` 我们给的是 eye / keyhole / caution —— **翻译对应词**；
西语版给的是「Órgano sensible a la luz que permite la visión」「Por metonimia, precaución」
—— **单语定义 + 语义关系标注**。后者才是词典，前者是词汇表。

✅ 已收的那批是干净的：54,075 个词里 54,042 个（99.9%）收全了，只有 33 个共差 35 条义项
   （tragasable / sutelesar 这类生僻词）。所以缺口就是上面那个数，不用返工。

═══ 🔴 为什么必须另建表，不能写进 definition_es ═══
义项四列（`definition` / `definition_es` / `translation` / `meta`）是**按行号一一对应**的：
第 i 行是同一个义项的英文、西语、中文、语法标记。空行是「这个义项没有英文」的占位，
不是噪声（`novia` 那个坑就是丢了占位行导致中英张冠李戴）。

现有数据能工作，靠的是一条**没写下来的隐式前提**：en 与 es 严格互斥。
实测 54,206 个有 `definition_es` 的词里，**英文释义非空的恰好 0 个** —— 因为当初只收了
我们没有的词，那些词天生没有英文释义，西语义项直接占满行号。

而这次要补的 46,373 个词**英文释义全都有**（只有 45 个是空的）。两边的义项切分又不是
同一套（15 条 vs 59 条），按行号塞进去就是把 `novia` 那个错配放大到四万六千个词。
⇒ **另建 `sense_es` 表，`dict` 一个字节不动。** 错了删表就回去了。

义项**合并**（把 59 条西语义项和 15 条英文义项做语义匹配、并成一套）是另一件事，
必须等原文安全落库之后再谈：义项是所有其他字段挂靠的锚点，合错一次，
中文/语法标记/语域全跟着错位，而且**合完就再也拆不开**。

═══ 收全部 109,191 个词，不只收缺的 46,373 个 ═══
本表的含义必须一句话说得清：「**西语版对这个词说了什么**」。
如果它有时有、有时没有（取决于历史上哪一轮收录碰过这个词），那么日后每个用它的人
都得先了解这段历史——这正是最容易烂掉的那种隐式知识。
⇒ 宁可让 54,075 个词的义项与 `dict.definition_es` 内容重复（同一份 dump 的冻结副本，
   不存在「两个真相源会漂移」的问题），换一张含义均匀的表。代价是几十 MB。

═══ 🔴 2026-08-06 补：去掉 `is_lemma=1` 闸门 ═══
上一版这里写的是 `... from dict where is_lemma=1`。那道闸门违反了上面刚立的规矩
——它让本表的含义变成「西语版对**我们判成原形的**词说了什么」，又一条得靠人记的历史。
后果实测：

    西语版当词条（`pos_title` 不以 "Forma " 开头）、我们判成变形层的词   5,701
    因此收不进来的义项                                              8,506

这批不是零头，是 `levantarse`（起床，2,323 个 Verbo pronominal 之一）、`absuelto`、
`elecciones`、`ratoncito` 这类**界面上一条释义都没有**的词。

⚠️ 判据两边并不矛盾，两边都对：kaikki 英文版说 `levantarse` 是 `levantar` 的自复不定式
   （真的），西语版说它是个有三条自己的释义的词条（也是真的）。
   ⇒ 本脚本只做**收录**，`dict.is_lemma` 一个字节不动 —— 「反身动词/指小词算不算
     独立词条」是词典学取舍，不是这里能顺手决定的事，留给 `docs/SCHEMA.md` 的词/词形重设计。
   （另有 3,890 个**异体拼写**被误判成变形层，那批是源头判据被误用、不是取舍问题，
     已由 `fixes/fix_altof_lemma.py` 确定性修掉并翻成 lemma。）

`dict.word` 全库唯一（1,136,294 行 = 1,136,294 个 distinct word），所以去掉闸门后
`dict_id` 的挂载依然无歧义。

═══ 闸门 ═══
建新表不碰 `dict` ⇒ `expect={}`。
⚠️ `dbtool.snapshot()` 只统计 `dict` 的列，新表不在它视野里，本脚本自己做计数断言。

用法（在仓库根）：
    python3 -m es.pipeline.ingest_es_senses --scan          # 只统计，不写库
    python3 -m es.pipeline.ingest_es_senses --limit 500     # 试跑
    python3 -m es.pipeline.ingest_es_senses                 # 全量
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool          # noqa: E402
import paths           # noqa: E402

# `extract_cache` 的产物；没有就现扫 dump 重建（96 MB gz，约 4 分钟）
CACHE = paths.WORK / "edition_senses_es.jsonl"
FORM_TITLE = "Forma "          # 西语版变形条目的 pos_title 前缀，见 ingest_edition.py

DDL = """
CREATE TABLE IF NOT EXISTS sense_es (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  word      TEXT NOT NULL,
  dict_id   INTEGER,          -- 指向 dict 的 lemma 行
  idx       INTEGER NOT NULL, -- 西语版内部义项序号，从 0；**不与 dict 的义项行号对应**
  gloss     TEXT NOT NULL,    -- 西语单语定义原文
  pos       TEXT,             -- 西语版给的 pos
  pos_title TEXT,             -- 西语版 pos_title 原文（Sustantivo masculino / Verbo transitivo…）
  tags      TEXT,             -- JSON array
  raw_tags  TEXT,             -- JSON array
  zh        TEXT,             -- 中文；本轮不做，留给翻译那步
  zh_src    TEXT,
  src       TEXT NOT NULL,    -- 恒为 es-edition
  UNIQUE(word, idx)
)
"""
IDX = ["CREATE INDEX IF NOT EXISTS idx_sense_es_word ON sense_es(word)",
       "CREATE INDEX IF NOT EXISTS idx_sense_es_dict ON sense_es(dict_id)"]


def build_cache() -> None:
    """现扫 dump 重建缓存。只取 lang_code=es 且非变形的条目。"""
    out = collections.defaultdict(list)
    n = 0
    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            n += 1
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("lang_code") != "es":
                continue
            if (e.get("pos_title") or "").startswith(FORM_TITLE):
                continue
            for s in e.get("senses", []):
                for g in (s.get("glosses") or []):
                    g = (g or "").strip()
                    if g:
                        out[e.get("word")].append({
                            "g": g, "pos": e.get("pos"), "pt": e.get("pos_title"),
                            "tags": s.get("tags") or [], "raw": s.get("raw_tags") or [],
                        })
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("w", encoding="utf-8") as f:
        for w, v in out.items():
            f.write(json.dumps({"word": w, "senses": v}, ensure_ascii=False) + "\n")
    print(f"  扫 {n:,} 行 dump → 缓存 {len(out):,} 个词头")


def load_cache() -> dict:
    if not CACHE.exists():
        print(f"缓存不存在，现扫 dump 重建 → {CACHE}")
        build_cache()
    out = {}
    with CACHE.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out[d["word"]] = d["senses"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只统计，不写库")
    ap.add_argument("--limit", type=int, help="只处理前 N 个词，试跑用")
    ap.add_argument("--rebuild-cache", action="store_true")
    args = ap.parse_args()

    if args.rebuild_cache:
        build_cache()
    cache = load_cache()
    print(f"西语版词头（西语、非变形、有义项）：{len(cache):,}")

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    # 🔴 不加 is_lemma 闸门，理由见 docstring「2026-08-06 补」
    lemmas = {w: (i, de, des, lem) for w, i, de, des, lem in con.execute(
        "select word, id, definition, definition_es, is_lemma from dict")}
    have = {w for (w,) in con.execute("select distinct word from sense_es")} \
        if con.execute("select count(*) from sqlite_master where type='table' "
                       "and name='sense_es'").fetchone()[0] else set()
    con.close()
    print(f"库内词条：{len(lemmas):,}（其中 lemma "
          f"{sum(1 for v in lemmas.values() if v[3]):,}）")
    print(f"sense_es 已有的词：{len(have):,}")

    def nlines(s):
        return len([x for x in (s or "").split("\n") if x.strip()])

    both = [w for w in cache if w in lemmas]
    gap = [w for w in both if not lemmas[w][2]]          # definition_es 为空 = 这次真正补上的
    already = [w for w in both if lemmas[w][2]]
    print(f"\n两边都有的词 {len(both):,}")
    print(f"  缺 definition_es（真缺口）  {len(gap):,}   义项 {sum(len(cache[w]) for w in gap):,} 条")
    print(f"  已有 definition_es（重复收） {len(already):,}   义项 {sum(len(cache[w]) for w in already):,} 条")
    only_dump = len(cache) - len(both)
    print(f"  只在 dump 里、我们库里没这个词  {only_dump:,}  ← 不收，本表只服务库内词条")

    # 本轮相对上一轮的净增 —— 「跳过/新增」那一栏必须逐条看得见，不能只报总数
    new = [w for w in both if w not in have]
    n_lem = sum(1 for w in new if lemmas[w][3])
    print(f"\n本轮净增 {len(new):,} 个词 / {sum(len(cache[w]) for w in new):,} 条义项")
    print(f"    其中已是 lemma {n_lem:,}    仍判在变形层 {len(new) - n_lem:,}")
    for w in sorted(new, key=lambda x: -len(cache[x]))[:8]:
        print(f"      {w:<20}{len(cache[w]):>3} 条  is_lemma={lemmas[w][3]}  "
              f"{cache[w][0]['g'][:44]}")

    # 🔴 项目教训：统计里"跳过"那一栏必须逐条看得见
    print(f"\n真缺口那批，英文/西语义项数对比：")
    cmp = collections.Counter()
    for w in gap:
        en, es = nlines(lemmas[w][1]), len(cache[w])
        cmp["西语更多" if es > en else ("英文更多" if es < en else "一样多")] += 1
    for k, v in cmp.most_common():
        print(f"    {k:<8}{v:>7,}  {v/max(len(gap),1)*100:5.1f}%")

    if args.scan:
        print("\n--scan：不写库，到此为止。")
        return

    # ═══ 🔴 续跑判据必须是**词级**，不能靠 (word, idx) 的 UNIQUE 去重 ═══
    # 2026-08-06 踩到：缓存是 dump 的原样快照，而库里的行已经被
    # `clean_sense_es_residue.py`（删 87 条 wikitext 残渣）和
    # `fix_sense_es_residue2.py`（拆分/重编号）修过。两边 idx 于是对不上：
    #
    #     caer 原本 25 条，[23] 是残渣 → 清掉并重编号后只剩 [0..23]
    #     重跑时 idx=24 空着，`INSERT OR IGNORE` 就把缓存里的第 25 条又塞了回来
    #
    # ⇒ 13 条已删的残渣（`:*Sinónimos:`、`*Derivado:`、`:*Ámbito: Perú`）复活。
    # 这是项目教训「改完数据，旧的续跑记录就作废」的又一次现形：UNIQUE 约束
    # 保证的是「不重复」，**不保证「不倒退」**。
    # 词级判据对重编号免疫 —— 一个词要么整体没收过，要么已经收过（且可能已被修正）。
    skip = [w for w in both if w in have]
    words = sorted(w for w in both if w not in have)
    print(f"\n已收过、跳过 {len(skip):,} 个词；本轮处理 {len(words):,} 个")
    if args.limit:
        words = words[:args.limit]
    rows = []
    for w in words:
        did = lemmas[w][0]
        for i, s in enumerate(cache[w]):
            rows.append((w, did, i, s["g"], s.get("pos"), s.get("pt"),
                         json.dumps(s.get("tags") or [], ensure_ascii=False),
                         json.dumps(s.get("raw") or [], ensure_ascii=False),
                         None, None, "es-edition"))
    print(f"\n待写入 {len(rows):,} 行（{len(words):,} 个词）")

    dbtool.sample_check(
        [(r[0], f"#{r[2]}", r[3][:56]) for r in rows[:10]], 10, ("词", "义项号", "西语定义"))

    with dbtool.session("ingest-es-senses", expect={}) as s:
        s.execute(DDL)
        for stmt in IDX:
            s.execute(stmt)
        s.executemany(
            "INSERT OR IGNORE INTO sense_es"
            "(word,dict_id,idx,gloss,pos,pos_title,tags,raw_tags,zh,zh_src,src)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

    # 新表不在 dbtool.snapshot 视野里，自己断言
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    n_rows = con.execute("select count(*) from sense_es").fetchone()[0]
    n_words = con.execute("select count(distinct word) from sense_es").fetchone()[0]
    n_dup = con.execute(
        "select count(*) from (select word,idx from sense_es group by 1,2 having count(*)>1)"
    ).fetchone()[0]
    orphan = con.execute(
        "select count(*) from sense_es where dict_id not in (select id from dict)").fetchone()[0]
    con.close()
    print(f"\n落库核对：sense_es {n_rows:,} 行 / {n_words:,} 个词")
    print(f"  (word,idx) 重复：{n_dup}   悬空 dict_id：{orphan}")
    assert n_dup == 0, "同一个词出现重复义项号"
    assert orphan == 0, "有 dict_id 指不到 dict 行"


if __name__ == "__main__":
    main()
