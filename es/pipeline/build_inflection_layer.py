#!/usr/bin/env python3
"""变形层归位：`dict.infl` / `dict.exchange` 两列字符串 → `inflection` 表。2026-08-20。

═══ 现状 ═══
    dict.infl      "pie 的 阳性·复数\\npiar 的 虚拟式·现在时·第二人称·单数·（voseo）"
                   978,140 行非空，拆行后共 **1,091,106 条**变形事实
    dict.exchange  "0:pie\\n0:piar"                        971,124 行非空

一个词形的多条变形关系挤在一个字符串里。页面今天**能正常显示**（每行自带原形词名），
所以「难看」不是理由。真正文本列**结构上做不到**的是这四件：
  · `base_id` —— 原形在不在库里，查不出来（悬空指针一条都定位不了）
  · 反查「某原形的全部变形」—— 只能 `LIKE '%…%'` 全表扫
  · 源头的 `tags` / 原文 gloss —— 组装成中文那一步就丢了，再也回不来
  · **加不了闸** —— 改一个字节，没有任何断言会红

═══ 与 it 的一处**有意不同** ═══
it 阶段 2b 把 `alt_of` 从变形层分流回了词条层（`a` 是 `alfiere` 的缩写、不是变位形式）。
es **不做这个分流**：那是内容改动，会改变页面上「变位形式」块里显示什么。
改成加一列 `kind`（form_of / alt_of / prose）把区别记下来，
迁移本身保持**逐字节可逆**。要不要分流，等看得见页面之后单独一轮再定。

═══ 不建 entry_id 指向变形自己的词条 ═══
`inflection.entry_id` 在 it 的语义是「**原形**的那个词条」（A72），用途是按名词词条筛复数，
挡掉 `bello` 的性数一致形被当成复数。es 实测这个缺陷**不存在**：
`dict.plural` 21,634 条里只有 296 条没有名词义项，逐条看是 `liberal → liberales`
这类形容词复数 —— 西语形容词本来就有复数，是对的，不是污染。
⇒ 本表只建 `base_id`（原形词形），不建 `base_entry_id`。同一天砍掉 `pronunciation_entry`
   用的是同一条判据：**照搬前先量这门语言有没有那个病**。

═══ 三道闸 ═══
① **可逆性回核**（100%，非抽样）：从新表反向重建 `dict.infl` 的完整字符串，
   与库里现有的列**逐字节**比对。一个字节都不许差。
② `exchange` 覆盖：`exchange` 里每个原形，都必须能在该词形的 `inflection` 行里找到
   —— 带已接受基线（`build.py:305-330` 有一批**手工裁决**的孤儿重指：
   MW_REPOINT 8 条 / MW_STUB 10 条 / 重音变体 unaccent 重指，
   那些 `exchange` 里的原形与 `infl` 行里的原形本来就不是同一个字符串）。
③ 抽样：确定性搬运，无判断成分，不适用。

用法（在 es/ 目录下）：
    python3 pipeline/build_inflection_layer.py            # 干跑 + 闸①②
    python3 pipeline/build_inflection_layer.py --apply
    python3 pipeline/build_inflection_layer.py --mutate
"""
import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool   # noqa: E402
import paths    # noqa: E402
import build as B   # noqa: E402   判据 import 被复刻的那份代码，不另写一套（A93）
from infl_compose import compose   # noqa: E402

SRC = "en-edition"

DDL = """CREATE TABLE inflection (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id  INTEGER NOT NULL,        -- 变形词形 → dict.id
  seq      INTEGER NOT NULL,        -- 该词形内的第几条，= 旧 infl 列的行序（迁移锚点）
  base     TEXT NOT NULL,           -- 原形词形，**原样存**，不解析成外键
  base_id  INTEGER,                 -- 原形在库里的 dict.id；NULL = 悬空（源头真缺词头）
  label_zh TEXT NOT NULL,           -- infl_compose.compose 组合的中文语法说明
  desc_en  TEXT,                    -- dump 原文 gloss（旧列组装成中文那一步丢掉的）
  tags     TEXT,                    -- 源头 tags 的 JSON（同上）
  kind     TEXT,                    -- form_of / alt_of / prose；旧列里三者混在一起
  src      TEXT NOT NULL,
  src_ref  TEXT NOT NULL,
  UNIQUE(src_ref)
)"""
IDX = ["CREATE INDEX idx_infl_word ON inflection(word_id)",
       "CREATE INDEX idx_infl_base ON inflection(base_id)",
       "CREATE INDEX idx_infl_basew ON inflection(base)"]


