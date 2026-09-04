#!/usr/bin/env python3
"""阶段 2b：变形层归位 —— `dict.infl`/`exchange` 两列字符串 → `inflection` 表。de 版，2026-09-01。

═══ 现状 ═══
    dict.infl      'Haus 的 复数主格'      263,552 行，多条用 \\n 拼在一起
    dict.exchange  '0:Haus'               同上
一个词形的多条变形关系挤在一个字符串里，查不了、也挂不住 entry。
`SCHEMA` §10 定的落点是 `inflection` 表，变形归到**词条**上。

═══ 与阶段 2a 的关系（这一步为什么必须在 2a 之后）═══
`de/pipeline/build.py:450` 是 `fo = s.get("form_of") or s.get("alt_of")` —— 两者一起当变形。
2a 已经把 8,941 条 `alt_of` 移回词条层了（`gross` 是 `groß` 的瑞士标准拼写，不是变形），
所以 `infl` 列里那部分**不该进变形层**。**本步只收 `form_of`。**

═══ 闸① 怎么保证「只搬不改」（本步最关键的设计）═══
用新表**反向重建** `infl` / `exchange` 两列的完整字符串，与库里现有的值**逐字节**比对。
⚠️ 但新表只有 `form_of`，而旧列含 `alt_of` ⇒ 直接比会差。所以重建时**按七月的旧规则
把 alt_of 那部分也算出来**一起拼：

    重建(form_of ∪ alt_of) == 现有列        ← 证明复刻规则与七月一致
    新表 == 其中的 form_of 部分              ← 证明分流正确

两条都过，才说明既没搬错、也没多收少收。**一条都不许差。**

═══ 复刻的是哪条规则（读自 `de/pipeline/build.py:448-467, 556-557`）═══
    fo = form_of or alt_of;  is_infl = bool(fo) and not is_affix
    base = fo[0]["word"].strip();  base 为空 ⇒ 整条跳过
    label = compose(tags) or "变形"          ← 🔴 de 的兜底词是「变形」不是 pt 的「变位形式」
    note  = f"{base} 的 {label}"             ← 🔴 「的」两侧各一个空格，别改
    infl 按 note **去重**后 \\n 拼接；exchange 按 base **去重**后 "0:%s" \\n 拼接
中文说明一律用已有的 `infl_compose.compose()`，**不新写一套**（七月已验证过措辞）。

🔴 **de 与 pt/fr 的一处关键差异：不折叠大小写。**
`build.py` 的键是 `word` 原样（德语名词首字母大写是正字法硬规则），
pt/fr 那两版是 `word.lower()`。⇒ 本步的 `words` 映射按**原样词形**建，
`Band`（乐队）和 `band`（binden 的过去式）在库里是两行，各自的变形也各归各的。

⚠️ **本步会 DROP 并重建 `inflection` 整张表** ⇒ 重跑它就会抹掉阶段 2c 补的链接。
   顺序永远是 **2b → 2c（各版）**。账的闸守着这一条：2c 的交付物判据是
   「`src<>'en-edition'` 的行数非空」，只跑 2b 不补 2c 会当场报红。

用法（在 de/ 目录下）：
    python3 -u pipeline/build_inflection_layer.py            # 干跑 + 闸①
    python3 -u pipeline/build_inflection_layer.py --apply
    python3 -u pipeline/build_inflection_layer.py --verify
    python3 -u pipeline/build_inflection_layer.py --mutate
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build_entry_layer import AFFIX_POS, SRC   # noqa: E402
from infl_compose import DERIV, compose        # noqa: E402

DDL = """CREATE TABLE inflection (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id  INTEGER NOT NULL,        -- 变形词形 → dict.id
  entry_id INTEGER,                 -- 该变形属于哪个词条（SCHEMA §10）
  kind     TEXT NOT NULL,           -- 'inflection' 屈折 / 'derivation' 构词
                                    -- 🔴 2026-09-01 外审后加，**两家一致**：
                                    -- 指小词/名词化不定式/施事名词是**派生出的新词**，
                                    -- 与 `Häuser → Haus` 并排展示会让读者以为是格形式。
                                    -- ⚠️ 本列有明确的消费者：阶段 8 分区渲染（记在计划表里），
                                    --   不是"先建着以后再说"（`PITFALLS` D1）。
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
    → rows[词形] = [(is_form_of, base, label, gloss, tags, ent_ref, src_ref), …]（dump 顺序）"""
    rows = defaultdict(list)
    key_seq = Counter()
    stat = Counter()
    with open(dump_path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "de":
                continue
            w = (e.get("word") or "").strip()
            if not w:
                continue
            pos_raw = e.get("pos") or ""
            etym = str(e.get("etymology_number") or 0)
            k = (w, pos_raw, etym)
            seq = key_seq[k]
            key_seq[k] += 1
            if w not in words:
                continue
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
                # 🔴 **一行两个标签，两个用途**（2026-09-01）：
                #    `label`  写进 `inflection.label_zh` —— **认构词族**（今天的正确值）；
                #    `legacy` 只给闸①拿去和七月的 `dict.infl` 列比 —— **不认**（复刻当年）。
                #    合成一个就必须二选一：要么闸报 5,263 条我自己造的假红、
                #    把 61 条真漂移淹掉，要么放弃改进。⇒ 闸守「没搬错」，表存「对的」。
                # ⚠️ 反过来也不行 —— 表里存 legacy、改进另开一个脚本 UPDATE，
                #    那就是 `[[replay-scripts-undo-fixes]]`：**本步重跑一次就把修复冲掉**。
                #    修复必须做在**产生这个值的地方**。
                label = compose(tags) or "变形"
                legacy = compose(tags, legacy=True) or "变形"
                rows[w].append((
                    bool(fo), base, label, (s.get("glosses") or [""])[0], tags,
                    "kk-en:%s:%s:%s:%d" % (w, pos_raw, etym, seq),
                    "kk-en:%s:%s:%s:%d#%d" % (w, pos_raw, etym, seq, i),
                    legacy))
                stat["form_of" if fo else "alt_of（2a 已移回词条层，不进变形层）"] += 1
    return rows, stat


def rebuild_cols(rows, only_form_of=False):
    """从复刻结果重建 infl / exchange 两列。**规则与 build.py:461-467,556-557 逐字一致。**"""
    out = {}
    for w, items in rows.items():
        notes, bases = [], []
        for is_fo, base, _label, _g, _t, _e, _s, legacy in items:
            if only_form_of and not is_fo:
                continue
            # 🔴 用 `legacy` 不用 `label` —— 这一列比的是**七月建的 `dict.infl`**。
            note = "%s 的 %s" % (base, legacy)
            if note not in notes:
                notes.append(note)
            if base not in bases:
                bases.append(base)
        out[w] = ("\n".join(notes) if notes else None,
                  "\n".join("0:%s" % b for b in bases) if bases else None)
    return out


BASELINE = ROOT / "tests" / "infl_drift_baseline.txt"


def drift(con, rows):
    """→ (每个对不上的词形 → 桶, 各桶计数, 样本)。判据只在这里写一份，闸与诊断共用。"""
    have = {w: (i, x) for w, i, x in
            con.execute("SELECT word, infl, exchange FROM dict")}
    both = rebuild_cols(rows)
    per_word, c, samples = {}, Counter(), defaultdict(list)
    for w, (hi, hx) in have.items():
        gi, gx = both.get(w, (None, None))
        if hi == gi and hx == gx:
            c["逐字节相同"] += 1
            continue
        if hi is None:
            b = "上游新增变形"
        elif gi is None:
            b = "上游不再产生变形"
        else:
            b = "上游改写了 tags/目标"
        per_word[w] = b
        c["🔴 " + b] += 1
        if len(samples[b]) < 3:
            samples[b].append((w, hi, gi))
    return per_word, c, samples


def gate1(con, rows, rebaseline=False):
    """闸① 反向重建两列，**锁漂移清单**（不是锁比率、也不是锁行数）。

    🔴 为什么不是「对不上 == 0」：本步从**今天这份 dump** 重建，而 `dict.infl` 是
       七月那份建的，上游中间换过版 —— 阶段 1 已经量到同一件事（143 个词条释义被改写、
       9 个不再产生义项）。这里看到的正是它的另一面：`ans`/`ins`/`ums`/`aufs`/`fürs`
       在阶段 1 **丢了义项**，在这里**多了变形** —— 同一次改版的两面。
    🔴 为什么不是「对不上 ≤ 某个数」：阶段 1 那道闸第一版就是写成率的阈值，
       **变异当场证明它是瞎的**（倒一个词的义项顺序，率只动 1e-5）。
       ⇒ 逐条记进基线文件，集合比较：多一个、少一个、换个桶，全都当场红。
       换基线必须是**有意**的动作（`--rebaseline`），不是静默接受。
    """
    print("\n═══ 闸① 反向重建（全量，非抽样）═══")
    per_word, c, samples = drift(con, rows)
    for k, v in c.most_common():
        print("   %-38s %8s" % (k, f"{v:,}"))
    for b, items in samples.items():
        for w, hi, gi in items:
            print("   [%s] %-20s 库=%r" % (b, w, (hi or "")[:46]))
            print("   %s %-20s 新=%r" % (" " * (len(b) + 2), "", (gi or "")[:46]))

    now = sorted("%s\t%s" % (w, b) for w, b in per_word.items())
    if rebaseline:
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text("\n".join(now) + "\n", encoding="utf-8")
        print("   ⚠️ 已重写基线 %s（%s 条）—— 这必须是一次**有意**的动作"
              % (BASELINE.name, f"{len(now):,}"))
        return True
    if not BASELINE.exists():
        print("   🔴 基线文件不存在：%s" % BASELINE)
        print("      第一次建立请跑：python3 pipeline/build_inflection_layer.py --rebaseline")
        return False
    old_ = [x for x in BASELINE.read_text(encoding="utf-8").splitlines() if x.strip()]
    add, rm = sorted(set(now) - set(old_)), sorted(set(old_) - set(now))
    print("   基线 %s 条 ／ 本次 %s 条 ／ 新增 %s ／ 消失 %s"
          % (f"{len(old_):,}", f"{len(now):,}", f"{len(add):,}", f"{len(rm):,}"))
    for x in (add[:4] + rm[:4]):
        print("      ~ %s" % x)
    ok = not add and not rm
    print("   %s" % ("✓ 漂移清单与基线逐条一致" if ok else "🔴 与基线对不上"))
    return ok


def gone_from_baseline():
    """基线里「上游不再产生变形」那一桶的词形集合 —— 闸②要用它，**读文件不重记**。"""
    if not BASELINE.exists():
        return set()
    out = set()
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            w, b = line.split("\t", 1)
            if b == "上游不再产生变形":
                out.add(w)
    return out


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    expect = dict(expect, gone=gone_from_baseline())
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
        ("🔴 (word_id, base, label_zh) 三元组重复（pt 收尾单 C8 那族）",
         q("SELECT count(*) FROM (SELECT word_id,base,label_zh FROM inflection "
           "GROUP BY 1,2,3 HAVING count(*)>1)"), 0),
        ("🔴 变形指向自己",
         q("SELECT count(*) FROM inflection i JOIN dict d ON d.id=i.word_id "
           "WHERE i.base = d.word"), 0),
        # 🔴 构词行必须与构词标签一一对应 —— 期望值**两边各自算**，不写死：
        #    左边按 `kind` 数，右边按中文标签数，两个独立口径对不上就是分流错了。
        ("kind='derivation' 的行 == 中文是构词标签的行",
         q("SELECT count(*) FROM inflection WHERE kind='derivation'"),
         q("SELECT count(*) FROM inflection WHERE " + " OR ".join(
             "label_zh LIKE '%s%%'" % zh for _k, zh in DERIV))),
        # 🔴 **本步真正要守的东西**：七月的 `exchange` 列里每一条指针，今天都必须
        #    在某个地方接住 —— 要么在变形层（真变形），要么在 2a 给它建了义项
        #    （异体/缩写，可能带 `sense_relation`、也可能是「定不出类型当普通释义收录」），
        #    要么它在漂移基线里（上游不再产生这条变形）。三条都不满足 = 有指针掉地上了。
        #    ⚠️ 期望值**算出来**不写死（`tests/test_no_literal_counts.py` 禁字面量）；
        #      漂移基线的条数由文件自己说，不由我记。
        ("🔴 exchange 里的指针掉地上了（既没进变形层，2a 也没接住）",
         con.execute(
             "SELECT count(*) FROM dict d WHERE d.exchange IS NOT NULL "
             "  AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id) "
             "  AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id) "
             # 漂移基线里「上游不再产生变形」那批不算掉地上 —— 它们的指针在**今天这份
             # dump 里已经没有了**，七月的 `exchange` 是历史值。名单由基线文件说了算。
             "  AND d.word NOT IN (%s)" % ",".join("?" * max(len(expect["gone"]), 1)),
             list(expect["gone"]) or [""]).fetchone()[0],
         0),
        # 「上游不再产生变形」那批 —— 它们在 dict 里还留着七月的 `exchange`，
        # 变形层里必然没有行。**条数由基线文件自己说**，不由我记。
        ("上游不再产生变形的词形（== 基线里的同名桶）",
         con.execute(
             "SELECT count(*) FROM dict d WHERE d.exchange IS NOT NULL "
             "  AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id) "
             "  AND d.word IN (%s)" % ",".join("?" * len(expect["gone"])),
             list(expect["gone"])).fetchone()[0] if expect["gone"] else 0,
         len(expect["gone"])),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %10s  期望 %s" % ("✓" if good else "🔴", name,
                                            f"{got:,}", f"{want:,}"))
    return ok


def mutate(con, rows):
    """🔴 变异：破坏 5 处重建结果，闸①必须全部报出。一次一个，每次从干净副本重来。

    ⚠️ 变异要打在**闸真正盯着的落点**上（`PITFALLS` G3）——
       这里盯的是「重建出来的两列字符串」，所以变异就改那个结构。
    """
    print("\n═══ 变异验证 ═══")
    base = {w: list(v) for w, v in rows.items()}
    old_ = {x for x in BASELINE.read_text(encoding="utf-8").splitlines() if x.strip()}
    multi = [w for w in sorted(base) if len(base[w]) > 1][:2]
    solo = [w for w in sorted(base) if len(base[w]) == 1][:3]
    cases = []

    def broke(name, mut):
        """🔴 变异必须打在**闸真正盯着的落点**上（`PITFALLS` G3）。
        闸盯的不是"有没有对不上"，是"对不上的那张清单和基线一不一样" ——
        所以这里也必须跟基线比。第一版比的是"对不上的个数 > 0"，
        那会**永远通过**（本来就有 61 个对不上），等于没验。"""
        got = {w: list(v) for w, v in base.items()}
        mut(got)
        per_word, _c, _s = drift(con, got)
        now = {"%s\t%s" % (w, b) for w, b in per_word.items()}
        n = len(now ^ old_)
        cases.append(n > 0)
        print("   %s  %-46s 闸%s" % ("✓" if n else "🔴", name,
                                     "报出 %d 条与基线的差异" % n if n else "没报"))

    for w in multi:
        broke("变形顺序颠倒：%s" % w, lambda g, w=w: g.__setitem__(w, list(reversed(g[w]))))
    broke("整条变形丢失：%s" % solo[0], lambda g: g.pop(solo[0]))
    broke("原形改一个字符：%s" % solo[1],
          lambda g: g.__setitem__(solo[1], [(g[solo[1]][0][0], g[solo[1]][0][1] + "X")
                                            + g[solo[1]][0][2:]]))
    # 🔴 打在**第 7 位 `legacy`** 上，不是第 2 位 `label` ——
    #    闸①比的是重建出来的 `dict.infl`，而那一列走的是 `legacy`。
    #    2026-09-01 拆出两个标签之后，原来那版变异改的是 `label`，
    #    **闸根本不看它** ⇒ 会变成一条永远通过的假绿（`PITFALLS` G3）。
    broke("中文标签改一个字符：%s" % solo[2],
          lambda g: g.__setitem__(solo[2], [g[solo[2]][0][:7] + (g[solo[2]][0][7] + "X",)]))
    ok = all(cases)
    print("\n%s" % ("✓ 五条变异全部被闸①逮到" if ok else "🔴 有变异没被逮到 —— 闸是瞎的"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--rebaseline", action="store_true",
                    help="重写漂移基线 —— 上游换版后**有意**接受新清单时才用")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
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
    ok1 = gate1(con, rows, a.rebaseline)
    if a.rebaseline:
        return 0
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0 if ok1 else 1
    if not ok1:
        print("\n🔴 闸①未过，中止 —— 复刻规则与七月不一致就不写库")
        return 1

    eid = dict(con.execute("SELECT src_ref, id FROM entry"))
    out, seen3, skipped = [], set(), Counter()
    for w, items in rows.items():
        for is_fo, base, label, gloss, tags, ent_ref, src_ref, _legacy in items:
            if not is_fo:
                continue
            # 🔴 两条都是**阶段 2c 的新断言照出来的旧账**（2c 自己一条没犯）：
            #    ① `die → der 复数主格/宾格` 在表里出现两次 —— 重建 `infl` 列时
            #       按字符串去过重，**往表里插的时候没有**（pt 收尾单 C8 同一形状）。
            #    ② `der → der 阳性单数主格` —— 德语冠词的变格表里原形本身占一格，
            #       信息是真的，但读者正站在 `der` 页上，这一行零价值。
            #    修在**产生它们的地方**，不做事后 UPDATE（`[[replay-scripts-undo-fixes]]`：
            #    本步一重跑就会把事后修复冲掉）。
            if base == w:
                skipped["变形指向自己（零信息）"] += 1
                continue
            tri = (w, base, label)
            if tri in seen3:
                skipped["同 (词形,原形,语法说明) 重复"] += 1
                continue
            seen3.add(tri)
            # 判据 import `infl_compose.DERIV` 那一份，**不在这里重列一遍 tag 名**
            kind = ("derivation" if any(k in tags for k, _ in DERIV) else "inflection")
            out.append((words[w], eid.get(ent_ref), kind, base, words.get(base),
                        label, gloss, json.dumps(tags, ensure_ascii=False), SRC, src_ref))
    for k, v in skipped.most_common():
        print("   %-46s %10s" % (k, f"{v:,}"))
    dangling = sum(1 for r in out if r[4] is None)
    no_entry = sum(1 for r in out if r[1] is None)
    print("   悬空原形（base 不在库里，阶段 3 收词后由 2c 回填）：%s" % f"{dangling:,}")
    print("   没挂上 entry 的（词形只在别人的 forms 里出现过）：%s" % f"{no_entry:,}")

    now = dbtool.snapshot()
    with dbtool.session("keep-v3-infl",
                        expect={"#inflection": len(out) - now.get("#inflection", 0)}) as s:
        s.execute("DROP TABLE IF EXISTS inflection")
        s.execute(DDL)
        for q in IDX:
            s.execute(q)
        s.executemany(
            "INSERT INTO inflection (word_id,entry_id,kind,base,base_id,label_zh,"
            "desc_en,tags,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)", out)

    con.close()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok2 = gate2(con, {"n": len(out)})
    print("\n%s" % ("✓ 两道闸全过" if ok2 else "🔴 有闸未通过"))
    return 0 if ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
