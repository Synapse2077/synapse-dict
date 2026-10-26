#!/usr/bin/env python3
"""**骨架闸** —— ru 阶段 1 的不变量。2026-10-07。

═══ 🔴 为什么它是一道独立的闸，而不是 `build.py` 里的几行断言 ═══
vi 的骨架闸文件头写着：那 15 条不变量**原本只写在 `build.py --apply` 分支里** ——
**只在建库那一刻跑过一次**，之后谁改坏了库都没人说话。
⇒ 不变量要活在一个**每次写库都会被叫起来**的地方（`dbtool` 的挂钩 ＋ 闸台账）。

═══ 🔴🔴 判据一个都不重写 ═══
`word_norm` 的正确性查的是 `criteria.norm_ru`（它的家在 `dbtool`，带 import 时自检）；
`pos` / `entry_type` 的值域查的是 `criteria.ENTRY_TYPE`。
vi 的阶段 6 栽过：**同一个谓词两份实现只修了一份** ⇒
断言和被断言的用同一个坏判据，**双方一致报全绿**。

═══ ⭐ 其中 K3 是**读者口径**，K10 是 vi 那门最狠的那个缺陷 ═══
· **K3**：`dict.pos` 的**每一个斜杠段**都必须在值域里。
  ko 的 **K31**：词性表按 `pos_raw` 长码写而展示层读 `pos` 短码，
  **我的覆盖闸也查长码 ⇒ 双方一致报全绿而每个徽标都是空的**。
  ⇒ 闸至少要有一条是**读者口径 ＝ 展示层 SELECT 了哪一列**。
· **K10**：`word_norm` 一对多。vi 实测 **1,263 组冲突**（`norm_vi` 折大小写 ⇒
  `Mai`/`mai` 撞），而展示层 `.get()` 只取第一行 ⇒
  **1,291 个页面打不开，而且内容是错的**。俄语同形更多（`Мир`/`мир`），
  这条必须从第一天就量，并且**它的解在展示层，不在归一层**
  （归一层去折 ⇒ 毁掉 ё 的辨义，见 `dbtool.norm_ru`）。

用法：
    python3 ru/tests/test_skeleton.py
    python3 ru/tests/test_skeleton.py --mutate
"""
import argparse
import collections
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC                                  # noqa: E402

# 🔴 **花名册独立声明**，不从代码里数（`[[expectation-must-be-declared]]`）。
ROSTER = ("K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11",
          "K12", "K13", "K14")

# 🔴 **已接受基线**：K10 的 `word_norm` 冲突不是 0，而**它的解在展示层不在数据层**。
#    ⇒ 锁住**数字**不锁名字（`[[fix-regression-and-gate]]`：ACCEPT 锁数字不锁名字，
#      「已接受」≠「不再看」）。涨了就红，逼人回来看是不是又多了一类冲突。
#    ⚠️ 这个数在阶段 1 落库后由本文件 `--accept` 写下来，不许手抄。
ACCEPT = HERE / ".skeleton_accept.json"


