#!/usr/bin/env python3
"""B1 [网络]纯音译:用 kaikki(Wiktionary) 认定的变形关系,把音译垃圾换成原形词义。见对话 2026-07-28。

背景:B1 = 单行 [网络] + ≤8 汉字音译,43.9 万条,抽样验 **bad 53.6%**(过半是错的),
是全库最大错误源(全库 78% 的错译集中在 [网络] 全族)。典型错法 airish→派对、boomhauer→繁荣。
但 B1 里 46% 其实是对的,**不能一刀切删**。

零 API 成本的一刀:`en/kaikki.org-dictionary-English.jsonl`(2.9GB,Wiktionary 全量)
覆盖 B1 的 50.2%(220,579 条)。其中 kaikki 首义就是元描述(plural of X / alternative form of X…)的,
**原形由 Wiktionary 权威给出**,再去库里取该原形的中文(ECDICT 审校过),就能把音译顶掉。

⚠️ 三道必须的核查(第一版都栽过):
  1. **原形可能是多词**:`bum wines → plural of bum wine`,正则若只抓第一个单词会得到 `bum`(游荡者),
     抄过来完全不相干。→ 捕获组必须允许空格/连字符。
  2. **原形本身可能是 [网络]**:defeminises→defeminise「[网络] 独裁」,抄过去是把垃圾从一条扩散成两条。
  3. **原形可能自己就是空壳/无汉字**。
  三道核完,220,579 → 实际可用 ~4 万条(我一度按"kaikki 首义像元描述"直接报 9.5 万,高估一倍多)。

处置=**替换**而非追加:B1 现有内容是众包音译(过半错),原形译文来自 ECDICT(审校),
故整条改写为「原形的形态说明 + 换行 + 原形中文」,与 A1 回填格式一致。原文全量留痕,可逐条回退。

用法:
  python3 en/fix_b1_kaikki.py            # dry-run
  python3 en/fix_b1_kaikki.py --run      # 备份后写库,留痕 b1_kaikki_fill.tsv
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, json, re, shutil, sqlite3, random
from collections import Counter
from datetime import datetime
from pathlib import Path

import buckets as B
import fix_a1a as F

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
GLOSS = paths.WORK / "anchors/b1_kaikki_gloss.json"
LOG = paths.WORK / "ledgers/b1_kaikki_fill.tsv"

# ⚠️ 捕获组 [\w'’\- ]* 必须含空格与连字符,否则多词原形被截断(bum wine → bum)
KINDS = [
    (r"plural of", "的复数形式"),
    (r"singular of", "的单数形式"),
    (r"present participle(?: and gerund)? of", "的现在分词"),
    (r"gerund of", "的动名词"),
    (r"past participle of", "的过去分词"),
    (r"simple past(?: tense)?(?: and past participle)? of", "的过去式"),
    (r"third-person singular[^.]*? of", "的第三人称单数"),
    (r"comparative(?: form)?(?: degree)? of", "的比较级"),
    (r"superlative(?: form)?(?: degree)? of", "的最高级"),
    (r"alternative (?:spelling|form) of", "的异体拼写"),
    (r"obsolete (?:spelling|form) of", "的旧拼写"),
    (r"misspelling of", "的错误拼写"),
]
# ⚠️ **同义词(synonym of)整类剔除**:变形关系里"原形的词义 == 该词的词义",可以直接抄;
#    但同义词关系下,原形词若多义,库里那条给的常是**另一个义**,抄过来就错:
#      tropical yam → "Synonym of ñame"(西语薯蓣) 重音被抹成 name → 抄成"名字,名称"
#      South American fox → zorro(西语狐狸) → 库里 zorro 是"佐罗(人名)"
#      auslaut → coda(语言学:音节尾) → 库里 coda 是"乐章尾声"
#    剔 1,980 条。
INFL = ("的复数形式", "的单数形式", "的现在分词", "的动名词", "的过去分词",
        "的过去式", "的第三人称单数", "的比较级", "的最高级")
PATS = [(re.compile(r"^" + k + r"\s+([A-Za-z][\w'’\- ]*?)\s*[.,:;(]", re.I), zh) for k, zh in KINDS]


def parse_gloss(g):
    """→ (base, 形态说明中文) 或 None。"""
    s = g.strip()
    if not s.endswith("."):
        s += "."
    for rx, zh in PATS:
        m = rx.match(s)
        if m:
            base = m.group(1).strip().rstrip(".,;:").strip()
            if base:
                return base, zh
    return None


def collect(conn):
    gl = json.load(open(GLOSS, encoding="utf-8"))
    trans, forms = {}, {}
    for w, t in conn.execute("SELECT word, translation FROM stardict"):
        k = w.strip().lower()
        trans.setdefault(k, (t or "").strip())
        forms.setdefault(k, set()).add(w.strip())
    b1 = {}
    for i, w, t, bk in B.load_tail(conn):
        if bk == "B1":
            b1[w.strip().lower()] = (i, w.strip(), (t or "").strip())

    rej = Counter(); out = []
    for w, glosses in gl.items():
        if w not in b1:
            continue
        p = parse_gloss(glosses[0])
        if not p:
            rej["kaikki 措辞非变形/提不出原形"] += 1; continue
        base, kindzh = p
        bl = base.lower()
        bt = trans.get(bl, "")
        if not bt:
            rej["原形不在库"] += 1; continue
        if "[网络]" in bt:
            rej["原形本身是[网络](不可扩散)"] += 1; continue
        if F.is_shell(bt):
            rej["原形自己是空壳"] += 1; continue
        if not re.search(r"[一-鿿]", bt):
            rej["原形译文无汉字"] += 1; continue
        if bl == w:
            rej["原形=词条自身"] += 1; continue
        # 变形类再加一道形态校验:词条必须由原形派生,首 3 字母须一致
        # (拦住 kaikki 措辞怪异或原形抓偏的个例;异体/旧拼写/错拼不适用,它们本就可能改头)
        if kindzh in INFL:
            aa = w.replace(" ", "").replace("-", "")
            bb = bl.replace(" ", "").replace("-", "")
            if aa[:3] != bb[:3]:
                rej["变形类但形态不符(首3字母)"] += 1; continue
        rid, word, cur = b1[w]
        out.append((rid, word, cur, base, kindzh, bt))
    return out, rej


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    cand, rej = collect(conn)
    print("B1 × kaikki 变形关系 → 逐条剔除原因:")
    for k, v in rej.most_common():
        print(f"  {k:26} {v:>7}")
    print(f"\n✅ 可回填 {len(cand)}")

    random.seed(11)
    print("\n---- 抽 20 条核对(重点看原形抓得对不对) ----")
    for rid, w, cur, base, kind, bt in random.sample(cand, min(20, len(cand))):
        print(f"  {w:26} 现:{cur.split(']')[-1].strip()[:12]:14} 原形<{base}> → "
              f"{(base+kind+chr(10)+bt).replace(chr(10),' ⏎ ')[:62]}")

    if not a.run:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-b1kaikki-{tag}.bak"))
    conn = sqlite3.connect(DB)
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tbase\tbefore\tafter\n")
        for rid, w, cur, base, kind, bt in cand:
            new = base + kind + "\n" + bt
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            f.write("\t".join([rid.__str__(), w, base, cur.replace("\t", " ").replace("\n", "\\n"),
                               new.replace("\t", " ").replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已改写 {len(cand)} 条,留痕 → {LOG.name};备份 pre-b1kaikki-{tag}.bak")


if __name__ == "__main__":
    main()
