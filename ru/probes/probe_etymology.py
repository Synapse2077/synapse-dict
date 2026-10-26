#!/usr/bin/env python3
"""阶段 7 探针：**词源层的落点与形状**。ru，2026-10-24。只读。

    python3 -u ru/probes/probe_etymology.py > data/work/ru/probe/probe_etymology.txt

  §A 每源：哪个字段（单数/复数/都有）、条目数、段数分布、长度分位
  §B 🔴 **先量这一列本身**（vi 的 B21／本门 6a 的教训）：形状分堆按源，每堆随机样本
       —— 占位串（«желательно добавить сведения об этимологии»）、模板残渣、`__MAGIC__`、整段＝词头、
       只有文献出处没有内容、过短……
  §C 同一段在同一词形的多个 entry 上重复（en 版同词源下名词/动词各抄一遍）⇒ 去重后的真实段数
  §D en 版 `etymology_templates` 的**完整值域**（`etym_type` 的依据，全打不截断）
  §E 读者口径：词元有词源（三语）／按源
判据一律 `import criteria`；值域全打。
"""
import collections
import random
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC, rd                              # noqa: E402

RND = random.Random(20261024)
F = lambda n: format(n, ",")                                    # noqa: E731


def shape(word, t):
    s = (t or "").strip()
    if not s:
        return "空"
    if re.search(r"__[A-Z]+__", s):
        return "含 __MAGIC__"
    if re.search(r"\{\{|\}\}|\[\[|\]\]|<[a-z/]", s):
        return "含 wiki/HTML 标记"
    if re.search(r"(?i)желательно|добавить сведения|не указан|неизвестн[оа]|нет данных|требуется", s):
        return "疑似占位/未知（含 желательно/неизвестно…）"
    if re.search(r"(?i)использованная литература|литература:|фасмер|шанский|черных", s) and len(s) < 80:
        return "短且只有文献"
    if not any(ch.isalpha() for ch in s):
        return "没有字母"
    if criteria.strip_stress(s).strip(" .").lower() == criteria.strip_stress(word).lower():
        return "整段＝词头"
    if len(s) < 8:
        return "过短 <8"
    if "\n" in s:
        return "多行"
    return "看起来正常"


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    is_lemma = dict(con.execute("SELECT word, is_lemma FROM dict"))
    con.close()
    st = collections.defaultdict(collections.Counter)
    seglen = collections.defaultdict(list)
    sh = collections.Counter()
    sheg = collections.defaultdict(list)
    tmpl = collections.Counter()
    tmpl_eg = collections.defaultdict(list)
    seen = collections.defaultdict(set)          # (src, word) → 段文本集合
    have = collections.defaultdict(set)          # src → 有词源的词形
    for src, p in SRC:
        for e in rd(p):
            ok, _s, _pos = criteria.entry_accept(e)
            if not ok:
                continue
            w = e["word"]
            one, many = e.get("etymology_text"), e.get("etymology_texts")
            k = "单数+复数" if one and many else "单数" if one else "复数" if many else None
            st[src]["entries"] += 1
            if not k:
                continue
            st[src]["有词源·" + k] += 1
            segs = []
            if one:
                segs.append(one)
            if many:
                segs += [x for x in many if isinstance(x, str)]
                if not all(isinstance(x, str) for x in many):
                    st[src]["🔴 复数字段里有非字符串"] += 1
            st[src]["段数=%d" % len(segs)] += 1
            for t in segs:
                seglen[src].append(len(t))
                b = shape(w, t)
                sh[(src, b)] += 1
                if len(sheg[(src, b)]) < 300:
                    sheg[(src, b)].append("%s ⟫ %s" % (w, t.replace("\n", "⏎")[:140]))
                key = criteria.strip_stress(t).strip()
                if key in seen[(src, w)]:
                    st[src]["同词形同源重复段"] += 1
                else:
                    seen[(src, w)].add(key)
                if b == "看起来正常":
                    have[src].add(w)
            for tp in e.get("etymology_templates") or []:
                n = tp.get("name")
                tmpl[n] += 1
                if len(tmpl_eg[n]) < 2:
                    tmpl_eg[n].append("%s: %s" % (w, (tp.get("expansion") or "")[:60]))
        print("   …%s 扫完" % src, flush=True)

    print("■ 俄语阶段 7 探针：词源层  2026-10-24  判据 %s" % criteria.RULE_VER)
    print("\n§A 每源规模")
    for src, _p in SRC:
        L = sorted(seglen[src])
        q = (lambda f: L[int(f * (len(L) - 1))]) if L else (lambda f: 0)
        print("   ── %s：%s" % (src, dict(st[src])))
        print("      段长 p10=%d p50=%d p90=%d p99=%d max=%d" % (q(.1), q(.5), q(.9), q(.99), q(1)))
    print("\n§B 🔴 形状分堆（按源，每堆随机 5 条）")
    for k, v in sorted(sh.items()):
        print("   %-48s %10s" % (" / ".join(k), F(v)))
        for x in RND.sample(sheg[k], min(5, len(sheg[k]))):
            print("         · %s" % x)
    print("\n§C 去重后的段数（同源同词形）")
    for src, _p in SRC:
        n = sum(len(v) for (s, _w), v in seen.items() if s == src)
        print("   %-18s %10s" % (src, F(n)))
    print("\n§D en 版 etymology_templates 完整值域（%d 种）" % len(tmpl))
    for n, v in tmpl.most_common():
        print("   %8s  %-24s %s" % (F(v), n, " ｜ ".join(tmpl_eg[n])))
    print("\n§E 读者口径：词元有「看起来正常」的词源")
    lem = {w for w, l in is_lemma.items() if l == 1}
    allw = set()
    for src, _p in SRC:
        h = {w for w in have[src] if w in lem}
        allw |= h if criteria.SENSE_LANG[src] in criteria.PUBLISH_LANGS else set()
        print("   %-18s %9s 词元（%.2f%%）" % (src, F(len(h)), 100.0 * len(h) / len(lem)))
    print("   三语并集 %s 词元（%.2f%%）" % (F(len(allw)), 100.0 * len(allw) / len(lem)))
    print("\n■ 完。")


if __name__ == "__main__":
    main()
