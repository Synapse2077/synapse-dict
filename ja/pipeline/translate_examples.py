#!/usr/bin/env python3
"""阶段 5e —— 例句中文译文（付费）。2026-09-16。

═══ 为什么要买：这是读者能看到的最大一块空白 ═══
    例句 53,309 条，**44,723 条（83.9%）没有中文译文**。
    免费路径已经用尽：中文版白送的 8,586 条阶段 5a 已经收了，三版再没有别的中文源
    （`[[prove-free-path-before-quoting]]`）。

    其中 16,100 条有**英文译文**可当参考，28,623 条只有日语原句。

═══ 🔴 一道题，不是两道 ═══
一律**从日语原句翻**，英文译文只当**参考**传进去。
理由：英文译文是维基编者写的二手转述，拿它当源会把误差叠一层；
而日语原句是一手的。⚠️ 但英文常常点明了省略的主语/语气，所以带上有用。
🔴 **英文只是参考，不许输出英文** —— `[[context-you-give-leaks-into-output]]`：
   给模型的「仅供参考」上下文会直接漏进输出，SYS 规则 3 专门堵这个。

═══ 🔴🔴 控制组**不能复用释义那一套** ═══
`ctrl.check()` 的 E5「带句末标点」对释义成立（释义是短语），
对例句译文**正好是反的**（它就是句子）。实测：拿 `check()` 判正确例句，
**2/2 条被判成 E5**。⇒ 另写 `ctrl.check_example()`，变异自检 8/8。

用法（在仓库根）：
    python3 -u ja/pipeline/translate_examples.py --slice 1     # 1% 切片，先量单价
    python3 -u ja/pipeline/translate_examples.py --read        # 逐条读切片结果
    python3 -u ja/pipeline/translate_examples.py               # 全量
    python3 -u ja/pipeline/translate_examples.py --load        # 落库
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import asyncio
import collections
import json
import sqlite3

import ctrl
import dbtool
import ds_batch
import paths

f = lambda n: format(n, ",")
OUT = paths.WORK / "runs" / "examples_zh.jsonl"

SYS = """你在把日语例句翻译成中文，用于一部给中文读者的日语词典。

输入是一个 JSON 对象，键是例句编号，值含：
  ja   日语原句（**这是要翻译的对象**）
  word 这条例句在给哪个词做示例
  gloss 那个词的中文释义（仅供你确定语境）
  en   英文译文（**仅供参考**，可能没有）

规则：
1. 翻译 `ja`，输出自然的**简体中文**句子。不要逐字直译。
2. 保持原句的语气与文体：敬体译成书面礼貌语气，简体/口语译成口语。
3. 🔴 **`gloss` 和 `en` 只是给你看的上下文，一个字都不许出现在输出里。**
   尤其不要把英文译文抄过去，也不要把释义当成译文。
4. 例句是句子，**该有句号/问号就写**。
5. 人名、地名、作品名：有通行中文译名就用；没有就保留日语汉字原形。
   纯假名的专名（`ドラえもん`）用通行译名（哆啦A梦），没有就保留原文。
6. 拟声拟态词按意思译（`ざあざあ` → 哗啦哗啦），不要音译。
7. 句中被解释的那个词要译准 —— 它是这条例句存在的理由。
8. 数字、型号、拉丁缩写（`C++`、`DVD`）原样保留。
9. 看不懂或残缺到无法翻译时，`zh` 写空字符串 ""。**不要猜，不要编。**

