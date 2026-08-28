#!/usr/bin/env python3
"""收尾单 A4 的一部分 — `regional`/`dialectal` 从**地区**桶挪进**语域**桶。2026-08-28。

═══ 起因 ═══
族 C 收标签时我把法文版的 `Régional` / `Régionalisme` 放进了 `FR_TAG_REGION`，
于是义项旁边渲染出「地区：地区性」—— **那不是一个地区，是一句用法说明**。
`REGISTER_LABELS` 里本来就有 `regional→地区性` / `dialectal→方言`。

    region/regional    968 行
    region/dialectal    51 行

🔴 **写入侧的分桶表和已落库的行必须一起改**，否则下一轮 ingest 又灌回来
（`[[replay-scripts-undo-fixes]]`：修复只做在一层、后一步从另一层重灌）。
分桶表已改：`packages/dict-labels/src/fr.ts` 的 `Régional`/`Régionalisme`
从 `FR_TAG_REGION` 移到 `FR_TAG_REGISTER`。本脚本改库里已有的行。

⚠️ **不是重算覆盖**：只把这两个值的 `kind` 从 `region` 改成 `register`，
   值本身不动、别的值一个不碰。

用法（在 fr/ 目录下）：
    python3 -u fixes/rebucket_region_tags.py            # 只报数
    python3 -u fixes/rebucket_region_tags.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from ingest_fr_tags import table                 # noqa: E402

f = lambda n: format(n, ",")
MOVE = ("regional", "dialectal")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = "SELECT sense_id, value FROM sense_tag WHERE kind='region' AND value IN (?,?)"
    rows = con.execute(q, MOVE).fetchall()
    print("■ 要从 region 挪到 register 的 %s 行" % f(len(rows)))
    for v in MOVE:
        print("   %-12s %s" % (v, f(sum(1 for _s, x in rows if x == v))))

    print("\n═══ 闸 ═══")
    ok = True

    def g(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-50s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))

    reg = table("common.ts", "REGISTER_LABELS")
    g("① 挪过去必须映射得出中文", sum(1 for v in MOVE if v not in reg), 0)
    # 挪过去会不会与已有的 register 行撞主键
    have = {(s, v) for s, v in con.execute(
        "SELECT sense_id, value FROM sense_tag WHERE kind='register'")}
    dup = sum(1 for s, v in rows if (s, v) in have)
    g("② 不与已有的 register 行重复（撞 PRIMARY KEY）", dup, 0)
    tag_reg = table("fr.ts", "FR_TAG_REGION")
    g("③ 写入侧分桶表已经改过（REGION 桶里不许再有它们）",
      sum(1 for v in tag_reg.values() if v in MOVE), 0)
    tag_rg = table("fr.ts", "FR_TAG_REGISTER")
    g("④ 写入侧 REGISTER 桶里已经有它们（否则下轮 ingest 会漏收）",
      0 if any(v in MOVE for v in tag_rg.values()) else 1, 0)

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-rebucket-region", expect={}) as s:
        s.execute("UPDATE sense_tag SET kind='register' WHERE kind='region' "
                  "AND value IN ('regional','dialectal')")
    print("✓ 已挪 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
