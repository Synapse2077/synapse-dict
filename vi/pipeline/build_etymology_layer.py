#!/usr/bin/env python3
"""vi 阶段 7a：**词源层**（`etymology` ＋ `entry.etym_type`）。2026-10-02。

判据全部 `import etym_sources`，本文件一行判据都不写。

═══ 两个交付物，别只做一个 ═══
① `etymology` —— 词源**散文**，三语（en/vi/zh）。⚠️ zh 版那 21,239 段 `词形［漢字］`
   **是汉字表记不是词源**，归阶段 2（已在 `han_spelling` 里）。
② `entry.etym_type` —— 结构化的来源类型，**只能从 en 版的 `etymology_templates` 来**
   （vi/zh 版实测 0 条 templates）。这一列从阶段 0 就建着、`dbtool.TRACK` 盯着，
   而到阶段 6 结束它还是 **0 行** —— 那正是 ja 的词源层缺席三个月那个形状的前兆。

═══ 🔴 挂靠：按 (词形, 词源号) 挂到 entry ═══
`etymology_number` 就是 `entry.etym_no` 的来源，所以这一层**不需要新的挂靠规则**
（义项层那条「跨版同词性」在这儿用不上）。实测 en 版 **100% 挂得上**。
⚠️ 一个词源对应**多条** entry（同一词源下的名词与动词）⇒ `etymology` 存一行，
   `entry.etym_type` 更新多行。两者行数不等是正常的，不是 bug。

═══ 🔴 多段词源**全收，不二选一** ═══
`[[etymology-layer-acceptance]]`：fr 那轮**静默二选一**，还挑错了（`sur`/`tu`）。
vi 版实测段数分布 `{1:7469, 2:643, 3:83, 4:6, 5:6+}` ⇒ 多段是真的。
`src_ref` 带段序号，**一段一行**，顺序靠 `etym_no` + 段序号可复原。
⚠️ 也**不设段数上限** —— `[[etymology-layer-acceptance]]` 记着「同一个『5 段』假设
   写在两处，只改一处三层全绿、端到端才逮到」。本文件里没有任何数字上限。

用法：
    python3 vi/pipeline/build_etymology_layer.py [--apply] [--rebuild]
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import dbtool                                                     # noqa: E402
import etym_sources as ES                                         # noqa: E402
import paths                                                      # noqa: E402

PATH_OF = {
    "en-edition": paths.KK, "vi-edition": paths.EDITION,
    "zh-edition-trad": paths.ZH_TRAD, "zh-edition-simp": paths.ZH_SIMP,
    "fr-edition": paths.FR_EDITION, "ja-edition": paths.JA_EDITION,
    "ko-edition": paths.KO_EDITION, "pl-edition": paths.PL_EDITION,
    "ru-edition": paths.RU_EDITION, "nl-edition": paths.NL_EDITION,
    "pt-edition": paths.PT_EDITION, "de-edition": paths.DE_EDITION,
}
F = lambda n: format(n, ",")                                      # noqa: E731


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def index(con):
    """→ (wid, (词,词源号)→entry_id 们, 同键但只 en 版建的, 词形总数)。

    🔴 **抽出来是为了外锚闸能 import 同一个函数**，不是为了整洁。
       闸若自己重写这段，它报的就是它自己的 bug（ko 那道外锚闸的原形）。纯搬移。
    """
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    ent = collections.defaultdict(list)
    en_ent = collections.defaultdict(list)
    for i, w, no, src in con.execute(
            "SELECT e.id, d.word, e.etym_no, e.src FROM entry e JOIN dict d ON d.id=e.word_id"):
        ent[(w, no)].append(i)
        if src == "en-edition":
            en_ent[(w, no)].append(i)
    return wid, ent, en_ent, len(wid)


def collect(wid, ent, en_ent):
    """收割 ⇒ (最终行, 统计, 跳过原因, entry_id→etym_type, 值域外的模板)。

    🔴 **抽出来是为了外锚闸能 import 同一个函数**（见 `index()`）。去重在里面，
       因为闸要比的是**最终落库的那批行**。⚠️「源头长出判据表外的模板」那条守卫
       有意留在 `main()`（它是 `raise SystemExit`，闸不该代调用方决定怎么死）。
    """
    rows, stat, skip = [], collections.Counter(), collections.Counter()
    types, unknown_tpl = {}, collections.Counter()
    for src, p in PATH_OF.items():
        lang = ES.ETYM_LANG[src]
        for e in rd(p):
            w = (e.get("word") or "").strip()
            no = str(e.get("etymology_number", "0") or "0")
            names = [t.get("name") for t in (e.get("etymology_templates") or [])]
            for n in ES.unknown_templates(names):
                unknown_tpl[n] += 1
            segs = []
            for k in ES.ETYM_KEYS:
                v = e.get(k)
                if v is None:
                    continue
                segs += [(k, t) for t in ([v] if isinstance(v, str) else (v or []))]
            if not segs:
                continue
            if w not in wid:
                stat["源词不在 dict（汉字词头等，有意不收）"] += len(segs)
                continue
            # ── `etym_type` 只从 en 版的 templates 来；一个词源对应多条 entry
            if src == "en-edition" and names:
                ty = ES.etym_type_of(names)
                if ty:
                    # 🔴🔴 **只写 en 版建的 entry**。第一版写的是 `ent[(w,no)]`（所有版），
                    #    于是 3 行 `etym_type` 落到了 vi/zh 版建的 entry 上 ——
                    #    信号只有 en 版有，而「同一个 (词, 词源号)」在不同版里
                    #    **不保证是同一个词源**（词源号都从 0 起编）。
                    #    骨架闸 S13 当场逮到（它原来的断言「阶段 1 一列都不填」过期了，
                    #    改成「只出现在 en 版建的 entry 上」之后才继续有信号）。
                    #    `[[correct-steps-can-compose-a-hole]]`：跨步假设失效。
                    for eid in en_ent.get((w, no), ()):
                        types[eid] = ty
            if lang is None:
                stat["第四语言的词源，有意不收（%s）" % src.split("-")[0]] += len(segs)
                continue
            eids = ent.get((w, no)) or []
            stat["挂得上 entry" if eids else "挂不上 ⇒ entry_id NULL"] += 1
            for si, (field, t) in enumerate(segs):
                why = ES.etym_skip_why(w, t)
                if why:
                    skip[(src.split("-")[0], why)] += 1
                    continue
                stat["✅ 可出版的词源散文（%s）" % lang] += 1
                # 🔴 主键带**段序号**：多段词源一段一行，不二选一（fr 那轮的教训）
                # 存**清洗后**的正文（判据内部也是对清洗后的文本判的，两边同一次清洗）
                rows.append((wid[w], eids[0] if eids else None, no,
                             ES.clean_etym_text(t),
                             field, src,
                             "etym:%s:%s:%s:%d" % (src.split("-")[0], w, no, si)))

    seen, out = set(), []
    for r in rows:
        if r[6] in seen:
            stat["同源重复（去重）"] += 1
            continue
        seen.add(r[6])
        out.append(r)
    rows = out
    return rows, stat, skip, types, unknown_tpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    # 纯派生层（全部从 dump 重算，无付费数据）⇒ 重跑＝清空再建，见阶段 6 的同一条
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid, ent, en_ent, tot = index(con)
    old_e = con.execute("SELECT COUNT(*) FROM etymology").fetchone()[0]
    old_t = con.execute(
        "SELECT COUNT(*) FROM entry WHERE etym_type IS NOT NULL").fetchone()[0]
    con.close()
    print("■ dict %s 词形 ／ entry 的 (词, 词源号) 组 %s" % (F(tot), F(len(ent))))

    rows, stat, skip, types, unknown_tpl = collect(wid, ent, en_ent)
    if unknown_tpl:
        print("\n🔴🔴 源头有 %d 种**可能表达来源**而判据表里没列的模板：%s"
              % (len(unknown_tpl), dict(unknown_tpl.most_common(12))))
        print("   ⇒ 逐个读它的 `expansion` 再归档到 `etym_sources` 的三张表之一，再建库。")
        raise SystemExit(1)

    print("\n■ 词源散文 %s 段（可出版）" % F(len(rows)))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("   %-44s %8s" % (k, F(v)))
    print("\n■ 被判为「不是词源」的段（**按版拆开看**，一堆是判据太宽一堆是真渣）")
    for (ed, why), v in sorted(skip.items(), key=lambda x: -x[1]):
        print("   %-6s %-26s %8s" % (ed, why, F(v)))
    print("   ⚠️ `bare-han-spelling` 那 2 万段是**汉字表记**，归阶段 2 —— "
          "它们在 `han_spelling` 里，不是丢了")

    print("\n■ `entry.etym_type`（只能从 en 版 templates 来，vi/zh 版 0 条 templates）")
    byty = collections.Counter(types.values())
    for k, v in byty.most_common():
        print("   %-18s %8s 条 entry" % (k, F(v)))
    print("   覆盖 entry %s / %s（%.1f%%）—— 其余 NULL ＝ **源头没给结构化信号**，"
          "不是「来源不明」" % (F(len(types)), F(sum(len(v) for v in ent.values())),
                          100.0 * len(types) / max(sum(len(v) for v in ent.values()), 1)))

    cov = len({r[0] for r in rows})
    print("\n■ 读者口径：有词源散文的词形 **%s（%.2f%%）**" % (F(cov), 100.0 * cov / tot))
    for lang in ("en", "vi", "zh"):
        n = len({r[0] for r in rows if ES.ETYM_LANG[r[5]] == lang})
        print("      %s 覆盖词形 %7s（%5.2f%%）" % (lang, F(n), 100.0 * n / tot))
    print("   ⭐ **中文词源是白送的** —— zh 版那批 `漢越詞，來自學習。` 就是中文，"
          "不需要翻译（对照：阶段 5b 的中文释义要花钱）")

    dbtool.sample_check([(r[3][:52], ES.ETYM_LANG[r[5]], r[4],
                          "挂entry" if r[1] else "词级") for r in rows],
                        10, ("词源", "语", "源字段", "落点"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    if (old_e or old_t) and not a.rebuild:
        raise SystemExit("🔴 etymology 已有 %s 行、entry.etym_type 已填 %s 行 —— "
                         "纯派生层，重跑要加 `--rebuild`。" % (F(old_e), F(old_t)))
    with dbtool.session(
            "build-vi-etymology-layer",
            expect={"__rows__": 0, "#etymology": len(rows) - old_e,
                    "etymology.text": len(rows) - old_e,
                    "etymology.src_field": len(rows) - old_e,
                    "entry.etym_type": len(types) - old_t},
            invalidates=["词源层落第一行 ⇒ `etymology` 从 UNCLAIMED 里拿出来，"
                         "词源层闸必须登记并跑绿（`vi/tests/test_etymology_layer.py`）；"
                         "**B18**（词源正文对读者不可见）从这一刻起是真欠账，归阶段 9"]) as s:
        if a.rebuild:
            s.execute("DELETE FROM etymology_gloss")
            s.execute("DELETE FROM etymology")
            s.execute("UPDATE entry SET etym_type=NULL")
        s.executemany(
            "INSERT INTO etymology (word_id, entry_id, etym_no, text, src_field, src, "
            "src_ref) VALUES (?,?,?,?,?,?,?)", rows)
        s.executemany("UPDATE entry SET etym_type=? WHERE id=?",
                      [(v, k) for k, v in types.items()])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]                     # noqa: E731
    checks = [
        ("etymology 行数", q("SELECT COUNT(*) FROM etymology"), len(rows)),
        ("entry.etym_type 填了几行",
         q("SELECT COUNT(*) FROM entry WHERE etym_type IS NOT NULL"), len(types)),
        ("src_ref 唯一", q("SELECT COUNT(*) FROM (SELECT src_ref FROM etymology "
                          "GROUP BY src_ref HAVING COUNT(*)>1)"), 0),
        ("每条都挂得上 dict",
         q("SELECT COUNT(*) FROM etymology e LEFT JOIN dict d ON d.id=e.word_id "
           "WHERE d.id IS NULL"), 0),
        ("entry_id 要么空要么真指向一条 entry",
         q("SELECT COUNT(*) FROM etymology x LEFT JOIN entry e ON e.id=x.entry_id "
           "WHERE x.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        ("src_field 只有那两个字段名",
         q("SELECT COUNT(*) FROM etymology WHERE src_field NOT IN "
           "('etymology_text','etymology_texts')"), 0),
        # 🔴 反向断言：裸表记一段都不许进来（它们是阶段 2 的料）
        ("🔴 没有一段是 `词形［漢字］` 裸表记",
         sum(1 for w, t in con.execute(
             "SELECT d.word, e.text FROM etymology e JOIN dict d ON d.id=e.word_id")
             if ES.is_bare_han_spelling(w, t)), 0),
        ("etym_type 都在值域里",
         q("SELECT COUNT(*) FROM entry WHERE etym_type IS NOT NULL AND etym_type NOT IN "
           "(%s)" % ",".join("'%s'" % v for v in ES.ETYM_TYPE_DOMAIN)), 0),
    ]
    for name, got, want in checks:
        print("   %s %-40s %s（期望 %s）"
              % ("✅" if got == want else "🔴", name, F(got), F(want)))
    con.close()
    if any(g != w for _n, g, w in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
