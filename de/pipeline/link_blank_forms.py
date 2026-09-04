#!/usr/bin/env python3
"""阶段 2d：把**空白页**接回它的词头 —— 2c 两条判据够不着的那一批。de 版，2026-09-04。

═══ 这一步是回归闸逼出来的 ═══
阶段 7 建回归闸时 B5「空白页」报红 **67,315（5.6%）**。
计划表阶段 2c 那行写的是「德语版也给不出释义的 67,318 是**真残差**」——
扫一遍 dump 发现**只对三分之二成立**：其中 **22,196（33.0%）源头的 `forms` 里
明明白白给了归属**，而且父词沿 `inflection.base` 链走下去 **98.7%** 能落到有义项的词上。
⇒ 「真残差」是 45,119，不是 67,315。

⚠️ **对照 pt**：pt 有 2c/2d/2e/2f 四步补链、每一步都是发现上一步够不着才有的
（`[[pt-dict-pipeline]]`）。de 的 2c 一步就到 13.7%，所以我当时以为不需要 2d ——
**这个判断是错的，而且它错在「我没量，我推」**。

═══ 🔴🔴 两个洞，根因是同一件事：**一条判据被用在了它没打算回答的问题上** ═══

① **`clean_form` → `is_single_form`（不含空格、不含 `/`）挡掉 1,200 条**
   那条判据是为「**该不该把这个单元格收成一个新词形**」设计的，
   理由是 `ich werde kooperieren` 是小句不是词形 —— 对。
   但 2c 拿它来判「**已经在库里的词头该不该连线**」：`im voraus`、`sich bedienen`、
   `G. m. b. H.` 早就是德语版的独立词头、有自己的页面，源头也明说它们是谁的异体，
   拒绝它们只让那些页面空着。
   ⇒ 连线时判据换成**「这个串在不在 dict 里」** —— 它有页面，就有资格被连上。
   ⚠️ **同一个坑本文件里已经有前科**：`clean_head` 的注释写着
      「第一版把 `is_single_form` 同时用在了顶层和 forms 上，丢掉 82,682 条」。
      **这是第三次。** 判据要问的永远是「它当初为了回答哪个问题」
      （`[[criteria-narrower-than-you-think]]`）。

② **「纯指针页整页不读」挡掉 21,685 条**
   2c 那条规则有真实来历：变形页的 forms 表列的是**兄弟形式**，
   照读会写出 `Epigrammes → Epigramms 变形`，两个都是变格形谁也不是原形。
   但它把两类东西合并处理了 —— 纯指针页的 forms 表里同时躺着：
       · **这一页词头自己的异体拼写**  `Weissruthenen → Weißruthenen`（瑞士 ss 拼写）
                                      `seyend → seiend`（1901 年前正字法）
                                      `Deiner → deiner`
       · **兄弟变格形**              `Bittens → Bitten`（都是 Bitte 的格形式）
                                      `Zahnarzthelfer → Zahnarzthelferin`
   ⇒ 判据从「整页不读」收窄成「**这一条是不是异体写法**」，
     而 tags 恰好把两类分得开（实测分布见文件末）。

═══ 判据：什么叫「异体写法」═══
**按含义**：这个 form 与页面词头是「**同一个词的两种写法**」，
不是「同一个词的两个语法形式」。落到 tags 上：
  · 含 `alternative` 或 `variant`                     → 是
  · 或 tags 全部落在正字法/地区/时代集合里（无语法标记）→ 是
  · 其余（`genitive` / `dative` / `feminine` / `subjunctive` …）→ **不是，不连**
⚠️ **`obsolete` 单独出现是正字法**（`seyend → seiend`），
   但 `('obsolete','subjunctive')` 是**语法形式**（`spiee → spie`）——
   所以判据不能写成「含不含 obsolete」，必须是「**除了正字法标记还有没有别的**」。

═══ 闸 ═══
① `dbtool` 的 expect 闸（`#inflection` 增量必须显式声明）。
② 不变量：孤儿 0 ／ 自指 0 ／ `label_zh` 非空 ／ 三元组无重复 ／
   **空白页必须真的降下来**（本步的目的，不是副作用）。
③ 抽样反验：随机打印新链接供人眼核 —— 这一步没有自动判据。

用法（在 de/ 目录下）：
    python3 -u pipeline/link_blank_forms.py            # 干跑
    python3 -u pipeline/link_blank_forms.py --apply
"""
import argparse
import gzip
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                                                  # noqa: E402
import paths                                                   # noqa: E402
from infl_compose import DERIV, compose                        # noqa: E402
from intake_edition_words import EDITIONS, clean_head, norm_word   # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))
from recover_alt_of import KIND_ZH, MOD_ZH, NO_MOD                 # noqa: E402

