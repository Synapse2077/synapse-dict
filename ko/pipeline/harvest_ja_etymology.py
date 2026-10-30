#!/usr/bin/env python3
"""K36 收尾：日文版的词源正文 —— 日语原文进 `etymology`（证据），中文译文进 `etymology_gloss`。2026-10-28。

═══ 盘子（2026-10-28 实测）═══
日文版「朝鮮語」切片 3,305 个条目有 `etymology_texts`（**复数**）。过 `criteria.ko_etymology`（与韩文版同一个判据）：
    收 3,093（正文 1,888／构词 1,199／页面上没有的汉字写法 5／来源 1），共 84,690 字
    不收：词不在 dict 211／汉字写法已在页面上 1
⚠️ 只给 **194 个词**补出第一条词源；其余是同一个词的又一个来源。值钱的是**中世韩语首见文献**
   （`1447年、『釈譜詳節』で中期朝鮮語 개야미 として初出`），英文版有这类、韩文版几乎没有。
用户 2026-10-28：「可以翻，小钱不要紧」。

═══ 🔴 落点：原文与译文分两张表（`build_v3_schema.py` 09-27 就定了，不另起一列）═══
三语方针（中＋英＋本语言）⇒ **日语原文读者一个字都不许看到**：
    `etymology.text`        日语原文，一个字节不改（外锚闸逐行比的是它）
    `etymology_gloss`(zh)   模型译文，`src='model:deepseek-v4-flash'`
展示层只印译文；**没有译文的日文版行一律不印**（`korean.ts` 的 WHERE，契约闸锁住）。
⚠️ 日文版在 ko 里**没有 entry**（建库只用了 ko/zh 两版）⇒ 全部挂在词上，进页尾「其余词源」区。

═══ 答案文件按 `src_ref` 存（不按「第几条」，`[[model-answer-files-key-by-id]]`）═══
行写库前还没有主键；`src_ref` 是 `etymology` 的 UNIQUE 键，键里带同键序号（96 组同词同词性同词源号）。

═══ 控制组：六条，各对着一种坏法（常量，`[[control-must-cover-every-output-field]]`）═══

跑（在仓库根）：
    python3 -u ko/pipeline/harvest_ja_etymology.py                    # 干跑：盘子
    python3 -u ko/pipeline/harvest_ja_etymology.py --translate --slice 0.05
    python3 -u ko/pipeline/harvest_ja_etymology.py --translate --conc 60
    python3 -u ko/pipeline/harvest_ja_etymology.py --apply            # 原文＋译文一次写库
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import asyncio
import collections
import gzip
import hashlib
import json
import re
import sqlite3

import dbtool
import ds_batch
import paths
from criteria import ko_etymology
from harvest_ko_etymology import known_hanja
from translate_etymology import KO_RUN, HEDGE_ZH

f = lambda n: format(n, ",")
EDITION = "ja-edition"
OUT = paths.WORK / "etymology_ja_zh"
SRC_MODEL = "model:deepseek-v4-flash"
CHAR_BUDGET = 2600
MAX_PER_BATCH = 24

KANA = re.compile(r"[぀-ヿ]+")
# 日文原文里的存疑语：句末「か。」、「…と思われる」「説」「不明」「とも」
HEDGE_JA = re.compile(r"か[。．]?$|か。|思われ|と考えられ|説|不明|とも言|未詳|可能性")
JA_GRAMMAR = re.compile(r"からの|として|による|である|された|の借用")

SYS = """你是韩汉词典的词源编辑。把给定的**日文**词源考据译成中文。

输入是一个 JSON 对象：键是编号，值含 t（日文词源正文），可能还有 w（这条词源所属的韩语词头）。
输出**同样的键**，值是 {"zh": "中文译文"}。键一个不许少、不许多、不许改。

🔴 最要紧的一条：**被引用的语言形式一个字符都不许改。**
   韩语词形、中世韩语、古谚文、汉字、罗马字转写、被引用的日语词（假名），都是**证据**，原样抄进译文：
   - 古谚文的字母与**声点**（例如 열〯다〮 里的 〯 和 〮），**不许规范成现代写法**（不许写成 열다）
   - 罗马字与耶鲁式上的符号（yěl-tá、súmùy-tá）原样保留
   - 被当作词源引用的日语词（例如「日本語 かばん からの借用語」里的 かばん）原样保留，不许译掉
   - 汉字字形不许改（釋 不许改成 释，竜 不许改成 龙）

