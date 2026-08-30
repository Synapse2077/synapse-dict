#!/usr/bin/env python3
"""阶段 4b：跨版收割音标 → `pronunciation`。2026-08-29。

═══ 上限已实测（`probes/ipa_landing.py`，全量非抽样），验收线只能定在它以下 ═══
    缺音标词形 326,698（其中变形 326,511 = 99.94%）
    跨版并集能补 **180,303（55.2%）**，音标覆盖 20.7% → 64.5%
    剩 146,395 个只能靠 G2P 或留空 —— **G2P 决策见 `PT_PLAN` §四.2，本步不做**

    落点分布：fr 179,722（独有 173,744 = 并集的 96.4%）／ de 5,380（命中率 73.2%）
              pt 666 ／ es 599 ／ it 8 ／ en 0（建库主源已榨干）／ zh 0

🔴 **pt 不能走 fr 那招**：`forms` 带 ipa 在**七个源上全部是 0**（`pt-CONVENTIONS` §一 结论 1）。
   fr 靠从 lemma 的 forms 收割一次补了 387,826 条变位形音标，pt 一条都拿不到。

═══ 🔴 判据一：地区（region）═══
**同时看 `tags` 和 `raw_tags`** —— 第一版只查 `tags`，而葡语版/法语版把地区写在
`raw_tags` 里、`tags` 恒空，据此报过「法语版一条都没标地区」（真值 8,133 条）。

    葡语版  18.4% 带标记，用的是**巴西内部方言名**（`Carioca`/`Paulistana`/`Caipira`/
            `Gaúcha`/`Paranaense`），`(Portugal)` 只有 47 条
            ⇒ 方言名归 `pt-BR` + 原始标记进 `tags`（不丢）
    法语版  只有 1.0% 带标记，而且排头是 `États-Unis` 2,479、`Yangsan (Corée du Sud)` 553
            —— **那是录音地点不是方言标注**

═══ 🔴 判据二：法语版没有地区标记，改用**排他性音征**（2026-08-29 实测）═══
`[[cross-edition-harvest]]` 记的「法语版补的是 ipa_pt 欧葡」——
**偏向属实，但不是"仅"**：

    法语版 811,074 条音标，有音征的 228,297 (28.2%)
      → **欧葡 69.3% ／ 巴葡 30.7%**

⇒ 一律灌 `ipa_pt` 会把那 7 万条巴葡读音标成欧葡（「错比缺更伤权威」）。

音征是**音位对立**不是形状代理：

    `ɨ`           非重读央元音 —— **欧葡专有**（巴葡对应 /i/）
    `t͡ʃ` `d͡ʒ`  /ti/ /di/ 塞擦化 —— **巴葡专有**（欧葡是 /t/ /d/）

⚠️ **这把尺子先跑过正控**：在我们已知区分的 76,921 对 `ipa_br`/`ipa_pt` 上，
   有音征时判对率 **99.7% / 99.0%**。没跑正控的判据不许上（`[[llm-as-evaluator-discipline]]` ⑦）。
⚠️ 两者都有（56 条）或无音征（58.3 万）⇒ `region=NULL`。
   **判不出就说判不出** —— 同 `_src` 列写 unknown 的规矩，不猜。

⚠️ 我第一版的判据是「整串与 `ipa_br`/`ipa_pt` 比对」，报出「99.8% 两边都不等」——
   那是在量**我的比对方法**（法语版转写约定不同），不是量数据。
   `[[measure-landing-not-source]]` 同一形状当天第四次，这次在报结论前逮住了。

═══ 🔴 判据三：notation ═══
    `[…]` 定界 → `narrow`（音值式）      其余 → `phonemic`（音位式）
⚠️ **按定界符判，不按内容猜。** 阶段 4a 逮到的 3 条「一个字段装两个音标」
   （`/pĩ.tɨˈʎei̯.ɾɐ/ [pĩtˈʎeɾɐ]`）在这里正好各自归位。

═══ 🔴 判据四：排除 X-SAMPA 冒充 IPA ═══
葡语版实测 **132 条**标着 `SAMPA`（收尾单 C5；fr 那轮同形状 150 条）。
标记里出现 `SAMPA` 一律不收 —— 混进 IPA 列会让所有音标比对失真。

═══ 闸 ═══
① 落点核对：新增覆盖的词形数必须落在 `ipa_landing.py` 预测的 180,303 附近（**差多少报多少**）
② 不变量：无孤儿 / region 值域 / notation 值域 / 不含定界符 / 不含 SAMPA
③ 抽样反验：随机打印，人眼核 —— 4a 和 3b 各有一个缺陷是它逮到的、闸看不见

用法（在 pt/ 目录下）：
    python3 pipeline/harvest_pronunciation.py            # 干跑
    python3 pipeline/harvest_pronunciation.py --apply
    python3 pipeline/harvest_pronunciation.py --verify
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from intake_edition_words import EDITIONS, norm_apos   # noqa: E402

# 地区标记词表（判据只在 `region_of()` 一处）
BR = {"Brazil", "Brazilian", "brasileiro", "Brasil", "Brésil",
      "Carioca", "Paulistana", "Paulista", "Caipira", "Gaúcha", "Paranaense",
      "São Paulo", "Rio de Janeiro", "Região Sul"}
PT = {"Portugal", "European Portuguese", "português europeu",
      "Porto", "Coimbra", "Braga", "Lisbonne", "Lisboa", "Alentejo", "Azores", "Açores"}

# 排他性音征（见判据二）。⚠️ 值是**音位对立**，不是形状特征。
EU_ONLY = ("ɨ",)
BR_ONLY = ("t͡ʃ", "d͡ʒ", "tʃ", "dʒ")


def region_of(sound):
    """→ 'pt-BR' / 'pt-PT' / None。先看标记，标记判不出再看音征。"""
    marks = list(sound.get("tags") or []) + list(sound.get("raw_tags") or [])
    blob = " | ".join(marks)
    hit_br = any(k in blob for k in BR)
    hit_pt = any(k in blob for k in PT)
    if hit_br and not hit_pt:
        return "pt-BR"
    if hit_pt and not hit_br:
        return "pt-PT"
    # 标记判不出 → 音征（正控 99.7%/99.0%，见文件头判据二）
    v = sound.get("ipa") or ""
    e = any(x in v for x in EU_ONLY)
    b = any(x in v for x in BR_ONLY)
    if e and not b:
        return "pt-PT"
    if b and not e:
        return "pt-BR"
    return None                       # 判不出就说判不出


def is_sampa(sound):
    return any("SAMPA" in m for m in
               (list(sound.get("tags") or []) + list(sound.get("raw_tags") or [])))


# 🔴🔴 判据五（抽样反验逮到，闸看不见）：**各版的定界符约定四种全不一样**
#
#     fr   \…\  95%（法语维基自己的约定）  […] 5%
#     pt   /…/   77%   /…) 17% 🔴   /…] 4% 🔴   […] 1%
#     en   /…/   72%   […] 28%
#     de   […]  100%
#
# 第一版写的是 `raw.strip("/[]")` —— **不认反斜杠**，65 万条法语版音标会带着 `\…\`
# 灌进库，违反六语种统一的「DB 存裸」约定（`[[ipa-bare-storage-convention]]`）。
# 而闸只查 `LIKE '/%' OR LIKE '[%'`，**判据比它要描述的东西窄，一条都拦不住。**
#
# 葡语版那些不配对的更脏（已知坑，`[[dbtool-and-golden-tests]]` 记过 `pelúcia`）：
#     "/pe.'lu.sja/ (Região Sul)"        音标 + 散文地区注记
#     "// (Região Sul)"                  **空音标**
#     "/poʁ.tuˈɡe(j)s/ [poh.tuˈɡe(ɪ̯)s]"  音位式+音值式粘一起（同 4a 那 3 条）
#     "/gi.ˈnɛ bi.ˈsaw/."                尾巴多个句点
#     "/o.se\"a~.nU/"                     整条是 X-SAMPA（" 重音、~ 鼻化、U）
#
# ⇒ 判据改成**「取第一个成对定界的音标段」**（按含义：一个字段里第一个完整的音标），
#   而不是「剥掉首尾字符」（形状代理，遇到不配对就露馅）。
_SEG = re.compile(r"\\([^\\]+)\\|/([^/]+)/|\[([^\]]+)\]")
# X-SAMPA 的内容特征：ASCII 引号当重音号、`~` 当鼻化。真 IPA 用 `ˈ` `ˌ` 和组合符 `̃`。
_XSAMPA_CHARS = ('"', "'", "~")

# 🔴 **「DB 存裸」判据只许这一份**（`[[ipa-bare-storage-convention]]`）。
#    回归闸 C2 第一版自己抄了一遍、写成 SQLite 的 `GLOB '*[/[\]|]*'` ——
#    而 GLOB 字符类里 `]` 必须放最前面，那个式子解析成了别的东西 ⇒ **恒真的假绿**，
#    是**变异验证**逮到的（加回定界符它不报）。⇒ 抽出来，闸 import 它。
DELIMS = "/[]\\|"


def has_delim(v):
    return bool(v) and any(c in v for c in DELIMS)


def extract_ipa(raw):
    """→ (裸音标, notation) 或 (None, None)。判据见上面那段。"""
    m = _SEG.search(raw)
    if m:
        bs, sl, br = m.group(1), m.group(2), m.group(3)
        val = bs or sl or br
        notation = "narrow" if br is not None else "phonemic"
    elif any(c in raw for c in "/[]\\"):
        # 🔴 **含定界符却取不出成对的段 ⇒ 残缺数据，不许兜底。**
        #    `// (Região Sul)` 就是这一支：空音标 + 散文注记。
        #    第一版没有这个分支，它掉进了下面的"整条是裸音标"，
        #    于是 `// (Região Sul)` 会被当成一条音标存进去。
        return None, None
    else:
        # 一个定界符都没有 ⇒ 整条就是裸音标（部分版本这么给）
        val, notation = raw, "phonemic"
    val = (val or "").strip()
    if not val:
        return None, None                      # `// (Região Sul)` 这类空壳
    if any(c in val for c in _XSAMPA_CHARS):   # X-SAMPA 冒充 IPA，内容判不靠标签
        return None, "xsampa"
    # 🔴 **取出来的段本身必须是裸的。**
    #    源头会把维基链接、多个音标塞进同一对方括号里：
    #       '[Ajuda:Guia de pronúncia|/tɾɐ̃sˈtoʁ.nu…/ [tɾɐ̃sˈtoɦ.nu…/'
    #       '[ɐ.sɐj.ˈtaɾ/]'   ← de 版，方括号里混着一个游离的斜杠
    #    `[…]` 那一支会把整段连同内部的 `/` 一起取出来。
    #    ⚠️ 这 19 条是**拓宽后的闸**逮到的 —— 旧判据只查"以 / 或 [ 开头"，
    #      `'ɐ.sɐj.ˈtaɾ/'` 这种结尾带斜杠的一条都拦不住。拓宽当场回本。
    if any(c in val for c in "/[]\\|"):
        return None, None
    return val, notation


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def harvest(ids, have):
    """→ rows, stat。have = 已有的 (word_id, ipa, notation) 三元组集合。"""
    rows, stat = [], Counter()
    seen = set(have)
    for ed in ("fr", "de", "pt", "es", "it", "en", "zh"):
        path, need_filter = EDITIONS[ed]
        if not path.exists():
            stat["🔴 %s dump 缺失" % ed] += 1
            continue
        n0 = len(rows)
        with opener(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if need_filter and e.get("lang_code") != "pt":
                    continue
                w = norm_apos((e.get("word") or "").strip())
                wid = ids.get(w)
                if wid is None:
                    stat["%s·词形不在库里" % ed] += 1
                    continue
                pos_raw = e.get("pos") or ""
                for i, s in enumerate(e.get("sounds") or []):
                    raw = (s.get("ipa") or "").strip()
                    if not raw:
                        continue
                    if is_sampa(s):
                        stat["🔴 %s·标着 SAMPA（不收）" % ed] += 1
                        continue
                    ipa, notation = extract_ipa(raw)
                    if notation == "xsampa":
                        stat["🔴 %s·内容是 X-SAMPA（不收）" % ed] += 1
                        continue
                    if not ipa:
                        stat["%s·空音标（不收）" % ed] += 1
                        continue
                    key = (wid, ipa, notation)
                    if key in seen:
                        stat["%s·已有（跳过）" % ed] += 1
                        continue
                    seen.add(key)
                    tags = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
                    rows.append((wid, ipa, notation, region_of(s),
                                 json.dumps(tags, ensure_ascii=False) if tags else None,
                                 pos_raw or None, 0, "%s-edition" % ed,
                                 "kk-%s:%s:%s#%d" % (ed, w, pos_raw, i)))
                    stat["%s·新增" % ed] += 1
        stat["→ %s 小计" % ed] = len(rows) - n0
    return rows, stat


def verify(con, predicted=180303):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    cov = q("SELECT COUNT(DISTINCT word_id) FROM pronunciation")
    tot = q("SELECT COUNT(*) FROM dict")
    checks = [
        ("孤儿 pronunciation",
         q("SELECT count(*) FROM pronunciation p LEFT JOIN dict d ON d.id=p.word_id "
           "WHERE d.id IS NULL"), 0),
        ("region 值域（pt-BR/pt-PT/NULL 之外）",
         q("SELECT count(*) FROM pronunciation "
           "WHERE region IS NOT NULL AND region NOT IN ('pt-BR','pt-PT')"), 0),
        ("notation 值域（phonemic/narrow 之外）",
         q("SELECT count(*) FROM pronunciation "
           "WHERE notation NOT IN ('phonemic','narrow')"), 0),
        # 🔴 判据必须覆盖它要描述的东西（「存裸」），不是只列我想到的那两个符号。
        #    第一版只查 `/` 和 `[` 开头，而法语版用 `\…\` —— 65 万条一条都拦不住。
        ("🔴 ipa 里残留任何定界符（存裸约定）",
         sum(1 for (v,) in con.execute("SELECT ipa FROM pronunciation")
             if any(c in v for c in "/[]\\")), 0),
        ("🔴 ipa 里有 X-SAMPA 特征字符（\" ' ~）",
         sum(1 for (v,) in con.execute("SELECT ipa FROM pronunciation")
             if any(c in v for c in "\"'~")), 0),
        ("🔴 tags 里混进 SAMPA",
         q("SELECT count(*) FROM pronunciation WHERE tags LIKE '%SAMPA%'"), 0),
        ("ipa 为空", q("SELECT count(*) FROM pronunciation WHERE TRIM(ipa)=''"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-42s %10s  期望 %s" % ("✓" if good else "🔴", name,
                                            f"{got:,}", f"{want:,}"))
    print("\n   音标覆盖 %s / %s 词形 = %.1f%%（4a 之后是 85,104 = %.1f%%）"
          % (f"{cov:,}", f"{tot:,}", 100.0 * cov / tot, 100.0 * 85104 / tot))
    print("   ⚠️ 落点预测新增覆盖 %s，实际 %s（差多少报多少）"
          % (f"{predicted:,}", f"{cov - 85104:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if verify(con) else 1

    ids = {norm_apos(w): i for i, w in con.execute("SELECT id, word FROM dict")}
    have = {(w, i, n) for w, i, n in
            con.execute("SELECT word_id, ipa, notation FROM pronunciation")}
    print("■ 库内词形 %s ／ 已有音标行 %s" % (f"{len(ids):,}", f"{len(have):,}"))
    rows, stat = harvest(ids, have)
    for k in sorted(stat):
        print("   %-28s %10s" % (k, f"{stat[k]:,}"))
    reg = Counter(r[3] for r in rows)
    nota = Counter(r[2] for r in rows)
    print("\n   → 新增 %s 行" % f"{len(rows):,}")
    print("   region  pt-BR %s ／ pt-PT %s ／ NULL %s"
          % (f"{reg['pt-BR']:,}", f"{reg['pt-PT']:,}", f"{reg[None]:,}"))
    print("   notation phonemic %s ／ narrow %s"
          % (f"{nota['phonemic']:,}", f"{nota['narrow']:,}"))
    newly = len({r[0] for r in rows} - {w for w, _, _ in have})
    print("   → 新覆盖词形 %s（落点预测 180,303）" % f"{newly:,}")

    print("\n── 抽样 15 条 ──")
    import random
    random.seed(0)
    idx = {i: w for w, i in ids.items()}
    for r in random.sample(rows, min(15, len(rows))):
        print("   %-24s %-18s %-9s %-7s %s"
              % (idx.get(r[0], "?")[:24], r[1][:18], r[3] or "—", r[2], r[7]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    con.close()
    with dbtool.session("keep-v3-ipa-harvest", expect={"#pronunciation": len(rows)}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO pronunciation "
            "(word_id,ipa,notation,region,tags,pos,is_primary,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return 0 if verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)) else 1


if __name__ == "__main__":
    sys.exit(main())
