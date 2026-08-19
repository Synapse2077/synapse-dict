#!/usr/bin/env python3
"""阶段 4 第三步：`dict.ipa` 一个列 → `pronunciation` 一读音一行。2026-08-17。

═══ 这一步在解决什么 ═══
`SCHEMA` §1.3 那条缺陷：**一个列只能存一个值，音标的变体正在被丢掉。**
第一步的普查（`probes/ipa_census.py`）把"丢了多少"数清了：

    三版并集里、我们有这个词形的      775,312 条 / 746,189 个词形
    现在 dict.ipa 列里                588,280 条（一词形一条，上限就是词形数）
    ⇒ 被列结构挤掉                   187,032 条；其中真·一词多读的词形 25,198 个

第二步（`probes/ipa_provenance.py`）把"现有这 588,280 条是谁写的"查清了：
**73.4% 是我们自己的 G2P 规则算的**（`rule`），dump 背书的只有 153,214 条。
⇒ 阶段 4 计划里"内容不用重做"这句只对了一半 —— 内容不重做，但**来源必须如实标**。

═══ 三条设计判断（每条都有替代方案被否掉的理由）═══

① **行键是 (word_id, 折排版后的音标, 记法)，不是原始字符串。**
   `ˈɡra.tis`（英文版/我们的 G2P）与 `ˈɡratis`（意语版）是同一个读音的两种排版。
   按原始串建行 ⇒ 每个词凭空多一条假变体（es 上正是这么把"多变体规模"虚报成 98.8%）。
   折的是什么、为什么不多折，见 `ipa_variants.cmp_key`。

② **同一个读音存哪一串字节：如果 `dict.ipa` 里正是这个读音，就存列里那串。**
   这样「从 `pronunciation` 逐字节重建 `dict.ipa`」不需要多插任何一行
   （否则 23,399 个词要各多一行、只差几个音节点 —— 纯污染）。
   代价说清楚：这 23,399 条的 `src` 写的是"哪一版背书了**这个读音**"，
   而字节上的音节切分是我们自己的约定。**背书的是读音，不是排版。**

③ **`entry_id` 只在能唯一确定时才写。**
   `SCHEMA` §10 立 entry 层的理由就是同形异读（`ancora` 名词 ˈankora / 副词 anˈkora）。
   但 `gratis` 的 adj 与 adv 共用同一个读音 ⇒ 一行挂不了两个 entry。
   ⇒ 源头里这个读音只属于一个 entry 时才写，否则 NULL（= 该词形各 entry 共用）。
   把 `UNIQUE(word_id,ipa,notation)` 拆开、给每个 entry 复制一行读音的方案否掉：
   那是 §10.2 已经论证过的"重复存 N 份"。

═══ is_primary：权威优先 ═══
每个词形选一条默认展示：`en > it > fr > rule > llm > unknown`，音位式优先。
es 的结论是**有权威源就用权威源，没有才派生**（`phoneticLatam` 的规则派生被证伪，
630 条错得有规律）。it 这边同一件事的规模是 **78,715 条**：库里是规则算的、
dump 里有权威值且不一致（`Gabon` 库 ˈɡa.bon / dump ɡaˈbɔn；`Madagascar`
库 ma.daˈɡas.kar / dump madaɡasˈkar —— 权威值对，规则的倒二重音默认错）。
⚠️ 其中 72,153 条的权威值**只有 fr 版给**，而 fr 版有已知噪声（`aw` 写成 `a.u`、
   `moˈŋgɔːlja` 那种）⇒ 这批要不要真的顶替，是阶段 8 切展示层时的决定，
   本步只把两条都落进表、并按上面的优先级标 is_primary。**本步不改 `dict.ipa` 一个字节。**

用法（在 it/ 目录下）：
    python3 pipeline/build_pronunciation_layer.py            # 干跑，只出数
    python3 pipeline/build_pronunciation_layer.py --apply
    python3 pipeline/build_pronunciation_layer.py --verify   # 闸
    python3 pipeline/build_pronunciation_layer.py --mutate   # 变异验证
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "probes"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool                                     # noqa: E402
import paths                                      # noqa: E402
from b_ipa import word_to_ipa                     # noqa: E402
from ipa_variants import (BLIND_SPOT, cmp_key, diff_kind, iter_source,   # noqa: E402
                          norm_ipa, variants_of)
from kaikki_util import unaccent                  # noqa: E402
from split_case_forms import APOSTROPHES           # noqa: E402

SOURCES = [("en-edition", paths.KK, None), ("it-edition", paths.EDITION, "it"),
           ("fr-edition", paths.KK_FR, None)]
# 同一个读音多版都给时，`src` 记优先级最高那版（"谁背书了这个读音"）。
# ⚠️ 这个顺序**只用来记来源**；选默认展示用的是 `trust_rank`，两者不是一回事。
PRIO = {"en-edition": 0, "it-edition": 1, "fr-edition": 2,
        "rule:accent": 3, "rule:plain": 4, "llm:doubao": 5, "unknown": 6}
SRCS = tuple(PRIO)
LEGACY = "dict.ipa"          # 列值锚点标记，写在 src_ref 末尾
f = lambda n: format(n, ",")


# ═══════════════════════════════════════════════════════════════════
# 判据本体（写入与闸共用；变异验证打的就是这两个函数）
# ═══════════════════════════════════════════════════════════════════
def row_key(word_id, ipa, notation):
    """一行 = 一个词形的一个读音的一种记法。"""
    return (word_id, cmp_key(ipa), notation)


def trust_rank(row, ours):
    """这一行有多可信（越小越可信）。**选默认展示用的就是它。**

    ═══ 为什么不是简单的 `en > it > fr > rule` ═══
    我原来的方案就是那个简单顺序，两家顾问一起把它否了，理由各不相同；
    我又回数据量了一遍，最终采的是 v4-pro 的分档方案，依据是两组实测：

      ① **三版互核**："另两版一致、只有它不同"的次数 —— fr 1,965 / it 1,038 / en 663。
         ⇒ fr 版偏离最多，不能让它全局顶替我们的值；en 版偏离最少，排第一。
         （这条同时否掉了豆包"意语版是母语编辑、该排英文版之前"的建议。）
      ② **G2P 的强弱面**：意语辅音正字法完全规则 ⇒ 音段我们算得准；
         猜不出的只有**重音位置 / e·o 开闭 / s·z 清浊**这三件事
         （`b_ipa` 顶部原话）。fr 版与有背书的层一致率 87%，而 G2P 光杆默认路径只有 57.2%。

    ⇒ **fr 版只在 G2P 的盲点上有覆盖权**：分歧仅落在重音/开闭/清浊时它排在规则之前；
      分歧含音段变化（`ˈnaw.ru` vs `naˈu.ru`、`ˈaːvatar`、`moˈŋgɔːlja` 的 `ŋg`）时
      它退到规则之后，只当备选。**这是"用长补短"，不是"用短换短"。**

    `ours` = 这个词形在库里原有的那条读音（`dict.ipa`），没有则 None。
    """
    src = row["src"]
    if src in ("en-edition", "it-edition"):
        return PRIO[src]
    # 档位：en 0 > it 1 > **rule:accent 2** > fr（只在盲点上）3 > rule:plain 4
    #       > fr（音段分歧）5 > llm 6 > unknown 7
    #
    # 🔴 **2026-08-18 修正：`rule:accent` 必须排在 fr 之前。**
    #    最初我把 fr 排在两条规则路径之前，理由是「fr 与有背书的层一致 87%」。
    #    回数据一量，那个理由不成立 —— 以 en/it 版为真值、同一批词形上比**重音位置**：
    #        rule:accent  83.9%      fr  64.5%      rule:plain  44.8%
    #    fr 版的意语**变形形音标本身就是机器按倒二默认生成的**，与我们的光杆路径同病：
    #        passano     fr pasˈsa.no      权威 ˈpas.sa.no
    #        applicano   fr ap.pliˈka.no   权威 ˈap.pli.ka.no
    #        denigrano   fr de.niˈɡra.no   权威 deˈni.ɡra.no
    #    词尾 -ano/-ono 且两边都有值的 6,846 个词形里，**66.8% 对不上**。
    #    ⇒ 让 fr 去顶替 `rule:accent`（重音由 kaikki 的带重音拼写定死）是拿差的换好的。
    #    fr 仍排在 `rule:plain` 之前（64.5% > 44.8%），也仍然是"我们没有值时"的主力来源。
    if src == "fr-edition":
        if ours is None:
            return 3                     # 没有可比的原值 ⇒ 它就是我们唯一的来源
        return 3 if diff_kind(cmp_key(row["ipa"]), cmp_key(ours)) in BLIND_SPOT else 5
    return {"rule:accent": 2, "rule:plain": 4}.get(src, 6 if src == "llm:doubao" else 7)


def primary_of(rows, ours=None):
    """一个词形的若干行里，哪一行当默认展示。

    音位式优先于严式；同级里让**列里那条**（用户现在看到的）稳定胜出；
    最后按字符串定序 —— 判据必须**全序**，否则两次跑出来的 is_primary 会不一样。
    """
    return sorted(rows, key=lambda r: (trust_rank(r, ours), r["notation"] != "phonemic",
                                       not r["legacy"], len(r["ipa"]), r["ipa"]))[0]


def collect(word_ids, verbose=True):
    """扫三版 dump → {行键: 行}，同时顺路建重音形映射（省一趟 761 MB 的扫描）。

    ⚠️ 重音形映射必须与 `b_ipa_fill.build_accent_map` **同口径**（first-seen 胜）——
       判定某行是不是规则产物，要复现它当初的生成路径，见 `probes/ipa_provenance.py`。
    """
    rows, amap = {}, {}
    for src, path, lc in SOURCES:
        c = Counter()
        for w, d in iter_source(path, src, lc):
            if src == "en-edition":
                for fm in (d.get("forms") or []):
                    form = (fm.get("form") or "").strip()
                    if form and any(ch in "àèéìíòóù" for ch in form):
                        amap.setdefault(unaccent(form), form)
            wid = word_ids.get(w)
            if wid is None:
                c["词形不在库里"] += 1
                continue
            for v in variants_of(d, src):
                k = row_key(wid, v.ipa, v.notation)
                old = rows.get(k)
                if old is None:
                    rows[k] = {"word_id": wid, "word": w, "ipa": v.ipa,
                               "notation": v.notation, "tags": list(v.tags),
                               "src": src, "src_ref": v.src_ref, "legacy": False,
                               "ent": {(v.pos, v.etym_no)}, "ent_src": src}
                    c["新读音"] += 1
                else:
                    # 同一读音多版都有：src 记最高优先级那版（背书强的），
                    # 但 entry 归属只认与 src 同一版的坐标，免得跨版对不上号
                    if PRIO[src] < PRIO[old["src"]]:
                        old.update(src=src, src_ref=v.src_ref, ipa=v.ipa,
                                   ent={(v.pos, v.etym_no)}, ent_src=src)
                    elif old["ent_src"] == src:
                        old["ent"].add((v.pos, v.etym_no))
                    for t in v.tags:
                        if t not in old["tags"]:
                            old["tags"].append(t)
                    c["并入已有读音"] += 1
        if verbose:
            print("     %-12s %s" % (src, dict(c)), flush=True)
    return rows, amap


def load_llm():
    """七月建库时模型答过的音标 → {词形: {cmp_key}}（只用于**如实标来源**）。"""
    out = defaultdict(set)
    for p in sorted((paths.WORK / "b_out").glob("chunk_*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for v in d.values():
            if isinstance(v, dict) and v.get("w") and v.get("ipa"):
                ip = v["ipa"]
                for one in (ip if isinstance(ip, list) else [ip]):
                    if isinstance(one, str) and one.strip():
                        out[v["w"]].add(cmp_key(one.strip().strip("/[]\\")))
    return out


def provenance(word, ipa, amap, llm):
    """列值这一条读音是谁写的（dump 命中已在调用点判掉）。

    → `rule:accent`（走带重音形路径算出来的）/ `rule:plain`（光杆词形默认路径）
      / `llm:doubao` / `unknown`。

    🔴 **两条规则路径必须分开记**，这是 v4-pro 提的、我原方案里漏掉的一点：
       带重音形路径把重音位置与 e/o 开闭都定死了（自证 strict≈83%），
       光杆默认路径靠"倒二音节 + 闭元音"猜，与有背书的层只有 57.2% 一致。
       混成一个 `rule` 就没法让 fr 版只顶替后者。
    🔴 判定顺序必须**复现当初的生成路径**（`b_ipa_fill`：先查重音形，查不到才用光杆）——
       否则会把 112,209 行误判（`kaikki_util.sounds_and_accent_map` 顶部记着那次）。
    """
    k = cmp_key(ipa)
    acc = amap.get(unaccent(word))
    if acc:
        rv = word_to_ipa(acc)
        if rv and cmp_key(rv.strip("/[]\\")) == k:
            return "rule:accent"
    rv = word_to_ipa(word)
    if rv and cmp_key(rv.strip("/[]\\")) == k:
        return "rule:plain"
    return "llm:doubao" if k in llm.get(word, ()) else "unknown"


def word_index(con):
    """dump 里的词形 → 该落到哪个 `dict.id`。

    🔴 **不能直接用 `{word: id}`**：`fixes/merge_apostrophe_variants.py` 把 267 组
       「只差撇号写法」的行合并过了 —— 内容（entry/sense）全搬到直撇号那行，
       弯撇号那行成了空壳，`ItalianDictService.getEntry` 也是这么路由的。
       dump 里的词形写的是弯撇号 ⇒ 直接按词形查会把读音落到**空壳**上，
       用户查 `all’estero` 命中的是直撇号那行，看不到这些读音。
       （2026-08-17 闸② 报「entry 与词形对不上 98 行」就是这么逮到的。）
    """
    ids = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    has_entry = {i for (i,) in con.execute("SELECT DISTINCT word_id FROM entry")}
    moved = 0
    for w, i in list(ids.items()):
        if i in has_entry:
            continue
        ascii_w = w.translate(APOSTROPHES)
        j = ids.get(ascii_w)
        if ascii_w != w and j is not None and j in has_entry:
            ids[w] = j
            moved += 1
    return ids, moved


def build(con, verbose=True):
    """→ (行列表, 词级 ipa_src, 统计)。纯计算，不写库。"""
    d = con.execute("SELECT id, word, ipa FROM dict").fetchall()
    word_ids, moved = word_index(con)
    if verbose and moved:
        print("■ 撇号空壳行改指向合并后的那一行：%s 个词形" % f(moved), flush=True)
    col = {i: ipa for i, w, ipa in d if (ipa or "").strip()}
    if verbose:
        print("■ 扫三版 dump（顺路建重音形映射）", flush=True)
    rows, amap = collect(word_ids, verbose)
    if verbose:
        print("     dump 给的读音行 %s；重音形映射 %s 条" % (f(len(rows)), f(len(amap))),
              flush=True)
        print("■ 把 dict.ipa 列并进来（列里有、dump 没有的要新建行）", flush=True)
    llm = load_llm()
    c = Counter()
    for i, w, _ in d:
        ipa = col.get(i)
        if not ipa:
            continue
        k = row_key(i, ipa, "phonemic")
        r = rows.get(k)
        if r is None:                       # dump 没这个读音 ⇒ 新建一行，来源如实标
            src = provenance(w, ipa, amap, llm)
            rows[k] = {"word_id": i, "word": w, "ipa": ipa, "notation": "phonemic",
                       "tags": [], "src": src, "src_ref": "%s:%d" % (LEGACY, i),
                       "legacy": True, "ent": set(), "ent_src": None}
            c["列值新建行·" + src] += 1
        else:
            # 判断②：这个读音存列里那串字节，重建列时不必多插一行
            if r["ipa"] != ipa:
                c["同读音·排版按列值（背书的是读音不是排版）"] += 1
                r["ipa"] = ipa
            else:
                c["列值与 dump 逐字节相同"] += 1
            r["legacy"] = True
            r["src_ref"] += "|" + LEGACY

    # entry 归属：源头里这个读音只属于一个 (pos, 词源号) 时才挂
    # ⚠️ 词源号**不一定是整数**：子条目改挂时写成过 `1.2` 这类复合号
    #    （`fixes/reroute_subentry_defs.py`）。int() 会当场炸 ⇒ 一律按**字符串**比，
    #    对不上的就是 entry_id 空，不硬凑。
    ent_id, by_pos = {}, defaultdict(set)
    for eid, src, ref in con.execute("SELECT id, src, src_ref FROM entry"):
        try:
            body, pos, etym, _seq = ref.rsplit(":", 3)
        except ValueError:
            continue
        w = body.split(":", 1)[1]
        ent_id[(src, w, pos, etym)] = eid
        by_pos[(w, pos)].add(eid)
    for r in rows.values():
        r["entry_id"] = None
        if len(r["ent"]) != 1 or not r["ent_src"]:
            continue                    # 该读音被多个词条共用 ⇒ NULL（= 各词条共用）
        pos, etym = next(iter(r["ent"]))
        eid = ent_id.get((r["ent_src"], r["word"], pos, str(etym)))
        if eid is None:
            # 退一步：词源号跨版不可比（各版自己编号），但**词性**可比。
            # 该词形在这个词性下只有一个 entry 时才挂 —— 多于一个就说明要靠词源号区分，
            # 而我们没有跨版的词源号对应关系，硬挑一个就是编造。
            cands = by_pos.get((r["word"], pos)) or set()
            eid = next(iter(cands)) if len(cands) == 1 else None
        r["entry_id"] = eid
    c["挂上 entry 的行"] = sum(1 for r in rows.values() if r["entry_id"])

    # is_primary：每个词形一条
    by_word = defaultdict(list)
    for r in rows.values():
        r["is_primary"] = 0
        by_word[r["word_id"]].append(r)
    for wid, rs in by_word.items():
        primary_of(rs, col.get(wid))["is_primary"] = 1
    c["词形数"] = len(by_word)
    for rs in by_word.values():
        p = [r for r in rs if r["is_primary"]][0]
        if p["legacy"] or not any(x["legacy"] for x in rs):
            continue
        c["is_primary 换成了权威值（阶段 8 切展示层时用户会看到变化）"] += 1
        c["  └ 其中权威值来自 " + p["src"]] += 1

    # 词级 ipa_src = 列里那条读音的来源（背书的是读音）
    ipa_src = {r["word_id"]: r["src"] for r in rows.values() if r["legacy"]}
    return list(rows.values()), ipa_src, c


def anchor_set(cached=False, verbose=True):
    """外锚：三版 dump 里**应有**的 (词形, 折排版后的音标, 记法, 版本) 全集。

    🔴 这道闸锚的是**外部 dump**，不是我们自己上一版的数据 ⇒ **永不过期**
       （`external-anchor-gates`：锚自己上一版的闸必然过期，锚 dump 的永远有效）。
       只有它能逮住「notation 被改了」「某一版的行被删了」这类改动 ——
       库内不变量对这些是瞎的（改了 notation，行数、is_primary、可逆性全都还是绿的）。

    `cached=True` 读 `probes/ipa_census.py` 落的 TSV（秒级），只在**变异验证**里用：
    那时要连跑七八遍，验的是"判据能不能逮住改动"，不是"dump 有没有变"。
    """
    out = set()
    if cached:
        for src, _p, _lc in SOURCES:
            p = paths.WORK / "ipa_census" / ("%s.tsv" % src)
            if not p.exists():
                sys.exit("🔴 缺 %s —— 先跑 probes/ipa_census.py" % p)
            for i, ln in enumerate(p.open(encoding="utf-8")):
                if i == 0:
                    continue
                c = ln.rstrip("\n").split("\t")
                if len(c) < 8:
                    continue
                out.add((c[0], cmp_key(c[3]), c[4], src))
        return out
    for src, path, lc in SOURCES:
        n = 0
        for w, d in iter_source(path, src, lc):
            for v in variants_of(d, src):
                out.add((v.word, cmp_key(v.ipa), v.notation, src))
                n += 1
        if verbose:
            print("     %-12s %s 条" % (src, f(n)), flush=True)
    return out


def gate(con, anchor=None):
    """闸。判据都用**全量**，不抽样。`anchor` 给了就一并跑外锚双向核对。"""
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = []

    # ① 可逆性回核：从 pronunciation 逐字节重建 dict.ipa（全量，非抽样）
    legacy = {}
    dup = 0
    for wid, ipa, ref in con.execute(
            "SELECT word_id, ipa, src_ref FROM pronunciation WHERE src_ref LIKE '%|"
            + LEGACY + "' OR src_ref LIKE '" + LEGACY + ":%'"):
        if wid in legacy:
            dup += 1
        legacy[wid] = ipa
    col = {i: ipa for i, ipa in con.execute(
        "SELECT id, ipa FROM dict WHERE trim(COALESCE(ipa,''))<>''")}
    bad = sum(1 for i, ipa in col.items() if legacy.get(i) != ipa)
    checks += [("🔴 ① 从表逐字节重建 dict.ipa：对不上的行", bad, 0),
               ("🔴 ① 一个词形只有一个列值锚点", dup, 0),
               ("🔴 ① 锚点数 == 列非空数（%s）" % f(len(col)), len(legacy), len(col))]

    # ② 不变量
    checks += [
        ("🔴 ② 孤儿行（word_id 不在 dict）",
         q("SELECT count(*) FROM pronunciation p WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=p.word_id)"), 0),
        ("🔴 ② entry_id 指向不存在的 entry",
         q("SELECT count(*) FROM pronunciation p WHERE p.entry_id IS NOT NULL AND NOT EXISTS"
           "(SELECT 1 FROM entry e WHERE e.id=p.entry_id)"), 0),
        ("🔴 ② entry 与词形对不上（挂到别的词头上了）",
         q("SELECT count(*) FROM pronunciation p JOIN entry e ON e.id=p.entry_id "
           "WHERE e.word_id <> p.word_id"), 0),
        ("🔴 ② 每个词形恰好一条 is_primary",
         q("SELECT count(*) FROM (SELECT word_id, sum(is_primary) s FROM pronunciation "
           "GROUP BY word_id HAVING s<>1)"), 0),
        ("🔴 ② ipa 不许带定界符或空白",
         q("SELECT count(*) FROM pronunciation WHERE ipa LIKE '%/%' OR ipa LIKE '%[%' "
           "OR ipa <> trim(ipa) OR ipa=''"), 0),
        ("🔴 ② notation 只有两种",
         q("SELECT count(*) FROM pronunciation WHERE notation NOT IN ('phonemic','narrow')"), 0),
        ("🔴 ② src 只有这七种",
         q("SELECT count(*) FROM pronunciation WHERE src NOT IN (%s)"
           % ",".join("'%s'" % x for x in SRCS)), 0),
        ("🔴 ③ dict.ipa_src 为空的行（证明不了写 unknown，但不许空）",
         q("SELECT count(*) FROM dict WHERE trim(COALESCE(ipa,''))<>'' "
           "AND trim(COALESCE(ipa_src,''))=''"), 0),
        ("🔴 ③ 没音标却有 ipa_src 的行",
         q("SELECT count(*) FROM dict WHERE trim(COALESCE(ipa,''))='' "
           "AND trim(COALESCE(ipa_src,''))<>''"), 0),
        ("🔴 ③ ipa_src 与表里那条锚点的 src 不一致",
         q("SELECT count(*) FROM dict d JOIN pronunciation p ON p.word_id=d.id "
           "WHERE (p.src_ref LIKE '%|" + LEGACY + "' OR p.src_ref LIKE '" + LEGACY
           + ":%') AND p.src <> d.ipa_src"), 0),
    ]

    # ④ normalize 往返（全量）+ 行键唯一
    #    ⚠️ 行键判据**不能写成 SQL**：`cmp_key` 要保留「元音.元音」的点，
    #       SQL 里用 replace 串起来做不到（第一版就是那么写的，等于换了一把尺子去验）。
    #       ⇒ 在 Python 里用**同一个** cmp_key 跑全量。
    n_bad = c_bad = 0
    keys = Counter()
    for wid, ipa, notation in con.execute(
            "SELECT word_id, ipa, notation FROM pronunciation"):
        if norm_ipa(norm_ipa(ipa)) != norm_ipa(ipa):
            n_bad += 1
        if cmp_key(cmp_key(ipa)) != cmp_key(ipa):
            c_bad += 1
        keys[(wid, cmp_key(ipa), notation)] += 1
    checks += [("🔴 ④ norm(norm(x))==norm(x) 全量", n_bad, 0),
               ("🔴 ④ cmp(cmp(x))==cmp(x) 全量", c_bad, 0),
               ("🔴 ④ 同词形同记法下折排版后重复的行",
                sum(1 for v in keys.values() if v > 1), 0)]

    # ⑤ 外锚双向核对（全量，非抽样）
    if anchor is not None:
        have = set()
        for w, ipa, notation, src in con.execute(
                "SELECT d.word, p.ipa, p.notation, p.src FROM pronunciation p "
                "JOIN dict d ON d.id=p.word_id"):
            have.add((w, cmp_key(ipa), notation, src))
        # ⚠️ 外锚的词形要走**与写入同一套路由**（撇号空壳 → 合并后那行），
        #    否则 267 组撇号词会两个方向都报红：dump 写弯撇号、表里落在直撇号那行。
        ids, _ = word_index(con)
        id2word = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
        want_anchor = {(id2word[ids[w]], k, nt, s) for w, k, nt, s in anchor if w in ids}
        edition_rows = {x for x in have if x[3].endswith("-edition")}
        # ⚠️ 两个方向的判据**不一样**，这不是笔误：
        #    正向要带 src（"标了 en 版就必须真在 en 版里"）；
        #    反向**必须去掉 src** —— 一个读音多版都给时，行上只记优先级最高那版，
        #    带 src 比会把 fr 版那条算成"漏收"（第一版就是这么写的，全是假红）。
        by_reading = {x[:3] for x in have}
        checks += [
            ("🔴 ⑤ 表里标了某版、而那版 dump 里查不到的行",
             len(edition_rows - want_anchor), 0),
            ("🔴 ⑤ dump 有、表里没有的读音（漏收）",
             len({x[:3] for x in want_anchor} - by_reading), 0),
        ]

    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-52s %s (期望 %s)"
              % ("✅" if got == want else "🔴", name, f(got) if isinstance(got, int) else got,
                 f(want) if isinstance(want, int) else want))
    return ok


def mutate():
    """变异验证：判据本体 + 阶段 4 判据 6 要求的「删 3 条音标、改 2 条 notation」。"""
    print("═══ 变异验证 A：行键与 is_primary 判据 ═══")
    R = lambda ipa, src, notation="phonemic", legacy=False: {
        "ipa": ipa, "src": src, "notation": notation, "legacy": legacy}
    cases = [
        ("🔴 只差音节点算同一行", row_key(1, "ˈɡra.tis", "phonemic")
         == row_key(1, "ˈɡratis", "phonemic"), True),
        ("🔴 只差 tie-bar 算同一行", row_key(1, "me.diˈt͡ʃi.ne", "phonemic")
         == row_key(1, "mediˈtʃine", "phonemic"), True),
        ("🔴 只差滑音写法算同一行（ˈaj/ˈai）", row_key(1, "ˈaj", "phonemic")
         == row_key(1, "ˈai", "phonemic"), True),
        ("🔴 hiatus 与 glide 不许合并（ˈɛ.u.ro / ˈɛw.ro）",
         row_key(1, "ˈɛ.u.ro", "phonemic") != row_key(1, "ˈɛw.ro", "phonemic"), True),
        ("🔴 hiatus 与 glide 不许合并（paˈla.u / paˈlaw）",
         row_key(1, "paˈla.u", "phonemic") != row_key(1, "paˈlaw", "phonemic"), True),
        ("重音位置不同是两行", row_key(1, "ˈɡa.bon", "phonemic")
         != row_key(1, "ɡaˈbɔn", "phonemic"), True),
        ("记法不同是两行", row_key(1, "a", "phonemic") != row_key(1, "a", "narrow"), True),
        ("词形不同是两行", row_key(1, "a", "phonemic") != row_key(2, "a", "phonemic"), True),
        ("英文版优先于法语版", primary_of([R("x", "fr-edition"), R("y", "en-edition")])["ipa"], "y"),
        ("音位式优先于严式", primary_of([R("x", "en-edition", "narrow"),
                                 R("y", "en-edition")])["ipa"], "y"),
        # ↓ fr 版的覆盖权：只在 G2P 的盲点上（重音/开闭/清浊）
        ("🔴 fr 版顶替规则值：分歧只是重音位置",
         primary_of([R("ˈɡa.bon", "rule:plain", legacy=True), R("ɡaˈbon", "fr-edition")],
                    ours="ˈɡa.bon")["src"], "fr-edition"),
        ("🔴 fr 版**不许**顶替：长音符（aˈva.tar / ˈaːvatar）",
         primary_of([R("aˈva.tar", "rule:plain", legacy=True), R("ˈaːvatar", "fr-edition")],
                    ours="aˈva.tar")["src"], "rule:plain"),
        ("🔴 fr 版**不许**顶替：辅音数量（aberˈrate / abberˈrate）",
         primary_of([R("a.berˈra.te", "rule:plain", legacy=True),
                     R("ab.berˈra.te", "fr-edition")], ours="a.berˈra.te")["src"], "rule:plain"),
        ("🔴 fr 版**不许**顶替：ŋg 那类非意语音段",
         primary_of([R("monˈɡo.lja", "rule:plain", legacy=True),
                     R("moˈŋgɔːlja", "fr-edition")], ours="monˈɡo.lja")["src"], "rule:plain"),
        # 🔴 2026-08-18 加：fr 版在**重音**上实测只有 64.5%，而带重音形路径 83.9%
        #    ⇒ 哪怕分歧正好落在盲点上，也不许 fr 顶掉 rule:accent
        ("🔴 rule:accent 不许被 fr 的「盲点顶替」挤掉",
         primary_of([R("ˈpas.sa.no", "rule:accent", legacy=True), R("pasˈsa.no", "fr-edition")],
                    ours="ˈpas.sa.no")["src"], "rule:accent"),
        ("fr 仍优先于光杆路径（64.5% > 44.8%）",
         primary_of([R("ˈpas.sa.no", "rule:plain", legacy=True), R("pasˈsa.no", "fr-edition")],
                    ours="ˈpas.sa.no")["src"], "fr-edition"),
        ("🔴 带重音形路径的规则值优先于 fr 版的音段分歧",
         primary_of([R("aˈva.tar", "rule:accent", legacy=True), R("ˈaːvatar", "fr-edition")],
                    ours="aˈva.tar")["src"], "rule:accent"),
        ("没有原值可比时，fr 版就是唯一来源",
         primary_of([R("naˈu.ru", "fr-edition")], ours=None)["src"], "fr-edition"),
        ("🔴 同级时列值胜出（结果必须稳定）",
         primary_of([R("x", "rule:plain"), R("y", "rule:plain", legacy=True)])["ipa"], "y"),
        ("🔴 判据必须全序（换个顺序结果不变）",
         primary_of([R("y", "rule:plain", legacy=True), R("x", "rule:plain")])["ipa"], "y"),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-44s → %s%s" % ("✅" if good else "🔴", name, got,
                                      "" if good else "（期望 %s）" % want))

    print("\n═══ 变异验证 B：闸能不能逮住数据被改坏 ═══")
    print("   （在**备份的副本**上改，不动活库）")
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    shutil.copy(paths.DB, tmp)
    muts = [
        ("删 3 条音标（其中含列值锚点）",
         "DELETE FROM pronunciation WHERE id IN (SELECT id FROM pronunciation "
         "WHERE src_ref LIKE '%|" + LEGACY + "' OR src_ref LIKE '" + LEGACY
         + ":%' LIMIT 3)"),
        ("改 2 条 notation",
         "UPDATE pronunciation SET notation='narrow' WHERE id IN "
         "(SELECT id FROM pronunciation WHERE notation='phonemic' LIMIT 2)"),
        ("把 1 条音标改一个字节",
         "UPDATE pronunciation SET ipa=ipa||'x' WHERE id IN (SELECT id FROM pronunciation "
         "WHERE src_ref LIKE '%|" + LEGACY + "' LIMIT 1)"),
        ("把 1 条 entry_id 挂到别的词头",
         "UPDATE pronunciation SET entry_id=(SELECT id FROM entry WHERE word_id<>"
         "pronunciation.word_id LIMIT 1) WHERE id=(SELECT min(id) FROM pronunciation)"),
        ("抹掉 5 条 ipa_src", "UPDATE dict SET ipa_src=NULL WHERE id IN "
         "(SELECT id FROM dict WHERE ipa_src IS NOT NULL LIMIT 5)"),
        ("把 1 个词形改成两条 is_primary",
         "UPDATE pronunciation SET is_primary=1 WHERE word_id=(SELECT word_id FROM "
         "pronunciation GROUP BY word_id HAVING count(*)>1 LIMIT 1)"),
    ]
    anchor = anchor_set(cached=True, verbose=False)
    caught = 0
    for name, sql in muts:
        c2 = sqlite3.connect(tmp)
        c2.execute(sql)
        c2.commit()
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            good = gate(c2, anchor)
        c2.close()
        shutil.copy(paths.DB, tmp)      # 每次只变一处
        caught += (not good)
        print("   %s %s" % ("✅ 逮住" if not good else "🔴 没逮住", name))
    ok &= caught == len(muts)
    print("\n   变异验证 %s（%d/%d）" % ("通过" if ok else "🔴 有洞", caught, len(muts)))
    return ok


def restamp(dry=True):
    """只重算 `is_primary`，不动任何一行的内容。

    改了 `trust_rank` 的档位之后不必重扫 761 MB 的 dump —— 判据要的
    （每行的 `src` / `ipa` / 记法 / 是不是列值锚点，以及该词形的原值）库里全有。
    """
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    col = {i: ipa for i, ipa in ro.execute(
        "SELECT id, ipa FROM dict WHERE trim(COALESCE(ipa,''))<>''")}
    by_word = defaultdict(list)
    for rid, wid, ipa, notation, src, ref, prim in ro.execute(
            "SELECT id, word_id, ipa, notation, src, src_ref, is_primary FROM pronunciation"):
        by_word[wid].append({"id": rid, "ipa": ipa, "notation": notation, "src": src,
                             "legacy": LEGACY in ref, "was": prim})
    ro.close()
    flip = []
    for wid, rs in by_word.items():
        win = primary_of(rs, col.get(wid))
        for r in rs:
            want = 1 if r is win else 0
            if want != r["was"]:
                flip.append((want, r["id"]))
    print("■ is_primary 要改的行 %s（词形 %s 个）"
          % (f(len(flip)), f(len({1 for _ in flip}) and len(flip) // 2)))
    if dry:
        print("(未加 --apply，不写库)")
        return 0
    with dbtool.session("restamp-pronunciation-primary", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE pronunciation SET is_primary=? WHERE id=?", flip)
    print("■ 已重标 %s 行" % f(len(flip)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate", "cached", "restamp"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.restamp:
        return restamp(dry=not a.apply)
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        print("■ 建外锚（%s）" % ("读普查缓存 —— ⚠️ 只在赶时间时用" if a.cached else "重扫三版 dump"),
              flush=True)
        return 0 if gate(ro, anchor_set(cached=a.cached)) else 1
    if a.mutate:
        ro.close()
        return 0 if mutate() else 1

    rows, ipa_src, c = build(ro)
    ro.close()
    print("\n■ 要落表 %s 行 / %s 个词形" % (f(len(rows)), f(c["词形数"])))
    for k, v in c.most_common():
        print("     %-46s %s" % (k, f(v)))
    by_src = Counter(r["src"] for r in rows)
    print("   按来源：" + "  ".join("%s %s" % (k, f(v)) for k, v in by_src.most_common()))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("build-pronunciation-layer",
                        expect={"__rows__": 0, "#pronunciation": len(rows),
                                "ipa_src": len(ipa_src)}) as s:
        if "entry_id" not in {r[1] for r in s.execute(
                "PRAGMA table_info(pronunciation)")}:
            s.execute("ALTER TABLE pronunciation ADD COLUMN entry_id INTEGER")
        s.executemany(
            "INSERT INTO pronunciation (word_id, entry_id, ipa, notation, region, tags,"
            " is_primary, src, src_ref) VALUES (?,?,?,?,NULL,?,?,?,?)",
            [(r["word_id"], r["entry_id"], r["ipa"], r["notation"],
              json.dumps(r["tags"], ensure_ascii=False) if r["tags"] else None,
              r["is_primary"], r["src"], r["src_ref"]) for r in rows])
        # 词级来源：`region` 一律 NULL —— 意语没有 es 那种半岛/拉美两分，
        # 方言限定（Milan / Romanesco / Monopoli，合计约 600 条）留在 tags 里，
        # 硬塞成地区码就是编造。
        s.executemany("UPDATE dict SET ipa_src=? WHERE id=?",
                      [(v, k) for k, v in ipa_src.items()])
    print("\n■ 已落表 %s 行；dict.ipa_src 回填 %s 行" % (f(len(rows)), f(len(ipa_src))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