f = lambda n: format(n, ",")
EDS = ("de", "en")
SRC = "kk-%s-blank"

# 正字法 / 地区 / 时代标记 —— 它们说的是「**怎么写**」，不是「**什么语法形式**」。
# 🔴 这张表**只用于判断 tags 里有没有别的东西**，不用于「含了就算」。
ORTHO = {
    "alternative", "variant", "alt-of",
    "obsolete", "archaic", "dated", "rare", "nonstandard", "informal", "colloquial",
    "Switzerland", "Liechtenstein", "Austria", "Germany", "Swiss", "Austrian",
    "regional", "dialectal", "abbreviation", "initialism", "contraction",
    "capitalized", "uncommon", "proscribed", "misspelling",
}
STRONG = {"alternative", "variant", "alt-of"}      # 含它就是异体，不必看别的

# 「废弃/古体/罕用…」这类修饰，顺序固定以保证同一组 tags 永远拼出同一个标签。
MODS = ("obsolete", "archaic", "dated", "superseded", "rare", "uncommon",
        "nonstandard", "proscribed", "informal", "colloquial", "regional")


def variant_label(tags):
    """tags → 中文标签。**用的是 `recover_alt_of` 那两张表，不另造一份。**

    🔴 为什么不能让它回退成「变形」：干跑第一版全部 18,172 条标签都是「变形」，
       而它们**根本不是变形，是异体拼写**（`Fussschmerze` 之于 `Fußschmerze`）。
       那正是收尾单 C16「5.6 万行『变形』其实是异体/缩写/地区拼写」那个病 ——
       本步再添 1.8 万行进去，等于**一边补空白页一边把另一个已知缺陷做大**。
    ⚠️ 这里只拼**语法说明部分**，不拼「X 的 Y」——
       `inflection` 的约定是目标词放 `base` 列，`label_zh` 只说是什么关系
       （与 `recover_alt_of.label_zh` 的约定不同，那一份是给 `sense_gloss` 用的）。
    """
    t = set(tags)
    if {"Switzerland", "Liechtenstein"} & t:
        kind = "swiss-standard"
    elif "misspelling" in t:
        kind = "misspelling"
    elif "abbreviation" in t:
        kind = "abbreviation"
    elif "initialism" in t:
        kind = "initialism"
    elif "contraction" in t:
        kind = "contraction"
    elif "capitalized" in t:
        kind = "letter-case"
    else:
        kind = "alternative"
    base = KIND_ZH[kind]
    if kind in NO_MOD:
        return base
    mod = next((m for m in MODS if m in t), None)
    return "%s%s" % (MOD_ZH.get(mod, ""), base) if mod else base


def is_spelling_variant(tags):
    """→ 这个 form 是页面词头的**另一种写法**吗（而不是它的另一个语法形式）。

    🔴 判据按含义，两条：
      · 含 `alternative`/`variant` ⇒ 源头直接说了这是异体 → 是
      · 否则要求 tags **非空且全部落在 `ORTHO` 里** ——
        「除了正字法/地区/时代，没有任何别的标记」。
        这样 `('obsolete',)` 是异体、`('obsolete','subjunctive')` 不是。
    ⚠️ tags 为空一律**不算**：空 tags 给不出任何证据，而这一步的默认应该是
       「证明不了就别连」（`FRAMEWORK §一` 错比缺更伤权威）。
    """
    t = set(tags)
    if not t:
        return False
    if t & STRONG:
        return True
    return t <= ORTHO


