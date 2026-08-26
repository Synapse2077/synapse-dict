#!/usr/bin/env python3
"""阶段 1.5(b) 之前：把地名族拆成「骨架 + 参数」，用模板确定性生成中文。2026-08-22。

═══ 为什么值得先做这个 ═══
待翻译的 511,083 条法语释义里，**地名族占 75,400 条**，长这样：

    Commune française, située dans le département du Pas-de-Calais.
    Commune d’Allemagne, située dans la Rhénanie-Palatinat.
    Commune d’Italie de la province de Bergame.

它们不是 7.5 万个不同的句子，而是**少数骨架 × 一批地区名**：

    归一冠词后的骨架   2,830 种 —— **前 30 个覆盖 87.0%**，前 60 个 90.7%
    地区名             5,387 个 —— **出现 ≥5 次的 1,199 个覆盖 91.6%**

⇒ 翻 **30 个骨架 + 1,199 个地区名 = 1,229 个单元**，确定性生成 **7.5 万条中文**。
   **53 倍压缩。**

⭐ **而且比送模型更好，不只是更便宜：**
① 同一骨架永远渲染成同一句 —— 没有 flash 那 30% 的表述漂移
② 同一地区名永远同一个中文 —— 模型跑三次能给出三个音译（mini 实测：米雷/迪雷/迪雷泰）
③ 🔴 **地区被保留下来** —— 这正是 `[[criteria-from-meaning-not-form]]` 那个已知缺陷的解药：
   当时 prompt 写「不是长句翻译」，模型把 `Saint-Léger (Charente).` 压成「圣莱热」，
   **十个同名市镇的中文一模一样**，坏掉 1,528 条。模板天然不会犯这个错。

═══ 分工 ═══
  · **骨架的中文**：我手写，逐条对着法语原文核（30 个，是最终产物，错了就是几万条一起错）
  · **地区名的中文**：送模型翻**一次**（短、量小、可去重复用），我抽样核
  · 骨架或地区名任一没命中 ⇒ **不生成**，退回模型走正常翻译路径。**宁可缺不可错。**

用法（在 fr/ 目录下）：
    python3 pipeline/geo_template.py --extract    # 抽骨架与地区名，落盘供审
    python3 pipeline/geo_template.py --stats
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths   # noqa: E402

WORK = paths.WORK / "geo"

# 只处理这些通名开头的（地名族）
FAM = re.compile(r"^(Commune|Ville|Village|Municipalité|Hameau|Localité|Bourg|Quartier)\b", re.I)
# 把结尾的「<介词> <专名>.」切出来 —— 专名必须大写开头，且不含逗号/分号
PARAM = re.compile(
    r"^(.*?)\s*\b(de la|de l’|de l'|du|des|de|d’|d'|dans le|dans la|dans les|dans l’|en)\s+"
    r"([A-ZÀ-Ý][^,.;]*?)\s*\.?$")


def split(text):
    """→ (骨架, 参数) 或 None。骨架已归一冠词与空白。"""
    t = text.strip()
    if not FAM.match(t):
        return None
    m = PARAM.match(t)
    if not m:
        return None
    skel = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(",")
    return skel, m.group(3).strip()


def rows(con):
    return [(sid, t) for sid, t in con.execute("""
        SELECT s.id, g.text FROM sense s
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL""")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--top-skel", type=int, default=60)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    all_rows = rows(con)
    skel, param, hit = Counter(), Counter(), 0
    pair = []
    for sid, t in all_rows:
        r = split(t)
        if not r:
            continue
        hit += 1
        skel[r[0]] += 1
        param[r[1]] += 1
        pair.append((sid, r[0], r[1]))

    print("■ 待翻译 %s 条；地名族可拆 %s 条（%.1f%%）"
          % (f"{len(all_rows):,}", f"{hit:,}", 100.0 * hit / len(all_rows)))
    print("   骨架 %s 种 / 地区名 %s 个" % (f"{len(skel):,}", f"{len(param):,}"))
    for n in (30, 60, 120, 300):
        print("   前 %3d 个骨架覆盖 %.1f%%" % (n, 100.0 * sum(v for _, v in skel.most_common(n)) / hit))
    for n in (2, 5, 10):
        c = sum(v for v in param.values() if v >= n)
        print("   出现 ≥%2d 次的地区名 %5s 个，覆盖 %.1f%%"
              % (n, f"{sum(1 for v in param.values() if v >= n):,}", 100.0 * c / hit))

    if a.stats:
        print("\n── 骨架 top %d ──" % a.top_skel)
        for k, v in skel.most_common(a.top_skel):
            print("   %7s  %s" % (f"{v:,}", k))
        return 0

    if not a.extract:
        print("\n(未加 --extract，不落盘)")
        return 0

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "skeletons.tsv").write_text(
        "\n".join("%d\t%s" % (v, k) for k, v in skel.most_common()), encoding="utf-8")
    (WORK / "regions.tsv").write_text(
        "\n".join("%d\t%s" % (v, k) for k, v in param.most_common()), encoding="utf-8")
    (WORK / "pairs.jsonl").write_text(
        "\n".join(json.dumps({"sense_id": s, "skel": k, "param": p}, ensure_ascii=False)
                  for s, k, p in pair), encoding="utf-8")
    print("\n✓ 落盘 %s" % WORK)
    print("   skeletons.tsv  %s 行" % f"{len(skel):,}")
    print("   regions.tsv    %s 行" % f"{len(param):,}")
    print("   pairs.jsonl    %s 行" % f"{len(pair):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
