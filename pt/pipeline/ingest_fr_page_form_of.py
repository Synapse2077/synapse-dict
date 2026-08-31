#!/usr/bin/env python3
"""阶段 2e：**法语版页面的 `form_of` 补进变形层** —— 又一条缝。2026-08-31。

═══ 这条缝在哪 ═══
21,184 个词形点进去一片空白（收尾单 C10）。其中 12,196 个**词条层有 `entry`、义项层是空的**，
按来源拆开：fr 版 7,653 ／ pt 版 1,781 ／ ru 版 1,687 ／ pl 版 627 …

回源扫 fr 版这 7,601 个词形，**5,342 条义项带结构化 `form_of`**，剩 2,694 条是
`abdomen → Abdomen.` 这种外语翻译（`[[gloss-three-languages]]`：非本语言版只给翻译不给定义，
按方针不收，那是收尾单 C18 那一族）。

    2b   变形层  读 `form_of` → **只读英文版**
    2d   变形层  读**葡语散文** `<关系词> de <原形>`（`ingest_prose_inflections.PTR`）
    2e   ← 本步：**法语版用法语写 form_of**，上面两步的判据都够不着

🔴 **`tags` 只有 `['form-of']`，语法细节全在法语散文里** ——
   所以必须解析法语术语。但**中文标签不在这里生成**：法语 → kaikki tags → `compose()`，
   `compose` 那份判据一个字不动（`[[fix-regression-and-gate]]`：判据只许一份）。

═══ 判据：两个独立信号必须一致 ═══
`form_of[0].word` 在 pt 版上**不可信**（wiktextract 把散文片段塞进去，见 2d 的教训）。
这里不赌它：**结构化字段的原形，必须等于散文结尾 `… de <原形>` 取出来的那个**。
实测 5,342 条里 **5,301 条（99.2%）一致**，41 条不一致 ⇒ 一律跳过，不猜。

⚠️ `Forme pronominale de X`（70 条）**有意不收**：代词式不是屈折形式，与 2d 不收
   `diminutivo`/`aumentativo` 同一个理由（构词不是屈折，收尾单 C26）。
⚠️ 法语术语表**不许兜底**：认不出的形状原样计数打印出来，不塞「变位形式」——
   兜底会让"没解析出来"伪装成"解析出来了"（收尾单 C12 就是这么来的 3,494 条）。

用法（在 pt/ 目录下）：
    python3 -u pipeline/ingest_fr_page_form_of.py
    python3 -u pipeline/ingest_fr_page_form_of.py --apply
"""
import argparse
import collections
import gzip
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from infl_compose import compose   # noqa: E402  ⭐ 中文标签只有这一份

SRC = "fr-edition-page"

# ── 法语语法术语 → kaikki tags ──────────────────────────────────
# 封闭词表，从实测的 125 种形状抽出来的，不是凭印象列的。
# 🔴 `conditionnel` 映射成 `{future, past}` 而不是 `conditional`：葡语的
#    futuro do pretérito 就是这个签名，`compose` 的 TENSE_RULES 第一条正是它。
FR_TAGS = [
    ("participe passé",      {"participle", "past"}),
    ("participe présent",    {"participle", "present"}),
    ("première personne",    {"first-person"}),
    ("deuxième personne",    {"second-person"}),
    ("troisième personne",   {"third-person"}),
    ("du singulier",         {"singular"}),
    ("du pluriel",           {"plural"}),
    ("de l’indicatif",       {"indicative"}),
    ("de l'indicatif",       {"indicative"}),
    ("du subjonctif",        {"subjunctive"}),
    ("de l’impératif",       {"imperative"}),
    ("de l'impératif",       {"imperative"}),
    ("du conditionnel",      {"future", "past"}),
    ("conditionnel",         {"future", "past"}),
    ("plus-que-parfait",     {"pluperfect"}),
    ("de l’imparfait",       {"imperfect"}),
    ("imparfait",            {"imperfect"}),
    ("du prétérit",          {"preterite"}),
    ("prétérit",             {"preterite"}),
    ("du présent",           {"present"}),
    ("du futur",             {"future", "present"}),
    ("futur",                {"future", "present"}),
]
# 只说性数、不说时态语气的那一族（`Féminin singulier de X` / `Pluriel de X`）
FR_BARE = [("féminin", {"feminine"}), ("masculin", {"masculine"}),
           ("singulier", {"singular"}), ("pluriel", {"plural"})]
SKIP = ("forme pronominale",)
TAIL = re.compile(r"\bd[eu’']\s*([^\s.]+)\.?\s*$")


