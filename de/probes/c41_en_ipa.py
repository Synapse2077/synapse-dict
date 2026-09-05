#!/usr/bin/env python3
"""收尾单 C41 —— **英文版能不能把那 29,329 个读者看不见的音标补回来**。2026-09-05。

═══ C41 到今天为止的结论，有一个洞 ═══
账上写着：那 29,329 个词形「`dict.ipa` 有值、`pronunciation` 没有行」，
而 `dict.ipa` 与 `pronunciation` 在 **39% 上实质分歧、且一面倒是 `dict.ipa` 错**
（`Arabisch` 重音位置、`extra` 带音节点、`ʀ` 不用 `ʁ`）⇒ **有意不搬**。

🔴 **那个 39% 回答的不是这一步要问的问题。** 它比的是
   「**七月那次收进来的东西** vs 阶段 4 收的德语版」，于是把两件事混成了一个数：

       (a) **英文版的德语音标质量差**        ← 若成立，补回来就是拿错换缺
       (b) **七月那次收得糙**（无过滤、无 provenance、疑似经过 `word.lower()` 折叠）
                                            ← 若成立，差的是我们的手艺不是源头

   两件事的处置**完全相反**：(a) 该放弃，(b) 该**重收**。
   而这 29,329 个词形全部 `entry.src = en-edition`、`ipa_src` 100% 是 `unknown`
   —— 它们本来就是英文版给的，只是七月那条路没有留下任何来源。

═══ 本探针只回答三个问题，都用**已经存在的判据**，不新写一份 ═══
  ① **质量**：拿我们信的那一层（`pronunciation`，阶段 4 从德语版收、带 provenance）
     当真值，量**今天重收的英文版**与它差在哪 —— 用 `ipa_conventions.BUCKETS`
     的消去法分桶，**记法约定归记法约定，音段分歧归音段分歧**，不混成一个百分比。
  ② **落点**（`[[measure-landing-not-source]]`）：英文版对那 29,329 个词形，
     过完阶段 4 的四道过滤之后**还剩多少**。不是问英文版有多少音标。
  ③ **忠实度**：七月的 `dict.ipa` 与今天重收的英文版**逐字相等吗**。
     不等的那部分就是 (b) 的证据 —— 差异出在我们这一侧。

🔴 **过滤器 import 阶段 4 那一份**（`bare` / `truncated` / `looks_like_spelling` /
   SAMPA 判据），不手抄。手抄过一次的代价见 `--drop-cols` 那轮：我自己写的
   「按第一个汉字切」报了 43 条假红，而真的切分器就在隔壁文件里。

⚠️ 本脚本**只读**，不写库、不下载、不调模型。

跑（在 de/ 目录下）：
    python3 -u probes/c41_en_ipa.py --limit 300000   # 先计时
    python3 -u probes/c41_en_ipa.py
"""
import argparse
import json
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

import paths                                                        # noqa: E402
from harvest_pronunciation import bare, truncated, looks_like_spelling   # noqa: E402
from ipa_conventions import (BUCKETS, bucket, _nfc, variants,       # noqa: E402
                             overmerge, full_key,
                             d_syllabic, d_dorsal, d_diph, d_devoice)

f = lambda n: format(n, ",")

# C41 集合的判据。**与回归闸 D6 / 收尾单 C41 说的是同一件事**：
# 有真义项（读者点得进去）、`pronunciation` 没有行（页面上没有音标）、`dict.ipa` 有值。
Q_C41 = ("SELECT d.id, d.word, d.ipa FROM dict d "
         " WHERE EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id) "
         "   AND NOT EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=d.id) "
         "   AND TRIM(COALESCE(d.ipa,''))<>''")


def scan_en(keep, limit=0):
    """扫英文版德语切片 → ({词形: set(裸音标)}, stat)。**过滤器与阶段 4 同一份。**"""
    out, stat = defaultdict(set), Counter()
    with open(paths.KK, encoding="utf-8") as fh:
        for n, line in enumerate(fh):
            if limit and n >= limit:
                break
            if '"sounds"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            if e.get("lang_code") != "de":
                stat["非德语条目"] += 1
                continue
            w = e.get("word") or ""
            if w not in keep:
                stat["词形不在库里"] += 1
                continue
            for s in e.get("sounds") or []:
                raw = s.get("ipa")
                if not raw:
                    continue
                stat["源头 ipa 条数"] += 1
                tags = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
                if any("SAMPA" in t.upper() for t in tags):
                    stat["🔴 丢弃：X-SAMPA"] += 1
                    continue
                v = bare(raw)
                if not v or truncated(v, w):
                    stat["🔴 丢弃：含省略号（占位符或半截）"] += 1
                    continue
                if looks_like_spelling(v, w):
                    stat["🔴 丢弃：音节切分/拼写冒充音标"] += 1
                    continue
                out[w].add(_nfc(v))
                stat["收下"] += 1
    return out, stat


def classify(A, B):
    """→ (一致?, 桶名)。A/B 是两组裸音标。**任意一条逐字相同就算一致**（同 C22 口径）。

    ⚠️ 「逐字相同」把括号里的可选成分展开后再比 —— `ˈapfalˌ(ʔ)aɪ̯mɐ` 与
       `ˈapfalˌʔaɪ̯mɐ` 是同一条数据的两种写法，不是两条数据。
    """
    if {v for a in A for v in variants(a)} & {v for b in B for v in variants(b)}:
        return True, None
    best, name = 99, None
    for a in A:
        for b in B:
            nm = bucket(a, b)
            idx = next((i for i, (n, _) in enumerate(BUCKETS) if n == nm), 98)
            if idx < best:
                best, name = idx, nm
    return False, name


