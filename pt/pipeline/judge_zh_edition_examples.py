#!/usr/bin/env python3
"""B30（pt 那一半）：中文版维基词典给葡语例句配的中文，有一部分是**照英文转译、挑错了多义词**。逐条判、错的改译。

═══ 缺陷 ═══
    Demorou horas para terminarmos a construção.  →「我们花了几个小时才完成这栋**大楼**。」（building）
    Ergueu-se nas pontas dos pés, mas isto lhe arrancou…  →「艰辛岁月」（整条对不上）
ru 那一半（2026-10-30，`ru/pipeline/judge_zh_edition_examples.py`）实测：flash 单层的误判率与缺陷率相当，
直接写会改坏差不多一样多 ⇒ **两层**：flash 判一遍 ＋ pro 开思考复核判错的那批，两层都说错且改译准确才改。

═══ 写到哪 ═══
pt 的 `example_gloss` 没有出版列，源头原文也没另存（`example.src_translation` 是空的）⇒
改 `text`、`src` 记成 `zh-edition:b30`（来源如实：源头那行被两层判官改过）；**原文落在答案文件 `orig` 字段**，
dump 里也还有。改译过一遍 `scripts/zh_t2s.t2s`（pt 回归闸 A10 锁繁体为 0）。

跑（在仓库根）：
    python3 -u pt/pipeline/judge_zh_edition_examples.py --full      # flash 全量（767 条，几毛钱）
    python3 -u pt/pipeline/judge_zh_edition_examples.py --verify    # pro 开思考复核判错的
    python3 -u pt/pipeline/judge_zh_edition_examples.py --read 40   # 写之前逐条读
    python3 -u pt/pipeline/judge_zh_edition_examples.py --apply     # 写库（走 dbtool 闸门）
"""
import argparse
import asyncio
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
import paths  # noqa: E402
import ds_batch  # noqa: E402
from zh_t2s import t2s  # noqa: E402

OUT = paths.WORK / "b30_zh_judge"
SRC, SRC_FIXED = "zh-edition", "zh-edition:b30"
PER_BATCH, VERIFY_BATCH = 20, 15
PRICE_HALF = 2.669
KNOWN = {26073: False, 30212: False, 29231: True, 31298: True, 31921: True}   # 定题（按 example.id）

SYS = """你是葡汉翻译审校。每条给你：w＝词头，pt＝该词条下的葡萄牙语例句，zh＝现有中文译文，en＝同一句的英文译文（可能没有，仅供参考）。
判断 zh 是否**意思上**正确地翻译了 pt。只在**读者会因此理解成另一个意思**时才判错。

算错（ok=false）：
- 意思错了：常见原因是有人照着英文转译，挑错了英文多义词的意思（如 construção/building 译成「大楼」而原句说的是「建造」）；
- 与句子对不上（译的是别的内容）；
- 漏译或多译导致意思明显改变。

不算错（ok=true）：
- 繁体字、异体字（另有程序转换）；
- 措辞、语序、意译、口语化，只要意思对；
- 略去无关紧要的语气词；多一两个修饰词、近义替换；程度、语气上的细微差别。
拿不准时判对。改译必须与你的说明一致。

判错时在 zh 里给出正确的简体中文译文，长短和风格贴近原译；判对时不要给 zh。
输出一个 JSON 对象：键与输入相同，值为 {"ok": true} 或 {"ok": false, "zh": "改译", "why": "十字以内说明错在哪"}。只输出 JSON。"""

SYS_VERIFY = """你是资深葡汉翻译审校。每条给你：w＝词头，pt＝葡萄牙语例句，en＝英译（可能没有），
zh_old＝现有中文译文，zh_new＝另一位审校给的改译，why＝他的理由。
请独立判断：real＝现有译文是否确实会让读者理解成**另一个意思**（措辞、语气、程度差别、多一两个字都不算）；
fix_ok＝改译是否准确。拿不准时 real 判 false。
输出 JSON 对象：键与输入相同，值为 {"real": true/false, "fix_ok": true/false}。只输出 JSON。"""


def pool(con):
    en = dict(con.execute("SELECT example_id, text FROM example_gloss WHERE lang='en'"))
    rows = []
    # `example.word` 存的是词形文本不是 dict.id（第一版按 id 连 ⇒ 767 条只剩 1 条，几乎空跑）
    for eid, w, txt, zh in con.execute(
            "SELECT e.id, e.word, e.text, g.text FROM example e JOIN example_gloss g ON g.example_id=e.id "
            "AND g.lang='zh' WHERE g.src=? ORDER BY e.id", (SRC,)):
        d = {"id": eid, "w": w, "pt": txt, "zh": zh}
        if en.get(eid):
            d["en"] = en[eid]
        rows.append(d)
    return rows


