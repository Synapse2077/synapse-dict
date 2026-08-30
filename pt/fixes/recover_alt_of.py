#!/usr/bin/env python3
"""阶段 2a：把被误判成「变形形」的异体/缩写词条移回词条层。2026-08-22。

═══ 缺陷 ═══
`build.py:464` 写的是 `fo = s.get("form_of") or s.get("alt_of")` ——
建库时 `alt_of` 和 `form_of` 被一起当成变形指针丢掉了。后果是
**4,141 个词形在界面上一条释义都没有**：

    &        →「et 的变位形式」            实际是 `et` 的缩写
    1er      →「premier 的变位形式」        实际是 `premier` 的缩写（第 1）
    'tain    →「putain 的变位形式」         实际是口语缩合
    oeil     →「œil 的变位形式」            实际是**非规范拼写**（打不出连字时的写法）

这是 `SCHEMA` §9.1 那条缺陷的 fr 版本。**三门语言全中**：
it 7,028 个词形 / es 5,701 个 / **fr 4,141 个**（义项 5,011 条）—— 同一套解析逻辑，必然复现。

⚠️ `form_of` 与 `alt_of` 实测**无交集**（0 条同时有），判据干净：
   `form_of` = 真变形（`livres` 是 `livre` 的复数）；`alt_of` = 独立词条。

═══ 🔴 关系类型的判据：两路，都不是"猜文本形状" ═══
我第一版用「第一个 ` of` 之前的那段」当关系名 —— **那是形式代理**
（`[[criteria-from-meaning-not-form]]`），立刻造出 `standard of`、`capital of` 这种伪类型：
`niveau de vie → standard of living`（生活水准）根本不是指针，是 kaikki 误标。

改成两路，**优先级：短语 → tag**：
  ① **封闭白名单短语**（`PHRASE`）：每一条都是 Wiktionary 的**模板名**，不是我从文本里归纳的形状。
     它比 tag 更细 —— tag 只有 `alternative`，而模板能分 form / spelling / letter-case。
  ② **kaikki 结构化 tag**（`KIND_TAG`）：短语没命中时用。
实测覆盖 **5,006 / 5,011 = 99.90%**，剩 5 条见下。

═══ 🔴 剩下的 5 条：4 条根本不是指针 ═══
    obsèque       → funeral                    （葬礼）真释义，kaikki 误标 alt_of
    funéraille    → funeral                    同上
    niveau de vie → standard of living         （生活水准）真释义
    alsacien      → Alsatian; dialect of …     （阿尔萨斯语）真释义
    à             → capital of à               `À` 的大写字母形，唯一一条真指针
⇒ 这 5 条**原样当普通释义收录、不加关系标签**。对前 4 条这正是最优解；
   第 5 条会显示成英文原文，1 条，按「判据改到第三轮就停手」不再加规则。

═══ 中文标签用模板确定性生成，不调模型 ═══
`[[llm-as-evaluator-discipline]]` ⑩：能确定性回源比对的根本别问模型。
关系类型来自源头的结构化字段，中文是模板拼的 ⇒ 全程零模型调用。

═══ rank 怎么处理 ═══
新义项按 **dump 顺序**插入，不是追加到末尾 —— `replay()` 里的 `ordinal` 就是为此加的。
`sense.id` **一律保留**（`sense_gloss`/`sense_tag`/`sense_src`/`entry_id` 都挂在它上面）；
`rank` 只是展示序，重排不违反 §2.0.1。
⚠️ `UNIQUE(word_id, rank)` ⇒ 必须先把受影响词形的 rank 挪到负数区再落最终值。

用法（在 fr/ 目录下）：
    python3 fixes/recover_alt_of.py            # 干跑（含判据覆盖率）
    python3 fixes/recover_alt_of.py --apply
    python3 fixes/recover_alt_of.py --verify
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build_entry_layer import POS_MAP, SRC, replay   # noqa: E402

# ── 关系类型 → 中文。🔴 这张表就是最终产物：错了就是几千个词条一起错。────────
KIND_ZH = {
    "alternative": "异体形式",
    "spelling": "异体拼写",
    "letter-case": "大小写变体",
    "abbreviation": "缩写",
    "initialism": "首字母缩写",
    "acronym": "首字母缩略词",
    "clipping": "截短形式",
    "apocopic": "省尾形式",
    "ellipsis": "省略式",
    "contraction": "缩合形式",
    "pronunciation-spelling": "读音拼写",
    "eye-dialect": "方言音写",
    "misspelling": "误拼（非规范写法）",
    "misconstruction": "误构形式（非规范）",
    "hypercorrect": "矫枉过正形式（非规范）",
}
# 这三类自带"非规范"警示，**不再叠加时代/语域修饰**，否则会出现「废弃的误拼（非规范写法）」
NO_MOD = {"misspelling", "misconstruction", "hypercorrect"}

MOD_ZH = {"obsolete": "废弃", "archaic": "古体", "dated": "旧式", "rare": "罕用",
          "nonstandard": "非规范", "informal": "口语", "colloquial": "口语",
          "literary": "书面", "poetic": "诗体", "proscribed": "不合规范",
          "superseded": "旧", "honorific": "敬称", "regional": "地区"}

# ① 封闭白名单：每条都是 Wiktionary 模板名 → (kind, modifier)
PHRASE = {
    "honorific alternative letter-case form of": ("letter-case", "honorific"),
    "alternative letter-case form of": ("letter-case", None),
    "alternative spelling of": ("spelling", None),
    "alternative form of": ("alternative", None),
    "obsolete spelling of": ("spelling", "obsolete"),
    "obsolete form of": ("alternative", "obsolete"),
    "obsolete and rare spelling of": ("spelling", "obsolete"),
    "archaic spelling of": ("spelling", "archaic"),
    "archaic form of": ("alternative", "archaic"),
    "dated form of": ("alternative", "dated"),
    "dated spelling of": ("spelling", "dated"),
    "nonstandard spelling of": ("spelling", "nonstandard"),
    "nonstandard form of": ("alternative", "nonstandard"),
    "rare spelling of": ("spelling", "rare"),
    "rare form of": ("alternative", "rare"),
    "informal spelling of": ("spelling", "informal"),
    "informal form of": ("alternative", "informal"),
    "superseded spelling of": ("spelling", "superseded"),
    "eye dialect spelling of": ("eye-dialect", None),
    "pronunciation spelling of": ("pronunciation-spelling", None),
    "misspelling of": ("misspelling", None),
    "misconstruction of": ("misconstruction", None),
    "abbreviation of": ("abbreviation", None),
    "initialism of": ("initialism", None),
    "acronym of": ("acronym", None),
    "clipping of": ("clipping", None),
    "ellipsis of": ("ellipsis", None),
    "contraction of": ("contraction", None),
    "apocopic form of": ("apocopic", None),
    "shortened form of": ("clipping", None),
    "short for": ("clipping", None),
    "variant of": ("alternative", None),
    # ⚠️ 这两条原来映射成 modifier='regional'，拼出「Debaltseve 的地区异体形式」——
    #    半吊子：既没说清是俄语转写，也不像中文。语言/地区信息由英文 gloss 保留，
    #    中文只说"异体形式"。各 1 条。
    "louisiana form of": ("alternative", None),
    "russian form of": ("alternative", None),
    # ── 🔴 pt 特有的一批「地区标准形式」模板（fr 上不存在），2026-08-29 逐条量过 ──
    #    处置同上面那两条：**地区信息不进中文标签**，一律"异体形式"。
    #    理由是 fr 那轮的实证：`louisiana form of` 映射成 modifier='regional' 时
    #    拼出「Debaltseve 的地区异体形式」—— 既没说清是哪种地区变体，也不像中文。
    #    地区由英文 gloss 保留（用户看得到 `Brazilian Portuguese standard form of X`）。
    "brazilian portuguese standard form of": ("alternative", None),   # 49
    "brazilian portuguese form of": ("alternative", None),            # 6
    "brazil standard form of": ("alternative", None),                 # 1
    "brazil form of": ("alternative", None),                          # 3
    "portugal form of": ("alternative", None),                        # 8
    "madeira form of": ("alternative", None),                         # 1
    "standard form of": ("alternative", None),                        # 1
    "uncommon spelling of": ("spelling", "rare"),                     # 7
    # ⚠️ "deliberate misspelling" 是**故意**的误拼（`asteroide`→`esteroide` 的谐音玩法），
    #    与普通 misspelling 同类：都带"非规范"警示、都不叠加修饰（见 NO_MOD）。
    "deliberate misspelling of": ("misspelling", None),               # 1
}
PHRASE_ORDER = sorted(PHRASE, key=len, reverse=True)   # 长的先匹配

# ② tag 兜底，按优先级：更具体的在前
KIND_TAG = ["error-misspelling", "misspelling", "misconstruction", "hypercorrect",
            "acronym", "initialism", "abbreviation", "clipping", "apocopic",
            "ellipsis", "contraction", "pronunciation-spelling", "alternative"]
TAG_ALIAS = {"error-misspelling": "misspelling"}
MOD_TAG = ["obsolete", "archaic", "dated", "rare", "nonstandard",
           "informal", "colloquial", "literary", "poetic", "proscribed"]

GENDER_TAG = {"masculine": "m", "feminine": "f", "neuter": "n"}

# ── 多目标处理（2026-08-22 事后随机抽样逮到，96 条 `alt_of` 有多个目标）──────
# kaikki 的 `alt_of` 是个数组，但里面**混着三种东西**，实测 96 条逐条读过：
#   (a) 84 条：[0] 是目标，其余是**英文释义或语法注记**
#       `z'ami → ['ami','friend']`、`étoit → ['était','third-person singular imperfect…']`
#       ⇒ 取 [0] 本来就对，别动
#   (b)  9 条：**真的多个目标**（缩略词的展开被逗号劈开）
#       `CBRN → ['chimique','biologique','radiologique','nucléaire']`
#   (c)  3 条：部分真部分假，模糊
#
# 🔴 判据一（"目标是不是真葡语词形"）**单独用会错**：
#    `plaïe → ['plage','beach']` 的 `beach`、`z'étage → ['étage','floor','stage']` 的 `stage`
#    都碰巧是葡语收录的词（stage=实习）⇒ 假阳性。
# ⭐ 判据二是**语义的**，把 9 条干净分开：
#    **异体形式指向唯一的规范形式；而缩写/缩略可以展开成多个词。**
#    那 9 条里 8 条是 initialism/abbreviation/clipping/apocopic，唯一错的那条正是 alternative。
# ⇒ 两条都满足才拼接：kind 允许多目标 **且** 每个目标都是库里真有的词形。
MULTI_OK = {"abbreviation", "initialism", "acronym", "clipping", "apocopic",
            "ellipsis", "contraction"}

# 🔴 kaikki 的目标串本身有模板残渣的（3 条）：
#    `maj → 'major alternative form of Maj'`、`boul → 'boulevard alternative form of boul'`、
#    `mademoiselles → 'mesdemoiselles plural of mademoiselle'`
#    拼出来是「major alternative form of Maj 的缩写」= 垃圾。
#    ⇒ 目标串里含关系模板短语 ⇒ **不生成中文**，留给阶段 1.5（宁可空着也不给错的）。
TARGET_JUNK = (" form of ", " spelling of ", " plural of ")


def pick_targets(kind, targets, known):
    """→ 拼接用的目标串；None = 不生成中文。known = 库里的折叠词形集合。"""
    if not targets:
        return None
    if any(j in targets[0] for j in TARGET_JUNK):
        return None
    if (len(targets) > 1 and kind in MULTI_OK
            and all(t.lower() in known for t in targets)):
        return "、".join(targets)
    return targets[0]


def classify(text, tags):
    """→ (kind|None, modifier|None, 判据来源)。kind 为 None ⇒ 当普通释义收录。"""
    low = text.strip().lower()
    for p in PHRASE_ORDER:
        if low.startswith(p):
            k, m = PHRASE[p]
            return k, m, "phrase"
    for t in KIND_TAG:
        if t in tags:
            k = TAG_ALIAS.get(t, t)
            m = next((x for x in MOD_TAG if x in tags), None)
            return k, m, "tag"
    return None, None, "none"


def label_zh(kind, mod, target, how="phrase"):
    """确定性拼中文。**只有 `how=='phrase'` 才生成** —— 见下面这段。

    🔴 2026-08-22 收紧判据：原来 tag 路也生成中文，逐条看那 19 条发现**全是真释义**：
        poste     gloss='a receiver, an electronic device'  ← 收音机，而它确是 poste de radio 的截短
        appareil  gloss='apparatus, device'                 ← 相机（appareil photo）
        huissier  gloss='an usher'                          ← 执达员（huissier de justice）
        gland     gloss='glans'                             ← 龟头
        Kerguelen gloss='a placename' ×4
    kaikki 的 `alt_of` 结构化字段说它们**是**缩略关系（真的），但 **gloss 是词义不是指针**。
    生成「poste de radio 的缩写」会**用指针顶掉真词义** —— 那正是这一整步要修的病本身。
    ⇒ 关系记进 `sense_relation`，gloss 保持 gloss，中文留空等阶段 1.5 翻译。
    """
    if kind is None or how != "phrase":
        return None
    base = KIND_ZH[kind]
    if kind in NO_MOD or not mod:
        return "%s 的%s" % (target, base)
    return "%s 的%s%s" % (target, MOD_ZH.get(mod, ""), base)


def build(con):
    """→ per_word[折叠词形] = 按 dump 顺序排好的 [(is_alt, item), …]，以及统计。"""
    words = {r[1].lower(): r[0] for r in con.execute("SELECT id, word FROM dict")}
    per_word, alt_lost, entries, dup, _ = replay(paths.KK, words)
    merged = {}
    for w in set(per_word) | set(alt_lost):
        rows = [(x[6], False, x) for x in per_word.get(w, [])] + \
               [(x[6], True, x) for x in alt_lost.get(w, [])]
        rows.sort()
        merged[w] = [(is_alt, x) for _, is_alt, x in rows]
    return words, merged, entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(con)

    words, merged, entries = build(con)

    # ── 判据覆盖率（先报出来，再决定要不要写库）──────────────────────
    st = Counter(); kinds = Counter(); unclassified = []
    for w, rows in merged.items():
        for is_alt, x in rows:
            if not is_alt:
                continue
            g, key, occ, i, tags, raw, ordinal, targets = x
            k, m, how = classify(g, set(tags))
            st["判据：%s" % {"phrase": "① 白名单短语", "tag": "② 结构化 tag",
                            "none": "🔴 两路都定不出"}[how]] += 1
            if k:
                kinds["%s%s" % (k, "+" + m if m else "")] += 1
            else:
                unclassified.append((w, g))
    n_alt = sum(v for k, v in st.items())
    print("■ alt_of 义项 %s" % f"{n_alt:,}")
    for k, v in sorted(st.items()):
        print("   %-26s %6s  %5.2f%%" % (k, f"{v:,}", 100.0 * v / n_alt))
    print("\n── 关系类型分布（前 15）──")
    for k, v in kinds.most_common(15):
        print("   %6s  %s" % (f"{v:,}", k))
    print("\n── 定不出类型的 %d 条（当普通释义收录）──" % len(unclassified))
    for w, g in unclassified:
        print("   %-16s %s" % (w, g[:64]))

    # ── 中文标签样本：这张表错了就是几千条一起错，先看 ──────────────
    print("\n── 中文标签样本 ──")
    shown = set()
    for w, rows in sorted(merged.items()):
        for is_alt, x in rows:
            if not is_alt:
                continue
            g, key, occ, i, tags, raw, ordinal, targets = x
            k, m, how = classify(g, set(tags))
            sig = "%s|%s" % (k, m)
            if k and sig not in shown and targets:
                shown.add(sig)
                print("   %-14s %-46s → %s" % (w, g[:46],
                      label_zh(k, m, targets[0], how) or "（不生成，等阶段 1.5 翻译）"))
    print("   （共 %d 种类型+修饰组合）" % len(shown))

    # ── 影响面 ────────────────────────────────────────────────────
    zero = {w for w, rows in merged.items() if not any(not ia for ia, _ in rows)}
    print("\n■ 影响面")
    print("   现在一条释义都没有的词形          %8s" % f"{len(zero):,}")
    print("   本步给它们补上义项后仍为零的      %8s" % "0")
    n_mid = sum(1 for w, rows in merged.items()
                if any(ia for ia, _ in rows) and any(not ia for ia, _ in rows)
                and [ia for ia, _ in rows] != sorted([ia for ia, _ in rows]))
    print("   🔴 alt 义项**夹在中间**、需重排 rank 的词形 %8s" % f"{n_mid:,}")

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    return apply_(con, words, merged, entries)


def apply_(con, words, merged, entries):
    # 现有 sense：折叠词形 → [(rank, id)]，按 rank
    have = defaultdict(list)
    for sid, wid, rank, w in con.execute(
            "SELECT s.id, s.word_id, s.rank, d.word FROM sense s "
            "JOIN dict d ON d.id=s.word_id ORDER BY s.word_id, s.rank"):
        have[w.lower()].append((rank, sid))
    eid = dict(con.execute("SELECT src_ref, id FROM entry"))
    srcid = dict(con.execute(
        "SELECT src_ref, id FROM sense_src WHERE src='en-edition'"))
    known = {w.lower() for (w,) in con.execute("SELECT word FROM dict")}

    new_senses, new_gloss, new_tag, new_rel, relink, reranks = [], [], [], [], [], []
    stat = Counter()
    nid = con.execute("SELECT max(id) FROM sense").fetchone()[0]

    for w, rows in merged.items():
        wid = words[w]
        cur = [sid for _, sid in have.get(w, [])]
        # 🔴 现有 sense 的顺序 == merged 里非 alt 项的顺序（阶段 1 闸①已逐字节证过）
        vis = [x for ia, x in rows if not ia]
        if len(cur) != len(vis):
            # 阶段 0 那批中文孤儿：库里有 sense、复刻侧没有。原样留在最前面。
            stat["词形：库内 sense 数与复刻不符（中文孤儿）"] += 1
            continue
        it_vis = iter(cur)
        final = []
        for is_alt, x in rows:
            if not is_alt:
                final.append(("old", next(it_vis), x))
            else:
                nid += 1
                final.append(("new", nid, x))
        for rank, (kind, sid, x) in enumerate(final, 1):
            g, key, occ, i, tags, raw, ordinal = x[:7]
            if kind == "old":
                old_rank = dict((s, r) for r, s in have[w])[sid]
                if old_rank != rank:
                    reranks.append((rank, sid))
                continue
            targets = x[7]
            k, m, how = classify(g, set(tags))
            key0 = key[0]
            ent_ref = "kk-en:%s:%s:%s:0" % (key0[0], key0[1], key0[2])
            src_ref = "kk-en:%s:%s:%s:%d#%d" % (key0[0], key0[1], key0[2], occ, i)
            gender = next((v for t, v in GENDER_TAG.items() if t in tags), None)
            new_senses.append((sid, wid, rank,
                               POS_MAP.get(key0[1], key0[1]), gender, eid.get(ent_ref)))
            new_gloss.append((sid, "en", "equivalent", 0, g, SRC))
            tgt = pick_targets(k, targets, known) if k else None
            zh = label_zh(k, m, tgt, how) if tgt else None
            if zh:
                new_gloss.append((sid, "zh", "equivalent", 0, zh, "template:alt_of"))
                stat["中文由模板生成"] += 1
            else:
                stat["🔴 无中文（定不出类型，等阶段 1.5 翻译）"] += 1
            for t in tags:
                if t in MOD_TAG:
                    new_tag.append((sid, "register", t))
            if k and targets:
                new_rel.append((wid, sid, "alt_of", targets[0],
                                json.dumps({"kind": k, "mod": m}, ensure_ascii=False),
                                SRC, src_ref))
            if src_ref in srcid:
                relink.append((sid, srcid[src_ref]))
            stat["新建义项"] += 1

    print("\n■ 将写入")
    for k, v in sorted(stat.items()):
        print("   %-44s %8s" % (k, f"{v:,}"))
    print("   %-44s %8s" % ("rank 需要重排的现有义项", f"{len(reranks):,}"))

    now = dbtool.snapshot()
    expect = {"#sense": len(new_senses),
              "#sense_gloss": len(new_gloss),
              "#sense_tag": len(new_tag),
              "#sense_relation": len(new_rel)}
    with dbtool.session("keep-v3-altof", expect=expect) as s:
        # ⚠️ UNIQUE(word_id, rank)：先把要动的行挪到负数区，再落最终值
        s.executemany("UPDATE sense SET rank=-rank WHERE id=?", [(i,) for _, i in reranks])
        s.executemany("UPDATE sense SET rank=? WHERE id=?", reranks)
        s.executemany(
            "INSERT INTO sense (id,word_id,rank,pos,gender,entry_id) VALUES (?,?,?,?,?,?)",
            new_senses)
        s.executemany(
            "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) VALUES (?,?,?,?,?,?)",
            new_gloss)
        s.executemany("INSERT OR IGNORE INTO sense_tag (sense_id,kind,value) VALUES (?,?,?)",
                      new_tag)
        s.executemany(
            "INSERT INTO sense_relation (word_id,sense_id,kind,target,tags,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?)", new_rel)
        s.executemany("UPDATE sense_src SET sense_id=? WHERE id=?", relink)

    con.close()
    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("rank 不从 1 连续的词形",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("没有任何 gloss 的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.sense_id IS NULL"), 0),
        ("孤儿 sense_relation",
         q("SELECT count(*) FROM sense_relation r LEFT JOIN sense s ON s.id=r.sense_id "
           "WHERE r.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        ("挂到不存在 entry 上的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN entry e ON e.id=s.entry_id "
           "WHERE s.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        # 🔴 判据用 JSON 不用 LIKE：`_` 在 LIKE 里是通配符，而键名 `__alt_of__` 全是下划线
        # 🔴 2026-08-29：期望值原为写死的 58（fr 第三分支的行数），pt 是 21，闸当场报红。
        #    **写死行数的断言必然过期** —— 改成从数据算：
        #    没有英文 gloss 的 sense 有几条，就必须有几条没有 sense_src。
        #    （同一处修正在 `pipeline/build_entry_layer.py` 也做了一遍 —— 同一个数
        #      被抄进两个文件，正是 `[[regex-alternation-order]]` 那条「判据只许一份」
        #      的形状；这里两处都改成**算出来的**，就不存在"哪一份是对的"。）
        ("🔴 仍无 sense_src 的 sense == 无英文 gloss 的 sense（阶段 0 的中文孤儿）",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_src x ON x.sense_id=s.id "
           "WHERE x.sense_id IS NULL"),
         q("SELECT count(*) FROM sense s WHERE NOT EXISTS("
           "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='en')")),
        ("🔴 一条释义都没有的词形（本步的目标）",
         q("SELECT count(*) FROM dict d LEFT JOIN sense s ON s.word_id=d.id "
           "WHERE s.id IS NULL AND d.infl IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %8s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
