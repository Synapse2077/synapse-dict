#!/usr/bin/env python3
"""es 音标**非西语音系字符**清理 —— 纯确定性字符替换,零成本,不调模型。2026-07-31。

═══ 判据(两个条件都要满足才动)═══
① 该字符在 **kaikki 的 165,192 条西语音位式里出现 0 次**(逐条扫过,见对话记录);
② 西语音位系统里本来就没有这个音位。
两条都满足 ⇒ 只可能是填空时漏转写/串了别的语言,不是任何一方的约定。

⚠️ 反例(**不要动**):`ʃ` 看着不像西语,但 kaikki 明确在用 —— `show ˈʃow`、`sushi ˈsuʃi`、
   `Shanghái ʃanˈɡai`。**判据是回源查 kaikki,不是"我觉得它不像西语"。**

═══ 映射目标怎么定的:也是回源查 kaikki 的外来词处理 ═══
   jazz ˈʝas / jeep ˈʝip / manager ˈmanaʝeɾ / Beijing beiˈʝin  →  英语 dʒ、ʒ 一律作 ʝ
   gay ˈɡei / brandy ˈbɾandi / hockey ˈoki / jersey xeɾˈsei    →  正字法 y 在元音后作 i
   bulldozer bulˈdoθeɾ / jazz ˈʝas                             →  正字法 z 作 θ,词内浊化 z 作 s

═══ 🔴 铁律:只换非法字符,其余一个字符都不动 ═══
   2026-07-31 上午试过用 `word_to_ipa` 整条重算来"修"外来词,结果很糟:
     eigenvector ˈeɡenbektor → eixembeɡˈtoɾ    Schwartz ˈʃvaɾts → ˈst͡ʃwaɾdθ
     curvy ˈkuɾvi → kuɾˈbi(重音跑了)
   这批词恰恰全是外来词/专名(kaikki 查不到才轮到人工填),正是 b_ipa.py 文件头写明的"借词坑"。
   → 不重算、不动重音、不动音节,只替换那几个字符。

默认 --dry(只看不写)。写库前自动备份。用法(在 es/ 目录):
  python3 fix_ipa_nonspanish.py                  # 全族预览 + 计数
  python3 fix_ipa_nonspanish.py --fam z --all    # 看某族全部改动
  python3 fix_ipa_nonspanish.py --apply          # 写库(自动备份)
"""
import argparse, re, shutil, sqlite3, time
from collections import Counter
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB

# ─────────────────────────────────────────── 族定义
# 每族: (说明, 命中判据 lambda, 改写 lambda(word, ipa) -> 新 ipa)

NARROW = "̯̪̥̩̟̺"      # 非成节/齿化/清化/成节/前移/舌尖 —— 严式附加符
SIMPLE = {                                           # 一对一替换,与词形无关
    "g":  ("g", "ɡ", "拉丁小写 g → IPA ɡ(同形异码)"),
    "chi": ("χ", "x", "希腊 χ → x"),
    "nlab": ("ɱ", "n", "唇齿鼻 ɱ(严式) → 音位 n"),
    "darkl": ("ɫ", "l", "软腭化 ɫ → l"),
    "phi": ("ɸ", "f", "双唇擦 ɸ → f"),
    "long": ("ː", "", "长音符(西语无音位长度)"),
}
VOWELS = {"ɔ": "o", "ɛ": "e", "ʊ": "u", "ɪ": "i", "ɑ": "a", "ɒ": "o", "ɐ": "a",
          "ə": "e", "ʌ": "a"}
SIMPLE["engr"] = ("ɹ", "ɾ", "英语近音 ɹ → ɾ")

# 🔴🔴 **不许动的白名单**:当前值与 kaikki 逐字相同的行。
#   本项目既定策略是"IPA 归信人工源 kaikki",kaikki 写什么就是什么 —— 哪怕它看着不像西语。
#   2026-07-31 上午的教训:`--wraised` 没有这道闸,把 83 条 kaikki 原文(software ˈsofdw̝eɾ、
#   web ˈw̝eb、oaxaqueño w̝axaˈkeɲo)当成"豆包填的"改坏了,事后靠来源普查才发现。
#   实例:`jacker` 的 ʀ̥ 看着完全不像西语,但 kaikki 原文就是 /ʀ̥akˈker/ —— 不许动。
#   ⚠️ 这道闸不是可选项。任何批量改音标的脚本都必须先过它。


def fix_z(word, ipa):
    """z 在 kaikki 零命中。西语无 /z/ 音位:
       词形**含正字法 z** → 是漏转写的 z,作 θ(bulldozer→bulˈdoθeɾ 即 kaikki 写法);
       词形**不含 z**     → 是 /s/ 在浊辅音前的严式浊化([ˈmizmo]),音位式作 s。"""
    return ipa.replace("z", "θ" if "z" in word.lower() else "s")


def fix_zh(word, ipa):
    """英语 dʒ / ʒ → ʝ(kaikki: jazz ˈʝas、jeep ˈʝip、manager ˈmanaʝeɾ)。先吃掉 dʒ 的 d。"""
    return ipa.replace("dʒ", "ʝ").replace("ʒ", "ʝ")


def fix_y(word, ipa):
    """正字法 y 残留。元音之间 → ʝ(poya→ˈpoʝa);其余(词尾/辅音旁) → i(gay→ˈɡei)。"""
    return re.sub(r"(?<=[aeiou])y(?=[aeiou])", "ʝ", ipa).replace("y", "i")