def opener(p):
    p = Path(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def scan(edition, words, blank, seen3):
    """→ (rows, stat)。`blank` = 现在点进去空白的词形集合（**只补空白，不动已有的**）。"""
    path, need_filter = EDITIONS[edition]
    rows, stat = [], Counter()
    seq_of = Counter()
    with opener(path) as fh:
        for line in fh:
            if '"forms"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if need_filter and e.get("lang_code") != "de":
                continue
            base = clean_head(e.get("word"))
            if not base:
                continue
            senses = e.get("senses") or []
            pure = bool(senses) and all(
                x.get("form_of") or "form-of" in (x.get("tags") or []) for x in senses)
            pos_raw = e.get("pos") or "unknown"
            k = (base, pos_raw)
            seq = seq_of[k]
            seq_of[k] += 1
            base_id = words.get(base)
            for i, fm in enumerate(e.get("forms") or []):
                # 🔴 **只归一，不套 `is_single_form`** —— 见文件头 ①。
                x = norm_word(fm.get("form"))
                if not x:
                    continue
                wid = words.get(x)
                if wid is None:
                    continue                       # 不在库里：轮不到本步，那是阶段 3 的事
                if x not in blank:
                    stat["已经不是空白页（跳过，本步只补空白）"] += 1
                    continue
                if x == base:
                    stat["🔴 形式就是词头自己（零信息，丢）"] += 1
                    continue
                tags = [t for t in (fm.get("tags") or []) if t != "canonical"]
                if pure and not is_spelling_variant(tags):
                    stat["纯指针页上的兄弟变格形（不连，见文件头 ②）"] += 1
                    stat["  └ tags=%s" % (tuple(tags)[:3],)] += 1
                    continue
                # 🔴 异体写法与语法形式**用两套标签**：前者是"另一种写法"、
                #    后者是"另一个语法形式"，都叫「变形」正是 C16 那个病的成因。
                label = (variant_label(tags) if is_spelling_variant(tags)
                         else (compose(tags) or "变形"))
                tri = (wid, base, label)
                if tri in seen3:
                    stat["三元组已存在（去重）"] += 1
                    continue
                seen3.add(tri)
                kind = "derivation" if any(k2 in tags for k2, _ in DERIV) else "inflection"
                rows.append((
                    wid, None, kind, base, base_id, label, None,
                    json.dumps(tags, ensure_ascii=False),
                    SRC % edition,
                    "%s:%s:%s:%d#%d" % (SRC % edition, base, pos_raw, seq, i)))
                stat["✅ 新链接（%s 版，%s）" % (edition, "纯指针页" if pure else "真词元页")] += 1
    return rows, stat


def blank_pages(con):
    return con.execute(
        "SELECT COUNT(*) FROM dict d "
        " WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
        "   AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)"
        "   AND COALESCE(d.exchange,'')=''").fetchone()[0]


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("inflection 行数 == 期望", q("SELECT COUNT(*) FROM inflection"), expect["n"]),
        ("🔴 孤儿（word_id 不在 dict）",
         q("SELECT COUNT(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
           "WHERE d.id IS NULL"), 0),
        ("🔴 自指（形式就是词头）",
         q("SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id=i.word_id "
           "WHERE d.word=i.base"), 0),
        ("🔴 label_zh 为空",
         q("SELECT COUNT(*) FROM inflection WHERE label_zh IS NULL OR label_zh=''"), 0),
        ("🔴 (word_id, base, label_zh) 三元组重复",
         q("SELECT COUNT(*) FROM (SELECT word_id,base,label_zh FROM inflection "
           "GROUP BY 1,2,3 HAVING COUNT(*)>1)"), 0),
        # 🔴 本步的**目的**就是这个数降下来。它不降 = 这一步白做了。
        ("🔴 空白页没有降下来", 1 if blank_pages(con) >= expect["blank_before"] else 0, 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %12s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    blank = {w for (w,) in con.execute(
        "SELECT d.word FROM dict d "
        " WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
        "   AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)"
        "   AND COALESCE(d.exchange,'')=''")}
    seen3 = {(w, b, l) for w, b, l in
             con.execute("SELECT word_id, base, label_zh FROM inflection")}
    n_before = con.execute("SELECT COUNT(*) FROM inflection").fetchone()[0]
    before = len(blank)
    con.close()
    print("■ 库内词形 %s ／ 变形层 %s 行 ／ 空白页 %s" % (f(len(words)), f(n_before), f(before)))

    rows, stat = [], Counter()
    for ed in EDS:
        print("\n■ 扫 %s 版…" % ed)
        r, s = scan(ed, words, blank, seen3)
        rows += r
        stat += s
    print()
    for k, v in stat.most_common(18):
        print("   %-50s %10s" % (k, f(v)))

    got = {r[0] for r in rows}
    dangling = sum(1 for r in rows if r[4] is None)
    print("\n■ 新链接 %s 条 ／ 覆盖 %s 个空白词形（空白页 %s → %s）／ 原形不在库 %s"
          % (f(len(rows)), f(len(got)), f(before), f(before - len(got)), f(dangling)))

    id2w = {i: w for w, i in words.items()}
    random.seed(11)
    print("\n── 抽样反验：随机 16 条新链接（人眼核，这一步没有自动判据）──")
    for r in random.sample(rows, min(16, len(rows))):
        print("   %-32s → %-24s %s" % (id2w[r[0]][:32], r[3][:24], r[5]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-2d-blank", expect={"#inflection": len(rows)}) as s:
        s.executemany(
            "INSERT INTO inflection (word_id,entry_id,kind,base,base_id,label_zh,"
            "desc_en,tags,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    after = blank_pages(con)
    print("\n■ 空白页 %s → %s（降 %s，-%.1f%%）"
          % (f(before), f(after), f(before - after), 100 * (before - after) / max(before, 1)))
    ok = gate2(con, {"n": n_before + len(rows), "blank_before": before})
    con.close()
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
