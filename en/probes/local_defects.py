#!/usr/bin/env python3
"""本地确定性缺陷检测器。见对话 2026-07-30。

为什么不交给模型:2026-07-30 实测,把"空壳(E)"从判官 prompt 里摘掉、改由 buckets.is_shell()
确定性判定后,精确率从 ~67% 跳到 **100%**、方差从 ±6pp 归零。
→ 凡是**纯结构/纯文本**可判的缺陷,一律本地做;只把**需要专业知识**的留给模型。
   test 集实测:廉价模型(flash∪mini)召回天花板约 63%,漏掉的一半是机械类缺陷。

本模块两个检测器:
  P 比较级/最高级未体现 —— exchange 说 1:r/1:t,而译文里找不到"更/较/最"
  H 词头讹写            —— 词头不在任何词表里,但**距某个真词只差 1-2 个字符**
                          ("查不到"本身不算:bridge washer 也查不到,但它是正规术语)

用法:
  python3 en/local_defects.py --check P --limit 20     # 抽样看检测效果
  python3 en/local_defects.py --check H --limit 20
  python3 en/local_defects.py --eval                   # 在 eval_set.json 上算精确率/召回率
  python3 en/local_defects.py --scan --out flags.json  # 全库扫,落 id → 码
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, json, re, sqlite3
from collections import Counter
from pathlib import Path

import buckets as B

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
WORDSET = paths.WORK / "anchors/kaikki_wordset.json"

# ---------- P:比较级/最高级 ----------
# exchange 的 1: 字段含 r=比较级 t=最高级
DEGREE = re.compile(r"更|较|最|逾|愈|比[^喻]|超过")
# 译文里已经自陈是比较级/最高级的,不算缺陷(它交代清楚了)
SELF = re.compile(r"比较级|最高级|comparative|superlative")


def infl_type(exchange):
    d = {}
    for p in (exchange or "").split("/"):
        if ":" in p:
            k, v = p.split(":", 1)
            d[k] = v
    return d.get("1", "").strip(), d.get("0", "").strip()


ADJ = re.compile(r"(^|[\s|;；])(a|adj)\.")


def stems(w):
    """-er/-est 的可能词干(含 -ier→-y、双写还原)。exchange 为空时的兜底路径。"""
    wl = w.lower(); out = []
    for suf, n in (("iest", 4), ("est", 3), ("ier", 3), ("er", 2)):
        if not wl.endswith(suf) or len(wl) - n < 3:
            continue
        base = wl[:-n]
        out.append(base + "y" if suf in ("iest", "ier") else base)
        if suf in ("est", "er"):
            out.append(base + "e")                      # nicer→nice
            if len(base) > 2 and base[-1] == base[-2]:
                out.append(base[:-1])                   # bigger→big
    return out


def flag_P(word, zh, exchange, lemma_zh=None, known=None, zh_of=None):
    """exchange 说是比较级/最高级,但译文既没程度词、也没自陈变形关系。

    ⚠️ **exchange 的比较级/最高级分析不可信**,它是按 -er/-est 词尾机械推的:
       armrest→"armr 的最高级"、banter→"bant 的比较级"、Bayer→"baye 的比较级"
       —— 这些译文全是对的,错的是 exchange。所以必须加两道闸:
         ① 原形得是真词(在词表里);
         ② 原形的译文得是**形容词**(只有形容词才有比较级)。
    """
    body = (zh or "").strip()
    if not body or SELF.search(body) or DEGREE.search(body):
        return False
    typ, lem = infl_type(exchange)
    if typ and lem and ({"r", "t"} & set(typ)):
        if known is not None and lem.lower() not in known:
            return False                   # 闸①:原形不是真词 → exchange 在瞎猜
        if lemma_zh is not None and not ADJ.search(lemma_zh or ""):
            return False                   # 闸②:原形不是形容词 → 比较级读法不成立
        return True
    # 兜底:exchange 为空(实测 hatefuller 就是),靠构词法。同样要求词干是**库内形容词**,
    # 否则 banter→bant 那类会大面积误伤。
    if zh_of is None:          # ⚠️ 别用 lemma_zh 当守卫:exchange 为空时它本来就是 None
        return False
    if not ADJ.search(body):               # 自身得是形容词条目
        return False
    for st in stems(word or ""):
        z = zh_of(st)
        if z and ADJ.search(z):
            return True
    return False


# ---------- H:词头讹写 ----------
# ⚠️ 结尾的 ? 多是**合法问号**('sup yo? / ...or what?),不算缺陷 —— 实测 918 条。
#   真损坏是 ? 出现在**开头或词中**:α/β 希腊字母、æ 连字、威妥玛拼音的 ü 在建库时丢成了 ?
#   (?-actin=α-actin、aa. gastric? breves=gastricae、y?eh=yüeh)。实测约 1,297 条。
LOSTCHAR = re.compile(r"^\?|\?(?=.)")          # ? 在开头,或 ? 后面还有字符
BADCHAR = re.compile(r"[*#@~^\\|<>{}\[\]]")   # 其余非法字符
ALPHA = "abcdefghijklmnopqrstuvwxyz"


def edits1(w):
    """编辑距离 1 的全部候选(删/换/插/换位)。"""
    out = set()
    for i in range(len(w)):
        out.add(w[:i] + w[i + 1:])                       # 删
        for c in ALPHA:
            out.add(w[:i] + c + w[i + 1:])               # 换
        if i:
            out.add(w[:i - 1] + w[i] + w[i - 1] + w[i + 1:])  # 换位
    for i in range(len(w) + 1):
        for c in ALPHA:
            out.add(w[:i] + c + w[i:])                   # 插
    out.discard(w)
    return out


def flag_H(word, known, min_len=5, edit_distance=False):
    """🔴 **编辑距离那部分已默认关闭 —— 随机样本实测精确率仅约 10%。**

    2026-07-30 在随机 2,000 条上人工核实:H 标记 25 条只有 2 条是真缺陷。误报清一色是
    **真实专名**(Capuzzo/Linau/Blesle/Venaria/Chérac/yassky/Galiani),它们只是不在 kaikki
    里、又恰好距某个词编辑距离 1。词典尾巴专名密集,这个统计猜测不成立。
    ⚠️ 而在人工评测集上它是 3/3 = 100% —— 那 3 条本身是从"模型标过"的池子里捞的,
       天然富集真缺陷。**这是选择偏差制造的假象,别信小样本上的完美精确率。**

    保留的只有 LOSTCHAR:词头里 `?` 替换了 α/β/æ/ü,这是**事实性字符损坏**,不是猜测。
    但它属于"字符修复"轨道,不是"译文重译"轨道 —— 译文往往是对的(?-actin → 肌动朊 正确),
    所以不该混进标记流水线。传 edit_distance=True 才启用旧行为。"""
    w = (word or "").strip()
    if not w:
        return None
    if LOSTCHAR.search(w):
        return "字符丢失(? 替换了 α/β/æ/ü)"
    if BADCHAR.search(w):
        return "非法字符"
    wl = w.lower()
    if " " in wl or "-" in wl:          # 短语/复合词不判
        return None
    if len(wl) < min_len or not wl.isalpha():
        return None
    if wl in known:
        return None
    if not edit_distance:
        return None
    hits = [c for c in edits1(wl) if c in known and len(c) >= min_len]
    return f"疑似讹写(近似 {hits[0]})" if hits else None


def load_known():
    if not WORDSET.exists():
        raise SystemExit(f"缺 {WORDSET.name},先跑词表构建")
    known = set(json.load(open(WORDSET, encoding="utf-8")))
    # 补上库内**有词频/词典信号**的词:它们是真词,即使 kaikki 未收
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    for (w,) in conn.execute(
            f"SELECT word FROM stardict WHERE {B.CORE}"):
        known.add((w or "").strip().lower())
    conn.close()
    return known


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", choices=["P", "H"])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--out", default="local_flags.json")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    if a.check == "P":
        known = load_known()
        lz = {}
        for w, t in conn.execute("SELECT word,translation FROM stardict"):
            k = (w or "").strip().lower()
            if k not in lz:
                lz[k] = t or ""
        n = 0
        for rid, w, t, e in conn.execute(
                "SELECT id,word,translation,exchange FROM stardict "
                "WHERE COALESCE(exchange,'') LIKE '%1:%'"):
            if flag_P(w, t, e, lz.get(infl_type(e)[1].lower()), known, lz.get):
                typ, lem = infl_type(e)
                print(f"  {w[:24]:26} [{lem} 的 {typ}]  {(t or '').replace(chr(10),' | ')[:44]}")
                n += 1
                if n >= a.limit:
                    break
        print(f"\n(前 {n} 条)")
        return

    if a.check == "H":
        known = load_known()
        print(f"词表 {len(known):,} 词")
        n = 0
        for rid, w, t in conn.execute("SELECT id,word,translation FROM stardict"):
            r = flag_H(w, known)
            if r:
                print(f"  {w[:26]:28} {r:<26} {(t or '').replace(chr(10),' | ')[:32]}")
                n += 1
                if n >= a.limit:
                    break
        print(f"\n(前 {n} 条)")
        return

    if a.eval:
        gold = {r["id"]: r for r in json.load(open(paths.WORK / "runs/eval_set.json", encoding="utf-8"))}
        known = load_known()
        lz = {}
        for w, t in conn.execute("SELECT word,translation FROM stardict"):
            k = (w or "").strip().lower()
            if k not in lz:
                lz[k] = t or ""
        rows = {}
        ids = ",".join(str(i) for i in gold)
        for rid, w, t, e in conn.execute(
                f"SELECT id,word,translation,exchange FROM stardict WHERE id IN ({ids})"):
            rows[rid] = (w, t, e)
        for split in ("dev", "test"):
            use = [i for i in gold if gold[i]["label"] != "unsure" and gold[i]["split"] == split]
            det = {}
            for i in use:
                w, t, e = rows[i]
                cs = ""
                if B.is_shell((t or "").strip()):
                    cs += "E"
                if flag_P(w, t, e, lz.get(infl_type(e)[1].lower()), known, lz.get):
                    cs += "P"
                if flag_H(w, known):
                    cs += "H"
                det[i] = cs
            tp = sum(1 for i in use if gold[i]["label"] == "bad" and det[i])
            fp = sum(1 for i in use if gold[i]["label"] == "ok" and det[i])
            fn = sum(1 for i in use if gold[i]["label"] == "bad" and not det[i])
            p = 100 * tp / max(tp + fp, 1); r = 100 * tp / max(tp + fn, 1)
            print(f"[{split}] 纯本地检测器  TP {tp} FP {fp} FN {fn}  "
                  f"精确率 {p:.1f}%  召回率 {r:.1f}%")
            if fp:
                for i in use:
                    if gold[i]["label"] == "ok" and det[i]:
                        print(f"    误报 [{det[i]}] {gold[i]['word'][:26]:28} ← {gold[i]['why'][:40]}")
            hit = [i for i in use if gold[i]["label"] == "bad" and det[i]]
            print(f"    抓到: " + ", ".join(f"{gold[i]['word'][:20]}[{det[i]}]" for i in hit))
        return

    if a.scan:
        known = load_known()
        lz = {}
        for w, t in conn.execute("SELECT word,translation FROM stardict"):
            k = (w or "").strip().lower()
            if k not in lz:
                lz[k] = t or ""
        out = {}; tal = Counter()
        for rid, w, t, e in conn.execute("SELECT id,word,translation,exchange FROM stardict"):
            cs = ""
            if B.is_shell((t or "").strip()):
                cs += "E"
            if flag_P(w, t, e, lz.get(infl_type(e)[1].lower()), known, lz.get):
                cs += "P"
            if flag_H(w, known):
                cs += "H"
            if cs:
                out[rid] = cs
                for ch in cs:
                    tal[ch] += 1
        json.dump(out, open(HERE / a.out, "w"), ensure_ascii=False)
        print(f"全库本地检出 {len(out):,} 条 → {a.out}")
        for ch, n in tal.most_common():
            print(f"  {ch} {n:,}")


if __name__ == "__main__":
    main()