def report(title, pairs, note=""):
    """pairs = [(word, A, B)]，A 是我们的/旧的，B 是英文版的。"""
    n = max(len(pairs), 1)
    agree, c, ex = 0, Counter(), {}
    for w, A, B in pairs:
        ok, nm = classify(A, B)
        if ok:
            agree += 1
            continue
        c[nm] += 1
        ex.setdefault(nm, (w, sorted(A)[0], sorted(B)[0]))
    print("\n■ %s  可比 %s %s" % (title, f(len(pairs)), note))
    print("   ✅ 逐字有交集（无分歧）        %8s  %5.1f%%" % (f(agree), 100.0 * agree / n))
    for k, v in sorted(c.items()):
        print("   %-34s %8s  %5.1f%%" % (k, f(v), 100.0 * v / n))
        w, a, b = ex[k]
        print("        %-20s 我们=%-24s 英文版=%s" % (w[:20], a[:24], b[:24]))
    return agree, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只读前 N 行（计时用）")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    keep = {w for (w,) in con.execute("SELECT word FROM dict")}
    c41 = {w: (i, ipa) for i, w, ipa in con.execute(Q_C41)}
    # 真值层：阶段 4 从德语版收的，**这是我们信的那一份**
    trust = defaultdict(set)
    for w, ipa in con.execute("SELECT d.word, p.ipa FROM pronunciation p "
                              "JOIN dict d ON d.id=p.word_id WHERE p.src='de-edition'"):
        trust[w].add(_nfc(ipa))
    # 七月那一列，只取**同时有 pronunciation** 的，用来复现账上那个 39%
    july = {w: _nfc(ipa) for w, ipa in con.execute(
        "SELECT word, ipa FROM dict WHERE TRIM(COALESCE(ipa,''))<>''")}
    con.close()
    print("■ 库内词形 %s ／ C41 集合 %s ／ 阶段 4 真值层词形 %s ／ 七月遗留列 %s"
          % (f(len(keep)), f(len(c41)), f(len(trust)), f(len(july))))

    # ── 闸⓪ 过度合并：新消去器不许把两条本来不同的德语音标抹成一样 ──────────
    # 🔴 先跑这道闸，**再看一致率**。反过来就是拿判据去凑数字
    #    （`[[proxy-metric-gets-optimized]]`：一致率是代理不是目的）。
    print("\n═══ 闸⓪ 过度合并（第二批消去器，2026-09-05 新加）═══")
    vals = sorted({v for s in trust.values() for v in s})
    keys = {v: full_key(v) for v in vals}
    print("   受检值域：阶段 4 真值层里 %s 条互不相同的音标" % f(len(vals)))
    for fn, nm in ((d_syllabic, "n̩ / ən"), (d_dorsal, "x / χ"),
                   (d_diph, "ɔɪ / ɔʏ"), (d_devoice, "z̥ / s、tʰ / t")):
        grew, ex = overmerge(vals, fn, keys)
        print("   %-16s 加上它 → 多合并 %5s 组%s" % (nm, f(grew), "" if grew else "  ✓"))
        for g in ex[:4]:
            print("        %s" % "  ≡  ".join(g))

    print("\n■ 扫英文版德语切片…")
    en, stat = scan_en(keep, a.limit)
    for k, v in stat.most_common():
        print("   %-36s %s" % (k, f(v)))
    print("   ⇒ 过滤后带音标的词形 %s" % f(len(en)))

    # ── ① 质量：今天重收的英文版 vs 我们信的那一层 ─────────────────────
    both = sorted(set(en) & set(trust))
    report("① 质量审计：英文版 vs 阶段 4 德语版（真值）", [(w, trust[w], en[w]) for w in both],
           "← 这一栏回答「英文版能不能信」")

    # ── ② 落点：英文版对 C41 那批还剩多少 ─────────────────────────────
    hit = [w for w in c41 if w in en]
    print("\n■ ② 落点：C41 的 %s 个词形，英文版过完四道过滤后还能补 %s（%.1f%%）"
          % (f(len(c41)), f(len(hit)), 100.0 * len(hit) / max(len(c41), 1)))

    # ── ③ 忠实度：七月的 dict.ipa 是不是英文版的忠实拷贝 ────────────────
    report("③ 忠实度：七月 `dict.ipa` vs 今天重收的英文版（限 C41 集合）",
           [(w, {july[w]}, en[w]) for w in hit if w in july],
           "← 不一致的部分说明差异出在**我们这一侧**")
    report("③b 忠实度：七月 `dict.ipa` vs 今天重收的英文版（有 pronunciation 的那批）",
           [(w, {july[w]}, en[w]) for w in both if w in july])

    # ── 账上那个 39% 的复现：七月列 vs 真值层 ──────────────────────────
    report("④ 复现账上那个数：七月 `dict.ipa` vs 阶段 4 德语版",
           [(w, {july[w]}, trust[w]) for w in sorted(set(july) & set(trust))],
           "← 账上说 39% 实质分歧，这里看它到底是什么")

    print("\n── C41 落点样本 20 条 ──")
    for w in sorted(hit)[:20]:
        print("   %-24s 七月=%-24s 英文版=%s"
              % (w[:24], (july.get(w) or "")[:24], sorted(en[w])[0][:24]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
