#!/usr/bin/env python3
"""F1（搜索预计算表陈旧性）这道闸的变异验证。2026-08-20。

═══ 为什么要单独一个文件 ═══
`search_prefix` 是**派生数据**，头号风险不是算错，是「算对了然后 `dict` 变了没人重算」——
那时页面上的搜索下拉给的是旧结果，而查表本身一切正常。
这正是 [[fix-regression-and-gate]] 记的第二种机制（被绕过）。

F1 只比一个指纹（`dict` 的行数与 max(id)），**判据极简 ⇒ 极容易写成恒真**。
「一条永远通过的检查等于没检查」，所以它必须自己也被验一遍。

⚠️ 判据与 `test_no_regression.special()` 里的 F1 **必须是同一段逻辑**。
   这里复制了一份而不是 import —— 因为 `special()` 把它嵌在一个大函数里、
   拆出来要动那个文件。**若改动 F1 判据，两处都要改**；下面的负控会在
   两边不一致时暴露（真实库应当返回 (0,0)）。

用法（在 it/ 目录下）：
    python3 tests/test_search_prefix_gate.py
"""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths   # noqa: E402


def f1(con):
    """→ (写入侧, 读取侧)。0 = 干净。与 test_no_regression 的 F1 同一判据。"""
    try:
        fp = con.execute("SELECT v FROM search_prefix_meta "
                         "WHERE k='dict_fingerprint'").fetchone()
        now = "%d:%d" % con.execute(
            "SELECT COUNT(*), COALESCE(MAX(id),0) FROM dict").fetchone()
        return (0 if fp else 1, 0 if (fp and fp[0] == now) else 1)
    except sqlite3.Error:
        return (1, 1)


CASES = [
    ("【负控】不动，应绿", None, (0, 0)),
    ("往 dict 插一行（陈旧）",
     "INSERT INTO dict(word,word_norm,is_lemma) VALUES('__mut__','__mut__',1)", (0, 1)),
    ("删掉一行 dict（陈旧）",
     "DELETE FROM dict WHERE id=(SELECT MAX(id) FROM dict)", (0, 1)),
    ("改坏指纹（模拟重算漏了）",
     "UPDATE search_prefix_meta SET v='0:0' WHERE k='dict_fingerprint'", (0, 1)),
    ("删掉 meta 表（被谁 DROP 了）", "DROP TABLE search_prefix_meta", (1, 1)),
]


def main():
    td = tempfile.mkdtemp()
    p = Path(td) / "t.sqlite"
    shutil.copy2(paths.DB, p)          # 🔴 在副本上做，正式库一个字节不碰
    bad = 0
    try:
        for name, sql, want in CASES:
            con = sqlite3.connect(p)
            con.execute("SAVEPOINT m")
            if sql:
                con.execute(sql)
            got = f1(con)
            con.execute("ROLLBACK TO m")
            con.execute("RELEASE m")
            con.close()
            ok = got == want
            bad += not ok
            print("   %s %-30s 得到 %s 期望 %s" % ("✅" if ok else "🔴", name, got, want))
    finally:
        shutil.rmtree(td)
    print("\n   %s %d/%d" % ("✅" if not bad else "🔴", len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
