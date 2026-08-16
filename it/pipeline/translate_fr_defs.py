#!/usr/bin/env python3
"""给法语版收来的词形配中文（经法语中转）。2026-08-13，阶段 3c。

═══ 两条路径，先模板后模型 ═══
法语侧 168,189 条释义里 **83.1% 是同一个字符串** `Nom de famille.`（139,691 条）。
这批走**模板**，不送模型：确定性、可回归测试、省 5 倍钱（同 A26 的道理）。
剩下 28,394 条走 flash。

═══ 🔴 这批中文是二手的，必须记在明处 ═══
链路是 **意语词 → 法语译名 → 中文**，两跳。
`sense_gloss.src` 记成 `<模型>:via-fr` / `template:via-fr`，
将来意语版补了真定义可以覆盖它。**不要**让它看起来和一手中文一样可信。

═══ 负控：直接量"两跳"的损失 ═══
拿**库里已有中文、法语版也收了**的词做控制组：喂法语释义、不给中文，
产出与库里现成的中文比。这量的正是中转本身的损失，不是模型的一般能力。

用法（在 it/ 目录下）：
    python3 pipeline/translate_fr_defs.py --plan
    python3 pipeline/translate_fr_defs.py --control   # 先跑这个，不合格就别跑全量
    python3 pipeline/translate_fr_defs.py --template  # 模板那批（免费）
    python3 pipeline/translate_fr_defs.py --run
    python3 pipeline/translate_fr_defs.py --merge
    python3 pipeline/translate_fr_defs.py --verify
"""
import argparse
import asyncio
import json
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from translate_it_defs import CHUNK, load_env, parse, run_batches   # noqa: E402

MODEL = "deepseek-v4-flash"
SRC_MODEL = MODEL + ":via-fr"
SRC_TPL = "template:via-fr"
OUT = paths.WORK / "fr_defs_zh.jsonl"
CTRL = paths.WORK / "fr_defs_control.jsonl"

# 完全固定的法语文本 → 中文。**只认逐字节相等**，不做模糊匹配。
TEMPLATE = {
    "Nom de famille.": "姓氏",
    "Nom de famille italien.": "意大利语姓氏",
    "Prénom masculin.": "男性名字",
    "Prénom féminin.": "女性名字",
}

SYS = """你是法语—中文词典助手。输入是**意大利语词条在法语维基词典里的释义**，
多数只是一个法语对应词（`Océanologue.`），少数是简短说明（`Hameau de Doues.`）。
把它转成**中文对应词式释义**。

规则：
1. 输出对应词，不是长句翻译。`Océanologue.` → `海洋学家`
2. 地名/村庄：`Hameau de Doues.` → `杜厄的村庄`；已有通用中译名的用通用名（`Glasgow` → `格拉斯哥`）
3. 姓氏：`Nom de famille.` → `姓氏`
4. **句末不加任何标点**；多个对应词用中文逗号分隔，最多 3 个
5. 不要出现"意为""指""该词"这类元话语，也不要出现词性标签
6. 法语释义本身就没有信息量、或你无法确定时，`zh` 输出空字符串 ""，**不要猜**

输入是 JSON 数组，每项有 `id`、`word`（意语词形）、`fr`（法语释义）。
输出**只有** JSON 数组，每项 {"id": 原样, "zh": "中文"}，不要围栏、不要解释。"""


def pending(con):
    return [dict(id=r[0], word=r[1], fr=r[2]) for r in con.execute(
        "SELECT s.id, d.word, x.text FROM sense_src x JOIN sense s ON s.id=x.sense_id "
        "JOIN dict d ON d.id=s.word_id WHERE x.src='fr-edition' AND NOT EXISTS("
        "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh') ORDER BY s.id")]


def split_tpl(items):
    tpl = [(x["id"], TEMPLATE[x["fr"]]) for x in items if x["fr"] in TEMPLATE]
    rest = [x for x in items if x["fr"] not in TEMPLATE]
    return tpl, rest


