#!/usr/bin/env python3
"""阶段 5 收尾：给 38,692 条例句配中文。2026-08-18。

═══ 为什么要做 ═══
词典的目的是**给中文用户看**（划词弹窗）。例句只有意语原文、少数有英文译文，
对目标用户等于不存在。这不是"锦上添花"，是把交付物做完。

═══ 三条来自血债的纪律 ═══
① **标识号用数据库主键 `example.id`，不用批内序号**
   （`model-answer-files-key-by-id`：答案文件按「第几条」存，重放时中文会贴到别的行上）。
   prompt 里写死「标识号不是序号，原样回传」。
② **输入不按字数截断**（A46）：最长的一条 994 字符（但丁的引文），完整送。
③ **只喂被翻译的那个字段**（`context-you-give-leaks-into-output`：给模型的"仅供参考"
   上下文会直接漏进输出，1,583 条地名音译被母地名污染）。
   ⇒ 默认**只喂例句原文**。词头、词头的中文释义、已有的英文译文都不喂 ——
   但这是个**可以被量出来**的判断，所以 `--pilot` 里做了消融（A/B/C 三臂），
   由数字决定，不由偏好决定。

═══ 控制组要覆盖每一个输出字段（A47）═══
本任务的输出只有一个字段 `zh`，但**对齐也是一个可以坏的东西** ⇒ 两组判据：
  · 对齐：回传的标识号必须是我发出去的那批主键，且一一对应（确定性，可全量查）
  · 内容：`--pilot` 抽样我自己逐条读（模型不判模型，A34）

用法（在 it/ 目录下）：
    python3 pipeline/translate_examples.py --pilot        # 1% 切片 + 三臂消融，先自己读
    python3 pipeline/translate_examples.py --apply        # 全量
    python3 pipeline/translate_examples.py --verify
"""
import argparse
import asyncio
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool     # noqa: E402
import ds_batch   # noqa: E402
import paths      # noqa: E402

OUT = paths.WORK / "example_zh.jsonl"
PILOT = paths.WORK / "example_zh_pilot"
SRC = "deepseek-v4-flash:example"
B = int(__import__("os").environ.get("EX_BATCH", "20"))
# 每批条数：例句比释义长，批小一点，避免输出上限截断。
# 🔴 2026-08-18 实测：模型会**静默丢掉批里的一部分**（不是报错，是回的 JSON 里就没有那几个 id）。
#    全量一轮后有 2,069 条从没被答过，且每轮丢的是同一批词（`D-o`/`DNA`/`Dante`…）。
#    多跑几轮能收敛（2,069→273→139→83→64），但真正的解法是**把批调小**：
#    `EX_BATCH=5 python3 pipeline/translate_examples.py --apply`。
#    ⚠️ 这与 `prompt-beats-model-choice` 记的 flash 的老毛病同源：输出上限小，
#      批大了就吐不完整 —— 按模型给不同块大小，别怪模型能力。

SYS = """你是意大利语词典编纂助手。把给出的**意大利语例句**翻译成中文。

规则：
1. 逐句翻译，忠实原意；不要解释、不要加注、不要补充原文没有的信息。
2. 保持句子的语体：日常口语译成口语，文学引文（但丁、曼佐尼一类）译成书面语。
3. 专有名词按通行中文译名；没有通行译名的人名地名按音译。
4. 原文里的省略号、引号、破折号照原样保留在译文相应位置。
5. 如果给出的不是一个可翻译的句子（只是符号、模板残渣、或空白），把 zh 留空。
6. 严格只返回 JSON 对象：{"标识号": {"zh": "译文"}, ...}。
   **标识号是每条自带的 n，不是它在这批里的第几个**，原样回传。"""

# 消融用的三臂：默认 A（只喂原文）
ARMS = {
    "A": "只喂例句原文",
    "B": "原文 + 该例句所属的词头",
    "C": "原文 + 词头 + 源头给的英文译文",
}


def payload(row, arm):
    """一条例句 → 送给模型的对象。**arm 决定喂几个字段**，其余一律不喂。"""
    eid, word, text, en = row
    d = {"n": eid, "it": text}
    if arm in ("B", "C"):
        d["词头"] = word
    if arm == "C" and en:
        d["en"] = en
    return d


def scan(con, only_missing=True):
    """→ [(example_id, 词形, 原文, 英文译文或 None)]"""
    sql = """SELECT e.id, e.word, e.text,
                    (SELECT g.text FROM example_gloss g
                      WHERE g.example_id=e.id AND g.lang='en' LIMIT 1)
             FROM example e"""
    if only_missing:
        sql += (" WHERE NOT EXISTS(SELECT 1 FROM example_gloss g2 "
                "WHERE g2.example_id=e.id AND g2.lang='zh' AND trim(COALESCE(g2.text,''))<>'')")
    return con.execute(sql).fetchall()


def batches_of(rows, arm):
    bs, meta = [], []
    for i in range(0, len(rows), B):
        chunk = rows[i:i + B]
        bs.append([payload(r, arm) for r in chunk])
        meta.append([(str(r[0]), r[0]) for r in chunk])
    return bs, meta


