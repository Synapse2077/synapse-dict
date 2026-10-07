#!/usr/bin/env python3
"""阶段 -1 探测③：**中文版白送的中文，有多少是真释义**。2026-10-07。只读可重跑。

这是决定**要花多少钱**的那个数：zh 版给的中文释义里，真释义的那一部分不用买。

═══ 🔴🔴 ko 的 K24 是这个位置上最贵的一跤 ═══
账上写着「白送中文释义 **206,091** 条」，9 月 24 日量到底：**97.2% 是元描述**，
中文覆盖率 74% → **2.11%**，19.5 万词形一条真释义都没有，而空白页闸报 6。
而**我量它的时候第一版判据又太宽**（自写「不全是汉字就算真释义」，zh 版报
173,887 条而真值是 **6**）⇒ 从此定下「判据一律 import 不重写」。

⇒ 本脚本**不写判据**，只 `from pipeline import criteria` 取用，并且
  **每一桶都抽样打印给人读** —— 形状检查看不见的那一类只有人眼逮得到
  （vi 的教训：抽样反验逮到 5,390 段内嵌 `__NOEDITSECTION__`）。

🔴 **本脚本的输出不是结论**：三桶的比例 + 人读的抽样一起，才够下结论。
   判据的推翻条件写在 `criteria.zh_gloss_kind` 的注释里（真释义桶污染 > 5% 即作废重写）。

用法：
    python3 ru/probes/probe_zh_gloss.py [--limit N] [--sample 40] [--archive]
"""
import argparse
import collections
import gzip
import io
import json
import random
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402

SRC = [("zh-s", paths.ZH_SIMP), ("zh-t", paths.ZH_TRAD)]


def rd(p, limit=None):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                return
            yield json.loads(line)


def pct(a, b):
    return "%6.2f%%" % (100.0 * a / b) if b else "     —"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample", type=int, default=25)
    ap.add_argument("--archive", action="store_true")
    a = ap.parse_args()
    limit = a.limit or None

    acc = {}
    for name, p in SRC:
        d = {"kind": collections.Counter(), "bucket": collections.defaultdict(list),
             "words": collections.defaultdict(set), "glosses": 0}
        for e in rd(p, limit):
            w = e.get("word") or ""
            for s in e.get("senses") or []:
                for g in s.get("glosses") or []:
                    d["glosses"] += 1
                    k = criteria.zh_gloss_kind(g)
                    d["kind"][k] += 1
                    d["words"][k].add(w)
                    if len(d["bucket"][k]) < 600:
                        d["bucket"][k].append((w, e.get("pos"), g))
        acc[name] = d
        print("  · %-5s %s 条释义" % (name, "{:,}".format(d["glosses"])), file=sys.stderr)

    # 两片的并集口径：一个词形只要在任一片里有 real/mixed，就算「白送到了」
    union = collections.defaultdict(set)
    for name, _ in SRC:
        for k, ws in acc[name]["words"].items():
            union[k] |= ws

    buf = io.StringIO()
    with redirect_stdout(buf):
        print("■ 俄语阶段 -1 探测③：中文版白送的中文有多少是真释义  2026-10-07"
              + ("（--limit %d）" % a.limit if a.limit else "（全量）"))
        print("  判据：`pipeline/criteria.zh_gloss_kind`（版本 %s）—— **本脚本不重写判据**"
              % criteria.RULE_VER)

        print("\n" + "═" * 78)
        print("§ 1 三桶的比例（**按释义条数**）")
        print("═" * 78)
        print("  %-6s%12s%16s%16s%16s" % ("源", "释义总数", "real 真释义", "mixed 混合", "meta 元描述"))
        print("  " + "-" * 66)
        for name, _ in SRC:
            d = acc[name]
            n = max(d["glosses"], 1)
            print("  %-6s%12s%9s %s%9s %s%9s %s" % (
                name, "{:,}".format(d["glosses"]),
                "{:,}".format(d["kind"]["real"]), pct(d["kind"]["real"], n),
                "{:,}".format(d["kind"]["mixed"]), pct(d["kind"]["mixed"], n),
                "{:,}".format(d["kind"]["meta"]), pct(d["kind"]["meta"], n)))

        print("\n" + "═" * 78)
        print("§ 2 **按词形**的并集 —— 这才是「多少个词白送到了中文」")
        print("═" * 78)
        print("  🔴 条数口径和词形口径是**两件事**（`[[measure-landing-not-source]]`：")
        print("     同一件事量出三个数，多半是量了三件事）。花钱按**可出版义项数**算，")
        print("     而「这个词有没有中文」按词形算 —— 两个数都要，别混用。")
        tot = set()
        for k in union:
            tot |= union[k]
        for k in ("real", "mixed", "meta"):
            print("     %-6s %9s 个词形" % (k, "{:,}".format(len(union[k]))))
        usable = union["real"] | union["mixed"]
        print("     ──────────────────────────────")
        print("     real ∪ mixed            %9s 个词形（可用的那批）"
              % "{:,}".format(len(usable)))
        print("     只落在 meta 里（没有可用中文）%5s 个词形"
              % "{:,}".format(len(union["meta"] - usable)))
        print("     两片词形并集            %9s" % "{:,}".format(len(tot)))

        print("\n" + "═" * 78)
        print("§ 3 🔴 每一桶都抽样给人读 —— **这一节才是判据的验收**")
        print("═" * 78)
        print("  判据的推翻条件：**`real` 桶里污染 > 5% 即作废重写**。")
        print("  ⚠️ 看 `meta` 桶要反着读：里面**夹着真释义**就是判据太宽（ko 栽过：")
        print("     宽的那 12 行里粘着真释义）。两头都要看，只看一头看不见另一头。")
        for name, _ in SRC:
            for k in ("real", "mixed", "meta"):
                rows = acc[name]["bucket"][k]
                if not rows:
                    continue
                print("\n  ── %s / %s（%s 条，抽 %d）"
                      % (name, k, "{:,}".format(acc[name]["kind"][k]),
                         min(a.sample, len(rows))))
                for w, pos, g in random.sample(rows, min(a.sample, len(rows))):
                    print("     %-20s %-9s %s" % (w[:18], (pos or "—")[:8], g[:62]))
    txt = buf.getvalue()
    print(txt)
    if a.archive:
        paths.PROBE.mkdir(parents=True, exist_ok=True)
        out = paths.PROBE / "probe_zh_gloss.txt"
        out.write_text(txt, "utf-8")
        print("■ 已存档 → %s" % out, file=sys.stderr)


if __name__ == "__main__":
    main()