def control_set(con, n=40, seed=7):
    """负控：库里已有中文、法语版也收了的词 —— 直接量「意→法→中」两跳的损失。"""
    import gzip
    have = {}
    for w, z in con.execute(
            "SELECT d.word, g.text FROM sense s JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' AND g.seq=0 "
            "WHERE s.rank=1 AND COALESCE(s.hidden,0)=0"):
        have.setdefault(w.lower(), z)
    rows = []
    with gzip.open(paths.KK_FR, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            w = (e.get("word") or "").strip()
            z = have.get(w.lower())
            if not z or (e.get("pos") or "") == "name":
                continue
            for s in (e.get("senses") or []):
                g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
                if not g or s.get("form_of") or s.get("alt_of"):
                    continue
                rows.append(dict(id=len(rows) + 1, word=w, fr=g, truth=z))
                break
    random.Random(seed).shuffle(rows)
    return rows[:n]


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("🔴 中转来源必须标 via-fr（二手要记在明处）",
         q("SELECT count(*) FROM sense_gloss g JOIN sense_src x ON x.sense_id=g.sense_id "
           "AND x.src='fr-edition' WHERE g.lang='zh' AND COALESCE(g.src,'') NOT LIKE '%via-fr'"), 0),
        ("模板那批的中文只有固定几种",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND text NOT IN (%s)"
           % ",".join("'%s'" % v for v in set(TEMPLATE.values())), SRC_TPL), 0),
        ("中文不许是空串",
         q("SELECT count(*) FROM sense_gloss WHERE src IN (?,?) AND trim(text)=''",
           SRC_MODEL, SRC_TPL), 0),
        ("中文句末不许有标点",
         q("SELECT count(*) FROM sense_gloss WHERE src IN (?,?) AND "
           "(text LIKE '%。' OR text LIKE '%.' OR text LIKE '%；')", SRC_MODEL, SRC_TPL), 0),
        ("🔴 没有覆盖任何已有中文（只填空不覆盖）",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='zh' "
           "GROUP BY sense_id HAVING count(*)>1)"), 0),
        ("🔴 出版层仍不出法语（A3）",
         q("SELECT count(*) FROM sense_gloss WHERE lang='fr'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "control", "template", "run", "merge", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    if a.verify:
        return 0 if gate(con) else 1

    if a.control:
        ctrl = control_set(con)
        CTRL.parent.mkdir(parents=True, exist_ok=True)
        import translate_it_defs as T
        T.SYS = SYS
        asyncio.run(run_batches([{"id": c["id"], "word": c["word"], "it": c["fr"]} for c in ctrl],
                                CTRL))
        got = {json.loads(l)["id"]: json.loads(l)["zh"] for l in CTRL.open(encoding="utf-8")}
        hit = 0
        print("\n■ 负控：量「意→法→中」两跳的损失")
        for c in ctrl:
            g = got.get(c["id"], "")
            ok = bool(g) and bool(set(g) & set(c["truth"]))
            hit += ok
            print("   %-16s 中转=%-20s 库(一手)=%-20s %s"
                  % (c["word"], g[:20], c["truth"][:20], "✓" if ok else "✗"))
        print("\n   有字面重叠 %d/%d —— ⚠️ 只是可用性下限，不是准确率" % (hit, len(ctrl)))
        return 0

    items = pending(con)
    tpl, rest = split_tpl(items)
    if a.plan:
        print("■ 待配中文 %s 条" % f"{len(items):,}")
        print("   模板（免费、确定性）%s 条 (%.1f%%)" % (f"{len(tpl):,}", 100.0 * len(tpl) / max(len(items), 1)))
        print("   送模型              %s 条" % f"{len(rest):,}")
        return 0

    if a.template:
        con.close()
        with dbtool.session("fr-zh-template", expect={"#sense_gloss": len(tpl)}) as s:
            s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                          "VALUES (?,'zh','equivalent',0,?,?)",
                          [(sid, zh, SRC_TPL) for sid, zh in tpl])
        print("■ 模板写入 %s 条" % f"{len(tpl):,}")
        return 0

    if a.run:
        import translate_it_defs as T
        T.SYS = SYS
        OUT.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(run_batches([{"id": x["id"], "word": x["word"], "it": x["fr"]} for x in rest],
                                OUT))
        return 0

    if a.merge:
        got = {}
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            if r["zh"]:
                got[r["id"]] = r["zh"]
        have = {r[0] for r in con.execute("SELECT sense_id FROM sense_gloss WHERE lang='zh'")}
        # 🔴 剔掉「词缀 + 译文里一个中文字都没有」的：那是把法语后缀原样给了中文用户
        #    （`-abilità` → `-abilité`）。判官与确定性体检都逮到同一族，全库 9 条。
        #    ⚠️ 只剔词缀：`DJ`→`DJ`、`MDMA` 是对的，摩洛哥地名回显也没信息可翻。
        import re as _re
        _cjk = _re.compile(r"[一-鿿]")
        word_of = {r[0]: r[1] for r in con.execute(
            "SELECT s.id, d.word FROM sense s JOIN dict d ON d.id=s.word_id")}
        drop = {sid for sid, zh in got.items()
                if not _cjk.search(zh)
                and (word_of.get(sid, "").startswith("-") or word_of.get(sid, "").endswith("-"))}
        print("   剔除词缀类无中文译文 %d 条" % len(drop))
        rows = [(sid, zh, SRC_MODEL) for sid, zh in got.items()
                if sid not in have and sid not in drop]
        print("■ 结果 %s 条，写入 %s 条" % (f"{len(got):,}", f"{len(rows):,}"))
        con.close()
        with dbtool.session("fr-zh-merge", expect={"#sense_gloss": len(rows)}) as s:
            s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                          "VALUES (?,'zh','equivalent',0,?,?)", rows)
        print("■ 已写入")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
