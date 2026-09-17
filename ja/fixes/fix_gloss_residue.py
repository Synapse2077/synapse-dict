#!/usr/bin/env python3
"""修：释义里两类真残渣。2026-09-16（阶段 7 回归闸首轮报出来的）。

═══ 是回归闸建成当天自己报出来的 ═══
A4 第一版判据「释义里含 `==` 或 `【】` 或汉字等级」报 **71 条**，逐条读之后
**只有 62 条是真的**，另外 385 条是**正当内容**：

    【decilitre】分升。        ← 中文版的正当写法：【英文原词】中文释义
    【megajoule】兆焦尔。

⇒ 判据比它要描述的东西宽。这一轮已经是第 N 次（`[[criteria-narrower-than-you-think]]`）。
   拆成两条各自收窄之后，剩下的才是真残渣：

**① `===Etymology 4======Etymology 5===`（2 条，en-edition）**
   维基章节标记漏进了英文释义。一条整条都是标记，一条标记后面还有真内容
   （`Used as ateji in various…`）⇒ **剥标记、留内容；剥完为空才删**。

**② 整条就是 `【現す、顕す】`（60 条，ja/zh-edition）**
   整条释义只有一个方括号异写列表，**不是释义**。与阶段 3a 处理 `鈹`（汉字存根）
   同一形状：字面看着像内容，其实是结构。
   ⚠️ 里面的异写信息**不丢** —— 关系层的 `alt_of`/`see_also` 已经从 dump 的
      `redirects`/`forms` 收过一遍，这里删的只是"把结构写在释义格里"的那份。

🔴 删 gloss 之后**义项可能变空** —— 连同空掉的义项一起删，
   与阶段 3b 收尾那次（拆编号后剩空串）同一处置。

用法：
    python3 -u ja/fixes/fix_gloss_residue.py
    python3 -u ja/fixes/fix_gloss_residue.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3

import dbtool
import paths
# 🔴 判据只许一份：章节标记的模式**import 生成侧那一份**，不在这儿重写。
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))
from intake_edition_words import SECTION            # noqa: E402
# 🔴 判据是「**整条**就是一个方括号列表」，不是「含有方括号」——
#    后者会咬到 `【decilitre】分升。` 这类正当的中文版释义（385 条）。
ONLY_BRACKET = re.compile(r"^\s*【[^】]*】\s*$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    upd, dele = [], []
    for rid, sid, t in con.execute(
            "SELECT rowid, sense_id, text FROM sense_gloss"):
        if ONLY_BRACKET.match(t or ""):
            dele.append((rid, sid, t))
            continue
        if "==" in (t or ""):
            new = SECTION.sub("", t).strip()
            if new:
                upd.append((new, rid, t))
            else:
                dele.append((rid, sid, t))
    print("■ 剥章节标记留内容 %d 条｜整条删 %d 条" % (len(upd), len(dele)))
    for n, r, o in upd[:4]:
        print("   改：%r → %r" % (o[:44], n[:44]))
    for r, s, t in dele[:4]:
        print("   删：%r" % t[:44])
    # 删完哪些义项会变空
    sids = {s for _r, s, _t in dele}
    empty = [s for s in sids if con.execute(
        "SELECT COUNT(*) FROM sense_gloss WHERE sense_id=?", (s,)).fetchone()[0]
        == sum(1 for _r, x, _t in dele if x == s)]
    con.close()
    print("■ 因此变空的义项 %d 条（一并删）" % len(empty))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        return

    with dbtool.session("ja-fix-gloss-residue", expect={
            "#sense_gloss": -len(dele), "#sense": -len(empty),
            "#sense_src": 0, "__rows__": 0, "#entry": 0, "#example": 0}) as con:
        con.executemany("UPDATE sense_gloss SET text=? WHERE rowid=?",
                        [(n, r) for n, r, _o in upd])
        con.executemany("DELETE FROM sense_gloss WHERE rowid=?",
                        [(r,) for r, _s, _t in dele])
        con.executemany("DELETE FROM sense WHERE id=?", [(s,) for s in empty])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("没有整条只是【异写列表】的释义", sum(
            1 for (t,) in con.execute("SELECT text FROM sense_gloss")
            if ONLY_BRACKET.match(t or "")) == 0),
        ("没有残留的 ==章节== 标记", sum(
            1 for (t,) in con.execute("SELECT text FROM sense_gloss")
            if "==" in (t or "")) == 0),
        ("没有空释义", q("SELECT COUNT(*) FROM sense_gloss WHERE TRIM(text)=''") == 0),
        ("没有一条 gloss 都没有的义项", q(
            "SELECT COUNT(*) FROM sense s WHERE NOT EXISTS("
            "  SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id)") == 0),
        # 🔴 正当的【英文原词】释义**一条都不许被误伤**
        ("中文版的【英文原词】释义还在（>300 条）", sum(
            1 for (t,) in con.execute(
                "SELECT text FROM sense_gloss WHERE text LIKE '%【%'")
            if not ONLY_BRACKET.match(t or "")) > 300),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
