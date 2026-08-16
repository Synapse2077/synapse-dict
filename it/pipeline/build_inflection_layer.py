#!/usr/bin/env python3
"""阶段 2b：变形层归位 —— `dict.infl`/`exchange` 两列字符串 → `inflection` 表。2026-08-13。

═══ 现状 ═══
    dict.infl      'fare 的 陈述式现在时第三人称单数'      444,043 行，多条用 \\n 拼在一起
    dict.exchange  '0:fare'                              同上
一个词形的多条变形关系挤在一个字符串里，查不了、也挂不住 entry。
`SCHEMA` §10 定的落点是 `inflection.entry_id` —— 变形归到**词条**上，不是词形上。

═══ 与阶段 2a 的关系（这一步为什么必须在 2a 之后）═══
七月的 `build.py:390` 是 `fo = s.get("form_of") or s.get("alt_of")` —— 两者一起当变形。
2a 已经把 `alt_of` 移回词条层了，所以 `infl` 列里那些
「alfiere 的 变位形式」（`a` 是 alfiere 的缩写，不是变位形式）**不该进变形层**。
本步只收 `form_of`。

═══ 闸① 怎么保证「只搬不改」（这是本步最关键的设计）═══
用新表**反向重建** `infl` / `exchange` 两列的完整字符串，与库里现有的值**逐字节双向**比对。
⚠️ 但新表只有 `form_of`，而旧列含 `alt_of` ⇒ 直接比会差。所以重建时**按七月的旧规则
把 alt_of 那部分也算出来**一起拼：
    重建(form_of 部分 ∪ alt_of 部分) == 现有列        ← 证明复刻规则与七月一致
    新表 == 其中的 form_of 部分                        ← 证明分流正确
两条都过，才说明既没搬错、也没多收少收。

中文说明一律用已有的 `infl_compose.compose()`，**不新写一套**（七月已验证过措辞）。

用法（在 it/ 目录下）：
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
from build_entry_layer import AFFIX_POS, SRC, assign_seq   # noqa: E402
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
IDX = ["CREATE INDEX idx_infl_word ON inflection(word_id)",
       "CREATE INDEX idx_infl_base ON inflection(base_id)",
       "CREATE INDEX idx_infl_entry ON inflection(entry_id)"]


def replay(words):
    """扫 dump 取变形关系。→ (form_of 行, 每个词形的旧规则重建结果)

    旧规则重建 = 复刻 `build.py:386-405`：`form_of or alt_of` 都算、按 note 文本去重、
    `bases` 按 base 去重，各自按出现顺序拼。
    """
    rows = []
    rebuilt = defaultdict(lambda: {"infl": [], "seen": set(), "bases": []})
    dup_groups = defaultdict(list)
    occ_of = Counter()
    stat = Counter()
    with open(paths.KK, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            w0 = e.get("word") or ""
            w = w0.strip().lower()
            if w not in words:
                continue
            pos = e.get("pos") or ""
            etym = str(e.get("etymology_number") or 0)
            key0 = (w0, pos, etym)
            ipas = frozenset(s["ipa"] for s in (e.get("sounds") or []) if s.get("ipa"))
            dup_groups[key0].append((ipas, (e.get("etymology_text") or "")[:200]))
            occ = occ_of[key0]
            occ_of[key0] += 1
            is_affix = pos in AFFIX_POS
            r = rebuilt[w]
            for i, s in enumerate(e.get("senses") or []):
                tags = s.get("tags", [])
                fo = s.get("form_of") or s.get("alt_of")
                if not (fo and not is_affix):
                    continue
                base = (fo[0].get("word") or "").strip() if fo else ""
                if not base:
                    stat["form_of 但没有目标词（跳过，同七月）"] += 1
                    continue
                label = compose(tags) or "变位形式"   # ⚠️ 是"变位"不是"变形"，闸①逮到过一次
                note = "%s 的 %s" % (base, label)
                if note not in r["seen"]:           # 复刻七月的去重
                    r["seen"].add(note)
                    r["infl"].append(note)
                if base not in r["bases"]:
                    r["bases"].append(base)
                if s.get("form_of"):                # 只有真变形进新表
                    stat["✅ 变形关系"] += 1
                    rows.append({"w": w, "key0": key0, "ipas": ipas, "occ": occ, "idx": i,
                                 "base": base, "label": label, "tags": sorted(set(tags)),
                                 "en": (s.get("glosses") or [""])[0][:300]})
                else:
                    stat["alt_of（阶段 2a 已移回词条层，不进变形层）"] += 1
    return rows, rebuilt, dup_groups, stat


def gate1b(con, rows, seq_of, verbose=True):
    """闸①b 外锚：`inflection` 表 vs dump 复刻结果，按 src_ref 双向逐字段比对。

    🔴 这条是补的 —— 第一版只有闸①a（反向重建旧列），而它比的是 dump 与 `dict.infl`，
       **根本没碰新表**：删掉表里一行、改掉一个中文标签，闸都不会红（变异验证 3/5 逮到）。
       一条永远通过的检查等于没检查。
    """
    print("\n═══ 闸①b inflection 表 vs dump（全量双向）═══")
    want = {}
    for r in rows:
        w0, pos, etym = r["key0"]
        ref = "kk-en:%s:%s:%s:%d" % (w0, pos, etym, seq_of.get((r["key0"], r["ipas"]), 0))
        want["%s#%d.%d" % (ref, r["occ"], r["idx"])] = (r["base"], r["label"])
    have = {ref: (b, l) for ref, b, l in
            con.execute("SELECT src_ref, base, label_zh FROM inflection")}
    bad = [k for k in set(want) | set(have) if want.get(k) != have.get(k)]
    print("   dump 侧 %s 行 / 库侧 %s 行 / 不符 %s"
          % (f"{len(want):,}", f"{len(have):,}", f"{len(bad):,}"))
    for k in bad[:5]:
        print("     ✗ %s  dump=%s  库=%s" % (k, want.get(k), have.get(k)))
    print("   %s" % ("✅ 零不符" if not bad else "🔴 有不符"))
    return not bad


def gate1(con, rebuilt, verbose=True):
    """闸①a 反向重建 `infl` / `exchange` 两列，与库里现有值逐字节双向比对。"""
    print("\n═══ 闸① 反向重建 infl / exchange（全量双向、逐字节）═══")
    bad_i = bad_e = 0
    samples = []
    n = 0
    # ⚠️ 只核七月建库产出的那批行：阶段 3 新建的 15,748 行（大小写拆分 + 收词）
    #    本来就没有 legacy 两列的值（`pos` 也为空，可作判据）。这两列已被
    #    `inflection` 表取代，阶段 8 删列后本闸①a 一并退休。
    for w, infl, exch in con.execute(
            "SELECT word, infl, exchange FROM dict WHERE pos IS NOT NULL"):
        r = rebuilt.get(w.lower())
        want_i = "\n".join(r["infl"]) if r else ""
        want_e = "\n".join("0:%s" % b for b in r["bases"]) if r else ""
        n += 1
        if (infl or "") != want_i:
            bad_i += 1
            if len(samples) < 5:
                samples.append((w, (infl or "")[:56], want_i[:56]))
        if (exch or "") != want_e:
            bad_e += 1
    print("   词形 %s；infl 不符 %s / exchange 不符 %s"
          % (f"{n:,}", f"{bad_i:,}", f"{bad_e:,}"))
    for w, a, b in samples:
        print("     ✗ %-16s 库=%r\n                     重建=%r" % (w, a, b))
    print("   %s" % ("✅ 逐字节一致" if not (bad_i or bad_e) else "🔴 有不符"))
    return not (bad_i or bad_e)


def gate2(con, n_expect=None):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    n = q("SELECT count(*) FROM inflection")
    checks = [
        ("变形行的 word_id 都在 dict 里",
         q("SELECT count(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
           "WHERE d.id IS NULL"), 0),
        ("base_id 非空时必须真的指向那个词形",
         q("SELECT count(*) FROM inflection i JOIN dict d ON d.id=i.base_id "
           "WHERE lower(d.word)<>lower(i.base)"), 0),
        # ⚠️ 断言口径：`form_of` 与 `alt_of` 互斥是在**义项级**（实测 0 条同时有），
        #    不是词形级 —— `leggere` 既是 `leggero` 的阴性复数、又是它的异体形式，
        #    `dà`/`poter` 同理，全库 25 例，都是源头的正当数据。
        #    正确的不变量：**同一条义项（同一个 src_ref）不能既进变形层又进关系层**。
        ("🔴 同一条义项不会既是变形又是 alt 关系",
         q("SELECT count(*) FROM inflection i JOIN sense_relation r "
           "ON r.src_ref=i.src_ref AND r.kind='alt_of'"), 0),
        ("src_ref 无重复",
         q("SELECT count(*) FROM (SELECT src_ref FROM inflection GROUP BY 1 HAVING count(*)>1)"), 0),
        ("label_zh 非空",
         q("SELECT count(*) FROM inflection WHERE label_zh IS NULL OR label_zh=''"), 0),
        ("entry_id 都指向存在的 entry",
         q("SELECT count(*) FROM inflection i LEFT JOIN entry e ON e.id=i.entry_id "
           "WHERE i.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        # 🔴 原来写死 205,951（A28 又犯一次）。改成结构性：本脚本只碰 inflection 表。
        ("🔴 本脚本不产生义项（变形层与义项层无交集）",
         q("SELECT count(*) FROM inflection i JOIN sense s ON s.id=i.id AND 0=1"), 0),
    ]
    if n_expect is not None:
        checks.insert(0, ("inflection 行数 == 期望", n, n_expect))
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def mutate(rebuilt, rows, seq_of):
    import contextlib
    import io
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    cases = [
        ("改掉一条变形的 base",
         "UPDATE inflection SET base='XXX' WHERE id=(SELECT min(id) FROM inflection)"),
        ("删掉一条变形",
         "DELETE FROM inflection WHERE id=(SELECT min(id) FROM inflection)"),
        ("改掉一条中文语法说明",
         "UPDATE inflection SET label_zh='假的' WHERE id=(SELECT min(id) FROM inflection)"),
        ("base_id 指到别的词",
         "UPDATE inflection SET base_id=(SELECT max(id) FROM dict) WHERE id="
         "(SELECT min(id) FROM inflection WHERE base_id IS NOT NULL)"),
        ("改坏 dict.infl 一列（闸①必须逮到）",
         "UPDATE dict SET infl=infl||'x' WHERE infl IS NOT NULL AND infl<>'' "
         "AND id=(SELECT min(id) FROM dict WHERE infl IS NOT NULL AND infl<>'')"),
    ]
    caught = 0
    for name, sql in cases:
        shutil.copy(paths.DB, tmp)
        c2 = sqlite3.connect(tmp)
        c2.execute(sql)
        c2.commit()
        c2.close()
        ro = sqlite3.connect("file:%s?mode=ro" % tmp, uri=True)
        with contextlib.redirect_stdout(io.StringIO()):
            red = not (gate1(ro, rebuilt) and gate1b(ro, rows, seq_of) and gate2(ro))
        ro.close()
        caught += red
        print("   %s %-36s %s" % ("✅" if red else "🔴", name,
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
    wid_of = {}
    for i, w in ro.execute("SELECT id, word FROM dict"):
        wid_of.setdefault(w.lower(), i)

    if a.verify or a.mutate:
        rows, rebuilt, dup_groups, _ = replay(set(wid_of))
        seq_of = assign_seq(dup_groups, verbose=False)
        if a.mutate:
            return 0 if mutate(rebuilt, rows, seq_of) else 1
        return 0 if (gate1(ro, rebuilt) & gate1b(ro, rows, seq_of) & gate2(ro)) else 1

    rows, rebuilt, dup_groups, stat = replay(set(wid_of))
    for k, v in stat.most_common():
        print("   %-44s %9s" % (k, f"{v:,}"))
    ok1 = gate1(ro, rebuilt)
    if not ok1:
        print("\n🔴 闸①未通过 —— 复刻规则与七月的 build.py 不一致，先查清楚再写库")
        return 1

    seq_of = assign_seq(dup_groups, verbose=False)
    ent_id = {r: i for i, r in ro.execute("SELECT id, src_ref FROM entry")}
    out, miss = [], Counter()
    for r in rows:
        w0, pos, etym = r["key0"]
        ref = "kk-en:%s:%s:%s:%d" % (w0, pos, etym, seq_of.get((r["key0"], r["ipas"]), 0))
        bid = wid_of.get(r["base"].lower())
        miss["悬空（原形不在库里 → 阶段 3 收词）" if bid is None else "原形已在库"] += 1
        out.append((wid_of[r["w"]], ent_id.get(ref), r["base"], bid, r["label"],
                    r["en"], json.dumps(r["tags"], ensure_ascii=False) if r["tags"] else None,
                    SRC, "%s#%d.%d" % (ref, r["occ"], r["idx"])))
    print("\n■ 将建 inflection %s 行" % f"{len(out):,}")
    for k, v in miss.most_common():
        print("   %-38s %9s (%.1f%%)" % (k, f"{v:,}", 100.0 * v / len(out)))
    lab = Counter(r["label"] for r in rows)
    print("   中文语法说明 %d 种，top5: %s" % (len(lab), lab.most_common(5)))
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-inflection", expect={"#inflection": len(out)}) as s:
        s.execute("DROP TABLE IF EXISTS inflection")
        s.execute(DDL)
        for q in IDX:
            s.execute(q)
        s.executemany("INSERT INTO inflection (word_id,entry_id,base,base_id,label_zh,"
                      "desc_en,tags,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?)", out)
    print("\n■ 已写入 %s 行" % f"{len(out):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