def _accept():
    import json
    try:
        return json.loads(ACCEPT.read_text("utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


# K12：ru 版**全部义项都只是「…прич. от X」**、别的源也没给词元条目 ⇒ 屈折形
K12_FORMS = ("взбулгаченный", "густимый", "использовавший", "боящийся", "сошедший",
             # ru-crit-10：fr 版**词级** `form-of` 的姓氏变格形（义项上没有任何指针字段）
             "Хортову", "Горланцеве", "Свердлова",
             # ru-crit-15：副动词页（词级 gerund ＋ 分类「Русские деепричастия」，义项不带标签）
             "выезжая", "используя", "шевеля")
# K13：带 participle 标签、但**另有真义项**（形容词化）或**另有同形异义的词元条目** ⇒ 词元
#   `навороченный` 花哨的／`убитый` 悲痛欲绝的／`одарённый` 有天赋的（形容词化）
#   `выпивши` 另有副词条目／`развивающийся` 另有形容词条目
#   `море` 海／`вилка` 叉子／`рёв` 吼声（同时也是别的词的变格形）
K13_LEMMAS = ("навороченный", "убитый", "одарённый", "выпивши", "развивающийся",
              "море", "вилка", "рёв", "ложе",
              # ru-crit-10 的反例：fr 版也标了词级 `form-of`，但别的源另有词元条目 ⇒ 仍是词元；
              #   `Пушкин`/`Свердлов` 是姓氏的**原形**（它们的变格形才翻 0）
              "нету", "воскресать", "Пушкин", "Свердлов",
              # ru-crit-15 的反例：已词汇化的副动词（别的源另有介词/副词/连词条目）
              "благодаря", "спустя", "погодя", "хотя")


def checks(con):
    """→ [(编号, 是否通过, 说明)]。"""
    out = []
    acc = _accept()

    def q(sql, *a):
        return con.execute(sql, a).fetchone()[0]

    # ── K1 骨架非空 ────────────────────────────────────────────────
    nd, ne = q("SELECT COUNT(*) FROM dict"), q("SELECT COUNT(*) FROM entry")
    out.append(("K1", nd > 0 and ne > 0,
                "" if nd and ne else "dict=%d entry=%d，骨架层是空的" % (nd, ne)))

    # ── K2 `word_norm` ＝ `norm_ru(word)`，**判据 import 不重写** ────
    bad = [(w, n) for w, n in con.execute("SELECT word, word_norm FROM dict")
           if criteria.norm_ru(w) != n]
    out.append(("K2", not bad,
                "" if not bad else "%d 行 `word_norm` 与 `norm_ru(word)` 不符，例：%r→%r（库里是 %r）"
                % (len(bad), bad[0][0], criteria.norm_ru(bad[0][0]), bad[0][1])))

    # ── K14 `word_fold` ＝ `fold_ru(word)`（R30 的 ё 召回键；同 K2，判据 import 不重写）────
    bad14 = [(w, f) for w, f in con.execute("SELECT word, word_fold FROM dict") if criteria.fold_ru(w) != f]
    out.append(("K14", not bad14,
                "" if not bad14 else "%d 行 `word_fold` 与 `fold_ru(word)` 不符，例：%r（库里是 %r）"
                % (len(bad14), bad14[0][0], bad14[0][1])))

    # ── K3 **读者口径**：`dict.pos` 的每个斜杠段都在值域里（ko 的 K31）──
    dom = set(criteria.ENTRY_TYPE)
    seen = set()
    for (p,) in con.execute("SELECT DISTINCT pos FROM dict WHERE pos IS NOT NULL"):
        seen |= set(p.split("/"))
    extra = sorted(seen - dom)
    out.append(("K3", not extra,
                "" if not extra else
                "`dict.pos` 出现值域外的段 %s —— ko 的 K31：**展示层读哪一列，闸就查哪一列**"
                % extra[:6]))

    # ── K4 `entry_type` 与 `entry.pos` 的值域 ──────────────────────
    ets = {r[0] for r in con.execute("SELECT DISTINCT entry_type FROM dict")}
    bad4 = sorted(ets - set(criteria.ENTRY_TYPE.values()))
    eps = {r[0] for r in con.execute(
        "SELECT DISTINCT pos FROM entry WHERE pos IS NOT NULL")}
    bad4b = sorted(eps - dom)
    out.append(("K4", not (bad4 or bad4b),
                "" if not (bad4 or bad4b) else
                "值域外的值：entry_type %s ／ entry.pos %s" % (bad4, bad4b[:6])))

    # ── K5 外键完整性：每个 entry 指得到 dict ──────────────────────
    orph = q("SELECT COUNT(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
             "WHERE d.id IS NULL")
    out.append(("K5", orph == 0,
                "" if not orph else "%d 个 entry 的 word_id 指不到 dict" % orph))

    # ── K6 `is_lemma` 真的分了（不是全 1，也不是全 0）───────────────
    lem = q("SELECT COUNT(*) FROM dict WHERE is_lemma=1")
    frm = nd - lem
    # 🔴 **两个方向都断言**：只断言「有屈折形」的话，全是屈折形也能满足它
    out.append(("K6", lem > 0 and frm > 0,
                "" if (lem and frm) else
                "`is_lemma` 没分开：词元 %d／屈折形 %d —— 它决定一切覆盖率的分母"
                % (lem, frm)))

    # ── K7 没有空词头 / 空归一键 ───────────────────────────────────
    empt = q("SELECT COUNT(*) FROM dict WHERE TRIM(COALESCE(word,''))='' "
             "OR TRIM(COALESCE(word_norm,''))=''")
    out.append(("K7", empt == 0, "" if not empt else "%d 行空词头或空归一键" % empt))

    # ── K8 **闸自证**：`entry.src` 的值域 ⊆ 登记的源 ───────────────
    reg = {s for s, _ in SRC}
    got = {r[0] for r in con.execute("SELECT DISTINCT src FROM entry")}
    bad8 = sorted(got - reg)
    out.append(("K8", not bad8,
                "" if not bad8 else
                "`entry.src` 出现没登记的源 %s —— 源头多一版要当场知道，"
                "不许静默收进来（`PLAYBOOK` 7.2 闸自证）" % bad8))

    # ── K9 **七份源每一份都有行落进来**（vi 的 X12）─────────────────
    # 🔴 只查「表非空」的话，少收六版也全绿。
    miss = sorted(reg - got)
    out.append(("K9", not miss,
                "" if not miss else
                "这几份源**一行都没落进来**：%s —— 只查「表非空」看不见这个" % miss))

    # ── K10 `word_norm` 一对多（vi 那门最狠的缺陷）──────────────────
    grp = q("SELECT COUNT(*) FROM (SELECT word_norm FROM dict "
            "GROUP BY word_norm HAVING COUNT(*)>1)")
    base = acc.get("K10_groups")
    if base is None:
        ok10, why10 = False, (
            "`word_norm` 一对多 **%s 组**，而**还没有已接受基线** ——"
            " 跑一次 `--accept` 把它锁下来。⚠️ 它的解在**展示层**"
            "（按 word_norm 返回全部行），不在归一层：归一层去折会毁掉 ё 的辨义。"
            " vi 实测 1,263 组 ⇒ **1,291 个页面打不开且内容是错的**" % format(grp, ","))
    else:
        ok10 = grp <= base
        why10 = ("" if ok10 else
                 "`word_norm` 一对多涨到 **%s 组**（已接受基线 %s）—— "
                 "多出来的那些是什么？" % (format(grp, ","), format(base, ",")))
    out.append(("K10", ok10, why10))

    # ── K11 `etym_no` 是整数且 ≥0（vi 的 B18：存 TEXT ⇒ 字典序）──────
    badt = q("SELECT COUNT(*) FROM entry WHERE typeof(etym_no)<>'integer' OR etym_no<0")
    out.append(("K11", badt == 0,
                "" if not badt else
                "%d 行 `etym_no` 不是非负整数 —— vi 的 B18：存成 TEXT ⇒ 字典序让"
                "「10」排在「2」前面" % badt))

    # ── K12/K13 `is_lemma` 的已知答案表：**两个方向各一条**（ru-crit-9）────
    # 🔴🔴 2026-10-23：62,576 个形动词页被标成词元（词元的 9.78%）——ru 版不给它们
    #    `form_of`、把「X 的被动过去时形动词」写进释义。K6 只问「分没分开」，
    #    **对「分错了 1/10」结构性失明**。⇒ 钉死已知答案（常量，不锚现状 —— B20）。
    #    K12 防判据**收窄**回去（形动词页又成了词元）；
    #    K13 防判据**放宽**（形容词化的形动词／同形异义的真名词被误伤）——
    #    只断言一个方向的话，「全标 0」也能满足 K12。
    def _lemma_table(words, want):
        bad = []
        for w in words:
            r = con.execute("SELECT is_lemma FROM dict WHERE word=?", (w,)).fetchone()
            if r is None:
                bad.append("%s〔不在 dict 里 —— 已知答案表的前提坏了〕" % w)
            elif r[0] != want:
                bad.append("%s=%s" % (w, r[0]))
        return bad
    b12 = _lemma_table(K12_FORMS, 0)
    out.append(("K12", not b12,
                "" if not b12 else
                "形动词页应是屈折形（is_lemma=0）而不是：%s —— "
                "`criteria.is_inflected_form` 第四条路失效？" % " ".join(b12)))
    b13 = _lemma_table(K13_LEMMAS, 1)
    out.append(("K13", not b13,
                "" if not b13 else
                "这些是真词元（有形容词/名词/副词义项）而被标成屈折形：%s —— "
                "判据放宽成了「有一个义项带 participle 就算」？" % " ".join(b13)))
    return out


def roster_check(rows):
    got = {c for c, _, _ in rows}
    bad = []
    for cid in ROSTER:
        if cid not in got:
            bad.append("花名册里的 %s **没有出现在输出里** —— 检查被删掉了？" % cid)
    for cid in sorted(got - set(ROSTER)):
        bad.append("输出里有花名册没登记的 %s" % cid)
    return bad


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def report():
    if not paths.DB.exists():
        print("🔴 库不存在：%s" % paths.DB)
        return 1
    con = _open()
    try:
        rows = checks(con)
    finally:
        con.close()
    print("■ 骨架闸（ru 阶段 1）—— 花名册 %d 条" % len(ROSTER))
    for cid, ok, why in rows:
        print("   %s %-5s %s" % ("✅" if ok else "🔴", cid, why))
    rb = roster_check(rows)
    for b in rb:
        print("   🔴🔴 花名册自检：" + b)
    red = [r for r in rows if not r[1]]
    print("■ %s（%d/%d）" % ("全绿 ✓" if not red and not rb else "有红",
                            len(rows) - len(red), len(rows)))
    return len(red) + len(rb)


def accept():
    """把 K10 的现状锁成已接受基线。**锁数字不锁名字。**"""
    import json
    con = _open()
    try:
        grp = con.execute("SELECT COUNT(*) FROM (SELECT word_norm FROM dict "
                          "GROUP BY word_norm HAVING COUNT(*)>1)").fetchone()[0]
        tot = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
        samples = [r for r in con.execute(
            "SELECT word_norm, COUNT(*) n, GROUP_CONCAT(word,' ｜ ') FROM dict "
            "GROUP BY word_norm HAVING n>1 ORDER BY n DESC LIMIT 8")]
    finally:
        con.close()
    ACCEPT.write_text(json.dumps({"K10_groups": grp, "dict_rows": tot},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 已接受基线写入 %s：K10_groups=%s（dict %s 行）"
          % (ACCEPT.name, format(grp, ","), format(tot, ",")))
    print("   最大的几组（**它们是展示层必须按 word_norm 返回全部行的理由**）：")
    for wn, n, ws in samples:
        print("      %-18s %2d 个  %s" % (wn[:16], n, (ws or "")[:62]))
    return 0


def _mutations():
    """(编号, 说明, 在副本上执行的 SQL)。**每条自带前提**（B20）。"""
    return [
        ("K2", "把一行的 `word_norm` 改成不符合 `norm_ru` 的值",
         ["UPDATE dict SET word_norm='ZZZ' WHERE id=(SELECT MIN(id) FROM dict)"]),
        ("K14", "把一行的 `word_fold` 写回带 ё 的形（省写 ё 又搜不到）",
         ["UPDATE dict SET word_fold=word_norm WHERE id=(SELECT MIN(id) FROM dict WHERE word_norm LIKE '%ё%')"]),
        ("K3", "往 `dict.pos` 塞一个值域外的段（模拟长码混进来）",
         ["UPDATE dict SET pos='Существительное' WHERE id=(SELECT MIN(id) FROM dict)"]),
        ("K4", "往 `entry_type` 塞一个值域外的值",
         ["UPDATE dict SET entry_type='гл' WHERE id=(SELECT MIN(id) FROM dict)"]),
        ("K5", "把一个 entry 的 word_id 指向不存在的 dict",
         ["UPDATE entry SET word_id=-7 WHERE id=(SELECT MIN(id) FROM entry)"]),
        ("K6", "把所有 `is_lemma` 置 1（模拟「屈折形被当成词元」）",
         ["UPDATE dict SET is_lemma=1"]),
        ("K7", "造一个空归一键",
         ["UPDATE dict SET word_norm='' WHERE id=(SELECT MIN(id) FROM dict)"]),
        ("K8", "往 `entry.src` 塞一个没登记的源",
         ["UPDATE entry SET src='xx-edition' WHERE id=(SELECT MIN(id) FROM entry)"]),
        ("K9", "删掉某一个源的全部 entry（模拟少收一版）",
         ["DELETE FROM entry WHERE src='pl-edition'"]),
        ("K10", "多造 50 组 `word_norm` 冲突（涨过已接受基线）",
         ["INSERT INTO dict(word,word_norm,entry_type,is_lemma) "
          "SELECT word||'ZZ'||CAST(id AS TEXT), word_norm, 'word', 1 FROM dict "
          "WHERE id IN (SELECT id FROM dict LIMIT 50)"]),
        # 🔴🔴 **这条变异第一版是空操作，而闸自己报了出来。**
        #    第一版写 `etym_no='10'` —— SQLite 的 **INTEGER 亲和性**把这个字符串
        #    **静默转成整数 10**，`typeof` 根本没变 ⇒ 变异什么都没注入而闸「没红」。
        #    （实测：'10' → integer 10 ／ '1.1' → **real 1.1** ／ 'abc' → **text**。）
        #    ⭐ `[[wait-loops-lie-about-progress]]` 那一族的同形：
        #      **什么都没注入而检查「通过」**。⇒ 变异必须动**判据真正读的那个量**
        #      （这里是 `typeof`），而不是「看起来像是改了」。
        #    ⇒ 用 `'1.1'` —— 它正是让 `etym_sub` 这一列存在的那个真实值。
        ("K11", "把一行 `etym_no` 写成 `'1.1'`（亲和性转不成整数 ⇒ typeof 变 real）",
         ["UPDATE entry SET etym_no='1.1' WHERE id=(SELECT MIN(id) FROM entry)"]),
        ("K12", "把一个形动词页改回词元（判据收窄回 ru-crit-8）",
         ["UPDATE dict SET is_lemma=1 WHERE word='взбулгаченный'"]),
        ("K13", "把一个形容词化的形动词标成屈折形（判据放宽）",
         ["UPDATE dict SET is_lemma=0 WHERE word='навороченный'"]),
    ]


def mutate():
    if not paths.DB.exists():
        print("🔴 库不存在，变异没法做")
        return 1
    if report():
        print("\n🔴 基线就不绿，先修基线（否则分不清是变异还是旧红）")
        return 1
    print("\n■ 变异验证（%d 条，跑在库的副本上，真库一个字节不动）" % len(_mutations()))
    real = paths.DB
    fails = []
    # 🔴 K1 没有变异档（删空库那条跑不起来：副本删空之后别的检查会连带炸，
    #    两种失败混在一起就分不开了）。**这件事要显式说，不许沉默跳过。**
    print("   ⚠️ K1    无变异档：把库清空会让别的检查连带炸，两种失败混在一起分不开")
    for cid, why, sqls in _mutations():
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / real.name
            shutil.copy2(real, cp)
            paths.DB = cp
            try:
                con = sqlite3.connect(cp)
                for s in sqls:
                    con.execute(s)
                con.commit()
                con.close()
                con = _open()
                try:
                    got = {c for c, ok, _ in checks(con) if not ok}
                finally:
                    con.close()
                if cid in got:
                    print("   ✅ %-5s %s" % (cid, why))
                elif got:
                    print("   🔴 %-5s 红了，但红的是 %s，不是它自己 —— %s"
                          % (cid, sorted(got), why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-5s **一条都没红** —— 判据是假的或变异是空操作：%s"
                          % (cid, why))
                    fails.append(cid)
            finally:
                paths.DB = real
    if report():
        print("\n🔴🔴 反控制失败：真库基线不绿了 —— 副本隔离破了")
        return 1
    print("\n%s" % ("■ 变异验证全过 ✓，反控制：真库基线仍全绿" if not fails
                    else "🔴 %d 条没逮到：%s" % (len(fails), fails)))
    return 1 if fails else 0


def check_brief():
    if not paths.DB.exists():
        return [("K?", "库不存在")]
    con = _open()
    try:
        return [(c, w) for c, ok, w in checks(con) if not ok]
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--accept", action="store_true",
                    help="把 K10 的现状锁成已接受基线（锁数字不锁名字）")
    a = ap.parse_args()
    if a.accept:
        raise SystemExit(accept())
    raise SystemExit(mutate() if a.mutate else (1 if report() else 0))


if __name__ == "__main__":
    main()
