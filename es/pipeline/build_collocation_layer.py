#!/usr/bin/env python3
"""把 `dict.collocation` 拆成 `collocation` + `collocation_gloss` 两张表。2026-08-07。

见 `docs/SCHEMA.md` §7.1。这是 v2 三处「目标语言出口」的第二处
（第一处 `sense_gloss` 已建，第三处 `example_gloss` 待建）。

═══ 🔴 为什么这一列**不改就做不了多语言** ═══
现在 28,960 条搭配把西语短语和中文**粘在同一个字符串里**：

    "entrada gratis 免费入场"

展示层（`spanish.ts` 的 `parseCollocations`）靠正则
`^(.+?)\\s+([一-鿿…].*)$`「从第一个汉字处切开」分离。三个问题：

1. **越南语用拉丁字母，找不到「第一个汉字」** —— 加一门语言这一列直接报废
2. **切分发生在每次渲染时，不留痕迹** —— 切错了没有任何记录
3. 实测已经在错：**95 条切不开**（0.33%），用户看到的是整串当西语、中文为空：

       rayos X X射线            第一个汉字「射」前面是字母 X 不是空格 ⇒ 正则不匹配
       do mayor C大调
       estándar Unicode Unicode标准

═══ 判据：第一个汉字**之前的最后一个空格** ═══
不是「第一个汉字处」，而是「第一个汉字之前的最后一个空格」——
这样跨语言的那个符号（X / C / Unicode / PIN）会跟着中文走，而它本来就属于中文那半：

    rayos X X射线   →  es="rayos X"           zh="X射线"      ✅
    as de espadas 黑桃A → es="as de espadas"   zh="黑桃A"      ✅

实测 **28,960 条 100% 干净切开**（旧判据 99.48%），西语部分无一含汉字。

═══ 结构 ═══
    collocation(id, word_id, sense_id, text, rank)
    collocation_gloss(collocation_id, lang, text, src)

`sense_id` 本轮全为 NULL：`pie de página`(页脚) 与 `pie de mesa`(桌脚) 分属不同义项，
但把搭配挂回义项需要语义判断，是编纂工作，不是这一步的机械转换。列先建出来。

═══ 三道闸（`docs/SCHEMA.md` §5.0）═══
① 可逆性回核：从新表**重建**出 `dict.collocation` 的每一行，逐字节比对（100%，非抽样）
② 不变量断言：行数守恒 / 主键无重 / 无孤儿
③ 抽样：本步骤是确定性转换，无需判断的部分，故不适用

用法（在仓库根）：
    python3 -m es.pipeline.build_collocation_layer
    python3 -m es.pipeline.build_collocation_layer --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

CJK = re.compile(r"[一-鿿　-〿＀-￯]")
TABLES = ("collocation", "collocation_gloss")
DDL = [
    """CREATE TABLE collocation (
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         word_id  INTEGER NOT NULL,     -- → dict.id
         sense_id INTEGER,              -- → sense.id；本轮全 NULL，挂回义项是编纂工作
         text     TEXT NOT NULL,        -- 西语短语原文
         rank     INTEGER NOT NULL,     -- 该词内顺序，保源序
         UNIQUE(word_id, rank)
       )""",
    """CREATE TABLE collocation_gloss (
         collocation_id INTEGER NOT NULL,
         lang           TEXT NOT NULL,  -- zh / vi …（加语言只往这里加行）
         text           TEXT NOT NULL,
         src            TEXT,
         PRIMARY KEY(collocation_id, lang)
       )""",
]
IDX = [
    "CREATE INDEX idx_col_word ON collocation(word_id)",
    "CREATE INDEX idx_col_sense ON collocation(sense_id)",
    "CREATE INDEX idx_colg_lang ON collocation_gloss(lang)",
]


def split_line(ln: str):
    """→ (西语, 中文|None)。判据见 docstring。"""
    m = CJK.search(ln)
    if not m:
        return ln, None                      # 整行无中文
    i = ln.rfind(" ", 0, m.start())
    if i <= 0:
        return None, ln                      # 整行是中文
    return ln[:i].strip(), ln[i + 1:].strip()


def collect(con):
    cols, glosses = [], []
    stat = collections.Counter()
    cid = 0
    for did, raw in con.execute(
            "SELECT id, collocation FROM dict WHERE collocation IS NOT NULL"):
        rank = 0
        for ln in raw.split("\n"):
            ln = ln.strip()
            if not ln:
                stat["空行（丢）"] += 1
                continue
            es, zh = split_line(ln)
            if es is None:
                stat["🔴 整行是中文，无西语"] += 1
                continue
            cid += 1
            rank += 1
            cols.append((cid, did, rank, es))
            stat["搭配"] += 1
            if zh:
                glosses.append((cid, "zh", zh, "dict-collocation"))
                stat["  有中文"] += 1
            else:
                stat["  🔴 无中文"] += 1
    return cols, glosses, stat


def verify(con) -> None:
    """闸① 从新表重建 `dict.collocation`，逐字节比对（100%，非抽样）。"""
    print("\n═══ 闸① 可逆性回核（全量，非抽样）═══")
    zh = dict(con.execute(
        "SELECT collocation_id, text FROM collocation_gloss WHERE lang='zh'"))
    rebuilt = collections.defaultdict(list)
    for cid, did, rank, text in con.execute(
            "SELECT id, word_id, rank, text FROM collocation ORDER BY word_id, rank"):
        z = zh.get(cid)
        rebuilt[did].append(f"{text} {z}" if z else text)

    bad, ex, n = 0, [], 0
    for did, raw in con.execute(
            "SELECT id, collocation FROM dict WHERE collocation IS NOT NULL"):
        n += 1
        want = [x.strip() for x in raw.split("\n") if x.strip()]
        got = rebuilt.get(did, [])
        if want != got:
            bad += 1
            if len(ex) < 5:
                ex.append((did, want[:2], got[:2]))
    print(f"  重建 {n:,} 个词的搭配串，与 `dict.collocation` 逐字节比对")
    print(f"  对不上的词：{bad}")
    for did, w, g in ex:
        print(f"    dict:{did}\n      原文={w}\n      重建={g}")
    assert bad == 0, "重建结果与原文不一致 —— 切分或顺序错了"
    print("  ✅ 闸① 通过：拆开再拼回去，与原文逐字节一致")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    cols, glosses, stat = collect(con)
    con.close()
    for k, v in stat.most_common():
        print(f"  {k:<22}{v:>8,}")
    print(f"\ncollocation       {len(cols):>8,}")
    print(f"collocation_gloss {len(glosses):>8,}")

    print("\n═══ 闸② 不变量断言 ═══")
    ids = {c[0] for c in cols}
    assert len(ids) == len(cols)
    dup = collections.Counter((c[1], c[2]) for c in cols)
    bad = [k for k, v in dup.items() if v > 1]
    print(f"  (word_id, rank) 重复：{len(bad)}")
    assert not bad
    assert {g[0] for g in glosses} <= ids, "gloss 指向不存在的搭配"
    withcjk = [c for c in cols if CJK.search(c[3])]
    print(f"  🔴 西语部分仍含汉字：{len(withcjk)}  {[c[3] for c in withcjk[:3]]}")
    assert not withcjk
    nozh = len(cols) - len(glosses)
    print(f"  无中文的搭配：{nozh}")

    dbtool.sample_check(
        [(c[3][:34], dict((g[0], g[2]) for g in glosses).get(c[0], "—")[:20])
         for c in cols[:10]], 10, ("西语搭配", "中文"))

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("build-collocation-layer", expect={}) as s:
        for t in TABLES:
            s.execute(f"DROP TABLE IF EXISTS {t}")
        for d in DDL:
            s.execute(d)
        for i in IDX:
            s.execute(i)
        s.executemany(
            "INSERT INTO collocation (id, word_id, rank, text) VALUES (?,?,?,?)", cols)
        s.executemany(
            "INSERT INTO collocation_gloss (collocation_id, lang, text, src) "
            "VALUES (?,?,?,?)", glosses)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    q = lambda x: con.execute(x).fetchone()[0]          # noqa: E731
    print("\n落库核对：")
    for t in TABLES:
        print(f"  {t:<20}{q(f'SELECT COUNT(*) FROM {t}'):>8,}")
    print(f"  悬空 word_id {q('SELECT COUNT(*) FROM collocation WHERE word_id NOT IN (SELECT id FROM dict)')}")
    verify(con)
    need_vi = q("SELECT COUNT(*) FROM collocation c WHERE NOT EXISTS ("
                "SELECT 1 FROM collocation_gloss g "
                "WHERE g.collocation_id=c.id AND g.lang='vi')")
    print(f"\n⭐ 加一门语言 = 往 collocation_gloss 加行。缺越南语的搭配：{need_vi:,}")
    con.close()


if __name__ == "__main__":
    main()
