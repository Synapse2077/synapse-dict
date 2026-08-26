#!/usr/bin/env python3
"""量 `pipeline/geo_patterns.py` 那张手写模式表在真实数据上的覆盖。2026-08-22。

之前这个数是我在 bash 里临时跑出来的 —— 每改一条模式就要重敲一遍，
而且**没有留下可复核的记录**。固化成脚本：改模式 → 跑一次 → 数字可比。

量三件事：
  ① 命中率（命中的才走模板，未命中退回模型）
  ② **去重后的槽值有多少个** —— 这才是要送去翻译的量
  ③ 未命中的前 N 族 —— 决定还值不值得再补模式

用法（在 fr/ 目录下）：
    python3 probes/geo_cover.py
    python3 probes/geo_cover.py --miss 20        # 看未命中的前 20 族
    python3 probes/geo_cover.py --dump           # 槽值落盘，供翻译
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                              # noqa: E402
from pipeline.geo_patterns import match, type_zh   # noqa: E402

WORK = paths.WORK / "geo"

# 地名族的判据 —— 与 geo_template.py 同一条，别在两处各写一份
FAM = re.compile(r"^(Commune|Ville|Village|Municipalité|Hameau|Localité|Bourg|Quartier)\b", re.I)


def rows(con):
    return [t for (t,) in con.execute("""
        SELECT g.text FROM sense s
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL""")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--miss", type=int, default=12)
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    all_rows = rows(con)
    fam = [t for t in all_rows if FAM.match(t.strip())]

    hit = 0
    slot = defaultdict(Counter)       # 类型 → 槽值 → 次数
    miss = Counter()
    for t in fam:
        r = match(t)
        if not r:
            miss[" ".join(t.split())[:64]] += 1
            continue
        hit += 1
        for kind, val in r[1]:
            slot[kind][val.strip()] += 1

    print("■ 待翻译 %s 条；其中地名族 %s 条（%.1f%%）"
          % (f"{len(all_rows):,}", f"{len(fam):,}", 100.0 * len(fam) / len(all_rows)))
    print("   ⇒ 手写模式命中 %s（%.1f%%）/ 未命中 %s"
          % (f"{hit:,}", 100.0 * hit / len(fam), f"{len(fam) - hit:,}"))

    # 🔴 断言：TYPE 是闭集（Hameau/Village/Ville/Bourg/Commune…），只该有个位数个不同值。
    #    第一版槽位类型列表与正则组顺序写反了，TYPE 里混进 670 个地名 —— 这条断言是
    #    **唯一**能自动逮到它的地方（命中率、槽值总数都照样"好看"）。
    bad_type = sorted(v for v in slot.get("TYPE", {}) if not type_zh(v))
    if bad_type:
        print("🔴 TYPE 槽出现 %d 个不在闭集里的值（前 10）：%s"
              % (len(bad_type), bad_type[:10]))
    else:
        print("✓ TYPE 槽 %d 个值全部落在闭集内" % len(slot.get("TYPE", {})))

    total_fill = sum(sum(c.values()) for c in slot.values())
    uniq = sum(len(c) for c in slot.values())
    print("\n■ 槽值：去重后 %s 个（共填充 %s 次）" % (f"{uniq:,}", f"{total_fill:,}"))
    for kind in sorted(slot):
        c = slot[kind]
        print("   %-4s %5s 个 / 填充 %8s 次" % (kind, f"{len(c):,}", f"{sum(c.values()):,}"))
    for n in (2, 3, 5):
        keep = {k: v for kd in slot for k, v in slot[kd].items() if v >= n}
        cov = sum(v for kd in slot for k, v in slot[kd].items() if v >= n)
        print("   出现 ≥%d 次的 %5s 个，覆盖填充的 %.1f%%"
              % (n, f"{len(keep):,}", 100.0 * cov / total_fill))

    if a.miss:
        print("\n── 仍未命中的前 %d 族 ──" % a.miss)
        for k, v in miss.most_common(a.miss):
            print("   %6s  %s" % (f"{v:,}", k))

    if a.dump:
        WORK.mkdir(parents=True, exist_ok=True)
        out = [{"kind": kd, "fr": k, "n": v}
               for kd in sorted(slot) for k, v in slot[kd].most_common()]
        (WORK / "slots.jsonl").write_text(
            "\n".join(json.dumps(o, ensure_ascii=False) for o in out), encoding="utf-8")
        print("\n✓ 槽值落盘 %s（%s 行）" % (WORK / "slots.jsonl", f"{len(out):,}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
