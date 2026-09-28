#!/usr/bin/env python3
"""**外锚闸**：库 vs 五份 dump，**义项级**逐条比对。ko 版，2026-09-24（阶段 8）。

═══ 为什么必须有这一道，且它与回归闸不可互相替代 ═══
`[[external-anchor-gates]]`：**锚自己上一版的必然过期，锚外部 dump 的永不过期**。

    回归闸  问「**过去的修复还在不在**」 —— 只看库里已有的东西
    外锚闸  问「**源头有而我们没有的，还剩多少**」

两个问题没有交集。es 那轮正是这道闸逮到 `derived` **义项级漏收 20,193 条**，
而所有内部闸（行数、不变量、可逆性）永远发现不了它：
**词形在库、义项没收进来**，按词形量覆盖率是满分。

═══ 🔴 必须义项级，不能词形级 ═══
按词形级量，「词形在库、这条义项没收」永远是绿的。
⇒ 一律按 **(归一词形, 义项文本)** 二元组比对。

═══ 🔴 判据一个字都不重抄：本文件 import `criteria.py` ═══
`is_pointer_sense` / `norm_ko` 原来在三个文件里各写一份 ——
建这道闸时抽成了 `ko/pipeline/criteria.py`（纯搬运，8.2 万条义项上验过行为一字未变）。
**闸与收词器判据漂开 ＝ 闸在报自己的 bug**：fr 那轮从 it 抄了一条「词缀豁免」，
当场报 42 条假缺口，逐条读下来 40 条是纯指针、收词器跳过是对的。

═══ 🔴🔴 这门与 ja **相反**的一条：指针义项要算进「我们有」═══
ja 的 `soft-redirect` 不产生义项，所以它的闸把指针排除在外。
**ko 的证据层是「全收、不做裁决」**（`sense_src` 里那 26,419 条 NULL 正是没出版的证据行），
指针义项照样落库 ⇒ 本闸的 dump 侧**不排除指针**，
否则会把库里真实存在的行算成"源头没有"，两边口径反着量。
⚠️ 这一条是 `[[decision-not-propagated-across-editions]]` 的正面用法：
   照搬 ja 的排除逻辑会让这道闸**在最该响的地方保持安静**。

═══ ⚠️ 「缺」的正当来源（不是缺陷），各自写明推翻条件 ═══
见 `BUDGET`。最大的一笔是**阶段 4a 对已在 `dict` 的词形整条跳过** ——
那是当时有意的（中文释义留给阶段 5），但它让三版的一批义项从没进过证据层。
🔴 **这道闸的价值就在于把那笔账摆到台面上**：它此前只存在于 `intake_editions.py`
的一行 `continue` 里，没有任何地方记着它有多大。

用法（在仓库根）：
    python3 -u ko/pipeline/verify_vs_dump.py
    python3 -u ko/pipeline/verify_vs_dump.py --show 20      # 逐条看缺的长什么样
    python3 -u ko/pipeline/verify_vs_dump.py --edition ko-edition --show 30
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

import paths
from criteria import NOT_A_WORD, norm_ko

f = lambda n: format(n, ",")

# 各版允许的缺口上限：`版 → (条数上限, 理由)`。**锁数字，不锁名字。**
# 🔴 上限一律写**实测值**，不许拍一个宽的 —— 拍宽了等于给自己留静默余量
#    （ja 的 zh-edition 原来写 70,000 是拍的，后来改回实测 55,363）。
BUDGET = {
    "en-edition": (
        0,
        "英文版是建库主源（阶段 1），义项**全收进证据层** ⇒ 一条都不许缺。"
        "🔴 这一版是唯一能写 0 的，因为它没有经过阶段 4a 那道「已在 dict 就跳过」。"),
    # 🔴🔴 **2026-09-26：K12 已结清，这三条上限跟着改小了 —— 理由也整个换掉。**
    #    旧理由是「阶段 4a 跳过已在 dict 的词形」，那个理由**已经作废**：
    #    `ko/pipeline/intake_skipped_senses.py` 把那批收进了证据层（52,565 条）。
    #    账上原话：「任何一个方向都要先把 `BUDGET` 改掉，否则闸会替这个决定继续背书」。
    "ko-edition": (
        0,
        "✅ **2026-09-26 收齐，缺口归零**（阶段 4a 跳过的那批已进证据层）。"
        "韩文版一条元描述都没有（`汉字或谚汉混合表记：…` 是中文版的写法）⇒ 上限写 0。"
        "🔴 **推翻条件**：dump 换版之后源头新增了义项 —— 那时重跑收割器，不是抬上限。"),
    "zh-edition-simp": (
        11_088,
        "剩下的**全部是元描述**（`汉字或谚汉混合表记：금발（金髮）`）—— 判据 "
        "`fix_meta_gloss.META`，就是 K10 那一族（实测 97.2% 是它）。"
        "**有意不收**：收进证据层只会灌噪声，出版层还得再筛一遍。"
        "🔴 这个数与 `intake_skipped_senses.py` 报的「有意不收·元描述」**逐条相等** —— "
        "残差能一条条说清，不是「其他」桶（`[[residual-bucket-is-not-evidence]]`）。"
        "🔴 **推翻条件**：决定把元描述也收进证据层（两层模型的『全收不做裁决』的严格读法），"
        "或 `META` 判据扩宽（实测它漏了**尖括号**写法 `궁수〈弓手 窮愁〉`，已并进本轮）。"),
    "zh-edition-trad": (
        1_492,
        "同上 —— 全部是元描述，与 `intake_skipped_senses.py` 的计数逐条相等。"),
    # 🔴🔴 这一档**不是阈值，是恒等式**（2026-09-24 改）。
    #    原来写死 34,897；阶段 8 补收 13,062 个词头之后它自动涨到 34,986 ——
    #    因为其中 89 个词日文版也有，于是从「词形不在库」挪到了「真缺」。
    #    **照着新数字往上调，与「收了新词就调低下限」是同一类动作**：
    #    数字随收词漂，而它要守的东西根本不是那个数字。
    #    ⇒ 判据按**含义**写：方针是「日语释义一条都不进库」
    #      ⇒ 缺口必须 **等于** 它落在库内词形上的全部义项数。
    #      少一条就说明有日语释义混进来了 —— 那才是这一档要逮的。
    "ja-edition": (
        "ALL",
        "🔴 **整版有意不进库**：日文版的释义是**日语**，而本项目「释义只保留三语」"
        "（中＋英＋本语言，`[[gloss-three-languages]]`）。它只用来给 IPA 交叉背书。"
        "⇒ 这一版的「缺口」等于它的全部义项数，**这不是缺陷，是方针**。"
        "🔴 **2026-09-25 方针被用户局部改过**：批准了选项① —— 收日文版那批释义、"
        "译成中文补覆盖率（927 条／+700 词元／0.18 元）。⇒ 「整版不进」不再是无条件的，"
        "闸改成**锚在已批准的 1,836 行上**（见 `APPROVED_JA`）。"
        "🔴 **推翻条件**：再批准收一批（连同 K24 那 3,344 条一起重算），或撤掉那 927 条。"),
}

SRC = [("en-edition", paths.KK, False),
       ("ko-edition", paths.EDITION, False),
       ("zh-edition-simp", paths.ZH_SIMP, True),
       ("zh-edition-trad", paths.ZH_TRAD, True),
       ("ja-edition", paths.JA_EDITION, True)]


def _op(p, gz):
    return (gzip.open(p, "rt", encoding="utf-8") if gz
            else open(p, "rt", encoding="utf-8"))


def dump_senses():
    """→ {版: {(归一词形, 义项文本)}}。

    🔴 取法必须与落库侧一致：
      · gloss 取 `glosses[-1]`（层级 gloss 的末项＝本义）—— `sense_src.text` 存的就是它
      · **不排除指针义项** —— ko 的证据层全收（见文件头）
      · 排除 `pos ∈ NOT_A_WORD`（import 自 `criteria`，不重抄）
    """
    out = {}
    for name, p, gz in SRC:
        s = set()
        with _op(p, gz) as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("pos") in NOT_A_WORD:
                    continue
                w = (o.get("word") or "").strip()
                if not w:
                    continue
                nw = norm_ko(w)
                for se in o.get("senses") or []:
                    g = se.get("glosses") or []
                    if g and (g[-1] or "").strip():
                        s.add((nw, g[-1].strip()))
        out[name] = s
        print("   %-18s 源头义项二元组 %s" % (name, f(len(s))), flush=True)
    return out


def db_senses(con):
    """库里的（出版层 ∪ 证据层）。**证据层也算「我们有」** ——
    出版层没出的，证据层留着就不算丢（两层义项模型的直接后果）。"""
    have = set()
    for w, t in con.execute(
            "SELECT d.word, g.text FROM sense_gloss g "
            "JOIN sense s ON s.id = g.sense_id JOIN dict d ON d.id = s.word_id "
            "WHERE g.src NOT LIKE 'model:%'"):
        have.add((norm_ko(w), (t or "").strip()))
    for w, t in con.execute(
            "SELECT d.word, x.text FROM sense_src x JOIN dict d ON d.id = x.word_id"):
        have.add((norm_ko(w), (t or "").strip()))
    return have


# ══════════════════════════════════════════════════════════════════
# 🔴 变异验证（`PLAYBOOK` 7.3）——**一条永远通过的检查等于没检查**。
#    每条变异都对着「这道闸声称自己能逮到什么」，而不是「它跑不跑得起来」。
MUTATIONS = {
    "M1": ("从库侧删掉 100 条 en-edition 的义项",
           "en-edition 的上限是 0 ⇒ **必须红**。它验的是"
           "「源头有而库里没有」这件事到底查没查"),
    "M2": ("dump 侧排除指针义项（照抄 ja 的做法）",
           "ko 的证据层**全收指针**，排除它会让两边口径反着量 ⇒ "
           "缺口数**必须变**。它验的是文件头那条「与 ja 相反」不是空话"),
    "M3": ("库侧只留出版层，扔掉证据层",
           "缺口**必须暴涨** ⇒ 证明证据层确实在兜底，"
           "而不是「出版层恰好就够」"),
    "M4": ("词形归一去掉 NFC",
           "源头两版词头实测 100% 已是 NFC ⇒ 这一条**应该几乎不变**。"
           "🔴 它验的是反面：**如果变了很多，说明我对源头的判断错了**"),
}


def mutate(which, have, src):
    """→ (have, src)，按变异改一份**副本**。"""
    have, src = set(have), {k: set(v) for k, v in src.items()}
    if which == "M1":
        en = list(src["en-edition"])[:100]
        have -= set(en)
    elif which == "M2":
        from criteria import is_pointer_sense
        keep = {}
        for name, p, gz in SRC:
            s2 = set()
            with _op(p, gz) as fh:
                for line in fh:
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    if o.get("pos") in NOT_A_WORD:
                        continue
                    w = (o.get("word") or "").strip()
                    if not w:
                        continue
                    nw = norm_ko(w)
                    for se in o.get("senses") or []:
                        g = se.get("glosses") or []
                        if g and (g[-1] or "").strip() and not is_pointer_sense(se):
                            s2.add((nw, g[-1].strip()))
            keep[name] = s2
        src = keep
    elif which == "M3":
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        have = set()
        for w, t in con.execute(
                "SELECT d.word, g.text FROM sense_gloss g "
                "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
                "WHERE g.src NOT LIKE 'model:%'"):
            have.add((norm_ko(w), (t or "").strip()))
        con.close()
    elif which == "M4":
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        have = set()
        for w, t in con.execute(
                "SELECT d.word, g.text FROM sense_gloss g "
                "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
                "WHERE g.src NOT LIKE 'model:%'"):
            have.add((w, (t or "").strip()))
        for w, t in con.execute(
                "SELECT d.word, x.text FROM sense_src x JOIN dict d ON d.id=x.word_id"):
            have.add((w, (t or "").strip()))
        con.close()
        src = {k: {(w, t) for w, t in v} for k, v in src.items()}
    return have, src


def gaps(have, src):
    return {name: len(src[name] - have) for name, _p, _gz in SRC}


def run_mutations(have, src):
    base = gaps(have, src)
    print("\n═══ 变异验证（%d 条）═══" % len(MUTATIONS))
    print("   基线：" + "  ".join("%s=%s" % (k, f(v)) for k, v in base.items()))
    bad = 0
    for mid, (what, expect) in MUTATIONS.items():
        h2, s2 = mutate(mid, have, src)
        g2 = gaps(h2, s2)
        if mid == "M1":
            ok = g2["en-edition"] > base["en-edition"]
        elif mid == "M2":
            ok = g2 != base
        elif mid == "M3":
            ok = sum(g2.values()) > sum(base.values()) * 1.2
        else:
            ok = abs(sum(g2.values()) - sum(base.values())) <= 50
        bad += not ok
        print("   %s %-4s %-32s %s" % ("✅" if ok else "🔴", mid, what,
                                       "  ".join("%s=%s" % (k, f(v)) for k, v in g2.items())))
        print("        期望：%s" % expect)
    print("   %s 变异验证：%d/%d"
          % ("✅" if not bad else "🔴", len(MUTATIONS) - bad, len(MUTATIONS)))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--edition", default="")
    ap.add_argument("--mutate", action="store_true",
                    help="变异验证：这道闸到底逮不逮得住它声称能逮的")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = db_senses(con)
    print("■ 库里（出版层 ∪ 证据层）义项二元组 %s\n" % f(len(have)))
    indict = {norm_ko(r[0]) for r in con.execute("SELECT word FROM dict")}
    con.close()

    src = dump_senses()
    print()
    red = 0
    for name, _p, _gz in SRC:
        if a.edition and name != a.edition:
            continue
        s = src[name]
        miss = s - have
        cap, why = BUDGET[name]
        # 🔴 「词形不在库里」**单独报、不计入失败** —— 那是收词缺口，
        #    混在一起报，这道闸就永远非零（`PLAYBOOK` 7.2）。
        nw_miss = {x for x in miss if x[0] not in indict}
        real = miss - nw_miss
        pct = 100.0 * len(miss) / max(len(s), 1)
        mark = "✅"
        if cap == "ALL":
            # 🔴🔴 **判据按结构写，不按文本比**（2026-09-24 第二次改）。
            #    第一版写成恒等式「库内词形上的日语义项一条都不许出现在库里」，
            #    当场报 3 条 —— 逐条看下去**全是假阳性**：
            #        석두 → 石頭   src=zh-edition-trad          中文版给的
            #        일본인 → 日本人 src=model:deepseek-v4-flash  我们自己译的中文
            #    **汉字词的中文释义与日语释义经常是同一个字符串**，
            #    「文本相同」推不出「收了日语释义」（`[[criteria-narrower-than-you-think]]`
            #     的反面：判据比它要描述的东西更宽）。
            #    ⇒ 方针是「日语释义不进库」，那就**直接查有没有日语来源的行**：
            #      结构判据精确、且不受汉字词同形干扰。
            _c = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
            leaked = _c.execute(
                "SELECT COUNT(*) FROM sense_gloss WHERE lang='ja' "
                "OR src LIKE '%ja-edition%'").fetchone()[0]
            leaked += _c.execute(
                "SELECT COUNT(*) FROM sense_src WHERE lang='ja' "
                "OR src LIKE '%ja-edition%'").fetchone()[0]
            _c.close()
            # 🔴🔴 **2026-09-26：方针被用户改过，而这条判据没跟着改 ⇒ 闸从 09-25 起一直红着。**
            #    原判据是「一行都不许有」。但 2026-09-25 用户批准了**选项①**：
            #    收日文版给的那批日语释义、译成中文补覆盖率（927 条，+700 词元）。
            #    ⇒ 「整版不进」这句话**已经不是现行方针**，闸拿它继续判就是拿作废的规矩报红。
            #    ⚠️ 但不能改成「不查」—— 那会把**新的**泄漏一起放过。
            #    ⇒ 锚在**已批准的那个数**上：只许是这 1,836 行，多一行少一行都红。
            #      1,836 ＝ `sense_src` 927（收割的原文）＋ `sense_gloss` 909（译文）；
            #      909 ＝ 927 − 18（R15 删掉的 `[[]]` 空释义）—— **逐条对得上，不是凑的**。
            #    🔴 **什么会推翻这个常量**：再批准收一批日文版释义（那时连同 K24 一起重算），
            #      或把那 927 条撤掉（回到 0）。
            APPROVED_JA = 1_836
            if leaked != APPROVED_JA:
                mark = "🔴"
                red += 1
                print("   🔴 来自日文版/标着 lang='ja' 的释义有 %s 行，"
                      "而已批准的是 %s 行（2026-09-25 选项①）—— 多出来的要说清出处"
                      % (f(leaked), f(APPROVED_JA)))
            else:
                print("   ℹ️  来自日文版的释义 %s 行 ＝ 2026-09-25 批准的选项① "
                      "（927 原文 ＋ 909 译文，909＝927−18 条 R15 删掉的空释义）" % f(leaked))
            cap = len(real)      # 只为打印对齐；判据是上面那条结构检查
        elif cap is not None and len(real) > cap:
            mark = "🔴"
            red += 1
        print("%s %-18s 源头 %8s  缺 %8s (%5.1f%%)  其中词形不在库 %7s  ⇒ 真缺 %8s%s"
              % (mark, name, f(len(s)), f(len(miss)), pct, f(len(nw_miss)),
                 f(len(real)), "  上限 %s" % f(cap) if cap is not None else "  上限：见理由"))
        if a.show and (a.edition == name or (not a.edition and real)):
            for w, t in list(real)[:a.show]:
                print("      %-14s %s" % (w, t[:78]))
    print()
    for name, _p, _gz in SRC:
        cap, why = BUDGET[name]
        print("   %-18s %s" % (name, why))
    if a.mutate and run_mutations(have, src):
        raise SystemExit("\n🔴 变异验证没过 —— 这道闸逮不住它声称能逮的")
    if red:
        raise SystemExit("\n🔴 外锚闸：%d 个版超上限" % red)
    print("\n■ 外锚闸通过 ✓")


if __name__ == "__main__":
    main()
