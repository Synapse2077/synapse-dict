#!/usr/bin/env python3
"""阶段 1.5a — 收德语原文释义 → `sense` / `sense_gloss(lang='de')` / `sense_src`。de 版，2026-09-01。

⚠️ **本步不花一分钱。** 收原文释义、建出版层义项、把中文版白送的中文放进去，全是确定性的。
   翻译是 **1.5b**，单独报价、单独跑。
   两件事分开的理由同 pt：**捆在一起就没法先看「免费能拿到多少」再决定买多少**
   （`[[prove-free-path-before-quoting]]`）。

═══ 范围：只收「一条义项都没有的词形」，不碰已有义项 ═══
🔴 这条范围是**为了绕开对齐问题**，不是偷懒。库里已有 125,649 条义项，每条都带中英文；
   德语版对同一个词往往给出**条数不同、切分不同**的义项 —— 硬对齐就是
   `[[verification-gates-not-sampling]]` 里用户点名的「义项和释义错配，那才是真灾难」。
   已有义项的德语原文归**阶段 1.5 第二段**，另设判据、另立一步。

═══ 🔴 只收德语版的定义，别的版另算 ═══
`[[gloss-three-languages]]`：**每个维基版只给「自己语言的词」写定义，对外语词只写翻译。**
de 这一门的探针已经印证过同一件事（`docs/lang/de-CONVENTIONS.md` 取数表的 ⚠️ 行）：
it/pt/es 版的「真释义占比」高达 85–95%，只是因为**那三版根本不标变形**，
它们给德语词的所谓"释义"是本语言对应词，不是定义。

⇒ 本步**只收 `de` 版**。其余各版给的对应词性质不同，进收尾单，不混进同一批。

═══ 中文版的中文：**免费，先拿** ═══
zh 版对德语词有人工中文。凡是本步新建的义项能从 zh 版拿到中文的，直接进
`sense_gloss(lang='zh')`，`src='zh-edition'` —— 那部分**不进 1.5b 的付费池**。
⚠️ 仍然建 `sense_src` 留底：出版层的每个字都要答得出「哪来的」。

═══ 判据：什么算「真释义」═══
`senses[].glosses[0]` 非空，**且该义项没有 `form_of` / `alt_of`**
—— 指针义项归变形层（阶段 2/2c 定的规矩，这里不重开）。

用法（在 de/ 目录下）：
    python3 -u pipeline/ingest_de_senses.py            # 干跑（含免费中文的落点）
    python3 -u pipeline/ingest_de_senses.py --apply
    python3 -u pipeline/ingest_de_senses.py --verify
"""
import argparse
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "probes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build import POS_MAP                                   # noqa: E402
from intake_edition_words import EDITIONS, clean_head, opener   # noqa: E402

f = lambda n: format(n, ",")
has_han = dbtool.has_han if hasattr(dbtool, "has_han") else (
    lambda s: any("一" <= c <= "鿿" for c in (s or "")))


# ── 德语一等字段：从德语版抽 ──────────────────────────────────────────────
# 🔴 **为什么值得抽**：阶段 1 只从**英文版**填了 368,376 行 entry 的一等字段，
#    而本步新建的 118,191 个词元一条都没有。实测德语版给得起：
#      名词性别   条目级 `tags`   82,534 / 83,070 = **99.4%**
#      变格 forms  结构化 tags    109,574 / 118,191 = **92.7%**
# ⚠️ **有意不给阶段 3 新收的另外 73 万个词形建 entry** —— 那批是变形，
#    德语版只给它们指针页，建出来就是 85 万行全 NULL 的空壳，
#    而 **pt 自己的展示层根本不读 `entry`**（`portuguese.ts` 文件头：
#    「查变形必须走 `inflection.word_id`，不能走 entry」，pt 收尾单 C11）。
#    ⇒ 造一张没人读的大表是 `PITFALLS` D1。本步只给**有真释义的词元**建。
GENDER_TAGS = {"masculine": "m", "feminine": "f", "neuter": "n"}


def _pick_form(forms, need, avoid=()):
    """挑第一个 tags ⊇ need 且不含 avoid 的 form。判据只在这里写一份。"""
    for fm in forms:
        t = set(fm.get("tags") or [])
        if need <= t and not (set(avoid) & t):
            x = (fm.get("form") or "").strip()
            if x and x not in ("-", "—", "?"):
                return x
    return None


def first_class(e):
    """→ 德语一等字段 dict（抽不出来的一律 None，**不用默认值填平**）。"""
    forms = e.get("forms") or []
    g = "/".join(GENDER_TAGS[t] for t in ("masculine", "feminine", "neuter")
                 if t in (e.get("tags") or []))
    pos_raw = e.get("pos") or ""
    out = {"gender": g or None}
    if pos_raw in ("noun", "name"):
        out["genitive"] = _pick_form(forms, {"genitive", "singular"})
        out["plural"] = _pick_form(forms, {"nominative", "plural"})
    elif pos_raw == "verb":
        # 过去时第三人称单数（德语词典著录的三基本形式之二）
        out["praeteritum"] = (_pick_form(forms, {"preterite", "third-person", "singular"})
                              or _pick_form(forms, {"past", "third-person", "singular"}))
        # 第二分词：德语版用单独的 `perfect`（同 `infl_compose` 那条缺口）
        out["partizip2"] = (_pick_form(forms, {"perfect"}, avoid={"auxiliary"})
                            or _pick_form(forms, {"participle", "past"}))
    return out


