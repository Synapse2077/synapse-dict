#!/usr/bin/env python3
"""族H：重音符不在音节开头。2026-08-30。

═══ 外审逮到的，我四道闸一条都没响 ═══
两家四版点了同一批：`bola /bˈɔlɐ/`、`magoado /mɐgwˈadu/`、`feriar /feɾjˈa/`、
`metias /metʃˈijəs/`。形状完全一样 —— **重音符夹在声母和韵核之间**，
而 IPA 的约定是重音符放在**整个音节前面**（`ˈbɔ.lɐ`）。

不是"版本约定不同"：**fr 版内部就不一致**，同一个 `português` 它既给
`poɾ.tu.ˈgeʃ`（对）又给 `poɾ.tu.gˈeʃ`（错）。

🔴🔴 **第一版判据差点毁掉 34.7 万条正确的音标。**
   我写的是「重音符必须紧跟在 `.` 后面或串首」，一跑 900,819 条，逐条看当场露馅：

       teˈzaw.ɾus  →  ˈtezaw.ɾus     ← 把对的改错了

   根因：**`ˈ` 本身就是音节分界**，标准 IPA 里有了 `ˈ` 就不再写 `.`。
   我把「分界」窄化成了「`.`」这一个符号 —— 又一次判据比它描述的东西窄。

⇒ **正确判据按含义写：每个音节必须有元音核。**
   按 `.` / `ˈ` / `ˌ` 切开后，如果重音符前那一段**没有元音**，
   说明那几个辅音是后一个音节的声母，重音符该在它们前面。

       bˈɔ.lɐ      → 段 `b`（无元音）⇒ 移  → ˈbɔ.lɐ
       teˈzaw.ɾus  → 段 `te`（有元音）⇒ 不动
       juːˌɛfˈaɪ   → 段 `ɛf`（有元音）⇒ 不动   ← 英语缩写，第一版会改坏
       pi.awˈi     → 段 `aw`（有元音）⇒ 不动   ← `w` 是前一音节的韵尾

⚠️ **fail-safe**：那一段还必须**全部由辅音符号构成**才移。
   否则 `ˈde ˈẽ.ne. ˈa`（DNA，段是一个空格）和 `-ˈsi.dɐ`（词缀，段是连字符）
   会被当成"无元音的声母"。认不出的字符一律不动 —— 宁可漏不可错。

⭐ **负控就是上一版判据误杀过的数据**（`[[criteria-from-meaning-not-form]]` 那条）：
   14 条用例里 6 条是"必须不变"，全部来自第一版的误伤。

用法（在 pt/ 目录下）：
    python3 fixes/fix_stress_position.py            # 干跑 + 自检
    python3 fixes/fix_stress_position.py --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 元音核（含鼻化预组合字符）。判据只问"这一段里有没有元音"。
VOWELS = set("aeiouɐɛɔəɨɪʊʌæyøœɵɤɯɑɒʏüöäãẽĩõũỹáéíóúâêôàèìòùåɜɘʉəɚɩǝεαä")
# 辅音符号 + 允许的附加符号。**只有整段都由这些字符构成时才允许左移**（fail-safe）。
CONSON = set("pbtdkgɡkqʔfvszʃʒʂʐçʝxɣχʁħhɦmnɲŋɴɱlʎɫʟɾrɽɹɻʀjwʋɰθðβɸʈɖcɟɕʑʧʤʦʣɬʃ"
             "ŁłRZSDFLMXAIOEPJqŋʈɗƀđǥȷᴣʲʷʰˡⁿ")
MODIF = set("͡‿̯̪̥̝̞̻̺̠̩̈̽̄́͂˜ːʰʲʷⁿˡ")
BOUND = re.compile(r"([.ˈˌ])")


def fix(ipa):
    """重音符左移到它所在音节的开头。判据：音节必须有元音核。"""
    parts = BOUND.split(ipa)
    segs, seps = parts[0::2], parts[1::2]
    for _ in range(8):
        moved = False
        for k, sep in enumerate(seps):
            if sep not in "ˈˌ" or not segs[k]:
                continue
            if any(c in VOWELS for c in segs[k]):
                continue
            if not all(c in CONSON or c in MODIF for c in segs[k]):
                continue                                  # fail-safe：认不出就不动
            if k > 0 and seps[k - 1] in "ˈˌ":
                continue                                  # 前面已是重音符，不再左移
            # 🔴 缺陷的定义是「重音符夹在**声母和韵核**之间」⇒ 韵核必须紧跟在它后面。
            #    不加这条会改坏两类真音节（欧葡里 i/u 弱化成的 j/w **是韵核**）：
            #      ɐɾ.kjˈtɛk.tu  `kj` 是「qui」弱化后的音节，不是声母簇
            #      a.lˈkɔ.wɔl    `l` 是前一音节的韵尾，源头的 `.` 本来就点错了
            #    两类的共同形状是「ˈ 后面不是元音」——那说明 ˈ 不在声母与韵核之间。
            if not segs[k + 1] or segs[k + 1][0] not in VOWELS:
                continue
            segs[k + 1] = segs[k] + segs[k + 1]
            segs[k] = ""
            moved = True
        if not moved:
            break
    return "".join(s + (seps[k] if k < len(seps) else "") for k, s in enumerate(segs))


# ⭐ 用例里 6 条是**负控** —— 全部来自第一版判据误伤过的真实数据。
CASES = [
    ("bˈɔ.lɐ", "ˈbɔ.lɐ"), ("fɐ.lˈaɾ", "fɐ.ˈlaɾ"), ("mɐ.gwˈa.du", "mɐ.ˈgwa.du"),
    ("poɾ.tu.gˈeʃ", "poɾ.tu.ˈgeʃ"), ("me.tʃˈi.jəs", "me.ˈtʃi.jəs"),
    ("fe.ɾjˈaɾ", "fe.ˈɾjaɾ"), ("mˈɛ.di.ku", "ˈmɛ.di.ku"), ("ʒɐ.nˈɛ.lɐ", "ʒɐ.ˈnɛ.lɐ"),
    # ── 负控：必须一个字符都不变 ──
    ("teˈzaw.ɾus", "teˈzaw.ɾus"),          # ˈ 本身就是音节分界
    ("juːˌɛfˈaɪ", "juːˌɛfˈaɪ"),            # ɛf 有元音，f 是韵尾
    ("pi.awˈi", "pi.awˈi"),                # w 是前一音节的韵尾
    ("aˈba.dɐ", "aˈba.dɐ"), ("ɐbˈsisɐ", "ɐbˈsisɐ"), ("ˈka.zɐ", "ˈka.zɐ"),
    ("ˈde ˈẽ.ne. ˈa", "ˈde ˈẽ.ne. ˈa"),    # DNA，段是空格
    ("-ˈsi.dɐ", "-ˈsi.dɐ"),                # 词缀，段是连字符
    ("kõ.pu.tɐ.ˈdoɾ", "kõ.pu.tɐ.ˈdoɾ"),
    ("ɐɾ.kjˈtɛk.tu", "ɐɾ.kjˈtɛk.tu"),      # kj 是弱化后的真音节，j 作韵核
    ("a.lˈkɔ.wɔl", "a.lˈkɔ.wɔl"),          # l 是前一音节韵尾，源头的 `.` 点错了
    ("dɨ.ljˈɾɐ̃w̃", "dɨ.ljˈɾɐ̃w̃"),
    ("e.xˈsɛp.tu", "e.xˈsɛp.tu"),
    ("plu.vjˈɔ.me.tɾu", "plu.ˈvjɔ.me.tɾu"),  # 对照：ˈ 后是元音 ⇒ 该移
    ("fɜːst ˈpɜːsn ˈʃuː.tɐ", "fɜːst ˈpɜːsn ˈʃuː.tɐ"),
]


def selftest():
    bad = [(a, fix(a), w) for a, w in CASES if fix(a) != w]
    for a, w in CASES:
        g = fix(a)
        print("   %s %-24s → %-24s%s" % ("✅" if g == w else "🔴", a, g,
                                         "" if g == w else "  期望 " + w))
    return bad


def main(a):
    print("■ 判据自检（%d 例，其中 %d 例负控）" % (len(CASES), sum(1 for x, y in CASES if x == y)))
    bad = selftest()
    if bad:
        print("🔴 自检不过，不动库")
        return 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("SELECT p.id, d.word, p.ipa, p.src FROM pronunciation p "
                       "JOIN dict d ON d.id=p.word_id").fetchall()
    ch = [(i, w, o, fix(o), s) for i, w, o, s in rows if fix(o) != o]
    f = lambda n: format(n, ",")
    print("\n■ 重音符不在音节开头：%s / %s（%.1f%%）"
          % (f(len(ch)), f(len(rows)), len(ch) * 100 / len(rows)))
    print("   按来源：%s" % collections.Counter(s for *_x, s in ch).most_common())
    for i, w, o, n, s in ch[:10]:
        print("     %-18s %-24s → %-24s %s" % (w[:18], o, n, s))
    # 不变量：只许动 ˈ/ˌ 的位置，其余字符一个不许变
    for _i, w, o, n, _s in ch:
        if sorted(o) != sorted(n):
            print("🔴 %s：改动不只是移位（字符集变了）%r → %r" % (w, o, n))
            return 1
    print("   ✓ 不变量：每一条改动都只是 ˈ/ˌ 移位，其余字符一个没变")
    # 🔴 移位后会和同词已有的**正确**读音撞 `UNIQUE(word_id, ipa, notation)`
    #    —— 这不是意外，是这个缺陷的直接证据：库里同一个词同时躺着错位版和正确版
    #    （`frei` 既有 `fɾˈej` 又有 `ˈfɾej`）。跟族G 同一个形状：**修对了才看得见重复**。
    #    合并时**不能随便留第一条** —— 各行的 region / pos / is_primary / tags 不一样。
    full = con.execute("SELECT id, word_id, ipa, notation, region, pos, is_primary, tags "
                       "FROM pronunciation").fetchall()
    newipa = {r[0]: fix(r[2]) for r in full}
    groups = collections.defaultdict(list)
    for r in full:
        groups[(r[1], newipa[r[0]], r[3])].append(r)
    drop, lost = [], 0
    for _k, rs in groups.items():
        if len(rs) == 1:
            continue
        # 信息更全的留下：is_primary → 有 region → 有 pos → 有 tags → id 最小
        rs.sort(key=lambda r: (-r[6], r[4] is None, r[5] is None, r[7] is None, r[0]))
        drop.extend(r[0] for r in rs[1:])
        if (rs[0][4] is None and any(r[4] for r in rs[1:])) or \
           (rs[0][6] == 0 and any(r[6] for r in rs[1:])):
            lost += 1
    print("   ■ 移位后重复、需合并：%s 行" % f(len(drop)))
    print("   ■ 负控 —— 留下的行丢了 region 或 is_primary：%d（必须是 0）" % lost)
    if lost:
        return 1
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    dropped = set(drop)
    with dbtool.session("fix-pt-stress-position",
                        expect={"#pronunciation": -len(drop)}) as s:
        s.executemany("DELETE FROM pronunciation WHERE id=?", [(i,) for i in drop])
        s.executemany("UPDATE pronunciation SET ipa=? WHERE id=?",
                      [(n, i) for i, _w, _o, n, _s in ch if i not in dropped])
    left = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True).execute(
        "SELECT ipa FROM pronunciation").fetchall()
    n_left = sum(1 for (v,) in left if fix(v) != v)
    print("\n✓ 改 %s 条；剩余不在音节开头的 %d（必须是 0）" % (f(len(ch)), n_left))
    return 1 if n_left else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
