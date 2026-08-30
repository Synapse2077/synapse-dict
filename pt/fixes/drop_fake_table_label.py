#!/usr/bin/env python3
"""阶段 2c 前置清洗：`metaphonic` —— 英文表格标签混进 dict 当葡语词形。2026-08-30。

═══ 缺陷 ═══
`dict` id=738731 `metaphonic` (pos='n')。它是**英文**，是英文版葡语名词变位表里
标注「元音变换复数」（metaphonic plural）的**表头文字**，被阶段 3 当成词形收了进来。

判定证据（全部确定性，非抽样）：
  · 四个 dump 全扫，`metaphonic` **作为葡语词头出现 0 次**
  · 库里零引用：entry 0 / inflection 0 / pronunciation 0
  · 阶段 2c 的候选集里它被 **571 个不同词元**当成变形 —— 表格标签的典型形状
    （真变形不会同时属于 571 个词元）

⚠️ 同批查过、**确认是真葡语词不许动**的同形词：
   `plural` / `singular` —— 葡语里同形同义，`is_lemma=1`，与英文标签撞脸而已。
   这正是判据必须逐条回源的理由（`[[criteria-narrower-than-you-think]]`）。

═══ 为什么用点名删、不写通用规则 ═══
扫过全部候选：「被 >8 个词元共用、且库里没有 entry」的词形**只有这一个**。
为一条数据写一条形状规则（"看起来像英文就删"）风险远大于收益 ——
`PITFALLS` C3「判据比它要描述的东西更宽」的头号形状。
⇒ 点名删，把判据写成"这一条为什么是假的"，不写成"这一类长什么样"。

🔴 **这是阶段 3 的漏网，记在收尾单里** —— `PITFALLS` B1.5 那一族的残留。

用法（在 pt/ 目录下）：
    python3 fixes/drop_fake_table_label.py
    python3 fixes/drop_fake_table_label.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

FAKE = "metaphonic"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    row = con.execute("SELECT id, word, pos, is_lemma FROM dict WHERE word=?", (FAKE,)).fetchone()
    if not row:
        print("✓ %r 不在库里，没有要做的" % FAKE)
        return 0
    wid = row[0]
    refs = {t: con.execute("SELECT COUNT(*) FROM %s WHERE word_id=?" % t, (wid,)).fetchone()[0]
            for t in ("entry", "inflection", "pronunciation")}
    con.close()
    print("■ 要删：dict id=%d word=%r pos=%r is_lemma=%d" % row)
    for t, n in refs.items():
        print("   %-14s 引用 %d 次" % (t, n))
    if any(refs.values()):
        print("🔴 有引用，**不删** —— 先查清引用是什么")
        return 1
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("keep-v3-2c-drop-fake", expect={"__rows__": -1, "pos": -1}) as s:
        s.execute("DELETE FROM dict WHERE id=?", (wid,))
    print("✓ 已删")
    return 0


if __name__ == "__main__":
    sys.exit(main())