def load(name):
    d, p = {}, OUT / name
    if p.exists():
        for l in p.open(encoding="utf-8"):
            x = json.loads(l)
            d[x["id"]] = x
    return d


def has_han(s):
    return bool(re.search(r"[㐀-鿿]", s or ""))


# 写前逐条读完 36 条（2026-10-30），两层都通过而**改了更错**的 —— 不写，原译留着：
REJECT = {29649: "葡萄牙用法 um bocado de tempo＝好一阵子，原译「我等了好久」对，改译「一小会」反了",
          29075: "巴西俚语 tá me estranhando＝找茬/瞧不起我，原译「贬低我」更近，改译「认不出我」错"}


def accepted():
    full, ver = load("full.jsonl"), load("verify_full.jsonl")
    return {g: full[g] for g, v in ver.items() if v.get("real") is True and v.get("fix_ok") is True
            and full.get(g, {}).get("ok") is False and has_han(full[g].get("zh")) and g not in REJECT}


def batches_of(items, fields, n):
    b, m = [], []
    for i in range(0, len(items), n):
        ch = items[i:i + n]
        b.append({"k%d" % j: {k: r[k] for k in fields if k in r} for j, r in enumerate(ch)})
        m.append([("k%d" % j, r["id"]) for j, r in enumerate(ch)])
    return b, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = pool(con)
    con.close()
    by = {r["id"]: r for r in rows}
    print("■ 池子 %d 条（有英译 %d）" % (len(rows), sum("en" in r for r in rows)))
    assert len(rows) >= 700, "🔴 池子只有 %d 条 —— 判据或连接坏了（应约 767）" % len(rows)
    if a.full:
        b, m = batches_of(rows, ("w", "pt", "zh", "en"), PER_BATCH)
        tok = asyncio.run(ds_batch.run(SYS, b, m, OUT / "full.jsonl", conc=60))
        print("■ flash token %s ≈ 半价 %.2f 元" % (format(tok, ","), tok / 1e6 * PRICE_HALF))
    full = load("full.jsonl")
    miss = [r["id"] for r in rows if r["id"] not in full and r["id"] in by]
    bad = [g for g, w in KNOWN.items() if g in full and full[g].get("ok") is not w]
    print("■ flash：判了 %d／缺 %d／判错 %d ｜ 定题判反 %s"
          % (len(full), len(miss), sum(1 for x in full.values() if x.get("ok") is False), bad or "无"))
    if a.verify:
        flag = [dict(by[g], zh_old=by[g]["zh"], zh_new=x.get("zh"), why=x.get("why"))
                for g, x in full.items() if x.get("ok") is False and g in by]
        b, m = batches_of(flag, ("w", "pt", "en", "zh_old", "zh_new", "why"), VERIFY_BATCH)
        tok = asyncio.run(ds_batch.run(SYS_VERIFY, b, m, OUT / "verify_full.jsonl", mode="pro", conc=60,
                                       thinking="enabled"))
        print("■ pro 思考 token %s（单价无实付账单）" % format(tok, ","))
    acc = accepted()
    print("■ 两层都判错且改译准确 %d ｜ 定题已知错留下 %d/%d"
          % (len(acc), sum(1 for g, w in KNOWN.items() if not w and g in acc), sum(1 for w in KNOWN.values() if not w)))
    if a.read:
        for g in random.Random(30).sample(sorted(acc), min(a.read, len(acc))):
            r = by[g]
            print("  %d [%s] %s\n     原：%s\n     改：%s（%s）%s" % (g, r["w"], r["pt"][:90], r["zh"][:50],
                  acc[g]["zh"][:50], acc[g].get("why", ""), ("\n     en：" + r["en"][:70]) if "en" in r else ""))
    if a.apply:
        import dbtool
        ups = [(t2s(acc[g]["zh"]), SRC_FIXED, g) for g in sorted(acc) if g in by]
        # 原文进账本（`[[answer-file-is-the-ledger]]`）：pt 库里不另存源头原文
        with (OUT / "applied.jsonl").open("a", encoding="utf-8") as fh:
            for new, _s, g in ups:
                fh.write(json.dumps({"id": g, "orig": by[g]["zh"], "new": new}, ensure_ascii=False) + "\n")
        with dbtool.session("b30-zh-edition-fix") as s:
            n = s.executemany("UPDATE example_gloss SET text=?, src=? WHERE example_id=? AND lang='zh' "
                              "AND src='%s'" % SRC, ups)
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        got = con.execute("SELECT COUNT(*) FROM example_gloss WHERE src=?", (SRC_FIXED,)).fetchone()[0]
        print("■ 写后回核：%s 行 %d（期望 %d）" % (SRC_FIXED, got, len(ups)))
        if got != len(ups):
            raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
