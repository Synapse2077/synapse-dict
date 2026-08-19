#!/usr/bin/env python3
"""阶段 4 第二步：**`dict.ipa` 这 588,280 条，每一条是谁写的**。不写库，只出数。2026-08-17。

═══ 为什么必须先做这一步 ═══
阶段 4 的验收判据 3 是「`ipa_src` 为空的行数为 0」。`it-CONVENTIONS` 已经记明：
那**不是核对而是回填工作**（三个 `*_src` 列存在但全空）。
而 `ipa-provenance-columns` 那条铁律是：**回填证明不了就写 `unknown`，不猜。**

⇒ 先把「能证明」的判据写清楚，再看剩下多少只能写 unknown。

═══ 四条判据（按优先级，第一个对上的就是来源）═══
① `en-edition` / `it-edition` / `fr-edition`
   —— 该词形在那一版 dump 里的某条音标，与库里这条**折点后相等**（`cmp_key`）
② `rule`
   —— **复现它当初的生成路径**：`b_ipa_fill` 是先查 kaikki `forms` 里的带重音形
      （`pàrlano`）喂 `b_ipa.word_to_ipa`，查不到才喂光杆词形。
      🔴 这一条是 `kaikki_util.sounds_and_accent_map` 顶部记着的血债：
         拿光杆词形去调 G2P 会走「倒二重音 + 闭元音」默认，
         结果自然对不上 —— 第一版普查就这么把 112,209 行（19.2%）误判成「规则算得出但不同」。
         **判定某行是不是规则产物，必须复现它当初的生成路径。**
③ `llm:doubao`
   —— 七月建库时豆包答的那批，产物还在 `data/work/it/b_out/*.json`（3,053 个分块）。
      ⚠️ 这是**记录历史来源**，不是新花钱；豆包在本项目已被明令禁用（2026-08-15）。
④ `unknown` —— 以上都对不上。**不猜。**

═══ 顺带量一个真缺陷 ═══
「库里是规则算的，而 dump 里有权威值，两者不一致」的那批。
es 上的结论是 **有权威源就用权威源，没有才派生并标 `src='rule'`**
（`build_pronunciation_layer` 顶部：`phoneticLatam` 的规则派生被证伪，630 条错得有规律）。
本脚本只报数，不改数据。

用法（在 it/ 目录下）：
    python3 probes/ipa_provenance.py
    python3 probes/ipa_provenance.py --mutate     # 变异验证：判据本体
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths                                        # noqa: E402
from b_ipa import word_to_ipa                       # noqa: E402
from ipa_variants import cmp_key, iter_source, norm_ipa   # noqa: E402
from kaikki_util import unaccent                    # noqa: E402

CENSUS = paths.WORK / "ipa_census"
B_OUT = paths.WORK / "b_out"
OUT = paths.WORK / "ipa_provenance.tsv"
# 判据①的版本优先级：主源在前（A1：英文版是建库主源）
EDITIONS = ["en-edition", "it-edition", "fr-edition"]
f = lambda n: format(n, ",")


def load_dump_values():
    """→ {词形: {版本: {cmp_key}}}。读第一步缓存的 TSV，不重扫 dump。"""
    out = defaultdict(lambda: defaultdict(set))
    for src in EDITIONS:
        p = CENSUS / ("%s.tsv" % src)
        if not p.exists():
            sys.exit("🔴 缺 %s —— 先跑 probes/ipa_census.py" % p)
        for i, ln in enumerate(p.open(encoding="utf-8")):
            if i == 0:
                continue
            c = ln.rstrip("\n").split("\t")
            if len(c) < 8:            # 源头 raw 里带换行的 3 行，音标本身仍在 c[3]
                continue
            out[c[0]][src].add(cmp_key(c[3]))
    return out


def build_accent_map():
    """去重音词形 → 带重音形。与 `b_ipa_fill.build_accent_map` **同口径**（first-seen 胜）。"""
    amap = {}
    for w, d in iter_source(paths.KK, "en-edition"):
        for fm in (d.get("forms") or []):
            form = (fm.get("form") or "").strip()
            if form and any(c in "àèéìíòóù" for c in form):
                amap.setdefault(unaccent(form), form)
    return amap


def load_llm():
    """→ {词形: {cmp_key}}，七月建库时模型答的音标。"""
    out = defaultdict(set)
    for p in sorted(B_OUT.glob("chunk_*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for v in d.values():
            if not isinstance(v, dict):
                continue
            w, ip = v.get("w"), v.get("ipa")
            if not w or not ip:
                continue
            # ⚠️ 模型有时把 ipa 答成**数组**（同一个词给两读）—— 两种都算它答过
            for one in (ip if isinstance(ip, list) else [ip]):
                if isinstance(one, str) and one.strip():
                    out[w].add(cmp_key(one.strip().strip("/[]\\")))
    return out


def classify(word, ipa, dumps, amap, llm):
    """判据本体（闸与写入共用这一个函数）→ (来源, 备注)。"""
    k = cmp_key(ipa)
    for src in EDITIONS:
        if k in dumps.get(word, {}).get(src, ()):
            return src, ""
    acc = amap.get(unaccent(word))
    for cand in ([acc] if acc else []) + [word]:
        rv = word_to_ipa(cand)
        if rv and cmp_key(rv.strip("/[]\\")) == k:
            return "rule", "accent" if cand is acc else "plain"
    if k in llm.get(word, ()):
        return "llm:doubao", ""
    return "unknown", ""


STRESS = "ˈˌ"
# 意语 G2P 三个词汇性不可预测点（`b_ipa` 顶部原话）：重音位置、e/o 开闭、s/z 清浊。
# 冲突按这三类分开看 —— 它们的可信度不一样。
QUAL = {"e": "e", "ɛ": "e", "o": "o", "ɔ": "o", "s": "s", "z": "s"}


def diff_kind(a, b):
    """两条音标的分歧属于哪一类。→ 重音位置 / 开闭·清浊 / 两者 / 音段不同。

    分这三类是因为**可信度不一样**：重音位置与开闭/清浊正是 G2P 猜不出、
    只能靠权威源的三件事；音段不同则往往是两边在说不同的词（或 fr 版噪声）。
    """
    seg = lambda s: "".join(ch for ch in s if ch not in STRESS)
    fold = lambda s: "".join(QUAL.get(ch, ch) for ch in seg(s))
    stress_moved = [i for i, ch in enumerate(a) if ch in STRESS] != \
                   [i for i, ch in enumerate(b) if ch in STRESS]
    if seg(a) == seg(b):
        return "重音位置"
    if fold(a) == fold(b):
        return "重音位置 + 开闭/清浊" if stress_moved else "开闭/清浊"
    return "音段不同"


def mutate(dumps=None, amap=None, llm=None):
    """变异验证：判据必须**区分开**四种来源，且不许把不一致的判成一致。"""
    print("═══ 变异验证：来源判据 ═══")
    D = {"gratis": {"en-edition": {cmp_key("ˈɡra.tis")}},
         "casa": {"it-edition": {cmp_key("ˈkaza")}}}
    A = {"parlano": "pàrlano"}
    L = {"xyzzy": {cmp_key("ˈksit.si")}}
    cases = [
        ("dump 里有这一条 → 记那一版", classify("gratis", "ˈɡra.tis", D, A, L)[0], "en-edition"),
        ("🔴 折点后相等也算 dump（排版差不是变体）",
         classify("gratis", "ˈɡratis", D, A, L)[0], "en-edition"),
        ("非主源版本也认", classify("casa", "ˈka.za", D, A, L)[0], "it-edition"),
        ("🔴 规则要走重音形路径才算得出",
         classify("parlano", "ˈpar.la.no", D, A, L)[0], "rule"),
        ("模型答过的记 llm", classify("xyzzy", "ˈksit.si", D, A, L)[0], "llm:doubao"),
        ("🔴 都对不上 → unknown，不许硬塞",
         classify("gratis", "zzzzz", D, A, L)[0], "unknown"),
        ("🔴 同词形但音标不同的 dump 值不许算命中",
         classify("gratis", "ɡraˈtis", D, A, L)[0], "unknown"),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-44s → %s%s" % ("✅" if good else "🔴", name, got,
                                      "" if good else "（期望 %s）" % want))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1

    print("■ 读第一步缓存的 dump 音标", flush=True)
    dumps = load_dump_values()
    print("■ 建重音形映射（扫英文版 forms，与 b_ipa_fill 同口径）", flush=True)
    amap = build_accent_map()
    print("     %s 条" % f(len(amap)), flush=True)
    print("■ 读七月建库的模型产物 b_out/", flush=True)
    llm = load_llm()
    print("     %s 个词形" % f(len(llm)), flush=True)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("SELECT id, word, ipa, is_lemma FROM dict "
                       "WHERE trim(COALESCE(ipa,''))<>''").fetchall()
    con.close()
    print("■ 分类 %s 条" % f(len(rows)), flush=True)

    c, by_lemma, conflict = Counter(), Counter(), []
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("word_id\tword\tipa\tsrc\tnote\n")
        for wid, w, ipa, is_lemma in rows:
            src, note = classify(w, ipa, dumps, amap, llm)
            c[src] += 1
            by_lemma[(src, bool(is_lemma))] += 1
            fh.write("%d\t%s\t%s\t%s\t%s\n" % (wid, w, ipa, src, note))
            # 真缺陷面：库里不是 dump 值，而 dump 明明给了这个词形音标
            if src != "unknown" and not src.endswith("-edition") and w in dumps:
                conflict.append((w, ipa, src, bool(is_lemma)))

    print("\n═══ `dict.ipa` 588,280 条的来源 ═══")
    for src, n in c.most_common():
        print("   %-12s %8s  (%.1f%%)   词头 %s / 变形 %s"
              % (src, f(n), 100.0 * n / len(rows),
                 f(by_lemma[(src, True)]), f(by_lemma[(src, False)])))

    print("\n═══ 🔴 规则/模型算的，而 dump 里有权威值且不一致 ═══")
    print("   %s 条（es 的结论：有权威源就用权威源，没有才派生并标 rule）" % f(len(conflict)))
    kinds, who, lem = Counter(), Counter(), Counter()
    for w, ipa, src, is_lemma in conflict:
        cand = sorted(set().union(*dumps[w].values()))
        kinds[min((diff_kind(cmp_key(ipa), x), x) for x in cand)[0]] += 1
        # 谁给的权威值 —— en/it 是高信任源，fr 版有噪声（`computer` 那条整短语转写）
        who["en/it 版有值" if (dumps[w].get("en-edition") or dumps[w].get("it-edition"))
            else "只有 fr 版有值"] += 1
        lem["词头" if is_lemma else "变形"] += 1
    for name, cnt in (("分歧类型", kinds), ("权威值来自", who), ("层", lem)):
        print("   %s：%s" % (name, "  ".join("%s %s" % (k, f(v)) for k, v in cnt.most_common())))
    for w, ipa, src, is_lemma in conflict[:12]:
        got = sorted(set().union(*dumps[w].values()))[:2]
        print("     %-18s 库(%s)=%-16s dump=%s" % (w[:18], src, ipa[:16], " / ".join(got)))
    print("\n   明细写在 %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
