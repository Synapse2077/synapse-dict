#!/usr/bin/env python3
"""阶段 4 取数前：量 kaikki `sounds` 的形状与落点。2026-09-08。零 API。

⚠️ 读**中间件** `entries.jsonl`（阶段 3a 产出，已裁剪），不再扫 3.2 GB 的 dump。

═══ 要量的四件（每件都直接决定表怎么填）═══
① **占位符**：`[…]` 是「这里没有音标」的记号，不是音标。
   `[[en-dict-pipeline]]` 记着我在阶段 -1 漏掉这条判据，de 版音标报错 7.8 倍。
② **地区**：阶段 -1 量出 66.4% 自带地区标记（GA/US ／ RP/UK）。
   `region` 推不出的**一律 null，不硬填** —— de 那轮 95% 有意留空。
③ **notation**：`/…/` 音位式 ／ `[…]` 严式。给不出信号的不硬判（de 的教训：
   德语版 100% 是 `[…]` 定界，照搬 pt 的判据会把全库标成 narrow）。
④ **落点**：多少条落在库内词形上 —— 量落点不量源头（`[[measure-landing-not-source]]`）。

    cd en && python3 -u probes/sounds_shape.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import re
import sqlite3

import paths

ING = paths.WORK / "ingest" / "entries.jsonl"
# 🔴 占位符：方括号里全是省略号/空白 ＝ 源头在说"这里没有音标"
PLACEHOLDER = re.compile(r"^[\[\(]?\s*[…\.\s\-–—]*\s*[\]\)]?$")
# 🔴 **源头给的地区就要记，不能因为"我们只关心英美"就丢掉**
#    （`[[dont-gate-facts-on-my-uncertainty]]`：先问这行是源头给的还是我推的）。
#    第一版只映射 uk/us，把 Australia 13,461 / Canada 12,354 / NZ 9,505 / Scotland 7,185
#    全算进了"推不出" ⇒ 地区覆盖被我自己压低了 14 个百分点。
REGION = {"UK": "uk", "RP": "uk", "British": "uk", "Received-Pronunciation": "uk",
          "England": "uk", "Northern-England": "uk", "Southern-England": "uk",
          "US": "us", "GA": "us", "GenAm": "us", "General-American": "us", "American": "us",
          "General-American-with-cot-caught-merger": "us",
          "Australia": "au", "General-Australian": "au",
          "Canada": "ca", "New-Zealand": "nz", "Ireland": "ie", "Scotland": "gb-sct",
          "Wales": "gb-wls", "India": "in", "South-Africa": "za"}


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()

    n_line = n_snd = n_ipa = n_ph = 0
    tagc = collections.Counter()
    regc = collections.Counter()
    delim = collections.Counter()
    land_w, all_w = set(), set()
    for ln in ING.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        n_line += 1
        w = o.get("word")
        for s in o.get("sounds") or []:
            n_snd += 1
            ipa = (s.get("ipa") or "").strip()
            if not ipa:
                continue
            if PLACEHOLDER.match(ipa):
                n_ph += 1
                continue
            n_ipa += 1
            all_w.add(w)
            if w in words:
                land_w.add(w)
            d = ipa[0] + ipa[-1] if len(ipa) > 1 else "?"
            delim["/…/" if d == "//" else "[…]" if d == "[]" else "裸"] += 1
            tags = s.get("tags") or []
            hit = None
            for t in tags:
                tagc[t] += 1
                if t in REGION and hit is None:
                    hit = REGION[t]
            regc[hit or "(推不出)"] += 1

    print("═══ kaikki sounds（读中间件 %s 行，未扫 dump）═══" % format(n_line, ","))
    print("   sounds 条目          %s" % format(n_snd, ","))
    print("   🔴 占位符（不是音标）  %s  %.1f%%" % (format(n_ph, ","), 100 * n_ph / max(n_snd, 1)))
    print("   ⭐ 真 IPA            %s" % format(n_ipa, ","))
    print("\n   定界符：%s" % "  ".join("%s %s(%.0f%%)" % (k, format(v, ","), 100 * v / n_ipa)
                                     for k, v in delim.most_common()))
    print("\n   地区：")
    for k, v in regc.most_common():
        print("      %-10s %9s  %5.1f%%" % (k, format(v, ","), 100 * v / n_ipa))
    print("\n   tags 前 12：%s" % "  ".join("%s:%s" % (k, format(v, ","))
                                         for k, v in tagc.most_common(12)))
    print("\n   ⭐ **落点**：带真 IPA 的词头 %s ／ 落在库内词形上 %s = %.1f%%"
          % (format(len(all_w), ","), format(len(land_w), ","),
             100 * len(land_w) / max(len(all_w), 1)))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
