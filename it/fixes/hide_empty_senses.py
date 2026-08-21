#!/usr/bin/env python3
"""可见义项却一条非空释义都没有 —— 页面上是个空编号。2026-08-19。

═══ 用户看得到 ═══
    chaperon   ① （空白）      ← 一条释义都没有，只有个编号
               ② …

全库 **3 条**（`chaperon` / `oi!` / `pbsl`）。三条都出自意语版那批
`definizione mancante; se vuoi, aggiungila tu`（源头明写"缺定义，你来补"）——
占位符清掉之后什么都不剩，义项壳子却留在了 `hidden=0`。

═══ 为什么是藏不是删 ═══
`prefer-reversible-designs`：`hidden=1` 随时可翻回来，删行不可逆。
而且这些义项的 `sense_src` 证据行还在 —— 哪天意语版补上了定义，
这一行就能直接接住，不用重新建。

═══ 连带的一件事：藏完之后这几个词形就没有任何可见内容了 ═══
这是**诚实的状态**，不是新缺陷：`hasContentQuery` 会认出来，
`getEntry` 按既有逻辑回落。留一个空编号才是错的。

⚠️ 本脚本**不碰**另外两族看着像但不是的东西：
  · 撇号空壳 254 个（`D’Agostino` 的内容在 `D'Agostino` 上）—— `merge_apostrophe_variants` 有意留的
  · 大小写空壳 10 个（`B` 的内容在 `b` 上）—— `split_case_forms` 有意留的
  判它们"零内容"是**尺子错**：内容在归一后的兄弟行上，一个字节都没丢。

用法（在 it/ 目录下）：
    python3 fixes/hide_empty_senses.py            # 干跑
    python3 fixes/hide_empty_senses.py --apply
    python3 fixes/hide_empty_senses.py --verify
    python3 fixes/hide_empty_senses.py --mutate
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# 🔴 判据里的 `g.text<>''` 不能省：`sense_gloss` 里存在 text 为空串的行
#    （某轮翻译的弃权落成了空串而不是不落行）。只查 EXISTS 会把它当"有释义"。
EMPTY = """
  SELECT s.id, d.word, s.pos FROM sense s JOIN dict d ON d.id = s.word_id
  WHERE COALESCE(s.hidden,0) = 0
    AND NOT EXISTS(SELECT 1 FROM sense_gloss g
                   WHERE g.sense_id = s.id AND g.text IS NOT NULL AND g.text <> '')
  ORDER BY s.id
"""


def scan(con):
    return con.execute(EMPTY).fetchall()


def gate(con):
    left = scan(con)
    ok = len(left) == 0
    print("   %s 可见但零释义的义项 %s（应 0）" % ("✅" if ok else "🔴", f(len(left))))
    for sid, w, pos in left[:5]:
        print("        %-20s sense=%s pos=%s" % (w, sid, pos))
    # 反向：不许把有释义的义项也藏了 —— 本步只该动这 3 条
    over = con.execute(
        "SELECT count(*) FROM sense s WHERE COALESCE(s.hidden,0)=1 "
        "AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id "
        "AND g.text IS NOT NULL AND g.text<>'')").fetchone()[0]
    # 已接受基线：藏起来且**有**释义的义项 —— 那是 `hide_duplicate_senses`（重复中文）
    # 和 `hide_wiktextract_residue`（残渣）的成果，与本步无关，这里只锚住它不变。
    good = over == BASE_HIDDEN_WITH_TEXT
    ok &= good
    print("   %s 已藏且有释义的义项 %s（基线 %s，别的脚本的成果，本步不该动它）"
          % ("✅" if good else "🔴", f(over), f(BASE_HIDDEN_WITH_TEXT)))
    return ok


# 「藏起来但**有**释义」的义项数。这不是本脚本的产物 —— 是 `hide_duplicate_senses`
# （重复中文）、`finish_duplicate_zh`（合并）、`hide_wiktextract_residue`（残渣）的成果。
#
# 🔴 这个数**会随着别的合并脚本跑而变**，那正是它存在的意义：变一次就红一次，
#    逼人去看「是谁又藏了有内容的义项、藏得对不对」。不是"永远不该变"，
#    而是"不许**悄悄**变"。改这个数之前必须先答出增量是谁造成的。
#
#   708 → 719：`finish_duplicate_zh` 合并 11 组重复中文（Gran Carro 的三个英文星座名等），
#              藏掉的那 11 条都有释义 —— 合并本来就是这么做的。核对无误后更新。
BASE_HIDDEN_WITH_TEXT = 719


def mutate():
    cases = [
        ("把一条已藏的空义项放出来",
         "UPDATE sense SET hidden=0 WHERE id=(SELECT s.id FROM sense s WHERE s.hidden=1 "
         "AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id "
         "AND g.text IS NOT NULL AND g.text<>'') LIMIT 1)"),
        ("把一条有释义的义项藏起来",
         "UPDATE sense SET hidden=1 WHERE id=(SELECT s.id FROM sense s "
         "WHERE COALESCE(s.hidden,0)=0 AND EXISTS(SELECT 1 FROM sense_gloss g "
         "WHERE g.sense_id=s.id AND g.text<>'') LIMIT 1)"),
        ("把一条可见义项的释义清成空串（不是删行）",
         "UPDATE sense_gloss SET text='' WHERE sense_id=(SELECT s.id FROM sense s "
         "WHERE COALESCE(s.hidden,0)=0 AND EXISTS(SELECT 1 FROM sense_gloss g "
         "WHERE g.sense_id=s.id AND g.text<>'') LIMIT 1)"),
    ]
    passed = 0
    for name, sql in cases:
        d = Path(tempfile.mkdtemp())
        shutil.copy(paths.DB, d / "m.sqlite")
        con = sqlite3.connect(d / "m.sqlite")
        con.execute(sql)
        con.commit()
        print("\n── 变异：%s" % name)
        red = not gate(con)
        con.close()
        shutil.rmtree(d)
        print("   %s" % ("✅ 闸报红" if red else "🔴 闸没报 —— 这道检查是假的"))
        passed += red
    print("\n■ 变异 %s/%s" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return mutate()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    print("■ 可见但一条非空释义都没有的义项 %s 条" % f(len(rows)))
    for sid, w, pos in rows:
        print("   %-20s sense=%-8s pos=%s" % (w, sid, pos))
    ro.close()
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)" if not a.apply else "\n(没有要改的)")
        return 0
    with dbtool.session("hide-empty-senses", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", [(r[0],) for r in rows])
    print("■ 已藏 %s 条" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
