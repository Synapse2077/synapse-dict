#!/usr/bin/env python3
"""阶段 2：**重音层**。ru，2026-10-08。九门里第一次有这一层。

═══ 这一层是什么 ═══
俄语的重音**辨义**（`замо́к` 锁／`за́мок` 城堡）**而且屈折时会移动**，
学习者词典不标重音是重大缺陷。而 `RU_PLAN` §2.3 实测出来的事实是：
**重音不住在词头里（0.00%），住在 `forms` 里。**

本层交付的是「**这个词条的带重音正字拼写**」：
    真值 → `stress` 表（一个 entry 可以有多个候选，带 `variant_seq`/`is_primary`）
    展示 → `entry.stressed` 派生列（从 `is_primary=1` 那行取）
照 ko 的 `entry.hanja` ＋ `hanja_spelling` 先例（`RU_PLAN` §5.1 裁决 C＋E）。
⚠️ **屈折表每一格各自的重音不在这一层**，它是阶段 3 的 `inflection.stressed`。

═══ 🔴🔴 本层最贵的一课：我的候选判据比它要描述的东西窄了一半 ═══
第一版候选判据是「`forms[].tags` 含 `canonical` 或 `stressed`」—— 那是**源头的 tag**，
而不是「这是这个词头的带重音拼写」这件事本身。实测：

    只收 canonical/stressed    词元覆盖 **15.73%**
    判据按含义写（剥重音后 ＝ 词头）  词元覆盖 **37.18%**   ← ＋137,325 个词元

差额全在 ru 版：它供了我们 **97.6% 的词元**，却几乎不给 `canonical`
（只有 2,367 条专用的 `stressed`）；词元自己的带重音拼写**躺在变位表里**，
标着 `['singular','nominative']` —— 主格单数那一行就是词元本身：

    агат → ага́т   ['singular', 'nominative']

⇒ `[[criteria-narrower-than-you-think]]`，而这一次它值 21 个百分点。
   判据的家在 `criteria.stressed_spelling`，tag **只当来源（`src`）不当门槛**。

═══ ⭐ 判定只有一个等式，所以修复可以写得宽 ═══
「剥掉重音符之后等于词头」是**唯一**的判定。于是 `criteria._repairs` 那一串
修复（空白、游离组合符、连字符旁空格、尾部残渣、同形异义编号、不可见字符）
**怎么写都放不进一条垃圾** —— 修完还要再过那个等式。等式是修复自己的闸。

🔴 而修复自己造过一个坑：`крем для бритья ́`（游离的重音符）被修掉之后，
   剩下的串与词头一字不差 —— 一条「源头标坏了」被静默修成了一条
   「看起来正常而没有信息」的行。印在读者页的「重音写法」栏里，它**比空着更坏**。
   ⇒ 与词头相同的候选一律不收（6,172 行），而**这一批要分两个数报**：
     2,897 个是含 ё 的（ё 永远重读、源头不另标符，**本来就无需标注**）、
     170 个单音节，而 **167 个是多音节而源头标坏了 —— 那是缺口不是「无需」**。
     （vi 的 `coverage.blank_split()`：**返回两个数不是一个**。）

═══ 🔴 `is_primary` 挑谁：这里只有一个弱信号，所以如实登记成欠账 ═══
实测 ≥2 个候选的 3,896 个 entry 里，**92.74% 的两个候选重音位置不同**
（`алфа́вит`／`алфави́т`、`Укра́ина`／`Украи́на`、`Бого́та`／`Богота́`）。
⚠️ 这推翻了 §5.1 的说法：那里量的是「字母串相同」(93.7%)，
   而那件事对「**该印哪一个**」一个字都没说。

挑主行的判据按**来源可信度 ＋ 源头给出的顺序**：
  ① `stressed`（ru 版专为这件事存在的字段，还带同形异义区分）
  ② `canonical`（词头展示模板给的规范拼写）
  ③ `无标签` / `语法标签`（从变位表反推出来的）
同一档内按**源头行序**（wiktextract 保留了模板顺序，第一个就是维基词典印在词头上的那个）。
🔴 **这是一个弱信号，别假装它强**：全部候选都落库（`variant_seq`），
   `is_primary` 只是默认展示值。欠账 **R14**，推翻条件写在 `RU_PLAN`。
"""
import argparse
import collections
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

