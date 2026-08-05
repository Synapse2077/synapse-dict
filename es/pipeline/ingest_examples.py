#!/usr/bin/env python3
"""例句入库：七个源全收，去重后单独成表。2026-08-04。

═══ 为什么单独一张表 ═══
例句是 **1:N** 的（一个词形挂多句，每句带自己的出处、高亮位置、源义项），
塞进 `dict` 的扁平列就得用分隔符打包，日后要按句处理只能反复切串。
理由不是"数量大"——去重后 50,766 条，只有 `dict` 表的 4.5%——**是结构**。

═══ 本轮只做收集，不做筛选、不做翻译 ═══
用户 2026-08-04：「先把例句收集起来吧，用不用再说，也暂时不用翻译。」
所以：
  · `zh` 留空（源里几乎没有中文：带译文的 28.5% 译的也是各版自己的语言）；
  · **不筛**。已知这批质量参差：62.2% 带 `ref` 是文献引用、中位数 106 字符偏长、
    且混着古语（`alemán` 有一条是中世纪西语 `et estando ý çinco días…`）。
    筛选判据等决定要用的时候再定，现在筛了反而丢信息。

═══ 存什么：能捡的都捡，捡不回来的绝不丢 ═══
`src_gloss` 是**日后做义项级挂载的桥**。例句在源里是挂在某条义项下的，
那个义项的 gloss 文本存下来，将来才能把它对到我们的义项上；
只存"第几条"是不行的——义项顺序会变（2026-08-04 刚重排过 4,381 行）。
`src_translation` 是源自带的译文（法语/德语…），对中文用户没用，
但**日后翻中文时可以当第二参照**，不存白不存。

═══ 去重与优先级 ═══
按 `(word, text)` 去重；同一句多个源给时，按 es版 → 英文版 → fr → de → it → pt → zh
的顺序取第一个（本族语版对西语句子的收录与标注最可信）。

═══ 闸门 ═══
建新表不碰 `dict` ⇒ `expect={}`，这道闸正好用来证明「我只加了张表，主表一个字节没动」。
⚠️ `dbtool.snapshot()` 只统计 `dict` 的列，**新表的行数不在它的视野里** ——
本脚本自己打印写入行数并做去重断言，闸门管不到这一层。
"""
import argparse
import collections
import gzip
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                    # noqa: E402
import paths                                                     # noqa: E402

DUMPS = paths.DUMPS
# 顺序即优先级
SOURCES = [
    ("es-edition", paths.EDITION, "gz"),
    ("en-edition", paths.KK, "txt"),
    ("fr-edition", DUMPS / "frwiktionary.jsonl.gz", "gz"),
    ("de-edition", DUMPS / "dewiktionary.jsonl.gz", "gz"),
    ("it-edition", DUMPS / "itwiktionary.jsonl.gz", "gz"),
    ("pt-edition", DUMPS / "ptwiktionary.jsonl.gz", "gz"),
    ("zh-edition", DUMPS / "zhwiktionary.jsonl.gz", "gz"),
]
SRC_LANG = {"es-edition": "es", "en-edition": "en", "fr-edition": "fr",
            "de-edition": "de", "it-edition": "it", "pt-edition": "pt",
            "zh-edition": "zh"}

DDL = """
CREATE TABLE IF NOT EXISTS example (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  word            TEXT NOT NULL,
  dict_id         INTEGER,          -- 预留：等义项稳定标识(sid)做完再定到具体行
  sid             TEXT,             -- 预留：义项稳定标识
  text            TEXT NOT NULL,    -- 西语原句
  zh              TEXT,             -- 中文译文；本轮不做
  zh_src          TEXT,
  bold            TEXT,             -- JSON [[start,end],…]，词形在句中的位置，供高亮
  ref             TEXT,             -- 文献出处
  src_gloss       TEXT,             -- 源里这条例句挂在哪条义项下（日后义项对齐的桥）
  src_translation TEXT,             -- 源自带的译文（各版自己的语言，非中文）
  src_lang        TEXT,             -- 上一列是什么语言
  src             TEXT NOT NULL,    -- 哪个版本给的
  UNIQUE(word, text)
)
"""
IDX = ["CREATE INDEX IF NOT EXISTS idx_example_word ON example(word)",
       "CREATE INDEX IF NOT EXISTS idx_example_dict ON example(dict_id)"]


