#!/usr/bin/env python3
"""中文出版正文（简体）同步 —— R29，2026-10-25。

    python3 -u ru/pipeline/zh_pub.py            # 干跑：数要改多少、抽样印出来
    python3 -u ru/pipeline/zh_pub.py --apply    # 写库（走 dbtool 闸门）

做两件事，**都是幂等的**（再跑一遍 0 改动）：

① **6d 模型例句的 `text` 回到模型原话。** 6d 回收时 `normalize_zh` 整段 `OpenCC t2s`，在本来就是
   简体的译文上改错了（`头发覆上→复上`、`“乾”→“干”`、`薹草→苔草`、`麻鳽→麻𫛚`）。
   答案文件是账本（`[[answer-file-is-the-ledger]]`）⇒ 按例句 id 从答案文件重算 `normalize_zh`（已不转繁简）。
   🔴 **只改「库里的值 ＝ 旧算法(答案)」的行** —— 先证明这行确实是从这份答案算出来的，再改；
      证明不了的一行都不动、大声报出来。
② **三张表的 `text_pub`**（`lang='zh'` 的行）＝ `criteria.zh_simp(text, src)`，与 `text` 相同存 NULL。
   词源层的 zh 版走它自己的收割器（`etymology_text_pub(text, src)`），不在这里。
"""
import argparse
import collections
import json
import random
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline import translate_examples as TX                   # noqa: E402

F = lambda n: format(n, ",")                                    # noqa: E731
TABLES = ("sense_gloss", "example_gloss", "sense_src")
ANSWER_TAGS = ("redo", "all", "slice0.01")      # 与 6d `load` 同一个优先级（redo 先认领）


def _old_normalize(t, src_lines):
    """6d 落库时用的那版（整段 t2s）—— 只用来**证明**库里的值是从答案算出来的。"""
    out = "\n".join(l.rstrip() for l in (t or "").strip().split("\n"))
    out = criteria._t2s()(out)
    if src_lines == 1 and "\n" in out:
        out = "".join(l.strip() for l in out.split("\n"))
    return out


def answers():
    got = {}
    for tag in ANSWER_TAGS:
        p = TX.OUT / ("%s.jsonl" % tag)
        for line in p.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:                    # noqa: BLE001
                continue
            if isinstance(d.get("id"), int) and d["id"] not in got and d.get("zh"):
                got[d["id"]] = d["zh"]
    return got


def plan_model_text(con):
    """→ (updates[(新 text, gloss.id)], 统计)。"""
    got = answers()
    up, st = [], collections.Counter()
    for gid, eid, text, esrc, etext, epub in con.execute(
            "SELECT g.id, g.example_id, g.text, e.src, e.text, e.text_pub FROM example_gloss g "
            "JOIN example e ON e.id = g.example_id WHERE g.src = ? AND g.lang = 'zh'", (TX.SRC_MODEL,)):
        a = got.get(eid)
        if a is None:
            st["🔴 答案文件里没有这条"] += 1
            continue
        new, nl = TX.model_zh_text(esrc, etext, epub, a)
        if new == text:
            st["已是该落库的模型中文"] += 1
        elif TX.normalize_zh(a, nl) == text:     # 先判这支：答案本是简体时两种旧算法给出同一个值
            st["R24：去掉出处那一行的译文（出处已搬进 ref）"] += 1
            up.append((new, gid))
        elif _old_normalize(a, nl) == text:
            st["改回模型原话（撤销整段 t2s）"] += 1
            up.append((new, gid))
        else:
            st["🔴 库里的值不是从这份答案算出来的"] += 1
    return up, st


def plan_text_pub(con, model_text=None):
    """→ {表: [(text_pub, id)]}、统计。model_text：①要改的 {gloss.id: 新 text}（干跑时据它算）。"""
    model_text = model_text or {}
    plan, st = {}, collections.Counter()
    for tbl in TABLES:
        up = []
        for rid, text, src, pub in con.execute(
                "SELECT id, text, src, text_pub FROM %s WHERE lang = 'zh'" % tbl):
            if tbl == "example_gloss" and rid in model_text:
                text = model_text[rid]
            s = criteria.zh_simp(text, src)
            want = s if s != text else None
            if want != pub:
                up.append((want, rid))
                st["%s：%s" % (tbl, "填简体" if want else "清空")] += 1
            if want:
                st["%s 有简体出版正文" % tbl] += 1
        plan[tbl] = up
    return plan, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ R29 中文出版正文  判据 %s" % criteria.RULE_VER, flush=True)
    up1, st1 = plan_model_text(con)
    print("\n① 6d 模型例句 `text`")
    for k, v in sorted(st1.items()):
        print("   %-34s %8s" % (k, F(v)))
    if any(k.startswith("🔴") and v for k, v in st1.items()):
        raise SystemExit("🔴 有行证明不了是从答案算出来的 —— 一行都不写")
    plan, st2 = plan_text_pub(con, {gid: t for t, gid in up1})
    print("\n② `text_pub`")
    for k, v in sorted(st2.items()):
        print("   %-34s %8s" % (k, F(v)))
    random.seed(7)
    for tbl in TABLES:
        ids = [rid for p, rid in plan[tbl] if p]
        for rid in random.sample(ids, min(4, len(ids))):
            t, p = con.execute("SELECT text, src FROM %s WHERE id=?" % tbl, (rid,)).fetchone()
            print("   %-13s %s\n   %13s → %s" % (tbl, t[:50].replace("\n", "⏎"), "",
                                                criteria.zh_simp(t, p)[:50].replace("\n", "⏎")))
    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return
    have = {tbl: con.execute("SELECT COUNT(*) FROM %s WHERE text_pub IS NOT NULL AND TRIM(text_pub)<>''"
                             % tbl).fetchone()[0] for tbl in TABLES}
    con.close()
    exp = {"%s.text_pub" % tbl: st2.get("%s 有简体出版正文" % tbl, 0) - have[tbl] for tbl in TABLES}
    import dbtool
    with dbtool.session("zh-pub-r29", expect=exp, invalidates=[]) as s:
        s.executemany("UPDATE example_gloss SET text = ? WHERE id = ?", up1)
        for tbl in TABLES:
            s.executemany("UPDATE %s SET text_pub = ? WHERE id = ?" % tbl, plan[tbl])


if __name__ == "__main__":
    main()
