#!/usr/bin/env python3
"""阶段 4 —— 收割德语版音标 → `pronunciation`。2026-09-03。

═══ 上限已实测（`probes/ipa_landing.py`，七源 2.5 GB 全量非抽样）═══
缺音标 1,092,809，但**这个数不能当分母** —— 按「页面上是什么」分三层：

    ⭐ 有真义项 121,677   德语版补 114,254 = **93.9%**   ← 本步的目标
       只是变形 903,814   德语版补 761,698 = 84.3%       ← 顺带收，读者看不见
       空白页   67,318    **有意不补**（页面上除音标什么都没有，补了更像缺陷）

🔴 **只收德语版，六个外版一个不收。** 理由是相减出来的，不是偏好：
   七版并集在「有真义项」那层是 114,457，德语版一版 114,254 ——
   **其余六版加起来只多 203 个词形（0.17%）**。
   而法语版的德语音标质量明显更差（实测：`ˈɑː.xə.nə.ʁɪn` 用 `ɑ`，**`ɑ` 不是德语音位**；
   `-ʦiːt` 用废弃连字 `ʦ`；`'ɑːl.fɑŋ` 拿 ASCII 撇号冒充重音符；`-linge` 给 `lɪgə`，
   **`g` 应为 `ŋ`，这条是真错**）。
   ⇒ 为 203 个词形引入一整套归一 + 质量闸不划算。变形层要不要收法语版
     （10,486 / 903,814）等这一步做完再单独决定 —— 那是另一个问题。

⚠️ **2026-09-05（C41）：上面那句「六个外版一个不收」漏掉了第八个来源。**
   那 203 是「德语版之外的**六个外版**还能多补谁」，而**英文版德语切片不在那六版里**
   —— 它是我们**建库的源**，它给的音标七月就以 `dict.ipa` 躺在库里，
   只是阶段 8 换了读取路径之后读者看不见了。实测它还能补 12,847 个**有真义项**的词形。
   ⇒ `pronunciation` 现在有两个来源：`de-edition` ＋ `en-edition`
     （`fixes/fill_ipa_from_en.py`，复用本文件的四道过滤与 `REGION`）。
   🔴 教训：**落点度量的分母里漏掉了一个已经在库里的来源** ——
     我把「外版」和「建库源」当成两回事，而对音标层它们是同一类东西。

═══ 🔴 判据跟着数据走，pt 那套有三条搬不过来 ═══
① **notation 不能按定界符判。** pt 用「`[…]`→narrow，其余 phonemic」，
   而**德语版 131,501 条音标 100% 是 `[…]`** —— 那是这一版的行文约定，
   不是窄式标音的信号。照搬会把全库标成 narrow。
   ⇒ de 一律 `phonemic`；德语版**给不出**区分窄式/宽式的信号，判不出就不硬判。
② **`[…]` 本身是占位符**（`Subfamilia` → `"[…]"` ＝「这里没有音标」）。
   剥完定界符只剩省略号/空 ⇒ 丢弃。不排除就会灌进一批假音标。
③ **地区标记要重量。** 表结构注释写的「奥/瑞只占 0.13%」与我抽样看到的
   `Austrian German` 2.9% 差一个数量级 ⇒ 干跑时全量打印，看完再定 `region` 怎么填。

═══ 🔴 排除音节切分冒充音标 ═══
`[[it-display-layer-stage8]]`：意语版把**音节切分**当读音灌了进来
（`sudanese` → `su/da/né/se`，116 条还是 `is_primary`），三层数据的闸全绿、
真渲染出来才看见。判据按**含义**写不按长相写：
**剥掉分隔符后如果与词头本身逐字相同（忽略大小写与变音），那它是拼写不是读音。**

═══ 🔴 排除 X-SAMPA 冒充 IPA ═══
fr 那轮 150 条、pt 132 条（`[[criteria-narrower-than-you-think]]` A5）。
标记里出现 `SAMPA` 一律不收 —— 混进来会让所有音标比对失真。

═══ 存的尺子与比的尺子分开（`[[it-pronunciation-layer]]`）═══
存：剥定界符、NFC，**别的一律不动**（`[[ipa-bare-storage-convention]]`：
    六语种统一裸存，展示层加 `/…/`）。
比：去重时才做记法归一。**归一后的值绝不回写**——
    `[[criteria-from-meaning-not-form]]` 那条「用归一后的值判断、却存原值」我犯过两次。

用法（在 de/ 目录下）：
    python3 -u pipeline/harvest_pronunciation.py           # 干跑，只量不写
    python3 -u pipeline/harvest_pronunciation.py --apply
    python3 -u pipeline/harvest_pronunciation.py --verify
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402
from intake_edition_words import EDITIONS        # noqa: E402
# region 的登记值域在 C31 那里定的，**这里 import 不重写**（判据只许一份）。
from normalize_region import DOMAIN as REGION_DOMAIN   # noqa: E402

f = lambda n: format(n, ",")
SRC = "de-edition"

DELIM = "/[]\\"
SEP = re.compile(r"[-‐‑–·.·|/‧⋅  ​]")
# 🔴 **含 `…` 一律丢，不只是"整串只有省略号"。**
#    第一版写的是 `^[…\.\s]*$`（整串都是省略号才丢），实测漏掉 30 条：
#      `Saison → …zoːn`      源头只给了后半截
#      `Kakaopulver → kaˈkaːo…` / `…vɐ`   源头把复合词读音拆成两半、用 `…` 标续接
#      `EuPs → ˈ…`
#    读者看到 `…zoːn` 得不到任何信息 —— **半截音标是"错"不是"缺"**。
#    ⇒ 判据从"整串是不是占位符"改成"**这串能不能独立读**"。
ELLIPSIS = re.compile(r"…")
# 半截音标的第二种记号：源头用连字符标「前/后半截同上」。字符集与 `ipa_conventions.HYPH` 同。
HYPH = "-‐‑–"


def truncated(ipa, word):
    """→ 这条音标是不是「半截/占位符」。**判据只许这一份**，闸 import 它。

    🔴 **第三版（2026-09-05）**。前两版的历史见上面那段注释，第二版「含 `…` 一律丢」
       的理由是「这串能不能独立读」—— 对 `…zoːn`（源头只给了后半截）完全成立，
       但它**同时误杀了德语的分离式习语**：

           weder … noch        [ˈveːdɐ … nɔx]
           entweder … oder     [ˈɛntˌveːdɐ … ˈoːdɐ]
           sowohl … als auch   [zoˈvoːl … als ˈʔaʊ̯x]
           auf … hin           [aʊ̯f … hɪn]

       这些**能独立读**，`…` 对应的是**词形自己的空位**，不是截断。
       ⇒ 判据换成：**音标里的 `…` 合法，当且仅当词形本身也有 `…`。**
         这才是「省略号在这里是什么意思」，而不是「有没有省略号」。
       实测：德语版里被误杀 10 条（另 7 条是真半截 `EuPs → [ˈ…]`，照丢）。

    🔴 **第四版（2026-09-05，做 C41 时）**：省略号不是源头唯一的「接续」记号，
       **连字符是另一个**，而且量大得多。英文版给 `Svalbard` 四条读音：

           ˈsvaːlˌbart   ˈsʋaːlˌbaʁt   -ˌbaɐ̯t   -ˌbaːt

       后两条的 `-` 意思是「前半截同上、后半截读成这样」。单独摆到页面上就是
       **读者读不出任何东西的半截**，与 `…zoːn` 一模一样。实测 1,309 条
       （英文版 1,288 ＋ 德语版 21 —— **阶段 4 就漏了，C41 只是把它放大了 60 倍**）。
    ⚠️ 判据必须**按位置**配、不能按包含配：`…` 那条用「词形里有没有 `…`」够了，
       连字符不行 —— `USB-Stick` 词形中间就有连字符，按包含判会把 `-ˌʃtɪk` 放行。
       ⇒ **音标开头的连字符合法，当且仅当词形也以连字符开头**（结尾同理）。
       词缀条目（`-algie` → `-alˈɡiː`）因此照样收得进来。
    """
    w = word or ""
    if "…" in ipa and "…" not in w:
        return True
    if ipa[:1] in HYPH and w[:1] not in HYPH:
        return True
    if ipa[-1:] in HYPH and w[-1:] not in HYPH:
        return True
    return False
# 地区标记 → region 值。**只收真·地区**，录音人性别/语域/词形标记不进这一列。
# 🔴🔴 **值域是 C31 登记的那一份，不是 kaikki 原样。**
#    2026-09-05 之前这张表产的是 `at`/`ch`/`de`（kaikki 内部约定），而 C31
#    已经把**落库的行**统一成了 BCP-47（`de-AT`/`de-CH`/`de-DE`）。生成侧没跟着改
#    ⇒ C41 复用本表补英文版音标时，577 行当场把 C31 撤销了一半
#    （`[[replay-scripts-undo-fixes]]`）。现在这张表**直接产登记值域里的值**。
REGION = {
    "Austrian German": "de-AT", "Austria": "de-AT",
    "Swiss Standard German": "de-CH", "Switzerland": "de-CH",
    "Germany": "de-DE", "German": "de-DE",
    "North German": "de-north", "Northern German": "de-north",
    "South German": "de-south", "Southern German": "de-south",
    # ⭐ 2026-09-05（C41）：英文版用**连字符**写同一批地区名，德语版用空格。
    #    这四个是**在英文版落点集上全量数过的**（33 种标记逐条看完）：
    #    `Southern-Germany` 256／`Swiss` 4／`Northern-Germany` 3／`Austrian` 1。
    # 🔴 有意**不**收的：`Northern` 15／`Southern` 8／`Western` 6／`Bavaria` 6／
    #    `Westphalian` 1 —— 前三个单独出现时说不出是哪一国的北/南/西，
    #    后两个比值域细。**判不出就不硬判**，硬塞一个值＝拿「错」换「缺」。
    "Southern-Germany": "de-south", "Northern-Germany": "de-north",
    "Swiss": "de-CH", "Austrian": "de-AT",
}
# 🔴 **import 时就断言**，别等写完库让闸去发现。判据只许一份：值域在 C31 那里登记。
assert set(REGION.values()) <= REGION_DOMAIN, set(REGION.values()) - REGION_DOMAIN


def opener(p):
    p = Path(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def bare(v):
    """存的尺子：剥定界符 + NFC。**别的一律不动。**"""
    return unicodedata.normalize("NFC", (v or "").strip().strip(DELIM).strip())


def looks_like_spelling(ipa, word):
    """→ 这条"音标"其实是音节切分/拼写吗。

    判据按**含义**写：剥掉分隔符后与词头逐字相同（忽略大小写与变音）
    ⇒ 它没有携带任何读音信息，是拼写。
    """
    a = SEP.sub("", ipa)
    b = SEP.sub("", word)
    fold = lambda s: "".join(c for c in unicodedata.normalize("NFD", s.casefold())
                             if not unicodedata.combining(c))
    return bool(a) and fold(a) == fold(b)


def harvest(keep):
    """扫德语版 → (rows, stat, tagc)。rows = [(word, ipa, notation, region, tags, pos, idx)]"""
    path, _ = EDITIONS["de"]
    rows, stat, tagc = [], Counter(), Counter()
    # 差额记账：哪些词形**有 ipa 字段但被全部丢弃**。
    # 🔴 落点探针 `ipa_landing.py` 只看"有没有 ipa 字段"，不看内容 ⇒ 它把
    #    `[…]` 占位符也算成了覆盖。两个数不一致时**必须能逐词说清差在哪**，
    #    不能拿"大概是占位符吧"糊过去（`PITFALLS`：统计表里"跳过"那栏必须逐条看）。
    had_ipa, kept_word = set(), set()
    with opener(path) as fh:
        for line in fh:
            if '"sounds"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "de":
                continue
            w = e.get("word") or ""
            if w not in keep:
                stat["词形不在库里（阶段 3 的残差）"] += 1
                continue
            pos = e.get("pos") or None
            for i, s in enumerate(e.get("sounds") or []):
                raw = s.get("ipa")
                if not raw:
                    continue
                stat["源头 ipa 条数"] += 1
                had_ipa.add(w)
                tags = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
                for t in tags:
                    tagc[t] += 1
                if any("SAMPA" in t.upper() for t in tags):
                    stat["🔴 丢弃：X-SAMPA 冒充 IPA"] += 1
                    continue
                v = bare(raw)
                if not v or truncated(v, w):
                    stat["🔴 丢弃：含省略号（占位符或半截音标）"] += 1
                    continue
                if looks_like_spelling(v, w):
                    stat["🔴 丢弃：音节切分/拼写冒充音标"] += 1
                    continue
                reg = next((REGION[t] for t in tags if t in REGION), None)
                rows.append((w, v, "phonemic", reg,
                             json.dumps(tags, ensure_ascii=False) if tags else None,
                             pos, i))
                stat["收下"] += 1
                kept_word.add(w)
    return rows, stat, tagc, (had_ipa - kept_word)


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("pronunciation 行数 == 期望", q("SELECT count(*) FROM pronunciation"), expect["rows"]),
        ("孤儿（word_id 不在 dict）",
         q("SELECT count(*) FROM pronunciation p LEFT JOIN dict d ON d.id=p.word_id "
           "WHERE d.id IS NULL"), 0),
        # 🔴 **只查首尾。** 第一版查"含不含"，报红 17 条，**而那 17 条数据是对的**：
        #    `apaʁt[ə]ˈmɑ̃ː` 的 `[ə]` 是**可选央元音**的标准记法；
        #    `ˈliːtɐ/ˈlɪtɐ` 的 `/` 是**两读并列**。
        #    「含 `[` `/` 就是没剥干净」是形状代理，它不知道方括号在词中间是另一个意思
        #    （`[[criteria-from-meaning-not-form]]`）。裸存约定管的是**定界**，不是内容。
        ("🔴 首尾还带着定界符（六语种约定裸存）",
         q("SELECT count(*) FROM pronunciation "
           "WHERE substr(ipa,1,1) IN ('/','[',']','\\') "
           "   OR substr(ipa,-1,1) IN ('/','[',']','\\')"), 0),
        ("🔴 空音标", q("SELECT count(*) FROM pronunciation WHERE TRIM(ipa)=''"), 0),
        ("🔴 含省略号（半截音标读者读不出东西）",
         q("SELECT count(*) FROM pronunciation WHERE ipa GLOB '*…*'"), 0),
        ("notation 值域外", q("SELECT count(*) FROM pronunciation "
                            "WHERE notation NOT IN ('phonemic','narrow')"), 0),
        # 🔴 2026-09-05 改：原来在这里**手抄了一遍值域**，而 C31 之后那份抄本就过期了
        #    —— 它列的是 kaikki 原样值，库里已经是 BCP-47。从 C31 到今天没人跑过这道闸，
        #    所以它红着也没人看见（**没人跑的闸等于没有闸**）。⇒ 改成 import 登记表。
        ("region 值域外（值域在 C31 `normalize_region.DOMAIN` 登记）",
         q("SELECT count(*) FROM pronunciation WHERE region IS NOT NULL AND region NOT IN (%s)"
           % ",".join("'%s'" % v for v in sorted(REGION_DOMAIN))), 0),
        # 🔴 2026-09-05 改：原来写死 `src<>'de-edition'` 应为 0。
        #    那条断言把「**本步**只写德语版」写成了「**这张表**只有德语版」——
        #    来源名回答的是「这条数据是谁给的」，回答不了「这一层是谁写的」。
        #    C41 补进英文版音标（`fixes/fill_ipa_from_en.py`）那一刻它就会红，
        #    而**数据是对的**。⇒ 换成值域断言；「本步只写德语版」由那一步自己的反向闸守。
        ("src 值域外（只许 de-edition / en-edition）",
         q("SELECT count(*) FROM pronunciation WHERE src NOT IN ('de-edition','en-edition')"), 0),
        # 🔴 表上的 UNIQUE 因 entry_id 恒 NULL 而不生效，这里必须自己查
        ("🔴 重复行（同词形同词性同音标）",
         q("SELECT count(*) FROM (SELECT word_id,ipa,notation,COALESCE(pos,'') FROM pronunciation "
           "GROUP BY 1,2,3,4 HAVING count(*)>1)"), 0),
        ("🔴 一个 (词形,词性) 有多条 is_primary",
         q("SELECT count(*) FROM (SELECT word_id,COALESCE(pos,'') FROM pronunciation "
           "WHERE is_primary=1 GROUP BY 1,2 HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        n = con.execute("SELECT count(*) FROM pronunciation").fetchone()[0]
        return 0 if gate2(con, {"rows": n}) else 1

    words = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    miss_sense = {w for (w,) in con.execute(
        "SELECT d.word FROM dict d WHERE (d.ipa IS NULL OR d.ipa='')"
        "  AND EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)")}
    miss_infl = {w for (w,) in con.execute(
        "SELECT d.word FROM dict d WHERE (d.ipa IS NULL OR d.ipa='')"
        "  AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
        "  AND EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)")}
    blank = {w for (w,) in con.execute(
        "SELECT d.word FROM dict d WHERE (d.ipa IS NULL OR d.ipa='')"
        "  AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)"
        "  AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)")}
    print("■ 库内词形 %s ／ 缺音标：有真义项 %s ・ 只是变形 %s ・ 空白页 %s（不补）"
          % (f(len(words)), f(len(miss_sense)), f(len(miss_infl)), f(len(blank))))

    print("\n■ 扫德语版…")
    rows, stat, tagc, all_dropped = harvest(set(words))
    for k, v in stat.most_common():
        print("   %-40s %s" % (k, f(v)))

    print("\n■ 地区标记全量分布（决定 region 怎么填，不靠抽样）")
    for k, v in tagc.most_common(14):
        print("   %-34s %8s %s" % (k[:34], f(v), "← 进 region=" + REGION[k] if k in REGION else ""))
    n_reg = sum(1 for r in rows if r[3])
    print("   ⇒ 收下的 %s 条里，判得出地区的 %s（%.2f%%）"
          % (f(len(rows)), f(n_reg), 100.0 * n_reg / max(len(rows), 1)))

    print("\n■ 差额记账：有 ipa 字段、但内容全被丢弃的词形 %s" % f(len(all_dropped)))
    print("   其中落在⭐有真义项缺口里的 %s  ← 落点探针把它们算成了覆盖，实际补不上"
          % f(len(all_dropped & miss_sense)))
    print("   其中落在只是变形缺口里的   %s" % f(len(all_dropped & miss_infl)))

    covered = {r[0] for r in rows}
    print("\n■ 落点（这一步真正补上了谁）")
    print("   ⭐ 有真义项的缺口   %s / %s = %.1f%%"
          % (f(len(covered & miss_sense)), f(len(miss_sense)),
             100.0 * len(covered & miss_sense) / max(len(miss_sense), 1)))
    print("      只是变形的缺口   %s / %s = %.1f%%"
          % (f(len(covered & miss_infl)), f(len(miss_infl)),
             100.0 * len(covered & miss_infl) / max(len(miss_infl), 1)))
    print("      空白页（不补）   %s  ← 收下了但页面上没有别的内容"
          % f(len(covered & blank)))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    # 🔴 **is_primary 必须在去重之后、按落库行算**，不能按源头下标算。
    #    第一版按 `(词形, 词性)` 取最小 `sounds` 下标 ⇒ **3,218 组重复首选**：
    #    同一个 (词形, 词性) 可以来自**多个词条**（不同词源），
    #    `-el [suffix]` 的两个词条各有自己的 `sounds[0]`，两个 0 并列都被判成首选。
    #    ⇒ 改成扫一遍落库行、每个 (word_id, pos) 只给**第一条**。
    # 🔴 **必须在 Python 里去重，不能靠 `INSERT OR IGNORE` + UNIQUE**：
    #    表上的 `UNIQUE(word_id, entry_id, ipa, notation)` 里 `entry_id` 本步恒为 NULL，
    #    而 **SQLite 的 UNIQUE 认为 NULL 彼此不相等** ⇒ 约束一次都不会触发，
    #    同一个 (词形, 音标) 在源头出现两次就会进去两行，页面上并排显示两个一样的音标。
    #    ⚠️ 这类「约束看着在、其实没生效」正是 `[[fix-regression-and-gate]]` 的形状：
    #      闸绿、数据错。⇒ 去重判据写在这里一份，闸①单独再查一次落点。
    seen, primary, out = set(), set(), []
    for w, v, nt, reg, tg, pos, i in rows:
        k = (words[w], v, nt, pos)
        if k in seen:
            continue
        seen.add(k)
        pk = (words[w], pos)
        is_pri = 0 if pk in primary else 1
        primary.add(pk)
        out.append((words[w], None, v, nt, reg, tg, pos, is_pri, SRC,
                    "kk-de:%s:%s#%d" % (w, pos or "", i)))
    print("■ 源头 %s 条 → 去重后 %s 条（同词形同词性同音标重复出现 %s 次）"
          % (f(len(rows)), f(len(out)), f(len(rows) - len(out))))

    n_before = con.execute("SELECT count(*) FROM pronunciation").fetchone()[0]
    con.close()
    print("\n■ 将写入 pronunciation %s 行" % f(len(out)))
    with dbtool.session("keep-v3-4-pron-de", expect={"#pronunciation": len(out)}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO pronunciation "
            "(word_id,entry_id,ipa,notation,region,tags,pos,is_primary,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", out)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n_after = con.execute("SELECT count(*) FROM pronunciation").fetchone()[0]
    ok = gate2(con, {"rows": n_after})
    print("\n%s（新增 %s，源头 %s，差额是 UNIQUE 去重）"
          % ("✓ 闸②全过" if ok else "🔴 有闸未通过", f(n_after - n_before), f(len(out))))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