# 来源可信度的档位。**小的优先。** 见文件头「`is_primary` 挑谁」。
PROV_RANK = {"stressed": 0, "canonical": 1, "无标签": 2, "语法标签": 3}


def provenance(tags):
    """这一行 `forms` 的来源身份 —— **只决定 `src` 与排序，不决定收不收**。"""
    ts = set(tags or [])
    if "canonical" in ts:
        return "canonical"
    if "stressed" in ts:
        return "stressed"
    return "无标签" if not ts else "语法标签"


def collect(limit=None, verbose=True):
    """重放七源 → 每个 entry 的候选重音拼写。**只读，不写库。**

    🔴 挂钩靠**重算 `src_ref`**（`criteria.SrcRef`，一行源头 ↔ 一行 entry）。
       能这么做是因为「哪些行会落成 entry」只有一个家（`criteria.entry_accept`）——
       这件事在阶段 2 的探针 §0 上**证明过**：重算出来的 1,372,375 个键
       与库里 `entry.src_ref` 完全相等，两个方向的差都是 0。
    """
    ref = criteria.SrcRef()
    # src_ref → {带重音串: (来源档位, 行序)}
    cand = collections.defaultdict(dict)
    st = {
        "rows": collections.Counter(),          # (src, 来源) → 过判据的行数
        "noinfo": collections.Counter(),        # 与词头一模一样（不收）
        "noinfo_w": collections.defaultdict(set),
        "rej": collections.Counter(),           # 被拒的分桶（只统计「源头声称的」那批）
        "rej_eg": collections.defaultdict(list),
        "kept_w": set(),
    }
    for src, p in SRC:
        t0 = time.time()
        n = 0
        for e in rd(p, limit):
            n += 1
            ok, _skip, pos = criteria.entry_accept(e)
            if not ok:
                continue
            w = e["word"]
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, w, pos, no, sub)
            for order, f in enumerate(e.get("forms") or []):
                form = (f.get("form") or "").strip()
                if not form:
                    continue
                prov = provenance(f.get("tags") or [])
                good, kind, val = criteria.stressed_spelling(w, form)
                if not good:
                    # 🔴 只给「源头**声称**这是词头拼写」的那批分桶。带语法标签的行
                    #    被拒是**正常**的（它们是别的词形），算进残渣桶会让
                    #    几百万条正当的变位把真残渣淹掉。
                    if prov in ("canonical", "stressed"):
                        st["rej"][kind] += 1
                        if len(st["rej_eg"][kind]) < 6:
                            st["rej_eg"][kind].append("%s → %s" % (w, form))
                        # 「无需标注」与「源头标坏了」两个数分开报 —— 分桶判据
                        # 的家在 `criteria.stress_not_needed`，**本文件不重写**。
                        if kind.startswith("无需标注") or kind.startswith("🔴 源头标坏"):
                            st["noinfo"][(src, prov)] += 1
                            st["noinfo_w"][kind].add(w)
                    continue
                st["rows"][(src, prov)] += 1
                st["kept_w"].add(w)
                key = (PROV_RANK[prov], order, src)
                # 同一个串被多行给出 ⇒ 留**档位最好、行序最前**的那一个来源
                if val not in cand[sref] or key < cand[sref][val][0]:
                    cand[sref][val] = (key, prov, src)
        if verbose:
            print("  · %-16s %9s 行  %5.1fs" % (src, format(n, ","),
                                                time.time() - t0), file=sys.stderr)
    return cand, st


