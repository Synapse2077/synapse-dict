#!/usr/bin/env python3
"""阶段 7 — 回归闸首次跑出来的真缺陷，一次修完。2026-08-26。

闸（`tests/test_no_regression.py`）第一次跑出 16 条红。逐条核完：
**7 条是我的判据宽了**（A5 拿 `BARE_BAD` 用错地方报 6,140、C1「没有汉字」误圈
`YouTube→YouTube` 报 103、C3 把正当的「（法国）」当泄漏报 105、E2 把构词式
`bleu + -s → bleus` 当没翻报 344…）—— 那些改判据，不改数据。
**这个脚本只修剩下的真缺陷。**

    A1  音标里残留没配对的定界符 \\ / [ ]        103 条（16 条是主读音）
    A3  拉丁小写 g 冒充 IPA ɡ (U+0261)      4,435 条（2,539 条是主读音）
    A4  键盘撇号 ' 冒充重音符 ˈ                213 条（20 条是主读音）
    A5  🔴 X-SAMPA 冒充 IPA                150 条 —— `absOlysjO~` = `absɔlysjɔ̃`
    B4  出版层释义只剩 … / . / ?              14 条（这些义项**一个中文都没有**）
    B6  维基链接标记残渣 [[ ]]                18 条（**其中 2 条不能碰**，见下）
    D2  变形表 base 撇号未归一                16 条

⚠️ **C2 的 2 条是假红，不在这里修**：`sic` 和 `en français dans le texte` 的中文
   **就是**「原文如此」—— 我的判据逮到了词头自己的含义。已在闸里写成基线。

═══ 🔴 B6 为什么不用正则 ═══
18 条里**有 2 条的方括号是正当内容**：
    érasure          定义在讲方括号这个符号本身，`[[abc]]` 是它举的例子
    rouge de méthyle `2-[[4-…)phenyl]diazenyl]benzoique` 是**化学命名法**
盲扫一遍会把这两条改坏。18 条的规模，逐条判比写正则可靠
（`[[criteria-from-meaning-not-form]]`：判据要按含义，不按形式）。

用法（在 fr/ 目录下）：
    python3 -u fixes/fix_gate_reds.py           # 只报数 + 打样，不写库
    python3 -u fixes/fix_gate_reds.py --apply   # 落库
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402
from intake_fr_words import norm_apos           # noqa: E402
import strip_editorial_residue as _res          # noqa: E402

f = lambda n: format(n, ",")

# A5：IPA 里不该出现大写拉丁字母。**与闸里 `_XSAMPA` 同一份判据**
XSAMPA = re.compile(r"[A-Z«»]|\s{2}")
# A1：没配对的定界符。音标是**裸存**的（`[[ipa-bare-storage-convention]]`），
#     所以 \ / [ ] 一个都不该有。
DELIM = "\\/[]"

# ── B6：逐条判定表 ────────────────────────────────────────────────────
#   key = 词形；值 = ("keep", 理由) 或 ("sub", 旧串, 新串) 或 ("hide", 理由)
B6_PLAN = {
    "érasure": ("keep", "定义在讲方括号符号本身，[[abc]] 是它举的例子"),
    "rouge de méthyle": ("keep", "2-[[4-…)phenyl]diazenyl]benzoique 是化学命名法"),
    "mycoplasmatale": ("hide", "内容是 `Synonyme de [[]].` —— 空链接，没有内容"),
    # 🔴 这条通用规则救不了：管道链接的**显示侧本身就是 `[…]`**（含方括号），
    #    而管道正则的显示侧不允许含 [ ]。不加这条，维基路径会留在释义里
    #    （`…crochets : Titres_non_pris_en_charge/Trois_points_entre_crochets|[…]…`）。
    #    ⚠️ 是**逐条打全 15 条肉眼过**时看见的，闸⑤（只删不增）对它是绿的。
    "crochet": ("sub", "[[Titres_non_pris_en_charge/Trois_points_entre_crochets|[…]]]",
                "[…]"),
}
# 其余按三条确定性规则清理（都只动标记，不动文字）
B6_PIPE = re.compile(r"\[+\(?([^\[\]|]*)\|([^\[\]|]*)\]+")   # [[X|Y]] / [X|Y]] / [(X|Y]] → Y
B6_MARK = re.compile(r"\[\[|\]\]|\{\{|\}\}")                  # 落单的 [[ ]] {{ }}


def unbalanced(t):
    """去掉**没有配对**的单个 [ 或 ]，配对的原样留着。

    🔴 加这一步是因为第一版只清双写标记，`[Ethnie]]` 清成了 `[Ethnie`
       —— 打样时一眼看见的，闸⑤查不出来（它只管字母有没有变）。
    """
    keep, stack = [True] * len(t), []
    for i, ch in enumerate(t):
        if ch == "[":
            stack.append(i)
        elif ch == "]":
            if stack:
                stack.pop()
            else:
                keep[i] = False           # 没有开头的 ]
    for i in stack:
        keep[i] = False                   # 没有结尾的 [
    return "".join(c for c, k in zip(t, keep) if k)


def b6_clean(t):
    t = B6_PIPE.sub(lambda m: m.group(2), t)
    t = B6_MARK.sub("", t)
    t = unbalanced(t)
    return " ".join(t.split())


# ══════════════════════════════════════════════════════════════════════
def plan(con):
    """→ (音标改动, 释义改动, 要隐的义项, 变形表改动)。**只算，不写。**"""
    ipa_fix, gl_fix, hide, infl_fix = [], [], [], []

    # ── A1/A3/A4/A5：音标 ────────────────────────────────────────────
    #
    # 🔴 归一**必然**产生重复：`pɛ̃.gwɛ̃` 与 `pɛ̃.ɡwɛ̃` 本来就是同一个音的两种写法，
    #    `g`→`ɡ` 之后它们撞上 `UNIQUE(word_id, ipa, notation)`。
    #    第一版没想到这一层，落库当场 IntegrityError（dbtool 已干净回滚）。
    #    ⇒ 必须在**同一步**里去重，而且**主读音要转移**，否则那个词形就没主读音了（破 F4）。
    rows = list(con.execute(
        "SELECT p.id, p.word_id, d.word, p.ipa, p.notation, p.is_primary FROM pronunciation p "
        "JOIN dict d ON d.id=p.word_id"))
    final = {}          # pid -> (wid, word, old, new, notation, prim)
    for pid, wid, word, ipa, nota, prim in rows:
        if not ipa:
            continue
        if XSAMPA.search(ipa):                                  # A5：整条丢掉
            ipa_fix.append(("drop", pid, wid, word, ipa, None, prim))
            continue
        new = ipa
        for ch in DELIM:                                        # A1
            new = new.replace(ch, "")
        new = new.replace("g", "ɡ")                             # A3（U+0067 → U+0261）
        new = new.replace("'", "ˈ").replace("ʼ", "ˈ")           # A4
        new = new.strip()
        final[pid] = (wid, word, ipa, new, nota, prim)

    # 按归一**之后**的键分组，每组只留一条：优先留主读音，其次留 id 最小的
    groups = {}
    for pid, (wid, word, old, new, nota, prim) in final.items():
        groups.setdefault((wid, new, nota), []).append(pid)
    for key, pids in groups.items():
        pids.sort(key=lambda p: (not final[p][5], p))            # 主读音排前
        keep = pids[0]
        wid, word, old, new, nota, prim = final[keep]
        if new != old:
            ipa_fix.append(("set", keep, wid, word, old, new, prim))
        for p in pids[1:]:
            w2, wd2, o2, _n2, _nt2, pr2 = final[p]
            ipa_fix.append(("dedup", p, w2, wd2, o2, new, pr2))
            if pr2 and not prim:                                 # 主读音要转过去
                ipa_fix.append(("primary", keep, wid, word, old, new, 1))

    # ── B4：出版层释义是空壳，且该义项一个中文都没有 ⇒ 隐掉义项 ──────────
    #    🔴 不是删 gloss —— 删了义项就彻底空白。隐藏**可逆**（`[[prefer-reversible-designs]]`）。
    zh = {s for (s,) in con.execute("SELECT DISTINCT sense_id FROM sense_gloss WHERE lang='zh'")}
    for word, sid, t in con.execute(
            "SELECT d.word, g.sense_id, g.text FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN entry e ON e.id=s.entry_id "
            "JOIN dict d ON d.id=e.word_id "
            "WHERE g.lang='fr' AND COALESCE(s.hidden,0)=0"):
        if t and (_res.EMPTY.match(t) or t in _res.STUB) and sid not in zh:
            hide.append((sid, word, t, "B4 释义只剩 %r 且无中文" % t))

    # ── B6：维基链接残渣 ─────────────────────────────────────────────
    for word, sid, t in con.execute(
            "SELECT d.word, g.sense_id, g.text FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN entry e ON e.id=s.entry_id "
            "JOIN dict d ON d.id=e.word_id "
            "WHERE g.lang='fr' AND COALESCE(s.hidden,0)=0"):
        if not t or not ("[[" in t or "]]" in t or "{{" in t or "}}" in t):
            continue
        p = B6_PLAN.get(word)
        if p and p[0] == "keep":
            continue
        if p and p[0] == "hide":
            hide.append((sid, word, t, "B6 " + p[1]))
            continue
        if p and p[0] == "sub":
            new = b6_clean(t.replace(p[1], p[2]))
            if new != t:
                gl_fix.append((sid, word, t, new))
            continue
        new = b6_clean(t)
        if new != t:
            gl_fix.append((sid, word, t, new))

    # ── D2：变形表 base 归一 ─────────────────────────────────────────
    for b, in con.execute("SELECT DISTINCT base FROM inflection WHERE base IS NOT NULL"):
        if b != norm_apos(b):
            infl_fix.append((b, norm_apos(b)))
    return ipa_fix, gl_fix, hide, infl_fix


def show(ipa_fix, gl_fix, hide, infl_fix, n=6):
    drops = [x for x in ipa_fix if x[0] == "drop"]
    sets = [x for x in ipa_fix if x[0] == "set"]
    dedup = [x for x in ipa_fix if x[0] == "dedup"]
    prim_mv = [x for x in ipa_fix if x[0] == "primary"]
    print("■ 音标：改 %s 条 ｜ 丢 %s 条（X-SAMPA）｜ 归一后重复删 %s 条 ｜ 主读音转移 %s 条"
          % (f(len(sets)), f(len(drops)), f(len(dedup)), f(len(prim_mv))))
    for _k, _p, _w, word, old, new, prim in sets[:n]:
        print("     %-22s %-26r → %r%s" % (word[:22], old[:26], new[:26], " ★主" if prim else ""))
    for _k, _p, _w, word, old, _n2, prim in drops[:3]:
        print("     丢 %-20s %r%s" % (word[:20], old[:34], " ★主" if prim else ""))
    for _k, _p, _w, word, old, new, prim in dedup[:4]:
        print("     重复 %-18s %-22r 已并入 %r%s"
              % (word[:18], old[:22], new[:22], " ★主" if prim else ""))
    print("\n■ 释义清理 %s 条（**逐条打全，这一族必须肉眼过**）" % f(len(gl_fix)))
    for sid, word, old, new in gl_fix:
        print("     【%s】\n        旧 %s\n        新 %s" % (word[:22], old[:78], new[:78]))
    print("\n■ 隐掉义项 %s 条" % f(len(hide)))
    for sid, word, t, why in hide[:n]:
        print("     【%-18s】 sense=%-8d %s" % (word[:18], sid, why))
    print("\n■ 变形表 base 归一 %s 条" % f(len(infl_fix)))
    for a, b in infl_fix[:4]:
        print("     %r → %r" % (a, b))


def gates(con, ipa_fix, gl_fix, hide):
    """🔴 改音标前先证明我**没有改变音值**（只去标记、只换等价符号）。"""
    ok = True

    def g(name, bad, n):
        nonlocal ok
        print("  %s %s：%s / %s" % ("✅" if not bad else "🔴", name, f(bad), f(n)))
        if bad:
            ok = False

    sets = [x for x in ipa_fix if x[0] == "set"]
    # ① 改完不许还剩缺陷符号
    g("① 改完不含 \\ / [ ] ' ʼ 与拉丁 g",
      sum(1 for x in sets if any(ch in x[5] for ch in DELIM) or "'" in x[5]
          or "ʼ" in x[5] or "g" in x[5]), len(sets))
    # ② 🔴 只许发生这四种替换。把改动逐字回放一遍，对不上就是我动了别的
    def replay(old):
        s = old
        for ch in DELIM:
            s = s.replace(ch, "")
        return s.replace("g", "ɡ").replace("'", "ˈ").replace("ʼ", "ˈ").strip()
    g("② 改动可逐字回放（没动别的）",
      sum(1 for x in sets if replay(x[4]) != x[5]), len(sets))
    # ③ 改完不许变空
    g("③ 改完非空", sum(1 for x in sets if not x[5].strip()), len(sets))
    # ④ 丢掉 X-SAMPA 后，主读音不能出现空缺（要重选）
    drops = {x[1] for x in ipa_fix if x[0] == "drop"}
    orphan = con.execute(
        "SELECT COUNT(*) FROM (SELECT word_id FROM pronunciation WHERE id IN (%s) "
        "AND is_primary=1)" % ",".join("?" * len(drops)), list(drops)).fetchone()[0] if drops else 0
    print("  ℹ️ 丢掉的行里有 %d 条是主读音 ⇒ 落库后要重选" % orphan)
    # ⑤ 释义清理**只许删、不许增也不许改顺序**。
    #    🔴 第一版写的是「字母逐字不变」，报 2 条红 —— 而那 2 条是**对的**：
    #       维基管道链接 `[(dissoudre|dissoute]]` 取显示侧 `dissoute`，
    #       按设计就会删掉目标侧 `dissoudre` 的字母。
    #       ⇒ 正确的不变量是**子序列**：新串的字母必须能在旧串里按序找到。
    #       这既允许「删」，又挡住「凭空多出字」和「顺序被打乱」。
    def letters(s):
        return re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]", "", s)

    def is_subseq(a, b):
        it = iter(b)
        return all(ch in it for ch in a)
    g("⑤ 释义清理只删不增（新串字母是旧串的子序列）",
      sum(1 for _s, _w, o, n2 in gl_fix if not is_subseq(letters(n2), letters(o))),
      len(gl_fix))
    # ⑥ 要隐的义项必须**确实没有中文**
    if hide:
        ids = [h[0] for h in hide]
        bad = con.execute(
            "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND sense_id IN (%s)"
            % ",".join("?" * len(ids)), ids).fetchone()[0]
        g("⑥ 要隐的义项确实没有中文", bad, len(ids))
    return ok, orphan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ipa_fix, gl_fix, hide, infl_fix = plan(con)
    show(ipa_fix, gl_fix, hide, infl_fix)
    print("\n══ 闸 ══")
    ok, orphan = gates(con, ipa_fix, gl_fix, hide)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1

    drops = [x[1] for x in ipa_fix if x[0] in ("drop", "dedup")]
    sets = [(x[5], x[1]) for x in ipa_fix if x[0] == "set"]
    prim_mv = [(x[1],) for x in ipa_fix if x[0] == "primary"]
    lost = [x[2] for x in ipa_fix if x[0] == "drop" and x[6]]     # 丢了主读音的词形
    with dbtool.session("keep-v3-gate-reds",
                        expect={"#pronunciation": -len(drops), "#sense_gloss": 0}) as s:
        # 🔴 顺序要紧：**先删重复、再改值**。反过来会在删之前就撞 UNIQUE。
        s.executemany("DELETE FROM pronunciation WHERE id=?", [(i,) for i in drops])
        s.executemany("UPDATE pronunciation SET ipa=? WHERE id=?", sets)
        s.executemany("UPDATE pronunciation SET is_primary=1 WHERE id=?", prim_mv)
        # 🔴 重选主读音：优先音位式，其次任意一条 —— 保住 F4「一词一主」
        for wid in lost:
            row = s.execute(
                "SELECT id FROM pronunciation WHERE word_id=? "
                "ORDER BY (notation<>'phonemic'), id LIMIT 1", (wid,)).fetchone()
            if row:
                s.execute("UPDATE pronunciation SET is_primary=1 WHERE id=?", (row[0],))
        s.executemany("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='fr'",
                      [(n, sid) for sid, _w, _o, n in gl_fix])
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", [(h[0],) for h in hide])
        s.executemany("UPDATE inflection SET base=? WHERE base=?",
                      [(b, a_) for a_, b in infl_fix])
    print("✓ 写入完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