def to_tags(gloss):
    """法语散文 → kaikki tags；认不出返回 None（**不兜底**）。"""
    g = gloss.lower()
    if any(s in g for s in SKIP):
        return None
    t = set()
    for k, v in FR_TAGS:
        if k in g:
            t |= v
    # 🔴 **性数必须无条件扫**（读打样逮到的）：第一版把它放在 `if not t` 分支里，
    #    于是 `Participe passé féminin pluriel de tabicar` 先命中 `participe passé`、
    #    就再也不看后面的 `féminin pluriel` ⇒ 4,254 条过去分词**性数全丢**，
    #    `tabicadas` 出来只有「过去分词」。而性数正是这一族唯一的信息量。
    #    ⚠️ 与 FR_TAGS 里的 `du singulier`/`du pluriel` 重复命中是无害的（同一个集合）。
    head = re.sub(r"\bd[eu’'][^\s]*\s+\S+\.?\s*$", "", g).strip()
    for k, v in FR_BARE:
        if k in head:
            t |= v
    return t or None


def scan(con):
    blank = {w: i for w, i in con.execute("""
        SELECT d.word, d.id FROM dict d JOIN entry e ON e.word_id=d.id
         WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id
                           AND COALESCE(s.hidden,0)=0)
           AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)""")}
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    stat, cand, unknown = collections.Counter(), {}, collections.Counter()
    with gzip.open(paths.DUMPS / "frwiktionary.jsonl.gz", "rt", encoding="utf-8") as fh:
        for ln in fh:
            e = json.loads(ln)
            w = e.get("word")
            if e.get("lang_code") != "pt" or w not in blank:
                continue
            for s in e.get("senses", []):
                fo = s.get("form_of")
                if not fo:
                    stat["源头这条不是 form_of（外语翻译，按方针不收）"] += 1
                    continue
                base = ((fo[0] or {}).get("word") or "").strip()
                g = (s.get("glosses") or [""])[0]
                m = TAIL.search(g)
                if not (base and m and m.group(1).strip("’'") == base):
                    stat["🔴 两个信号不一致 ⇒ 跳过"] += 1
                    continue
                if base not in ids:
                    stat["原形不在库里 ⇒ 跳过"] += 1
                    continue
                tags = to_tags(g)
                if not tags:
                    stat["法语术语认不出 ⇒ 跳过（不兜底）"] += 1
                    unknown[re.sub(r"\bde\s+\S+\.?$", "de <原形>", g.strip())] += 1
                    continue
                zh = compose(sorted(tags))
                if not zh:
                    stat["compose 组不出中文 ⇒ 跳过"] += 1
                    unknown["[compose] " + g[:60]] += 1
                    continue
                stat["✅ 可补"] += 1
                cand[(blank[w], base, zh)] = (w, base, zh, g)
    return cand, stat, unknown


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    f = lambda n: format(n, ",")
    cand, stat, unknown = scan(con)
    for k, v in stat.most_common():
        print("   %9s  %s" % (f(v), k))
    print("\n■ 去重后可补 %s 条 / %s 个词形"
          % (f(len(cand)), f(len({k[0] for k in cand}))))
    if unknown:
        print("\n■ 认不出的形状（**不兜底**，原样列出来）前 8：")
        for k, v in unknown.most_common(8):
            print("   %5d  %s" % (v, k[:70]))
    random.seed(5)
    print("\n■ 抽 12 条人眼核：")
    for w, base, zh, g in random.sample(list(cand.values()), min(12, len(cand))):
        print("   %-16s → %-14s %-22s ← %s" % (w[:16], base[:14], zh[:22], g[:44]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    # 🔴 `src_ref` 必须带**标签**：同一个词形指向同一原形可以有多个不同标签
    #    （`une → unir` 既是陈述式第三人称单数、又是命令式第二人称单数）。
    #    第一版写成 `fr-page:<wid>:<base>` ⇒ `UNIQUE(src_ref)` 当场拦住，数据一行没写进去。
    #    ⚠️ 这已经是这张表第二次靠这个约束兜底了（阶段 1.5a 那次同一个形状）。
    rows = [(wid, base, ids[base], zh, "fr-page:%d:%s:%s" % (wid, base, zh))
            for (wid, base, zh) in cand]
    with dbtool.session("ingest-pt-fr-page-form-of",
                        expect={"#inflection": len(rows)}) as s:
        s.executemany(
            "INSERT INTO inflection(word_id, base, base_id, label_zh, src, src_ref) "
            "VALUES(?,?,?,?,'%s',?)" % SRC, rows)
    print("\n✓ 变形层 +%s" % f(len(rows)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