只输出 JSON 对象，形如：
{"12345": {"zh": "我头疼。"}, "12346": {"zh": "……"}}
"""


def pool(slice_pct=None):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("""
        SELECT x.id, x.word, x.text,
               (SELECT g.text FROM example_gloss g
                 WHERE g.example_id=x.id AND g.lang='en') AS en,
               (SELECT g2.text FROM sense_gloss g2
                 WHERE g2.sense_id=x.sense_id AND g2.lang='zh') AS gloss
        FROM example x
        WHERE x.hidden=0
          AND NOT EXISTS(SELECT 1 FROM example_gloss g
                          WHERE g.example_id=x.id AND g.lang='zh')
        ORDER BY x.id""").fetchall()
    con.close()
    out = []
    for xid, word, text, en, gloss in rows:
        # 🔴 切片判据用 `id % 100`，确定性可复现
        if slice_pct is not None and xid % 100 >= slice_pct:
            continue
        p = {"id": xid, "ja": text, "word": word}
        if gloss:
            p["gloss"] = gloss[:60]
        if en:
            p["en"] = en[:200]
        out.append(p)
    return out


def batches(items, per=20):
    bs, meta = [], []
    for i in range(0, len(items), per):
        chunk = items[i:i + per]
        bs.append({str(p["id"]): {k: v for k, v in p.items() if k != "id"}
                   for p in chunk})
        meta.append([(str(p["id"]), p["id"]) for p in chunk])
    return bs, meta


def read_back():
    """逐条读 + 过控制组。🔴 判据 import `ctrl.check_example`，不手抄。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    src = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT id, text, word FROM example")}
    con.close()
    if not OUT.exists():
        print("🔴 还没有结果文件 %s" % OUT)
        return
    st = collections.Counter()
    samples = collections.defaultdict(list)
    n = 0
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        xid, zh = r.get("id"), (r.get("zh") or "").strip()
        ja, word = src.get(xid, ("", ""))
        n += 1
        bad = ctrl.check_example(zh, ja)
        if not bad:
            st["干净"] += 1
            if len(samples["ok"]) < 8:
                samples["ok"].append((word, ja[:26], zh[:30]))
            continue
        for code, why in bad:
            st[code + " " + why] += 1
            if len(samples[code]) < 3:
                samples[code].append((word, ja[:26], zh[:30]))
        st["真失败" if any(c[0] == "E" for c, _ in bad) else "警告"] += 1
    print("■ 读回 %s 条" % f(n))
    for k in sorted(st):
        print("   %-40s %6s  (%.2f%%)" % (k, f(st[k]), 100 * st[k] / max(n, 1)))
    print("\n── 干净样本 ──")
    for w, ja, zh in samples["ok"]:
        print("   %-8s %-28s → %s" % (w, ja, zh))
    for code in sorted(k for k in samples if k != "ok"):
        print("\n── %s ──" % code)
        for w, ja, zh in samples[code]:
            print("   %-8s %-28s → %s" % (w, ja, zh))


def load():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute(
        "SELECT example_id FROM example_gloss WHERE lang='zh'")}
    alive = {r[0] for r in con.execute("SELECT id FROM example")}
    con.close()
    rows, empty, dup, orphan, seen = [], 0, 0, 0, set()
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        xid, zh = r.get("id"), (r.get("zh") or "").strip()
        if xid not in alive:
            orphan += 1
            continue
        if xid in have or xid in seen:
            dup += 1
            continue
        if not zh:
            empty += 1          # 🔴 模型主动弃权的不落，空译文比没有更伤
            continue
        seen.add(xid)
        rows.append((xid, "zh", zh, "model:deepseek-v4-flash:example"))
    print("■ 可落 %s ｜留空不落 %s ｜已有跳过 %s ｜孤儿 %s"
          % (f(len(rows)), f(empty), f(dup), f(orphan)))
    with dbtool.session("ja-translate-examples",
                        expect={"#example_gloss": len(rows)}) as s:
        s.executemany("INSERT INTO example_gloss (example_id, lang, text, src)"
                      " VALUES (?,?,?,?)", rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int)
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--conc", type=int, default=12)
    a = ap.parse_args()
    # 🔴 开跑前确认连的是 ja 的库（`translate_defs` 那个 near-miss 的闸）
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的"
    assert not hasattr(dbtool, "has_han"), "🔴 dbtool 不是 ja 的"
    if a.read:
        return read_back()
    if a.load:
        return load()
    items = pool(a.slice)
    bs, meta = batches(items)
    print("■ 待翻 %s 条 / %s 批%s"
          % (f(len(items)), f(len(bs)), "（%d%% 切片）" % a.slice if a.slice else ""))
    if not items:
        return
    tok = asyncio.run(ds_batch.run(SYS, bs, meta, OUT, mode="flash", conc=a.conc))
    if tok:
        print("■ 单价 %.1f token/条" % (tok / max(len(items), 1)))


if __name__ == "__main__":
    main()
