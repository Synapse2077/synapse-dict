#!/usr/bin/env python3
"""阶段 2c：变形层补链 —— 把阶段 3 新收的变形接回它的词元。2026-08-30。

═══ 这个洞是怎么来的（阶段顺序错，不是数据错）═══
阶段 2b 建 `inflection` 时**只读英文版每个词条自己的 `form_of`**（「我是 X 的某某形式」），
那时库里只有 411,802 个词形。阶段 3 之后库涨到 769,012 —— 新收的 357,210 个词形
绝大多数来自各版**变位表**（`forms` 数组），**没有任何一步给它们连过线**。

实测（2026-08-30）：

    词形 769,012
      有可见义项              79,111   10.3%
      是变形、有链接能跳词元   339,567   44.2%
      🔴 孤儿                355,605   46.2%   ← 查得到词，点进去空白页
           其中 is_lemma=1    46,015          → 新词头，阶段 1.5 的对象（要花钱）
           其中 is_lemma=0   309,590          → **本步的对象**

⚠️ **对照组证明这不是语言属性**：fr 同一口径的孤儿率只有 **1.8%**（37,239 条，几乎全是词缀）。
   fr 的变形层是从法语版变位表建的，天然覆盖到；pt 走的是英文版 `form_of` 那条路。

═══ 方向反了：`form_of` 是「我是谁的形式」，`forms` 是「我有哪些形式」═══
两条路互补，不重复：

    form_of（2b 用）  变形页 → 词元    只有变形**自己建了页**才有
    forms  （本步用）  词元页 → 变形    词元页的变位表，覆盖全套变位

⇒ 本步的父词元**按构造就在手里**：走 `entry["forms"]` 时，`entry["word"]` 就是词元。
  不需要解析、不需要猜、不需要模型。

═══ 判据：哪些 `forms` 行算「变形」═══
🔴 **不能全收。** 阶段 2 已经定过一条规矩：**只收 `form_of`，`alt_of` 归词条层**
（`&` 是 `e` 的缩写，不是 `e` 的变位形式）。`forms` 数组里同样混着两类：

    真变形    带 person/number/tense/mood/gender 这类**屈折** tags
    非变形    `alternative`（异体拼写）/ `abbreviation` / 无 tags 的裸词形

判据写在 `is_inflection()` 一处，**按含义**（"这条 tags 描述的是屈折范畴吗"），
不按形状（不写"tags 多于 N 个"这类代理，`[[criteria-from-meaning-not-form]]`）。

═══ 三道闸 ═══
① 不变量：不动任何已有行（en-edition 计数恒定）／`base_id` 指向真词元／
   `src_ref` 无重复／`label_zh` 非空／不与已有 (word_id, base, label) 重复。
② 账：孤儿数必须真的降下来（这一步的目的就是它）。
③ **抽样反验**：随机打 25 条给人眼核。`forms` 表把 A 和 B 关联起来对不对，
   不变量证明不了 —— `[[criteria-narrower-than-you-think]]` 的老教训。

用法（在 pt/ 目录下）：
    python3 pipeline/link_table_forms.py --tags     # 先看 tags 分布，判据从数据里长出来
    python3 pipeline/link_table_forms.py            # 干跑 + 三道闸预演
    python3 pipeline/link_table_forms.py --apply
"""
import argparse
import gzip
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from infl_compose import compose   # noqa: E402
from intake_edition_words import EDITIONS, _real_forms, norm_apos   # noqa: E402

