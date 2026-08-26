#!/usr/bin/env python3
"""阶段 1.5 补丁：把法文版的 `alt_of` 义项收回来。2026-08-22。

═══ 缺陷（阶段 2a 那个缺陷换个版本重演）═══
法文版的 `alt_of` 义项**两头都不落地**：
  · 不进 `inflection` —— 3b-2 只收 `form_of`（`alt_of` 是独立词条，不是变形，2a 已定）
  · 不进 `sense_src` —— 1.5 第一段按源头的结构化字段把**所有**指针都过滤了

结果 **10,064 条整批消失**，直接造成 **10,953 个词形一条内容都没有**：

    bahá'í         Variante de bahaï.
    penjabi        Variante de pendjabi.
    anarythmétisme Variante orthographique de anarithmétisme.
    pashto         Variante de pachto.

英文版侧同一族缺陷阶段 2a 已修（4,141 个词形）。**同一套解析逻辑，必然复现。**

═══ 判据：封闭前缀白名单，命中 99.14% ═══
法文版 `alt_of` 共 **12,753** 条 / **919 种骨架** —— 骨架比英文版散得多
（前 40 种只覆盖 92.3%），但**前缀是规整的**：
`Variante de` / `Variante orthographique de` / `Mauvaise orthographe de` /
`Orthographe par contrainte typographique de` / `→ voir` …
实测前缀白名单命中 **12,643 / 12,753 = 99.14%**，未命中 **110** 条。

🔴 与 2a 同一条纪律：**只有前缀命中才生成中文**。没命中的照样收录义项
（法语原文进 `sense_gloss(lang='fr')`），但**中文留空**等翻译 —— 宁可空着不给错的。

═══ `kind` 用 `definition` 不用 `equivalent` ═══
法语那句是**完整的定义式句子**（带句号），不是对应词。
阶段 0 记账里「`sense_gloss.kind` 249,647 行全是 equivalent」是历史债，
**新写的行不再往债里加**：法语句子记 `definition`，模板中文记 `equivalent`。

═══ rank ═══
这批词绝大多数**本来一条义项都没有**；有已有义项的（来自英文版）则追加在后面。
跨版本的 dump 顺序没有意义，不强行插位。

用法（在 fr/ 目录下）：
    python3 fixes/recover_fr_alt_of.py            # 干跑（含判据覆盖率与中文样本）
    python3 fixes/recover_fr_alt_of.py --apply
    python3 fixes/recover_fr_alt_of.py --verify
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from intake_fr_words import POS_MAP, norm_apos   # noqa: E402

SRC = "fr-edition"

# 🔴 封闭前缀白名单 → 中文模板。**这张表就是最终产物：错了就是上万条一起错。**
#    键已归一（小写 + 直撇 + 去变音符），长的排前面先匹配。
TPL = {
    "variante orthographique de": "%s 的异体拼写",
    "variante orthographique d'": "%s 的异体拼写",
    "orthographe alternative de": "%s 的异体拼写",
    "variante typographique fautive de": "%s 的排印变体（非规范）",
    "variante typographique de": "%s 的排印变体",
    "variante typographique d'": "%s 的排印变体",
    "variante par contrainte typographique de": "%s 的排印受限变体",
    "variante par contrainte typographique d'": "%s 的排印受限变体",
    "orthographe par contrainte typographique de": "%s 的排印受限拼写",
    "orthographe par contrainte typographique d'": "%s 的排印受限拼写",
    "mauvaise orthographe de": "%s 的误拼（非规范写法）",
    "mauvaise orthographe d'": "%s 的误拼（非规范写法）",
    "graphie erronee du mot": "%s 的误拼（非规范写法）",
    "graphie erronee de": "%s 的误拼（非规范写法）",
    "graphie erronee d'": "%s 的误拼（非规范写法）",
    "ancienne orthographe de": "%s 的旧拼写",
    "ancienne orthographe d'": "%s 的旧拼写",
    "ancienne graphie de": "%s 的旧拼写",
    "variante ancienne de": "%s 的古体异体形式",
    "variante de": "%s 的异体形式",
    "variante d'": "%s 的异体形式",
    "abreviation de": "%s 的缩写",
    "abreviation d'": "%s 的缩写",
    "acronyme de": "%s 的首字母缩略词",
    "sigle de": "%s 的首字母缩写",
    "apocope de": "%s 的省尾形式",
    "apherese de": "%s 的省首形式",
    "diminutif de": "%s 的指小形式",
    "augmentatif de": "%s 的指大形式",
    "→ voir": "参见 %s",
    "-> voir": "参见 %s",
    "voir": "参见 %s",
}
ORDER = sorted(TPL, key=len, reverse=True)


def norm_key(s):
    """归一只用于**匹配前缀**，不影响任何输出。"""
    s = s.replace("’", "'").replace("ʼ", "'").lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def zh_of(gloss, target):
    """→ 中文标签；前缀没命中返回 None（**不猜**）。"""
    if not target:
        return None
    k = norm_key(gloss)
    for p in ORDER:
        if k.startswith(p):
            return TPL[p] % target
    return None


def scan(ids):
    """→ per_word[word] = [(pos_raw, occ, idx, gloss, target, tags)]"""
    out = defaultdict(list)
    occ_of = Counter()
    stat = Counter()
    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "fr":
                continue
            w = norm_apos((e.get("word") or "").strip())
            if not w:
                continue
            pos_raw = e.get("pos") or ""
            occ = occ_of[(w, pos_raw)]
            occ_of[(w, pos_raw)] += 1
            for i, s in enumerate(e.get("senses") or []):
                ao = s.get("alt_of")
                if not ao or s.get("form_of"):
                    continue
                stat["alt_of 义项"] += 1
                g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
                if not g:
                    stat["空 gloss（跳过）"] += 1
                    continue
                if w not in ids:
                    stat["🔴 词形不在 dict（不该发生）"] += 1
                    continue
                out[w].append((pos_raw, occ, i, g,
                               norm_apos((ao[0].get("word") or "").strip()),
                               s.get("tags") or []))
                stat["→ 要收的义项"] += 1
    return out, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(con)
    ids = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    print("■ 扫法文版…")
    per_word, stat = scan(ids)
    for k, v in sorted(stat.items()):
        print("   %-32s %8s" % (k, f"{v:,}"))

    n = sum(len(v) for v in per_word.values())
    hit = sum(1 for v in per_word.values() for x in v if zh_of(x[3], x[4]))
    print("\n■ 判据覆盖：前缀命中 %s / %s = %.2f%%（未命中 %s，中文留空）"
          % (f"{hit:,}", f"{n:,}", 100.0 * hit / max(n, 1), f"{n - hit:,}"))

    print("\n── 中文样本（每种模板一条）──")
    seen = set()
    for w in sorted(per_word):
        for pos_raw, occ, i, g, tgt, tags in per_word[w]:
            z = zh_of(g, tgt)
            if not z:
                continue
            k = norm_key(g).split(" de ")[0][:34]
            if k in seen:
                continue
            seen.add(k)
            print("   %-18s %-48s → %s" % (w[:18], g[:48], z))
    print("\n── 未命中样本（中文留空，法语原文照收）──")
    m = 0
    for w in sorted(per_word):
        for pos_raw, occ, i, g, tgt, tags in per_word[w]:
            if zh_of(g, tgt) or m >= 6:
                continue
            m += 1
            print("   %-18s %s" % (w[:18], g[:62]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    return apply_(con, ids, per_word)


def apply_(con, ids, per_word):
    eid = dict(con.execute("SELECT src_ref, id FROM entry WHERE src=?", (SRC,)))
    maxrank = defaultdict(int)
    for wid, r in con.execute("SELECT word_id, max(rank) FROM sense GROUP BY word_id"):
        maxrank[wid] = r
    nid = con.execute("SELECT max(id) FROM sense").fetchone()[0]

    senses, glosses, rels, srcs = [], [], [], []
    st = Counter()
    for w, items in per_word.items():
        wid = ids[w]
        for pos_raw, occ, i, g, tgt, tags in items:
            nid += 1
            maxrank[wid] += 1
            ref = "kk-fr:%s:%s#%d.%d" % (w, pos_raw, occ, i)
            senses.append((nid, wid, maxrank[wid], POS_MAP.get(pos_raw, pos_raw),
                           eid.get("kk-fr:%s:%s#%d" % (w, pos_raw, occ))))
            # 法语原文是**定义式句子** ⇒ kind='definition'（不再往 equivalent 那笔历史债里加）
            glosses.append((nid, "fr", "definition", 0, g, SRC))
            z = zh_of(g, tgt)
            if z:
                glosses.append((nid, "zh", "equivalent", 0, z, "template:fr-alt_of"))
                st["中文由模板生成"] += 1
            else:
                st["🔴 前缀未命中，中文留空（等翻译）"] += 1
            if tgt:
                rels.append((wid, nid, "alt_of", tgt,
                             json.dumps(tags, ensure_ascii=False), SRC, ref))
            srcs.append((wid, nid, SRC, ref, "fr", g,
                         json.dumps({"tags": tags, "__alt_of__": [tgt] if tgt else []},
                                    ensure_ascii=False)))
            st["新建义项"] += 1

    for k, v in sorted(st.items()):
        print("   %-36s %8s" % (k, f"{v:,}"))
    con.close()

    with dbtool.session("keep-v3-fr-altof",
                        expect={"#sense": len(senses), "#sense_gloss": len(glosses),
                                "#sense_relation": len(rels), "#sense_src": len(srcs)}) as s:
        s.executemany("INSERT INTO sense (id,word_id,rank,pos,entry_id) VALUES (?,?,?,?,?)",
                      senses)
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,?,?,?,?,?)", glosses)
        s.executemany("INSERT OR IGNORE INTO sense_relation "
                      "(word_id,sense_id,kind,target,tags,src,src_ref) VALUES (?,?,?,?,?,?,?)",
                      rels)
        s.executemany("INSERT INTO sense_src "
                      "(word_id,sense_id,src,src_ref,lang,text,raw_tags) VALUES (?,?,?,?,?,?,?)",
                      srcs)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("rank 不从 1 连续的词形",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("没有任何 gloss 的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.sense_id IS NULL"), 0),
        ("孤儿 sense", q("SELECT count(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id "
                         "WHERE d.id IS NULL"), 0),
        ("孤儿 sense_src", q("SELECT count(*) FROM sense_src x LEFT JOIN dict d "
                             "ON d.id=x.word_id WHERE d.id IS NULL"), 0),
        ("sense_src.src_ref 重复",
         q("SELECT count(*) FROM (SELECT src_ref FROM sense_src GROUP BY src_ref "
           "HAVING count(*)>1)"), 0),
        ("🔴 无 sense_src 的 sense == 58（阶段 0 的中文孤儿，不能变多）",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_src x ON x.sense_id=s.id "
           "WHERE x.sense_id IS NULL"), 58),
        # 🔴 2026-08-22：这条断言第一版写成「中文里含 Variante/orthographe」——
        #    **又是形式代理**，当场误报 1 条：`orthographie` 是 `orthographe`（正字法）的异体，
        #    目标词本身就叫 orthographe，中文里出现它完全正确。**红的是断言不是数据。**
        #    ⇒ 换成对着**自己的模板集合**做封闭校验：每条模板中文要么以「参见 」开头，
        #      要么以 TPL 里某个中文后缀结尾。这是可判定的，不靠猜词形。
        ("🔴 模板中文不符合任何一个模板的形状",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE src='template:fr-alt_of'")
             if not (t.startswith("参见 ")
                     or any(t.endswith(v.split("%s", 1)[-1]) for v in TPL.values()))), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-50s %8s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    dead = q("SELECT count(*) FROM dict d LEFT JOIN sense s ON s.word_id=d.id "
             "LEFT JOIN inflection i ON i.word_id=d.id "
             "LEFT JOIN sense_src x ON x.word_id=d.id "
             "WHERE s.id IS NULL AND i.id IS NULL AND x.id IS NULL")
    print("\n■ 🔴 完全没内容的 dict 行：{:,}".format(dead))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
