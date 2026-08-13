#!/usr/bin/env python3
"""阶段 0 迁移前的形状核对：`definition` / `translation` / `meta` 三边逐行是否对得齐。

═══ 为什么这一步不能省 ═══
迁移把"一行一个义项"拆成表，靠的就是这三者**按行一一对应**。
只要有一行错位，`novia` 那类"义项和释义错配"就会被固化进新表 ——
用户 2026-08-07 的原话：「不要把义项和释义错配了，那才是真灾难」。
`IT_PLAN` 说抽 3,000 词形量到 99.999%，那是**抽样**；迁移前必须**全量**数一遍。

⚠️ 只读，不写库。

跑：  python3 probes/audit_sense_shape.py        （在 it/ 目录下）
"""
import sys
import pathlib
import json
import sqlite3
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import paths


def lines(s):
    """空串与 None 都算 0 行；其余按 \n 拆。**不 strip 整体**——尾部空行是数据事实。"""
    if s is None or s == "":
        return []
    return s.split("\n")


def main():
    c = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cnt = Counter()
    bad_len, bad_meta, empty_line = [], [], []
    meta_keys = Counter()
    meta_pos = Counter()
    trans_line_total = 0

    for rid, word, d, t, m in c.execute(
            "SELECT id, word, definition, translation, meta FROM dict"):
        cnt["行"] += 1
        dl, tl = lines(d), lines(t)
        if not dl:
            cnt["无 definition（变形层）"] += 1
            # 变形行的 translation 应该是单行指针文本
            if len(tl) > 1:
                cnt["🔴 变形行的 translation 多于一行"] += 1
            continue
        cnt["有 definition"] += 1
        cnt["definition 行数合计"] += len(dl)
        trans_line_total += len(tl)
        if len(dl) != len(tl):
            bad_len.append((rid, word, len(dl), len(tl)))
        if any(x.strip() == "" for x in dl):
            empty_line.append((rid, word))
        if m:
            try:
                arr = json.loads(m)
            except Exception:
                cnt["🔴 meta 不是合法 JSON"] += 1
                continue
            if not isinstance(arr, list):
                cnt["🔴 meta 不是数组"] += 1
                continue
            cnt["meta 元素合计"] += len(arr)
            if len(arr) != len(dl):
                bad_meta.append((rid, word, len(dl), len(arr)))
            for o in arr:
                if isinstance(o, dict):
                    for k in o:
                        meta_keys[k] += 1
                    if o.get("pos"):
                        meta_pos[o["pos"]] += 1
        else:
            cnt["有 definition 但无 meta"] += 1
    c.close()

    print("■ 总体")
    for k, v in cnt.items():
        print("   %-28s %10s" % (k, f"{v:,}"))
    print("   %-28s %10s" % ("translation 行数合计（有释义行）", f"{trans_line_total:,}"))

    print("\n■ 🔴 definition ↔ translation 行数不等：%d 条" % len(bad_len))
    for r in bad_len[:20]:
        print("   id=%-8s %-24s def %d 行 / trans %d 行" % r)

    print("\n■ 🔴 definition ↔ meta 元素数不等：%d 条" % len(bad_meta))
    for r in bad_meta[:20]:
        print("   id=%-8s %-24s def %d 行 / meta %d 个" % r)

    print("\n■ definition 里有空行的词条：%d 条" % len(empty_line))
    for r in empty_line[:10]:
        print("   id=%-8s %s" % r)

    print("\n■ meta 的键（出现次数）")
    for k, v in meta_keys.most_common():
        print("   %-14s %10s" % (k, f"{v:,}"))
    print("\n■ meta.pos 取值")
    for k, v in meta_pos.most_common(15):
        print("   %-14s %10s" % (k, f"{v:,}"))


if __name__ == "__main__":
    main()
