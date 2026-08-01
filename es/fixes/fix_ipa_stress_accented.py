#!/usr/bin/env python3
"""es 音标**重音位置**修复 —— 仅限「词形带重音符」这一确定性子集。2026-07-31。零成本,不调模型。

═══ 这一族是怎么找到的 ═══
2026-07-31 v4-pro 盲测(1500 条,开思考,`blind_ipa_trial.py`)在「规则算得出但不同」层
标出率 81.1%,其中 26 条是**只动重音位置**的意见。逐条核对后这族劈成两半:
  · 西语本族词(多数拼写带重音符):判官对、库里错 —— hemerología / metalúrgico / pitagórico…
  · 外来词:判官错、库里对 —— super(súper) / liner / qubit / skater / crew
**判官只用来定位这一族,改法不由它定。**

═══ 判据:正字法的重音符本身就是权威 ═══
① 词形含 á/é/í/ó/ú ⇒ 重音落在该音节,**正字法唯一确定,没有外来词歧义**
   (qubit/skater/weber 这些坑词一个重音符都没有,天然被排除在外);
② 该行不是 kaikki 原生(库值 ≠ kaikki 逐字值) —— 与所有 fix_ipa_* 同一道闸;
③ `b_ipa.word_to_ipa` 算得出值,且与库值**只差重音符位置**(去掉 ˈˌ 后逐字相同)。
三条都满足才改,改成规则值。**不重算音段、不动任何其他字符。**

═══ 为什么敢信规则的重音 ═══
· 带重音符的词形 247,007 条中,**98.65%(243,665)库值已与规则一致** —— 本族 421 条是 0.17% 的异类;
· 其中 kaikki 有人工音标的 27,752 条,规则与 kaikki **逐字一致 95.92%**。
· 反面:**不带**重音符的「只差重音」1,207 条**一律不动** —— 那批靠"元音/n/s 结尾看倒数第二"
  的默认规则,而外来词不遵守它(qubit→规则 kuˈbit 是错的,库里 ˈkubit 才对)。

默认 --dry。用法(在 es/ 目录):
  python3 fix_ipa_stress_accented.py            # 预览
  python3 fix_ipa_stress_accented.py --apply    # 写库(自动备份)
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, re, shutil, sqlite3, time
from pathlib import Path

import kaikki_util
from b_ipa import word_to_ipa

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
ACC = set("áéíóúÁÉÍÓÚ")
bare = lambda s: re.sub("[ˈˌ]", "", s)


def build_plan(conn):
    rows = conn.execute("SELECT id, word, phonetic, is_lemma FROM dict "
                        "WHERE TRIM(COALESCE(phonetic,''))<>''").fetchall()
    print(f"有音标 {len(rows):,} 行,扫 kaikki 取权威值…", flush=True)
    kk = kaikki_util.phonemic_ipa({r[1] for r in rows})
    print(f"  kaikki 音位式 {len(kk):,} 词", flush=True)

    plan, guarded = [], 0
    for rid, w, p, isl in rows:
        if not any(ch in ACC for ch in w):        # ① 无重音符 → 不碰(外来词坑都在这里)
            continue
        if kk.get(w) == p:                        # ② kaikki 原生 → 不许动
            guarded += 1
            continue
        rv = word_to_ipa(w)
        if rv is None:
            continue
        rv = rv.strip("/")
        if rv != p and bare(rv) == bare(p):       # ③ 只差重音符位置
            plan.append((rid, w, p, rv, "lemma" if isl else "变形"))
    return plan, guarded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--all", action="store_true", help="打印全部(默认 30 条)")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    plan, guarded = build_plan(conn)
    conn.close()

    print(f"\n命中 {len(plan):,} 行(kaikki 原生被闸下 {guarded:,} 行)\n")
    for rid, w, p, rv, lay in (plan if a.all else plan[:30]):
        print(f"  [{lay}] {w[:26]:28} {p[:28]:30} → {rv[:28]}")
    if not a.apply:
        print(f"\n(--dry 预览。确认后加 --apply 写库)")
        return

    bak = DB.with_name(f"synapse-dict-es.pre-stress-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy2(DB, bak)
    print(f"\n已备份 → {bak.name}")
    c = sqlite3.connect(DB)
    c.executemany("UPDATE dict SET phonetic=? WHERE id=?", [(rv, rid) for rid, _, _, rv, _ in plan])
    c.commit()
    n = lambda s: c.execute(s).fetchone()[0]
    NONEMPTY = "SELECT COUNT(*) FROM dict WHERE TRIM(COALESCE({},''))<>''"
    print(f"已写入 {len(plan):,} 行")
    print(f"不变量 → 总行 {n('SELECT COUNT(*) FROM dict'):,} | "
          f"有音标 {n(NONEMPTY.format('phonetic')):,} | "
          f"有中文 {n(NONEMPTY.format('translation')):,}")
    conn2 = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    left, _ = build_plan(conn2)
    conn2.close()
    print(f"残留复查:仍命中 {len(left)} 行(应为 0)")
    c.close()


if __name__ == "__main__":
    main()