# ══════ 判据只许一份：什么是「屈折范畴」══════
# 🔴 按**含义**列：这些 tag 描述的是"同一个词的不同语法形式"。
#    `alternative`/`abbreviation`/`obsolete` 描述的是"另一个写法"⇒ 不是变形，归词条层。
INFLECTION_TAGS = {
    # 人称·数
    "first-person", "second-person", "third-person", "singular", "plural",
    # 式
    "indicative", "subjunctive", "imperative", "conditional",
    # 时
    "present", "past", "future", "imperfect", "preterite", "pluperfect",
    # 非限定形式
    "infinitive", "personal", "gerund", "participle", "participle-2", "supine",
    # 性·级（形容词/名词的屈折）
    "feminine", "masculine", "neuter", "comparative", "superlative", "augmentative",
    "diminutive",
    # 否定命令式（葡语的 não + 虚拟式，见 intake 文件头）
    "negative",
}
# 明确**不是**变形的（出现这些就整条不收，哪怕同时带屈折 tag）
NOT_INFLECTION_TAGS = {
    "alternative", "abbreviation", "alt-of", "obsolete", "archaic", "rare",
    "romanization", "table-tags", "inflection-template", "class", "error",
}


# 🔴 **单独成格的表格残渣。** 判据按含义写：
#    葡语的否定命令式是「`não` + 虚拟式」——**两个词**（`não abdiques`）。
#    光一个 `não` 是否定小品词占了变位表的一格，**永远不可能是某个动词的形式**。
#    实测：它被 **618 个不同词元**当成变形（真变形不会同时属于 618 个词元）。
#    ⚠️ `não` 本身是真葡语词（副词/叹词/名词），**只拒绝它当"形式"，不动它的词条**。
BARE_TABLE_CELL = {"não"}


