#!/usr/bin/env python3
"""B30：中文版维基词典的俄语例句译文，约一成是**从英文转译时挑错了多义词的义项**。逐条判、错的给改译。

═══ 缺陷（2026-10-30 回 dump 原文核过，错在源头不在我们）═══
    изда́тельский дом          publishing house       →「建造房屋」
    чума́ на о́ба ва́ши до́ма    plague on both your houses →「之後的王朝都是瘟疫」
    набра́ть тру́ппу           make up a theatre company →「組成公司」
    с непокры́той голово́й     bareheaded             →「禿頭的」
抽样：繁体版 40 条错 4、简体版 25 条错 1。错译与正确译文**形式上无差别**（通顺、长度正常）⇒ 没有免费判据，只能判意思。

═══ 做法 ═══
判官看三样：俄语原句、源头中文、（有的话）en 版同一句的英译 ⇒ `ok`（对/错）＋ 错的给 `zh`（改译）。
⚠️ 只判**意思**：繁简、措辞、意译都不算错（繁简由 B29 另转）。
⚠️ 答案按 `example_gloss.id`（主键）落盘（`[[model-answer-files-key-by-id]]`）。
⚠️ 写库只写 `text_pub`，`text` 是源头原文一字不动（`[[source-typo-fix-ours-not-quote]]`）——本脚本这一版**不写库**。

═══ 控制组（输出几个字段就几组判据，`[[control-must-cover-every-output-field]]`）═══
  C1 定题：已知错的 5 条必须判错、已知对的 5 条必须判对（混在切片里，判官不知道）
  C2 逐 id 点名：发出去的每个 id 都回来了
  C3 `ok` 是布尔
  C4 判错的必须给 `zh`，且 `zh` 有汉字、不等于原译文；判对的不许给 `zh`

跑（在仓库根）：
    python3 -u ru/pipeline/judge_zh_edition_examples.py --slice     # 1% 切片 ＋ 控制组
    python3 -u ru/pipeline/judge_zh_edition_examples.py --report    # 只读答案文件出报告
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
import paths  # noqa: E402
import ds_batch  # noqa: E402

OUT = paths.WORK / "b30_zh_judge"
SRCS = ("zh-edition-trad", "zh-edition-simp")
PER_BATCH = 20
PRICE_HALF = 2.669          # 元/百万 token，vi 5b 对过账单；高峰是它的两倍

# 定题：已知答案的条目（按源头中文原文找 id，判官不知道哪几条是）
KNOWN_BAD = ("建造房屋", "之後的王朝都是瘟疫", "組成公司（如：劇院）", "禿頭的", "跋涉者")
KNOWN_OK = ("茶包", "他在一場車禍中喪生", "養老院", "文具", "避免戰爭")

SYS = """你是俄汉翻译审校。每条给你：w＝词头，ru＝该词条下的俄语例句（可能是短语；「～」代表词头 w 或它的某个变化形式），
zh＝现有中文译文，en＝同一句的英文译文（可能没有，仅供参考）。
判断 zh 是否**意思上**正确地翻译了 ru。只在**读者会因此理解成另一个意思**时才判错。

算错（ok=false）：
- 意思错了：常见原因是有人照着英文转译，挑错了英文多义词的意思（如 publishing house 译成「建造房屋」、theatre company 译成「公司」、bareheaded 译成「秃头的」、wader 译成「跋涉者」）；
- 与句子对不上（译的是别的内容）；
- 漏译或多译导致意思明显改变。

不算错（ok=true）：
- 繁体字、异体字（另有程序转换，不要因此判错）；
- 措辞、语序、意译、口语化，只要意思对；
- 略去无关紧要的语气词；多一两个修饰词、「书籍／书」这类近义替换；
- 程度、语气上的细微差别。
拿不准时判对。改译必须与你的说明一致。

