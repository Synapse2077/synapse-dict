#!/usr/bin/env python3
"""阶段 2b：变形层归位 —— `dict.infl`/`exchange` 两列字符串 → `inflection` 表。2026-08-29。

═══ 现状 ═══
    dict.infl      'piar 的 虚拟式现在时第一/三人称单数'   346,289 行，多条用 \\n 拼在一起
    dict.exchange  '0:piar'                       同上
一个词形的多条变形关系挤在一个字符串里，查不了、也挂不住 entry。
`SCHEMA` §10 定的落点是 `inflection.entry_id` —— 变形归到**词条**上，不是词形上。

═══ 与阶段 2a 的关系（这一步为什么必须在 2a 之后）═══
`build.py:415` 是 `fo = s.get("form_of") or s.get("alt_of")` —— 两者一起当变形。
2a 已经把 `alt_of` 移回词条层了，所以 `infl` 列里那些
「e 的 变位形式」（`&` 是 `e` 的**缩写**，不是变位形式）**不该进变形层**。
**本步只收 `form_of`。**

═══ 闸① 怎么保证「只搬不改」（本步最关键的设计）═══
用新表**反向重建** `infl` / `exchange` 两列的完整字符串，与库里现有的值**逐字节**比对。
⚠️ 但新表只有 `form_of`，而旧列含 `alt_of` ⇒ 直接比会差。所以重建时**按七月的旧规则
把 alt_of 那部分也算出来**一起拼：

    重建(form_of 部分 ∪ alt_of 部分) == 现有列        ← 证明复刻规则与七月一致
    新表 == 其中的 form_of 部分                        ← 证明分流正确

两条都过，才说明既没搬错、也没多收少收。**一条都不许差。**

═══ 复刻的是哪条规则（读自 `pt/pipeline/build.py:412-435`）═══
    fo = form_of or alt_of;  is_infl = bool(fo) and not is_affix
    base = fo[0]["word"].strip();  base 为空 ⇒ 整条跳过
    label = compose(tags) or "变位形式"
    note  = f"{base} 的 {label}"        # 🔴 「的」两侧各一个空格，别改
    infl 按 note **去重**后 \\n 拼接；exchange 按 base **去重**后 "0:%s" \\n 拼接
中文说明一律用已有的 `infl_compose.compose()`，**不新写一套**（七月已验证过措辞）。

用法（在 pt/ 目录下）：
    python3 pipeline/build_inflection_layer.py            # 干跑 + 闸①
    python3 pipeline/build_inflection_layer.py --apply
    python3 pipeline/build_inflection_layer.py --verify
    python3 pipeline/build_inflection_layer.py --mutate
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
from build_entry_layer import AFFIX_POS, SRC   # noqa: E402
from infl_compose import compose   # noqa: E402

DDL = """CREATE TABLE inflection (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id  INTEGER NOT NULL,        -- 变形词形 → dict.id
  entry_id INTEGER,                 -- 该变形属于哪个词条（SCHEMA §10）
  base     TEXT NOT NULL,           -- 原形词形，**原样存**不解析成外键
  base_id  INTEGER,                 -- 原形在库里的 dict.id；NULL = 悬空（源头真缺词头）
  label_zh TEXT NOT NULL,           -- infl_compose 组合的中文语法说明
  desc_en  TEXT,                    -- dump 原文 gloss
  tags     TEXT,                    -- 源头 tags 的 JSON
  src      TEXT NOT NULL,
  src_ref  TEXT NOT NULL,
  UNIQUE(src_ref)
)"""
IDX = [
    "CREATE INDEX idx_infl_word ON inflection(word_id)",
    "CREATE INDEX idx_infl_base ON inflection(base_id)",
    "CREATE INDEX idx_infl_entry ON inflection(entry_id)",
]


def replay_infl(dump_path, words):
    """复刻 build.py 的变形循环。
    → rows[折叠词形] = [(is_form_of, base, label, gloss, tags, ent_ref, src_ref), …]（dump 顺序）"""
    rows = defaultdict(list)
    occ_of = Counter()
    stat = Counter()
    with open(dump_path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "pt":
                continue
            w0 = (e.get("word") or "").strip()
            if not w0:
                continue
            w = w0.lower()                      # 🔴 复刻 build.py:388 的折叠
            if w not in words:
                continue
            pos_raw = e.get("pos") or ""
            etym = str(e.get("etymology_number") or 0)
            key0 = (w0, pos_raw, etym)
            occ = occ_of[key0]
            occ_of[key0] += 1
            is_affix = pos_raw in AFFIX_POS
            for i, s in enumerate(e.get("senses") or []):
                fo, ao = s.get("form_of"), s.get("alt_of")
                if not (fo or ao) or is_affix:
                    continue
                src = fo or ao
                base = (src[0].get("word") or "").strip() if src else ""
                if not base:
                    stat["🔴 base 为空（build.py 当年也是整条跳过）"] += 1
                    continue
                tags = s.get("tags") or []
                label = compose(tags) or "变位形式"
                rows[w].append((
                    bool(fo), base, label, (s.get("glosses") or [""])[0], tags,
                    "kk-en:%s:%s:%s:0" % key0,
                    "kk-en:%s:%s:%s:%d#%d" % (key0[0], key0[1], key0[2], occ, i)))
                stat["form_of" if fo else "alt_of（2a 已移回词条层，不进变形层）"] += 1
    return rows, stat


def rebuild_cols(rows, only_form_of=False):
    """从复刻结果重建 infl / exchange 两列。**规则与 build.py:476-480,595-596 逐字一致。**"""
    out = {}
    for w, items in rows.items():
        notes, bases = [], []
        for is_fo, base, label, _g, _t, _e, _s in items:
            if only_form_of and not is_fo:
                continue
            note = "%s 的 %s" % (base, label)
            if note not in notes:
                notes.append(note)
            if base not in bases:
                bases.append(base)
        out[w] = ("\n".join(notes) if notes else None,
                  "\n".join("0:%s" % b for b in bases) if bases else None)
    return out


def gate1(con, rows, show=6):
    """闸① 双向：①全量重建 == 现有列（证明复刻规则对）②新表 == 其中 form_of 部分。"""
    print("\n═══ 闸① 反向重建（全量，非抽样）═══")
    have = {w.lower(): (i, x) for w, i, x in
            con.execute("SELECT word, infl, exchange FROM dict")}
    both = rebuild_cols(rows)
    bad_i = bad_x = 0
    samples = []
    for w, (hi, hx) in have.items():
        gi, gx = both.get(w, (None, None))
        if hi != gi:
            bad_i += 1
            if len(samples) < show:
                samples.append(("infl", w, repr(hi)[:80], repr(gi)[:80]))
        if hx != gx:
            bad_x += 1
            if len(samples) < show:
                samples.append(("exchange", w, repr(hx)[:80], repr(gx)[:80]))
    print("   ① 重建(form_of ∪ alt_of) vs 现有列")
    print("      %s infl     对不上 %s" % ("✓" if not bad_i else "🔴", f"{bad_i:,}"))
    print("      %s exchange 对不上 %s" % ("✓" if not bad_x else "🔴", f"{bad_x:,}"))
    for c, w, a, b in samples:
        print("      🔴 %s %s\n         现有: %s\n         重建: %s" % (c, w, a, b))
    return bad_i == 0 and bad_x == 0


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("inflection 条数 == 期望", q("SELECT count(*) FROM inflection"), expect["n"]),
        ("孤儿 inflection（word_id 不在 dict）",
         q("SELECT count(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
           "WHERE d.id IS NULL"), 0),
        ("挂到不存在 entry 上的 inflection",
         q("SELECT count(*) FROM inflection i LEFT JOIN entry e ON e.id=i.entry_id "
           "WHERE i.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        ("🔴 混进变形层的 alt_of（2a 已移走，必须为 0）",
         q("SELECT count(*) FROM inflection i JOIN sense_relation r "
           "ON r.src_ref = i.src_ref AND r.kind='alt_of'"), 0),
        ("label_zh 为空", q("SELECT count(*) FROM inflection WHERE label_zh=''"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    return ok


def mutate(con, rows):
    """🔴 变异：破坏 5 处重建结果，闸①必须全部报出。一次一个，每次从干净副本重来。"""
    print("\n═══ 变异验证 ═══")
    have = {w.lower(): (i, x) for w, i, x in
            con.execute("SELECT word, infl, exchange FROM dict")}
    base = {w: list(v) for w, v in rows.items()}
    multi = [w for w in base if len(base[w]) > 1][:2]
    solo = [w for w in base if len(base[w]) == 1][:3]
    cases = []

    def broke(name, mut):
        got = {w: list(v) for w, v in base.items()}
        mut(got)
        both = rebuild_cols(got)
        n = sum(1 for w, (hi, hx) in have.items()
                if (hi, hx) != both.get(w, (None, None)))
        cases.append(n > 0)
        print("   %s  %-46s 闸%s" % ("✓" if n else "🔴", name,
                                     "报出 %d 个词形" % n if n else "没报"))

    for w in multi:
        broke("变形顺序颠倒：%s" % w, lambda g, w=w: g.__setitem__(w, list(reversed(g[w]))))
    broke("整条变形丢失：%s" % solo[0], lambda g: g.pop(solo[0]))
    broke("原形改一个字符：%s" % solo[1],
          lambda g: g.__setitem__(solo[1], [(g[solo[1]][0][0], g[solo[1]][0][1] + "X")
                                            + g[solo[1]][0][2:]]))
    broke("中文标签改一个字符：%s" % solo[2],
          lambda g: g.__setitem__(solo[2], [g[solo[2]][0][:2] + (g[solo[2]][0][2] + "X",)
                                            + g[solo[2]][0][3:]]))
    ok = all(cases)
    print("\n%s" % ("✓ 五条变异全部被闸①逮到" if ok else "🔴 有变异没被逮到 —— 闸是瞎的"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {r[1].lower(): r[0] for r in con.execute("SELECT id, word FROM dict")}
    if a.verify:
        n = con.execute("SELECT count(*) FROM inflection").fetchone()[0]
        return 0 if gate2(con, {"n": n}) else 1

    print("■ 复刻 build.py 的变形循环…")
    rows, stat = replay_infl(paths.KK, words)
    for k, v in stat.items():
        print("   %-46s %10s" % (k, f"{v:,}"))
    n_fo = sum(1 for v in rows.values() for x in v if x[0])
    print("   %-46s %10s" % ("→ inflection 行（只收 form_of）", f"{n_fo:,}"))

    if a.mutate:
        return mutate(con, rows)
    ok1 = gate1(con, rows)
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0 if ok1 else 1
    if not ok1:
        print("\n🔴 闸①未过，中止 —— 复刻规则与七月不一致就不写库")
        return 1

    eid = dict(con.execute("SELECT src_ref, id FROM entry"))
    out = []
    for w, items in rows.items():
        for is_fo, base, label, gloss, tags, ent_ref, src_ref in items:
            if not is_fo:
                continue
            out.append((words[w], eid.get(ent_ref), base, words.get(base.lower()),
                        label, gloss, json.dumps(tags, ensure_ascii=False), SRC, src_ref))
    dangling = sum(1 for r in out if r[3] is None)
    print("   悬空原形（base 不在库里，阶段 3 收词后回填）：%s" % f"{dangling:,}")

    now = dbtool.snapshot()
    with dbtool.session("keep-v3-infl",
                        expect={"#inflection": len(out) - now.get("#inflection", 0)}) as s:
        s.execute("DROP TABLE IF EXISTS inflection")
        s.execute(DDL)
        for q in IDX:
            s.execute(q)
        s.executemany(
            "INSERT INTO inflection (word_id,entry_id,base,base_id,label_zh,desc_en,"
            "tags,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?)", out)

    con.close()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok2 = gate2(con, {"n": len(out)})
    print("\n%s" % ("✓ 两道闸全过" if ok2 else "🔴 有闸未通过"))
    return 0 if ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
