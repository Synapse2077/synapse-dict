#!/usr/bin/env python3
"""地理释义重做：音译交模型、框架交模板。2026-08-14，阶段 3c 重做。

═══ 分工（`PLAYBOOK` 5.3 的正确用法）═══
    只有模型能做的：意语专名 → 中文音译（`Villa Fiore` → 维拉菲奥雷）
    只有模板该做的：`（意大利X大区Y省市镇）` —— 必须逐条一致，模型做不到

上一轮把两件事一起丢给 flash，同一个模式出了三种格式，而且 3,966 条**把词条
自己的名字丢了**（`Villa Fiore` → 「阿尔巴阿德里亚蒂卡的村庄」，只剩母地名）。

═══ 这一步只重做 3,966 条的音译 ═══
另外 1,938 条现有中文本来就是干净音译，直接套框架，不花钱。

⚠️ 音译 prompt 的唯一任务是**音译**：不许加"意大利""村庄""省"这类信息 ——
   那些由模板统一加，模型加了反而不一致。验收就查这一条。

用法（在 it/ 目录下）：
    python3 pipeline/fix_geo_zh.py --plan
    python3 pipeline/fix_geo_zh.py --run       # 只跑要重做音译的那 3,966 条
    python3 pipeline/fix_geo_zh.py --apply     # 套模板、写库（含免费的 1,938 条）
    python3 pipeline/fix_geo_zh.py --verify
"""
import argparse
import asyncio
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
import translate_it_defs as T   # noqa: E402  用它的可续传跑批器
from geo_zh import FRAME_WORDS, compose, parse   # noqa: E402

OUT = paths.WORK / "geo_translit.jsonl"
SRC = "template+translit:via-fr"

SYS = """你的唯一任务是把**意大利语地名**转写成中文音译。

规则：
1. 只给**音译**，不要加任何说明。`Villa Fiore` → `维拉菲奥雷`
2. 🔴 **绝对不要**出现"意大利""村庄""市镇""省""大区"这类词 —— 那些由程序统一添加，
   你加了会导致格式不一致。
3. 已有通行中译名的用通行名（`Firenze` → `佛罗伦萨`，`Roma` → `罗马`）
4. 句末不加标点
5. 名字里的连接成分按意语习惯处理：`di` `del` `della` `d'` 音译进去
   （`Acquaviva d'Isernia` → `阿夸维瓦迪塞尔尼亚`）

输入是 JSON 数组，每项有 `id`、`word`（意语地名）、`it`（法语侧原文，仅供辨别是哪个地方）。
输出**只有** JSON 数组，每项 {"id": 原样, "zh": "音译"}。不要围栏、不要解释。"""


def load(con):
    """→ (要重做音译的, 可直接套框架的)。两者都是地理句式。"""
    zh_of = {}
    for w, z in con.execute(
            "SELECT d.word, g.text FROM sense s JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' AND g.seq=0 "
            "WHERE s.rank=1"):
        zh_of.setdefault(w, z)
    redo, keep = [], []
    for sid, w, fr, zh in con.execute(
            "SELECT s.id, d.word, x.text, g.text FROM sense_src x "
            "JOIN sense s ON s.id=x.sense_id JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' "
            "WHERE x.src='fr-edition' AND g.src NOT LIKE 'template%'"):
        info = parse(fr)
        if not info:
            continue
        (keep if not FRAME_WORDS.search(zh) else redo).append(
            dict(id=sid, word=w, it=fr, info=info, cur=zh, zh_of=zh_of))
    return redo, keep


def parent_zh(info, zh_of):
    p = info.get("parent") or ""
    z = zh_of.get(p)
    return z if (z and not FRAME_WORDS.search(z)) else None


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("🔴 模板产出的中文格式统一（都带括号）",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND text NOT LIKE '%（%）%'", SRC), 0),
        ("🔴 括号里必须以「意大利」开头或含「村庄」",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND text NOT LIKE '%（意大利%' "
           "AND text NOT LIKE '%村庄%'", SRC), 0),
        ("音译部分不含框架词（框架只在括号里）",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND "
           "(substr(text,1,instr(text,'（')-1) LIKE '%市镇%' OR "
           " substr(text,1,instr(text,'（')-1) LIKE '%大区%' OR "
           " substr(text,1,instr(text,'（')-1) LIKE '%村庄%')", SRC), 0),
        ("句末无标点",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND "
           "(text LIKE '%。' OR text LIKE '%.')", SRC), 0),
        ("🔴 一条 sense 只有一条中文",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='zh' "
           "GROUP BY sense_id HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %s (期望 %s)" % ("✅" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "run", "apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(con) else 1
    redo, keep = load(con)

    if a.plan:
        print("■ 地理句式共 %s 条" % f"{len(redo) + len(keep):,}")
        print("   要重做音译（现有中文丢了词条名）%s 条 ← 唯一花钱的" % f"{len(redo):,}")
        print("   现有中文是干净音译，直接套框架  %s 条（免费）" % f"{len(keep):,}")
        return 0

    if a.run:
        T.SYS = SYS
        T.CHUNK = 30
        OUT.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(T.run_batches([{k: x[k] for k in ("id", "word", "it")} for x in redo], OUT))
        return 0

    if a.apply:
        tl = {}
        if OUT.exists():
            for line in OUT.open(encoding="utf-8"):
                r = json.loads(line)
                if r["zh"]:
                    tl[r["id"]] = r["zh"].strip()
        rows, stat = [], Counter()
        for x in keep + redo:
            head = tl.get(x["id"]) or (x["cur"] if not FRAME_WORDS.search(x["cur"]) else None)
            if not head:
                stat["🔴 没有可用音译，跳过"] += 1
                continue
            if FRAME_WORDS.search(head):
                stat["🔴 音译里混进了框架词，跳过"] += 1
                continue
            out = compose(x["info"], head, parent_zh(x["info"], x["zh_of"]))
            if not out:
                stat["拼不出来，跳过"] += 1
                continue
            stat["✅ 生成"] += 1
            rows.append((x["id"], out))
        for k, v in stat.most_common():
            print("   %-30s %7s" % (k, f"{v:,}"))
        print("\n■ 将改写 %s 条（删旧中文、写模板版）" % f"{len(rows):,}")
        for sid, t in rows[:6]:
            print("     %s" % t)
        con.close()
        if not rows:
            return 0
        with dbtool.session("geo-template", expect={"#sense_gloss": 0}) as s:
            ids = [(r[0],) for r in rows]
            s.executemany("DELETE FROM sense_gloss WHERE sense_id=? AND lang='zh'", ids)
            s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                          "VALUES (?,'zh','equivalent',0,?,'%s')" % SRC,
                          [(sid, t) for sid, t in rows])
        print("■ 已写入")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
