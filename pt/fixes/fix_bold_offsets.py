#!/usr/bin/env python3
"""阶段 5c 清洗：`example.bold` 里指向别的字符串的 29 组坐标。2026-08-30。

判据 **import 自 `ingest_examples.clean_bold`** —— 不在这里再抄一份。
`[[fix-regression-and-gate]]`：闸与它守的那段逻辑用两个判据 ⇒ 闸在报自己的 bug。

用法（在 pt/ 目录下）：
    python3 fixes/fix_bold_offsets.py
    python3 fixes/fix_bold_offsets.py --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from ingest_examples import clean_bold   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = [(i, w, t, b) for i, w, t, b in con.execute(
        "SELECT id, word, text, bold FROM example WHERE bold IS NOT NULL")
        if clean_bold(t, json.loads(b)) is None]
    con.close()
    print("■ 坐标不属于这段文本的：%d 条" % len(todo))
    for i, w, t, b in todo[:10]:
        print("   id=%-6d %-16s len=%-4d 坐标=%s" % (i, w[:16], len(t), b))
    if not todo or not a.apply:
        print("\n(未加 --apply，不写库)" if todo else "\n✓ 没有要改的")
        return 0
    with dbtool.session("fix-pt-bold-offsets", expect={"#example": 0}) as s:
        s.executemany("UPDATE example SET bold=NULL WHERE id=?", [(i,) for i, *_ in todo])
    print("✓ 已置空 %d 条（文本一个字节没动）" % len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