# 逐条排除:改法机械套用会更糟的个别条目。
#   mhm 是拟声词,`m̩`(成节 m)、`m̥`(清化 m)的严式符在这里**承载词义**,剥掉得 `mˈmm˥` 更差。
EXCLUDE_WORDS = {"mhm"}

FAMS = {
    "th":     ("th → θ(θ 被写成拉丁 th)", lambda w, p: "th" in p,
               lambda w, p: p.replace("th", "θ")),
    "z":      ("z 西语无 /z/ 音位", lambda w, p: "z" in p, fix_z),
    "zh":     ("ʒ / dʒ → ʝ", lambda w, p: "ʒ" in p, fix_zh),
    "y":      ("正字法 y 残留", lambda w, p: "y" in p, fix_y),
    "vowel":  ("非西语元音 ɔɛʊɪɑɒɐə → 五元音",
               lambda w, p: any(c in p for c in VOWELS),
               lambda w, p: "".join(VOWELS.get(c, c) for c in p)),
    "narrow": ("严式附加符 ̯ ̪ ̥ ̩ ̟ ̺",
               lambda w, p: any(c in p for c in NARROW),
               lambda w, p: "".join(c for c in p if c not in NARROW)),
}
for key, (src, dst, desc) in SIMPLE.items():
    FAMS[key] = (desc, (lambda s: lambda w, p: s in p)(src),
                 (lambda s, d: lambda w, p: p.replace(s, d))(src, dst))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fam", choices=sorted(FAMS), help="只看某一族")
    ap.add_argument("--all", action="store_true", help="打印全部改动(默认每族只打 12 条)")
    ap.add_argument("--apply", action="store_true", help="写库(自动备份)")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT id, word, phonetic, is_lemma FROM dict "
                        "WHERE TRIM(COALESCE(phonetic,''))<>''").fetchall()
    conn.close()

    import kaikki_util
    kk = kaikki_util.phonemic_ipa({r[1] for r in rows})     # 🔴 白名单闸,见 SIMPLE 上方注释
    print(f"kaikki 音位式 {len(kk):,} 词(其值与库内逐字相同的行将被排除)\n", flush=True)

    fams = [a.fam] if a.fam else list(FAMS)
    plan = {}                      # id → (word, 旧, 新, 族列表)
    tally = Counter()
    guarded = 0
    for rid, w, p, isl in rows:
        if kk.get(w) == p or w in EXCLUDE_WORDS:   # 权威源 / 逐条排除,不许动
            guarded += 1
            continue
        new, hit = p, []
        for f in fams:
            desc, match, fix = FAMS[f]
            if match(w, new):
                new = fix(w, new)
                hit.append(f)
        if hit and new != p:
            plan[rid] = (w, p, new, hit)
            for f in hit:
                tally[f] += 1

    print(f"{'族':10}{'说明':34}{'命中行数':>9}")
    print("-" * 56)
    for f in fams:
        print(f"{f:10}{FAMS[f][0]:34}{tally[f]:>9,}")
    print("-" * 56)
    print(f"{'合计':10}{'(去重后实际改动行数)':34}{len(plan):>9,}")
    print(f"{'':10}{'kaikki 逐字相同、被白名单挡下':34}{guarded:>9,}\n")

    shown = Counter()
    for rid, (w, old, new, hit) in plan.items():
        key = hit[0]
        if not a.all and shown[key] >= 12:
            continue
        shown[key] += 1
        print(f"  [{'+'.join(hit):14}] {w[:24]:26} {old[:30]:32} → {new[:30]}")

    if not a.apply:
        print(f"\n(--dry 预览。确认无误后加 --apply 写库)")
        return

    bak = DB.with_name(f"synapse-dict-es.pre-nonspanish-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy2(DB, bak)
    print(f"\n已备份 → {bak.name}")
    c = sqlite3.connect(DB)
    c.executemany("UPDATE dict SET phonetic=? WHERE id=?",
                  [(v[2], k) for k, v in plan.items()])
    c.commit()
    n = lambda s: c.execute(s).fetchone()[0]
    tot = n("SELECT COUNT(*) FROM dict")
    ipa = n("SELECT COUNT(*) FROM dict WHERE TRIM(COALESCE(phonetic,''))<>''")
    zh = n("SELECT COUNT(*) FROM dict WHERE TRIM(COALESCE(translation,''))<>''")
    print(f"已写入 {len(plan):,} 行")
    print(f"不变量 → 总行 {tot:,} | 有音标 {ipa:,} | 有中文 {zh:,}")
    # 残留复查必须**套同一道白名单**,否则受保护的行会被算成"没修干净"(误导)。
    left, protected = 0, 0
    for rid, w, p, isl in c.execute("SELECT id, word, phonetic, is_lemma FROM dict "
                                    "WHERE TRIM(COALESCE(phonetic,''))<>''"):
        if not any(FAMS[f][1](w, p) for f in fams):
            continue
        if kk.get(w) == p or w in EXCLUDE_WORDS:
            protected += 1
        else:
            left += 1
            print(f"  🔴 未处理 {w[:24]:26} {p[:30]}")
    print(f"残留复查:未处理 {left} 行(应为 0);受保护未动 {protected} 行(kaikki 原生 + 逐条排除)")
    c.close()


if __name__ == "__main__":
    main()
