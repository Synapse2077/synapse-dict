#!/usr/bin/env python3
"""补上「一条 entry 多个汉字表记」里被推迟的那些异体字。ko，2026-09-26（K2）。

═══ 账上原话与实测的差别 ═══
K2 记的是「其余异体进 `sense_relation.kind='alt_hanja'`」，清单 100 条。
逐条回源头（`paths.KK` 的 `forms[tags=hanja]`）读完，**那 100 条不是一类东西**，
账上那句话只对 58 条成立：

    ✅ 无 head_nr、非汉字部分一致   **58 条 ⇒ 69 条边**   真异体字（奇跡/奇迹/奇蹟、映畫館/映畵館）
    ❌ ② 含阿拉伯数字              40 条   不是汉字
    ❌ ③ 非汉字部分不同             1 条    `미국 사람` → `米國사람`
    ❌ ① head_nr 不同              1 条    `봉` → 封/鳳 是**两个词**

🔴 **③ 这条判据我第一版写宽了，误伤真异体字。** 第一版写成「含谚文就排除」，
   于是 `쇠퇴하다` 的 `衰退하다` / `衰頹하다`（退/頹 是真异体）被排掉了 ——
   **两边都带着 `하다` 后缀**，谚文是两边共有的，不是差别所在。
   ⇒ 改成比「去掉汉字之后剩下的部分是否相同」，收回 3 条边
   （`쇠퇴하다`/`야비하다` 那两组）。`[[criteria-narrower-than-you-think]]`。

═══ 🔴 判据来自源头的结构，不是我的眼力 ═══
**`head_nr`** 是 kaikki 自己用来区分「同一页上的不同词头」的字段：

    봉 (etym 4)  forms: [{"form":"封","head_nr":1}, {"form":"鳳","head_nr":2}]
                 senses: ['A small paper bag or envelope', 'An East Asian phoenix', …]

⇒ 封（信封）与 鳳（凤凰）是**两个不同的词**，只是都读 봉。
  把它们收成 `alt_hanja` ＝ **断言「封和鳳是同一个词的两种写法」，那是错的**。
  而 `기적`(etym 1) 的 奇跡/奇迹/奇蹟 **没有 head_nr** ⇒ 同一个词的三种写法 ✅
  `[[dict-framework-doc]]`：错比缺更伤权威。

═══ ❌ 40 条数字写法有意不收 ═══
全是「阿拉伯数字 vs 汉数字」的同一个说法：
    시월 十月/**10月**　열한시 열한時/**11時**　70년대 七十年代/**70年代**
    3차원 三次元/**3次元**　10종경기 十種競技/**10種競技**
它们进 `alt_hanja` 会在页面的**「汉字表记」区印出 `11時`** ——
读者看见的是一个不是汉字的东西摆在汉字栏里，那是**用一条真数据造出一个假观感**。
⚠️ 注意有几条连 `kept` 本身都是混写（`열한時` ＝ 谚文 열한 ＋ 汉字 時），
   也就是 `entry.hanja` 这一列里**已经**躺着混写形 —— 那是另一笔账（K28）。

跑（在仓库根）：
    python3 -u ko/pipeline/backfill_alt_hanja.py
    python3 -u ko/pipeline/backfill_alt_hanja.py --apply
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
import resolve_relation_targets as R   # 落点解析判据：import，不重写

f = lambda n: format(n, ",")

SRC = "en-edition"        # 清单来自英文版切片的 forms
DIGIT = re.compile(r"\d")
HANGUL = re.compile(r"[가-힣ᄀ-ᇿ]")


def ledger():
    """账本清单 → [(word, pos_raw, etym_no, seq, kept, [alts])]"""
    out = []
    with (paths.WORK / "entry_multi_hanja.tsv").open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i == 0:
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) >= 6:
                out.append((c[0], c[1], c[2], c[3], c[4], [x for x in c[5].split("|") if x]))
    return out


def source_headnr():
    """(word, pos, etym_no) → {form: head_nr}，只取 tags 含 hanja 的 forms。"""
    info = {}
    with paths.KK.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            hf = [x for x in (d.get("forms") or []) if "hanja" in (x.get("tags") or [])]
            if len(hf) < 2:
                continue
            key = (d.get("word"), d.get("pos"), str(d.get("etymology_number") or 0))
            info[key] = {x.get("form"): x.get("head_nr") for x in hf}
    return info


def classify(kept, alts, headnr):
    """→ ('收', None) 或 ('不收', 原因)。判据顺序：先问源头结构，再问字形。"""
    if headnr and len({v for v in headnr.values() if v is not None}) > 1:
        return "不收", "① head_nr 不同 ⇒ 是不同的词，不是异体字"
    if DIGIT.search(kept) or any(DIGIT.search(a) for a in alts):
        return "不收", "② 阿拉伯数字写法，不是汉字"
    # 🔴 **第一版写成「含谚文就排除」，把真异体字误伤了。**
    #    `쇠퇴하다` 的 `衰退하다` / `衰頹하다` —— 退/頹 是真异体字，
    #    而**两边都带着 `하다` 后缀**，只看「含不含谚文」就把它排掉了。
    #    真正该排除的是 `美國` → `米國사람`：**两边的非汉字部分不一样**。
    #    ⇒ 判据比的是「去掉汉字之后剩下的那部分是否相同」，不是「有没有谚文」。
    #    `[[criteria-narrower-than-you-think]]`：收窄之后才只逮到真的。
    def residue(x):
        return "".join(ch for ch in x if not dbtool.has_han_char(ch))

    if any(residue(a) != residue(kept) for a in alts):
        return "不收", "③ 非汉字部分不同（`美國` → `米國사람`）"
    if len({len(x) for x in [kept] + alts}) > 1:
        return "不收", "④ 长度不同 ⇒ 不是同一写法的异体"
    return "收", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    led = ledger()
    hn = source_headnr()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    have_norm = {w for w, in con.execute("SELECT word_norm FROM dict")}
    existing = {(w, t) for w, t in con.execute(
        "SELECT word_id, target FROM sense_relation WHERE kind='alt_hanja'")}
    n_rel_before = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    n_alt_before = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE kind='alt_hanja'").fetchone()[0]
    n_norm_before = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL").fetchone()[0]

    take, skip = [], collections.defaultdict(list)
    no_src = 0
    for word, praw, eno, seq, kept, alts in led:
        key = (word, praw, eno)
        info = hn.get(key) or hn.get((word, praw, "0"))
        if info is None:
            no_src += 1
        verdict, why = classify(kept, alts, info)
        if verdict == "不收":
            skip[why].append((word, kept, alts))
            continue
        wid = indict.get(word)
        if wid is None:
            skip["⑤ 词形不在 dict"].append((word, kept, alts))
            continue
        for alt in alts:
            if (wid, alt) in existing:
                skip["⑥ 库里已有"].append((word, kept, [alt]))
                continue
            tn, _how = R.resolve(alt, have_norm)
            take.append((wid, alt, tn,
                         "kk-ko:%s:%s:%s:%s#alt_hanja:%s" % (word, praw, eno, seq, alt)))

    print("■ 账本 %s 条；回源头取到 head_nr 的 %s 条（对不上 %d）"
          % (f(len(led)), f(len(led) - no_src), no_src))
    print("   ✅ 要收的 `alt_hanja` 边 %s 条" % f(len(take)))
    for why, xs in sorted(skip.items()):
        print("   ❌ %-44s %3d 条" % (why, len(xs)))
        for w, k, al in xs[:3]:
            print("        %-10s %-8s → %s" % (w, k, "|".join(al)))
    print("\n■ 要收的样本")
    id2w = {i: w for w, i in indict.items()}
    for wid, alt, tn, _ref in take[:10]:
        print("   %-10s --alt_hanja--> %-8s target_norm=%s"
              % (id2w.get(wid), alt, tn or "—"))
    print("\n■ 其中 target_norm 解析得出的 %s 条（另 %s 条的异体字本身不是词条，如实留空）"
          % (f(sum(1 for _w, _a, tn, _r in take if tn)),
             f(sum(1 for _w, _a, tn, _r in take if not tn))))

    # 🔴 src_ref 必须唯一（它是这条边的身份）
    refs = collections.Counter(r for _w, _a, _t, r in take)
    dup = {k: v for k, v in refs.items() if v > 1}
    print("   %s src_ref 唯一性：%s"
          % ("✅" if not dup else "🔴", "全唯一" if not dup else list(dup)[:3]))
    if dup:
        raise SystemExit("🔴 src_ref 重复，先弄清楚")
    con.close()

    if not take:
        print("\n■ 没有要收的")
        return
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    n_norm_new = sum(1 for _w, _a, tn, _r in take if tn)
    with dbtool.session(
            "ko-backfill-alt-hanja",
            expect={"#sense_relation": len(take),
                    "sense_relation.target": len(take),
                    "sense_relation.target_norm": n_norm_new},
            invalidates=[]) as s:
        s.executemany(
            "INSERT INTO sense_relation"
            " (word_id, sense_id, kind, target, tags, hidden, src, src_ref, target_norm)"
            " VALUES (?, NULL, 'alt_hanja', ?, NULL, 0, ?, ?, ?)",
            [(wid, alt, SRC, ref, tn) for wid, alt, tn, ref in take])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("关系边行数", q("SELECT COUNT(*) FROM sense_relation"),
         n_rel_before + len(take)),
        ("alt_hanja 行数", q("SELECT COUNT(*) FROM sense_relation WHERE kind='alt_hanja'"),
         n_alt_before + len(take)),
        ("target_norm 非空", q("SELECT COUNT(*) FROM sense_relation"
                              " WHERE target_norm IS NOT NULL"),
         n_norm_before + n_norm_new),
        ("`기적` 的异体字收到了",
         q("SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id"
           " WHERE d.word='기적' AND r.kind='alt_hanja' AND r.target IN ('奇迹','奇蹟')"), 2),
        # 🔴 反向：三类有意不收的，一条都不许溜进来
        ("`봉` 没有被收成异体字（封/鳳 是两个词）",
         q("SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id"
           " WHERE d.word='봉' AND r.kind='alt_hanja' AND r.target='鳳'"), 0),
        ("数字写法没有溜进来",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind='alt_hanja'"
           " AND target GLOB '*[0-9]*'"), 0),
        # 🔴 这一条原来写「含谚文的 = 0」，而我**放宽判据之后**有意收了 3 条
        #    （`衰頹하다`/`野鄙하다`/`燿燿하다`，谚文后缀两边共有）⇒ 期望值跟着改，
        #    并且**钉成常量**：多了少了都该有人看。
        #    改了判据不改检查 —— 今天第三次犯，写在这儿。
        ("含谚文后缀的异体字恰好 3 条（有意收的）",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind='alt_hanja'"
           " AND target GLOB '*[가-힣]*'"), 3),
        # 🔴 `src_ref` 唯一性**只审这一轮插的**。原来审整张表，报出 9 组重复 ——
        #    那 9 组是**既有的**（`#ptr:0`：一个指针义项对多个目标共用一个 ref），
        #    与本次写入无关。**闸不该拿别人的旧账判我这一次的写入**（已记 K29）。
        ("本轮插入的 src_ref 全唯一",
         q("SELECT COUNT(*) FROM (SELECT src_ref FROM sense_relation"
           " WHERE src_ref LIKE '%#alt_hanja:%' GROUP BY src_ref HAVING COUNT(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-40s %8s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
