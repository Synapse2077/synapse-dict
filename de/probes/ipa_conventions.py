#!/usr/bin/env python3
"""阶段 4 前置 —— **德语版与法语版给同一个词的音标，差在哪里**。2026-09-03。

═══ 为什么先做这一步 ═══
两版都要收（德语版独有 417,539、法语版独有 10,486，谁都不可替代），
于是必然撞上「同一个词两版给的音标不一样」。**在合并之前必须先知道差异是什么性质**：

    是**记法约定**不同（两个都对，选一个就行）
    还是**真的有一边错**（那要判）

🔴 这正是我在 es 上栽过的坑（`[[es-dict-pipeline]]`）：把 `coda 浊化 31,890` 和
   `多词次重音 7,889` 当成两个大缺陷报上去，回源逐字核对后发现**两个都是记法约定**，
   99.9% / 96.8% 逐字一致。而 `[[cross-edition-harvest]]` 已明写
   **fr 版重音符位置约定不同，没归一会误报 92%**。

═══ 判据：一次只抹掉一个特征，看剩下的还等不等 ═══
分类不靠正则猜"看起来像什么"，靠**消去法**：
把两串各抹掉特征 X 之后如果相等，那这对差异**只**关于 X。
一个都消不掉的进「其他」，那一桶才是要拿去问模型的。
⚠️ 顺序固定、且每条只归**第一个**命中的桶 —— 否则同一对会被重复计数。

本脚本**只读**，不写库、不下载、不调模型。
"""
import gzip, json, re, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import paths                                    # noqa: E402
from intake_edition_words import EDITIONS       # noqa: E402

f = lambda n: format(n, ",")


