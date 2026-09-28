#!/usr/bin/env python3
"""把阶段 4a 跳过的那批义项收进**证据层**。ko，2026-09-26（K12）。

═══ K12 的两个方向，数据已经选出了一个 ═══
账上写：「决定把这批收进证据层（出版与否另议），**或者证明它们与库里已有义项重复**」。
2026-09-26 逐条分类（判据全部 import，不重写）：

    版                缺口    元描述   真内容   真内容占比
    ko-edition      21,101       0   21,092    100.0%
    zh-简           18,276  11,088    7,177     39.3%
    zh-繁           11,301   1,492    9,809     86.8%
    ─────────────────────────────────────────────────────
    合计            50,678  12,580   38,078     75.1%

⇒ **75.1% 是真内容，不是重复** —— 「证明它们重复」这条路被数据否掉了。

🔴🔴 **其中最刺眼的一类**：zh 版那 7,177 条真中文释义里，**7,065 条对应的词，
   它现在的中文是我们花钱让模型译的**（`가을 → 秋，秋天，秋季`、
   `일본 → 日本（位於亞洲的國家）`、`넷 → 四`）—— 源头白送的中文就在那儿，
   我们跳过它，然后付钱译了英文释义。另有 **112 条**对应的词**现在一条中文都没有**
   （`唐 → 唐朝`、`淚 → 眼泪`）。
   ⚠️ 这不等于「阶段 5 的钱全白花」：模型译的是**那一条义项**的中文，
     zh 版给的是**它自己那条义项**的中文，两者未必是同一条义项。
     但「白送的没拿」这一点是确定的。

═══ 只收真内容，元描述有意不收 ═══
**12,580 条元描述不收**（`汉字或谚汉混合表记：금발（金髮）`）。判据 import
`fix_meta_gloss.META` —— 就是 K10 那一族，实测 97.2% 是它，收进来只会把
证据层灌成噪声，而出版层还得再筛一遍。
⚠️ 这是**有意的缺口**，`verify_vs_dump.py` 的 `BUDGET` 要跟着改成只剩这一部分 ——
  否则闸会继续替一个**已经作废的理由**背书（账上原话）。

═══ 收进证据层 ≠ 出版 ═══
`sense_src.sense_id = NULL`（尚未裁决），`sense` / `sense_gloss` 一行不动。
🔴 **出版与否是另一个决定，而且该问用户**：拿 zh 版源头给的中文去顶替
   已经付过钱的模型译文，涉及「读者看到哪一版」，不是纯技术选择。⇒ 记 K31。

跑（在仓库根）：
    python3 -u ko/pipeline/intake_skipped_senses.py
    python3 -u ko/pipeline/intake_skipped_senses.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import gzip
import json
import sqlite3

import dbtool
import paths
# 🔴🔴 **判据必须与外锚闸 `verify_vs_dump.dump_senses()` 逐字一致**，否则
#    「收进来」和「闸认为还缺」永远对不上。第一版我用了 `real_senses`（它**排除指针义项**），
#    而 ko 的方针是**证据层全收指针**（en 版的指针行本来就在库里）⇒ 少收 7,236 条，
#    而闸照旧报缺、我还以为是别的原因。
#    ⇒ 三条取法照搬闸：gloss 取 `glosses[-1]`／不排除指针／排除 `pos ∈ NOT_A_WORD`；
#      词形一律过 `norm_ko`。
from criteria import NOT_A_WORD, norm_ko
import verify_vs_dump as V                 # 🔴 `db_senses()` 判据的唯一家
from fix_meta_gloss import META            # 元描述判据：与 K10 的修复同一份

f = lambda n: format(n, ",")

# 版 → (路径, 是否 gz, 这一版释义的语言)
SRC = [
    ("ko-edition", paths.EDITION, False, "ko"),
    ("zh-edition-simp", paths.ZH_SIMP, True, "zh"),
    ("zh-edition-trad", paths.ZH_TRAD, True, "zh"),
]


def opener(path, gz):
    return gzip.open(path, "rt", encoding="utf-8") if gz else open(path, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    # 🔴🔴 **为什么需要 `--redo`**：2026-09-26 第一轮我用了 `real_senses`（排除指针），
    #    第二轮改成照搬外锚闸（不排除指针）⇒ **义项序号的语义变了**，
    #    同一个 `src_ref` 串在两套判据下指向不同的义项。
    #    而 `src_ref` 是这条证据的**身份与可追溯性**（`[[model-answer-files-key-by-id]]` 同族）。
    #    ⇒ 不许两套 ref 混在库里。`--redo` 先把本脚本上一轮的产物（`#k12:` 标记）删掉，
    #      再用**唯一一份判据**重收，保证「库里的行能从判据复算出来」。
    ap.add_argument("--redo", action="store_true",
                    help="先删掉本脚本上一轮收的（src_ref 带 #k12:），再重收")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {norm_ko(w): i for i, w in con.execute("SELECT id, word FROM dict")}
    # 🔴🔴 **不再自己写这个集合 —— import 闸那一份 `db_senses()`。**
    #    我在这个脚本里因为「自己重写闸的判据」栽了**三次**，每次都是修完才发现下一处：
    #      ① 用 `real_senses`（排除指针）而 ko 的方针是证据层全收指针 ⇒ 少收 7,236
    #      ② 词形没过 `norm_ko` ⇒ 归一口径不一致
    #      ③ `have` 里**算进了模型译文** ⇒ `칫솔 → 牙刷` 被当成「已有」而跳过，
    #         可源头那条 `牙刷` 是**证据**、模型那条是**译文**，两者不能互相顶替
    #         （闸有意写了 `WHERE g.src NOT LIKE 'model:%'`，而我没抄这一句）。
    #    ⇒ 判据只有一个家：`verify_vs_dump.db_senses`。**一个字都不在这里重写。**
    have = V.db_senses(con)
    # `--redo` 要重收本脚本上一轮的产物 ⇒ 把它们从 `have` 里剔掉，否则全被当成「已有」
    if True:
        mine = {(norm_ko(w), (t or "").strip()) for w, t in con.execute(
            "SELECT d.word, x.text FROM sense_src x JOIN dict d ON d.id = x.word_id"
            " WHERE x.src_ref LIKE '%#k12:%'")}
        have -= mine
    have_ref = {r for r, in con.execute(
        "SELECT src_ref FROM sense_src WHERE src_ref NOT LIKE '%#k12:%'")}
    n_src_before = con.execute("SELECT COUNT(*) FROM sense_src").fetchone()[0]
    n_sense_before = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    n_gloss_before = con.execute("SELECT COUNT(*) FROM sense_gloss").fetchone()[0]
    n_sid_before = con.execute(
        "SELECT COUNT(*) FROM sense_src WHERE sense_id IS NOT NULL").fetchone()[0]
    con.close()

    prev = con0_prev = None
    con_chk = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    prev = con_chk.execute(
        "SELECT COUNT(*) FROM sense_src WHERE src_ref LIKE '%#k12:%'").fetchone()[0]
    prev_ids = [r[0] for r in con_chk.execute(
        "SELECT id FROM sense_src WHERE src_ref LIKE '%#k12:%'")]
    con_chk.close()
    if prev and not a.redo:
        raise SystemExit(
            "🔴 库里已有 %s 条本脚本收过的行（src_ref 带 `#k12:`）。\n"
            "   判据变过就不能叠着收 —— 加 `--redo` 先删掉上一轮再重收。" % f(prev))

    rows, stat = [], collections.Counter()
    seen_ref = set()
    # (版, 词形, pos, etym_no) → 已经见过几条记录。见 `occ` 的注释。
    occurrence = collections.Counter()
    for name, path, gz, lang in SRC:
        with opener(path, gz) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("pos") in NOT_A_WORD:
                    continue
                w = (d.get("word") or "").strip()
                if not w:
                    continue
                nw = norm_ko(w)
                pos = d.get("pos") or "unknown"
                eno = str(d.get("etymology_number") or 0)
                key = (name, nw, pos, eno)
                occ = occurrence[key]      # 0,1,2,… 第几条记录
                occurrence[key] += 1
                # 不排除指针义项 —— ko 的证据层全收（与闸同一条）
                for i, se in enumerate(d.get("senses") or []):
                    gl = se.get("glosses") or []
                    g = (gl[-1] or "").strip() if gl else ""
                    if not g:
                        continue
                    if (nw, g) in have:
                        stat["跳过·库里已有这条二元组·" + name] += 1
                        continue
                    if nw not in wid:
                        stat["🔴 跳过·词形不在 dict·" + name] += 1
                        continue
                    if META.match(g):
                        stat["有意不收·元描述（K10 那一族）·" + name] += 1
                        continue
                    # `src_ref` 是这条证据的身份，**UNIQUE 约束会拦，但先自己查一遍**。
                    # 🔴🔴 **第一版少了 `occ`，2,667 条撞了 ref 被跳过**（ko 1,951／
                    #    zh-繁 687／zh-简 29）。原因：同一个词在 dump 里有**多条记录**
                    #    （同 pos、同 etym_no），而义项序号 `i` 在每条记录里都从 0 重新数 ⇒
                    #    第二条记录的义项 0 与第一条撞上。
                    #    ⚠️ 这与 `harvest_ja_glosses` 踩过的**同一个坑**（`가` 在 ja 版有 18 条
                    #    记录、每条的 `si` 都从 0 起）—— 那次已经写下「源头 id ＋ 全局running number」，
                    #    我这次又忘了。⇒ 加 `occ`：这是该词在本版里的**第几条记录**。
                    #    ⭐ 幸好它不是静默丢：撞了就计进 🔴 那一行，干跑时看得见。
                    ref = "%s:%s:%s:%s:%d#k12:%d" % (name, nw, pos, eno, occ, i)
                    if ref in have_ref or ref in seen_ref:
                        stat["🔴 跳过·src_ref 撞了·" + name] += 1
                        continue
                    seen_ref.add(ref)
                    tags = se.get("tags")
                    rows.append((wid[nw], name, ref, lang, g,
                                 json.dumps(tags, ensure_ascii=False) if tags else None))
                    stat["✅ 要收·" + name] += 1

    print("■ 分类（判据全部 import：闸的取法 / `META`）")
    for k in sorted(stat):
        print("   %-52s %s" % (k, f(stat[k])))
    take = collections.Counter(r[1] for r in rows)
    print("\n■ 要收进证据层 %s 条：%s" % (f(len(rows)), dict(take)))
    print("\n■ 样本")
    for r in rows[:10]:
        print("   %-16s %-3s %s" % (r[1], r[3], r[4][:56]))

    if not rows:
        print("\n■ 没有要收的")
        return
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    if prev:
        n_src_before -= prev
        with dbtool.session(
                "ko-intake-skipped-senses-redo-cleanup",
                expect={"#sense_src": -prev}, invalidates=[]) as s0:
            s0.executemany("DELETE FROM sense_src WHERE id=?", [(i,) for i in prev_ids])
        print("■ 已删掉上一轮的 %s 条（判据变了，ref 不许两套混着）" % f(prev))

    with dbtool.session(
            "ko-intake-skipped-senses",
            expect={"#sense_src": len(rows), "sense_src.sense_id": 0},
            # 🔴 只动证据层。出版层一行不碰 ⇒ 覆盖率、空白页、翻译账全不受影响。
            invalidates=[]) as s:
        s.executemany(
            "INSERT INTO sense_src (word_id, sense_id, src, src_ref, lang, text, raw_tags)"
            " VALUES (?, NULL, ?, ?, ?, ?, ?)", rows)

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("sense_src 行数", q("SELECT COUNT(*) FROM sense_src"), n_src_before + len(rows)),
        # 🔴 反向：出版层一行都不许动 —— 收进证据层**不是**出版
        ("sense 行数没变", q("SELECT COUNT(*) FROM sense"), n_sense_before),
        ("sense_gloss 行数没变", q("SELECT COUNT(*) FROM sense_gloss"), n_gloss_before),
        ("新收的全是未裁决（sense_id 为空）",
         q("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NOT NULL"), n_sid_before),
        ("src_ref 全唯一", q("SELECT COUNT(*) FROM (SELECT src_ref FROM sense_src"
                            " GROUP BY src_ref HAVING COUNT(*)>1)"), 0),
        # 🔴 抽两条点名：白送的中文确实进来了
        # 🔴 写成存在性判断，不写死条数 —— 一个词在两片中文版里可能各有一条，
        #    钉死 `== 1` 是又一次「凭印象写期望值」。
        ("`가을` 的 zh 版释义进了证据层",
         q("SELECT COUNT(*) FROM sense_src x JOIN dict d ON d.id=x.word_id"
           " WHERE d.word='가을' AND x.src LIKE 'zh-edition%' AND x.text LIKE '%秋%'") > 0, True),
        ("`唐` 的 zh 版释义进了证据层",
         q("SELECT COUNT(*) FROM sense_src x JOIN dict d ON d.id=x.word_id"
           " WHERE d.word='唐' AND x.src LIKE 'zh-edition%'") > 0, True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-38s %9s（期望 %s）" % ("✅" if good else "🔴", name, str(got), str(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