def read_out(path):
    """→ {example_id: 中文}。⚠️ 只认我发出去过的主键，模型自己编的键一律丢。"""
    out = {}
    for line in path.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        zh = (r.get("zh") or "").strip()
        if zh:
            out[r["id"]] = zh
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    f = lambda n: format(n, ",")
    checks = [
        ("🔴 ① 本步中文不许为空",
         q("SELECT count(*) FROM example_gloss WHERE src LIKE '%s%%' AND trim(text)=''" % SRC), 0),
        ("🔴 ① 一条例句最多一条中文",
         q("SELECT count(*) FROM (SELECT example_id FROM example_gloss WHERE lang='zh' "
           "GROUP BY example_id HAVING count(*)>1)"), 0),
        ("🔴 ② 中文不许挂到不存在的例句上",
         q("SELECT count(*) FROM example_gloss g WHERE NOT EXISTS"
           "(SELECT 1 FROM example e WHERE e.id=g.example_id)"), 0),
        ("🔴 ② 出版层语言仍只有 zh/en/it",
         q("SELECT count(*) FROM example_gloss WHERE lang NOT IN ('zh','en','it')"), 0),
        # 🔴 对齐：译文与原文逐字相同，通常是"模型把原文抄回来了"这个典型失败。
        #    但**这一批 12 条是真的没法译**，逐条读过，接受为基线（闸必须带基线+理由，
        #    否则永远红、没人看）：
        #      数学/符号  `2 x 3 x 5 = 30` `3,5` `!=` `n!` `∃!`
        #      但丁的无义诗行 `Pape Satàn, pape Satàn aleppe!`
        #      罗马方言   `A scaja jo pia nbocca e sur cazzo je sbratta`
        #      词源记法   `nella < *in la`
        #    ⚠️ 基线是**逐条读过**才定的，不是把红改绿。再涨就要重新逐条看。
        ("译文与原文逐字相同（已逐条核过的基线）",
         q("SELECT count(*) FROM example_gloss g JOIN example e ON e.id=g.example_id "
           "WHERE g.lang='zh' AND g.text = e.text"), 12),
        ("（记账）还没有中文的例句",
         q("SELECT count(*) FROM example e WHERE NOT EXISTS(SELECT 1 FROM example_gloss g "
           "WHERE g.example_id=e.id AND g.lang='zh')"), None),
    ]
    ok = True
    for name, got, want in checks:
        good = want is None or got == want
        ok &= good
        print("   %s %-44s %s%s" % ("✅" if good else "🔴", name, f(got),
                                    "" if want is None else " (期望 %s)" % f(want)))
    return ok


def run_pilot(con):
    """1% 切片 × 三臂消融。**只出文件，不写库** —— 先自己逐条读。"""
    rows = scan(con)
    random.seed(20260818)
    sample = random.sample(rows, 120)
    PILOT.mkdir(parents=True, exist_ok=True)
    tok = {}
    for arm in ARMS:
        p = PILOT / ("arm_%s.jsonl" % arm)
        bs, meta = batches_of(sample, arm)
        tok[arm] = asyncio.run(ds_batch.run(SYS, bs, meta, p, mode="flash", conc=6,
                                            every=2, thinking="disabled"))
    print("\n═══ 三臂对照（同样 120 条）═══")
    got = {arm: read_out(PILOT / ("arm_%s.jsonl" % arm)) for arm in ARMS}
    for arm in ARMS:
        print("   %s %-26s 答出 %3d/120   token %s"
              % (arm, ARMS[arm], len(got[arm]), format(tok[arm], ",")))
    # 对齐判据（确定性）：回传的键必须都在我发出去的主键里
    ids = {r[0] for r in sample}
    for arm in ARMS:
        stray = [k for k in got[arm] if k not in ids]
        print("   %s 回传了不属于这批的标识号：%d" % (arm, len(stray)))
    txt = {r[0]: (r[1], r[2]) for r in sample}
    outp = PILOT / "compare.txt"
    with outp.open("w", encoding="utf-8") as fh:
        for eid in sorted(ids):
            w, t = txt[eid]
            fh.write("【%s】%s\n" % (w, t))
            for arm in ARMS:
                fh.write("   %s %s\n" % (arm, got[arm].get(eid, "（没答）")))
            fh.write("\n")
    print("\n   三臂逐条对照写在 %s —— 下一步是我自己读，不交给模型判" % outp)
    return 0


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "pilot"):
        ap.add_argument("--" + x, action="store_true")
    ap.add_argument("--arm", default="A")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    if a.pilot:
        return run_pilot(ro)

    rows = scan(ro)
    ro.close()
    print("■ 待翻译例句 %s 条（臂 %s：%s）" % (format(len(rows), ","), a.arm, ARMS[a.arm]))
    if not a.apply:
        print("(未加 --apply，不跑批不写库)")
        return 0
    bs, meta = batches_of(rows, a.arm)
    tok = asyncio.run(ds_batch.run(SYS, bs, meta, OUT, mode="flash", conc=12,
                                   every=20, thinking="disabled"))
    print("■ token %s" % format(tok, ","))
    zh = read_out(OUT)
    ids = {r[0] for r in rows}
    zh = {k: v for k, v in zh.items() if k in ids}      # 只认发出去过的主键
    print("■ 译回 %s / %s 条" % (format(len(zh), ","), format(len(rows), ",")))
    with dbtool.session("translate-examples",
                        expect={"__rows__": 0, "#example_gloss": len(zh)}) as s:
        s.executemany("INSERT INTO example_gloss (example_id,lang,text,src) "
                      "VALUES (?,'zh',?,?)", [(k, v, SRC) for k, v in zh.items()])
    print("■ 已写 %s 条中文" % format(len(zh), ","))
    return 0


if __name__ == "__main__":
    sys.exit(main())