其余规矩：
1. 日语写的**释义**要译成中文：`사냥 (sanyang)「狩り」` → `사냥 (sanyang)「狩猎」`。
2. **存疑必须保留**：句末的「か」、「〜と思われる」「〜説」「不明」，译成「可能」「或许」「一说」「不明」。
   🔴 抹掉存疑就是把一个假说说成了定论 —— 这比漏译严重。
3. 术语：中期朝鮮語＝中世韩语｜近代朝鮮語＝近代韩语｜古代朝鮮語＝古韩语｜朝鮮語＝韩语｜漢字語＝汉字词｜
   固有語＝固有词｜借用語＝借词｜初出＝首见｜イェール式＝耶鲁式｜接尾辞＝后缀｜接頭辞＝前缀｜使役＝使动
   「英語 X からの借用語」→「借自英语 X」；「…で…として初出」→「首见于…，作…」。
4. 文献名保留原来的汉字与书名号：『釈譜詳節』→《釈譜詳節》。
5. 原文用 `+` 连接构词成分的，译文也用 `+`。
6. **只输出译文**，不加解释、不补原文没有的考据。原文里残留的维基模板（如 `{{m|en|phone`）照抄，不要修。
7. w 只是帮你消歧的参考，**不许出现在输出里**（除非它本来就在 t 里）。"""

PROBE = {
    "__j1": {"t": "英語 error からの借用語",
             "want": ("英语",), "want2": ("error",), "bad": ("からの", "借用語")},
    "__j2": {"t": "1447年、『竜飛御天歌』で中期朝鮮語 열〯다〮 (イェール式: yěl-tá) として初出。",
             "want": ("열〯다〮",), "want2": ("yěl-tá",), "bad": ("열다", "として")},
    "__j3": {"t": "옳다 (olt'a) + 바르다 (parŭda)か。",
             "want": HEDGE_ZH, "want2": ("옳다",), "bad": ()},
    "__j4": {"t": "사냥 (sanyang)「狩り」 + 개 (kae)「犬」",
             "want": ("狩猎", "打猎", "狩獵", "打獵"), "want2": ("狗", "犬"), "bad": ("狩り",)},
    "__j5": {"t": "몸 (mom) + 짓 (chit)", "w": "자전거",
             "want": ("몸",), "want2": ("짓",), "bad": ("自行车", "自行車", "자전거")},
    "__j6": {"t": "日本語 かばん からの借用語",
             "want": ("かばん",), "want2": ("日语",), "bad": ("からの",)},
}


def collect(con):
    """→ (rows, stat)。rows = (word_id, word, etym_no, text, src_ref)。键与韩文版收割器同一套形状。"""
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    known = known_hanja(con)
    rows, stat, seen = [], collections.Counter(), collections.Counter()
    with gzip.open(paths.JA_EDITION, "rt", encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            w = d.get("word")
            if not w or not w.strip():
                continue
            praw = d.get("pos") or "unknown"
            en_ = d.get("etymology_number")
            etym = str(en_) if en_ is not None else "0"
            k = (w, praw, etym)
            seq = seen[k]
            seen[k] += 1
            text, kind = ko_etymology(d.get("etymology_texts"), known.get(w, ()))
            if kind == "无":
                continue
            stat["有词源字段"] += 1
            if text is None:
                stat[kind] += 1
                continue
            if w not in wid:
                stat["不收·词不在 dict"] += 1
                continue
            stat["收·" + kind] += 1
            rows.append((wid[w], w, etym, text, "%s:%s:%s:%s:%d" % (EDITION, w, praw, etym, seq)))
    return rows, stat


def pick_slice(rows, frac):
    k = int(frac * 0xFFFF)
    return [r for r in rows if int(hashlib.md5(r[4].encode()).hexdigest()[:4], 16) < k]


def build(rows):
    batches, meta = [], []
    cur, m, size = {}, [], 0
    order = list(PROBE)

    def flush():
        if not cur:
            return
        ck = order[len(batches) % len(order)]
        cur[ck] = {x: PROBE[ck][x] for x in ("t", "w") if x in PROBE[ck]}
        m.append((ck, ck))
        batches.append(dict(cur))
        meta.append(list(m))
        cur.clear()
        m.clear()

    for _wid, word, _e, text, ref in rows:
        if cur and (size + len(text) > CHAR_BUDGET or len(cur) >= MAX_PER_BATCH):
            flush()
            size = 0
        cur[ref] = {"t": text, "w": word}
        m.append((ref, ref))
        size += len(text)
    flush()
    return batches, meta


def answers():
    got = {}
    for p in sorted(OUT.glob("*.jsonl")):
        for line in p.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            k, zh = str(d.get("id") or ""), (d.get("zh") or "").strip()
            if k and zh:
                got[k] = zh
    return got


def shape_problems(text, zh):
    """译文的形状检查 → [问题]。回收与闸共用这一份（判据只有一个家）。"""
    bad = []
    for tok in set(KO_RUN.findall(text)):
        if tok not in zh:
            bad.append("韩语/古谚文形式丢了或被改了：%s" % tok)
            break
    extra_kana = [k for k in KANA.findall(zh) if k not in text]
    if extra_kana:
        bad.append("译文里有原文没有的假名：%s" % extra_kana[0])
    if JA_GRAMMAR.search(zh):
        bad.append("译文里残留日语语法：%s" % JA_GRAMMAR.search(zh).group(0))
    if HEDGE_JA.search(text) and not any(h in zh for h in HEDGE_ZH + ("一说",)):
        bad.append("存疑被抹掉（假说变成了断言）")
    if len(zh) < 0.25 * len(text):
        bad.append("译文过短")
    return bad


def audit(rows, got, ntok, peak):
    print("\n═══ 控制组（六条，各对着一种坏法）═══")
    bad = []
    for k, v in PROBE.items():
        ans = got.get(k)
        if ans is None:
            bad.append((k, "没回来"))
            continue
        for key in ("want", "want2"):
            need = v.get(key) or ()
            if need and not any(x in ans for x in need):
                bad.append((k, "答成 %r —— 该含 %s" % (ans[:70], "/".join(need[:4]))))
        for x in v.get("bad", ()):
            if x in ans:
                bad.append((k, "🔴 不该出现：%r（答 %r）" % (x, ans[:60])))
    print("   %s 定题 %d 条问题" % ("✅" if not bad else "🔴", len(bad)))
    for k, why in bad:
        print("      🔴 %s %s" % (k, why))
    want = {r[4] for r in rows}
    lost = want - set(got)
    print("   %s 逐键点名 回来 %s / 要 %s（丢 %s）"
          % ("✅" if not lost else "🔴", f(len(want & set(got))), f(len(want)), f(len(lost))))
    shape = collections.Counter()
    ex = collections.defaultdict(list)
    for _w, word, _e, text, ref in rows:
        zh = got.get(ref)
        if zh is None:
            continue
        for p in shape_problems(text, zh):
            k = p.split("：")[0]
            shape[k] += 1
            if len(ex[k]) < 4:
                ex[k].append((word, text[:70], zh[:70]))
    print("   %s 形状 坏 %s" % ("✅" if not shape else "⚠️", f(sum(shape.values()))))
    for k, v in shape.most_common():
        print("      %-36s %s" % (k, f(v)))
        for w, s, a in ex[k]:
            print("          %s | %s\n              → %s" % (w, s, a))
    print("\n═══ 单价（%s）═══ 总 token %s ／ 成功 %s 条 ⇒ 每条 %.1f token"
          % ("🔴 高峰全价" if peak else "✅ 空闲半价", f(ntok), f(len(want & set(got))),
             ntok / max(len(want & set(got)), 1)))
    print("\n■ 抽样（人眼看）")
    for _w, word, _e, text, ref in rows[:12]:
        print("   %-8s %s\n            → %s" % (word[:8], text[:80], (got.get(ref) or "")[:80]))
    return bad, lost, shape


def publishable(rows, got):
    """哪些行真的落库：有译文、且译文形状过关。🔴 「哪些行才真的落库」也是判据（vi 阶段 8 那一课）
    —— 写库与外锚闸都问这一个函数，不各写一份。"""
    return [r for r in rows if r[4] in got and not shape_problems(r[3], got[r[4]])]


def apply(rows, got):
    ok = publishable(rows, got)
    skip = len(rows) - len(ok)
    print("■ 原文 %s 条；有译文且形状过关 %s 条；不写 %s 条（没有译文的日文版行不进库 —— 进了也不许印）"
          % (f(len(rows)), f(len(ok)), f(skip)))
    con = sqlite3.connect(paths.DB)
    if "etymology_gloss" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        from translate_etymology import create_table
        con.close()
        create_table()
    else:
        con.close()
    with dbtool.session(
            "ko-k36-ja-etymology",
            expect={"#etymology": len(ok), "#etymology_gloss": len(ok)},
            invalidates=[
                "展示层：日文版词源只印 `etymology_gloss` 的中文，没有中文的不印 —— `korean.ts` 必须同步",
            ]) as s:
        for wid, _w, etym, text, ref in ok:
            cur = s.execute(
                "INSERT INTO etymology (word_id, entry_id, edition, etym_no, text, src, src_ref)"
                " VALUES (?,NULL,?,?,?,?,?)", (wid, EDITION, etym, text, paths.JA_EDITION.name, ref))
            s.execute("INSERT INTO etymology_gloss (etymology_id, lang, text, src) VALUES (?,'zh',?,?)",
                      (cur.lastrowid, got[ref], SRC_MODEL))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("日文版词源行", q("SELECT COUNT(*) FROM etymology WHERE edition='ja-edition'"), len(ok)),
        ("🔴 日文版行没有中文译文", q("SELECT COUNT(*) FROM etymology e WHERE edition='ja-edition' AND NOT EXISTS("
                             "SELECT 1 FROM etymology_gloss g WHERE g.etymology_id=e.id AND g.lang='zh')"), 0),
        ("🔴 译文挂在非日文版行上", q("SELECT COUNT(*) FROM etymology_gloss g JOIN etymology e ON e.id=g.etymology_id "
                              "WHERE e.edition<>'ja-edition'"), 0),
        ("🔴 日文版行挂了 entry", q("SELECT COUNT(*) FROM etymology WHERE edition='ja-edition' AND entry_id IS NOT NULL"), 0),
    ]
    red = 0
    print("\n■ 写后回核（从库里重算）")
    for name, got_n, want in checks:
        red += got_n != want
        print("   %s %-26s %8s  期望 %8s" % ("✅" if got_n == want else "🔴", name, f(got_n), f(want)))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--translate", action="store_true")
    ap.add_argument("--slice", type=float, default=0.0)
    ap.add_argument("--conc", type=int, default=60)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if con.execute("SELECT COUNT(*) FROM etymology WHERE edition=?", (EDITION,)).fetchone()[0]:
        raise SystemExit("🔴 已有日文版词源 —— 本脚本只做首次收录")
    rows, stat = collect(con)
    con.close()
    print("■ 日文版词源")
    for k, v in sorted(stat.items()):
        print("   %-30s %7s" % (k, f(v)))
    print("   %-30s %7s 条 / %s 字" % ("── 要译的", f(len(rows)), f(sum(len(r[3]) for r in rows))))
    if a.apply:
        apply(rows, answers())
        return
    if not a.translate:
        print("\n（干跑。--translate 跑批，--apply 写库）")
        return
    peak = ds_batch.announce_window()
    got = answers()
    todo = [r for r in (pick_slice(rows, a.slice) if a.slice else rows) if r[4] not in got]
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "slice" if a.slice else "all"
    path = OUT / ("%s.jsonl" % tag)
    batches, meta = build(todo)
    print("\n■ 日文词源 → zh：%s 条，%s 批" % (f(len(todo)), f(len(batches))))
    if todo:
        ntok = asyncio.run(ds_batch.run(SYS, batches, meta, path, mode="flash", conc=a.conc, every=5))
        tp = OUT / "tokens.json"
        prev = json.loads(tp.read_text()) if tp.exists() else {"tok": 0, "runs": []}
        prev["tok"] += ntok
        prev["runs"].append({"tok": ntok, "n": len(todo), "peak": peak})
        tp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    tok = json.loads((OUT / "tokens.json").read_text())["tok"] if (OUT / "tokens.json").exists() else 0
    scope = pick_slice(rows, a.slice) if a.slice else rows
    audit(scope, answers(), tok, peak)


if __name__ == "__main__":
    main()
