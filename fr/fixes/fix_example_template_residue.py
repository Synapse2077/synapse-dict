#!/usr/bin/env python3
"""fr 例句里的 wikitext 模板残渣：2 条。2026-11-23。

═══ 为什么现在才现形 ═══
fr 契约闸一直有「页面上不许出现模板/脚注残渣」。它之前没红，是因为义项级例句
**恒定 `slice(0, 3)`**（2026-11-23 之前），而这 2 条挂在词条级、又不在闸的取样词里。
2026-11-23 把例句改成分页展开（`expandAll()` 下渲染全部）后，闸第一次看到全部例句，
当场报 `roi` 的 `}}` 与 `liaison` 的 `{{`。

═══ 修复规则 ═══
不是改字，是**展开模板**：去掉模板外壳，保留参数里的引文。
  `{[eg}} le client est roi - ο πελάτης είναι βασιλιάς`
      → `le client est roi - ο πελάτης είναι βασιλιάς`（`{[eg}}` 是坏掉的模板头）
  `{{exemple | lang=fr | Un vaisseau a de bonnes liaisons ou ses liaisons sont faibles.}`
      → `Un vaisseau a de bonnes liaisons ou ses liaisons sont faibles.`
两条的恢复目标都能唯一确定；写前逐条核对当前值，值不符就拒绝写库。

⚠️ 这是十门同类残渣里**已经让闸变红的两条**，不等于全库只有两条：
只读扫描（2026-11-23）en 10／it 1／fr 18／pt 3／ja 1／ko 2／vi 10／ru 7。
其余登记在 `docs/BACKLOG.md` B35，逐条裁决，不在这里盲改。

用法（在 fr/ 目录下）：
    python3 -u fixes/fix_example_template_residue.py           # 只核对 + 打样
    python3 -u fixes/fix_example_template_residue.py --apply   # 落库
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool  # noqa: E402

FIXES = {
    2212840: ("{[eg}} le client est roi - ο πελάτης είναι βασιλιάς",
              "le client est roi - ο πελάτης είναι βασιλιάς"),
    1562711: ("{{exemple | lang=fr | Un vaisseau a de bonnes liaisons ou ses liaisons sont faibles.}",
              "Un vaisseau a de bonnes liaisons ou ses liaisons sont faibles."),
}


def check() -> None:
    """写前核对：当前值必须逐字等于脚本里记的旧值，否则拒绝。"""
    c = sqlite3.connect(f"file:{dbtool.DB}?mode=ro", uri=True)
    try:
        for i, (old, _) in FIXES.items():
            got = c.execute("SELECT text FROM example WHERE id=?", (i,)).fetchone()
            if not got or got[0] != old:
                raise SystemExit(f"🔴 id={i} 当前值不是预期的旧值，拒绝写库：{got!r}")
    finally:
        c.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    check()
    for i, (old, new) in FIXES.items():
        print(f"  {i}: {old!r}\n    → {new!r}")
    if not args.apply:
        print("(dry：核对通过，未写库)")
        return
    with dbtool.session("b35-fr-example-template-residue", small=len(FIXES)) as s:
        for i, (old, new) in FIXES.items():
            s.execute("UPDATE example SET text=? WHERE id=? AND text=?", (new, i, old))
    print(f"✓ 已写 {len(FIXES)} 行")


if __name__ == "__main__":
    main()
