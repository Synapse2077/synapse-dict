#!/usr/bin/env python3
"""阶段 2 探针：**重音层的落点**。ru，2026-10-08。

═══ 为什么阶段 -1 量过了还要再量一次 ═══
阶段 -1 的 `probe_stress.py` 量的是**源头侧**（「重音住在哪」：词头 0.00%、
`forms[canonical]` 99.93%、ru 版 `forms` 94.83%）。那一轮回答的是「要不要建这一层」。
这一轮回答的是**另一件事**：

  🔴 `[[measure-landing-not-source]]`：**量落点不量源头。**
     源头有 42 万条 canonical ≠ 库里能挂上 42 万条 ——
     能挂上的前提是「它所属的那行源头**真的落成了一个 entry**」。

⇒ §0 先把这件事**证明**出来（而不是假设）：按 `criteria.entry_accept` ＋ `criteria.SrcRef`
  重放一遍七源，拼出的 `src_ref` 集合必须与库里 `entry.src_ref` **完全相等**。
  这同时是 2026-10-08 那次重构（判据从 `build.py` 搬进 `criteria.py` §⑥）的回归验证：
  **两边差一行，挂上去的重音就整体错位一格，而两边各自的闸都会报绿。**

═══ 🔴🔴 §5.1 的「三个源」清单是不全的 ═══
`RU_PLAN` §5.1 列了 en 版 `canonical` 423,676 ／ ru 版 `stressed` 2,367 ／
ru 版变位表 4,170,656。但阶段 -1 的 §A 表格自己印着：
    zh-t canonical 72,193（99.99% 带重音）／ fr 33,450（99.51%）／
    zh-s 9,270（99.98%）／ vi 1,256（99.60%）
—— 合计 **116,169 行**，而当时我没把它们写进裁决。`[[cross-edition-harvest]]`：
语言版 dump 里有大量**其他语言**的词条且带音标 —— 同一条在重音上也成立。
⇒ §E 必须分两个口径报：**只用 en** 和 **七源并集**，差额才是「漏掉它们的代价」。

═══ 判据纪律 ═══
① 所有谓词 `from pipeline import criteria`，本文件**一条都不自己实现**；
② §B 是**完整值域、无条件、不过滤** —— 这条是 2026-10-07 栽出来的：
   我拿一张猜的 `ASPECT_WORDS` 表当值域，`perfective` 几乎没有而真名是 `perfect`，
   于是**两家外审对一个不存在的现象各给了一套有说服力的归因**
   （`[[consult-two-models-on-rules]]`：有说服力的归因是前提错误的掩体）。
   加了「无条件全打」之后第一次跑就又逮到两个漏掉的值名。
③ 残差一律**单独成桶并打印样本**，不许沉进「其他」（`[[residual-bucket-is-not-evidence]]`）。
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                   # noqa: E402
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC                                  # noqa: E402

# 本层只认这两个 tag。**它们是源头的 tag 名，不是我起的** ——
#   en/zh/fr/vi 版：`forms[tags 含 'canonical']`  = 这个词元的带重音规范拼写
#   ru 版：        `forms[tags 含 'stressed']`    = 专为这件事存在的字段
# 🔴 判据是「tags **含**」不是「tags **等于**」：实测 en 版的 canonical 行同时带
#    语法标签（`['animate','canonical','feminine']`），写 `==` 会漏掉几乎全部。
FIELD_TAGS = ("canonical", "stressed")


def provenance(tags):
    """这一行 `forms` 记录的**来源身份**。→ `canonical`/`stressed`/`无标签`/`语法标签`。

    🔴🔴 2026-10-08 实测推翻了本层的第一版候选判据。第一版只收「tags 含
    canonical/stressed」的行，而 **ru 版 43.85% 的条目的带重音拼写不带这两个 tag** ——
    它躺在变位表里，标着 `['singular','nominative']`（主格单数那一行**就是词元自己**）：

        агат → ага́т  ['singular', 'nominative']
        эбонитовый → эбони́товый  ['singular', 'masculine', 'nominative']

    ⇒ 候选判据改成「**剥掉重音符之后等于词头**」（`criteria.stressed_spelling`），
      tag **只当来源不当门槛**。`[[criteria-narrower-than-you-think]]`：
      我的判据又一次比它要描述的那件事窄 —— 而 ru 版正是供了 97.6% 词元的那一版。
    """
    ts = set(tags or [])
    if "canonical" in ts:
        return "canonical"
    if "stressed" in ts:
        return "stressed"
    return "无标签" if not ts else "语法标签"

# 俄语正字里**合法**的字符（判据按含义：这是「一个带重音的俄语拼写」允许出现的东西）。
#   西里尔字母 ＋ U+0301/U+0300 ＋ 空格（多词词条）＋ 连字符（复合词/词缀）
# ⚠️ 这不是白名单式清洗，是**用来把残渣逼出来**的度量 —— 不合法的字符
#    一个一个列名字、带样本，谁都别想沉进大桶。
def _odd_chars(s):
    out = []
    for c in s:
        if c in (" ", "-", criteria.STRESS, "̀"):
            continue
        if dbtool.is_cyrillic(c):
            continue
        out.append(c)
    return out


def rd(p, limit=None):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                return
            yield json.loads(line)


def scan(limit=None):
    """重放七源 → 候选重音行 ＋ 拼出的 src_ref 集合。**只读。**"""
    ref = criteria.SrcRef()
    refs = set()                                   # 拼出来的 src_ref（§0 要跟库比）
    # 候选：src_ref → {带重音的串: 来源}（同一个串被多行给出时只留第一个来源）
    cand = collections.defaultdict(dict)
    word_of = {}                                   # src_ref → 词头（§C/§G 要）
    st = {
        "accepted": collections.Counter(),
        "skipped": collections.Counter(),
        "rows": collections.Counter(),             # (src, tag) → 行数
        "acute": collections.Counter(),            # (src, tag) → 带 U+0301 主重音
        "grave": collections.Counter(),            # (src, tag) → 带 U+0300 次重音
        "nomark": collections.Counter(),           # (src, tag) → 一个重音符都没有
        "cotags": collections.Counter(),           # §B 完整值域：共现的 tag
        "odd": collections.Counter(),              # §B 残渣字符
        "odd_eg": {},
        "formless": collections.Counter(),         # 候选行里 form 为空
        "kind": collections.Counter(),             # §B③ 判据分桶
        "kind_src": collections.Counter(),         # (kind, src)
        "kind_eg": collections.defaultdict(list),
        "rej_words": set(),                        # 被拒的行涉及的词形
        "rej_detail": collections.defaultdict(list),   # 词形 → [(串, 桶)]
        "cand_prov": collections.Counter(),        # (src, 来源) → 过判据的行数
        "noinfo": collections.Counter(),           # (src, 来源) → 与词头一模一样
        "noinfo_w": set(),                         # 这批涉及的词形
    }
    for src, p in SRC:
        t0 = time.time()
        n = 0
        for e in rd(p, limit):
            n += 1
            ok, skip, pos = criteria.entry_accept(e)
            if not ok:
                st["skipped"]["%s/%s" % (src, skip[0])] += 1
                continue
            w = e["word"]
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, w, pos, no, sub)
            refs.add(sref)
            st["accepted"][src] += 1
            word_of[sref] = w
            for f in (e.get("forms") or []):
                tags = f.get("tags") or []
                form = (f.get("form") or "").strip()
                prov = provenance(tags)
                claimed = prov in ("canonical", "stressed")
                if claimed:
                    st["rows"][(src, prov)] += 1
                    if not form:
                        st["formless"][(src, prov)] += 1
                        continue
                    # 🔴 主重音与次重音**分开数**：`has_stress` 只认 U+0301，
                    #    而俄语的复合词次重音用 U+0300（`Ко̀т-д’Ивуа́р`）。
                    if criteria.has_stress(form):
                        st["acute"][(src, prov)] += 1
                    if "̀" in form:
                        st["grave"][(src, prov)] += 1
                    if not criteria.has_any_stress(form):
                        st["nomark"][(src, prov)] += 1
                    for ct in tags:
                        if ct not in FIELD_TAGS:
                            st["cotags"][ct] += 1
                    for c in _odd_chars(form):
                        st["odd"][c] += 1
                        st["odd_eg"].setdefault(c, "%s → %s" % (w, form))
                elif not form:
                    continue
                # 判据分桶 —— **用 `criteria.stressed_spelling`，本文件不自己判**
                ok, kind, val = criteria.stressed_spelling(w, form)
                # 🔴🔴 **分桶只对「源头声称这是词头的拼写」的那批做**（canonical/stressed）。
                #    带语法标签的行被拒是**正常**的（它们是别的词形，本来就不等于词头），
                #    把它们也算进残渣桶，几百万条正当的变位会把真残渣淹掉
                #    （`[[residual-bucket-is-not-evidence]]` 的反面：桶**撑大**一次，缺陷也隐身一次）。
                if claimed:
                    st["kind"][kind] += 1
                    st["kind_src"][(kind, src)] += 1
                    if len(st["kind_eg"][kind]) < 10:
                        st["kind_eg"][kind].append(
                            "%-26s → %s%s" % (w, form, "" if val == form
                                              else "   ⇒ 修成 %s" % val))
                    if not ok:
                        st["rej_words"].add(w)
                        if len(st["rej_detail"][w]) < 4:
                            st["rej_detail"][w].append((form, kind))
                if not ok:
                    continue
                st["cand_prov"][(src, prov)] += 1
                if val == w:
                    # 与词头**一模一样** ⇒ 它一个字节的信息都不带。
                    # 🔴 不收，而且**要分开数**：读者页上「这个词的重音写法」印出
                    #    一个与词头无异的串，比空着更坏（`错比缺更伤权威`）。
                    #    ⚠️ 这一批里有合法的（含 ё／单音节），见 §D。
                    st["noinfo"][(src, prov)] += 1
                    st["noinfo_w"].add(w)
                    continue
                cand[sref].setdefault(val, prov)
        print("  · %-16s %9s 行  %5.1fs" % (src, format(n, ","), time.time() - t0),
              file=sys.stderr)
    return refs, cand, word_of, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="每份源只读前 N 行（**只用来调试，结论一律全量**）")
    a = ap.parse_args()
    lim = a.limit or None

    print("■ 俄语阶段 2 探针：重音层的落点  2026-10-08"
          + ("（--limit %d，非结论）" % lim if lim else "（全量）"))
    print("   判据版本 %s" % criteria.RULE_VER)

    refs, cand, word_of, st = scan(lim)

    c = sqlite3.connect(paths.DB)
    c.row_factory = sqlite3.Row

    # ══════════════════════════════════════════════════════════════════
    print("\n" + "═" * 78)
    print("§ 0 🔴 挂钩的证明：重算出来的 `src_ref` 与库里的是不是同一个集合")
    print("═" * 78)
    db_refs = set(r[0] for r in c.execute("SELECT src_ref FROM entry"))
    only_db = db_refs - refs
    only_scan = refs - db_refs
    print("  库里 entry        %9s" % format(len(db_refs), ","))
    print("  本次重算          %9s" % format(len(refs), ","))
    print("  库里有·重算没有   %9s" % format(len(only_db), ","))
    print("  重算有·库里没有   %9s" % format(len(only_scan), ","))
    if lim:
        print("  ⚠️ --limit 模式下两边本来就不该相等，这一节无意义")
    elif only_db or only_scan:
        print("  🔴🔴 **不相等 ⇒ 重音一挂上去就会整体错位。这一层不许往下做。**")
        for x in list(only_db)[:5]:
            print("     库里有：%s" % x)
        for x in list(only_scan)[:5]:
            print("     重算有：%s" % x)
    else:
        print("  ✅ **完全相等** ⇒ ① `criteria` §⑥ 的搬家没改意思（重构回归验证）；")
        print("     ② 重音层可以靠重算 `src_ref` 精确挂到 entry 上。")

    # ══════════════════════════════════════════════════════════════════
    print("\n" + "═" * 78)
    print("§ A ① 源头**声称**是词头拼写的行（canonical/stressed）")
    print("═" * 78)
    print("  %-16s %-10s %10s %10s %8s %9s %9s %7s"
          % ("源", "来源", "声称行", "主重音0301", "占比", "次重音0300", "无任何符", "空 form"))
    print("  " + "-" * 90)
    for src, _p in SRC:
        for t in FIELD_TAGS:
            n = st["rows"][(src, t)]
            if not n:
                continue
            print("  %-16s %-10s %10s %10s %7.2f%% %9s %9s %7s"
                  % (src, t, format(n, ","), format(st["acute"][(src, t)], ","),
                     100.0 * st["acute"][(src, t)] / n,
                     format(st["grave"][(src, t)], ","),
                     format(st["nomark"][(src, t)], ","),
                     format(st["formless"][(src, t)], ",")))
    print("\n  ⚠️ 主重音与次重音两列**会同时为真**（复合词 `Ко̀т-д’Ивуа́р` 两个都有），"
          "所以别把两列相加。")

    print("\n  ② 🔴 **过了判据的行**（剥重音后 ＝ 词头），按来源分 —— "
          "`语法标签`/`无标签` 这两列是第一版判据完全看不见的：")
    print("  %-16s %10s %10s %10s %10s"
          % ("源", "canonical", "stressed", "语法标签", "无标签"))
    print("  " + "-" * 62)
    PROV = ("canonical", "stressed", "语法标签", "无标签")
    for src, _p in SRC:
        row = [st["cand_prov"][(src, pv)] for pv in PROV]
        if not any(row):
            continue
        print("  %-16s %10s %10s %10s %10s"
              % (src, *[format(x, ",") for x in row]))
    print("  " + "-" * 62)
    print("  %-16s %10s %10s %10s %10s"
          % ("合计", *[format(sum(st["cand_prov"][(s2, pv)] for s2, _ in SRC), ",")
                       for pv in PROV]))

    print("\n  ③ 过了判据而**不带任何重音信息**的行（不收，分两个数见 §D）：%s 行"
          % format(sum(v for k, v in st["kind"].items()
                       if k.startswith("无需标注") or k.startswith("🔴 源头标坏")), ","))
    print("\n  跳过的行（没落成 entry，所以它的候选行也无处可挂）：")
    for k, v in sorted(st["skipped"].items(), key=lambda x: -x[1]):
        print("     %-24s %9s" % (k, format(v, ",")))

    # ══════════════════════════════════════════════════════════════════
    print("\n" + "═" * 78)
    print("§ B 完整值域 —— **无条件、不过滤**（2026-10-07 那一跤的闸）")
    print("═" * 78)
    print("  ① 与 canonical/stressed **共现**的其他 tag（全打，共 %d 种）："
          % len(st["cotags"]))
    for k, v in st["cotags"].most_common():
        print("     %-28s %9s" % (k, format(v, ",")))
    print("\n  ② 带重音拼写里**不该出现**的字符（西里尔/U+0301/空格/连字符之外，全打，共 %d 种）："
          % len(st["odd"]))
    if not st["odd"]:
        print("     （一个都没有）")
    for ch, v in st["odd"].most_common():
        print("     U+%04X %-3s %9s   例：%s"
              % (ord(ch), repr(ch)[1:-1], format(v, ","), st["odd_eg"][ch]))

    print("\n  ③ `criteria.stressed_spelling` 的分桶 —— **收的只有 ok 那两桶**：")
    tk = sum(st["kind"].values())
    for k, v in st["kind"].most_common():
        per = " ".join("%s:%s" % (criteria.SRC_SHORT[s], format(n, ","))
                       for (kk, s), n in sorted(st["kind_src"].items(),
                                                key=lambda x: -x[1])
                       if kk == k)
        print("\n     %-34s %9s  %6.2f%%   %s"
              % (k, format(v, ","), 100.0 * v / max(tk, 1), per))
        for x in st["kind_eg"][k]:
            print("        %s" % x)

    # ══════════════════════════════════════════════════════════════════
    print("\n" + "═" * 78)
    print("§ C 一个 entry 几个候选 —— 这决定 `is_primary` 要不要判据")
    print("═" * 78)
    per = collections.Counter()
    same_pos, diff_pos = 0, 0
    diff_eg, prov_mix = [], collections.Counter()
    for sref, vals in cand.items():
        per[len(vals)] += 1
        if len(vals) >= 2:
            # 🔴 多候选分两类，**而这一刀才是 `is_primary` 的关键**：
            #    字母串一定相同（判据保证了它们都等于词头），所以真问题是
            #    **重音位置是不是也相同**。相同 ⇒ 只是写法重复，随便挑一个都对；
            #    不同 ⇒ `замо́к`/`за́мок` 那种**辨义**对立，挑错一个就是印错。
            poss = {criteria.stress_position(v) for v in vals}
            if len(poss) == 1:
                same_pos += 1
            else:
                diff_pos += 1
                prov_mix[tuple(sorted(set(vals.values())))] += 1
                if len(diff_eg) < 15:
                    diff_eg.append((word_of[sref],
                                    [(v, vals[v]) for v in sorted(vals)]))
    tot = sum(per.values())
    print("  有候选的 entry  %s（占库里 entry 的 %.2f%%）"
          % (format(tot, ","), 100.0 * tot / max(len(db_refs), 1)))
    for k in sorted(per):
        print("     %d 个候选 %12s   %6.2f%%" % (k, format(per[k], ","),
                                               100.0 * per[k] / max(tot, 1)))
    m = same_pos + diff_pos
    if m:
        print("\n  ≥2 个候选的 %s 组里：" % format(m, ","))
        print("     重音**位置相同**（只是写法重复）%9s   %6.2f%%  ← 随便挑都对"
              % (format(same_pos, ","), 100.0 * same_pos / m))
        print("     重音**位置不同**（真的重音变体）%9s   %6.2f%%  ← 🔴 必须有判据挑主行"
              % (format(diff_pos, ","), 100.0 * diff_pos / m))
        print("\n     位置不同的那批，候选来自哪些来源的组合：")
        for k, v in prov_mix.most_common():
            print("        %-34s %8s" % ("＋".join(k), format(v, ",")))
        print("\n     样本：")
        for w, vs in diff_eg:
            print("        %-22s %s" % (w, " ｜ ".join(
                "%s〔%s〕" % (v, pv) for v, pv in vs)))

    # ══════════════════════════════════════════════════════════════════
    print("\n" + "═" * 78)
    print("§ D **不带任何重音信息**的行 —— 两个数分开：无需标注 ／ 源头标坏了")
    print("═" * 78)
    print("""  🔴🔴 这一批里有 2026-10-08 自己造出来的坑：`ok-修过游离组合符` 把
     `крем для бритья ́` 里那个**游离的重音符删掉**之后，剩下的串与词头一字不差。
     于是一条「源头标坏了」被静默修成了一条「看起来正常而没有信息」的行 ——
     印到读者页「这个词的重音写法」那一栏，它比空着更坏（**错比缺更伤权威**）。
  ⇒ `criteria.stressed_spelling` 的出口拒掉它们，而**分成两个标签**
     （分桶判据的家是 `criteria.stress_not_needed`，本文件不重写）：
       含 ё／单音节 ⇒ **本来就不需要重音符**，不是缺口
       多音节      ⇒ **源头标坏了**，是缺口
  ⚠️ `[[dont-say-source-lacks-what-we-skipped]]`：这两个数混成一个，
     「我们没抽」就会慢慢变成「源头没有」。
  ⚠️ 下面只统计源头**声称**是词头拼写的那批（canonical/stressed）；
     全库口径（拿「需要标注的词元」做分母）在重音闸 T10 与 `COVERAGE` 里。""")
    nd = {k: v for k, v in st["kind"].items()
          if k.startswith("无需标注") or k.startswith("🔴 源头标坏")}
    tot_nd = sum(nd.values())
    if not tot_nd:
        print("\n  🔴🔴 **一条都没有** —— 这不可能（实测 291 行）。"
              "多半是 `criteria` 的标签名改了而这里的前缀没跟上 ——"
              "**这一节就变成了永远空过的检查，比没有检查更坏**。")
    for k, v in sorted(nd.items(), key=lambda x: -x[1]):
        print("\n     %-46s %8s  %6.2f%%" % (k, format(v, ","),
                                              100.0 * v / max(tot_nd, 1)))
        for x in st["kind_eg"][k][:6]:
            print("        %s" % x)

    # ══════════════════════════════════════════════════════════════════
    print("\n" + "═" * 78)
    print("§ E 覆盖率 —— 三个口径，**分词元与屈折形**")
    print("═" * 78)
    rows = c.execute("SELECT word, is_lemma FROM dict").fetchall()
    lemma = {r["word"] for r in rows if r["is_lemma"]}
    allw = {r["word"] for r in rows}
    infl = allw - lemma
    cov_en, cov_tag, cov_all = set(), set(), set()
    for sref, vals in cand.items():
        w = word_of[sref]
        cov_all.add(w)
        if sref.startswith("kk-en:"):
            cov_en.add(w)
        if any(pv in ("canonical", "stressed") for pv in vals.values()):
            cov_tag.add(w)
    print("  词元 %s ／ 屈折形 %s ／ 合计 %s"
          % (format(len(lemma), ","), format(len(infl), ","), format(len(allw), ",")))
    for name, sset in (("① 只用 en 版", cov_en),
                       ("② 七源，只收 canonical/stressed（第一版判据）", cov_tag),
                       ("③ 七源，判据放宽后（本层实际收法）", cov_all)):
        print("\n  %s：盖到 %s 个词形" % (name, format(len(sset), ",")))
        print("     词元   %9s   覆盖 %6.2f%%"
              % (format(len(sset & lemma), ","),
                 100.0 * len(sset & lemma) / max(len(lemma), 1)))
        print("     屈折形 %9s   覆盖 %6.2f%%"
              % (format(len(sset & infl), ","),
                 100.0 * len(sset & infl) / max(len(infl), 1)))
        print("     不在 dict 里的 %s   ← 挂不上（应为 0）"
              % format(len(sset - allw), ","))
    print("\n  🔴 ②→③ 判据放宽**多盖词元 %s 个**（+%.2f 个百分点）"
          % (format(len((cov_all - cov_tag) & lemma), ","),
             100.0 * len((cov_all - cov_tag) & lemma) / max(len(lemma), 1)
             - 0))
    print("     ①→③ 跨版并集**多盖词元 %s 个**"
          % format(len((cov_all - cov_en) & lemma), ","))

    # 被拒的代价要量**落点**：不是「拒了多少行」，而是
    # 「有多少个词形因为被拒而**一条重音都没有**」。
    rej = st["rej_words"]
    lost = rej - cov_all
    print("\n  源头声称是词头拼写而被拒的行涉及 %s 个词形；其中**一条都没收到**的 %s 个"
          % (format(len(rej), ","), format(len(lost), ",")))
    print("     真正丢掉的里，是词元的 %s 个 ⇒ 占词元 %.4f%%"
          % (format(len(lost & lemma), ","),
             100.0 * len(lost & lemma) / max(len(lemma), 1)))
    for w in sorted(lost)[:12]:
        print("        %-30s %s" % (w, " ｜ ".join(
            "%s〔%s〕" % (f, k) for f, k in st["rej_detail"][w])))

    # ══════════════════════════════════════════════════════════════════
    print("\n" + "═" * 78)
    print("§ F 欠账 R13：7 个**词头自己带重音符**的词形，源头怎么说")
    print("═" * 78)
    r13 = [r["word"] for r in c.execute(
        "SELECT word FROM dict WHERE word LIKE ?", ("%" + criteria.STRESS + "%",))]
    print("  库里词头含 U+0301 的：%d 个 → %s" % (len(r13), " ｜ ".join(sorted(r13))))
    for w in sorted(r13):
        bare = criteria.strip_stress(w)
        hit = c.execute("SELECT id, is_lemma, pos, entry_type FROM dict WHERE word=?",
                        (bare,)).fetchone()
        mine = [(k, v) for k, v in cand.items() if word_of[k] == w]
        print("\n     %-16s 无重音版在 dict 里：%s"
              % (w, ("在（id=%d, %s）" % (hit["id"], hit["pos"])) if hit else "**不在**"))
        print("        它自己的候选行：%s"
              % (mine[0][1] if mine else "（没有）"))
        if hit:
            bm = [(k, v) for k, v in cand.items() if word_of[k] == bare]
            print("        无重音版的候选行：%s" % (bm[0][1] if bm else "（没有）"))

    print("\n■ 完。结论一律写进 `docs/RU_PLAN.md`，**别留在这份输出里**。")


if __name__ == "__main__":
    main()