判错时在 zh 里给出正确的简体中文译文，长短和风格贴近原译（短语就给短语）；判对时不要给 zh。
输出一个 JSON 对象：键与输入相同，值为 {"ok": true} 或 {"ok": false, "zh": "改译", "why": "十字以内说明错在哪"}。只输出 JSON。"""


# 复核层（2026-10-30 切片实测）：flash 单独一层的误判率（≈2.7%）与缺陷率（≈2–3%）相当，直接写会改坏差不多一样多；
#   pro 开思考复核 flash 判错的那批 ⇒ 我逐条标过的 13 条里真错留 5/5、误判留 1/6。**两层都说错才算错**。
SYS_VERIFY = """你是资深俄汉翻译审校。每条给你：w＝词头，ru＝俄语例句（「～」代表词头或其变化形式），en＝英译（可能没有），
zh_old＝现有中文译文，zh_new＝另一位审校给的改译，why＝他的理由。
请独立判断：real＝现有译文是否确实会让读者理解成**另一个意思**（措辞、语气、程度差别、多一两个字都不算）；
fix_ok＝改译是否准确。拿不准时 real 判 false。
输出 JSON 对象：键与输入相同，值为 {"real": true/false, "fix_ok": true/false}。只输出 JSON。"""
VERIFY_BATCH = 15


def pool(con):
    """→ [{gid, ru, zh, en}]：源头给的中文译文（不含 `:同句` 借用 —— 它们跟着原条走）。"""
    en = {}
    for wid, txt, g in con.execute(
            "SELECT e.word_id, e.text, g.text FROM example e JOIN example_gloss g ON g.example_id=e.id "
            "AND g.lang='en' WHERE e.src='en-edition'"):
        en.setdefault((wid, txt), g)
    rows = []
    # 🔴 第一版切片没给词头：简体版 90% 的例句用「～」代词头（`～ ры́бу`），判官看不到是哪个词就编
    #    （「把鱼切成片」改成「捕鱼」）—— 39 条「判错」里 24 条是这一种
    for gid, wid, txt, pub, zh, word in con.execute(
            "SELECT g.id, e.word_id, e.text, e.text_pub, g.text, d.word FROM example e JOIN example_gloss g "
            "ON g.example_id=e.id AND g.lang='zh' JOIN dict d ON d.id=e.word_id WHERE g.src IN (%s) ORDER BY g.id"
            % ",".join("'%s'" % s for s in SRCS)):
        d = {"gid": gid, "w": word, "ru": pub or txt, "zh": zh}
        if (wid, txt) in en:
            d["en"] = en[(wid, txt)]
        rows.append(d)
    return rows


def fixes(con):
    """→ {example_gloss.id: 改译}。**两层都判错（flash 判错 ＋ pro 思考复核 real 且 fix_ok）**才收。
    `zh_pub.plan_text_pub` 拿它当 `text` 算 `text_pub` —— 出版正文只有那一处决定，免得 `zh_pub` 重跑把改译冲掉。
    同句借用（`<源>:同句`）的行跟着改：同一个词形下、中文与被改那条原文一字不差的。"""
    def load(name):
        d = {}
        p = OUT / name
        if p.exists():
            for l in p.open(encoding="utf-8"):
                x = json.loads(l)
                d[x["id"]] = x
        return d
    full, ver = load("full.jsonl"), load("verify_full.jsonl")
    acc = {g: full[g]["zh"] for g, v in ver.items()
           if v.get("real") is True and v.get("fix_ok") is True and g in full
           and full[g].get("ok") is False and has_han(full[g].get("zh"))}
    if not acc:
        return {}
    src = {}
    for gid, wid, zh in con.execute(
            "SELECT g.id, e.word_id, g.text FROM example_gloss g JOIN example e ON e.id=g.example_id "
            "WHERE g.id IN (%s)" % ",".join(map(str, acc))):
        src.setdefault((wid, zh), set()).add(acc[gid])
    out = dict(acc)
    for gid, wid, zh in con.execute(
            "SELECT g.id, e.word_id, g.text FROM example_gloss g JOIN example e ON e.id=g.example_id "
            "WHERE g.lang='zh' AND g.src LIKE '%:同句'"):
        hit = src.get((wid, zh))
        if hit and len(hit) == 1:                 # 同词形同原文却给了两种改译 ⇒ 不跟
            out[gid] = next(iter(hit))
    return out


def has_han(s):
    return bool(re.search(r"[㐀-鿿]", s or ""))


def controls(sent, ans, known):
    """→ [(名, 通过?, 说明)]"""
    by = {a["id"]: a for a in ans}
    out = []
    bad = [g for g, w in known.items() if g in by and by[g].get("ok") is not w]
    out.append(("C1 定题 %d 条" % len(known), not bad and all(g in by for g in known),
                "判反了：%s" % bad if bad else ""))
    miss = [r["gid"] for r in sent if r["gid"] not in by]
    out.append(("C2 逐 id 点名", not miss, "缺 %d 条：%s" % (len(miss), miss[:5]) if miss else ""))
    nb = [a["id"] for a in ans if not isinstance(a.get("ok"), bool)]
    out.append(("C3 ok 是布尔", not nb, str(nb[:5]) if nb else ""))
    zh0 = {r["gid"]: r["zh"] for r in sent}
    c4 = [a["id"] for a in ans if (a.get("ok") is False and (not has_han(a.get("zh")) or a.get("zh") == zh0.get(a["id"])))
          or (a.get("ok") is True and a.get("zh"))]
    out.append(("C4 判错必给改译／判对不给", not c4, "%d 条：%s" % (len(c4), c4[:5]) if c4 else ""))
    return out


def report(sent, path, known):
    ans = [json.loads(l) for l in path.open(encoding="utf-8")] if path.exists() else []
    seen = {}
    for a in ans:
        seen[a["id"]] = a                         # 续传可能重复，取最后一条
    ans = list(seen.values())
    print("\n■ 控制组")
    allok = True
    for name, ok, why in controls(sent, ans, known):
        allok &= ok
        print("   %s %-22s %s" % ("✅" if ok else "🔴", name, why))
    by = {r["gid"]: r for r in sent}
    wrong = [a for a in ans if a.get("ok") is False and a["id"] not in known]
    n = len([a for a in ans if a["id"] not in known])
    print("\n■ 判错 %d / %d（%.1f%%，不含定题）" % (len(wrong), n, 100.0 * len(wrong) / max(n, 1)))
    for a in wrong:
        r = by[a["id"]]
        print("   %-7d %s\n           原：%s\n           改：%s  （%s）%s"
              % (a["id"], r["ru"][:70], r["zh"][:50], a.get("zh", "")[:50], a.get("why", ""),
                 "\n           en：" + r["en"][:60] if r.get("en") else ""))
    return allok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--full", action="store_true", help="全量 flash 判一遍（含定题）")
    ap.add_argument("--verify", action="store_true", help="pro 开思考复核 full 里判错的")
    ap.add_argument("--conc", type=int, default=60)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = pool(con)
    con.close()
    by_zh = {}
    for r in rows:
        by_zh.setdefault(r["zh"], r)
    known = {by_zh[z]["gid"]: False for z in KNOWN_BAD}
    known.update({by_zh[z]["gid"]: True for z in KNOWN_OK})
    rnd = random.Random(30)
    sl = rnd.sample([r for r in rows if r["gid"] not in known], len(rows) // 100)
    sent = sl + [r for r in rows if r["gid"] in known]
    rnd.shuffle(sent)
    path = OUT / "slice2.jsonl"          # slice.jsonl ＝ 没给词头的第一版，留作对照
    print("■ 池子 %s 条（有英译 %s）｜切片 %d ＋ 定题 %d"
          % (format(len(rows), ","), format(sum("en" in r for r in rows), ","), len(sl), len(known)))
    if a.full or a.verify:
        sent = rows                                   # 定题天然在池子里（它们本来就是池子里的真条目）
        path = OUT / "full.jsonl"
    if a.verify:
        ans = {}
        for l in path.open(encoding="utf-8"):
            d = json.loads(l)
            ans[d["id"]] = d
        by = {r["gid"]: r for r in rows}
        flag = [d for d in ans.values() if d.get("ok") is False]
        batches, meta = [], []
        for i in range(0, len(flag), VERIFY_BATCH):
            chunk = flag[i:i + VERIFY_BATCH]
            batches.append({"k%d" % j: {**{k: by[d["id"]][k] for k in ("w", "ru", "en") if k in by[d["id"]]},
                                        "zh_old": by[d["id"]]["zh"], "zh_new": d.get("zh"), "why": d.get("why")}
                            for j, d in enumerate(chunk)})
            meta.append([("k%d" % j, d["id"]) for j, d in enumerate(chunk)])
        vp = OUT / "verify_full.jsonl"
        tok = asyncio.run(ds_batch.run(SYS_VERIFY, batches, meta, vp, mode="pro", conc=a.conc, thinking="enabled"))
        v = {}
        for l in vp.open(encoding="utf-8"):
            d = json.loads(l)
            v[d["id"]] = d
        acc = [g for g in v if v[g].get("real") is True and v[g].get("fix_ok") is True]
        miss = [d["id"] for d in flag if d["id"] not in v]
        print("■ 复核 %d 条（pro 思考，token %s）：两层都判错且改译准确 %d ｜ 复核缺 %d ｜ 定题已知错留下 %d/%d"
              % (len(flag), format(tok, ","), len(acc), len(miss),
                 sum(1 for g, w in known.items() if not w and g in acc), sum(1 for w in known.values() if not w)))
        return 0 if not miss else 1
    if a.slice or a.full:
        batches, meta = [], []
        for i in range(0, len(sent), PER_BATCH):
            chunk = sent[i:i + PER_BATCH]
            batches.append({"k%d" % j: {k: r[k] for k in ("w", "ru", "zh", "en") if k in r}
                            for j, r in enumerate(chunk)})
            meta.append([("k%d" % j, r["gid"]) for j, r in enumerate(chunk)])
        tok = asyncio.run(ds_batch.run(SYS, batches, meta, path, conc=a.conc))
        per = tok / max(len(sent), 1)
        full = per * len(rows)
        print("■ 本轮 token %s（%.1f token/条）⇒ 全量外推 %s token ≈ 半价 %.1f 元／高峰 %.1f 元"
              % (format(tok, ","), per, format(int(full), ","), full / 1e6 * PRICE_HALF, full / 1e6 * PRICE_HALF * 2))
    ok = report(sent, path, known)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
