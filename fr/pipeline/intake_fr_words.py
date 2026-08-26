#!/usr/bin/env python3
"""阶段 3b-1：从法文版收词 —— `dict` 词形层 + `entry` 词条层。2026-08-22。

用户 2026-08-22 定：**全收**（「词汇不要紧，我选择全收」，`[[dict-scope-four-rules]]` 第①条）。

═══ 落点预检的四个结论（`probes/intake_preflight.py`，写库前跑的）═══

**① 🔴 撇号：两版约定完全相反，必须归一。**

| | 直撇 `'` | 弯撇 `’` |
|---|---:|---:|
| 我们库（英文版建的） | **2,429** | 3 |
| 法文版 | 23 | **20,198** |

原样收进来，`l'homme`（已有）与 `l’homme`（新收）会变成**两个词条**，用户敲哪个都只找到一半。
⇒ **收词时把 `’ ʼ ‘` 一律归一成 `'`**（跟已有的多数约定走，也是键盘上打得出的那个）。
实测归一在法文版内部只合并 **2 组**（`juǀʼhoan`/`juǀ’hoan`、`a'`/`a’`），不会造成塌陷。
归一后新词 **1,661,965**（原样 1,663,756）。

**② 大小写一律原样收，不折叠。** 阶段 3a 刚证明 `Écosse`/`écosse`、`pie`/`Pie`/`PIE` 是不同的词。
`build.py` 当年的 `key = word.lower()` 是缺陷，不复刻。

**③ 重音符差异（11,771 个）是真词形，照收。**
`fraichissait`（1990 改革后拼写）与 `fraîchissait`（传统拼写）在法语里都成立，不是编码问题。

**④ 🔴 法文版没有 `etymology_number`**（实测 0 / 2,107,055）。
⇒ `src_ref` 不能照抄英文版的 `kk-en:<词形>:<词性>:<词源号>:<seq>`，
   改用 `kk-fr:<词形>:<词性>#<该键第几条JSON>`。it 那轮对意语版同样处理。

═══ 五个 `POS_MAP` 盖不到的词性，逐个显式映射 ═══
🔴 **一个都不用默认值填平** —— `[[prompt-self-harm-two-patterns]]`：
   `pos or "v"` 把分类名、缩写、词缀全说成动词，落库 404 行。

    typographic variant  1,452  → `var`   ⚠️ **它根本不是词性**，是 `oeil`/`œil`、`coeur`/`cœur`
                                          那族连字变体（kaikki 把这个关系塞进了 pos 槽）。
                                          存 `var` 只是占位，真正的处置是当异体关系，归阶段 1.5。
    onomatopoeia          267  → `onom`  拟声词，正当词类（`pan` `splash` `prout`）
    interfix                5  → 原样
    postp                   3  → 原样（后置词）
    infix                   2  → 原样

═══ 本步只收「词形 + 词条」，不收义项 ═══
法文版的 **697,814 条真释义**归阶段 1.5（可对齐性已实测，见 `FR_PLAN`）。
变形指针（1,233,879 个新词形是纯指针）归 3b-2 建 `inflection`。
一次只动一样东西（`[[one-problem-at-a-time]]`）。

用法（在 fr/ 目录下）：
    python3 pipeline/intake_fr_words.py            # 干跑
    python3 pipeline/intake_fr_words.py --apply
    python3 pipeline/intake_fr_words.py --verify
"""
import argparse
import gzip
import json
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build_entry_layer import POS_MAP as POS_EN   # noqa: E402

SRC = "fr-edition"

# 🔴 收词的撇号约定。改这里等于改全库的词形，动之前先读上面 ① 那段。
APOS = {"’": "'", "ʼ": "'", "‘": "'"}

# 英文版的映射 + 法文版独有的五个（见上）
POS_MAP = dict(POS_EN)
POS_MAP.update({"onomatopoeia": "onom", "typographic variant": "var"})


def norm_apos(s):
    for a, b in APOS.items():
        s = s.replace(a, b)
    return s


def unaccent(s):
    """与 `build.py:139-142` 逐字一致 —— `word_norm` 的口径只有这一份。"""
    nfd = unicodedata.normalize("NFD", s.lower())
    out = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return out.replace("œ", "oe").replace("æ", "ae")


