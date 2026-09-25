#!/usr/bin/env python3
"""阶段 6d：把缺中文的 33,811 条例句译成中文。2026-09-24。

═══ 盘子 ═══
    例句 38,224（hidden 117）
      ├ 已有中文   4,296   ← 中文两片用**全角空格**挤在 `text` 同一格里，白送
      └ 🔴 缺中文  33,811
           ├ 挂在**出版义项**下   17,721 (52.4%)   读者一定看得到
           ├ 词级、而词本身有出版义项 15,141 (44.8%)  读者也看得到（词级例句区）
           ├ 词级、词没有出版义项      949 ( 2.8%)
           └ 挂在 hidden 义项下         0 ( 0.0%)   ← **阶段 9 的展示形态不会缩小这个盘子**

⭐ **没有「例句怪物」**：每义项平均 1.42 条、每词形 2.37 条，封顶到 3 条只省 4.0%
   （`[[display-extremes-doc]]` 那种"关系怪物/义项怪物"的形状在这一层不存在）
   ⇒ 先封顶再翻译省不下钱，不做这一步。

═══ 🔴 为什么排在阶段 8 之前（用户 2026-09-24 问过「能不能放到 8、9 后面」）═══
技术上没有依赖 —— 它只往已有的 `example_gloss` 填行，不动 schema。但推后要付两笔：
 ① 阶段 8 的闸会锁一个随后就变的覆盖率下限 ⇒ **闸要建两遍**；
 ② 阶段 9 的验收会失真 —— **接上展示层是独立一道闸**
    （`[[it-display-layer-stage8]]`：三层数据全绿，真渲染出来才看见三个缺陷）。
    88% 的例句显示成光秃秃的韩语句时，没法判断例句区的排版好不好用，填完还得再判一次。

═══ 🔴 这不是「译释义」那个任务，prompt 不能照抄 ═══
阶段 5 译的是**词典释义**（要词典体例、不要句号、不要译成句子）；
这一步译的是**例句**（要自然的中文句子、标点要跟原文走）。
⚠️ 照抄阶段 5 的 `SYS` 会让模型把句子压成短语 —— **同一个 prompt 在两种任务上意思相反**。

═══ 🔴 控制组对着三种坏法，外加这一步**独有**的第四种 ═══
  · 错位     —— 每批注入定题，答案对不上就是 id 对齐坏了
  · 静默丢批 —— 回收时逐 id 点名
  · 答非所问 —— 形状检查（混进谚文/罗马字/把词头单独译出来）
  · 🔴 **上下文泄漏**（这一步独有）—— 我要给模型 `w`（词头）和 `e`（英文译文）
    当消歧材料，而 `[[context-you-give-leaks-into-output]]`：
    **给模型的「仅供参考」上下文会直接漏进输出**。
    ⇒ 定题里专门放一条：上下文给的是别的词，答案里不许出现它。

跑（在仓库根）：
    python3 -u ko/pipeline/translate_examples.py --slice 0.01    # 实测单价
    python3 -u ko/pipeline/translate_examples.py --conc 60       # 正式跑
    python3 -u ko/pipeline/translate_examples.py --load --apply  # 回收进库
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import asyncio
import collections
import hashlib
import json
import re
import sqlite3

import dbtool
import ds_batch
import paths

f = lambda n: format(n, ",")
PER_BATCH = 20
OUT = paths.WORK / "example_zh"
SRC_MODEL = "model:deepseek-v4-flash"
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]{3,}")

SYS = """你是韩汉词典的例句编辑。把给定的韩语例句译成中文。

输入是一个 JSON 对象：键是例句编号，值含 s（韩语例句原文），
可能还有 w（这条例句所属的词头）、e（已有的英文译文）。
输出**同样的键**，值是 {"zh": "中文译文"}。键一个不许少、不许多、不许改。

规矩：
1. 译成**自然的中文句子**，不是词典释义。该是句子就是句子，该是短语就是短语，
   跟着原文的形态走。
2. **标点跟着原文**：原文有句号就有句号，原文没有就不要加；原文是问句就是问句。
3. **只输出译文**。不要输出韩语原文、不要加罗马字或音标、不要加「意思是」「译：」
   这类引导语、不要解释语法。
4. 🔴 **w 和 e 只是帮你消歧的参考，不许出现在输出里**，也不要单独把词头译出来
   再拼到句子上。e 是英文译文，可能本身就不准，**以韩语原文 s 为准**。
