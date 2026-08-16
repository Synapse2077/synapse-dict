#!/usr/bin/env python3
"""③ 真翻译那批：按 `PLAYBOOK` 5.5 的四条纪律重做。2026-08-14，阶段 3c 重做。

═══ 上一轮漏了什么 ═══
5.5 四条纪律白纸黑字写着，我的 payload 只有 `word` + `fr`：

  1. 带该词**已有的义项**   —— 漏（这批 99.4% 单义项，影响小，但多义那批会重复翻）
  2. 带上位义 parent        —— 不适用
  3. 🔴 **带词性**          —— **漏了**。`A` 的 `bishop` 是国际象棋的「象」不是主教
  4. 明说残渣不要带进中文   —— 部分做了

═══ 这一轮只做「真翻译」那批 ═══
地理句式（5,904）已由 `fix_geo_zh` 用模板做完；纯专名（12,545）现有音译是干净的。
剩下的才是需要真翻译的 —— 它们的法语侧是有实义的短语或说明。

═══ 新旧两版怎么处置 ═══
新版 payload 严格更全（多了词性与同词条其它义项）⇒ 信息上不劣于旧版。
但**不盲目覆盖**：先报两版分歧率，抽样看过再写。写入时旧版删除、新版落库，
证据层（法语原文）一个字节不动，随时可重做。

用法（在 it/ 目录下）：
    python3 pipeline/retranslate_fr_real.py --plan
    python3 pipeline/retranslate_fr_real.py --run
    python3 pipeline/retranslate_fr_real.py --diff     # 新旧分歧率 + 抽样
    python3 pipeline/retranslate_fr_real.py --apply
    python3 pipeline/retranslate_fr_real.py --verify
"""
import argparse
import asyncio
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
import translate_it_defs as T   # noqa: E402
from geo_zh import parse as geo_parse   # noqa: E402

OUT = paths.WORK / "fr_real_zh.jsonl"
SRC = "deepseek-v4-flash:via-fr-v2"

# 法语侧只是把词名重复一遍（`Ayas.` `Kirov.`）⇒ 纯音译，不归这一轮
BARE = re.compile(r"^[A-ZÀ-Þ][^.]{0,40}\.?$")

SYS = """你是意大利语—中文词典编纂员。每条给你：
`w` 意大利语词形、`pos` 词性、`fr` 它在**法语**维基词典里的释义（参考）、
`other` 该词条已有的其它中文义项（可能为空）。

给出 `w` 的**中文对应词式释义**。

🔴 以你对**意大利语**的了解为准。`fr` 只是参考 —— 法语编者有时换成法语自己的说法、
   有时丢掉语体色彩、有时比原词更窄或更宽。不一致时**以意语为准**。
🔴 `pos` 必须用上：同一个拼写在不同词性下意思不同
   （`A` 作名词在国际象棋里是「象」，不是「主教」）。
🔴 如果 `other` 非空，**不要产出与它意思重复的释义** —— 那会让同一个词并排显示两遍。

规则：
1. 输出对应词，不是长句翻译；多个用中文逗号分隔，最多 3 个
2. 句末不加任何标点
3. 不要出现"意为""指""该词"这类元话语，也不要写词性标签
4. 习语/谚语给**地道的中文说法**；带语体色彩的（粗俗、俚语、文语）要在中文里体现
5. 学名、`:*` 之类的抓取残渣不要带进中文
6. 你确实不认识这个意语词、法语也帮不上时，`zh` 输出空字符串 ""，**不要猜**

输入是 JSON 数组。输出**只有** JSON 数组，每项 {"id": 原样, "zh": "中文"}。
不要围栏、不要解释。"""


