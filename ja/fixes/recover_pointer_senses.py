#!/usr/bin/env python3
"""修：指针义项从未到达读者 —— 3,891 个词搜得到、点进去完全空白。2026-09-16。

═══ 病灶：每一步都按自己的规矩做对了，跨步的那件事没人负责 ═══
阶段 1.5a **有意不出版指针义项**（`form-of`/`alt-of`/`romanization`），账上写着
「指针 7,637 条不出版，归阶段 2」。阶段 2 建 `alt_of` 关系时，认的是
`redirects` / `forms` 两个**结构字段** —— 而英文版把指针写在**义项正文里**：

    EU   → "EU; initialism of 欧州連合 (Ōshū rengō)"
    OS   → "abbreviation of オペレーティングシステム"
    AC   → "abbreviation of アーケード"
    佛   → "Kyūjitai form of 仏"
    見た  → "past form of 見る"

⇒ 5,144 条证据里只有 716 个词转成了关系，**3,891 个什么都没落地**。
   `[[correct-steps-can-compose-a-hole]]`：1.5a 没错、2 没错，
   「正文里的指针」这件事**两步都不认为是自己的**。

⚠️ 与阶段 5d 的 soft-redirect 是**同一个形状**：指针在证据层里躺着，
   没有任何一步负责把它送到读者面前。5d 那次是我自己撞见的，这次是
   **起了服务、真敲进搜索框**才看见的。

═══ 抽取：抓结构不抓词表 ═══
🔴 第一版我列了个关系词表（`alternative spelling|abbreviation|…`）⇒ 只认出 70.1%，
   漏掉的是 `Kyūjitai form of`／`past form of`／`Extended shinjitai form of` 这些
   我没想到的说法。**枚举永远列不全。**
⇒ 改成通用结构 `<短语> of|for <目标>`，覆盖率 **99.7%**（89 种短语）。

═══ 四个去向，按**这条指针在说什么**分 ═══
    A 异表记    → `sense_relation` kind=`alt_of`       （alternative form/spelling…）
    B 旧字体    → `sense_relation` kind=`kyujitai`     （Kyūjitai/shinjitai form）
    C 缩写      → `sense_relation` kind=`abbreviation` （short for/clipping/initialism…）
    D 活用形    → **`inflection`**，不是关系层         （past/polite/negative/imperative…）

🔴 D **必须进 `inflection`**。把「`見た` 是 `見る` 的过去形」写成一条语义关系，
   等于告诉读者那是两个词；它是同一个词的一个形。表选错了，标签再准也没用。
🔴 D 的中文名**复用 `infl_compose.compose()`**，不新写一张表 ——
   两张表迟早漂开（`[[refactor-mindset-code-quality]]`）。

跑（在仓库根）：
    python3 -u ja/fixes/recover_pointer_senses.py
    python3 -u ja/fixes/recover_pointer_senses.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import paths
from pipeline.infl_compose import compose

f = lambda n: format(n, ",")

# `<短语> of|for <目标>`。⚠️ 先剥 `EU; ` 这种前缀。
GEN = re.compile(r"^(.*?)\b(?:of|for)\s+(\S+)", re.I)

# ── 短语 → 去向。**89 种全部登记，不留"其他"桶** ──
# 🔴 `[[residual-bucket-is-not-evidence]]`：留一个"其他"桶，它会随判据变胖变瘦，
#    而我会拿它当证据。全部点名，点不到的当场报出来。
ALT = {"alternative form", "alternative spelling", "obsolete spelling", "obsolete form",
       "visual rendering", "misspelling", "rare spelling", "rare form",
       "eye dialect spelling", "nonstandard form", "nonstandard spelling",
       "uncommon spelling", "variant form", "variant", "alternative typography",
       "alternative name", "alternative or misspelling form", "dated form",
       "dialect form", "alternative letter-case form", "archaic form",
       "archaic spelling", "deliberate misspelling", "standard", "modern form",
       "katakana form", "kagoshima form", "classical japanese form",
       "classical japanese and literary form", "reduplicated form", "misconstruction",
       "subject", "alternative attributive form"}
KYU = {"kyūjitai form", "extended shinjitai form", "shinjitai form"}
ABBR = {"short", "abbreviation", "clipping", "initialism", "acronym", "contraction",
        "ellipsis", "symbol"}
# D：英文短语 → kaikki tag 集合，交给 `infl_compose.compose()` 出中文
INFL = {
    "conjunctive form": {"conjunctive"}, "past tense form": {"past"},
    "past form": {"past"}, "past": {"past"},
    "stem or continuative form": {"continuative"}, "continuative form": {"continuative"},
    "polite form": {"polite"}, "formal form": {"polite"},
    "negative": {"negative"}, "imperative": {"imperative"},
    "perfective": {"perfective"}, "perfective form": {"perfective"},
    "negative potential form": {"negative", "potential"},
    "informal form": {"informal"}, "adverbial form": {"adverbial"},
    "adverbial": {"adverbial"}, "adverbial and continuative stem": {"adverbial"},
    "passive": {"passive"}, "passive form": {"passive"},
    "potential form": {"potential"}, "potential": {"potential"},
    "volitional form": {"volitional"}, "negative continuative": {"negative", "continuative"},
    "honorific form": {"honorific"}, "humble form": {"humble"},
    "emphatic form": {"emphatic"}, "literary negative": {"negative"},
    "plural": {"plural"}, "attributive": {"attributive"},
    "attributive form": {"attributive"}, "past adnominal": {"past", "attributive"},
    "topicalized form": {"topicalized"}, "desiderative": {"desiderative"},
    "negative polite form": {"negative", "polite"}, "polite negative": {"negative", "polite"},
    "causative": {"causative"}, "polite perfective form": {"polite", "perfective"},
    "imperfective": {"imperfective"}, "polite imperfective": {"polite", "imperfective"},
    "present continuous": {"continuative"}, "nominalized form": {"nominalized"},
    "informal imperative": {"imperative", "informal"},
    "irrealis and adverbial": {"imperfective", "adverbial"},
    "polite volitional form": {"polite", "volitional"},
    "negative perfect": {"negative", "perfective"},
}


def classify(phrase):
    """→ ('rel', kind) / ('infl', 中文标签) / (None, 原因)。"""
    p = phrase.strip().lower()
    if p in ALT:
        return "rel", "alt_of"
    if p in KYU:
        return "rel", "kyujitai"
    if p in ABBR:
        return "rel", "abbreviation"
    if p in INFL:
        zh = compose(INFL[p])
        return ("infl", zh) if zh else (None, "compose 拼不出：%s" % p)
    return None, "短语没登记：%r" % p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    rows = list(con.execute(
        "SELECT x.id, x.word_id, d.word, x.text, x.src FROM sense_src x "
        "JOIN dict d ON d.id=x.word_id "
        "WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=x.word_id) "
        "AND NOT EXISTS(SELECT 1 FROM sense_relation r WHERE r.word_id=x.word_id)"))
    con.close()

    rels, infls, st = {}, {}, collections.Counter()
    unreg = collections.Counter()
    for sid, w_id, word, text, src in rows:
        m = GEN.match((text or "").strip())
        if not m:
            st["🔴 抓不到指针结构"] += 1
            continue
        phrase = re.sub(r"^.*?[;:]\s*", "", m.group(1).strip().lower())
        # 目标：去掉尾随的读音括注/标点
        tgt = re.split(r"[\s(（,，;；:：。]", m.group(2).strip())[0].rstrip("：:,，。")
        if not tgt or tgt == word:
            st["🔴 目标为空或指向自己"] += 1
            continue
        kind, val = classify(phrase)
        if kind is None:
            st["🔴 分不了类"] += 1
            unreg[val] += 1
            continue
        if kind == "rel":
            rels[(w_id, val, tgt)] = (w_id, None, val, tgt, None, 0, src,
                                      "%s:ptr:%d" % (src, sid))
            st["⭐ 关系 " + val] += 1
        else:
            infls[(w_id, tgt, val)] = (w_id, None, "inflection", tgt,
                                       wid.get(tgt), val, None, None, src,
                                       "%s:ptr:%d" % (src, sid))
            st["⭐ 活用 " + val] += 1
    for k in sorted(st):
        print("   %-28s %s" % (k, f(st[k])))
    if unreg:
        print("\n   🔴 没登记的短语（**必须补进表，不许留「其他」桶**）：")
        for r, n in unreg.most_common(8):
            print("      %4d  %s" % (n, r))
    # 🔴🔴 **§二.5 的规矩对新建的 alt_of 同样成立，而且必须连"库里已有的"一起算。**
    #    第一版只看本步新建的那批 ⇒ 33 个词形拿到了第 2 个**不同的**异体目标
    #    （有的是库里已有一条、本步又加一条），回归闸 F3 当场报红。
    #    这是阶段 5b 那个「聚合之后再判一次」的教训，我在**同一条规矩上**又漏了一次：
    #    上次漏的是"跨词条聚合"，这次漏的是"跨步骤聚合"。
    #    ⇒ 判据要问的始终是「**这个词形最终指向几个目标**」，不是「我这一步写了几个」。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have_alt = collections.defaultdict(set)
    for w_id, tgt in con.execute(
            "SELECT word_id, target FROM sense_relation WHERE kind='alt_of'"):
        have_alt[w_id].add(tgt)
    con.close()
    for (w_id, kind, tgt) in list(rels):
        if kind != "alt_of":
            continue
        have_alt[w_id].add(tgt)
    multi = {w for w, t in have_alt.items() if len(t) > 1}
    if multi:
        for k in [k for k in rels if k[1] == "alt_of" and k[0] in multi]:
            w_id, _kind, tgt = k
            row = rels.pop(k)
            rels[(w_id, "see_also", tgt)] = (w_id, None, "see_also", tgt, *row[4:])
        print("   ⚪ 聚合后 ≥2 目标 ⇒ 降级 see_also：%s 个词形"
              "（含库里已有的那批一起降）" % f(len(multi)))

    covered = len({r[0] for r in rels} | {i[0] for i in infls})
    print("\n■ 关系 %s 条｜活用 %s 条｜覆盖词元 %s / %s"
          % (f(len(rels)), f(len(infls)), f(covered), f(len({r[1] for r in rows}))))
    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        return

    with dbtool.session("ja-recover-pointers", expect={
            "#sense_relation": len(rels), "#inflection": len(infls),
            "__rows__": 0, "#entry": 0, "#sense": 0, "#example": 0}) as con:
        # 存量 alt_of 里落进 multi 的，一并降级 —— 新旧混着才是真实状态
        if multi:
            con.executemany(
                "UPDATE sense_relation SET kind='see_also'"
                " WHERE kind='alt_of' AND word_id=?", [(w,) for w in multi])
        con.executemany(
            "INSERT OR IGNORE INTO sense_relation"
            "(word_id,sense_id,kind,target,tags,hidden,src,src_ref) VALUES(?,?,?,?,?,?,?,?)",
            list(rels.values()))
        con.executemany(
            "INSERT OR IGNORE INTO inflection"
            "(word_id,entry_id,kind,base,base_id,label_zh,desc_en,tags,src,src_ref)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)", list(infls.values()))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("空白词元大幅下降（<600）", q(
            "SELECT COUNT(*) FROM dict d WHERE d.is_lemma=1"
            " AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
            " AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)"
            " AND NOT EXISTS(SELECT 1 FROM sense_relation r WHERE r.word_id=d.id)") < 600),
        ("新建的关系不指向自己", q(
            "SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id"
            " WHERE d.word=r.target") == 0),
        ("新建的活用不指向自己", q(
            "SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id=i.word_id"
            " WHERE d.word=i.base") == 0),
        ("活用都有中文标签", q(
            "SELECT COUNT(*) FROM inflection WHERE src_ref LIKE '%:ptr:%'"
            " AND (label_zh IS NULL OR label_zh='')") == 0),
        # 🔴 §二.5 那条规矩对新建的 alt_of 同样成立
        ("没有词形被断言成 ≥2 个不同词的异体", q(
            "SELECT COUNT(*) FROM (SELECT word_id FROM sense_relation WHERE kind='alt_of'"
            " GROUP BY word_id HAVING COUNT(DISTINCT target)>1)") == 0),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    con.close()
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
