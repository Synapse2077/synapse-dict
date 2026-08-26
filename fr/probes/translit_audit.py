#!/usr/bin/env python3
"""拿 GB/T 17693.2 标准译写去核**全部**模型音译。2026-08-24。

此前市镇名音译的"验收"是：26,470 个里我看了约 80 个（**0.3%**）。
用户问「中法地名翻译应该是有规则的吧」—— 有：
**GB/T 17693.2-1999《外语地名汉字译写导则·法语》**（民政部地名研究所）。
`pipeline/fr_translit.py` 按它实现了确定性译写。

⇒ 抽样变成**全量比对**：
   · 标准与模型**一致** ⇒ 两个独立来源互证，可信
   · **不一致** ⇒ 进人工裁决队列。**不自动改**，因为标准自己写明
     「只适用于尚未被《世界地名译名词典》收录的地名」——
     `Paris`→巴黎、`Marseille`→马赛 这类约定译名**压过表**，机械套表反而错。
   · 标准**拆不出** ⇒ 只能留给抽样

跑：python3 probes/translit_audit.py            （在 fr/ 目录下）
    python3 probes/translit_audit.py --diff 40  # 看不一致的样本
"""
import argparse
import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                                  # noqa: E402
from pipeline.fr_translit import translit     # noqa: E402

PLACE = paths.WORK / "geo" / "place_zh.jsonl"


def rows():
    out = []
    for ln in io.open(PLACE, encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("zh"):
            out.append(o)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", type=int, default=25)
    ap.add_argument("--dump", action="store_true", help="不一致的落盘，供裁决")
    a = ap.parse_args()

    rs = rows()
    same, diff, none = [], [], []
    for o in rs:
        std = translit(o["fr"])
        if std is None:
            none.append(o)
        elif std == o["zh"]:
            same.append(o)
        else:
            diff.append((o, std))

    n = len(rs)
    print("■ 模型给出的市镇名音译 %s 个" % format(n, ","))
    print("   与标准**一致**      %7s（%.1f%%）  ⇐ 两个独立来源互证"
          % (format(len(same), ","), 100.0 * len(same) / n))
    print("   与标准**不一致**    %7s（%.1f%%）  ⇐ 进裁决队列"
          % (format(len(diff), ","), 100.0 * len(diff) / n))
    print("   标准**拆不出**      %7s（%.1f%%）  ⇐ 只能抽样"
          % (format(len(none), ","), 100.0 * len(none) / n))

    # 按「首字不同 / 仅末字不同 / 长度不同」粗分，帮我判断分歧的性质
    kind = Counter()
    for o, std in diff:
        z = o["zh"]
        if len(z) != len(std):
            kind["长度不同"] += 1
        elif z[0] != std[0]:
            kind["首字不同"] += 1
        elif z[-1] != std[-1]:
            kind["仅末字不同"] += 1
        else:
            kind["中间字不同"] += 1
    print("\n── 分歧性质 ──")
    for k, v in kind.most_common():
        print("   %-10s %s（%.1f%%）" % (k, format(v, ","), 100.0 * v / max(len(diff), 1)))

    print("\n── 不一致样本（按出现次数降序，影响面大的在前）──")
    print("%-30s %-16s %-16s %s" % ("法语", "模型给的", "标准给的", "出现次数"))
    print("-" * 78)
    for o, std in sorted(diff, key=lambda x: -x[0]["n"])[:a.diff]:
        print("%-30s %-16s %-16s %d" % (o["fr"][:30], o["zh"][:16], std[:16], o["n"]))

    if a.dump:
        p = paths.WORK / "geo" / "translit_diff.jsonl"
        p.write_text("\n".join(json.dumps(
            {"fr": o["fr"], "model": o["zh"], "std": std, "n": o["n"]}, ensure_ascii=False)
            for o, std in sorted(diff, key=lambda x: -x[0]["n"])), encoding="utf-8")
        print("\n✓ 不一致落盘 %s（%s 行）" % (p, format(len(diff), ",")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