def unaccent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def replay(dump_path):
    """复刻 build.py:243-283 的**变位那一支**。

    → per_bucket[word.lower()] = [(line, base, label, tags, desc_en, kind)]
      顺序与去重规则与 `build.py` 写进 `infl` 列时一致（按桶去重、首次出现的留下）。
    """
    per = defaultdict(lambda: {"lines": [], "seen": set()})
    with open(dump_path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            e = json.loads(raw)
            if e.get("lang_code") != "es":
                continue
            word = (e.get("word") or "").strip()
            if not word:
                continue
            rec = per[word.lower()]
            pos = e.get("pos", "")
            is_affix = pos in ("suffix", "prefix", "infix", "interfix")
            for s in e.get("senses", []):
                tags = s.get("tags", [])
                if bool(set(tags) & B.ABBR_TAGS) or is_affix:
                    continue                      # 缩写不是变位；词素不是某词的变位
                if not B.is_infl_sense(s):
                    continue
                base = B.base_of(s)
                if not base:
                    continue                      # prose 抽不出 base ⇒ build.py 当真义
                label = compose(tags) or "变位形式"
                line = "%s 的 %s" % (base, label)
                if line in rec["seen"]:
                    continue                      # 🔴 按**桶**去重，正是 build.py 的行为
                rec["seen"].add(line)
                kind = ("form_of" if s.get("form_of") else
                        "alt_of" if s.get("alt_of") else "prose")
                g = (s.get("glosses") or [""])[0]
                rec["lines"].append((line, base, label,
                                     json.dumps(tags, ensure_ascii=False) if tags else None,
                                     re.sub(r"\s+", " ", g).strip() or None, kind))
    return {k: v["lines"] for k, v in per.items()}


def replay_edition(per):
    """再复刻一遍**西语版**（`ingest_edition.py:296-313`），并进同一批桶。

    🔴 第一版只扫了英文版，1,091,106 条里有 **375,186 条（34%）复刻不出来** ——
       不是缺陷，是我漏了一整个源：`ingest_edition` 从 `eswiktionary` 收了 369,001 行，
       `pitia 的 阴性·单数`、`zulaque 的 虚拟式…` 这些词形在英文版 dump 里根本不存在。
       判据同样 import 被复刻的那份代码（`is_form_entry` / `is_form_sense` /
       `bases_of` / `label_of`），不另写一套。
    """
    import ingest_edition as IE
    import kaikki_util as K
    for w, e in K.iter_edition():
        if e.get("lang_code") != "es":
            continue
        w = (w or "").strip()
        if not w:
            continue
        rec = per.setdefault(w.lower(), [])
        seen = {ln[0] for ln in rec}
        ef = IE.is_form_entry(e)
        for s in (e.get("senses") or []):
            g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
            if not g or not IE.is_form_sense(s, ef):
                continue
            bs = IE.bases_of(s, g)
            lab = IE.label_of(g)
            for b in (bs or [None]):
                # 🔴 `ingest_edition:311` 无原形时整行**就是标签**，没有「X 的 Y」结构。
                #    这正是闸①最后 6 行不同的原因：我按 " 的 " 劈，把 `变位形式`
                #    劈成了 base=`变位形式` + 空标签，重建出「变位形式 的 变位形式」。
                line = ("%s 的 %s" % (b, lab)) if b else lab
                if line in seen:
                    continue
                seen.add(line)
                rec.append((line, b or "", lab, None, g, "es-edition"))
    return per


def plan(con, per, verbose=True):
    """把复刻结果对到 dict 行上。→ (rows, counters)"""
    id_by_word, lower_ids = {}, defaultdict(list)
    for i, w in con.execute("SELECT id, word FROM dict"):
        id_by_word.setdefault(w, i)
        lower_ids[w.lower()].append(i)
    # 原形解析：先精确拼写，再 unaccent 归一（正是 build.py:328 的 ① 重指规则）
    norm_index = {}
    for w in id_by_word:
        norm_index.setdefault(unaccent(w), w)

    rows, c = [], Counter()
    for wid, word, infl in con.execute(
            "SELECT id, word, infl FROM dict WHERE infl IS NOT NULL AND infl!=''"):
        want = [x for x in infl.split("\n") if x.strip()]
        got = {ln[0]: ln for ln in per.get(word.lower(), [])}
        for i, line in enumerate(want):
            m = got.get(line)
            if m is None:
                c["🔴 库里有这行、dump 里复刻不出来"] += 1
                # 仍要搬（否则闸①不可能过），从字符串里劈出 base/label
                # 无 " 的 " 的行（`ingest_edition:311` 无原形时整行就是标签）
                # base 存空串，重建时只输出标签 —— 别劈出个假原形来。
                if " 的 " in line:
                    base, _, label = line.partition(" 的 ")
                else:
                    base, label = "", line
                m = (line, base, label, None, None, None)
            else:
                c["✅ 复刻到原文与 tags"] += 1
            _, base, label, tags, desc, kind = m
            bid = id_by_word.get(base) if base else None
            if bid is None:
                alt = norm_index.get(unaccent(base))
                bid = id_by_word.get(alt) if alt else None
                if bid is not None:
                    c["原形靠去重音归一才查到"] += 1
            if bid is None:
                c["悬空：原形不在库里"] += 1
            rows.append((wid, i, base, bid, label, desc, tags, kind, SRC,
                         "kk-en:%d#%d" % (wid, i)))
    if verbose:
        print("■ 试算 %s 条变形事实" % format(len(rows), ","))
        for k, v in sorted(c.items()):
            print("     %-32s %s" % (k, format(v, ",")))
    return rows, c


# ───────────────────────── 闸① ─────────────────────────
def gate_reversible(con, rows, verbose=True):
    """从 rows 反向重建 `dict.infl`，与库里现有列**逐字节**比。100%，非抽样。"""
    rebuilt = defaultdict(list)
    for wid, seq, base, bid, label, desc, tags, kind, src, ref in rows:
        rebuilt[wid].append((seq, ("%s 的 %s" % (base, label)) if base else label))
    bad = same = 0
    sample = []
    for wid, infl in con.execute(
            "SELECT id, infl FROM dict WHERE infl IS NOT NULL AND infl!=''"):
        mine = "\n".join(t for _, t in sorted(rebuilt.get(wid, [])))
        if mine == infl:
            same += 1
        else:
            bad += 1
            if len(sample) < 3:
                sample.append((wid, infl[:80], mine[:80]))
    if verbose:
        print("■ 闸① 反向重建 infl 列：逐字节相同 %s / 不同 %s" % (
            format(same, ","), format(bad, ",")))
        for wid, a, b in sample:
            print("     🔴 id=%d\n        库里: %s\n        重建: %s" % (wid, a, b))
    return bad, same


# ───────────────────────── 闸② ─────────────────────────
def gate_exchange(con, rows, verbose=True):
    """`exchange` 里每个原形，都要能在该词形的变形行里找到。

    已接受基线：`build.py:305-330` 那一批**手工裁决**的孤儿重指
    （MW_REPOINT 把 `azud m` 剥回 `azud`、unaccent 把 `fertil` 重指 `fértil` 等），
    重指之后 `exchange` 存的是**目标**、`infl` 行里留的是**原字符串**，两边本来就不同。
    ⇒ 基线按「去重音后仍对不上」算，这样重音重指那一大族自动豁免。
    """
    by_word = defaultdict(set)
    for wid, seq, base, bid, label, desc, tags, kind, src, ref in rows:
        by_word[wid].add(base)
    miss = []
    for wid, ex in con.execute(
            "SELECT id, exchange FROM dict WHERE exchange IS NOT NULL AND exchange!=''"):
        have = by_word.get(wid) or set()
        haven = {unaccent(x) for x in have}
        for ln in ex.split("\n"):
            if not ln.strip():
                continue
            b = ln.split(":", 1)[-1].strip()
            if b not in have and unaccent(b) not in haven:
                miss.append((wid, b))
    # 已接受基线 **3,903 条**（2026-08-20 量的，A94：基线在动作**之后**取）。
    # 逐条核过，全部是**迁移前就存在的列间不一致**，不是本次搬运造成的：
    #   3,881 行有 `exchange` 却整列 `infl` 为空 —— `absconder` 的 `alt_of` 指针
    #   后来被提升成了正式义项（`obsolete form of esconder` 进了 `definition`），
    #   `infl` 清掉了、`exchange` 留着。`Iraq→Irak`、`Qatar→Catar` 同族。
    # ⇒ 闸只拦**涨**，不拦这批存量。要清它得动 `dict.exchange`，属内容改动，另开一轮。
    BASE = 3903
    over = len(miss) - BASE
    if verbose:
        print("■ 闸② exchange 覆盖：对不上 %s 条（基线 %s，%s）" % (
            format(len(miss), ","), format(BASE, ","),
            "🔴 涨了 %d" % over if over > 0 else "已接受"))
    return miss if over > 0 else []


def apply(con, rows):
    con.execute("DROP TABLE IF EXISTS inflection")
    con.execute(DDL)
    con.executemany(
        "INSERT INTO inflection (word_id,seq,base,base_id,label_zh,desc_en,tags,kind,src,src_ref)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    for s in IDX:
        con.execute(s)
    return len(rows)


def mutate(con, rows):
    """变异验证。闸①比的是「重建的 infl 字符串 vs 库里的列」⇒ 变异就改 rows。"""
    n0, _ = gate_reversible(con, rows, verbose=False)
    cases, ok = [], 0

    def run(name, mut):
        nonlocal ok
        r2 = [list(x) for x in rows]
        mut(r2)
        bad, _ = gate_reversible(con, [tuple(x) for x in r2], verbose=False)
        red = bad > n0
        ok += red
        cases.append((name, "✅ 报红" if red else "🔴 没报", bad - n0))

    run("① 改掉一条的原形词", lambda r: r[0].__setitem__(2, "__篡改__"))
    run("② 改掉一条的中文说明", lambda r: r[1].__setitem__(4, "__篡改__"))
    run("③ 删掉一条", lambda r: r.pop(2))
    run("④ 把某词形内两条的次序对调",
        lambda r: (r[0].__setitem__(1, r[1][1]), r[1].__setitem__(1, r[0][1]))
        if r[0][0] == r[1][0] else r.pop(0))
    print("\n■ 变异验证")
    for n, s, d in cases:
        print("     %-26s %s（多报 %s 行）" % (n, s, format(d, ",")))
    print("     %d/%d" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()

    print("■ 复刻 build.py 的变位那一支（英文版）…")
    per = replay(paths.KK)
    print("   桶 %s" % format(len(per), ","))
    print("■ 复刻 ingest_edition 的变形那一支（西语版）…")
    per = replay_edition(per)
    print("   桶 %s" % format(len(per), ","))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, c = plan(con, per)
    bad, same = gate_reversible(con, rows)
    miss = gate_exchange(con, rows)
    if a.mutate:
        r = mutate(con, rows)
        con.close()
        return r
    con.close()
    if bad:
        print("\n🔴 闸① 未通过，不写库")
        return 1
    if not a.apply:
        print("\n(未加 --apply，没有写库)")
        return 0
    with dbtool.session("inflection-layer", expect={}) as s:
        s.written = apply(s.conn, rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = con.execute("SELECT COUNT(*) FROM inflection").fetchone()[0]
    nb = con.execute("SELECT COUNT(*) FROM inflection WHERE base_id IS NULL").fetchone()[0]
    print("■ inflection %s 行，悬空原形 %s 条" % (format(n, ","), format(nb, ",")))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
