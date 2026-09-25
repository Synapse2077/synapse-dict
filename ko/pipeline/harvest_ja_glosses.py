#!/usr/bin/env python3
"""收日文版的释义 —— **K10 里唯一还能榨出来的那一点**。ko，2026-09-25。

═══ 为什么现在才收，以及为什么这是翻一条旧决定 ═══
建库时 `sense_gloss` 的表注释写着：

    🔴 日文版那 29,671 条**日语**释义不进这儿，它只用来给 IPA 交叉背书

那条决定的依据是 `[[gloss-three-languages]]`：**释义只保留三语（中＋英＋本语言）**。
2026-09-25 用户在页面上看见 K10（`사가`：「有很多没有释义」），当天把账量到底：

    词元 267,645，没有释义的 208,159（77.8%）
      └ 五份源里**任何一版**有真释义的 **743（0.36%）**
          └ 其中 **686 是日文版的日语释义**（en 83 ／ ko 43 ／ zh 两片共 17，互有重叠）

⇒ **三语方针挡住的，正好是那 0.36% 的绝大部分**。用户当天拍板收。

🔴 **收法不违反三语方针**：日语原文只进**证据层** `sense_src`（它本来就是"全收、不做裁决"），
   出版层 `sense_gloss` 里落的是**中文译文**。读者看到的仍然只有三语。
   ⚠️ `[[dont-say-source-lacks-what-we-skipped]]`：译文的 `src` 要写明它**来自日文版**，
     别让它看起来和源头白送的中文释义一样。

═══ 🔴🔴 规模：我先报了一个**错的数**（2,821），真值是 710 ═══
第一版的「是不是真释义」判据漏了 `rstrip("。")`：

    all(是汉字 or 在 ' ，,、/（）()' 里 for c in g)

`温柔。` 结尾那个 `。` 既不是汉字也不在白名单里 ⇒ `all(...)` 为假
⇒ **一整族「只是汉字词」被当成了真释义**，数从 710 虚报成 2,821，
把「收完能涨多少」从 ＋0.28 点说成了 ＋1.05 点。
⚠️ 同一个形状本项目已经犯过很多次（`[[criteria-narrower-than-you-think]]`），
   这次特别值得记：**判据的漏洞在一个标点上**，而它把量级放大了 4 倍。

═══ 实测规模（修正后，分三堆）═══
    A 真·日语释义（不是光一串汉字）              **882 条 / 685 个词**  ← 收
    B 只是汉字，但我们对这个词一个汉字都没有         **45 条 /  25 个词**  ← 收
    C 只是汉字，而我们已有汉字表记              **3,344 条**            ← **有意不收**

🔴 **C 为什么不收**（这是本步最重要的判据）：
    온유  ja=`温柔`   我们已有 `溫柔`      ← **日本新字体**，同一个词
    거점  ja=`拠点`   我们已有 `據點`      ← 同上
    가근  ja=`仮根`   我们已有 `假根`      ← 同上
  译过来落进「释义」= **把页面上早就印着的汉字表记再说一遍**，
  P6 覆盖率会涨而**读者一个字的新信息都没拿到** ——
  `[[proxy-metric-gets-optimized]]` 的正脸：**判据要写目的，不要写目的的可观测代理**。
  ⚠️ 更糟的是它们是**日本新字体**：`拠` 不是韩语汉字（韩语用 `據`），
     当成「另一种汉字写法」收进关系层就是错的。

⚠️ C 里确实混着少量真东西（`오살` ja=`鏖殺` 是我们没有的第三个汉字表记、
   `춘궁` ja=`皇太子` 是日语给的释义）—— 那是**另一条判据**（"这是不是一个新的
   韩语汉字表记"），`[[one-problem-at-a-time]]`：本步不办，落账 **K24**。

═══ 出版层怎么接（🔴 这一步最容易出错，写清楚判据）═══
这 710 个词形在库里长这样：
    · 绝大多数：1 个 entry ＋ **1 条 hidden 的空壳 sense**（K10 搬走元描述之后剩的）
    · 少数（如 `를`）：**一条 sense 都没有**（K13 补收进来的词头）

⇒ ① ja 的第 1 条义项**复用那条空壳**（取消 hidden），第 2 条起**新建 sense**；
  ② 本来就没有 sense 的，全部新建。
🔴 **不动 `entry.pos`**：ja 版给了词性（noun/verb…），但那一列已经有写入方
  （`build_entry_layer`）。**一个字段一个写入方** —— 想用 ja 的词性是另一件事，
  在这儿顺手写就是第二个写入方（ja 的 `inflection` 正是这么栽的）。

跑（在仓库根）：
    python3 -u ko/pipeline/harvest_ja_glosses.py
    python3 -u ko/pipeline/harvest_ja_glosses.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import json
import sqlite3

import dbtool
import paths
from fix_meta_gloss import META          # 🔴 import 收割器自己的判据，不重写

f = lambda n: format(n, ",")

SRC = "ja-edition"


def is_han(c):
    return "一" <= c <= "鿿"


def real_gloss(g):
    """这条 gloss 是不是**释义**（而不是元描述 / 光一串汉字）。

    ⚠️ 判据与 `fix_meta_gloss.META` 共用，**不在这儿另写一份**。
    🔴 「整条就是汉字串」这一条是额外加的：日文版有大量 `温柔。` `血肉。` 这种
       —— 它们**要收**（对中文读者可用），所以这里**不**拿它当排除条件，
       只用来在统计里分两族看。
    """
    g = (g or "").strip()
    return bool(g) and not META.match(g)


def only_hanja(g):
    g = (g or "").strip().rstrip("。.")
    return bool(g) and all(is_han(c) or c in " ，,、/（）()〈〉" for c in g)


def collect(nodef, known=None):
    """→ {词形: [(源义项序号, 日文原文, tags), ...]}

    `known`＝{词形: 我们已有的汉字集}。给了它就按文件头的 A/B/C 分堆，只留 A ＋ B。
    """
    out = collections.defaultdict(list)
    with gzip.open(paths.JA_EDITION, "rt", encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            w = d.get("word")
            if not w or w not in nodef:
                continue
            for si, s in enumerate(d.get("senses") or []):
                gs = [g for g in (s.get("glosses") or []) if real_gloss(g)]
                if not gs:
                    continue
                g = gs[0]
                # C 堆：只是汉字，而我们对这个词已经有汉字表记 ⇒ 不收（文件头）
                if known is not None and only_hanja(g) and known.get(w):
                    continue
                # 🔴 `src_ref` 必须唯一（`sense_src.src_ref` 上有 UNIQUE）。
                #    第一版用 `词形#sense:序号` —— **当场被那条 UNIQUE 拦下**：
                #    ja 版同一个词头有**多条记录**（`가` 有 18 条，按词性分），
                #    每条记录里 `si` 都从 0 重新数 ⇒ 撞车。
                #    ⚠️ 源头的 `sense.id` 也不能直接用：实测**有 4 个 id 重复**
                #      （`ja-상주-ko-noun-jQ9ozPXq1` 出现 7 次）。
                #    ⇒ 带上源头 id **再加一个全局流水号**，两者都留着便于回溯。
                out[w].append((s.get("id") or "sense:%d" % si, g,
                               s.get("tags") or []))
    return out


def known_hanja(con):
    """我们已经知道的汉字表记：`entry.hanja` ＋ 汉字族的关系边。"""
    k = collections.defaultdict(set)
    for w, h in con.execute(
            "SELECT d.word_norm, e.hanja FROM entry e JOIN dict d ON d.id = e.word_id"
            " WHERE e.hanja IS NOT NULL"):
        k[w].add(h)
    for w, t in con.execute(
            "SELECT d.word_norm, r.target FROM sense_relation r"
            " JOIN dict d ON d.id = r.word_id"
            " WHERE r.kind IN ('hanja_spelling','alt_hanja')"):
        k[w].add(t)
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 🔴 只给**没有任何真释义**的词元收 —— 已有释义的不许被 ja 版覆盖或加塞
    nodef = {r[0]: r[1] for r in con.execute(
        "SELECT d.word_norm, d.id FROM dict d WHERE d.is_lemma = 1"
        " AND NOT EXISTS(SELECT 1 FROM sense s JOIN sense_gloss g ON g.sense_id = s.id"
        "                WHERE s.word_id = d.id AND s.hidden = 0)")}
    print("■ 没有真释义的词元 %s（本步只碰这些）" % f(len(nodef)))

    known = known_hanja(con)
    got_all = collect(set(nodef))                 # 不分堆，用来报 C 有多大
    got = collect(set(nodef), known)              # 只留 A ＋ B
    n_sense = sum(len(v) for v in got.values())
    n_all = sum(len(v) for v in got_all.values())
    n_b = sum(1 for w, v in got.items() for _si, g, _t in v if only_hanja(g))
    print("   ja 版有释义的义项共 %s，按文件头分堆后**要收** %s"
          % (f(n_all), f(n_sense)))
    print("     · A 真·日语释义            %s 条 / %s 个词"
          % (f(n_sense - n_b), f(len({w for w, v in got.items()
                                      if any(not only_hanja(g) for _s, g, _t in v)}))))
    print("     · B 只是汉字但我们没有汉字   %s 条" % f(n_b))
    print("     · C 只是汉字而我们已有汉字   %s 条 —— **有意不收**（多为日本新字体："
          "`拠点` vs 韩语的 `據點`）" % f(n_all - n_sense))

    # 现有出版层结构
    shells = collections.defaultdict(list)     # word_id → [sense_id]（hidden 空壳）
    for sid, wid in con.execute(
            "SELECT s.id, s.word_id FROM sense s WHERE s.hidden = 1"
            " AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id = s.id)"):
        shells[wid].append(sid)
    maxrank = dict(con.execute(
        "SELECT word_id, MAX(rank) FROM sense GROUP BY word_id"))
    entry_of = dict(con.execute(
        "SELECT word_id, MIN(id) FROM entry GROUP BY word_id"))
    maxsrc = con.execute("SELECT COALESCE(MAX(id),0) FROM sense_src").fetchone()[0]

    reuse = new = 0
    seq = 0
    plan = []            # (word, word_id, 用哪条 sense（None＝新建）, rank, 日文原文, 源引用)
    for w, items in sorted(got.items()):
        wid = nodef[w]
        avail = list(shells.get(wid, []))
        rank = maxrank.get(wid, 0)
        for si, g, _tags in items:
            seq += 1
            ref = "%s:%s#%d" % (SRC, si, seq)      # si 这里是源头的 sense id
            if avail:
                plan.append((w, wid, avail.pop(0), None, g, ref))
                reuse += 1
            else:
                rank += 1
                plan.append((w, wid, None, rank, g, ref))
                new += 1
    print("\n■ 出版层接法：复用空壳 %s 条，新建 %s 条" % (f(reuse), f(new)))
    n_noentry = sum(1 for _w, wid, sid, _r, _g, _ref in plan
                    if sid is None and wid not in entry_of)
    print("   其中连 entry 都没有的 %s（应为 0）%s"
          % (f(n_noentry), "✅" if n_noentry == 0 else "🔴"))
    if n_noentry:
        raise SystemExit("🔴 有词形没有 entry 行 —— 先弄清楚再接")

    print("\n■ 样本 10")
    for w, _wid, sid, rank, g, _ref in plan[:10]:
        print("   %-10s %-28s %s" % (w, g[:28],
                                     "复用空壳 #%d" % sid if sid else "新建 rank=%d" % rank))

    n_sense_before = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    n_hidden_before = con.execute(
        "SELECT COUNT(*) FROM sense WHERE hidden=1").fetchone()[0]
    n_src_before = con.execute("SELECT COUNT(*) FROM sense_src").fetchone()[0]
    con.close()

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        print("⚠️ 本步**只收日语原文进证据层 ＋ 备好出版层的位置**，一分钱不花。")
        print("   中文译文是下一步（`translate_ja_glosses.py`），那一步要挑半价窗口。")
        return

    with dbtool.session(
            "ko-harvest-ja-glosses",
            expect={
                "#sense": new,
                "#sense_src": len(plan),
                "sense_src.sense_id": len(plan),
                "__rows__": 0,              # 不插新词形
            },
            invalidates=[
                "义项层行数变了：`test_plan_ledger` 的 P6 中文覆盖率分母会涨 %d，"
                "而分子要等译文落库才涨 —— **中间状态下 P6 会比现在更红，这是对的**" % new,
                "空壳义项数变了：K10 的「200,207 条空壳」要重数",
            ]) as s:
        # ① 新建 sense
        for _w, wid, sid, rank, _g, _ref in plan:
            if sid is None:
                s.execute(
                    "INSERT INTO sense(word_id, entry_id, rank, pos, hidden)"
                    " VALUES(?,?,?,?,0)", (wid, entry_of[wid], rank, None))
        # ② 复用的空壳取消 hidden
        s.executemany("UPDATE sense SET hidden=0 WHERE id=?",
                      [(sid,) for _w, _wid, sid, _r, _g, _ref in plan if sid])
        # ③ 日语原文进**证据层**（出版层只放中文译文，见文件头）
        s.executemany(
            "INSERT INTO sense_src(word_id, sense_id, src, src_ref, lang, text)"
            " SELECT ?, COALESCE(?, (SELECT id FROM sense WHERE word_id=? AND rank=?)),"
            "        ?, ?, 'ja', ?",
            [(wid, sid, wid, rank, SRC, ref, g)
             for _w, wid, sid, rank, g, ref in plan])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("sense 行数", q("SELECT COUNT(*) FROM sense"), n_sense_before + new),
        ("hidden 空壳少了", n_hidden_before - q(
            "SELECT COUNT(*) FROM sense WHERE hidden=1"), reuse),
        ("sense_src 行数", q("SELECT COUNT(*) FROM sense_src"),
         n_src_before + len(plan)),
        ("新收的证据行都认领到了出版义项",
         q("SELECT COUNT(*) FROM sense_src WHERE src='%s' AND lang='ja'"
           " AND sense_id IS NULL" % SRC), 0),
        # 🔴 反向：日语**一个字都没进出版层**（三语方针）
        ("出版层里有日语释义的（应为 0）",
         q("SELECT COUNT(*) FROM sense_gloss WHERE lang='ja'"), 0),
        # 🔴 反向：没有碰已有释义的词
        ("新收的义项挂在「本来就有释义」的词上（应为 0）",
         q("SELECT COUNT(*) FROM sense_src ss WHERE ss.src='%s' AND ss.lang='ja'"
           " AND EXISTS(SELECT 1 FROM sense s2 JOIN sense_gloss g ON g.sense_id=s2.id"
           "            WHERE s2.word_id=ss.word_id AND s2.hidden=0"
           "              AND s2.id<>ss.sense_id)" % SRC), 0),
    ]
    ok = True
    for name, got_, want in checks:
        good = got_ == want
        ok &= good
        print("   %s %-40s %8s（期望 %s）"
              % ("✅" if good else "🔴", name, f(got_), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")
    print("\n⚠️ 下一步 `translate_ja_glosses.py`：把这 %s 条日语原文译成中文落进出版层。"
          % f(len(plan)))
    print("   **在那之前，这批义项在页面上仍然没有释义** —— P6 会比现在更红，这是对的。")


if __name__ == "__main__":
    main()