def build_rows(cand, conn, remap=None):
    """候选 → `stress` 表的行 ＋ `entry.stressed` 的值。

    → `(stress_rows, entry_stressed, 统计)`

    🔴🔴 `remap` 是 R13 的 `{要删掉的 dict_id: 孪生 dict_id}`。**必须接**：
       那 7 行 `dict` 会在本次写库里被删掉，而 `stress.word_id` 取自
       `entry.word_id` 的**现状** —— 不重映射就会留下 7 行指向已删除行的外键。
    ⚠️ 实测这 7 个词形**眼下一个候选都没有**（阶段 2 探针 §F），
       所以重映射现在是空操作。**照样要做** —— `[[top-level-backlog]]` 的 **B20**：
       「我造的那一行不会撞」本身就是一个关于现状的假设，而现状会变。
    """
    remap = remap or {}
    ent = {}                     # src_ref → (entry_id, word_id)
    for eid, wid, sref in conn.execute("SELECT id, word_id, src_ref FROM entry"):
        ent[sref] = (eid, remap.get(wid, wid))
    srows, estr = [], []
    st = {"orphan": 0, "variants": collections.Counter(), "diff_pos": 0,
          "diff_pos_eg": [], "primary_prov": collections.Counter()}
    for sref, vals in cand.items():
        hit = ent.get(sref)
        if hit is None:
            # 🔴 探针 §0 证明过这不该发生。真发生了就**记数并跳过，不猜 entry**
            #    （`stress.entry_id` 可以为 NULL，但那是「定不到」用的，
            #      而这里是「键对不上」—— 两件事别混成一个）。
            st["orphan"] += 1
            continue
        eid, wid = hit
        ordered = sorted(vals.items(), key=lambda kv: kv[1][0])
        st["variants"][len(ordered)] += 1
        if len(ordered) >= 2:
            poss = {criteria.stress_position(v) for v, _ in ordered}
            if len(poss) > 1:
                st["diff_pos"] += 1
                if len(st["diff_pos_eg"]) < 10:
                    st["diff_pos_eg"].append(
                        (sref, [(v, m[1]) for v, m in ordered]))
        for seq, (val, (_key, prov, src)) in enumerate(ordered):
            srows.append((wid, eid, val, seq, 1 if seq == 0 else 0,
                          "%s/%s" % (src, prov),
                          # `src_ref` 带上 variant_seq：`UNIQUE(src_ref)` 要求
                          # 一行一个键，而同一个 entry 可以有多个候选。
                          "%s#stress.%d" % (sref, seq)))
        st["primary_prov"][ordered[0][1][1]] += 1
        estr.append((ordered[0][0], eid))
    return srows, estr, st


# ══════════════════════════════════════════════════════════════════════════
# 欠账 R13：7 个**词头自己带着重音符**的 `dict` 行
# ══════════════════════════════════════════════════════════════════════════
# `RU_PLAN` 的 R13 写明这一层要一并处理。阶段 2 探针 §F 把答案量清了：
# **7 个全都有无重音的孪生行已经在 `dict` 里**，其中两个的孪生行拼写**重音位置不同**
# （`восемью́`／`во́семью`、`вперего́нки`／`вперегонки́` —— 两个都对，是真变体）。
#
# ⇒ 判据：**`dict.word` 永远不许带重音符** —— 那是本层的前提（重音不是拼写的一部分）。
#   这 7 行是源头缺陷漏进了我们的身份单位。处理：
#     ① 它的 `entry` 行改挂到孪生词形上（`src_ref` 里带着原词，证据一个字不动）；
#     ② 它的带重音词头本身**作为一个候选**进 `stress`（这是它唯一的信息）；
#     ③ 删掉这 7 个 `dict` 行，并按 `criteria.entry_type_for_word` **重算**孪生行的
#        `pos` / `entry_type`（合并之后词性集合变了，不重算就是一条过期的派生值）。
# ⚠️ `◌́`（维基词典给 U+0301 本身建的条目）**没有孪生行、合法、保留** ——
#    它是「不处理」而不是「漏掉了」，这句话本身是判据的一部分。
def r13_merge(conn):
    """→ `(操作列表, 说明行)`。**只算不写**，写在 `write()` 里统一过闸。"""
    marks = (criteria.STRESS, "̀")
    rows = [r for r in conn.execute("SELECT id, word, pos FROM dict")
            if any(m in r[1] for m in marks)]
    ops, notes = [], []
    for did, word, pos in rows:
        bare = criteria.strip_stress(word)
        twin = conn.execute("SELECT id, pos FROM dict WHERE word=?", (bare,)).fetchone()
        if twin is None:
            notes.append("保留 %-12s —— 没有孪生行（`◌́` 是 U+0301 自己的条目，合法）"
                         % word)
            continue
        tid, tpos = twin
        ers = conn.execute("SELECT id, src_ref FROM entry WHERE word_id=?",
                           (did,)).fetchall()
        poss = (set((tpos or "").split("/")) | set((pos or "").split("/"))) - {""}
        ops.append(dict(dict_id=did, word=word, twin_id=tid, bare=bare,
                        entries=[e[0] for e in ers],
                        new_pos="/".join(sorted(poss)),
                        new_type=criteria.entry_type_for_word(bare, poss)))
        notes.append("合并 %-12s → %-12s（搬 %d 条 entry，重算 pos=%s type=%s）"
                     % (word, bare, len(ers), "/".join(sorted(poss)),
                        criteria.entry_type_for_word(bare, poss)))
    return ops, notes


