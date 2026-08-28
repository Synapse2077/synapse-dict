#!/usr/bin/env python3
"""读音行里混进了**不属于这个词**的东西 —— 两族。2026-08-28（第二轮外审导材料时看见的）。

═══ 怎么发现的 ═══
不是闸逮到的，是我在导第二轮外审材料时**读渲染成品**看见的：

    gaz   读音表里躺着 `[dy ɡaz]`（France (Paris)）和 `[lə ɡas]`（Avignon）
                              ↑↑ 「du gaz」「le gaz」—— 那是**录音里说的整个短语**

法文版的窄式标音有相当一部分是从 Commons 录音转写来的，录音者念的是
「une photographie」「un pays」，转写就把限定词一起写进了这个词的读音行。
`[[it-display-layer-stage8]]`：**渲染出来才看得见** —— 三层数据的闸全绿。

═══ 🔴 第一版判据宽了 6 倍，是抽样打回来的 ═══
    v1  「单词词条但音标含空格」            → **998** 条
读了 45 条，**绝大多数是对的**：缩写和数字的读音本来就是多个词。

    URSS   y ɛ.ʁ‿ɛ.s‿ɛs        ✅      2FN    dø.zjɛm fɔʁm nɔʁ.mal  ✅
    A48    a ka.ʁɑ̃.tɥit        ✅      â      ɑ ak.sɑ̃ siʁ.kɔ̃.flɛks ✅

    v2  「首词是限定词」                    → 240 条（仍含假阳）
    v3  ＋五道负控                          → **130** 条
`[[criteria-narrower-than-you-think]]`：判据比它要描述的东西更宽，形状每次都一样。

⭐ **五道负控全部来自 v2 误判过的真数据**（`[[criteria-from-meaning-not-form]]`：
   负控用例 ＝ 我上一版判据误杀过的数据）：

    Lenôtre    lə notʁ            词形**本身**以「Le」开头 ⇒ `lə` 是它的第一个音节
    Debruyne   də bʁœjn           同上（De-）
    amha       a mɔ̃.n‿œ̃.bl‿a.vi  网络缩写，读音就是「à mon humble avis」整句
    montrer    mɔ̃ .tʁe           空格误打成了音节点，剥掉就成了 `.tʁe`
    un(e)      ɛ̃ yn              读作「un ou une」，`ɛ̃` 是正文

═══ 家族② 是我自己上一个修复留下的 ═══
`mark_liaison_readings.py` 对前导连诵符那一条做了**两件互相矛盾**的事：
剥掉 `‿`（因为那是连**进来**的音，不属于这个词），**同时**标 `context='liaison'`。
剥完之后它就是这个词的普通读音了，而 `Haut-Pyrénéens` 只有这一条读音、还是主读音
⇒ 页头印着「/o.pi.ʁe.neɛ̃/ 连诵」，等于告诉读者这个词唯一的读音是个连诵形。

规模 1 条。⭐ 值钱的不是这 1 条，是**不变量**：`context='liaison'` ⇒ 音标里必须有 `‿`。
已加进回归闸 F6（`[[lesson-must-become-mechanism]]`：教训的交付物是一道会自己响的闸）。

═══ 怎么修 ═══
家族①**剥掉限定词、保留这一行** —— 它是真的地区变体（`lə ʃɒ` 是魁北克的 /ʃɒ/），
删掉就把地区信息一起丢了。剥完与同词同 notation 的既有行撞 UNIQUE ⇒ 那才删。
家族②清掉 `context`，音标不动。

用法（在 fr/ 目录下）：
    python3 -u fixes/clean_reading_intruders.py            # 只报数
    python3 -u fixes/clean_reading_intruders.py --apply
    python3 -u fixes/clean_reading_intruders.py --mutate
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402

f = lambda n: format(n, ",")
LINK = "‿"

# 限定词/介词的**音** → 它的**正字法形式**。右边那一列是负控用的：
# 词形本身就以它开头时（Lenôtre / Debruyne），那不是闯入者，是第一个音节。
DET = {"lə": "le", "la": "la", "le": "les", "ly": "lu", "lo": "lo",
       "dy": "du", "də": "de", "de": "de", "yn": "une", "œ̃": "un", "ɛ̃": "un",
       "ø": "eux", "se": "ces", "sɛ": "ces", "ma": "ma", "mɔ̃": "mon",
       "tɔ̃": "ton", "sɔ̃": "son", "o": "au", "ɔ": "au", "a": "à",
       "o.z": "aux", "le.z": "les", "de.z": "des"}


def ordinary(w):
    """这是不是一个**普通法语词**（而不是缩写／字母名／数字／多词条目）。

    缩写和数字的读音天然是多个词（`URSS` = 「u erre esse esse」），
    对它们「首词是限定词」根本不成立判据。
    """
    return (len(w) >= 2 and not re.search(r"[\s\-\d]", w)
            and w[1:] == w[1:].lower() and w[1:] != w[1:].upper())


def intruder(word, ipa, is_primary):
    """判据本体 —— **写入侧与闸共用这一份**（`[[fix-regression-and-gate]]`）。

    「这一行的开头多出了一个不属于这个词的限定词」。
    """
    t = ipa.split(" ")
    if len(t) != 2 or t[0] not in DET:
        return None                       # 不是「限定词 + 一块」的形状
    if is_primary:
        return None                       # 负控：主读音里这一族全是缩写/姓氏，见文件头
    if not ordinary(word):
        return None                       # 负控：URSS / A48 / à
    if t[1].startswith("."):
        return None                       # 负控：montrer `mɔ̃ .tʁe` 是空格误打
    if word.lower().startswith(DET[t[0]]):
        return None                       # 负控：Lenôtre / Debruyne / un(e)
    return t[1]


def merge_tags(a, b):
    """两行的源标签求并集，**保序去重**。合并撞行时用。"""
    out = []
    for s in (a, b):
        try:
            for x in json.loads(s) if s else []:
                if x not in out:
                    out.append(x)
        except ValueError:
            pass
    return json.dumps(out, ensure_ascii=False) if out else None


def plan(con):
    det, mislabel = [], []
    for pid, wid, w, ipa, nota, pri, reg, tags in con.execute(
            "SELECT p.id, p.word_id, d.word, p.ipa, p.notation, p.is_primary, p.region, p.tags "
            "FROM pronunciation p JOIN dict d ON d.id=p.word_id WHERE instr(p.ipa,' ')>0"):
        new = intruder(w, ipa, pri)
        if new:
            dup = con.execute(
                "SELECT id, region, tags FROM pronunciation "
                "WHERE word_id=? AND ipa=? AND notation=? AND id<>?",
                (wid, new, nota, pid)).fetchone()
            # 🔴 撞 UNIQUE 就直接删会**把地区证言一起丢掉**：`mot` 的 `lə mɔ` 是
            #    布拉班特瓦隆的录音，幸存那行是洛桑的。20 条撞行的地区与幸存行不同。
            #    ⇒ 幸存行地区为空时，把地区与源标签**搬过去**再删；两边都有地区
            #    则确实存不下（UNIQUE 是 word_id+ipa+notation），据实记 loss。
            adopt = None
            if dup and not dup[1] and reg:
                adopt = (dup[0], reg, merge_tags(dup[2], tags))
            det.append((pid, w, ipa, new, dup[0] if dup else None, adopt,
                        bool(dup and dup[1] and reg and dup[1] != reg)))
    for pid, w, ipa in con.execute(
            "SELECT p.id, d.word, p.ipa FROM pronunciation p JOIN dict d ON d.id=p.word_id "
            "WHERE p.context='liaison'"):
        if LINK not in ipa:
            mislabel.append((pid, w, ipa))
    return det, mislabel


def gates(con, det, mislabel):
    print("\n═══ 闸 ═══")
    ok = True

    def g(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-56s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))

    g("① 主读音一条都没被圈进来（缩写族全在那里）",
      sum(1 for d in det if con.execute(
          "SELECT is_primary FROM pronunciation WHERE id=?", (d[0],)).fetchone()[0]), 0)
    g("② 剥完不许留下空串或以音节点开头的残串",
      sum(1 for d in det if not d[3] or d[3].startswith(".")), 0)
    g("③ 剥完的音标里不再有空格", sum(1 for d in det if " " in d[3]), 0)
    g("④ 家族② 全部确实不含连诵符", sum(1 for m in mislabel if LINK in m[2]), 0)
    # ⑤ 幂等：剥完之后再用同一判据查一遍，一条都不该再中
    g("⑤ 幂等（剥完再查一遍，不该再中）",
      sum(1 for d in det if intruder(d[1], d[3], 0)), 0)
    return ok


def mutate():
    print("═══ 变异验证：判据本体 ═══")
    cases = [
        ("🔴 gaz 的 `du gaz`", intruder("gaz", "dy ɡaz", 0), "ɡaz"),
        ("🔴 photographie 的 `une photographie`",
         intruder("photographie", "yn fɔ.tɔ.ɡʁa.fi", 0), "fɔ.tɔ.ɡʁa.fi"),
        ("🔴 France 的 `la France`", intruder("France", "la fʁãːs", 0), "fʁãːs"),
        ("负控 Lenôtre（词形本身以 Le 开头）", intruder("Lenôtre", "lə notʁ", 0), None),
        ("负控 Debruyne（同上，De-）", intruder("Debruyne", "də bʁœjn", 0), None),
        ("负控 montrer（空格误打成音节点）", intruder("montrer", "mɔ̃ .tʁe", 0), None),
        ("负控 un(e)（读作「un ou une」）", intruder("un(e)", "ɛ̃ yn", 0), None),
        ("负控 URSS（缩写，读音本来就是多个词）",
         intruder("URSS", "y ɛ.ʁ‿ɛ.s‿ɛs", 1), None),
        ("负控 A48（含数字）", intruder("A48", "a ka.ʁɑ̃.tɥit", 1), None),
        ("负控 amha（网络缩写，读音是整句）",
         intruder("amha", "a mɔ̃.n‿œ̃.bl‿a.vi", 1), None),
        ("负控 hiérophore（首块不是限定词，是音节）",
         intruder("hiérophore", "je.ʁɔ fɔʁ", 0), None),
        ("负控 neuf（`un char neuf`，三块 ⇒ 整句转写，另记）",
         intruder("neuf", "œ̃ ʃɑɔ̯ʁ nø", 0), None),
        ("负控 普通单块音标", intruder("maison", "mɛ.zɔ̃", 0), None),
    ]
    ok = 0
    for name, got, want in cases:
        good = got == want
        ok += good
        print("   %s %-46s → %s" % ("✅" if good else "🔴", name, got))
    print("\n   变异 %d/%d" % (ok, len(cases)))
    return ok == len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    det, mislabel = plan(con)
    dup = sum(1 for d in det if d[4])
    adopt = sum(1 for d in det if d[5])
    lost = sum(1 for d in det if d[6])
    print("■ 家族① 前导限定词  %s 条（剥掉 %s · 与既有行撞 UNIQUE ⇒ 删 %s）"
          % (f(len(det)), f(len(det) - dup), f(dup)))
    print("   撞行里：地区搬到幸存行 %s · 两边都有地区、存不下 %s" % (f(adopt), f(lost)))
    for pid, w, old, new, d, ad, ls in det[:12]:
        print("      【%s】%s → %s%s" % (w, old, new, "  （撞行 ⇒ 删）" if d else ""))
    print("      …" if len(det) > 12 else "")
    print("■ 家族② 剥了前导连诵符却仍标 liaison  %s 条" % f(len(mislabel)))
    for pid, w, ipa in mislabel:
        print("      【%s】%s  ⇒ 清掉 context" % (w, ipa))
    ok = gates(con, det, mislabel)
    con.close()
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    # 🔴 `expect` 必须声明**行数变化**：撞 UNIQUE 的那 53 条是删行。
    #    第一次跑我写了 `expect={}`，dbtool 当场拦住「未声明的表 pronunciation
    #    行数变了 -53 —— 动到了不该动的表」。那道闸拦对了：删行和改字段是两回事，
    #    「我只是改了几个音标」和「我删了 53 行」必须由我显式说出来。
    with dbtool.session("keep-v3-reading-intruders",
                        expect={"#pronunciation": -dup}) as s:
        for pid, w, old, new, d, ad, ls in det:
            if ad:
                s.execute("UPDATE pronunciation SET region=?, tags=? WHERE id=?",
                          (ad[1], ad[2], ad[0]))
            if d:
                s.execute("DELETE FROM pronunciation WHERE id=?", (pid,))
            else:
                s.execute("UPDATE pronunciation SET ipa=? WHERE id=?", (new, pid))
        s.executemany("UPDATE pronunciation SET context=NULL WHERE id=?",
                      [(m[0],) for m in mislabel])
    print("✓ 剥 %s 条 · 删 %s 条（地区搬走 %s）· 清 context %s 条"
          % (f(len(det) - dup), f(dup), f(adopt), f(len(mislabel))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
