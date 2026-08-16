#!/usr/bin/env python3
"""补跑 flash 留空的那批，换 v4-pro。2026-08-14，阶段 3c 收尾。

═══ 为什么有这一步 ═══
flash 按 prompt 规则六「没把握就输出空」，留下 **1,546 条义项 / 1,444 个词形**
一条中文都没有 —— 这正是我先前反对 fr 收词时说的「空壳」，结果我自己造了 1,444 个。
构成：专名 1,026 / 普通词 487 / 词缀 19 / 符号 14。

⇒ 换 v4-pro（更强、量小、开思考）重跑。**仍然空的那些，把 dict 行删掉** ——
   按我自己的判据，什么都没有的词条比未收录更伤。

⚠️ 不放宽「没把握就留空」这条规则：宁可删行，也不要编造的中文。

用法（在 it/ 目录下）：
    python3 pipeline/retry_fr_empty.py --run
    python3 pipeline/retry_fr_empty.py --merge
    python3 pipeline/retry_fr_empty.py --prune    # 仍为空的，删词条
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
import translate_it_defs as T   # noqa: E402

MODEL = "deepseek-v4-pro"
SRC = MODEL + ":via-fr"
OUT = paths.WORK / "fr_defs_zh_retry.jsonl"

SYS = """你是法语—中文词典助手。输入是**意大利语词条在法语维基词典里的释义**。
这批是上一轮模型判为"没把握"而留空的难例：多为专名、词缀、符号。请尽量给出可用的中文。

规则：
1. 专名（人名/地名/机构）：给通用中译名；没有通用译名就音译，后面用中文括号标类别，
   如 `杰迪里耶（摩洛哥地名）`。**专名几乎总能音译，不要留空。**
2. 词缀：给这个词缀在中文里的意思，格式如 `-性（后缀，表性质）`、`前缀，表…`。
   **不要**把法语词缀原样抄过来。
3. 符号/标记：说明它标的是什么，如 `中性标记`。
4. 句末不加标点；多个义项用中文逗号分隔，最多 3 个。
5. 不要出现"意为""指""该词"这类元话语。
6. **实在无法确定含义时才输出空字符串 ""** —— 但音译型专名不属于此列。

输入是 JSON 数组，每项有 `id`、`word`（意语词形）、`it`（法语释义）。
输出**只有** JSON 数组，每项 {"id": 原样, "zh": "中文"}，不要围栏、不要解释。"""


def pending(con):
    return [dict(id=r[0], word=r[1], it=r[2]) for r in con.execute(
        "SELECT s.id, d.word, x.text FROM sense_src x JOIN sense s ON s.id=x.sense_id "
        "JOIN dict d ON d.id=s.word_id WHERE x.src='fr-edition' AND NOT EXISTS("
        "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh') ORDER BY s.id")]


def main():
    ap = argparse.ArgumentParser()
    for f in ("run", "merge", "prune"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pending(con)
    print("■ 仍无中文的义项 %s 条" % f"{len(items):,}")

    if a.run:
        T.SYS = SYS
        T.MODEL = MODEL
        T.CHUNK = 15                      # v4-pro 慢但强，块小一点
        OUT.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(T.run_batches(items, OUT, conc=4))
        return 0

    if a.merge:
        got = {}
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            if r["zh"]:
                got[r["id"]] = r["zh"]
        ids = {x["id"] for x in items}
        rows = [(sid, zh, SRC) for sid, zh in got.items() if sid in ids]
        print("■ v4-pro 补出 %s 条（原 %s 条空）" % (f"{len(rows):,}", f"{len(items):,}"))
        con.close()
        with dbtool.session("fr-zh-retry", expect={"#sense_gloss": len(rows)}) as s:
            s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                          "VALUES (?,'zh','equivalent',0,?,?)", rows)
        print("■ 已写入")
        return 0

    if a.prune:
        # 仍然一条中文都没有的**词形**：整行删掉（连同义项与证据）
        dead = [r[0] for r in con.execute(
            "SELECT d.id FROM dict d WHERE d.id IN (SELECT word_id FROM sense_src WHERE src='fr-edition') "
            "AND NOT EXISTS(SELECT 1 FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
            "AND g.lang='zh' WHERE s.word_id=d.id)")]
        n_s = con.execute("SELECT count(*) FROM sense WHERE word_id IN (%s)"
                          % ",".join("?" * len(dead)), dead).fetchone()[0] if dead else 0
        n_x = con.execute("SELECT count(*) FROM sense_src WHERE word_id IN (%s)"
                          % ",".join("?" * len(dead)), dead).fetchone()[0] if dead else 0
        print("■ 仍为空壳的词形 %s 个（义项 %s / 证据 %s）—— 删掉"
              % (f"{len(dead):,}", f"{n_s:,}", f"{n_x:,}"))
        for w, in list(con.execute("SELECT word FROM dict WHERE id IN (%s) LIMIT 6"
                                   % ",".join("?" * len(dead)), dead)) if dead else []:
            print("     %s" % w)
        con.close()
        if not dead:
            return 0
        marks = ",".join("?" * len(dead))
        with dbtool.session("prune-fr-shells",
                            expect={"__rows__": -len(dead), "#sense": -n_s, "#sense_src": -n_x}) as s:
            s.execute("DELETE FROM sense_src WHERE word_id IN (%s)" % marks, dead)
            s.execute("DELETE FROM sense WHERE word_id IN (%s)" % marks, dead)
            s.execute("DELETE FROM dict WHERE id IN (%s)" % marks, dead)
        print("■ 已删")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
