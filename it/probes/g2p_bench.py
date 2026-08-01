#!/usr/bin/env python3
"""it 的 G2P 正面对比:本项目规则 vs eSpeak NG —— 拿 kaikki 人工音标当真值。
零成本、确定性、不调模型。2026-08-01。

═══ 🔴 为什么不能逐字比 ═══
两边的**约定**完全不同,逐字比会得出近似 0%,那是在量约定差异不是量质量:
    gatto       espeak ɡˈatːo        kaikki ˈɡat.to      (重音符位置/长辅音写法)
    città       espeak tʃitːˈa       kaikki t͡ʃitˈta      (连结弧)
    abalienate  espeak abalienˈate   kaikki a.ba.ljeˈna.te (滑音分析/音节点)
    ancora      espeak ankˈora       kaikki ˈaŋ.ko.ra     (ŋ 同位异音)
这正是 2026-07-31 在 es 上栽过的坑(把 kaikki 的 coda 浊化约定当成缺陷)。

═══ 比什么:只比我们真正缺的那两样信息 ═══
意语辅音映射完全规则、本项目规则早就做对了。缺口只有拼写里不写的两件事:
  ① **重音落在第几个元音**   ② **e/ɛ、o/ɔ 开闭**
故把两边都归一到「元音序列 + 重音落点」再比,并对称施加同一套归一:
  去连结弧/音节点/次重音;espeak 的 Cː 还原为 CC;j→i、w→u(滑音分析差异);ŋ→n(同位异音)。
额外报「音段骨架」(再抹掉开闭与重音)作为下界参照。

⚠️ 归一是**对称**的:同一个函数同时作用于 kaikki、本项目规则、espeak 三方,
   不给任何一方开小灶。

用法(在 it/ 目录):
  python3 g2p_bench.py              # 全量 8.3 万词
  python3 g2p_bench.py --limit 3000 # 快速试跑
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, re, subprocess, sqlite3, sys, time
from collections import Counter
from pathlib import Path

import kaikki_util
from b_ipa import word_to_ipa

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
VOWELS = set("aeiouɛɔ")


def canon(s):
    """对称归一:抹掉三方**约定**上的差异,保留音系信息。"""
    if not s:
        return ""
    s = s.replace("͡", "").replace(".", "").replace("ˌ", "")
    # 🔴 长音符 ː 必须**分辅音/元音两种处理**(第一版一律删掉,把 espeak 打低了一大截):
    #    espeak 用 Cː 表示意语的双辅音(gatto ɡˈatːo),而 kaikki 写双写(ˈɡat.to) → 必须还原成 CC,
    #    否则每个含双辅音的意语词都会被判成音段不同(实测骨架一致率因此从真实值掉到 50.6%);
    #    元音后的 ː 是长元音(ˈiːn),意语无音位长元音,直接去掉。
    s = re.sub(r"([^aeiouɛɔ])ː", r"\1\1", s)
    s = s.replace("ː", "")
    s = re.sub(r"(.)\1{2,}", r"\1\1", s)       # 3 连以上收敛到 2(不动正常的双写)
    s = s.replace("j", "i").replace("w", "u")  # 滑音分析差异
    s = s.replace("ŋ", "n").replace("ɡ", "g")  # 同位异音 / 同形异码
    # 🔴 espeak 的记法特点(第一版漏掉,导致 28.3% 的词"元音数不同"、被排除在重音/开闭统计之外):
    #    ① 非重读 /i/ /u/ 写作 ɪ ʊ(duplichi → dˈuplikɪ、australi → aʊstrˈalɪ) —— 不归一就
    #       根本不被算作元音,元音序列天然对不上;② 意语 /r/ 它写闪音 ɾ,kaikki 写 r。
    #    这些都是**记法**不是音系差异,必须归一,否则量的是"谁的写法像 kaikki"。
    s = s.replace("ɪ", "i").replace("ʊ", "u").replace("ɾ", "r")
    return s.strip()


def vseq_stress(s):
    """→ (元音序列, 重音落在第几个元音)。两种约定下「重音元音」都是 ˈ 之后的第一个元音。"""
    c = canon(s)
    vs, sidx, pending = [], None, False
    for ch in c:
        if ch == "ˈ":
            pending = True
            continue
        if ch in VOWELS:
            if pending:
                sidx = len(vs)
                pending = False
            vs.append(ch)
    return vs, sidx


def skeleton(s):
    """音段骨架:再抹掉开闭与重音,只剩辅音+元音骨。"""
    return canon(s).replace("ˈ", "").replace("ɛ", "e").replace("ɔ", "o")


CLAUSE = re.compile(r"[.,;:?!()\[\]\"]")     # espeak 把这些当**子句分隔**,一个词会吐成两行


def _run(args, inp=None):
    """espeak 的 stderr 不保证是 utf-8(实测抛 UnicodeDecodeError),必须容错解码。"""
    return subprocess.run(args, input=inp, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def espeak_batch(words, chunk=2000):
    """逐行喂,分块校验行数对齐;某块不齐只对该块退回逐词,不牵连全体。

    🔴 输入必须先去掉子句分隔标点:库里有 `S.p.A.`、`occhio per occhio, dente…` 这类词条,
       espeak 会按 . 和 , 切成多行,导致整批**错位**(不是少一行那么简单,是之后全部对错人)。"""
    res = []
    for j in range(0, len(words), chunk):
        sub = words[j:j + chunk]
        clean = [CLAUSE.sub(" ", w).replace("\n", " ").strip() or "-" for w in sub]
        out = [ln.strip() for ln in _run(["espeak-ng", "-v", "it", "--ipa", "-q"],
                                         "\n".join(clean)).stdout.split("\n")]
        while out and out[-1] == "":
            out.pop()
        if len(out) == len(sub):
            res += out
            continue
        print(f"  ⚠️ 第 {j//chunk} 块行数不齐({len(out)} vs {len(sub)}),该块逐词跑…", flush=True)
        for w in clean:
            res.append(_run(["espeak-ng", "-v", "it", "--ipa", "-q", w]).stdout.strip().replace("\n", " "))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ex", type=int, default=10, help="打印几条分歧例词")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT word, ipa FROM dict WHERE TRIM(COALESCE(ipa,''))<>''").fetchall()
    conn.close()
    print(f"库内有音标 {len(rows):,} 行,取 kaikki 真值…", flush=True)
    kk, amap = kaikki_util.sounds_and_accent_map(None)
    print(f"  kaikki {len(kk):,} 词 / 重音形映射 {len(amap):,}", flush=True)

    seen = set()
    items = []           # (word, kaikki真值, 是否拿到带重音形)
    for w, p in rows:
        if w in seen or w not in kk:
            continue
        seen.add(w)
        items.append((w, kk[w], kaikki_util.unaccent(w) in amap))
    if a.limit:
        items = items[:a.limit]
    print(f"  可比对词形 {len(items):,}\n", flush=True)

    t0 = time.time()
    esp = espeak_batch([w for w, _, _ in items])
    print(f"espeak 跑完 {time.time()-t0:.0f}s", flush=True)

    # 三方各自的结果
    tal = {e: Counter() for e in ("本项目规则", "eSpeak NG")}
    bypath = {e: {True: Counter(), False: Counter()} for e in tal}
    diff_ex = {e: [] for e in tal}
    for (w, kv, has_acc), ev in zip(items, esp):
        rv = word_to_ipa(amap.get(kaikki_util.unaccent(w), w))
        rv = rv.strip("/") if rv else None
        kvs, ksi = vseq_stress(kv)
        for eng, val in (("本项目规则", rv), ("eSpeak NG", ev)):
            t = tal[eng]; bp = bypath[eng][has_acc]
            t["可比"] += 1; bp["可比"] += 1
            if not val:
                t["算不出"] += 1; bp["算不出"] += 1
                continue
            vs, si = vseq_stress(val)
            if len(vs) != len(kvs):            # 元音个数都不同 → 音段层面就没对上
                t["元音数不同"] += 1; bp["元音数不同"] += 1
            else:
                if si is not None and si == ksi:
                    t["重音对"] += 1; bp["重音对"] += 1
                elif si != ksi:
                    if len(diff_ex[eng]) < a.ex:
                        diff_ex[eng].append(("重音", w, kv, val))
                if vs == kvs:
                    t["元音全对(含开闭)"] += 1; bp["元音全对(含开闭)"] += 1
                elif [c for c in vs if c in "eɛoɔ"] != [c for c in kvs if c in "eɛoɔ"]:
                    t["开闭错"] += 1; bp["开闭错"] += 1
                    if len(diff_ex[eng]) < a.ex:
                        diff_ex[eng].append(("开闭", w, kv, val))
            if skeleton(val) == skeleton(kv):
                t["音段骨架一致"] += 1; bp["音段骨架一致"] += 1
            if val == kv:
                t["逐字一致(仅参考)"] += 1; bp["逐字一致(仅参考)"] += 1

    KEYS = ["逐字一致(仅参考)", "音段骨架一致", "元音数不同", "重音对", "元音全对(含开闭)",
            "开闭错", "算不出"]
    W = 74
    print("=" * W)
    print(f"{'指标':22}" + "".join(f"{e:>18}" for e in tal))
    print("=" * W)
    for k in KEYS:
        line = f"{k:22}"
        for e in tal:
            n, d = tal[e][k], tal[e]["可比"]
            line += f"{n:>10,} {100*n/max(d,1):>6.1f}%"
        print(line)
    print("-" * W)
    print(f"{'可比词形':22}" + "".join(f"{tal[e]['可比']:>10,} {'':>7}" for e in tal))

    for has_acc, lab in ((True, "拿到 kaikki 带重音形"), (False, "没拿到(按默认处理)")):
        print(f"\n■ 分路径:{lab}")
        print(f"  {'指标':20}" + "".join(f"{e:>18}" for e in tal))
        for k in ("重音对", "元音全对(含开闭)", "音段骨架一致"):
            line = f"  {k:20}"
            for e in tal:
                n, d = bypath[e][has_acc][k], bypath[e][has_acc]["可比"]
                line += f"{n:>10,} {100*n/max(d,1):>6.1f}%"
            print(line)

    for e in tal:
        if diff_ex[e]:
            print(f"\n■ {e} 的分歧例:")
            for kind, w, kv, val in diff_ex[e]:
                print(f"    [{kind}] {w[:22]:24} kaikki {kv[:26]:28} {e} {val[:26]}")


if __name__ == "__main__":
    main()
