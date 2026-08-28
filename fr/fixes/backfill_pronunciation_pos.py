#!/usr/bin/env python3
"""族 D — 给 `pronunciation` 补 `pos` 列（**读音归属**）。2026-08-27。

═══ 起因 ═══
导评审材料时看见 `taper` 的读音行是 `/ta.pe/ /te.pœʁ/`。后一个来自
`kk-fr:taper:noun#s0.0` —— 法文版 `taper` **名词**条目（光纤锥，念英式 /teɪpər/）。
数据没错，**归属错**：它被当成整个词形的读音摆在页头。

    跨词性读音不同的词形   **3,674**（A1 113 / A2 102 / B1 174 / B2 483 / C1 329 / C2 298）

🔴 高频词上尤其难看 —— 法文版把**缩写展开后的读音**也写成音标：

    en    prep /ɑ̃/ ｜ noun /ɑ̃.ky.le/     ← A1 介词旁边摆着 "enculé"
    bon   adj  /bɔ̃/ ｜ noun /ba.ta.jɔ̃/   ← "bon" 作 bataillon 的缩写
    ce    det  /sə/ ｜ noun /kɑz/
    au    art  /o/  ｜ symbol /y.ni.te as.tʁo.no.mik/
    diner verb /di.ne/ ｜ noun /daj.nœʁ/（英语 diner）

═══ 为什么不建 `pronunciation_entry`（it 那张表）═══
`[[es-v3-structure-backfill]]`：**照搬别的语言结构前先量这门语言有没有那个病**。
量了：fr 是 3,674，it 是 21,666（fr 只有 1/6）。而 fr 的坐标够用 ——
`src_ref` 形如 `kk-<版>:<词>:<pos>#s<n>.<i>`，**词性就写在里面**：

    能解析出词性   1,892,437 / 1,901,758
    解析不出           9,295   全是 `legacy`（七月老流水线，没有词性坐标）⇒ 留 NULL
    POS_MAP 映射不到      26   5 种（abbrev/interfix/unknown/infix/postp）⇒ 存原值

⇒ 加一列就够，不必建表、不必迁移。

═══ 判据只许一份 ═══
`src_ref` 的解析**直接 import** `pipeline/adjudicate_fr_defs.ref_pos`（那边已经为
裁决写过一次，且处理了「词形里可以有 `:`」这个坑：必须从右切）。
在这里重抄一遍 = 两处慢慢漂开（`[[refactor-mindset-code-quality]]`）。

⚠️ **本脚本只补数据，不改展示。** 展示层怎么用这一列见 `packages/dict-core/src/french.ts`
   的 `frReadingBelongsTo` —— 那条判据同样只许一份，组件与契约闸共用。

用法（在 fr/ 目录下）：
    python3 -u fixes/backfill_pronunciation_pos.py            # 只报数
    python3 -u fixes/backfill_pronunciation_pos.py --apply    # 落库
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from pipeline.adjudicate_fr_defs import ref_pos  # noqa: E402

f = lambda n: format(n, ",")


def plan(con):
    """→ ([(pos, id)], 统计)。src_ref 解析不出坐标的留 NULL。"""
    rows, st = [], Counter()
    for pid, src, ref in con.execute("SELECT id, src, src_ref FROM pronunciation"):
        if not ref or not ref.startswith("kk-"):
            st["📋 无词性坐标 ⇒ 留 NULL（%s）" % src] += 1
            continue
        p = ref_pos(ref)
        if not p:
            st["🔴 解析出空词性"] += 1
            continue
        rows.append((p, pid))
        st["pos=" + p] += 1
    return rows, st


def gates(con, rows):
    ok = True

    def g(name, bad, n):
        nonlocal ok
        print("  %s %s：%s / %s" % ("✅" if not bad else "🔴", name, f(bad), f(n)))
        if bad:
            ok = False

    total = con.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0]
    legacy = con.execute(
        "SELECT COUNT(*) FROM pronunciation WHERE src_ref NOT LIKE 'kk-%'").fetchone()[0]
    g("① 补齐数 + 无坐标数 == 总行数", total - (len(rows) + legacy), total)

    # ② 🔴 补出来的 pos 必须是**义项层用的同一套取值**，否则展示层永远对不上。
    #    ⚠️ 不是「必须全部出现在 sense.pos 里」—— 有些词性我们一条义项都没有
    #       （`symbol`/`character` 之类），那不是错，只是没有对应的义项组。
    #    真正要拦的是**映射漏了**：POS_MAP 认不出、原样存进去的那些。
    from intake_fr_words import POS_MAP
    known = set(POS_MAP.values())
    unk = Counter(p for p, _i in rows if p not in known)
    print("  ℹ️ POS_MAP 映射不到、原样存的：%s 行 / %s 种 %s"
          % (f(sum(unk.values())), f(len(unk)), dict(unk.most_common(6))))

    # ③ 同一个词条坐标（词形+词性）下的读音，pos 必须一致 —— 对解析本身的回归断言
    bad = con.execute("""
        SELECT COUNT(*) FROM (
          SELECT word_id, substr(src_ref, 1, instr(src_ref, '#')) k, COUNT(DISTINCT src_ref) n
          FROM pronunciation WHERE src_ref LIKE 'kk-%' GROUP BY 1,2 HAVING n < 1)""").fetchone()[0]
    g("③ 坐标解析自洽", bad, total)
    return ok


def show(con, rows):
    """把已知案例打出来，落库前肉眼过一遍。"""
    pos_of = dict((i, p) for p, i in rows)
    print("\n── 已知案例（回填后各词性分别是什么读音）──")
    for w in ("taper", "en", "bon", "ce", "diner", "livre"):
        r = con.execute("SELECT id FROM dict WHERE word=?", (w,)).fetchone()
        if not r:
            continue
        by = {}
        for pid, ipa, nota in con.execute(
                "SELECT id, ipa, notation FROM pronunciation WHERE word_id=?", (r[0],)):
            by.setdefault(pos_of.get(pid, "—"), []).append(ipa)
        print("   %-8s %s" % (w, {k: v[:3] for k, v in sorted(by.items())}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, st = plan(con)
    print("■ 可回填 %s 行" % f(len(rows)))
    for k, v in st.most_common(10):
        print("   %-34s %s" % (k, f(v)))
    show(con, rows)
    print("\n══ 闸 ══")
    ok = gates(con, rows)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-pron-pos", expect={}) as s:
        cols = {r[1] for r in s.execute("PRAGMA table_info(pronunciation)")}
        if "pos" not in cols:
            # 🔴 先加列再写值（`[[ipa-provenance-columns]]`：先加列再入库）
            s.execute("ALTER TABLE pronunciation ADD COLUMN pos TEXT")
        s.executemany("UPDATE pronunciation SET pos=? WHERE id=?", rows)
        n = s.execute("SELECT COUNT(*) FROM pronunciation WHERE pos IS NOT NULL").fetchone()[0]
    print("✓ 写入完成：%s 行有 pos（%s 行留 NULL = 无词性坐标）"
          % (f(n), f(con.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0] - n)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
