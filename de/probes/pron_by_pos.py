#!/usr/bin/env python3
"""阶段 0 的一个结构问题：`pronunciation` 表要不要 `pos` 列。2026-08-31。

═══ 为什么必须现在量，而不是等到阶段 8 ═══
fr 是做到**阶段 8 之后的族 D 评审**才发现「读音要按词性归位」（`taper` 页头摆着名词的读音），
补 `pos` 列是**返工**。pt 在阶段 -1 就量了（484 个词形，葡语元音交替），一次建对。
`PLAYBOOK` 开篇：**顺序错了要返工，而返工最贵。**

═══ 德语上这件事的先验比罗曼语族更强 ═══
德语有一整类**最小对立**，靠重音区分可分/不可分动词，而两者**意思不同**：

    übersetzen  /ˈyːbɐˌzɛt͡sn̩/  摆渡（可分，重音在前缀）
    übersetzen  /yːbɐˈzɛt͡sn̩/   翻译（不可分，重音在词干）
    umfahren / durchbrechen / umgehen … 同一族

还有名词/动词同形（`der Band` 卷 vs `das Band` 带子）与外来词的两读。
⇒ **本探针只负责如实数**：同一个词形在不同 `pos` 下读音到底一不一样、有多少个。
   建不建列由数字决定，不由这段先验决定。

⚠️ 只读，不写库、不下载。判据：
  · 音标逐字节比较，**不归一**（归一会把要找的差异抹掉 —— 那正是我们要数的东西）
  · 同一 (词形, pos) 内部有多个读音是**正常的**（方言/异读），不算数
  · 只有**跨 pos 的读音集合不相等**才算一条

跑：  cd de && python3 probes/pron_by_pos.py
"""
import collections
import gzip
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import paths                                     # noqa: E402

SOURCES = [
    ("en", paths.DUMPS / "kaikki.org-dictionary-German.jsonl", False),
    ("de", paths.DUMPS / "dewiktionary.jsonl.gz",              True),
]


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def main():
    for key, p, filt in SOURCES:
        if not p.exists():
            print("%s 🔴 文件不存在" % key)
            continue
        byword = collections.defaultdict(lambda: collections.defaultdict(set))
        with opener(p) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if filt and e.get("lang_code") != "de":
                    continue
                w, pos = e.get("word"), e.get("pos")
                if not w or not pos:
                    continue
                ipas = {s["ipa"] for s in (e.get("sounds") or []) if s.get("ipa")}
                if ipas:
                    byword[w][pos] |= ipas
        multi = {w: d for w, d in byword.items() if len(d) > 1}
        diff = {w: d for w, d in multi.items()
                if len({frozenset(v) for v in d.values()}) > 1}
        # 只有一方的读音是另一方的真子集 ⇒ 多半是收录多寡，不是对立
        strict = {w: d for w, d in diff.items()
                  if not any(a < b or b < a
                             for a in map(frozenset, d.values())
                             for b in map(frozenset, d.values()) if a != b)}
        print("\n══ %s 版 ══" % key)
        print("   带音标的词形               %s" % f"{len(byword):,}")
        print("   跨 pos 出现（≥2 个词性）    %s" % f"{len(multi):,}")
        print("   🔴 跨 pos 读音集合不相等    %s" % f"{len(diff):,}")
        print("   其中互不为子集（真对立）    %s" % f"{len(strict):,}")
        print("   样本：")
        for w in sorted(strict)[:12]:
            print("      %-18s %s" % (w, " ｜ ".join(
                "%s %s" % (k, "/".join(sorted(v))[:46]) for k, v in sorted(byword[w].items()))))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
