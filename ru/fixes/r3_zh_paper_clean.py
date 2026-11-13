#!/usr/bin/env python3
"""R3：zh 版释义里抄进来的整条俄汉纸质词典 → 洗成释义。ru，2026-11-07。**不花钱。**

判据全在 `criteria` ⑩b（`zh_paper_clean`／`zh_publish_text`／`sense_hidden_why`），本文件一条都不写。
收割器 `sense_layer.py` 已改成调同一组函数 ⇒ 以后重建义项层不会把这次洗的冲掉。

只动两处出版层，证据层（`sense_src.text`）一个字不动：
  · `sense_gloss.text`（zh 版那一行）＝ `zh_publish_text(证据原文, src)`
  · `sense.hidden／hidden_why` ＝ `sense_hidden_why('zh', 证据原文, src)`
`text_pub`（简体出版正文）之后由 `ru/pipeline/zh_pub.py --apply` 同步（E15 的不动点）。

跑（在仓库根）：
    python3 -u ru/fixes/r3_zh_paper_clean.py              # 干跑：分布 ＋ 翻转明细存档
    python3 -u ru/fixes/r3_zh_paper_clean.py --apply
    python3 -u ru/pipeline/zh_pub.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths
from pipeline import criteria

F = lambda n: format(n, ",")                                      # noqa: E731
ARCHIVE = paths.WORK / "r3_zh_paper_clean_plan.json"


def plan(con):
    """→ (gloss 改写 [(新文本, gloss.id)], 藏不藏改写 [(hidden, why, sense.id)], 统计, 明细)。
    回归闸 import 它数「还剩几条没同步」（应为 0）。"""
    g_upd, s_upd = [], []
    st = collections.Counter()
    flips = collections.defaultdict(list)
    for gid, sid, h, why, gtext, src, raw, word in con.execute(
            "SELECT g.id, s.id, s.hidden, s.hidden_why, g.text, g.src, x.text, d.word "
            "FROM sense_gloss g JOIN sense s ON s.id = g.sense_id "
            "JOIN sense_src x ON x.sense_id = s.id JOIN dict d ON d.id = s.word_id "
            "WHERE g.lang = 'zh' AND g.src IN ('zh-edition-simp', 'zh-edition-trad')"):
        new_t = criteria.zh_publish_text(raw, src)
        new_w = criteria.sense_hidden_why("zh", raw, src)
        new_h = 1 if new_w else 0
        if new_t != gtext:
            g_upd.append((new_t, gid))
            st["文本改了·" + src] += 1
        if (new_h, new_w) != (h, why):
            s_upd.append((new_h, new_w, sid))
            k = "%s → %s" % ("印" if not h else why, "印" if not new_h else new_w)
            st["藏不藏改了"] += 1
            flips[k].append((word, raw[:200], new_t[:120]))
    return g_upd, s_upd, st, flips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    g_upd, s_upd, st, flips = plan(con)
    print("■ 判据 %s" % criteria.RULE_VER)
    for k in sorted(st):
        print("   %-28s %8s" % (k, F(st[k])))
    print("■ 藏不藏的翻转（旧 → 新）：")
    for k in sorted(flips, key=lambda k: -len(flips[k])):
        print("   %6s  %s" % (F(len(flips[k])), k))
    # 🔴 新藏的义项上不许挂着模型中文（E14：钱不能花在不出版的行上）
    newly_hidden = [sid for h, _w, sid in s_upd if h == 1]
    paid = 0
    for i in range(0, len(newly_hidden), 900):
        chunk = newly_hidden[i:i + 900]
        paid += con.execute("SELECT COUNT(*) FROM sense_gloss WHERE src LIKE 'model:%%' AND sense_id IN (%s)"
                            % ",".join("?" * len(chunk)), chunk).fetchone()[0]
    con.close()
    print("■ 新藏的义项上挂着的模型中文：%d" % paid)
    ARCHIVE.write_text(json.dumps({"rule_ver": criteria.RULE_VER, "stats": dict(st),
                                   "flips": {k: v for k, v in flips.items()}},
                                  ensure_ascii=False, indent=1), "utf-8")
    print("■ 翻转明细存档 %s" % ARCHIVE)
    if paid:
        print("🔴 有付费数据挂在要藏的义项上 —— 先查清再写")
        return 1
    if not a.apply:
        print("(未加 --apply，未写库)")
        return 0
    n_hid = sum(1 for h, _w, _s in s_upd if h == 1) - sum(1 for h, _w, _s in s_upd if h == 0)
    with dbtool.session("r3-zh-paper-clean", expect={"sense.hidden_why": n_hid}, invalidates=[]) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE id=?", g_upd)
        s.executemany("UPDATE sense SET hidden=?, hidden_why=? WHERE id=?", s_upd)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = plan(con)
    con.close()
    if left[0] or left[1]:
        print("🔴 写后重算还剩 %d／%d 行不一致" % (len(left[0]), len(left[1])))
        return 1
    print("✓ 写完，重算一致。下一步：python3 -u ru/pipeline/zh_pub.py --apply")
    return 0


if __name__ == "__main__":
    _sys.exit(main())
