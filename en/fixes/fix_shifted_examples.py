#!/usr/bin/env python3
"""例句译文**批内错开一位**：找出来、清掉、重翻。2026-09-09（外审照出来的）。

═══ 现场 ═══
外审报「`flutter` 有一条例句译文完全无关」。回源：

    id=825882  little flutters of breeze shook the white hats of the daisies
               → 「学过拉丁语之后，西班牙语简直是小菜一碟。」
    id=825883  After studying Latin, Spanish was a breeze.
               → 「换乘东米德兰铁路只需八分钟，轻松得很…」

**825882 拿到了 825883 的译文，825883 拿到了 825884 的。整批错开一位。**

🔴🔴 `id` 确实发出去也回来了（`slot_translate` 有硬闸守着），
   但**模型在应答里把 id 和内容配错了行** ——
   `[[model-answer-files-key-by-id]]` 说的是「用主键当 key」，
   这次证明**用了主键仍然不够**：主键保证认领得上，不保证配对是对的。

═══ 为什么所有闸都是绿的 ═══
六条落库闸查的是：行数、空串、同句一译、覆盖数、别的来源没被动、id 是真主键。
**每一条都通过了** —— 因为错位不改变任何计数，只把内容挪了一格。
⇒ `[[verification-gates-not-sampling]]`：「别把义项和释义错配了，那才是真灾难」，
  而**计数型的闸对错配是结构性失明的**。

═══ 判据：长度比 ═══
中文长度约为英文的一个固定比例（**从数据算中位数，不写死**）。
若 `zh(X)` 配 `en(X+1)` 的长度比明显更合理，就是错位。
⚠️ 这只逮得到**长度差得开**的那些 ⇒ 按**连片**扩到整批重翻，不只修逮到的那几条。

    cd en && python3 -u fixes/fix_shifted_examples.py
    cd en && python3 -u fixes/fix_shifted_examples.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import json
import math
import shutil
import sqlite3
import statistics

import dbtool
import paths

OUT = paths.WORK / "examples"
ANS = OUT / "zh.jsonl"
MARGIN = 45          # 一批 40 条 ⇒ 往两边各扩一批，保证整批都被重翻
GAP = 1.2


def _lr(en, zh):
    return math.log(max(len(zh), 1) / max(len(en), 1))


def detect(con):
    rows = con.execute(
        "SELECT e.id, e.text, g.text FROM example e "
        "JOIN example_gloss g ON g.example_id=e.id "
        "WHERE e.hidden=0 ORDER BY e.id").fetchall()
    base = statistics.median(_lr(t, z) for _, t, z in rows)
    hit = []
    for k in range(len(rows) - 1):
        i1, t1, z1 = rows[k]
        i2, t2, _ = rows[k + 1]
        if i2 - i1 > 3:
            continue
        if abs(_lr(t1, z1) - base) - abs(_lr(t2, z1) - base) > GAP:
            hit.append(i1)
    ids = {i for i, _, _ in rows}
    redo = set()
    for i in hit:
        redo |= {x for x in range(i - MARGIN, i + MARGIN + 1) if x in ids}
    return hit, redo, base


def drop_answers(ids):
    """从答案文件里划掉 —— **清库不等于清账本**（[[answer-file-is-the-ledger]]）。"""
    if not ids or not ANS.exists():
        return 0
    shutil.copy2(ANS, ANS.with_suffix(".jsonl.bak2"))
    keep, drop = [], []
    for ln in ANS.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            keep.append(ln); continue
        (drop if o.get("id") in ids else keep).append(ln)
    with (OUT / "zh.dropped.jsonl").open("a", encoding="utf-8") as f:
        f.writelines(drop)
    tmp = ANS.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(keep), "utf-8")
    tmp.replace(ANS)
    return len(drop)


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    hit, redo, base = detect(con)
    print("═══ 例句译文错位 ═══")
    print("   判据基准：中文/英文 长度比中位数 %.2f（算出来的，不写死）" % math.exp(base))
    print("   逮到 %s 条明显错位" % format(len(hit), ","))
    print("   ⇒ 按整批扩到 **%s 条**重翻（一批 40，两边各扩 %d）"
          % (format(len(redo), ","), MARGIN))
    print("\n   样本：")
    for i in hit[:3]:
        t, z = con.execute(
            "SELECT e.text, g.text FROM example e JOIN example_gloss g "
            "ON g.example_id=e.id WHERE e.id=?", (i,)).fetchone()
        nxt = con.execute("SELECT text FROM example WHERE id>? AND hidden=0 "
                          "ORDER BY id LIMIT 1", (i,)).fetchone()
        print("      id=%s\n        英   : %s\n        中   : %s\n        下一条: %s"
              % (i, t[:66], z[:66], (nxt[0] if nxt else "")[:66]))
    con.close()
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    with dbtool.session("keep-v3-fix-shifted-examples",
                        expect={"#example_gloss": -len(redo)}) as s:
        s.executemany("DELETE FROM example_gloss WHERE example_id=?",
                      [(i,) for i in sorted(redo)])
    n = drop_answers(redo)
    print("\n■ 已清库 %s 行、从答案文件划掉 %s 行"
          % (format(len(redo), ","), format(n, ",")))
    print("■ 下一步：重翻（**必须缩小批**，不缩小会以同样概率再错一次）+ --apply")
    return 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