def opener(p):
    p = Path(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def scan(key, keep):
    """→ {词形: set(裸音标)}，只收 `keep` 里的词形。"""
    path, need_filter = EDITIONS[key]
    out = defaultdict(set)
    with opener(path) as fh:
        for line in fh:
            if need_filter and '"lang_code"' in line and '"de"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if need_filter and e.get("lang_code") != "de":
                continue
            w = e.get("word") or ""
            if w not in keep:
                continue
            for s in e.get("sounds") or []:
                # 🔴 **各版的定界符约定不同，必须全剥干净**：
                #    我们/英/德版用 `/…/` 或 `[…]`，**法语维基词典用 `\…\`**。
                #    第一版漏了反斜杠 ⇒ 21,922 条（4.5%）被判成"音段本身不同"，
                #    而实际 `\ʁetʁospɛkˈtiːvm̩\` 与 `ʁetʁospɛkˈtiːvm̩` 逐字相同。
                #    ⇒ **最大的那一桶是我的度量错，不是数据的分歧**
                #      （`[[measure-landing-not-source]]`：新数字先假设我的度量错了）。
                #    逮到它靠的是把**实样**打出来，不是读代码。
                ipa = (s.get("ipa") or "").strip().strip("/[]\\").strip()
                if ipa:
                    out[w].add(ipa)
    return out


# ── 消去器：每个只抹掉一个特征 ──────────────────────────────────────────
STRESS = re.compile(r"[ˈˌ'ˈˌ]")
LONG   = re.compile(r"[ːˑ:]")
SYLL   = re.compile(r"[.·̵‿]")
GLOT   = re.compile(r"[ʔ]")
DIACR  = re.compile(r"[̀-̩̯̞̥ͯ̊͜͡]")
R_ALL  = re.compile(r"[ʁrʀɐɹʶ]")
SPACE  = re.compile(r"[\s​ ]")
HYPH   = re.compile(r"^[-‐‑–]+|[-‐‑–]+$")   # 词缀条目的首尾连字符（法语版带、德语版不带）

def _nfc(x):    return unicodedata.normalize("NFC", x)
def d_stress(x): return STRESS.sub("", x)
def d_long(x):   return LONG.sub("", x)
def d_syll(x):   return SYLL.sub("", x)
def d_glot(x):   return GLOT.sub("", x)
def d_diacr(x):  return DIACR.sub("", unicodedata.normalize("NFD", x))
def d_r(x):      return R_ALL.sub("R", x)
def d_space(x):  return SPACE.sub("", x)
def d_hyph(x):   return HYPH.sub("", x)

# 顺序＝归桶优先级。每对只进第一个命中的桶。
BUCKETS = [
    ("① 只差空白",                 [d_space]),
    ("①b 只差词缀首尾连字符",       [d_space, d_hyph]),
    ("② 只差音节点 . ·",           [d_space, d_syll]),
    ("③ 只差重音符 ˈ ˌ（位置或有无）", [d_space, d_stress]),
    ("④ 只差长音符 ː",             [d_space, d_long]),
    ("⑤ 只差词首喉塞音 ʔ",          [d_space, d_glot]),
    ("⑥ 只差 r 类记法 ʁ/r/ɐ/ʀ",     [d_space, d_r]),
    ("⑦ 只差附加符（元音下加点等）",   [d_space, d_diacr]),
    ("⑧ 上面几样的组合",            [d_space, d_hyph, d_syll, d_stress, d_long, d_glot, d_r, d_diacr]),
]


def bucket(a, b):
    """→ 桶名。a/b 已 NFC。"""
    if a == b:
        return None
    for name, fns in BUCKETS:
        x, y = a, b
        for fn in fns:
            x, y = fn(x), fn(y)
        if x == y:
            return name
    return "⑨ 其他（音段本身不同）← 要拿去问模型的就是这一桶"


def main():
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    keep = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()
    print("■ 库内词形 %s" % f(len(keep)))

    print("■ 扫德语版…"); de = scan("de", keep); print("   带音标词形 %s" % f(len(de)))
    print("■ 扫法语版…"); fr = scan("fr", keep); print("   带音标词形 %s" % f(len(fr)))

    both = set(de) & set(fr)
    print("\n■ 两版都给了音标的词形 %s" % f(len(both)))

    agree, c, ex = 0, Counter(), {}
    for w in both:
        A = {_nfc(x) for x in de[w]}
        B = {_nfc(x) for x in fr[w]}
        if A & B:                       # 有任意一条逐字相同 ⇒ 不算分歧
            agree += 1
            continue
        # 取"最像的一对"来归类：桶序越靠前越像
        best, bname = 99, None
        for a in A:
            for b in B:
                nm = bucket(a, b)
                idx = next((i for i, (n, _) in enumerate(BUCKETS) if n == nm), 98)
                if idx < best:
                    best, bname = idx, nm
                    ex.setdefault(nm, (w, a, b))
        c[bname] += 1

    n = max(len(both), 1)
    print("   逐字有交集（无分歧）    %s  %5.1f%%" % (f(agree), 100.0 * agree / n))
    print("\n■ 分歧归类（每对只进第一个命中的桶）")
    for k, v in sorted(c.items()):
        print("   %-38s %8s  %5.1f%%" % (k, f(v), 100.0 * v / n))
        w, a, b = ex[k]
        print("        %-22s de=%-24s fr=%s" % (w[:22], a[:24], b[:24]))

    print("\n── ⑨ 其他 桶的样本 20 条（这一桶才值得问模型）──")
    shown = 0
    for w in sorted(both):
        if shown >= 20:
            break
        A = {_nfc(x) for x in de[w]}; B = {_nfc(x) for x in fr[w]}
        if A & B:
            continue
        if any(bucket(a, b) and bucket(a, b).startswith("⑨") for a in A for b in B) and \
           not any(bucket(a, b) and not bucket(a, b).startswith("⑨") for a in A for b in B):
            print("   %-24s de=%-26s fr=%s" % (w[:24], sorted(A)[0][:26], sorted(B)[0][:26]))
            shown += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
