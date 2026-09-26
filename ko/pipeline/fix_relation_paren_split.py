#!/usr/bin/env python3
"""关系层：**逗号切分切断了括号注** ⇒ 道名变成假目标、地区信息丢了。ko，2026-09-26（K19）。

═══ 怎么发现的 ═══
查 K19（账上写的是「`dialectal` 那 75 条的 `kind` 判错了」）时回源头读，
发现**账上的诊断是错的**：75 条里 67 条（89%）的 `kind` 是**对的**，坏的是 `target`。

ko 维基词典把方言信息塞在 `examples[]` 的标签行里（与 K11 构词公式、K15 谚语成分同族）：

    무당  "지역어(방언) : 굿재이(강원, 경남, 전남, 충북), 무덩(경기, 황해), 암무이(경남), …"
    조선  "사투리: 매롱이, 매리이, 매아미, 미암, 억시기, 자리, 재열"

⭐ **`조선` 那批是对的**：它那条义项是「'매미'의 북한말」（蝉的北韩语），
  所以 매아미/재열 确实是它的方言形。**我一开始怀疑它错了，回源头才知道没错** ——
  `[[measure-landing-not-source]]` 的反面：不回源头就会把对的判成错的。

═══ 根因：一行代码里两步的顺序反了 ═══
`harvest_relations_from_examples.py`：

    SPLIT = re.compile(r"[，,、；;/]|\\s-\\s|｜")      # ① 先按逗号切
    t = re.sub(r"[（(\\[【].*?[)\\]）】]", "", t)       # ② 再去括号注

② 只能去掉**完整**的括号对，而 ① 已经把括号切断了：

    "굿재이(강원, 경남, 전남, 충북)"  ──①──▶  "굿재이(강원" │ " 경남" │ " 전남" │ " 충북)"
                                   ──②──▶   굿재이 ✅   │  경남 ❌ │  전남 ❌ │  충북) ❌

⇒ **道名成了假的方言词，而「这个方言形用在哪些道」这个真信息被丢掉了。**

═══ 🔴 判据不写成「目标是不是道名」═══
那会误伤真词：`서울` / `북한` / `제주` / `평양` 本身都是词条，
`related → 서울` 完全可能是正常的关系边（全库实测 64 条「目标是地区名」里就混着这些）。
⇒ 判据写成**机制**：拿同一份源文行，用**认括号的切分器**重跑一遍，
  只动「旧切分器造出来、而新切分器不会造」的那些行。
  这条判据可证伪、可复算，且不依赖任何地名清单
  （`[[criteria-from-meaning-not-form]]`：判据不许用形式代理）。

═══ 只做一件事：删掉确凿的垃圾。另两件有意不做 ═══
① ✅ **做**：删掉切断括号造出来的假目标（逐条对上源文裁决过，见 `KEEP`）。

② ❌ **不做：把括号里的内容补进 `tags`。** 第一版这么写了，干跑报出 908 条，
   一读就知道**那些括号里根本不是地区**：
       `편주(片舟/扁舟)`    → **汉字表记**（该进 `hanja_spelling`，不是标签）
       `부정되다(피동)`      → **语态标签**（被动/主动）
       `성두(星斗)`         → 汉字表记
   一股脑灌进 `tags` ＝ 把三种语义混成一堆，比不做更糟。⇒ 记账另办（K27）。

③ ❌ **不做：补上新切分器才看得见的那 1 条边**（`우기다 → 우격`）。
   源文是 `우격 (> 우격다짐,우격으로)` ——「派生出 우격，它再派生成 우격다짐/우격으로」。
   而 `clean()` 里那条 `>` 规则是为「`어두움 > 어둠` 旧形>新形取后者」写的，
   **同一个符号在这里是「再派生」**，两种意思。要补这条边得先定 `>` 的语义 ⇒ K27。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_relation_paren_split.py
    python3 -u ko/pipeline/fix_relation_paren_split.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import json
import re
import sqlite3

import dbtool
import paths
import harvest_relations_from_examples as H

f = lambda n: format(n, ",")

# 认括号的切分：只在**括号外**的分隔符上切。
# ⚠️ 分隔符集合与 `H.SPLIT` **一字不差**（`，,、；;/`、` - `、`｜`）——
#    这里改的是「在哪儿切」，不是「切什么」。判据借来，不重写。
_SEP = re.compile(r"[，,、；;/]|\s-\s|｜")
_OPEN, _CLOSE = "（([【", "）)]】"


def split_outside_parens(s):
    """按 `H.SPLIT` 的同一套分隔符切，但**跳过括号内部**。"""
    out, buf, depth = [], [], 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in _OPEN:
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch in _CLOSE:
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue
        if depth == 0:
            m = _SEP.match(s, i)
            if m:
                out.append("".join(buf))
                buf = []
                i = m.end()
                continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [x for x in out if x.strip()]


# 🔴 **10 条全部逐条对上源文读过**（`[[judge-output-must-be-adjudicable]]`：
#    判官产出要可裁决）。9 条是垃圾，1 条要留 —— 判据是「这个目标是不是一个真词」，
#    不是「它是不是被切坏了」：被切坏**也可能正好切出一个真词**。
KEEP = {
    # 源文 `우격 (> 우격다짐,우격으로)`：旧切分器靠 `clean()` 的 `>` 规则
    # 阴差阳错抓到了 `우격다짐` —— **词是真的，派生关系也是真的**（只是间接一层）。
    # 删掉它＝为了修解析而丢掉一条正确的边。留着，理由写在这儿。
    ("우기다", "derived", "우격다짐"): "真词、真派生关系，只是源文里是第二层派生",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows = H.load_rows()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {w: i for i, w in con.execute("SELECT id, word FROM dict")}

    # 同一份源文，两个切分器各跑一遍 —— 差集就是这个 bug 造出来的
    old_edges, new_edges, srcline = set(), set(), {}
    for _src, word, lab, payload in rows:
        if lab in H.DROP or lab not in H.M:
            continue
        kind, _tag = H.M[lab]
        wid = indict.get(word)
        if wid is None:
            continue
        for raw in H.SPLIT.split(payload):
            t = H.clean(raw)
            if t and (H.HANGUL.search(t) or H.CJK.search(t)) and t != word:
                old_edges.add((wid, kind, t))
                srcline[(wid, kind, t)] = payload
        for frag in split_outside_parens(payload):
            t = H.clean(frag)
            if t and (H.HANGUL.search(t) or H.CJK.search(t)) and t != word:
                new_edges.add((wid, kind, t))

    ghost = old_edges - new_edges       # 切断括号造出来的假目标
    gained = new_edges - old_edges      # 认括号之后才切出来的（应当是 0 或极少）
    print("■ 源文标签行 %s 条" % f(len(rows)))
    print("   旧切分器造出的边 %s ／ 认括号的新切分器 %s" % (f(len(old_edges)), f(len(new_edges))))
    print("   🔴 只有旧切分器会造的（假目标）  %s" % f(len(ghost)))
    print("   ⭐ 只有新切分器会造的（原先漏的）%s" % f(len(gained)))

    # 落到库里的是哪些
    have = {(w, k, t): (rid, tags) for rid, w, k, t, tags in con.execute(
        "SELECT id, word_id, kind, target, tags FROM sense_relation")}
    norm_of = {rid: tn for rid, tn in con.execute(
        "SELECT id, target_norm FROM sense_relation WHERE target_norm IS NOT NULL")}
    # 🔴 **真实行数要单独数。** 第一版回核拿 `len(have)` 当行数 —— 而 `have` 是按
    #    `(word_id, kind, target)` 做键的字典，**同键的多行被它去重了**
    #    （253,384 vs 真实 256,502，差 3,118）。写后回核当场报红，而**数据是对的、期望是错的**。
    #    `[[expectation-must-be-declared]]`：期望要独立声明，但别从一个**顺手的变量**里推。
    n_rows_before = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    # 回核用的基线也一样：写前抓，别手写数字（第一版 `조선` 手写 13，真值一直是 12）
    base = {name: con.execute(sql).fetchone()[0] for name, sql in (
        ("조선-dialectal",
         "SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id"
         " WHERE d.word='조선' AND r.kind='dialectal'"),
        ("무당-dialectal",
         "SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id"
         " WHERE d.word='무당' AND r.kind='dialectal'"),
    )}
    id2w0 = {i: w for w, i in indict.items()}
    drop, kept = [], []
    for g in ghost:
        if g not in have:
            continue
        key = (id2w0.get(g[0]), g[1], g[2])
        (kept if key in KEEP else drop).append((have[g][0], g))
    # 🔴 裁决清单必须**全部命中**：源文变了它就该当场响，而不是静默少留一条
    if len(kept) != len(KEEP):
        raise SystemExit("🔴 `KEEP` 里有 %d 条，实际只命中 %d 条 —— 源文变了，重新裁决"
                         % (len(KEEP), len(kept)))
    print("\n■ 这些假目标在库里实际存在 %s 条" % f(len(drop)))
    byk = collections.Counter(g[1] for _rid, g in drop)
    for k, n in byk.most_common():
        print("   kind=%-16s %d 条" % (k, n))
    id2w = {i: w for w, i in indict.items()}
    print("\n■ 样本（词条 → 假目标）")
    for _rid, (wid, kind, t) in drop[:14]:
        print("   %-12s --%-12s--> %s" % (id2w.get(wid, "?"), kind, t))

    print("\n■ 有意保留的（真词、真关系，只是被解析 bug 顺手带出来的）")
    for _rid, g in kept:
        print("   ✅ %-10s --%-11s--> %-12s ← %s"
              % (id2w.get(g[0]), g[1], g[2], KEEP[(id2w.get(g[0]), g[1], g[2])]))
    upd = []   # 这一轮不动 `tags`，见文件头 ②

    # 🔴 反向：删完有没有词条因此**一条关系都不剩**
    left = collections.Counter()
    dropped_ids = {rid for rid, _ in drop}
    for rid, wid in con.execute("SELECT id, word_id FROM sense_relation"):
        if rid not in dropped_ids:
            left[wid] += 1
    orphan = sorted({g[0] for _rid, g in drop} - set(left))
    print("\n■ 删完一条关系都不剩的词条：%d %s"
          % (len(orphan), [id2w.get(x) for x in orphan[:8]]))
    con.close()

    if not drop:
        print("\n■ 没有要改的")
        return
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    keep_keys = {g for _rid, g in kept}
    # 🔴 **删行不止改行数**：`target` / `target_norm` 是被跟踪的列，
    #    删掉 9 行就会让它们的非空计数各自变少。第一版只声明了 `#sense_relation`，
    #    写库闸当场拦下「未声明的列 `target` 变了 -9 / `target_norm` 变了 -2」——
    #    **这正是它该拦的**（`[[dbtool-and-golden-tests]]`）。
    #    期望值从**要删的那批行自己**算出来，不手写数字。
    d_target = sum(1 for rid, _g in drop
                   if next(k for k, v in have.items() if v[0] == rid)[2])
    d_norm = sum(1 for rid, _g in drop if norm_of.get(rid))
    with dbtool.session(
            "ko-fix-relation-paren-split",
            expect={"#sense_relation": -len(drop),
                    "sense_relation.target": -d_target,
                    "sense_relation.target_norm": -d_norm},
            invalidates=[]) as s:
        s.executemany("DELETE FROM sense_relation WHERE id=?",
                      [(rid,) for rid, _ in drop])
        # 这一轮不动 `tags`（文件头 ②）

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    now = {(w, k, t) for w, k, t in con.execute(
        "SELECT word_id, kind, target FROM sense_relation")}
    checks = [
        ("关系边行数", q("SELECT COUNT(*) FROM sense_relation"),
         n_rows_before - len(drop)),
        # 🔴 `ghost` 里**含着有意保留的那条** —— 检查必须把 `KEEP` 排除掉，
        #    否则「还剩 1」是检查自己造的假红（第一版就是这么报的）。
        ("假目标一条不剩（不含有意保留的）", len((ghost - keep_keys) & now), 0),
        # 🔴 反向：认括号的新切分器该留的，一条都没少
        ("新切分器认定的边仍在库里", len((new_edges & set(have)) - now), 0),
        # 🔴 反向：裁决为「留」的那条一定还在
        ("`우기다 → 우격다짐` 还在（有意保留）",
         q("SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id"
           " WHERE d.word='우기다' AND r.target='우격다짐'"), 1),
        # 🔴 反向：真方言词一条没少（只删道名，不删词）
        ("`무당` 的方言边＝原有减去删掉的 5 条道名",
         q("SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id"
           " WHERE d.word='무당' AND r.kind='dialectal'"),
         base["무당-dialectal"] - sum(1 for _r, g in drop
                                     if id2w0.get(g[0]) == "무당")),
        # 🔴 `조선` 那批是**对的**，一条都不许动（它的义项是「매미의 북한말」）
        # 🔴 `조선` 那批是**对的**（它那条义项是「매미의 북한말」），一条都不许动。
        #    期望值**写前从库里抓**：第一版手写 13，而真值一直是 12 —— 数据没错，我数错了。
        ("`조선` 的方言边一条没少",
         q("SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id"
           " WHERE d.word='조선' AND r.kind='dialectal'"), base["조선-dialectal"]),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-32s %7s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
