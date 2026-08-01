#!/usr/bin/env python3
"""es 音标约定归一化 —— 落库。2026-08-01。

把 `ipa_norm.normalize()` 的结果写进 `phonetic`，原值留档到 `phonetic_raw`。
这是把「约定归一从展示层搬进数据」的执行脚本，见 docs/FRAMEWORK.md §五之二。

═══ 落库前已完成的验收 ═══
· `test_ipa_norm.py` 20 个金标准用例全绿，期望值取自西语版 dump（不是我推的）；
· 变异验证 8/8：把每条规则的 bug 塞回去，测试都能拦住；
· **全量对照组**：46.7 万个「库内 + 西语版都有」的词，对称归一后与权威值比对——
      改前一致 297,101 (63.62%)  →  改后 302,748 (64.83%)
      修好 5,647，**改坏 0**
  零倒退是本次落库的验收判据。
· 双家评审（豆包 pro + v4-pro，均开思考，并行）：约定选择无异议；
  指出的 `x`→/ks/ 缺口属"少改了"不属"改坏了"，本轮不做；
  指出的 `tl`/`dl` 族**回西语版核实后已采纳**（见 ipa_norm 文件头）。

═══ 三列 ═══
    phonetic       约定值（本次写入）
    phonetic_raw   源值（本次留档，可回滚、可审计）
    phonetic_src   来源（backfill_src.py 已填）

用法（在 es/ 目录）：
  python3 apply_ipa_norm.py            # 预览
  python3 apply_ipa_norm.py --apply    # 写库（dbtool 闸门：备份+不变量+抽样反验）
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse
import sqlite3
from collections import Counter

import dbtool
import ipa_norm as N


def plan():
    conn = sqlite3.connect(f"file:{dbtool.DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT id, word, phonetic FROM dict "
                        "WHERE TRIM(COALESCE(phonetic,''))<>''").fetchall()
    conn.close()
    tal = Counter()
    changes, samples = [], []
    for rid, w, p in rows:
        b = N.basic(N.strip_narrow(p))
        cc = N.spirants_to_stops(b)
        d = N.devoice_coda(w, cc)
        tal["有音标"] += 1
        if b != p:
            tal["记法层"] += 1
        if cc != b:
            tal["擦音→塞音"] += 1
        if d != cc:
            tal["coda清音"] += 1
        if d != p:
            changes.append((d, rid))
            samples.append((w, p, d))
    return len(rows), tal, changes, samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    total, tal, changes, samples = plan()
    print(f"{'情况':16}{'行数':>10}{'占比':>9}")
    for k in ("有音标", "记法层", "擦音→塞音", "coda清音"):
        print(f"  {k:14}{tal[k]:>10,}{100*tal[k]/total:>8.2f}%")
    print(f"  {'合计将改写':14}{len(changes):>10,}{100*len(changes)/total:>8.2f}%")
    dbtool.sample_check(samples, 12, ("词", "改前", "改后"))

    if not a.apply:
        print("\n(预览。确认后 --apply)")
        return

    with dbtool.session("ipanorm",
                        expect={"phonetic": 0,           # 只改内容，覆盖率不动
                                "phonetic_raw": total}) as s:
        # 🔴 顺序：先留档源值，再覆盖 —— 反过来就把源值弄丢了。
        s.execute("UPDATE dict SET phonetic_raw=phonetic "
                  "WHERE TRIM(COALESCE(phonetic,''))<>''")
        s.executemany("UPDATE dict SET phonetic=? WHERE id=?", changes)


if __name__ == "__main__":
    main()
