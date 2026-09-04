#!/usr/bin/env python3
"""要不要第 17 张表 `pronunciation_entry` —— 2026-08-31 阶段 0 前的结构探针。

═══ 问题 ═══
`[[es-v3-structure-backfill]]` 定的规矩：**照搬别的语言结构前，先量这门语言有没有那个病。**
`pronunciation_entry`（读音挂在**词条**上而不是词形上）：it 建了、收回 21,666 个词形；
es **有意不建** —— 全量回源"不同词条读音不同"只有 **14 个**词形，
而我的粗尺子当时给 13,742、v4-pro 估 200、豆包估 2,500，**三个数错一到三个数量级**。

═══ 为什么 de 上要单独量，而且上一个探针量不出来 ═══
`probes/pron_by_pos.py` 按 (词形, **词性**) 归并读音，报「跨词性读音不同」de 版 685 个。
**那个口径看不见德语最典型的那一类**：

    übersetzen  verb  [ˌyːbɐˈzɛt͡sn̩]  把…译成另一种语言   ← 不可分，重音在词干
    übersetzen  verb  [ˈyːbɐˌzɛt͡sn̩]  用渡船把…运过去     ← 可分，重音在前缀

**同词形、同词性、两个独立词条**（德语版给它们分开建页），读音与词义都不同。
`Band` 有 **4 个** noun 词条（bant 带子／bant 卷／**bɛnt** 乐队／bant 轮胎）。
⇒ 按 (word_id, pos) 建的 `pronunciation` **结构上装不下**，压平就是把 `bɛnt` 抹掉。

═══ 判据 ═══
逐**条目**保留粒度（不按词形归并），然后问：同一个 (词形, 词性) 下的多个条目，
**读音集合是不是全都一样**。只有不一样的才算一条。
  · 音标逐字节比，**不归一**（要找的差异会被归一抹掉）
  · 空读音的条目跳过 —— 它证明不了"读音不同"，只是没收
  · `[…]` 这种源头占位符**单独数**，不当读音（阶段 4 的清洗料）

跑：  cd de && python3 probes/entry_level_ipa.py
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
PLACEHOLDER = {"[…]", "…", "[...]", "...", "[ ]", ""}


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def main():
    for key, p, filt in SOURCES:
        if not p.exists():
            print("%s 🔴 文件不存在" % key)
            continue
        # (词形, 词性) → [每个条目自己的读音集合]
        groups = collections.defaultdict(list)
        ph = 0
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
                ipas = set()
                for s in (e.get("sounds") or []):
                    v = (s.get("ipa") or "").strip()
                    if not v:
                        continue
                    if v in PLACEHOLDER:
                        ph += 1
                        continue
                    ipas.add(v)
                if ipas:
                    groups[(w, pos)].append(frozenset(ipas))
        multi = {k: v for k, v in groups.items() if len(v) > 1}
        diff = {k: v for k, v in multi.items() if len(set(v)) > 1}
        # 互不为子集 ⇒ 真对立，不是"一版收得多一版收得少"
        strict = {k: v for k, v in diff.items()
                  if not any(a < b or b < a for a in set(v) for b in set(v) if a != b)}
        words = {w for (w, _) in diff}
        print("\n══ %s 版 ══" % key)
        print("   带音标的 (词形,词性) 组      %s" % f"{len(groups):,}")
        print("   同组 ≥2 个独立词条           %s" % f"{len(multi):,}")
        print("   🔴 同组各词条读音不同        %s 组 / %s 个词形" % (f"{len(diff):,}", f"{len(words):,}"))
        print("   其中互不为子集（真对立）     %s" % f"{len(strict):,}")
        print("   ⚠️ 源头占位符当读音（`[…]`） %s 条" % f"{ph:,}")
        print("   样本：")
        for k in sorted(strict, key=lambda x: (-len(groups[x]), x))[:12]:
            print("      %-16s %-6s %s" % (
                k[0][:16], k[1], "  ｜  ".join("/".join(sorted(s))[:26] for s in groups[k][:4])))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