def opener(path, kind):
    if kind == "gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def harvest():
    """→ {(word, text): row}，按 SOURCES 顺序先到先得。"""
    out = {}
    stat = collections.Counter()
    for src, path, kind in SOURCES:
        if not Path(path).exists():
            print("   ⚠️ 缺文件，跳过：%s" % path)
            continue
        t = time.time()
        got = 0
        with opener(path, kind) as fh:
            for ln in fh:
                # 便宜预筛。⚠️ 这里可以按 lang_code 筛，因为它是**顶层字段**；
                # 不能学 B1 那样按义项内容筛（同词的不同 pos 块是独立行）。
                if '"lang_code": "es"' not in ln:
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get("lang_code") != "es":
                    continue
                w = e.get("word")
                if not w:
                    continue
                for s in e.get("senses") or []:
                    gloss = " ".join(s.get("glosses") or []).strip() or None
                    for x in s.get("examples") or []:
                        txt = (x.get("text") or "").strip()
                        if not txt:
                            continue
                        key = (w, txt)
                        if key in out:
                            stat["重复（已有更优先的源）"] += 1
                            continue
                        bold = x.get("bold_text_offsets")
                        out[key] = (
                            w, None, None, txt, None, None,
                            json.dumps(bold, ensure_ascii=False) if bold else None,
                            (x.get("ref") or "").strip() or None,
                            gloss,
                            (x.get("translation") or "").strip() or None,
                            SRC_LANG[src] if x.get("translation") else None,
                            src,
                        )
                        got += 1
        stat["收自 " + src] = got
        print("   %-12s +%-7d 条  (%.0fs)" % (src, got, time.time() - t))
    return out, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    print("■ 扫七个源")
    rows, stat = harvest()
    print("\n■ 去重后 %d 条（重复丢弃 %d）" % (len(rows), stat["重复（已有更优先的源）"]))

    # 与库对照：例句的词形我们有没有
    import sqlite3
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    known = {w for (w,) in conn.execute("SELECT DISTINCT word FROM dict")}
    conn.close()
    words = {k[0] for k in rows}
    orphan = words - known
    n_orphan = sum(1 for k in rows if k[0] in orphan)
    print("   覆盖词形 %d（库里有 %d，库里没有 %d ⇒ 例句 %d 条暂成孤儿，**照存不丢**）"
          % (len(words), len(words - orphan), len(orphan), n_orphan))

    have_ref = sum(1 for v in rows.values() if v[7])
    have_tr = sum(1 for v in rows.values() if v[9])
    print("   带 ref %d (%.1f%%) ｜ 带源译文 %d (%.1f%%) ｜ 带高亮位置 %d"
          % (have_ref, have_ref / len(rows) * 100, have_tr, have_tr / len(rows) * 100,
             sum(1 for v in rows.values() if v[6])))

    samples = [(v[0], v[3][:52]) for v in list(rows.values())[:10]]
    dbtool.sample_check(samples, 10, ("词", "例句"))

    if not a.apply:
        print("\n(预览。确认后 --apply)")
        return

    plan = list(rows.values())
    # 建新表不碰 dict ⇒ 所有被 TRACK 的列变化必须为 0
    with dbtool.session("ingest-examples", expect={}) as s:
        s.execute(DDL)
        for q in IDX:
            s.execute(q)
        s.executemany(
            "INSERT OR IGNORE INTO example "
            "(word,dict_id,sid,text,zh,zh_src,bold,ref,src_gloss,src_translation,src_lang,src) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", plan)

    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = conn.execute("SELECT COUNT(*) FROM example").fetchone()[0]
    d = conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM example GROUP BY word,text)").fetchone()[0]
    conn.close()
    print("■ example 表现有 %d 行（唯一 word+text %d）" % (n, d))
    assert n == d, "去重断言失败：表里有重复的 (word,text)"
    print("■ 去重断言通过 ✓")


if __name__ == "__main__":
    main()
