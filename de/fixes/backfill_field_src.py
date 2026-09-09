#!/usr/bin/env python3
"""收尾单 C7 —— 给德语一等字段补 provenance：**哪些值不是源头给的**。de，2026-09-05。

═══ C7 是什么 ═══
七月用豆包给一等字段补空、**没留来源标记** ⇒ 26,754 个值说不出出处。
⚠️ **「说不清来源」不等于「错」** —— C7 的判据被数据打回过三次，最后靠「两个独立信号
相交」才逮到真的 254 条造出来的比较级（已删，`fixes/drop_bad_comparatives.py`）。
剩下的抽样看**绝大多数是对的**（`sorgen für → gesorgt`、`Kernchemie → -` 有意写无复数）。
⇒ 本步**一个值都不改**，只让每个值说得出自己有没有源头背书。

═══ 事实是可验证的，不是推的 ═══
实测 25,996 条「无背书」**100% 是同一种情况**：

    这个词 kaikki 认识（`entry` 行在、`src=en-edition`），
    但 kaikki **没给这个字段**，而 `dict` 里有值。

「压根没有 entry 行」的**一条都没有**（0 / 25,996）⇒ 所以
**「这个值不是 kaikki 给的」是可验证的事实**，不是从项目史推出来的。

⚠️ 但「是豆包填的」**逐行证明不了** —— 那是项目史（账上记着七月那次补空），不是行级证据。
   ⇒ `[[ipa-provenance-columns]]`：**证明不了就别硬写**。
     本表的约定是：**有行 ＝ 没有源头背书**（可验证），`src` 一律写 `unsourced`
     （＝「无源头背书，逐行来源不可考」），不写 `model:doubao`。

═══ 为什么是新建一张窄表，不是加 11 个列 ═══
`dict` 刚从 33 列降到 26 列（阶段 0 的 `--drop-cols`），再加 11 个 `*_src` 列是往回走。
⚠️ 也**不合并进 `entry`**：`entry` 是 kaikki 的证据层，把模型填的值塞进去会污染它
（`[[two-layer-sense-model]]`：证据层与出版层不能混）。
⚠️ 更**不用「一列逗号拼字段名」** —— `dict.translation` 那个 `\\n` 拼串的教训就在隔壁：
   一个串没有单一来源，最后只能整列退场。

🔴 `gender` / `ipa` **不进本表**：它们的 `gender_src` / `ipa_src` 列早就存在、
   且已由 C1 回填。同一件事两处存储是坏味道，但**判据只写一份** ——
   `unsourced()` 这一个函数同时知道两条路径，闸 import 它。

用法（在 de/ 目录下）：
    python3 -u fixes/backfill_field_src.py
    python3 -u fixes/backfill_field_src.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                            # noqa: E402

f = lambda n: format(n, ",")
SRC = "unsourced"

# `dict` 与 `entry` 都有的德语一等字段，**除去自带 `*_src` 列的那两个**。
# ⚠️ 顺序即输出顺序，改动请连同 `docs/SCHEMA.md` 一起改。
FIELDS = ("genitive", "plural", "aux", "praeteritum", "partizip2", "vclass",
          "separable", "sep_prefix", "reflexive", "comparative", "superlative")

DDL = """CREATE TABLE IF NOT EXISTS field_src (
           word_id INTEGER NOT NULL,      -- → dict.id
           field   TEXT    NOT NULL,      -- dict 的列名，取值域见本文件 FIELDS
           src     TEXT    NOT NULL,      -- 目前恒为 'unsourced'（无源头背书、逐行来源不可考）
           PRIMARY KEY (word_id, field)
         )"""


def unbacked(con, field):
    """→ [word_id]：`dict.<field>` 有值，而**没有任何 entry 行给出这个字段**。

    🔴 **判据只许这一份**，回填与闸都用它。写成 `NOT EXISTS(... AND e.<field> 非空)`，
       不是 `LEFT JOIN ... IS NULL` —— 一个词可以有多条 entry 行（不同词性/词源），
       只要**任何一条**给了这个字段就算有背书。
    """
    return [r[0] for r in con.execute(
        "SELECT d.id FROM dict d "
        " WHERE TRIM(COALESCE(d.%s,''))<>'' "
        "   AND NOT EXISTS(SELECT 1 FROM entry e WHERE e.word_id=d.id "
        "                   AND TRIM(COALESCE(e.%s,''))<>'')" % (field, field))]


def unsourced(con):
    """→ 有值却**说不出来源**的条数。C7 的判据；账的闸与回归闸都 import 这一份。

    两条存储路径都要查（见文件头「为什么 gender/ipa 不进本表」）：
      · `ipa` / `gender`  → 看 `dict.ipa_src` / `dict.gender_src` 填没填（C1 做的）
      · 其余 11 个字段    → 看 `field_src` 里有没有行，或 `entry` 有没有背书
    """
    n = 0
    for col in ("ipa", "gender"):
        n += con.execute(
            "SELECT COUNT(*) FROM dict WHERE TRIM(COALESCE(%s,''))<>'' "
            "  AND TRIM(COALESCE(%s_src,''))=''" % (col, col)).fetchone()[0]
    if not con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                       "AND name='field_src'").fetchone()[0]:
        # 表还没建 ⇒ 这 11 个字段的无背书值全都说不出来源
        return n + sum(len(unbacked(con, c)) for c in FIELDS)
    for c in FIELDS:
        n += con.execute(
            "SELECT COUNT(*) FROM dict d WHERE TRIM(COALESCE(d.%s,''))<>'' "
            "  AND NOT EXISTS(SELECT 1 FROM entry e WHERE e.word_id=d.id "
            "                  AND TRIM(COALESCE(e.%s,''))<>'') "
            "  AND NOT EXISTS(SELECT 1 FROM field_src s WHERE s.word_id=d.id "
            "                  AND s.field=?)" % (c, c), (c,)).fetchone()[0]
    return n


def fingerprint(con):
    """→ 全部一等字段值的指纹（sha256）。**反向闸用**：这一步一个值都不许改。

    🔴 在 Python 里算真校验和，不用 SQL 拼 `MIN/MAX/SUM(LENGTH)` 那种弱指纹 ——
       弱指纹的问题不是慢，是**它可能在数据变了的时候不变**，
       而一条「数据变了也不报」的反向闸等于没有闸。
    ⚠️ 按 `dict.id` 排序后逐行喂，保证与行序无关。
    """
    import hashlib
    h = hashlib.sha256()
    cols = ("ipa", "gender") + FIELDS
    sql = "SELECT id,%s FROM dict ORDER BY id" % ",".join("COALESCE(%s,'')" % c for c in cols)
    for row in con.execute(sql):
        h.update(("\x1f".join(str(x) for x in row) + "\x1e").encode("utf-8"))
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, per = [], {}
    for c in FIELDS:
        ids = unbacked(con, c)
        per[c] = len(ids)
        rows += [(i, c, SRC) for i in ids]
    print("■ 无源头背书的一等字段值 %s 条" % f(len(rows)))
    for c in FIELDS:
        if per[c]:
            print("   %-14s %8s" % (c, f(per[c])))
    print("\n■ 本步之前「说不出来源」的总数：%s" % f(unsourced(con)))
    before = fingerprint(con)
    con.close()

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    import dbtool
    with dbtool.session("keep-v3-c7-field-src", expect={"#field_src": len(rows)}) as s:
        s.execute(DDL)
        s.executemany("INSERT OR REPLACE INTO field_src (word_id,field,src) VALUES (?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    print("\n═══ 闸 ═══")
    checks = [
        ("🔴 有值却说不出来源（C7 的判据）", unsourced(con), 0),
        # 🔴 **反向闸**：本步只写 `field_src`，`dict` 的值一个都不许动。
        #    `[[fix-regression-and-gate]]`：只查「新的对不对」查不出「旧的被动了」。
        ("🔴 一等字段的值被改动了（指纹不一致）",
         0 if fingerprint(con) == before else 1, 0),
        ("🔴 给**有背书**的值也写了行（越界）",
         sum(q("SELECT COUNT(*) FROM field_src s JOIN dict d ON d.id=s.word_id "
               "WHERE s.field=? AND EXISTS(SELECT 1 FROM entry e WHERE e.word_id=d.id "
               "  AND TRIM(COALESCE(e.%s,''))<>'')" % c, c) for c in FIELDS), 0),
        ("🔴 给**空值**写了行",
         sum(q("SELECT COUNT(*) FROM field_src s JOIN dict d ON d.id=s.word_id "
               "WHERE s.field=? AND TRIM(COALESCE(d.%s,''))=''" % c, c) for c in FIELDS), 0),
        ("🔴 field 值域外", q("SELECT COUNT(*) FROM field_src WHERE field NOT IN (%s)"
                            % ",".join("'%s'" % c for c in FIELDS)), 0),
        ("🔴 src 值域外", q("SELECT COUNT(*) FROM field_src WHERE src<>?", SRC), 0),
        ("🔴 孤儿（word_id 不在 dict）",
         q("SELECT COUNT(*) FROM field_src s LEFT JOIN dict d ON d.id=s.word_id "
           "WHERE d.id IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-40s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    con.close()
    print("\n%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
