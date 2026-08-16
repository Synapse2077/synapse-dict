#!/usr/bin/env python3
"""同形异读普查：一个词形在源头有几个**读音不同**的词条，我们压成了几行。

═══ 为什么要先量 ═══
`ancora`（副词 ancóra 仍然 / 名词 àncora 锚）、`pesca`（桃 ˈpɛska / 捕鱼 ˈpeska）
在库里各只有一行、一个音标 —— 也就是说其中一个义项配的重音是错的。
但"有多少个"决定了处理方式：几百个和上万个是两种工程。
🔴 [[llm-as-evaluator-discipline]] ⑩：能确定性回源比对的，根本别问模型。

判据（保守，宁可少报）：
  · 只看同一词形下**不同 entry**（kaikki 一个 entry ≈ 一个词性/词源）
  · 每个 entry 取其音位式音标集合（`sounds[].ipa`，排除 romanization/rhymes）
  · 两个 entry 的音标集合**完全不相交** ⇒ 判为同形异读
    （相交的多半只是变体差异，不是两个词）
  · 归一化只做最保守的一步：去定界符、去音节点 `.`、去连结弧 —— 不动重音符与元音质量，
    因为**它们正是判据本身**

只读 dump，不碰库。

跑：  python3 probes/homograph_census.py            （en 版，约 1 分钟）
      python3 probes/homograph_census.py --src it   （意语版）
      python3 probes/homograph_census.py --list 40  （打印样例）
"""
import argparse
import gzip
import json
import sys
import pathlib
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import paths

SRC = {
    "en": (paths.KK, False),
    "it": (paths.EDITION, True),
    "fr": (paths.KK_FR, False),
}


def norm(ipa):
    """最保守的归一：只去掉不表音的记号。**重音符和元音质量必须保留**——它们是判据。"""
    s = ipa.strip()
    for a, b in (("/", ""), ("[", ""), ("]", ""), ("\\", ""), (".", ""), ("͡", "")):
        s = s.replace(a, b)
    return s.strip()


def phonemic(entry):
    out = set()
    for s in entry.get("sounds") or []:
        ip = s.get("ipa")
        if not ip:
            continue
        tags = set(s.get("tags") or [])
        if tags & {"romanization", "rhymes", "X-SAMPA"}:
            continue
        n = norm(ip)
        if n:
            out.add(n)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="en", choices=sorted(SRC))
    ap.add_argument("--list", type=int, default=12)
    a = ap.parse_args()
    path, need_filter = SRC[a.src]

    per_word = defaultdict(list)          # word → [(pos, frozenset(ipa)), …]
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if need_filter and e.get("lang_code") != "it":
                continue
            ip = phonemic(e)
            if ip:
                per_word[e.get("word")].append((e.get("pos"), frozenset(ip)))

    stat = Counter()
    hits = defaultdict(list)
    for w, entries in per_word.items():
        stat["有音标的词形"] += 1
        sets = [s for _, s in entries]
        if len(entries) < 2:
            continue
        stat["同词形多 entry"] += 1
        disjoint = False
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                if sets[i] and sets[j] and not (sets[i] & sets[j]):
                    disjoint = True
        if not disjoint:
            continue
        stat["音标集合不相交（上界）"] += 1
        # 🔴 上界要分类：样例里 `-ano: ano | ˈano` 只是**漏标重音符**，不是两个词。
        #    分类判据：
        #      C 转写不一致 —— 有的 entry 整个没有重音符（ˈ/ˌ 都没有）
        #      A 重音位置不同 —— 都标了重音，去掉重音符后**其余字母相同**（ancora）
        #      B 元音质量不同 —— 去掉重音符后不同，但只差 e↔ɛ / o↔ɔ（pesca）
        #      D 其余（音段真不一样，多为外来名/异读）
        allmarked = all(any("ˈ" in x or "ˌ" in x for x in s) for s in sets if s)
        bare = [frozenset(x.replace("ˈ", "").replace("ˌ", "") for x in s) for s in sets]
        flat = [frozenset(x.replace("ɛ", "e").replace("ɔ", "o") for x in s) for s in bare]
        if not allmarked:
            cls = "C 转写不一致（有 entry 漏标重音）"
        elif any(bare[i] & bare[j] for i in range(len(bare)) for j in range(i + 1, len(bare))):
            cls = "A 重音位置不同"
        elif any(flat[i] & flat[j] for i in range(len(flat)) for j in range(i + 1, len(flat))):
            cls = "B 元音开闭不同"
        else:
            cls = "D 音段不同（外来名/异读）"
        stat["  " + cls] += 1
        hits[cls].append((w, entries))
        if any(p not in ("suffix", "prefix", "name", "character") for p, _ in entries):
            stat["    其中含实词（非词缀/专名）"] += 1

    print("■ 源：%s" % path.name)
    for k, v in stat.items():
        print("   %-32s %10s" % (k, f"{v:,}"))
    n = stat["🔴 同形异读（音标集合不相交）"]
    print("   %-32s %10.2f%%" % ("占有音标词形的比例", 100 * n / max(stat["有音标的词形"], 1)))

    print("\n■ 各类样例（只看实词，词缀/专名跳过）")
    for cls in sorted(hits):
        real = [(w, e) for w, e in hits[cls]
                if any(p not in ("suffix", "prefix", "name", "character") for p, _ in e)]
        print("\n   ── %s：%d 个（实词 %d）" % (cls, len(hits[cls]), len(real)))
        for w, entries in sorted(real)[:a.list]:
            print("      %-20s %s" % (w, "  |  ".join(
                "%s %s" % (p, "/".join(sorted(s))[:32]) for p, s in entries)))


if __name__ == "__main__":
    main()
