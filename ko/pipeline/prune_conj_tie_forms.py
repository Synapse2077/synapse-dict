#!/usr/bin/env python3
"""删掉「规则平局」生成的活用形。ko，2026-09-26（K18 可指认的那一部分）。

═══ K18 的结构性难点，先说清楚 ═══
账上要求「把那 322 条挑出来修」。**按构造做不到**：

    有真值的词我们不生成；我们生成的词没有真值。

生成对象恰恰是「源头一张活用表都没有」的 7,590 个用言，而 322 是留出法
（在**有表的词**上测）的错误率乘以 745,037 行得出的**统计期望**，不是清单。

═══ 于是先问一个可判的问题：残差能不能分层？═══
`ko/probes/conj_residual_strata.py`，在留出集上测（那里有真值）：

    ① 按**变体支持度**分层 ⇒ **可以**
         支持度 [0.80,0.90)     25 命中 /  21 错  错率 **84.0%**
         支持度 [0.90,1.00)  2,336 命中 /   6 错  错率 0.257%
         支持度  =1.00     173,617 命中 /  54 错  错率 0.031%
       低支持度的错率是满支持度的 **2,178 倍**。
    ② 按**支撑键的词元数**分层 ⇒ **不行**（假设被数据推翻）
         ≤5 个词元支撑：错率 0.011%   ≥6 个：0.050%  —— 少样本反而错得更少

⇒ 可指认的只有支持度低的那一小撮。全量生成集里支持度 <0.90 的共 **11 条**，
  **全在 `야멸치다` 一个词元上**，而且支持度恰好都是 **0.50**。

═══ 根因：`learn()` 的门槛在平局时把对立的两边都留下了 ═══
    rule[k] = {v for v, n in d.items() if n >= 0.5 * seen[k]}    ← `>=`

平局（两个变体各占一半）意味着**训练词元互相矛盾**，而 `>=` 两边都收：

    야멸치냐 / 야멸친데 / 야멸치다      形容词词尾 ✅
    야멸치느냐 / 야멸치는데 / 야멸친다   动词词尾  ❌

数据自己给的证据（pos 明确是 adj 的训练词元，不是我的语感）：

    ["contrastive","informal"]   신데×778  으신데×117  은데×77  **는데×43**
    ["formal","indicative"]      시다×778  으시다×117  **신다×3**
    ["formal","interrogative"]   냐×781  시냐×778  으시냐×117  으냐×77  **느냐×43**

⇒ 动词词尾是压倒性的少数派。`conj_generate.learn()` 的门槛已改成严格多数
  （改完重跑留出法，各类错率**一字未变** —— 没有伤到准确率）；
  本脚本清掉已经落库的那 11 条。

⚠️ **连对的 5 条一起删**：那 3 个 tags 组合会一条形式都不剩。有意如此 ——
   读者看见 `야멸친다`（错）比看不见更糟（`[[dict-framework-doc]]`）。

⚠️ **剩下约 310 条不可指认**：它们散在 738,203 条满支持度的行里（错率 0.031%），
   而我试过的两种内部信号只有一种有效、且只圈住 11 条。⇒ K18 余下部分的结论与
   翻案条件写在账上，不在这里。

跑（在仓库根）：
    python3 -u ko/pipeline/prune_conj_tie_forms.py
    python3 -u ko/pipeline/prune_conj_tie_forms.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "probes"))

import argparse
import collections
import sqlite3

import conj_generate as G
import conj_residual_strata as S
import dbtool
import paths

f = lambda n: format(n, ",")

TIE = 0.5 + 1e-9   # 「平局」＝ 支持度不超过一半


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    info = G.load_info(con)

    # 🔴 用**旧门槛**重算一遍，才找得到已经落库的平局变体。
    #    判据不重写：`learn_with_support` 与 `G.learn` 是同一套统计，
    #    只是把 `learn()` 算过又丢掉的那个比值留下来（见 probes 那份文件头）。
    R, support, real = S.learn_with_support(con, info)
    IDX = G.index_rules(R)
    use, tot = G.tag_share(real, info, sorted(real))

    targets = sorted({b for b, in con.execute(
        "SELECT DISTINCT base FROM inflection WHERE src = 'rule'")})
    ties = []
    for b in targets:
        if b not in info or info[b][0] not in G.SAFE:
            continue
        for tags, w, sup in S.generate_with_support(
                info, IDX, support, b, G.keepset(use, tot, info, b)):
            if sup <= TIE:
                ties.append((b, tags, w, sup))

    print("■ 生成过的词元 %s 个；支持度 ≤0.50（平局）的生成形 %s 条"
          % (f(len(targets)), f(len(ties))))
    byb = collections.Counter(b for b, _t, _w, _s in ties)
    print("   涉及词元：%s" % dict(byb))
    for b, tags, w, sup in ties:
        print("   %-12s → %-14s sup=%.2f  %s" % (b, w, sup, tags))

    # 落到库里的 inflection 行
    want = {(b, w) for b, _t, w, _s in ties}
    rows = [(rid, wid, base, word) for rid, wid, base, word in con.execute(
        "SELECT i.id, i.word_id, i.base, d.word FROM inflection i"
        " JOIN dict d ON d.id = i.word_id WHERE i.src = 'rule'")
        if (base, word) in want]
    print("\n■ 库里对应的 inflection 行 %s 条" % f(len(rows)))

    # 🔴 词形行只在**它彻底没人要**时才删：没有别的 inflection、没有义项、
    #    没有读音、不是词元。留着一个孤儿 dict 行 ＝ 搜得到、点进去空白页，
    #    那正是这个项目一直在治的东西。
    dict_drop, dict_keep = [], []
    for _rid, wid, _b, word in rows:
        n_infl = con.execute(
            "SELECT COUNT(*) FROM inflection WHERE word_id=?", (wid,)).fetchone()[0]
        n_sense = con.execute(
            "SELECT COUNT(*) FROM sense WHERE word_id=?", (wid,)).fetchone()[0]
        n_pron = con.execute(
            "SELECT COUNT(*) FROM pronunciation WHERE word_id=?", (wid,)).fetchone()[0]
        is_lemma = con.execute(
            "SELECT is_lemma FROM dict WHERE id=?", (wid,)).fetchone()[0]
        (dict_drop if (n_infl == 1 and n_sense == 0 and n_pron == 0 and not is_lemma)
         else dict_keep).append((wid, word))
    print("   其中连 `dict` 行一起删的 %s 条（孤儿：无别的变形/义项/读音、非词元）"
          % f(len(dict_drop)))
    if dict_keep:
        print("   🔴 保留 `dict` 行的 %s 条（它还有别的东西挂着）：%s"
              % (f(len(dict_keep)), dict_keep[:6]))

    n_infl_before = con.execute("SELECT COUNT(*) FROM inflection").fetchone()[0]
    n_dict_before = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    # 被跟踪的列：写前从**要删的那批行自己**算，不手写数字
    d_baseid = sum(1 for rid, _w, _b, _x in rows if con.execute(
        "SELECT base_id IS NOT NULL FROM inflection WHERE id=?", (rid,)).fetchone()[0])
    d_label = sum(1 for rid, _w, _b, _x in rows if con.execute(
        "SELECT label_zh IS NOT NULL FROM inflection WHERE id=?", (rid,)).fetchone()[0])
    base_before = con.execute(
        "SELECT COUNT(*) FROM inflection WHERE base='야멸치다'").fetchone()[0]
    con.close()

    if not rows:
        print("\n■ 没有要改的")
        return
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-prune-conj-tie-forms",
            expect={"#inflection": -len(rows),
                    "inflection.base_id": -d_baseid,
                    "inflection.label_zh": -d_label,
                    # 🔴 `dict` 的总行数在不变量里叫 **`__rows__`**，不是 `#dict`
                    #    （`#` 前缀是出版层各表的行数）。第一版写成 `#dict`，
                    #    闸不认这个键 ⇒ 报「总行数变了 -11，期望 +0」并要求回滚。
                    #    **拦对了**：未声明的变化就是未声明，哪怕我以为我声明了。
                    "__rows__": -len(dict_drop)},
            invalidates=[]) as s:
        s.executemany("DELETE FROM inflection WHERE id=?", [(r[0],) for r in rows])
        s.executemany("DELETE FROM dict WHERE id=?", [(w,) for w, _x in dict_drop])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    checks = [
        ("inflection 行数", q("SELECT COUNT(*) FROM inflection"),
         n_infl_before - len(rows)),
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), n_dict_before - len(dict_drop)),
        ("平局生成形一条不剩",
         sum(1 for w in {x[3] for x in rows}
             if q("SELECT COUNT(*) FROM dict WHERE word=?", w)), 0),
        # 🔴 反向：`야멸치다` 本身与它**别的**活用形一条没少。
        #    期望值写前抓（`base_before`）—— 第一版我在这里写了一条
        #    「拿自己和自己比」的检查，那是**永真的假检查**，比没有更糟。
        ("`야멸치다` 还在 dict 里", q("SELECT COUNT(*) FROM dict WHERE word='야멸치다'"), 1),
        ("`야멸치다` 其余活用形没被带走",
         q("SELECT COUNT(*) FROM inflection WHERE base='야멸치다'"),
         base_before - sum(1 for _r, _w, b, _x in rows if b == "야멸치다")),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-30s %9s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