def is_inflection(tags):
    """→ 这一条 `forms` 行是不是屈折形式。判据只在这里。"""
    t = set(tags or [])
    if t & NOT_INFLECTION_TAGS:
        return False
    return bool(t & INFLECTION_TAGS)


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def scan(editions, want_tags=False):
    """→ (cands, stat, tagstat)

    cands[(form_word, parent_word)] = (pos_raw, tags, edition)   —— 同一对只留第一次见到的
    """
    cands, stat, tagstat = {}, Counter(), Counter()
    tagsample = defaultdict(list)
    for ed in editions:
        path, filt = EDITIONS[ed]
        if not path.exists():
            stat["🔴 dump 不存在：" + ed] += 1
            continue
        with opener(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if filt and e.get("lang_code") != "pt":
                    continue
                w = norm_apos((e.get("word") or "").strip())
                if not w:
                    continue
                # 🔴 **变形页自己的变位表不收。** 各版都给变位形式单独建页，
                #    那些页的小表里列的是**兄弟形式**（`átonas` 的页列出 `átonos`）。
                #    照收写出来的是「átonos 是 átonas 的阳性复数」——两个都是变形，
                #    谁也不是词元。不变量闸五条全绿，只有抽样看得见（2026-08-30 实测逮到）。
                #
                #    ⚠️ 判据用**源头**的 `form_of`/`alt_of`，不用我们自己的 `is_lemma` ——
                #    后者是我们打的标，拿它当判据是拿自己的工具当真值
                #    （`[[measure-landing-not-source]]` / `PITFALLS` C3）。
                #    ⚠️ 判据是「**除了指针什么都没有**」不是「含指针」——
                #    `amo` 既是名词「主人」（真词元）又是 `amar` 的第一人称单数，
                #    含指针就整页丢会把它的名词复数 `amos` 一起丢掉。
                sn_ = e.get("senses") or []
                ptr = [bool(x.get("form_of") or x.get("alt_of")) for x in sn_]
                if all(ptr):                       # 空 senses 也算（没有真义项）
                    stat["变形页的变位表（不收）"] += 1
                    continue
                if any(ptr):
                    stat["混合页（既是词元又是别人的变形，照收）"] += 1
                pos_raw = e.get("pos") or ""
                for fm in (e.get("forms") or []):
                    tags = fm.get("tags") or []
                    for x in _real_forms(fm, ed):
                        x = norm_apos(x)
                        if x == w:
                            continue
                        if x in BARE_TABLE_CELL:
                            stat["单独成格的小品词（不收）"] += 1
                            continue
                        if want_tags:
                            k = "|".join(sorted(tags)) or "(无 tags)"
                            tagstat[k] += 1
                            if len(tagsample[k]) < 3:
                                tagsample[k].append("%s → %s" % (x, w))
                            continue
                        if not is_inflection(tags):
                            stat["非屈折（不收）"] += 1
                            continue
                        stat["候选"] += 1
                        cands.setdefault((x, w), (pos_raw, tags, ed))
        stat["扫完 " + ed] += 1
    return cands, stat, (tagstat, tagsample)


def load(con):
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    have = {(r[0], r[1], r[2])
            for r in con.execute("SELECT word_id, base, label_zh FROM inflection")}
    ent = defaultdict(list)
    for eid, wid, pos in con.execute("SELECT id, word_id, pos FROM entry"):
        ent[wid].append((pos, eid))
    return ids, have, ent


def orphans(con):
    return con.execute(
        "SELECT COUNT(*) FROM dict d "
        " WHERE NOT EXISTS(SELECT 1 FROM entry e JOIN sense s ON s.entry_id=e.id"
        "                   WHERE e.word_id=d.id)"
        "   AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)").fetchone()[0]


def build(con, cands):
    """→ (rows, stat)  rows 直接进 inflection

    🔴 **方向必须核。** 各版都给变位形式单独建页，那些页里也有 `forms` 小表。
       如果小表里列着词元本身，照收就会写出一条**反向**的链
       （`falar 是 falávamos 的变位形式`）—— 不变量闸一条都逮不到：
       word_id 在库里 ✓ base_id 在库里 ✓ 不指向自己 ✓ label 非空 ✓。
       ⇒ 单独量「base 不是 lemma」和「A→B 且 B→A」两项，量出来再决定收不收。
    """
    from build_entry_layer import POS_MAP
    ids, have, ent = load(con)
    lemma = {i for (i,) in con.execute("SELECT id FROM dict WHERE is_lemma=1")}
    rows, stat, seen = [], Counter(), Counter()
    suspect = defaultdict(list)
    # 🔴 **双向链两个方向一起丢。** A→B 且 B→A 只可能是「兄弟形式互相列对方」
    #    （`filósofo ↔ filósofa`、`negra ↔ negro`、`cínica ↔ cínicas`），
    #    写进库就是"哲学家（阳）是哲学家（阴）的阳性形式"。
    #    只丢一个方向要判"哪边是词元"，而那正是 `is_lemma` 靠不住的地方
    #    （实测 7,870 条 base 不是 lemma 的链**全是对的**，是标错不是链错）。
    #    ⇒ 498 条对 478,184 条是 0.1%，按「**错比缺更伤权威**」两边都不要。
    both = {(x, w) for (x, w) in cands if (w, x) in cands}
    for (x, w), (pos_raw, tags, ed) in sorted(cands.items()):
        wid, bid = ids.get(x), ids.get(w)
        if wid is None:
            stat["🔴 变形不在库里（阶段 3 应已收全）"] += 1
            continue
        if bid is None:
            stat["词元不在库里（悬空，base_id=NULL）"] += 1
        elif bid not in lemma:
            stat["🔴 base 不是 lemma（方向可能反了）"] += 1
            suspect["base 不是 lemma"].append((x, w))
        if (x, w) in both:
            stat["双向链（两个方向一起丢）"] += 1
            suspect["双向链·已丢弃"].append((x, w))
            continue
        label = compose(tags)
        if not label:
            stat["label 退化成兜底「变位形式」"] += 1
            label = "变位形式"
        if (wid, w, label) in have:
            stat["已有同样的链接（不重收）"] += 1
            continue
        have.add((wid, w, label))
        pos = POS_MAP.get(pos_raw, pos_raw)
        eid = next((e for p, e in ent.get(wid, []) if p == pos), None)
        if eid is None:
            stat["词性对不上、entry_id 留空"] += 1
        k = (ed, w, pos_raw)
        seq = seen[k]
        seen[k] += 1
        rows.append((wid, eid, w, bid, label, None, json.dumps(sorted(tags)),
                     "%s-edition-forms" % ed,
                     "kk-%s:%s:%s#form%d" % (ed, w, pos_raw, seq)))
        stat["要写入"] += 1
    return rows, stat, suspect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tags", action="store_true", help="只看 tags 分布，不建行")
    # 🔴 **源清单只许一份** —— 从 `EDITIONS` 派生，不手抄。
    #    2026-08-30 实测：补下八个切片后只改了 `EDITIONS`，而这四个文件
    #    （relations/audio/examples/link_table_forms）各自手抄了一份默认值 ⇒
    #    **新源一个都没被扫**，`audio` 跑完行数一条没涨。
    #    `[[refactor-mindset-code-quality]]`：同一张表在两处各存一份，
    #    没分叉纯属运气。
    ap.add_argument("--editions", default=",".join(EDITIONS))
    ap.add_argument("--cache", help="把候选集存/读这个 JSON，省一次全量扫")
    a = ap.parse_args()
    eds = [e for e in a.editions.split(",") if e]

    cache = Path(a.cache) if a.cache else None
    if cache and cache.exists() and not a.tags:
        print("■ 读候选集缓存 %s" % cache)
        cands = {(k.split("\t")[0], k.split("\t")[1]): tuple(v)
                 for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
        stat, tagstat, tagsample = Counter({"从缓存读入": len(cands)}), Counter(), {}
    else:
        print("■ 扫 %s 版的 forms 数组 …" % "/".join(eds), flush=True)
        cands, stat, (tagstat, tagsample) = scan(eds, want_tags=a.tags)
        if cache and not a.tags:
            cache.write_text(json.dumps({"%s\t%s" % k: list(v) for k, v in cands.items()},
                                        ensure_ascii=False), encoding="utf-8")
            print("   候选集已缓存 → %s" % cache)

    if a.tags:
        print("\n── tags 组合分布（前 40）──")
        tot = sum(tagstat.values())
        for k, n in tagstat.most_common(40):
            mark = "  " if is_inflection(k.split("|")) else "✗ "
            print("%s%-52s %9s  %5.1f%%  %s"
                  % (mark, k[:52], f"{n:,}", 100 * n / tot, "; ".join(tagsample[k][:2])[:46]))
        print("\n   合计 %s ／ 判为屈折 %s (%.1f%%)"
              % (f"{tot:,}",
                 f"{sum(n for k, n in tagstat.items() if is_inflection(k.split('|'))):,}",
                 100 * sum(n for k, n in tagstat.items() if is_inflection(k.split("|"))) / tot))
        return 0

    for k, v in sorted(stat.items()):
        print("   %-38s %10s" % (k, f"{v:,}"))
    print("   %-38s %10s" % ("→ (变形, 词元) 去重后", f"{len(cands):,}"))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    before = orphans(con)
    before_en = con.execute(
        "SELECT COUNT(*) FROM inflection WHERE src='en-edition'").fetchone()[0]
    rows, bstat, suspect = build(con, cands)
    con.close()
    print()
    for k, v in sorted(bstat.items()):
        print("   %-38s %10s" % (k, f"{v:,}"))

    newly = {r[0] for r in rows}
    print("\n   孤儿（当前）        %s" % f"{before:,}")
    print("   本步能接上的词形    %s" % f"{len(newly):,}")

    for k, v in sorted(suspect.items()):
        print("\n── 可疑类「%s」共 %s，抽 12 条 ──" % (k, f"{len(v):,}"))
        random.seed(1)
        for x, w in random.sample(v, min(12, len(v))):
            print("   %-30s → %s" % (x[:30], w))

    print("\n── 抽样反验 25 条（forms 表的关联对不对，只有人眼看得出来）──")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    w_of = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
    con.close()
    random.seed(0)
    for r in random.sample(rows, min(25, len(rows))):
        print("   %-26s → %-22s %-26s %s"
              % (w_of.get(r[0], "?")[:26], r[2][:22], r[4][:26], r[7]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-2c-link-forms",
                        expect={"#inflection": len(rows)}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO inflection "
            "(word_id,entry_id,base,base_id,label_zh,desc_en,tags,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True), before, before_en)


def verify(con, before=None, before_en=None):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    after = orphans(con)
    checks = [
        # 🔴 期望值**从写库前取**，不许写死行数 ——
        #    `tests/test_no_literal_counts.py` 2026-08-30 当场逮到我把 400,330 写进了这里。
        ("🔴 2b 的 en-edition 变形链被动过（本步只许新增）",
         q("SELECT COUNT(*) FROM inflection WHERE src='en-edition'"), before_en),
        ("word_id 不在 dict",
         q("SELECT COUNT(*) FROM inflection i WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=i.word_id)"), 0),
        ("base_id 非空但不在 dict",
         q("SELECT COUNT(*) FROM inflection i WHERE i.base_id IS NOT NULL AND NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=i.base_id)"), 0),
        ("label_zh 为空",
         q("SELECT COUNT(*) FROM inflection WHERE TRIM(COALESCE(label_zh,''))=''"), 0),
        ("src_ref 重复",
         q("SELECT COUNT(*) FROM (SELECT src_ref FROM inflection GROUP BY 1 HAVING COUNT(*)>1)"), 0),
        # ⚠️ 下面两条**只查本步写的行**（`src LIKE '%-edition-forms'`）。
        #    第一版没限定范围，红了 1,370 + 20 —— 逐条读完发现**全是阶段 2b 的老账**，
        #    2c 自己的行是 0/0。闸红了先问「数据错了还是断言过期」，
        #    这次是第三种：**断言的范围比它该管的宽**（`[[criteria-narrower-than-you-think]]`）。
        #    两笔老账已进收尾单 C8/C9，不在这里悄悄带过。
        ("(word_id, base, label_zh) 重复（本步）",
         q("SELECT COUNT(*) FROM (SELECT word_id,base,label_zh FROM inflection"
           " WHERE src LIKE '%-edition-forms' GROUP BY 1,2,3 HAVING COUNT(*)>1)"), 0),
        ("跨 2b/2c 重复（同一关系两步各记一份）",
         q("SELECT COUNT(*) FROM (SELECT word_id,base,label_zh FROM inflection"
           " GROUP BY 1,2,3 HAVING COUNT(*)>1"
           " AND COUNT(DISTINCT src LIKE '%-edition-forms')>1)"), 0),
        # 🔴 **「变形不许指向自己」这条断言对葡语本来就不成立** ——
        #    规则动词的**人称不定式**与**虚拟式将来时**同形于不定式（`que eu orlar`），
        #    `-e` 结尾形容词阴阳同形（`avolescente` 的阴性就是它自己）。
        #    这两个时态正是 `pt-CONVENTIONS` 记的「es/fr 都没有」的葡语特有形式。
        #    ⇒ 只查本步，且**不当缺陷**；2b 那 20 条逐条读过后进收尾单 C9。
        ("变形指向自己（本步）",
         q("SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id=i.word_id"
           " WHERE d.word=i.base AND i.src LIKE '%-edition-forms'"), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-46s %10s  (期望 %s)" % ("✅" if ok else "🔴", name, f"{got:,}", f"{want:,}"))
    if before is not None:
        print("\n   孤儿 %s → %s  （降 %s）" % (f"{before:,}", f"{after:,}", f"{before - after:,}"))
        if after >= before:
            print("   🔴 孤儿没降，这一步的目的没达成")
            bad += 1
    print("\n%s" % ("✅ 全部通过" if not bad else "🔴 %d 条红" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