5. 例句里的人名、地名按通行译法；没有通行译法的按音译，不要留韩文。
6. 原文是残句、俗语、诗句的，照它的样子译，不要补全成完整句子。
7. 吃不准的直译，**不要编造**，不要为了通顺增添原文没有的信息。
8. 原文里的引号、括号保留，用中文标点。"""

# 🔴 控制组的定题。前三条验 id 对齐，第四条验**上下文泄漏**。
PROBE = {
    "__c1": {"s": "물을 마셔요.", "want": ("水",), "bad": ()},
    "__c2": {"s": "저는 한국 사람입니다.", "want": ("韩国", "韓國"), "bad": ()},
    "__c3": {"s": "오늘은 날씨가 좋다.", "want": ("天气", "天氣"), "bad": ()},
    # ⚠️ 这一条的 `w` 和 `e` 故意与句子**无关**：句子讲的是下雨，
    #    而上下文说词头是「자전거（自行车）」、英文译文是一句不相干的话。
    #    若输出里出现「自行车」或「library」，就是上下文漏进了输出。
    "__c4": {"s": "비가 옵니다.", "w": "자전거", "e": "The library is closed.",
             "want": ("雨",), "bad": ("自行车", "自行車", "图书馆", "圖書館", "library")},
}


def gap_rows(con):
    """缺中文的例句。**口径只写一份。**

    ⚠️ `hidden=1` 的不译（那 117 条是「多行挤成一格」的 blob，本来就不上页面）。
    """
    return con.execute("""
        SELECT e.id, e.word, e.text,
               (SELECT g.text FROM example_gloss g
                 WHERE g.example_id = e.id AND g.lang = 'en' LIMIT 1)
          FROM example e
         WHERE COALESCE(e.hidden, 0) = 0
           AND NOT EXISTS (SELECT 1 FROM example_gloss g
                            WHERE g.example_id = e.id AND g.lang = 'zh')
         ORDER BY e.id
    """).fetchall()


def pick_slice(rows, frac):
    """按例句主键的稳定哈希抽 —— **不是 `rows[::n]`**（那是先截断再抽）。"""
    k = int(frac * 0xFFFF)
    return [r for r in rows
            if int(hashlib.md5(str(r[0]).encode()).hexdigest()[:4], 16) < k]


def build(rows):
    batches, meta = [], []
    for i in range(0, len(rows), PER_BATCH):
        chunk = rows[i:i + PER_BATCH]
        pay = {}
        m = []
        for eid, w, text, en in chunk:
            d = {"s": text}
            if w:
                d["w"] = w
            if en:
                d["e"] = en
            pay[str(eid)] = d
            m.append((str(eid), eid))
        ck = list(PROBE)[i // PER_BATCH % len(PROBE)]
        pay[ck] = {x: PROBE[ck][x] for x in ("s", "w", "e") if x in PROBE[ck]}
        m.append((ck, ck))
        batches.append(pay)
        meta.append(m)
    return batches, meta


def load(dry=True):
    """把答案文件写进 `example_gloss`。"""
    got = {}
    for p in sorted(OUT.glob("*.jsonl")):
        for line in p.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            k, zh = d.get("id"), (d.get("zh") or "").strip()
            if not k or str(k).startswith("__"):
                continue
            try:
                k = int(k)
            except (TypeError, ValueError):
                continue
            if zh:
                got[k] = zh
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    need = {r[0] for r in gap_rows(con)}
    con.close()
    rows = [(k, v) for k, v in got.items() if k in need]
    print("■ 答案文件里 %s 条；其中仍在缺口里的 %s 条" % (f(len(got)), f(len(rows))))
    skipped = len(got) - len(rows)
    if skipped:
        print("   （%s 条已经不在缺口里 —— 上一轮已落库或例句被改过，不重复写）"
              % f(skipped))
    if dry:
        print("\n（干跑。确认后 --load --apply）")
        return
    with dbtool.session(
            "ko-load-example-zh",
            expect={"#example_gloss": len(rows)},
            invalidates=[
                "🔴 例句的中文译文有 `src='model:deepseek-v4-flash'` 这一档 —— "
                "与中文两片**白送**的 4,296 条不是一回事，展示层与验收都要能分开",
                "阶段 8 的闸：例句中文覆盖率的下限要在**确认落点之后**再设",
            ]) as s:
        for i in range(0, len(rows), 20000):
            s.executemany(
                "INSERT OR IGNORE INTO example_gloss (example_id, lang, text, src)"
                " VALUES (?,'zh',?,?)",
                [(k, v, SRC_MODEL) for k, v in rows[i:i + 20000]])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n■ 写后回核（从库里重算）")
    left = q("""SELECT COUNT(*) FROM example e WHERE COALESCE(e.hidden,0)=0
        AND NOT EXISTS(SELECT 1 FROM example_gloss g
                        WHERE g.example_id=e.id AND g.lang='zh')""")
    print("   模型译文行            %9s" % f(q(
        "SELECT COUNT(*) FROM example_gloss WHERE lang='zh' AND src='%s'" % SRC_MODEL)))
    print("   仍缺中文的例句        %9s" % f(left))
    print("   例句中文覆盖率        %8.2f%%" % q(
        """SELECT 100.0*SUM(CASE WHEN EXISTS(SELECT 1 FROM example_gloss g
             WHERE g.example_id=e.id AND g.lang='zh') THEN 1 ELSE 0 END)/COUNT(*)
           FROM example e WHERE COALESCE(e.hidden,0)=0"""))
    con.close()


def audit(path, rows, ntok, peak):
    got = {}
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        got[d["id"]] = d.get("zh")
    print("\n═══ 控制组 ═══")
    bad = []
    for k, v in PROBE.items():
        ans = got.get(k)
        if ans is None:
            bad.append((k, "没回来"))
            continue
        if not any(x in ans for x in v["want"]):
            bad.append((k, "答成 %r（该含 %s）" % (ans, "/".join(v["want"]))))
        for x in v.get("bad", ()):
            if x in ans:
                bad.append((k, "🔴 **上下文漏进输出**：答案里出现了 %r" % x))
    print("   %s 定题对齐（含上下文泄漏那一条） %d/%d"
          % ("✅" if not bad else "🔴", len(PROBE) - len(bad), len(PROBE)))
    for k, why in bad:
        print("      🔴 %s %s" % (k, why))
    want = {eid for eid, *_ in rows}
    back = {k for k in got if not str(k).startswith("__")}
    lost = want - back
    print("   %s 逐 id 点名       回来 %s / 要 %s（丢 %s）"
          % ("✅" if not lost else "🔴", f(len(back & want)), f(len(want)), f(len(lost))))
    shape = collections.Counter()
    for eid, w, text, en in rows:
        a = got.get(str(eid)) or got.get(eid)
        if a is None:
            continue
        if not a.strip():
            shape["空"] += 1
        if HANGUL.search(a):
            shape["混进谚文（原文是韩语，译文不该有）"] += 1
        if LATIN.search(a) and not LATIN.search(text):
            shape["混进拉丁词（原文没有）"] += 1
        if en and en.lower() in a.lower():
            shape["🔴 英文译文原样漏进输出"] += 1
        if w and len(a) <= len(w) + 1 and w not in text:
            shape["疑似只译了词头"] += 1
    n = len(rows)
    print("   %s 形状             坏 %s / %s"
          % ("✅" if not shape else "⚠️", f(sum(shape.values())), f(n)))
    for k, v in shape.most_common():
        print("      ⚠️ %-32s %s" % (k, f(v)))
    print("\n═══ 单价（%s）═══" % ("🔴 高峰全价" if peak else "✅ 空闲半价"))
    ok = len(back & want)
    print("   总 token %s ／ 成功 %s 条 ⇒ **每条 %.1f token**"
          % (f(ntok), f(ok), ntok / max(ok, 1)))
    print("   ⚠️ 折算到全量乘的是**条数**，不是切片比例")
    print("\n■ 抽样（人眼看 —— 形状检查看不出「译错了」）")
    for eid, w, text, en in rows[:12]:
        a = got.get(str(eid)) or got.get(eid) or ""
        print("   %-10s %-42s → %s" % (w[:10], text[:42], a[:40]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--slice", type=float, default=0.0)
    ap.add_argument("--conc", type=int, default=60)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if a.load:
        load(dry=not a.apply)
        return
    peak = ds_batch.announce_window()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = gap_rows(con)
    con.close()
    if a.slice:
        rows = pick_slice(rows, a.slice)
    OUT.mkdir(parents=True, exist_ok=True)
    tag = a.tag or ("slice" if a.slice else "all")
    path = OUT / ("%s.jsonl" % tag)
    batches, meta = build(rows)
    print("\n■ 例句 → zh：%s 条，%s 批（每批 %d ＋ 1 条定题）"
          % (f(len(rows)), f(len(batches)), PER_BATCH))
    if not rows:
        return
    ntok = asyncio.run(ds_batch.run(SYS, batches, meta, path,
                                    mode="flash", conc=a.conc, every=5))
    tp = path.with_suffix(".tokens.json")
    prev = json.loads(tp.read_text()) if tp.exists() else {"tok": 0, "runs": []}
    prev["tok"] += ntok
    prev["runs"].append({"tok": ntok, "n": len(rows), "peak": peak})
    tp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    audit(path, rows, prev["tok"], peak)


if __name__ == "__main__":
    main()
