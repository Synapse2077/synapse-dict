#!/usr/bin/env python3
"""**外锚闸·第二支**：例句 / 变形 / 读音三层 vs dump。ko，2026-09-24（阶段 8）。

`verify_vs_dump.py` 只管义项那一支。`PLAYBOOK` §7.2 要**每张出版层表都有**一道
锚外部 dump 的闸（`[[external-anchor-gates]]`：锚自己上一版的必然过期）。

═══ 🔴 我的第一版判据太宽，这一版是改过的 ═══
第一版把源头侧写成「dump 里每条 `examples[].text` 都该在库里」，当场报 3 万条"缺"。
逐条看下去**一条真缺都没有**：
    · 中文版的 `text` 是 `그는 왔다　他来了`（**全角空格**把原文和译文挤在一格），
      我拿整串去比，而库里存的是切开之后的韩语正文 ⇒ 每条都"对不上"
    · 英文版的 forms 里 `vowel-stem` `infinitive` 这类**表头文字**被我当成了变形词形
    · 韩文版 `近义词：추` 这种**关系数据**塞在 examples 里，本来就该留给关系层
⇒ 这三样全是**收割器早就处理过的**，是我的闸自己重写了一遍判据、写得比它宽。
   `[[criteria-narrower-than-you-think]]` 的老毛病 ——
   **闸与收割器判据一旦漂开，闸报的就是它自己的 bug**（fr 那轮 42 条假缺口）。

⇒ 本文件**一个判据都不重写**，三层各 import 收割器本身：
    例句   `harvest_examples.harvest()`        （含 LABEL_DROP / split_text / is_zh）
    变形   `build_inflection_layer.iter_forms()`（含 infl_tags.classify / is_korean_form）
    读音   `build_pronunciation.norm_ipa()`     （含"单边定界符也认"那条）

═══ ⚠️ 这道闸**逮得到什么、逮不到什么**，说在前面 ═══
它是 **源头 → 库** 的恒等式。
  ✅ 逮得到：写库时丢了行、后续某一步静默改了行、库里出现追不回源头的行、
            源头换了一份 dump 而没人重跑
  ❌ **逮不到：收割器的判据本身写错了**（判据错，两边一起错，恒等式照样成立）
🔴 所以每层除了恒等式，都另外把**"有意不收"的那一桶的大小锁成数**（`BUDGET`）——
   那一桶此前只存在于收割器的 `Counter` 里，跑完就没了。
   判据一旦悄悄放宽，桶的大小会动 ⇒ 闸红 ⇒ 逼我重新说明理由。
   ⚠️ 但这仍然不是"判据对不对"的证明，只是**让它动起来有声音**。

用法（在仓库根）：
    python3 -u ko/pipeline/verify_layers_vs_dump.py
    python3 -u ko/pipeline/verify_layers_vs_dump.py --layer example --show 20
    python3 -u ko/pipeline/verify_layers_vs_dump.py --mutate
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import json
import sqlite3

import paths
import harvest_examples as HE
import build_inflection_layer as BI
import build_pronunciation as BP

f = lambda n: format(n, ",")

# X-SAMPA 判据：IPA 不用 ASCII 数字/反引号/反斜杠/下划线，X-SAMPA 这四样全用。
# 🔴 **import 那一份，不重抄** —— 这是本文件从头到尾的规矩（见文件头）。
#    我第一版在这儿又写了一遍 re，还在注释里写着"能 import 就 import"。
from fix_xsampa_ipa import BAD as XSAMPA        # noqa: E402


def ro():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


# ══════════════════════════════════════════════════════════════════
# ⚠️ 本文件**有意没有 `BUDGET`**，与 `verify_vs_dump.py` 不同 ——
#    那边的每一版都有一笔「有意不收」的账要锁上限，这三层是**双向恒等式**：
#    缺口必须是 0，没有"允许缺多少"这回事。
#    唯一不算失败的是「词形不在 `dict` 里」，而它**按含义重算、不锁数字**
#    （锁成数就会在补收词之后逼我照着新数字调，`[[expectation-must-be-declared]]`）。
#    「有意不收」那几桶只**报大小、不设上限** —— 它们的作用是把收割器 `Counter`
#    里跑完就没的那些数摆到台面上，让判据放宽的时候有声音。


# ══════════════════════════════════════════════════════════════════
def layer_example(show=0):
    """例句层：`harvest_examples.harvest()` 的产出 ≡ 库里的 `example` 行。

    🔴 **两个方向都查**。只查「源头有而库里没有」漏掉另一半：
       库里有而源头追不回去的行（别的写入方偷偷插的、或者某一步改过文本）。
       `[[primary-key-is-not-enough]]`：计数型闸对"错配"结构性失明 ——
       这儿用 `(word, text)` 二元组，正是 `example` 的 UNIQUE 键。
    """
    rows, labeled, resid, stat = HE.harvest()
    want = {(r["word"], r["text"]) for r in rows}
    con = ro()
    have = {(w, t) for w, t in con.execute("SELECT word, text FROM example")}
    indict = {r[0] for r in con.execute("SELECT word FROM dict")}
    # 「有意不收」那一桶：带 LABEL_DROP 前缀的，留给关系层
    dropped = collections.Counter(s for s, _w, _lab, _b in labeled)
    # 这一桶里**已经被关系层吃掉的**有多少 —— 剩下的是真·未消费欠账
    # 🔴 判据是 `src_ref` 的**形状**，不是 `src`：`sense_relation.src` 存的是
    #    「哪一版 dump」，两个写入方（`build_relation_layer` 与
    #    `harvest_relations_from_examples`）填的是同一批版名，分不开。
    #    能分开的是 src_ref：关系层走 `kk-ko:…#s0:rel:…`（带义项下标 `#`），
    #    例句标签那一支走 `<版>:<词>:rel:<kind>:<目标>`（没有 `#`）。
    #    ⚠️ 这条只是**能分**，不是**设计上分得清** —— 落账见 K14。
    reledges = con.execute(
        "SELECT COUNT(*) FROM sense_relation "
        "WHERE src_ref LIKE '%:rel:%' AND src_ref NOT LIKE '%#%'").fetchone()[0]
    con.close()

    gap, extra = want - have, have - want
    # 🔴 「词形不在 `dict` 里」**单独报、不算失败** —— 那是收词缺口不是例句缺口
    #    （与义项那一支同一条规矩）。收割器 `main()` 里那行
    #    `miss = [r for r in rows if r["word"] not in indict]` 就是它。
    #    ⚠️ 这一桶**按含义重算，不锁数字**：它随 `dict` 变，
    #      锁成数就会在补收词之后逼我"照着新数字调"（`[[expectation-must-be-declared]]`）。
    nodict = {x for x in gap if x[0] not in indict}
    miss = gap - nodict
    print("■ 例句层")
    print("   收割器产出 %8s   库里 %8s" % (f(len(want)), f(len(have))))
    print("   %s 源头有·库里没有 %s   其中词形不在 `dict` %s ⇒ 真缺 %s"
          % ("✅" if not miss else "🔴", f(len(gap)), f(len(nodict)), f(len(miss))))
    print("   %s 库里有·追不回源头 %s" % ("✅" if not extra else "🔴", f(len(extra))))
    if show or miss:
        for w, t in list(miss)[:max(show, 10)]:
            print("      🔴缺  %-12s %s" % (w, t[:70]))
    if show:
        for w, t in list(nodict)[:show]:
            print("      (无词条) %-12s %s" % (w, t[:60]))
        for w, t in list(extra)[:show]:
            print("      多  %-12s %s" % (w, t[:70]))
    print("   ── 有意不收的那一桶（带关系标签，留给关系层）──")
    tot = sum(dropped.values())
    for s, n in dropped.most_common():
        print("      %-18s %7s" % (s, f(n)))
    print("      %-18s %7s   其中关系层已消费 %s 条边"
          % ("合计", f(tot), f(reledges)))
    if resid:
        print("   ⚠️ 不在标签表里的前缀（当例句收了，但报出来）top 8：%s"
              % resid.most_common(8))
    return {"miss": len(miss), "extra": len(extra), "drop": tot,
            "gap": len(gap), "nodict": len(nodict),
            "drop_by_src": dict(dropped), "resid": len(resid),
            "_want": want, "_have": have}


# ══════════════════════════════════════════════════════════════════
def layer_inflection(show=0):
    """变形层：`build_inflection_layer.iter_forms()` 的产出 ≡ 库里的 `inflection` 行。

    ⚠️ 身份键 = **(原形, 变形形, 排序后的 tags)** —— 与收割器去重用的那个键同一个
       （`iter_forms` 的 `seen_fact`）。库侧从 `base` ＋ `word_id→word` ＋ `tags`
       这三列还原同一个键。
    🔴 **不拿行数比行数**：行数相等而配对错乱是最常见的坏法
       （`[[primary-key-is-not-enough]]`，ja 的变形层八条回核全绿而数据是坏的）。
    """
    con = ro()
    id2w = {r[0]: r[1] for r in con.execute("SELECT id, word FROM dict")}
    have = set()
    # 🔴 排除 `src='rule'`：那是 `conj_generate.py` **按规则生成**的活用表
    #    （源头对那些词一张表都没有，见 K8）⇒ dump 里根本没有它们，
    #    拿它去比源头每一行都会"多出来"。
    #    ⚠️ 与读音层排除 `src='g2p'` **同一条规矩**：生成数据有自己的验法
    #      （`conj_generate` 的留出法自测），不归外锚闸管。
    #    🔴 但它**不是豁免**：生成行的正确性由那一步的闸守着，
    #      而"有没有人偷偷用 rule 这个 src 塞别的东西"由下面的行数报出来。
    nrule = con.execute(
        "SELECT COUNT(*) FROM inflection WHERE src='rule'").fetchone()[0]
    for wid, base, tags in con.execute(
            "SELECT word_id, base, tags FROM inflection WHERE src <> 'rule'"):
        try:
            tg = tuple(json.loads(tags))
        except Exception:
            tg = ()
        have.add((base, id2w.get(wid), tg))
    con.close()

    want = set()
    cls = collections.Counter()
    for w, _eref, fw, tags, _i in BI.iter_forms():
        want.add((w, fw, tuple(sorted(tags))))
    # 🔴🔴 **有意偏离源头的那一批**（2026-09-24，`fix_bad_inflected_forms.py`）。
    #    源头给 `짝짓다`/`한숨짓다` 生成的是**规则**活用表，而这两个词是 ㅅ불규칙 ⇒
    #    库里的 `짝짓어` 已改成 `짝지어`。恒等式因此不再成立，**这正是我们要的**。
    # ⚠️ 登记成**变换**而不是一个数：源头侧原样套同一条 ㅅ 脱落变换，
    #    于是「第 93 条偏离」照样会红。写成「允许差 92 条」就等于把闸关了
    #    （`[[proxy-metric-gets-optimized]]`）。
    from fix_bad_inflected_forms import LEMMAS as _FIXED, is_bad as _isbad, fix_form as _fix
    want = {(b, _fix(fw, b) if b in _FIXED and _isbad(fw, b) else fw, tg)
            for b, fw, tg in want}
    # 「有意不收」那一桶：`classify` 判为非 inflection 的 form
    from infl_tags import classify
    notkorean = 0
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        if o.get("pos") == "romanization":
            continue
        w = o.get("word")
        if not w or not w.strip():
            continue
        for fo in (o.get("forms") or []):
            c = classify(fo.get("tags") or [])
            if c != "inflection":
                cls[c or "（分不出类·旧模板残留）"] += 1
                continue
            fw = (fo.get("form") or "").strip()
            if not fw or fw in ("-", "—") or fw == w:
                cls["空/占位/与原形同形"] += 1
                continue
            if not BI.is_korean_form(fw):
                notkorean += 1

    miss, extra = want - have, have - want
    print("\n■ 变形层")
    print("   收割器产出 %8s   库里 %8s   （另有 %s 行 `src='rule'` 生成表，不参与比对）"
          % (f(len(want)), f(len(have)), f(nrule)))
    print("   %s 源头有·库里没有 %s" % ("✅" if not miss else "🔴", f(len(miss))))
    print("   %s 库里有·追不回源头 %s" % ("✅" if not extra else "🔴", f(len(extra))))
    if show:
        for x in list(miss)[:show]:
            print("      缺  %s" % (x,))
        for x in list(extra)[:show]:
            print("      多  %s" % (x,))
    print("   ── 有意不收的那一桶（`infl_tags.classify` 分流走的）──")
    for c, n in cls.most_common():
        print("      %-26s %8s" % (c, f(n)))
    print("      %-26s %8s   ← `is_korean_form` 拦下的表头文字/模板残留"
          % ("不是韩语词形", f(notkorean)))
    return {"miss": len(miss), "extra": len(extra),
            "cls": dict(cls), "notkorean": notkorean,
            "_want": want, "_have": have}


# ══════════════════════════════════════════════════════════════════
def layer_pronunciation(show=0):
    """读音层：四版 dump 的 `sounds[].ipa` ≡ 库里 `src<>'g2p'` 的 `pronunciation` 行。

    🔴 **排除 `src='g2p'` 的 18 万行** —— 那是我们自己按 표준발음법 算的，
       dump 里根本没有。拿它去比源头 ＝ 每一条都"多出来"。
       它有**自己的外部锚闸**（`ko/tests/test_g2p_rules.py`，锚条文例词）。
    🔴🔴 身份键 = **`(词形, 裸 IPA)`**，`notation` 靠 `BP.pick_notation` 从
       源头那一组记法还原 —— **不是** `(词形, IPA, notation)`。
       第一版我写成了后者，当场报 **7,163 条"缺"，一条真缺都没有**：
       收割器的聚合键就是 `(wid, ipa)`，几版记法不同时**有意合并成一行取窄式**
       （`읽다` 的 `ik̚t͈a̠` 在英/韩版是 `[…]`、日文版是 `/…/`，是同一个音值）。
       ⇒ 我的闸比收割器**细了一档**，于是把"合并"读成了"丢失"。
       这与例句那一版"比收割器宽"是同一个病的两面：
       **判据不是自己写的，就不会对**（`[[criteria-narrower-than-you-think]]`）。
       ⇒ 那条规则已从 `main()` 里抽成 `BP.pick_notation()`，两边共用。
    ⚠️ 不带 `entry_id`：同一个 (词形,IPA) 会按词条拆行，而**源头侧还原不出那个拆法**
       —— 拿还原不出的东西去比就是在比我的猜测。
       `entry_id` 的正确性由收割器自己的回核管（那一步能看见 entry）。
    """
    con = ro()
    indict = {r[0] for r in con.execute("SELECT word FROM dict")}
    have = {(w, i, n) for w, i, n in con.execute(
        "SELECT d.word, p.ipa, p.notation FROM pronunciation p "
        "JOIN dict d ON d.id=p.word_id WHERE p.src <> 'g2p'")}
    con.close()

    acc = collections.defaultdict(set)      # (词形, 裸IPA) → {源头给的记法}
    notin = collections.Counter()
    for src, path, _base in BP.SOURCES:
        for line in BP.op(path):
            try:
                d = json.loads(line)
            except Exception:
                continue
            w = d.get("word")
            if not w or not w.strip():
                continue
            if w not in indict:
                for s in (d.get("sounds") or []):
                    if s.get("ipa"):
                        notin[src] += 1
                continue
            for s in (d.get("sounds") or []):
                if not s.get("ipa"):
                    continue
                ipa, notation = BP.norm_ipa(s["ipa"])
                # 🔴 **X-SAMPA 冒充 IPA，有意不收**（2026-09-25，见 `fix_xsampa_ipa.py`）。
                #    日文版的 `sounds.ipa` 里混着 X-SAMPA（`4mL\`` ＝ `ɾɯɭ`），98 行。
                #    ⚠️ 登记成**判据**不是数字：源头侧套同一条过滤 ⇒
                #      「源头新出现一条正常 IPA 而我们没收」照样会红。
                #      写成「允许差 98 条」就把闸关了。
                if ipa and not XSAMPA.search(ipa):
                    acc[(w, ipa)].add(notation)
    want = {(w, i, BP.pick_notation(ns)) for (w, i), ns in acc.items()}

    miss, extra = want - have, have - want
    print("\n■ 读音层（不含 g2p）")
    print("   源头 %8s   库里 %8s" % (f(len(want)), f(len(have))))
    print("   %s 源头有·库里没有 %s" % ("✅" if not miss else "🔴", f(len(miss))))
    print("   %s 库里有·追不回源头 %s" % ("✅" if not extra else "🔴", f(len(extra))))
    if show:
        for x in list(miss)[:show]:
            print("      缺  %s" % (x,))
        for x in list(extra)[:show]:
            print("      多  %s" % (x,))
    print("   ── 词形不在 `dict` 里因而没收的 IPA ──")
    for s, n in notin.most_common():
        print("      %-18s %7s" % (s, f(n)))
    print("      🔴 这一桶就是 K13 那笔账的形状：**有读音、没词条**。"
          "收词之后它应该缩小，缩不下去的是别的语言的词（跨版 dump 里有大量外语词条）")
    return {"miss": len(miss), "extra": len(extra), "notin": dict(notin),
            "_want": want, "_have": have}


# ══════════════════════════════════════════════════════════════════
# 🔴 变异验证（`PLAYBOOK` 7.3）——**一条永远通过的检查等于没检查**。
#    每条都对着「这道闸声称能逮到什么」，不是「它跑不跑得起来」。
MUTATIONS = {
    "N1": ("例句：库侧删掉 200 行",
           "恒等式的「源头有·库里没有」那一半**必须红** —— 验它真在查写丢的行"),
    "N2": ("例句：把 `近义词` 从 LABEL_DROP 里拿掉",
           "那 2,000 多条关系数据会当例句收 ⇒ **「库里有·追不回源头」必须变**。"
           "🔴 它验的是反向那一半 —— 判据放宽会不会有声音"),
    "N3": ("变形：库侧把 100 行的 `tags` 打乱",
           "行数一点不变 ⇒ **计数型闸完全看不见**，而身份键带 tags 的必须红。"
           "验的正是 ja 栽过的那个坑：八条回核全绿而配对是错的"),
    "N5": ("变形：再「有意偏离」源头一条（登记之外的）",
           "🔴 我们有意把 `짝짓다`/`한숨짓다` 的 92 个形式改得与源头不同，"
           "并把**变换**登记进了闸。验的是这个登记**没有把闸关掉**："
           "第 93 条没登记的偏离**必须红**。写成「允许差 92 条」就过不了这一关"),
    "N4": ("读音：库侧把 `src='g2p'` 也算进来",
           "18 万条规则读音 dump 里没有 ⇒ **「追不回源头」必须暴涨**。"
           "验的是「排除 g2p」这条不是随口说的"),
}


def mutate(which, ex, infl, pron):
    if which == "N1":
        h = set(list(ex["_have"])[200:])
        return len(ex["_want"] - h), len(h - ex["_want"])
    if which == "N2":
        HE.LABEL_DROP.discard("近义词")
        HE.LABEL_DROP.discard("近義詞")
        rows, _l, _r, _s = HE.harvest()
        HE.LABEL_DROP.add("近义词")
        HE.LABEL_DROP.add("近義詞")
        want2 = {(r["word"], r["text"]) for r in rows}
        return len(want2 - ex["_have"]), len(ex["_have"] - want2)
    if which == "N3":
        h = list(infl["_have"])
        h2 = set(h[100:]) | {(b, w, tuple(reversed(t))) for b, w, t in h[:100]}
        return len(infl["_want"] - h2), len(h2 - infl["_want"])
    if which == "N5":
        # 把库侧**另一个**词的一条形式改掉（不在登记名单里）⇒ 恒等式必须报红
        h = set(infl["_have"])
        victim = next(x for x in sorted(h) if x[0] == "결정짓다")
        h.discard(victim)
        h.add((victim[0], victim[1] + "ㄱ", victim[2]))
        return len(infl["_want"] - h), len(h - infl["_want"])
    if which == "N4":
        con = ro()
        h = {(w, i, n) for w, i, n in con.execute(
            "SELECT d.word, p.ipa, p.notation FROM pronunciation p "
            "JOIN dict d ON d.id=p.word_id")}
        con.close()
        return len(pron["_want"] - h), len(h - pron["_want"])
    raise KeyError(which)


def run_mutations(ex, infl, pron):
    # ⚠️ 例句那两条的基线用**未扣「词形不在 dict」的 raw gap** ——
    #    `mutate()` 返回的也是 raw，两边必须同一个口径才比得出变化。
    base = {"N1": (ex["gap"], ex["extra"]), "N2": (ex["gap"], ex["extra"]),
            "N3": (infl["miss"], infl["extra"]), "N5": (infl["miss"], infl["extra"]),
            "N4": (pron["miss"], pron["extra"])}
    print("\n═══ 变异验证（%d 条）═══" % len(MUTATIONS))
    bad = 0
    for mid, (what, why) in MUTATIONS.items():
        m, e = mutate(mid, ex, infl, pron)
        b = base[mid]
        if mid == "N1":
            ok = m > b[0]
        elif mid == "N2":
            ok = e != b[1] or m != b[0]
        elif mid in ("N3", "N5"):
            ok = m > b[0] and e > b[1]
        else:
            ok = e > b[1] + 100_000
        bad += not ok
        print("   %s %-4s %-34s 缺=%s 多=%s（基线 缺=%s 多=%s）"
              % ("✅" if ok else "🔴", mid, what, f(m), f(e), f(b[0]), f(b[1])))
        print("        期望：%s" % why)
    print("   %s 变异验证：%d/%d"
          % ("✅" if not bad else "🔴", len(MUTATIONS) - bad, len(MUTATIONS)))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", default="", choices=["", "example", "inflection",
                                                    "pronunciation"])
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()

    ex = infl = pron = None
    if a.layer in ("", "example"):
        ex = layer_example(a.show)
    if a.layer in ("", "inflection"):
        infl = layer_inflection(a.show)
    if a.layer in ("", "pronunciation"):
        pron = layer_pronunciation(a.show)

    red = sum((d["miss"] > 0) + (d["extra"] > 0)
              for d in (ex, infl, pron) if d)
    if a.mutate and ex and infl and pron:
        red += run_mutations(ex, infl, pron)
    if red:
        raise SystemExit("\n🔴 外锚闸·三层：%d 项对不上" % red)
    print("\n■ 外锚闸·例句/变形/读音三层 通过 ✓")


if __name__ == "__main__":
    main()
