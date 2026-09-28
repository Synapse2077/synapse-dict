#!/usr/bin/env python3
"""K15：谚语的「成分拆解」进关系层 —— **复用已有的 `proverb` kind，不发明新的**。2026-09-26。

═══ 这批是什么 ═══
韩文版给谚语/惯用句词条时，把**构成它的那些词**塞进 `examples[]`：

    词条 `가난한 놈은 성도 없나`  →  가난하다 ／ 놈은 ／ 성도 ／ 없다
    词条 `가슴을 찢다`          →  가슴 ／ 찢다

2026-09-24 已标 `hidden=1`/`hidden_why='词条成分拆解'`（339 条，91 个谚语词条）。
账上写的结清条件是「进关系层（新 kind，例如 `idiom_component`），或者写明为什么不值得进」。

═══ 🔴🔴 **不发明新 kind** —— 现成的 `proverb` 就是这件事，而且方向正好 ═══
动手前查了一遍值域（`[[refactor-mindset-code-quality]]`：动手前先找有没有现成的）：

    kind='proverb'  **404 条**，方向是   개 → 개 눈에는 똥만 보인다
                                        （「这个**词**出现在这个谚语里」）

而 339 条成分拆解的信息就是 (谚语, 成分) 这一对 —— 按 `proverb` 的方向存，
它等于给这个现成特性**再加 276 条**，而不是造第二套机制：

    · 不用加映射（`KO_RELATION_LABELS.proverb` 已经是「谚语」）
    · 不用动展示层、不用改覆盖闸、不用改契约闸
    · 「谚语 → 它的成分」那个视图**反查同一批边就能渲染**，不需要另存一份

⚠️ 反过来说：如果哪天要把「谚语 → 成分」做成页面上的一块，那是**展示层**的事
   （一条反向 SQL），不是再插 276 行。

═══ 两个方向的扇出都量过，都不是怪物 ═══
    正向（谚语 → 成分）    1–8 条，中位 4
    反向（成分 → 谚语）    最大 **7**（`먹다`），≥3 的只有 11 个成分 / 共 275 个
    插完之后单页最多 10 条（`개`：现有 6 ＋ 新增 4）
⇒ `[[display-extremes-doc]]` 那种「关系怪物」在这一层不存在。

═══ 成分怎么解到词（判据，带实测代价）═══
    ① 原样在 `dict` 里且是词元                    293 条
    ② 剥掉括号注之后是词元（`은(銀)`→`은`、`서(셋)`→`서`）  +11 条
    ③ 解不出：**30 条**，全是「体言＋助词」形（`놈은`／`싸움에`／`것보다`／`귀에`）
       与多词短语（`먹다 보다`／`삼 년`／`식후 구경`）
       🔴 **查过我们自己的变形层：0/24 命中** —— `inflection` 管用言活用，
         不管体言＋助词。⇒ 没有形态分析器就解不出，**不猜**。
    ④ 成分是非词元 4 条 ⇒ 跳过（同形异义风险，与 K11 同一条规则）
    ⑤ `《 》` 那个标点词条的 `《위키낱말사전》` 1 条 ⇒ **不是成分**，当初标注判据偏宽

跑（在仓库根）：
    python3 -u ko/pipeline/intake_idiom_components.py
    python3 -u ko/pipeline/intake_idiom_components.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import random
import sqlite3

import dbtool
import paths
from intake_word_formation import bare      # 🔴 剥括号的判据只有一份家，不重写

f = lambda n: format(n, ",")
KIND = "proverb"
WHY = "词条成分拆解"

# 🔴 **有意不收**，逐条读过。
NOT_A_COMPONENT = {
    "《위키낱말사전》": "`《 》` 是标点词条，它的这条「例句」是用例不是成分 —— "
                       "当初标 `词条成分拆解` 的判据在这一条上偏宽",
}


def resolve(comp, info):
    """成分 → `dict` 里的那个词。→ (词, 理由) 或 (None, 为什么解不出)。

    ⚠️ 只有两步，**有意不做第三步**：不猜助词、不猜分词。
       第三步会是「剥掉 은/는/이/가/에…」，而它在 `낮말`（不是 낮＋말）、
       `약이다`（药＋이다）这类上必定误伤，且我们没有可以背书它的形态层
       （实测变形层对这 24 个形 **0/24** 命中）。
    """
    if comp in info and info[comp][1]:
        return comp, "原样是词元"
    b = bare(comp)
    if b != comp and b in info and info[b][1]:
        return b, "剥括号注后是词元"
    if comp in info or (b != comp and b in info):
        return None, "在 dict 里但不是词元（同形异义风险）"
    return None, "解不出（体言＋助词 / 多词短语）"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=20)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT id, word, text, src FROM example WHERE hidden_why = ? ORDER BY id",
        (WHY,)).fetchall()
    idioms = {r[1] for r in rows}
    print("■ `hidden_why='%s'` 的行 %s 条，落在 %s 个谚语词条上"
          % (WHY, f(len(rows)), f(len(idioms))))

    info = {}
    for w, i, il in con.execute("SELECT word, id, is_lemma FROM dict ORDER BY id"):
        info.setdefault(w, (i, il))
    have = collections.defaultdict(set)
    for wid, t, tn in con.execute(
            "SELECT word_id, target, target_norm FROM sense_relation WHERE kind = ?", (KIND,)):
        have[wid].add(tn or t)

    cand, stat = [], collections.Counter()
    for eid, idiom, comp, src in rows:
        if comp in NOT_A_COMPONENT:
            stat["有意不收（见 NOT_A_COMPONENT）"] += 1
            continue
        if idiom not in info:
            stat["🔴 谚语词条不在 dict —— 这本身要查"] += 1
            continue
        got, why = resolve(comp, info)
        if got is None:
            stat["挂不上：" + why] += 1
            continue
        wid = info[got][0]
        if idiom in have[wid]:
            stat["这条 `%s` 边已经有了" % KIND] += 1
            continue
        cand.append((eid, got, wid, idiom, src))
        stat["✅ 要插"] += 1

    print("\n■ 分类")
    for k, v in stat.most_common():
        print("   %-42s %s" % (k, f(v)))

    # 🔴 词级边的 UNIQUE 靠不住（`sense_id` 是 NULL、NULL≠NULL）⇒ 自己去重
    seen, uniq = set(), []
    for x in cand:
        key = (x[2], x[3])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(x)
    if len(uniq) != len(cand):
        print("   ⚠️ 批内自重复 %d 条已去掉" % (len(cand) - len(uniq)))

    print("\n■ 要插 %s 条 `%s` 边（方向：**成分 → 谚语**，与现有 404 条同向）"
          % (f(len(uniq)), KIND))
    # 🔴 插完之后有没有页被撑成怪物 —— **写前就算出来**，不是写完再看
    add = collections.Counter(x[1] for x in uniq)
    worst = []
    for comp, n in add.most_common(6):
        cur = len(have[info[comp][0]])
        worst.append((comp, cur, n, cur + n))
    print("   插完后 `%s` 边最多的几页：" % KIND)
    for comp, cur, n, tot in worst:
        print("      %-12s 现有 %2d ＋ 新增 %2d = %d" % (comp, cur, n, tot))
    if worst and worst[0][3] > 40:
        raise SystemExit("🔴 `%s` 会被撑到 %d 条 —— 先回去想展示形态（DISPLAY_EXTREMES）"
                         % (worst[0][0], worst[0][3]))

    print("\n■ 抽 %d 条人眼看（左边是**成分**，右边是它出现的**谚语**）" % a.sample)
    pick = list(uniq)
    random.Random(20260926).shuffle(pick)
    for eid, comp, _wid, idiom, _src in pick[:a.sample]:
        print("   [%-6s] %-12s → %s" % (eid, comp, idiom))

    if not uniq:
        print("\n■ 没有要插的")
        con.close()
        return
    n_before = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    n_kind = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE kind=?", (KIND,)).fetchone()[0]
    n_norm = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL").fetchone()[0]
    con.close()

    if not a.apply:
        print("\n（干跑。读过抽样之后 --apply）")
        return

    # 谚语词条**全部在 dict**（实测 91/91）⇒ `target_norm` 一律非空、边都可点
    ins = [(x[2], KIND, x[3], x[3], x[4], "ko-example:%d#k15:0" % x[0]) for x in uniq]
    with dbtool.session(
            "ko-k15-intake-idiom-components",
            expect={"#sense_relation": len(ins),
                    "sense_relation.target": len(ins),
                    "sense_relation.target_norm": len(ins),
                    "__rows__": 0},
            invalidates=[]) as s:
        s.executemany(
            "INSERT INTO sense_relation (word_id, sense_id, kind, target, target_norm,"
            " tags, hidden, src, src_ref) VALUES (?, NULL, ?, ?, ?, NULL, 0, ?, ?)", ins)

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    checks = [
        ("sense_relation 行数", q("SELECT COUNT(*) FROM sense_relation"), n_before + len(ins)),
        ("%s 边条数" % KIND, q("SELECT COUNT(*) FROM sense_relation WHERE kind=?", KIND),
         n_kind + len(ins)),
        ("target_norm 非空", q("SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL"),
         n_norm + len(ins)),
        ("新边 src_ref 唯一",
         q("SELECT COUNT(DISTINCT src_ref) FROM sense_relation WHERE src_ref LIKE '%#k15:%'"),
         len(ins)),
        ("新边一条不多不少",
         q("SELECT COUNT(*) FROM sense_relation WHERE src_ref LIKE '%#k15:%'"), len(ins)),
        # 🔴 反向：新边的 `target_norm` **一条都不许悬空**（谚语全在 dict）
        ("新边没有悬空目标",
         q("SELECT COUNT(*) FROM sense_relation sr WHERE sr.src_ref LIKE '%#k15:%'"
           " AND NOT EXISTS (SELECT 1 FROM dict d WHERE d.word = sr.target_norm)"), 0),
        # 🔴 反向：没有动到别的 kind
        ("别的 kind 一条没变",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind<>?", KIND),
         n_before - n_kind),
    ]
    # 头/中/尾三条各自回读，标签从**库里**取（别从循环变量取 —— K11 那次就印错了对象）
    for pos in (0, len(uniq) // 2, len(uniq) - 1):
        _e, comp, wid, idiom, _s = uniq[pos]
        page = q("SELECT word FROM dict WHERE id=?", wid)
        got = q("SELECT COUNT(*) FROM sense_relation WHERE word_id=? AND kind=? AND target=?",
                wid, KIND, idiom)
        checks.append(("样例 `%s → %s` 在库里" % (page, idiom), got, 1))
        checks.append(("样例挂载页确实是 `%s`" % comp, page == comp, True))
    ok = True
    for name, got_v, want in checks:
        good = got_v == want
        ok &= good
        print("   %s %-34s %9s（期望 %s）"
              % ("✅" if good else "🔴", name[:34], got_v, want))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
