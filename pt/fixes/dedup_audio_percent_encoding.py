#!/usr/bin/env python3
"""同一条录音被当成两条：`file` 没做百分号归一。2026-08-31。

═══ 怎么发现的 ═══
用户看 `banco` 的页面：真人发音三个按钮，其中两个是**同一个人的同一条录音**。

    4617  fr-edition  LL-Q5146_(por)-Santamarcanda-banco
    7743  en-edition  LL-Q5146_%28por%29-Santamarcanda-banco     ← 同一个文件
    4618  fr-edition  LL-Q5146_(por)-Nelson_Ricardo_2500-banco

🔴 **表的设计是对的，坏在值上。** `audio.file` 的注释写着「Commons 文件名 ＝ 录音身份
   （去重靠它，不是 URL）」，`UNIQUE(word, file)` 也在 —— 判据选得没问题。
   但**英文版给的文件名是百分号转义的、法语版是裸括号**，同一条录音落成两个身份，
   约束结构上拦不住。⇒ **约束能不能生效，取决于键有没有归一**，这是判据之外的一层。

规模：`file` 含 `%28/%29` 的 3,571 行；归一后与另一行撞车的 **5,096 行 / 2,543 组**
（全表 12,577 行的 40%）。读者看到的就是同一条录音印两遍。

═══ 处置 ═══
留**最早入库**的那条（`MIN(id)`），删重复行。
⚠️ 与「隐掉」不同，这里是真删 —— 因为 `audio` 是**纯派生表**（`ingest_audio.py`
   扫 dump 重建，不含任何我们自己产生的信息），删了随时能重跑回来
   （`[[prefer-reversible-designs]]`：可逆性来自"能不能重新生成"，不只来自"有没有软删列"）。
⚠️ **归一只用于「是不是同一条录音」这一个判断**，不改 `file` 的值、不动 URL ——
   两种写法的 URL 都能播，改值反而制造新的不一致。

用法（在 pt/ 目录下）：
    python3 fixes/dedup_audio_percent_encoding.py
    python3 fixes/dedup_audio_percent_encoding.py --apply
"""
import argparse
import collections
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


def ident(word, file):
    """录音身份。**判据只在这里**：百分号解码后的 Commons 文件名。"""
    return (word, unquote(file))


def plan(con):
    seen, drop = {}, []
    for i, w, f, src in con.execute(
            "SELECT id, word, file, src FROM audio ORDER BY id"):
        k = ident(w, f)
        if k in seen:
            drop.append((i, w, f, src, seen[k]))
        else:
            seen[k] = i
    return drop


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    drop = plan(con)
    f = lambda n: format(n, ",")
    total = con.execute("SELECT COUNT(*) FROM audio").fetchone()[0]
    print("■ 录音总行 %s，重复 %s 行（留最早入库的那条）" % (f(total), f(len(drop))))
    print("   来源组合：%s" % dict(collections.Counter(x[3] for x in drop).most_common(5)))
    print("\n■ 抽 8 条看：")
    for i, w, fl, src, keep in drop[:8]:
        print("   删 id=%-6d %-14s %-46s [%s]  留 id=%d" % (i, w[:14], fl[:46], src, keep))
    # 不变量：删完之后，任何一个词下不许再有两条同身份录音
    left = {}
    dupleft = 0
    ids = {x[0] for x in drop}
    for i, w, fl in con.execute("SELECT id, word, file FROM audio"):
        if i in ids:
            continue
        k = ident(w, fl)
        if k in left:
            dupleft += 1
        left[k] = i
    print("\n   ✓ 不变量：删完后仍重复的 %d（必须是 0）" % dupleft)
    con.close()
    if dupleft:
        return 1
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("dedup-pt-audio", expect={"#audio": -len(drop)}) as s:
        s.executemany("DELETE FROM audio WHERE id=?", [(i,) for i, *_ in drop])
    print("\n✓ 删 %s 行（`audio` 是派生表，`ingest_audio.py` 随时重跑得回来）" % f(len(drop)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