def report(cand, st, srows, bst, notes):
    print("\n■ 阶段 2 重音层")
    print("   过判据的行 %s ／ 覆盖词形 %s ／ `stress` 行 %s"
          % (format(sum(st["rows"].values()), ","),
             format(len(st["kept_w"]), ","), format(len(srows), ",")))
    print("\n   按来源（`src` 列就是这个，三个源不并成一堆）：")
    for (src, prov), n in sorted(st["rows"].items(), key=lambda x: -x[1]):
        print("      %-16s %-10s %10s" % (src, prov, format(n, ",")))
    print("\n   一个 entry 几个候选：")
    for k in sorted(bst["variants"]):
        print("      %d 个 %12s" % (k, format(bst["variants"][k], ",")))
    print("   其中**重音位置不同**的 %s 个 —— `is_primary` 靠弱信号挑（欠账 R14）"
          % format(bst["diff_pos"], ","))
    for sref, vs in bst["diff_pos_eg"]:
        print("      %-34s %s" % (sref.split(":")[1],
                                  " ｜ ".join("%s〔%s〕" % x for x in vs)))
    print("\n   主行来自哪一档：")
    for k, v in bst["primary_prov"].most_common():
        print("      %-12s %10s" % (k, format(v, ",")))
    print("\n   不带任何重音信息 ⇒ 不收（%s 行）。**两个数分开报**，"
          "⚠️ 这里只统计源头**声称**是词头拼写的那批；"
          "全库口径（「需要标注的词元」做分母）在覆盖率里，见账的闸 `COVERAGE`："
          % format(sum(st["noinfo"].values()), ","))
    for k in sorted(st["noinfo_w"]):
        print("      %-28s %8s 个词形" % (k, format(len(st["noinfo_w"][k]), ",")))
    print("\n   源头声称是词头拼写而被拒的（分桶，残渣不许沉）：")
    for k, v in st["rej"].most_common():
        print("      %-30s %8s   例：%s" % (k, format(v, ","),
                                           st["rej_eg"][k][0] if st["rej_eg"][k] else ""))
    if bst["orphan"]:
        print("\n   🔴🔴 **%s 个候选的 `src_ref` 在库里找不到 entry** —— "
              "探针 §0 证明过这不该发生，不许静默跳过，查完再跑"
              % format(bst["orphan"], ","))
    print("\n   欠账 R13（词头自带重音符）：")
    for n in notes:
        print("      %s" % n)