def scan(have):
    """扫法文版 → 新词形、以及所有 fr 条目的 entry 行。

    have = 库里已有的词形（**已归一撇号**）。
    """
    new = {}                 # word → {"pos": set, "lemma": bool}
    entries = []             # (word, pos_raw, occ)
    occ_of = Counter()
    stat = Counter()

    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            if e.get("lang_code") != "fr":
                continue
            w0 = (e.get("word") or "").strip()
            if not w0:
                continue
            w = norm_apos(w0)
            if w != w0:
                stat["撇号被归一的条目"] += 1
            pos_raw = e.get("pos") or ""
            key = (w, pos_raw)
            occ = occ_of[key]
            occ_of[key] += 1
            entries.append((w, pos_raw, occ))
            stat["法文版 fr 条目"] += 1

            real = any(s.get("glosses") and not (s.get("form_of") or s.get("alt_of"))
                       for s in (e.get("senses") or []))
            if w not in have:
                r = new.setdefault(w, {"pos": set(), "lemma": False})
                r["pos"].add(POS_MAP.get(pos_raw, pos_raw))
                r["lemma"] |= real
    return new, entries, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(con)

    raw_have = {w for (w,) in con.execute("SELECT word FROM dict")}
    have = {norm_apos(w) for w in raw_have}
    n_curly = len(raw_have) - len({w for w in raw_have if norm_apos(w) == w}) if False else \
        sum(1 for w in raw_have if norm_apos(w) != w)
    print("■ 库内词形 %s（其中撇号写法与约定不符的 %d 个，本步一并归一）"
          % (f"{len(raw_have):,}", n_curly))

    print("■ 扫法文版…")
    new, entries, stat = scan(have)
    for k, v in sorted(stat.items()):
        print("   %-28s %12s" % (k, f"{v:,}"))
    print("   %-28s %12s" % ("→ 新词形", f"{len(new):,}"))
    print("   %-28s %12s" % ("→ fr-edition entry 行", f"{len(entries):,}"))
    n_lemma = sum(1 for r in new.values() if r["lemma"])
    print("   %-28s %12s  %.1f%%"
          % ("   其中有真释义（像词头）", f"{n_lemma:,}", 100.0 * n_lemma / max(len(new), 1)))
    print("   %-28s %12s" % ("   纯指针（像变形）", f"{len(new) - n_lemma:,}"))

    posc = Counter(p for r in new.values() for p in r["pos"])
    print("\n── 新词形的词性分布（前 12）──")
    for p, v in posc.most_common(12):
        print("   %-10s %10s" % (p, f"{v:,}"))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    return apply_(con, raw_have, new, entries, n_curly)


def apply_(con, raw_have, new, entries, n_curly):
    nid = con.execute("SELECT max(id) FROM dict").fetchone()[0]
    rows = []
    for w in sorted(new):
        nid += 1
        r = new[w]
        rows.append((nid, w, unaccent(w),
                     "/".join(sorted(r["pos"])) if r["pos"] else None,
                     1 if r["lemma"] else 0))
    # 库里那几个弯撇的现有行，一并归一（保持全库一个约定）
    fix = [(norm_apos(w), unaccent(norm_apos(w)), w)
           for w in raw_have if norm_apos(w) != w]

    print("\n■ 将写入 dict %s 行；归一现有行 %d 行" % (f"{len(rows):,}", len(fix)))
    con.close()

    with dbtool.session("keep-v3-intake-fr-words",
                        expect={"__rows__": len(rows), "pos": len(rows)}) as s:
        s.executemany(
            "INSERT INTO dict (id, word, word_norm, pos, is_lemma) VALUES (?,?,?,?,?)", rows)
        s.executemany("UPDATE dict SET word=?, word_norm=? WHERE word=?", fix)

    # entry 层单独一个事务：行数太大，分开写便于出问题时定位
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ids = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    ent = []
    for w, pos_raw, occ in entries:
        wid = ids.get(w)
        if wid is None:
            continue
        ent.append((wid, w, POS_MAP.get(pos_raw, pos_raw), pos_raw, "0", occ, SRC,
                    "kk-fr:%s:%s#%d" % (w, pos_raw, occ)))
    print("■ 将写入 entry %s 行" % f"{len(ent):,}")
    con.close()
    with dbtool.session("keep-v3-intake-fr-entry", expect={"#entry": len(ent)}) as s:
        s.executemany(
            "INSERT INTO entry (word_id, word_src, pos, pos_raw, etym_no, seq, src, src_ref) "
            "VALUES (?,?,?,?,?,?,?,?)", ent)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    curly = sum(1 for (w,) in con.execute("SELECT word FROM dict")
                if any(c in w for c in APOS))
    checks = [
        ("🔴 词形里还有弯撇/异体撇号的（约定必须唯一）", curly, 0),
        ("词形重复（UNIQUE 不存在，必须自己查）",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
        ("word_norm 为空", q("SELECT count(*) FROM dict WHERE word_norm IS NULL OR word_norm=''"), 0),
        ("孤儿 entry", q("SELECT count(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
                         "WHERE d.id IS NULL"), 0),
        ("entry.src_ref 重复",
         q("SELECT count(*) FROM (SELECT src_ref FROM entry GROUP BY src_ref HAVING count(*)>1)"), 0),
        ("🔴 entry.word_src != dict.word（3a 立的规矩，收词不能破）",
         sum(1 for a_, b_ in con.execute(
             "SELECT e.word_src, d.word FROM entry e JOIN dict d ON d.id=e.word_id") if a_ != b_), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    # ⚠️ f-string 里不能有反斜杠（今天第三次踩）⇒ 先算出来再格式化
    n_dict = q("SELECT count(*) FROM dict")
    n_ent = q("SELECT count(*) FROM entry")
    n_en = con.execute("SELECT count(*) FROM entry WHERE src=?", ("en-edition",)).fetchone()[0]
    n_fr = con.execute("SELECT count(*) FROM entry WHERE src=?", ("fr-edition",)).fetchone()[0]
    print("\n■ 落点：dict {:,} | entry {:,}（en {:,} / fr {:,}）".format(
        n_dict, n_ent, n_en, n_fr))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
