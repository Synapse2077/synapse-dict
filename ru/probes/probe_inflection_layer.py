#!/usr/bin/env python3
"""阶段 3 探针：**屈折层的落点**。ru，2026-10-08。

═══ 这一层要回答的问题，和阶段 2 不是一个 ═══
阶段 2 收的是「**词头自己**的带重音拼写」（剥重音后 ＝ 词头）。
阶段 3 收的是「这个词元的**变位表**」—— 也就是 `forms` 里**剩下的那一大堆**：
ru 版 439 万行、en 版 291 万行。两层共用一个 `forms` 字段，而判据正好互补。

🔴 `inflection.entry_id` 的语义是 **「原形的那个 entry」**（照 it 阶段 8 定死的），
   不是「这个屈折形自己的 entry」—— 所以 ru 版那条路（词元页带变位表）
   直接挂得上，而 en 版那条路（屈折形页带 `form_of` 指针）是**反向**的，
   要把指针目标解析回词元。`PLAYBOOK` 四：**2b / 2c 两条反向的路必须都走**。

═══ 判据纪律：本轮**先量后写** ═══
🔴🔴 2026-10-07 栽过一跤：我拿一张**猜的** `ASPECT_WORDS` 当值域，
`perfective` 几乎没有而真名是 `perfect`，于是两家外审对一个**不存在的现象**
各给了一套有说服力的归因（`[[consult-two-models-on-rules]]`）。
⇒ §A/§B 是**完整值域、无条件、不过滤、不截断**：
  · §A 所有 `forms` 行的 tag 值域（逐个全打）
  · §B 所有 `forms` 行的**字符**值域（俄语字母/重音符/空格/连字符之外的，逐个全打带样本）
⚠️ 并且**不许用 `[:8]` 之类的截断** —— `probe_schema.py` 只印了 `etymology_number`
   值域的前 8 个，我于是把「值域是 0–7」写进了计划表，而真值里有 `'1.1'`，
   建库当场崩（那次是 `raise` 救的）。

═══ 已知会咬人的两条（欠账 R8/R9），而**其中一条的原文判据是错的** ═══
R8 ✅ 真的在：ru 版变位表带源头表格标记 —— `*` / `^△` / `†`（实测 12 万行里 7,253 条）。
   ⚠️ 还有一种原文没提的形状：**一个字段里挤了多个词形** ——
      `быть → есть (есь^†, еси́^†)`。
R9 🔴 **原文写「按字母表挡掉 ѣ/і/ѳ/词尾ъ」，而那是拿形式代理当内容判据**：
   en 版把改革前正字法**明确标成** `['dated','genitive','plural']`
   （`собака → соба́къ`，20 万行里 14,726 条），zh-t 标成 `['alternative']`（1,322 条），
   而 **ru 版一条都没有（0 行）** —— 按字母挡等于扔掉源头已经标好的历史词形，
   且在主源上一条也挡不到。⇒ 判据要问**源头的 tag**，不问字母。§C 量它。
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
from pipeline.build import SRC, rd                              # noqa: E402

# 阶段 2 已经收走的那两个 tag（词头自己的带重音拼写）
STAGE2_TAGS = ("canonical", "stressed")


def odd_chars(s):
    """俄语屈折形里**不该出现**的字符。用来把残渣逼出来的度量，不是清洗白名单。"""
    out = []
    for c in s:
        if c in (" ", "-", criteria.STRESS, "̀"):
            continue
        if dbtool.is_cyrillic(c):
            continue
        out.append(c)
    return out


def scan(limit=None):
    ref = criteria.SrcRef()
    refs = set()
    st = {
        "lines": collections.Counter(),
        "forms": collections.Counter(),          # (src) → forms 行总数
        "tags": collections.defaultdict(collections.Counter),   # src → tag → n
        "tagless": collections.Counter(),
        "stage2": collections.Counter(),
        "odd": collections.Counter(),            # 字符 → n（全源合计）
        "odd_src": collections.defaultdict(collections.Counter),
        "odd_eg": {},
        "per_entry": collections.Counter(),      # 一个 entry 几行屈折
        "dup": collections.Counter(),            # (entry, form, tags) 重复
        "dated": collections.Counter(),          # src → 带 dated/alternative 的行
        "ptr": collections.Counter(),            # src → 指针条目数
        "ptr_pairs": collections.defaultdict(set),   # src → {(屈折形, 词元)}
        "ru_pairs": set(),                       # ru 版变位表给出的 (屈折形, 词元)
        # 🔴 **全部版的变位表并集** —— 第一版只拿 ru 版比，而落库的表来自六个版
        #    ⇒ 那样会**高估指针路的增量**（我的度量比问题窄，当天第二次）。
        "all_pairs": set(),
        "paren": collections.Counter(),          # 一个字段挤多个词形
        "paren_eg": [],
        "lemma_with_table": collections.defaultdict(set),   # src → {词元}
        "kind": collections.Counter(),           # 判据分桶
        "kind_src": collections.Counter(),
        "kind_eg": collections.defaultdict(list),
        "out_rows": collections.Counter(),       # src → 真正会落库的行数
        "out_lemma": collections.defaultdict(set),
        "marked": collections.Counter(),         # src-mark:* 的分布
        "ptr_raw": collections.defaultdict(set),
    }
    for src, p in SRC:
        t0 = time.time()
        n = 0
        for e in rd(p, limit):
            n += 1
            ok, _skip, pos = criteria.entry_accept(e)
            if not ok:
                continue
            st["lines"][src] += 1
            w = e["word"]
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, w, pos, no, sub)
            refs.add(sref)
            # ── 指针路（en 版的主力）：屈折形页 → 词元 ──
            isf, _via = criteria.is_inflected_form(e)
            if isf:
                tgt = criteria.pointer_target(e)
                if tgt:
                    st["ptr"][src] += 1
                    st["ptr_raw"][src].add((w, tgt))
            # ── 变位表路（ru 版的主力）：词元页 → 各个屈折形 ──
            seen = set()
            for f in (e.get("forms") or []):
                tags = f.get("tags") or []
                form = (f.get("form") or "").strip()
                st["forms"][src] += 1
                if set(tags) & set(STAGE2_TAGS):
                    st["stage2"][src] += 1
                    continue
                if not tags:
                    st["tagless"][src] += 1
                for t in tags:
                    st["tags"][src][t] += 1
                if not form:
                    continue
                if {"dated", "alternative", "archaic", "obsolete"} & set(tags):
                    st["dated"][src] += 1
                if "(" in form or "," in form:
                    st["paren"][src] += 1
                    if len(st["paren_eg"]) < 12:
                        st["paren_eg"].append("%-14s → %s  %s" % (w, form, tags[:3]))
                for c in odd_chars(form):
                    st["odd"][c] += 1
                    st["odd_src"][c][src] += 1
                    st["odd_eg"].setdefault(c, "%s → %s  %s" % (w, form, tags[:3]))
                key = (form, "|".join(sorted(tags)))
                if key in seen:
                    st["dup"][src] += 1
                seen.add(key)
                st["lemma_with_table"][src].add(w)
                # ── 判据分桶：**用 `criteria.inflection_rows`，本文件不自己判** ──
                kind, rows = criteria.inflection_rows(w, form, tags)
                st["kind"][kind] += 1
                st["kind_src"][(kind, src)] += 1
                if len(st["kind_eg"][kind]) < 8:
                    st["kind_eg"][kind].append(
                        "%-16s → %-28s %s" % (w, form[:28], tags[:3]))
                for bare, stressed, extra in rows:
                    st["out_rows"][src] += 1
                    st["out_lemma"][src].add(w)
                    for x in extra:
                        st["marked"][x] += 1
                    st["all_pairs"].add((bare, w))
                    if src == "ru-edition":
                        st["ru_pairs"].add((bare, w))
            if seen:
                st["per_entry"][min(len(seen), 60)] += 1
        print("  · %-16s %9s 行  %5.1fs" % (src, format(n, ","),
                                            time.time() - t0), file=sys.stderr)
    return refs, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    lim = a.limit or None
    print("■ 俄语阶段 3 探针：屈折层的落点  2026-10-08"
          + ("（--limit %d，非结论）" % lim if lim else "（全量）"))
    print("   判据版本 %s" % criteria.RULE_VER)
    refs, st = scan(lim)
    c = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    print("\n" + "═" * 78)
    print("§ 0 挂钩的证明：重算的 `src_ref` 与库里 `entry.src_ref` 是不是同一个集合")
    print("═" * 78)
    db = set(r[0] for r in c.execute("SELECT src_ref FROM entry"))
    print("  库里 %s ／ 重算 %s ／ 库有·算没有 %s ／ 算有·库没有 %s"
          % (format(len(db), ","), format(len(refs), ","),
             format(len(db - refs), ","), format(len(refs - db), ",")))
    if lim:
        print("  ⚠️ --limit 下这一节无意义")
    elif db == refs:
        print("  ✅ 完全相等 ⇒ 屈折行可以按 `src_ref` 精确挂到「原形的那个 entry」上")
    else:
        print("  🔴🔴 **不相等，这一层不许往下做**")

    print("\n" + "═" * 78)
    print("§ A 规模：`forms` 行怎么分（阶段 2 已收走的 ／ 带语法标签的 ／ 无标签）")
    print("═" * 78)
    print("  %-16s %10s %12s %12s %10s %10s"
          % ("源", "可落库行", "forms 行", "阶段2已收", "无标签", "有变位表的词"))
    print("  " + "-" * 76)
    for src, _p in SRC:
        if not st["forms"][src]:
            continue
        print("  %-16s %10s %12s %12s %10s %10s"
              % (src, format(st["lines"][src], ","), format(st["forms"][src], ","),
                 format(st["stage2"][src], ","), format(st["tagless"][src], ","),
                 format(len(st["lemma_with_table"][src]), ",")))

    print("\n" + "═" * 78)
    print("§ B 🔴 **完整 tag 值域，无条件、不过滤、不截断**")
    print("═" * 78)
    allt = collections.Counter()
    for src in st["tags"]:
        allt.update(st["tags"][src])
    print("  合计 %d 种 tag。按源分列（空＝这一版没用过这个 tag）：\n" % len(allt))
    srcs = [s for s, _ in SRC if st["tags"][s]]
    print("  %-26s %10s  %s" % ("tag", "合计", "  ".join("%-9s" % s[:9] for s in srcs)))
    print("  " + "-" * (40 + 11 * len(srcs)))
    for t, v in allt.most_common():
        cells = "  ".join("%-9s" % (format(st["tags"][s][t], ",") if st["tags"][s][t]
                                    else "·") for s in srcs)
        print("  %-26s %10s  %s" % (t, format(v, ","), cells))

    print("\n" + "═" * 78)
    print("§ C 🔴 **完整字符值域**：屈折形里不该出现的字符，逐个全打带样本")
    print("═" * 78)
    if not st["odd"]:
        print("  （一个都没有）")
    for ch, v in st["odd"].most_common():
        per = " ".join("%s:%s" % (criteria.SRC_SHORT[s], format(n, ","))
                       for s, n in st["odd_src"][ch].most_common())
        print("  U+%04X %-3s %10s  %-26s 例：%s"
              % (ord(ch), repr(ch)[1:-1], format(v, ","), per, st["odd_eg"][ch]))

    print("\n  一个字段里挤了多个词形（含 `(` 或 `,`）：")
    for src, _p in SRC:
        if st["paren"][src]:
            print("     %-16s %10s" % (src, format(st["paren"][src], ",")))
    for x in st["paren_eg"]:
        print("        %s" % x)

    print("\n  源头**明确标成历史/异体**的行（`dated`/`alternative`/`archaic`/`obsolete`）：")
    for src, _p in SRC:
        if st["dated"][src]:
            print("     %-16s %10s" % (src, format(st["dated"][src], ",")))
    print("  🔴 R9 的原文判据（按字母挡 ѣ/і/ѳ/ъ）**问的是形式**，而源头已经用 tag "
          "说清楚了 —— 判据要问 tag。")

    print("\n" + "═" * 78)
    print("§ C′ 🔴 `criteria.inflection_rows` 的分桶 —— **收的只有 `ok` 那一桶**")
    print("═" * 78)
    tk = sum(st["kind"].values())
    for k, v in st["kind"].most_common():
        per = " ".join("%s:%s" % (criteria.SRC_SHORT[s], format(n, ","))
                       for (kk, s), n in sorted(st["kind_src"].items(),
                                                key=lambda x: -x[1]) if kk == k)
        print("\n  %-42s %10s  %6.2f%%   %s"
              % (k, format(v, ","), 100.0 * v / max(tk, 1), per))
        for x in st["kind_eg"][k][:5]:
            print("     %s" % x)
    print("\n  真正会落库的行（拆格之后，所以可能比 `ok` 的行数多）：")
    tot_out = 0
    for src, _p in SRC:
        if st["out_rows"][src]:
            tot_out += st["out_rows"][src]
            print("     %-16s %12s 行   %8s 个词"
                  % (src, format(st["out_rows"][src], ","),
                     format(len(st["out_lemma"][src]), ",")))
    print("     %-16s %12s 行" % ("合计", format(tot_out, ",")))
    print("\n  源头标过记号的行（落库时进 `tags`，命名空间 `src-mark:`）：")
    for k, v in st["marked"].most_common():
        print("     %-18s %10s" % (k, format(v, ",")))

    print("\n" + "═" * 78)
    print("§ D 一个 entry 几行屈折 ／ 源头自己的重复行")
    print("═" * 78)
    tot = sum(st["per_entry"].values())
    acc = 0
    for k in sorted(st["per_entry"]):
        acc += st["per_entry"][k]
        if k in (1, 2, 3, 5, 10, 20, 30, 40, 50, 60) or st["per_entry"][k] > tot * 0.05:
            print("     %3s 行 %12s   累计 %6.2f%%"
                  % (k if k < 60 else "≥60", format(st["per_entry"][k], ","),
                     100.0 * acc / max(tot, 1)))
    print("\n  同一 entry 内 (form, tags) 完全重复的行：")
    for src, _p in SRC:
        if st["dup"][src]:
            print("     %-16s %10s" % (src, format(st["dup"][src], ",")))

    print("\n" + "═" * 78)
    print("§ E 两条反向的路：ru 版变位表 ／ en 版 `form_of` 指针，各给多少、重叠多少")
    print("═" * 78)
    for src, _p in SRC:
        if st["ptr"][src]:
            print("  %-16s 指针条目 %9s   (屈折形,词元) 对 %9s"
                  % (src, format(st["ptr"][src], ","),
                     format(len(st["ptr_pairs"][src]), ",")))
    # 🔴 指针目标要**按判据解析**再比。第一版拿源头原样去查 `dict`，报出
    #    「只有 24.27% 在 dict 里」—— 而真因是 **91.81% 的目标带重音符**，
    #    那个数是**我的度量错**（`[[measure-landing-not-source]]`）。
    words = {r[0] for r in c.execute("SELECT word FROM dict")}
    norms = collections.defaultdict(list)
    for r in c.execute("SELECT word_norm, word FROM dict"):
        norms[r[0]].append(r[1])
    how_hit = collections.Counter()
    for s in st["ptr_raw"]:
        for f, tgt in st["ptr_raw"][s]:
            res = None
            for k, how in criteria.pointer_lookup_keys(tgt):
                if k in words:
                    res, hw = k, how
                    break
                if how.startswith("归一") and norms.get(k):
                    res, hw = norms[k][0], how + "→word_norm"
                    break
            how_hit[hw if res else "🔴 怎么都对不上"] += 1
            if res:
                st["ptr_pairs"][s].add((f, res))
    print("\n  指针目标**按 `criteria.pointer_lookup_keys` 解析**之后，靠哪条路对上：")
    tp = sum(how_hit.values())
    for k, v in how_hit.most_common():
        print("     %-28s %10s   %6.2f%%" % (k, format(v, ","), 100.0 * v / max(tp, 1)))
    allptr = set()
    for s in st["ptr_pairs"]:
        allptr |= st["ptr_pairs"][s]
    for name, rp in (("只拿 ru 版的变位表比（**这个口径太窄**）", st["ru_pairs"]),
                     ("拿**全部版**的变位表并集比（决策看这个）", st["all_pairs"])):
        print("\n  %s" % name)
        print("     变位表给出的 (屈折形,词元) 对   %s" % format(len(rp), ","))
        print("     指针路给出的                   %s" % format(len(allptr), ","))
        print("     两条路**都给**的               %s   %6.2f%%"
              % (format(len(rp & allptr), ","),
                 100.0 * len(rp & allptr) / max(len(allptr), 1)))
        print("     🔴 只有指针路给的              %s   ← 不走这条路就是这么多白丢"
              % format(len(allptr - rp), ","))


    print("\n" + "═" * 78)
    print("§ F 覆盖率的上界：有变位表的词元 / 词元总数")
    print("═" * 78)
    lem = {r[0] for r in c.execute("SELECT word FROM dict WHERE is_lemma=1")}
    # 🔴 分母要用**真正会落库的词**，不是「`forms` 字段非空的词」——
    #    pl 版那 20,776 个「有 forms 行的词」**整个是拉丁转写**，一条屈折形都没有。
    cov = set()
    for s in st["out_lemma"]:
        cov |= st["out_lemma"][s]
    tbl = set(cov)
    cov |= {t for _f, t in allptr}
    print("  词元 %s" % format(len(lem), ","))
    print("  变位表路盖到的词元 %s （%.2f%%）"
          % (format(len(tbl & lem), ","), 100.0 * len(tbl & lem) / max(len(lem), 1)))
    print("  两条路并集盖到的   %s （%.2f%%）"
          % (format(len(cov & lem), ","), 100.0 * len(cov & lem) / max(len(lem), 1)))
    print("\n■ 完。结论写进 `docs/RU_PLAN.md`。")


if __name__ == "__main__":
    main()
