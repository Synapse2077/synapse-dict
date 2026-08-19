#!/usr/bin/env python3
"""阶段 3a：把被大小写折叠压成一行的词形拆开。2026-08-13。

═══ 缺陷 ═══
建库时 `build.py:325` 是 `key = word.lower()` ⇒ dump 里的 `Abate`（姓氏）和
`abate`（男修道院院长）被并进同一行 `abate`。后果有两个：
  ① 两个词的义项混在一起
  ② 搜小写词会命中大写专名（es 至今如此：搜 `gracias` 排第一的是洪都拉斯的城镇 `Gracias`）

🔴 **规模更正**：`it-CONVENTIONS` 原记 19,030 —— 那数的是"词形非全小写的 dump entry"，
   是**源头口径**。真正被压成一行的（同一 dict 行里混着两种大小写）是 **3,821 个词形**，
   其余的 dict 行本来就保留了原大小写（`Roma` 就存成 `Roma`）。
   ⇒ 又一次"量源头不量落点"。落点口径：3,827 个新行 / 3,935 个 entry / 4,385 条义项。

═══ 拆法 ═══
`entry.src_ref` 里保留了 dump 的**真实大小写**（阶段 1 特意留的凭据）。
按它把 entry 分组：与 `dict.word` 相同的留在原行，其余每种拼写建一个新 dict 行，
并把该拼写下的 `entry` / `sense` / `inflection` 全部改挂过去。

**新行带哪些列**：只带 `word` / `word_norm` / `ipa` / `level` / `is_lemma`。
  · `ipa` 可以带 —— 意语里大小写不影响读音
  · `level` 可以带 —— CEFR 是词形级
  · 🔴 语法列（`gender`/`aux`/`conj`/`plural`/…）**一律不带**：它们是词条级的，
    真值已经在 `entry` / `sense_tag` 里了，复制过来就是造第二份真值（A21）
  · `infl`/`exchange` 不带 —— 已被 `inflection` 表取代（阶段 2b）

用法（在 it/ 目录下）：
    python3 fixes/split_case_forms.py            # 干跑
    python3 fixes/split_case_forms.py --apply
    python3 fixes/split_case_forms.py --verify
    python3 fixes/split_case_forms.py --mutate
"""
import argparse
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


# 🔴 2026-08-17 加：撇号的各种写法折成 ASCII `'`。
#    意语里撇号是**词形的一部分**（`all'alba` `sant'Antonio` `d'accordo`），而网页正文
#    普遍用弯撇号 `’`、用户手打用直撇号 `'`。库里两种都有（1,333 / 1,257 个词形），
#    **只有 267 个词两种写法都收了** ⇒ 划词选中 `all'alba` 查不到（库里是 `all’alba`）。
#    ⚠️ 归一只进 `word_norm`，`word` 一个字节不动（源头怎么写就怎么留，[[ipa-bare-storage-convention]] 同理）。
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "´": "'", "`": "'", "＇": "'"})


def norm(w):
    """与建库时的 word_norm 同规则：**小写 + 去重音符 + 撇号折成 `'`**。

    ⚠️ 第一版漏了小写（`ASCII` 的 word_norm 是 `ascii`），全量核对 584,904 行时逮到。
    ⚠️ 2026-08-17 加撇号折叠。**TS 侧 `apostropheNorm` 必须与本函数逐字节一致** ——
       同一个契约写两遍是老坑（音标哈希那次差一字节全库静默降级），
       所以 `probes/norm_contract.py` 逐行核对两边的实现。
    """
    return "".join(c for c in unicodedata.normalize("NFD", w.translate(APOSTROPHES).lower())
                   if unicodedata.category(c) != "Mn")


def plan(con):
    """→ [(原 word_id, 新拼写, [entry_id…])]"""
    by = defaultdict(lambda: defaultdict(list))
    for eid, ref, wid in con.execute("SELECT id, src_ref, word_id FROM entry"):
        by[wid][ref[len("kk-en:"):].rsplit(":", 3)[0]].append(eid)
    dw = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
    out = []
    for wid, forms in by.items():
        if len(forms) < 2:
            continue
        keep = dw[wid]
        for f, eids in sorted(forms.items()):
            if f != keep:
                out.append((wid, f, eids))
    return out