def load(con):
    other = defaultdict(list)
    for wid, sid, z in con.execute(
            "SELECT s.word_id, s.id, g.text FROM sense s "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' AND g.seq=0"):
        other[wid].append((sid, z))
    out = []
    for sid, wid, w, pos, fr, zh in con.execute(
            "SELECT s.id, s.word_id, d.word, s.pos, x.text, g.text FROM sense_src x "
            "JOIN sense s ON s.id=x.sense_id JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' "
            "WHERE x.src='fr-edition' AND g.src LIKE '%via-fr' "
            "AND g.src NOT LIKE 'template%'"):
        if geo_parse(fr):
            continue                       # 地理句式已由模板做完
        if BARE.match(fr.strip()):
            continue                       # 纯专名，现有音译干净
        out.append(dict(id=sid, word=w, pos=pos or "?", it=fr,
                        other="；".join(z for s2, z in other.get(wid, []) if s2 != sid)[:80],
                        cur=zh))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("🔴 来源仍标 via-fr（二手要记在明处）",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND src NOT LIKE '%via-fr%'", SRC), 0),
        ("中文不许为空",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND trim(text)=''", SRC), 0),
        ("句末不许有标点",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND "
           "(text LIKE '%。' OR text LIKE '%.' OR text LIKE '%；')", SRC), 0),
        ("不许含元话语",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND "
           "(text LIKE '%意为%' OR text LIKE '%指的是%' OR text LIKE '%该词%')", SRC), 0),
        ("🔴 一条 sense 只有一条中文",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='zh' "
           "GROUP BY sense_id HAVING count(*)>1)"), 0),
        ("🔴 法语原文仍只在证据层",
         q("SELECT count(*) FROM sense_gloss WHERE lang='fr'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-42s %s (期望 %s)" % ("✅" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "run", "diff", "apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(con) else 1
    items = load(con)

    if a.plan:
        print("■ 真翻译那批 %s 条" % f"{len(items):,}")
        print("   词性分布: %s" % Counter(x["pos"] for x in items).most_common(6))
        print("   带其它义项的（纪律①会用上）: %s"
              % f"{sum(1 for x in items if x['other']):,}")
        return 0

    if a.run:
        T.SYS = SYS
        T.CHUNK = 20
        OUT.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(T.run_batches(
            [{"id": x["id"], "word": x["word"], "pos": x["pos"],
              "it": x["it"], "other": x["other"]} for x in items], OUT))
        return 0

    got = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            got[r["id"]] = r["zh"].strip()

    if a.diff:
        same = diff = empty = 0
        rows = []
        for x in items:
            b = got.get(x["id"])
            if b is None:
                continue
            if not b:
                empty += 1
            elif set(b) & set(x["cur"]):
                same += 1
            else:
                diff += 1
                rows.append(x | {"new": b})
        n = same + diff + empty
        print("■ 新旧两版比对（%s 条）" % f"{n:,}")
        print("   一致  %7s (%.1f%%)" % (f"{same:,}", 100.0 * same / max(n, 1)))
        print("   分歧  %7s (%.1f%%)" % (f"{diff:,}", 100.0 * diff / max(n, 1)))
        print("   新版空 %6s (%.1f%%)" % (f"{empty:,}", 100.0 * empty / max(n, 1)))
        random.seed(8)
        print("\n■ 分歧抽样 14 条（旧 = 无词性，新 = 带词性）")
        for x in random.sample(rows, min(14, len(rows))):
            print("   %-18s [%s] fr=%s" % (x["word"][:18], x["pos"], x["it"][:44]))
            print("      旧=%-22s 新=%s" % (x["cur"][:22], x["new"][:26]))
        return 0

    if a.apply:
        # 🔴 守卫：新版把「输出对应词」执行得太彻底，**非意大利地名**（西班牙/法国等，
        #    我的 geo_parse 只认意大利句式）被压成了纯音译，地理信息全丢。
        #    实测 320 条。判据是确定性的：旧版有地理词、新版没有 ⇒ 保留旧版。
        GEO_WORDS = re.compile(r"(省|大区|市镇|街区|自治区|广域市|村庄|地区)")
        rows, kept = [], 0
        for x in items:
            b = got.get(x["id"])
            if not b:
                continue
            if GEO_WORDS.search(x["cur"]) and not GEO_WORDS.search(b):
                kept += 1
                continue
            rows.append((x["id"], b))
        print("■ 将改写 %s 条；因新版丢地理信息而保留旧版 %s 条"
              % (f"{len(rows):,}", f"{kept:,}"))
        con.close()
        with dbtool.session("fr-real-v2", expect={"#sense_gloss": 0}) as s:
            s.executemany("DELETE FROM sense_gloss WHERE sense_id=? AND lang='zh'",
                          [(r[0],) for r in rows])
            s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                          "VALUES (?,'zh','equivalent',0,?,'%s')" % SRC, rows)
        print("■ 已写入")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