def write(srows, estr, ops, conn, rebuild=False):
    """落库。`rebuild=True` ＝ 判据改了，**原地重算这一层**。

    🔴 `[[replay-scripts-undo-fixes]]` / `[[aim-for-perfect-not-cheap]]`：
       判据改了就**重跑生成侧**，不许只去 UPDATE 已落库的那几行 ——
       否则下一次有人跑收割器，结果与库里不一样，而两边各自都「对」。
    ⚠️ 这一层**没有付费数据**，所以重跑是免费的；义项层以后不许这么干
       （vi 的 6e 之后 `--rebuild` 被付费数据保险拦住，要走 `--sync`）。
    """
    q = lambda s: conn.execute(s).fetchone()[0]                  # noqa: E731
    base_s = q("SELECT COUNT(*) FROM stress") if rebuild else 0
    base_e = q("SELECT COUNT(*) FROM entry WHERE stressed IS NOT NULL "
               "AND TRIM(stressed)<>''") if rebuild else 0
    exp = {
        "#stress": len(srows) - base_s,
        "stress.stressed": len(srows) - base_s,
        # `is_primary` 是 `NOT NULL DEFAULT 0`，`'0'` 非空 ⇒ 全计入（与 `etym_no` 同理）
        "stress.is_primary": len(srows) - base_s,
        "entry.stressed": len(estr) - base_e,
        # R13：删 dict 行 ＋ 重算孪生行的派生列
        "__rows__": -len(ops),
        "word_norm": -len(ops),
        "is_lemma": -len(ops),
        "entry_type": -len(ops),
        "pos": -len(ops),
    }
    # 🔴 这一步让哪些层过期：重音是**内容层**，账的闸 V10 的 `COVERAGE` 锁
    #    正是为「一出现内容层就判红」而立的 —— 它会响，而**那是设计好的**。
    with dbtool.session("stress-layer" + ("-rebuild" if rebuild else ""),
                        expect=exp,
                        invalidates=["stress", "entry.stressed"]) as s:
        if rebuild:
            s.execute("DELETE FROM stress")
            s.execute("UPDATE entry SET stressed=NULL")
        s.executemany(
            "INSERT INTO stress(word_id,entry_id,stressed,variant_seq,is_primary,"
            "src,src_ref) VALUES (?,?,?,?,?,?,?)", srows)
        s.executemany("UPDATE entry SET stressed=? WHERE id=?", estr)
        for op in ops:
            # ⚠️ 顺序有讲究：先搬 entry，再改派生列，最后删 dict 行 ——
            #    反过来删在前面会撞 `entry.word_id` 的外键。
            s.executemany("UPDATE entry SET word_id=? WHERE id=?",
                          [(op["twin_id"], e) for e in op["entries"]])
            s.execute("UPDATE dict SET pos=?, entry_type=? WHERE id=?",
                      (op["new_pos"], op["new_type"], op["twin_id"]))
            s.execute("DELETE FROM dict WHERE id=?", (op["dict_id"],))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只统计，不写库")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rebuild", action="store_true",
                    help="判据改了：清掉这一层原地重算（本层无付费数据，重跑免费）")
    a = ap.parse_args()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    print("■ 扫七源（重音层）……", file=sys.stderr)
    cand, st = collect(a.limit or None)
    # 🔴 **R13 先算**：它决定哪些 `dict` 行要删，而 `stress.word_id` 必须避开它们。
    ops, notes = r13_merge(conn)
    remap = {op["dict_id"]: op["twin_id"] for op in ops}
    srows, estr, bst = build_rows(cand, conn, remap)
    # R13 的带重音词头本身也是一个候选，但它挂的 entry 已经搬走了 ——
    # 它的 `stress` 行在 `srows` 里（来自那些 entry 的 `src_ref`），所以不另加。
    report(cand, st, srows, bst, notes)
    if bst["orphan"]:
        raise SystemExit("🔴 有候选挂不上 entry，不写库")
    if a.dry:
        print("\n(dry：没写库)")
        return 0
    if a.limit:
        raise SystemExit("🔴 `--limit` 只许和 `--dry` 一起用 —— "
                         "半份数据写进库，之后所有覆盖率都是错的")
    conn.close()
    write(srows, estr, ops, sqlite3.connect(paths.DB), rebuild=a.rebuild)
    out = paths.WORK / "stage2_stress_stats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "rows": len(srows), "entries": len(estr),
        "diff_pos": bst["diff_pos"],
        "noinfo": {k: len(v) for k, v in st["noinfo_w"].items()},
        "rej": dict(st["rej"]),
        "by_src": {"%s/%s" % k: v for k, v in st["rows"].items()},
        "rule_ver": criteria.RULE_VER,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n■ 统计已存档 → %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