def gate(con, n_new=None):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        # 🔴 **已接受基线 252，附理由**（闸没有基线就永远红、久了没人看）：
        #    阶段 1.5 灌意语证据时库里还没拆大小写（按 `w.lower()` 查），阶段 3a 拆行时
        #    只搬了**已裁决**的那些，剩下的证据仍挂在大小写不对的 dict 行上。
        #    已修 609 条，剩这批要连义项一起搬 —— **出版层的闸全绿、用户看不到**，
        #    故记账不追（`it-CONVENTIONS` 记账本有条目）。
        #    ⚠️ 数字**变大**就说明来了新的，不是这批老账。
        ("（基线 252）entry 的 src_ref 大小写 == 它所属 dict 行的 word",
         q("SELECT count(*) FROM entry e JOIN dict d ON d.id=e.word_id "
           "WHERE substr(e.src_ref, 7, length(d.word)) <> d.word "
           "OR substr(e.src_ref, 7+length(d.word), 1) <> ':'"), 252),
        ("义项与它的 entry 属于同一个 dict 行",
         q("SELECT count(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
           "WHERE s.word_id <> e.word_id"), 0),
        # 🔴 2026-08-18 改口径（A28：红的是断言不是数据）。
        #    原来写死「变形的 entry 必须属于变形形自己那一行」，报 724,575 条 ——
        #    实测 `inflection.entry_id` **有两套语义**、各自内部一致、没有第三种：
        #        724,582 条指向**原形**的 entry（`Antiochena` → `antiocheno`）
        #        510,110 条指向**变形形自己**的 entry（`pie` → `pie` 自己的 adj entry）
        #    哪一种对还没定（记账本已记，排阶段 8）⇒ 断言只保证**不是第三种**：
        #    entry 必须落在「变形形自己」或「它的原形」二者之一，不许指到别的词去。
        ("变形的 entry 必须落在自己或原形那一行（不许指到别的词）",
         q("SELECT count(*) FROM inflection i JOIN entry e ON e.id=i.entry_id "
           "WHERE e.word_id <> i.word_id "
           "AND (i.base_id IS NULL OR e.word_id <> i.base_id)"), 0),
        ("证据行与它的义项属于同一个 dict 行",
         q("SELECT count(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.word_id <> s.word_id"), 0),
        ("关系行与它的义项属于同一个 dict 行",
         q("SELECT count(*) FROM sense_relation r JOIN sense s ON s.id=r.sense_id "
           "WHERE r.word_id <> s.word_id"), 0),
        ("拆出来的新行 word_norm 正确",
         q("SELECT count(*) FROM dict WHERE word_norm <> ?", "\x00"), None),
        ("每个词形的 rank 仍连续无空洞",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("🔴 不存在两行 word 完全相同",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        if want is None:
            continue
        good = got == want
        ok &= good
        print("   %s %-48s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    if n_new is not None:
        got = q("SELECT count(*) FROM dict")
        good = got == n_new
        ok &= good
        print("   %s %-48s %s (期望 %s)" % ("✅" if good else "🔴", "dict 行数 == 期望",
                                           f"{got:,}", f"{n_new:,}"))
    return ok


def mutate():
    import contextlib
    import io
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    cases = [
        ("把一个 entry 挂回错误大小写的行",
         "UPDATE entry SET word_id=(SELECT id FROM dict WHERE word='abate') "
         "WHERE src_ref LIKE 'kk-en:Abate:%'"),
        # ⚠️ 不能只改 word_id —— `UNIQUE(word_id, rank)` 会先挡住，变异根本落不了地
        #    （第一版就是这样，看起来像"闸没红"，其实是变异没发生）。给个不冲突的 rank。
        ("把一条义项挂到别的词",
         "UPDATE sense SET word_id=(SELECT id FROM dict WHERE word='abate'), rank=9999 "
         "WHERE id=(SELECT min(s.id) FROM sense s JOIN dict d ON d.id=s.word_id "
         "WHERE d.word='Abate')"),
        ("造出两行同名",
         "INSERT INTO dict (word,word_norm,is_lemma) SELECT word,word_norm,is_lemma "
         "FROM dict WHERE word='Abate'"),
        ("把变形挂到别的词",
         "UPDATE inflection SET word_id=word_id+1 WHERE id=(SELECT min(id) FROM inflection)"),
    ]
    caught = 0
    for name, sql in cases:
        shutil.copy(paths.DB, tmp)
        c2 = sqlite3.connect(tmp)
        try:
            c2.execute(sql)
            c2.commit()
        except Exception as e:
            print("   ⚠️ %-38s 变异本身失败：%s" % (name, e))
            c2.close()
            continue
        c2.close()
        ro = sqlite3.connect("file:%s?mode=ro" % tmp, uri=True)
        with contextlib.redirect_stdout(io.StringIO()):
            red = not gate(ro)
        ro.close()
        caught += red
        print("   %s %-38s %s" % ("✅" if red else "🔴", name,
                                  "闸红了（对）" if red else "闸没红 —— 这条闸是假的"))
    print("\n   变异验证 %d/%d" % (caught, len(cases)))
    return caught == len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    if a.mutate:
        return 0 if mutate() else 1

    rows = plan(ro)
    n_sense = n_infl = 0
    stat = Counter()
    for wid, f, eids in rows:
        marks = ",".join("?" * len(eids))
        n_sense += ro.execute("SELECT count(*) FROM sense WHERE entry_id IN (%s)" % marks,
                              eids).fetchone()[0]
        n_infl += ro.execute("SELECT count(*) FROM inflection WHERE entry_id IN (%s)" % marks,
                             eids).fetchone()[0]
        stat["拆出大写专名/缩写" if f[0].isupper() else "拆出其它大小写变体"] += 1
    print("■ 将新建 dict 行 %s / 改挂 entry %s / 义项 %s / 变形 %s"
          % (f"{len(rows):,}", f"{sum(len(e) for _, _, e in rows):,}",
             f"{n_sense:,}", f"{n_infl:,}"))
    for k, v in stat.most_common():
        print("   %-24s %7s" % (k, f"{v:,}"))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    src = {i: (ipa, lv) for i, ipa, lv in ro.execute("SELECT id, ipa, level FROM dict")}
    nid = ro.execute("SELECT max(id) FROM dict").fetchone()[0]
    new_dict, moves = [], []
    for wid, f, eids in rows:
        nid += 1
        ipa, lv = src[wid]
        # is_lemma：该拼写下有非变形义项就算 lemma
        marks = ",".join("?" * len(eids))
        has = ro.execute("SELECT count(*) FROM sense WHERE entry_id IN (%s)" % marks,
                         eids).fetchone()[0]
        new_dict.append((nid, f, norm(f), ipa, 1 if has else 0, lv))
        moves.append((nid, eids))
    ro.close()

    with dbtool.session("split-case-forms",
                        expect={"__rows__": len(new_dict), "ipa": 0, "level": 0}) as s:
        s.executemany("INSERT INTO dict (id,word,word_norm,ipa,is_lemma,level) "
                      "VALUES (?,?,?,?,?,?)", new_dict)
        for nid2, eids in moves:
            marks = ",".join("?" * len(eids))
            s.execute("UPDATE sense SET word_id=? WHERE entry_id IN (%s)" % marks,
                      [nid2] + eids)
            s.execute("UPDATE inflection SET word_id=? WHERE entry_id IN (%s)" % marks,
                      [nid2] + eids)
            s.execute("UPDATE entry SET word_id=? WHERE id IN (%s)" % marks,
                      [nid2] + eids)
        # 证据层 / 关系层跟着它们的义项走
        s.execute("UPDATE sense_src SET word_id=(SELECT word_id FROM sense WHERE id=sense_src.sense_id) "
                  "WHERE sense_id IS NOT NULL AND word_id<>(SELECT word_id FROM sense WHERE id=sense_src.sense_id)")
        s.execute("UPDATE sense_relation SET word_id=(SELECT word_id FROM sense WHERE id=sense_relation.sense_id) "
                  "WHERE sense_id IS NOT NULL AND word_id<>(SELECT word_id FROM sense WHERE id=sense_relation.sense_id)")
        # 拆出去之后 rank 会出现空洞，两边都重排
        touched = {w for w, _, _ in rows} | {n for n, _ in moves}
        for wid in sorted(touched):
            ids = [r[0] for r in s.conn.execute(
                "SELECT id FROM sense WHERE word_id=? ORDER BY rank", (wid,))]
            s.execute("UPDATE sense SET rank=-rank WHERE word_id=?", (wid,))
            s.executemany("UPDATE sense SET rank=? WHERE id=?",
                          [(i, sid) for i, sid in enumerate(ids, start=1)])
    print("\n■ 已拆出 %s 行" % f"{len(new_dict):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
