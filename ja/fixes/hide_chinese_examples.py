#!/usr/bin/env python3
"""修：中文版例句里，「日语原句」那一列装的是中文。2026-09-16（阶段 5e 收尾）。

═══ 这是阶段 5a **明说过判据管不到**的那一类 ═══
阶段 5a 用「含简体专用字」把 1,624 条中文挡在了外面，并在账上写明：

    ⚠️ 判据管不到的那一类，明说：不带任何括号、直接内嵌的纯汉字日文词识别不了。
       量不出来（纯汉字串字形上分不出中日），所以不假装它不存在。
       🔴 推翻/收紧它需要：出现一种能标出「这段是日文引用」的结构信号，或者有人报出实例。

**推翻条件兑现了** —— 阶段 5e 跑完翻译，出现了一个当时没有的信号：
**模型把整句原样抄了回来**。`慢慢地走。`／`悲喜交集。`／`抓住手腕不放。`
模型没错，它抄回来是因为**没东西可翻**。

⚠️ 这正是 `[[record-the-negative-decision]]` 要求写推翻条件的用处：
   当时写不出判据是事实，但写下了「什么会让这个结论失效」，
   于是三小时后新证据出现时，它是**被认出来的**，而不是又一次偶然撞见。

═══ 判据：三个条件同时成立才算 ═══
    ① 来源是中文版 且 源头**没给** `translation`（给了的那批 text 已证明是日语）
    ② 正文**不含假名**
    ③ 模型把它**原样抄了回来**
🔴 三条缺一不可。单看③会咬到 `昭和新山`／`上位概念`／`横尾太郎` ——
   那些是**纯汉字的日语**，抄回来是正确译文（汉语里就这么写）。

═══ 两条收窄（各自都有实例）═══
④ **正文本身就是库里的一个日语词头** ⇒ 放过（`幸`／`西洋人`／`橘`／`小船`／`望`，5 条）
⑤ **逗号分段后每段都是库内词头** ⇒ 放过（`のあ` 的例句是
   `希杏，希歩，希海，…` —— 日语人名写法列表，不是中文）

⚠️ **残余误判说清**：抽 20 条读，收窄之前 1 条误判（5%）；两条收窄之后抽样未再见到，
   但样本小，**估计仍有个位数**。⇒ 处置是 `hidden=1` **不是删除** ——
   证据层一个字不动，判错了随时翻回来（`[[prefer-reversible-designs]]`）。

⚠️ 顺带承认：这 440 条在阶段 5e 里是**付了钱的**（约 1% 的开销），
   因为发现它们的正是那次付费跑批。

跑：
    python3 -u ja/fixes/hide_chinese_examples.py
    python3 -u ja/fixes/hide_chinese_examples.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import json
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
SEG = re.compile(r"[，,、；;]")
OUT = paths.WORK / "runs" / "examples_zh.jsonl"


def find(con):
    words = {w for (w,) in con.execute("SELECT word FROM dict")}
    meta = {r[0]: (r[1], r[2], r[3], r[4]) for r in con.execute(
        "SELECT id, word, text, src, src_translation FROM example")}
    hit, spared = [], []
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        xid, zh = r.get("id"), (r.get("zh") or "").strip()
        w, t, src, tr = meta.get(xid, ("", "", "", None))
        t = (t or "").strip()
        if not (zh and zh == t and src == "zh-edition" and not tr and not KANA.search(t)):
            continue
        # ④ 正文就是一个日语词头
        if t in words:
            spared.append((xid, w, t, "正文是库内词头"))
            continue
        # ⑤ 逗号分段后每段都是词头（`希杏，希歩，希海…` 是日语人名列表）
        segs = [x.strip() for x in SEG.split(t) if x.strip()]
        if len(segs) >= 2 and all(s in words for s in segs):
            spared.append((xid, w, t, "逗号分段全是词头（日语列表）"))
            continue
        hit.append((xid, w, t))
    return hit, spared


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    hit, spared = find(con)
    con.close()
    print("■ 判为中文 %s 条 ｜ 收窄放过 %s 条" % (f(len(hit)), f(len(spared))))
    for _i, w, t, why in spared[:8]:
        print("   放过 %-10s %-24s（%s）" % (w[:10], t[:24], why))
    print()
    for _i, w, t in hit[:10]:
        print("   隐藏 %-10s %s" % (w[:10], t[:40]))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        return
    with dbtool.session("ja-hide-chinese-examples", expect={
            "__rows__": 0, "#example": 0, "#example_gloss": 0,
            "#entry": 0, "#sense": 0}) as con:
        # 🔴 `hidden=1` 不是 DELETE —— 判错了要翻得回来
        # 🔴 **按 id 去重再写**。答案文件里切片那 450 条和全量重叠，
        #    同一个 id 会出现两次 ⇒ `len(hit)` 是 440 而**不同 id 只有 438**，
        #    断言拿 `len(hit)` 当期望就报了假红。
        con.executemany("UPDATE example SET hidden=1 WHERE id=?",
                        [(i,) for i in {x[0] for x in hit}])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("隐藏的都还在表里（没被删）", q(
            "SELECT COUNT(*) FROM example WHERE hidden=1") >= len({x[0] for x in hit})),
        ("没有隐藏掉带假名的例句", q(
            "SELECT COUNT(*) FROM example WHERE hidden=1"
            " AND (text GLOB '*[ぁ-ゖ]*' OR text GLOB '*[ァ-ヺ]*')") == 0),
        ("没有隐藏掉非中文版的例句", q(
            "SELECT COUNT(*) FROM example WHERE hidden=1 AND src<>'zh-edition'") == 0),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    con.close()
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