def is_real_sense(s):
    """真释义的判据 —— 只有这一份，扫两个版都用它。"""
    if s.get("form_of") or s.get("alt_of"):
        return False
    if "form-of" in (s.get("tags") or []):
        return False
    return bool((s.get("glosses") or [""])[0].strip())


def scan(edition, targets):
    """扫一版 → {词形: [(gloss, pos_raw, tags, seq, sense_idx)]}，只保留 `targets` 里的词形。"""
    path, need_filter = EDITIONS[edition]
    out = defaultdict(list)
    seq_of, stat = Counter(), Counter()
    meta = {}                       # (词形, pos_raw, seq) → 德语一等字段
    with opener(path) as fh:
        for line in fh:
            if need_filter and '"lang_code"' in line and '"de"' not in line:
                continue                       # 便宜的预筛，避免整行 JSON 解析
            try:
                e = json.loads(line)
            except Exception:
                continue
            if need_filter and e.get("lang_code") != "de":
                continue
            w = e.get("word") or ""
            if w not in targets:
                w = clean_head(w)
                if w not in targets:
                    continue
            pos_raw = e.get("pos") or "unknown"
            k = (w, pos_raw)
            seq = seq_of[k]
            seq_of[k] += 1
            for i, s in enumerate(e.get("senses") or []):
                if not is_real_sense(s):
                    continue
                out[w].append(((s.get("glosses") or [""])[0].strip(),
                               pos_raw, s.get("tags") or [], seq, i))
                stat["真释义"] += 1
            if out.get(w):
                meta.setdefault((w, pos_raw, seq), first_class(e))
    return out, stat, meta


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("sense 行数 == 期望", q("SELECT count(*) FROM sense"), expect["sense"]),
        ("rank 不从 1 连续的词形",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("没有任何 gloss 的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.sense_id IS NULL"), 0),
        ("🔴 sense.gender 全为空（德语性别是词条级）",
         q("SELECT count(*) FROM sense WHERE gender IS NOT NULL"), 0),
        ("🔴 本步新建的义项都有德语原文",
         q("SELECT count(*) FROM sense s WHERE s.id > %d AND NOT EXISTS("
           "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='de')"
           % expect["max_sense_before"]), 0),
        ("🔴 中文 gloss 里没有汉字（免费中文取错了）",
         q("SELECT count(*) FROM sense_gloss WHERE lang='zh' AND src='zh-edition' "
           "  AND text NOT GLOB '*[一-鿿]*'"), 0),
        ("entry 孤儿（word_id 不在 dict）",
         q("SELECT count(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
           "WHERE d.id IS NULL"), 0),
        ("entry.src_ref 重复",
         q("SELECT count(*) FROM (SELECT src_ref FROM entry GROUP BY src_ref HAVING count(*)>1)"), 0),
        ("sense_src 孤儿（sense_id 指向不存在的义项）",
         q("SELECT count(*) FROM sense_src x LEFT JOIN sense s ON s.id=x.sense_id "
           "WHERE x.sense_id IS NOT NULL AND s.id IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-48s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    # 🔴 **默认关**。德语一等字段 + entry 行本来不在阶段 1.5 的范围里
    #    （阶段表第 182 行把 entry 的增长挂在**阶段 3**，而阶段 3 有意没建）。
    #    2026-09-01 我把它悄悄折进正在跑的 1.5a，用户当场制止：
    #    「我本来只是问一下，结果你就给我跑起来了」「乱了步骤，导致后面填不完的坑」。
    #    ⇒ 做成开关而不是删掉：抽取逻辑本身有实测支撑（性别 99.4%、变格 92.7%），
    #      值得留着；但**它是一个单独的决定，要带着数字单独去问**，
    #      不许搭另一步的车进库。判据：`--with-entry` 没写在命令行里，就一行都不写。
    ap.add_argument("--with-entry", action="store_true",
                    help="额外写 entry 行 + 德语一等字段（默认不写，需单独决定）")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate2(con, {"sense": con.execute("SELECT count(*) FROM sense").fetchone()[0],
                                "max_sense_before": 0}) else 1

    words = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    zero = {w for (w,) in con.execute(
        "SELECT d.word FROM dict d WHERE NOT EXISTS("
        "  SELECT 1 FROM sense s WHERE s.word_id=d.id)")}
    print("■ 库内词形 %s ／ **一条义项都没有的** %s" % (f(len(words)), f(len(zero))))

    print("\n■ 扫德语版（真释义）…")
    de_def, st1, de_meta = scan("de", zero)
    n_def = sum(len(v) for v in de_def.values())
    print("   有真释义的零义项词形 %s ／ 义项 %s" % (f(len(de_def)), f(n_def)))
    print("   德语版也给不出释义的  %s   ← 花钱也买不到" % f(len(zero) - len(de_def)))

    print("\n■ 扫中文版（免费中文）…")
    zh_def, _, _ = scan("zh", set(de_def))
    zh_hit = {w: [g for g, *_ in v if has_han(g)] for w, v in zh_def.items()}
    zh_hit = {w: v for w, v in zh_hit.items() if v}
    print("   ⭐ 中文版**白送**中文的词形 %s（%.1f%%）／ 条 %s"
          % (f(len(zh_hit)), 100 * len(zh_hit) / max(len(de_def), 1),
             f(sum(len(v) for v in zh_hit.values()))))

    paid = sum(len(v) for w, v in de_def.items() if w not in zh_hit)
    chars = sum(len(g) for w, v in de_def.items() if w not in zh_hit for g, *_ in v)
    print("\n■ 1.5b 的付费池（本步之后才定得下来）")
    print("   要送翻译的义项      %s" % f(paid))
    print("   德语原文字符        %s（均 %.0f）" % (f(chars), chars / max(paid, 1)))
    print("   ⇒ 按 pt 实测 60.8 token/条：约 %s token" % f(int(paid * 60.8)))

    random.seed(5)
    print("\n── 抽样反验：随机 8 个新词形的德语原文 ──")
    for w in random.sample(sorted(de_def), min(8, len(de_def))):
        print("   %-24s %s" % (w, de_def[w][0][0][:56]))
    if zh_hit:
        print("\n── 免费中文样本 ──")
        for w in random.sample(sorted(zh_hit), min(6, len(zh_hit))):
            print("   %-24s %s" % (w, zh_hit[w][0][:44]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    max_sense = con.execute("SELECT max(id) FROM sense").fetchone()[0]
    n_before = con.execute("SELECT count(*) FROM sense").fetchone()[0]
    con.close()

    sid = max_sense
    senses, glosses, srcs = [], [], []
    for w in sorted(de_def):
        wid = words[w]
        zh = zh_hit.get(w, [])
        for rank, (g, pos_raw, tags, seq, i) in enumerate(de_def[w], 1):
            sid += 1
            senses.append((sid, wid, rank, POS_MAP.get(pos_raw, pos_raw), None))
            glosses.append((sid, "de", "definition", 0, g, "de-edition"))
            # 中文版按**顺序**配对：它与德语版的义项切分不保证一致 ⇒
            # 🔴 只在**两边都只有一条**时才配，多条一律不猜（错配比没有更伤）。
            if len(zh) == 1 and len(de_def[w]) == 1:
                glosses.append((sid, "zh", "equivalent", 0, zh[0], "zh-edition"))
            srcs.append((wid, sid, "de-edition",
                         "kk-de:%s:%s:%d#%d" % (w, pos_raw, seq, i),
                         "de", g, json.dumps(tags, ensure_ascii=False) if tags else None))

    erows, fc = [], Counter()
    for (w, pos_raw, seq), m in sorted(de_meta.items()):
        if w not in de_def or w not in words:
            continue
        for k2 in ("gender", "genitive", "plural", "praeteritum", "partizip2"):
            if m.get(k2):
                fc[k2] += 1
        erows.append((words[w], w, POS_MAP.get(pos_raw, pos_raw), pos_raw, "0", seq,
                      m.get("gender"), m.get("genitive"), m.get("plural"),
                      None, m.get("praeteritum"), m.get("partizip2"),
                      None, None, None, None, None, None,
                      "de-edition", "kk-de:%s:%s:%d" % (w, pos_raw, seq)))
    print("\n■ 德语一等字段（从德语版抽，零模型）%s"
          % ("" if a.with_entry else "  ← **本次不写**，仅报数（要写加 --with-entry）"))
    for k2, v in fc.most_common():
        print("   %-14s %s" % (k2, f(v)))
    print("   entry 候选行     %s" % f(len(erows)))
    if not a.with_entry:
        erows = []

    n_zh = sum(1 for g in glosses if g[1] == "zh")
    print("\n■ 将写入 sense %s ／ sense_gloss %s（其中免费中文 %s）／ sense_src %s ／ entry %s"
          % (f(len(senses)), f(len(glosses)), f(n_zh), f(len(srcs)), f(len(erows))))
    expect = {"#sense": len(senses), "#sense_gloss": len(glosses),
              "#sense_src": len(srcs)}
    if erows:
        expect["#entry"] = len(erows)
    with dbtool.session("keep-v3-15a-de-senses", expect=expect) as s:
        s.executemany("INSERT INTO sense (id,word_id,rank,pos,gender) VALUES (?,?,?,?,?)",
                      senses)
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,?,?,?,?,?)", glosses)
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
                      "VALUES (?,?,?,?,?,?,?)", srcs)
        s.executemany(
            "INSERT INTO entry (word_id,word_src,pos,pos_raw,etym_no,seq,gender,genitive,"
            " plural,aux,praeteritum,partizip2,vclass,separable,sep_prefix,reflexive,"
            " comparative,superlative,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", erows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok = gate2(con, {"sense": n_before + len(senses), "max_sense_before": max_sense})
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
