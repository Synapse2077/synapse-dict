#!/usr/bin/env python3
"""it 音标混合方案:用 eSpeak NG 补「重音位置 + e/ɛ o/ɔ 开闭」,由本项目 G2P 出串。2026-08-01。

═══ 为什么这么做 ═══
`g2p_bench.py` 全量实测(83,004 个有 kaikki 真值的词形):
                        本项目规则          eSpeak NG
  拿到 kaikki 带重音形     重音 92.3% 开闭 96.9%   85.2% / 88.8%     ← 我们赢
  **没拿到、走默认**       重音 66.8% 开闭 70.6%   **86.7% / 87.9%**  ← espeak 赢 ~20pp
  音段骨架(默认路径)       **90.3%**              84.9%             ← 我们赢
两边**互补**:我们的音段更准且完全对齐 kaikki 约定,espeak 的词汇性重音/开闭更准
(它内置意语词典把这些记住了,而规则只能猜"倒二音节+闭元音")。

═══ 做法:只取信息,不取字符串 ═══
espeak 的记法与 kaikki 处处不同(长辅音 Cː、非重读 ɪ ʊ、闪音 ɾ、重音标在元音前……),
直接入库等于换一套约定。所以只从它那里取两项**信息**:
    ① 重音落在第几个元音   ② 该元音的开闭(ɛ/ɔ 还是 e/o)
再把这两项写回**拼写**(a→à、e→è/é、o→ò/ó、i→ì、u→ù),喂给 `b_ipa.word_to_ipa`。
→ 产出仍是本项目自己的 kaikki 约定串,一个记法字符都不用改。
这与 `b_ipa_fill.py` 现有路径**形状完全一样**(它是从 kaikki forms 拿带重音拼写),
只是在"kaikki 没有重音形"时,改由 espeak 供给。

═══ 安全边界 ═══
· 只动**同时满足**:kaikki 无该词音标(不覆盖人工源) + kaikki forms 无带重音形(不抢已有好路径);
· espeak 元音数与拼写元音数**必须一致**,否则无法把重音落点映射回字母,跳过;
· G2P 对注入后的拼写返回 None 则跳过(保留原值)。

用法(在 it/ 目录):
  python3 hybrid_ipa.py --eval     # 在有 kaikki 真值的同类词上验证提升(不写库)
  python3 hybrid_ipa.py            # 预览将改动多少行
  python3 hybrid_ipa.py --apply    # 写库(自动备份)
"""
import argparse, re, shutil, sqlite3, subprocess, time
from collections import Counter
from pathlib import Path

import kaikki_util
from b_ipa import word_to_ipa

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
VOWELS = set("aeiouɛɔ")
SPELL_V = "aeiou"
CLAUSE = re.compile(r"[.,;:?!()\[\]\"]")
# 拼写元音 + 开闭 → 带重音字母。è/ò 表开,é/ó 表闭(与 b_ipa.VOWEL 表一致)。
ACCENT = {("a", None): "à", ("i", None): "ì", ("u", None): "ù",
          ("e", "open"): "è", ("e", "close"): "é",
          ("o", "open"): "ò", ("o", "close"): "ó"}


def canon(s):
    """与 g2p_bench 同一套对称归一(记法差异,不是音系差异)。"""
    if not s:
        return ""
    s = s.replace("͡", "").replace(".", "").replace("ˌ", "")
    s = re.sub(r"([^aeiouɛɔ])ː", r"\1\1", s)
    s = s.replace("ː", "")
    s = s.replace("j", "i").replace("w", "u")
    s = s.replace("ŋ", "n").replace("ɡ", "g")
    s = s.replace("ɪ", "i").replace("ʊ", "u").replace("ɾ", "r")
    return s.strip()


def vseq_stress(s):
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


def espeak_batch(words, chunk=2000):
    res = []
    for j in range(0, len(words), chunk):
        sub = words[j:j + chunk]
        clean = [CLAUSE.sub(" ", w).replace("\n", " ").strip() or "-" for w in sub]
        r = subprocess.run(["espeak-ng", "-v", "it", "--ipa", "-q"],
                           input="\n".join(clean), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        out = [ln.strip() for ln in r.stdout.split("\n")]
        while out and out[-1] == "":
            out.pop()
        if len(out) != len(sub):
            out = [subprocess.run(["espeak-ng", "-v", "it", "--ipa", "-q", w],
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace").stdout.strip().replace("\n", " ")
                   for w in clean]
        res += out
        if j and j % 40000 == 0:
            print(f"    espeak {j:,}/{len(words):,}", flush=True)
    return res


def inject(word, esp):
    """把 espeak 的重音落点+开闭写回拼写,返回带重音的拼写;做不到返回 None。"""
    vs, sidx = vseq_stress(esp)
    if sidx is None:
        return None
    # 拼写里的元音字母位置(已带重音符的词不处理 —— 那条路本来就走 kaikki forms)
    pos = [i for i, ch in enumerate(word.lower()) if ch in SPELL_V]
    if len(pos) != len(vs) or sidx >= len(pos):
        return None                       # 元音数对不上 → 无法把落点映回字母,跳过
    ch = word[pos[sidx]].lower()
    v = vs[sidx]
    if ch in "eo":
        kind = "open" if v in "ɛɔ" else "close"
    elif ch in "aiu":
        kind = None
    else:
        return None
    acc = ACCENT.get((ch, kind))
    if not acc:
        return None
    return word[:pos[sidx]] + acc + word[pos[sidx] + 1:]


def load(conn):
    return conn.execute("SELECT id, word, ipa FROM dict "
                        "WHERE TRIM(COALESCE(ipa,''))<>''").fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true", help="在有 kaikki 真值的同类词上验证,不写库")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ex", type=int, default=12)
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = load(conn)
    conn.close()
    print(f"有音标 {len(rows):,} 行,取 kaikki…", flush=True)
    kk, amap = kaikki_util.sounds_and_accent_map(None)
    print(f"  kaikki {len(kk):,} 词 / 重音形映射 {len(amap):,}", flush=True)

    # 目标集:走"默认路径"的行 —— kaikki 无带重音形。
    # --eval 取其中**kaikki 有音标**的(有真值可验);正式跑取**kaikki 无音标**的(真正要修的)。
    tgt, seenw = [], set()
    for rid, w, p in rows:
        if kaikki_util.unaccent(w) in amap:
            continue                       # 已走 kaikki 重音形路径,不碰
        has_truth = w in kk
        if a.eval and not has_truth:
            continue
        if not a.eval and has_truth:
            continue                       # kaikki 有音标 → 人工源优先,不碰
        if w in seenw:
            continue
        seenw.add(w)
        tgt.append((rid, w, p))
    print(f"  目标 {len(tgt):,} 个词形（{'验证集:有 kaikki 真值' if a.eval else '待修:无任何人工源'}）\n",
          flush=True)

    t0 = time.time()
    esp = espeak_batch([w for _, w, _ in tgt])
    espmap = {w: e for (_, w, _), e in zip(tgt, esp)}
    print(f"espeak 完成 {time.time()-t0:.0f}s", flush=True)

    tal = Counter()
    plan, ex = [], []
    for (rid, w, p), ev in zip(tgt, esp):
        acc = inject(w, ev)
        if acc is None:
            tal["无法注入(元音数不齐等)"] += 1
            continue
        new = word_to_ipa(acc)
        if not new:
            tal["G2P 算不出"] += 1
            continue
        new = new.strip("/")
        if new == p:
            tal["与现值相同"] += 1
            continue
        tal["将改写"] += 1
        plan.append((rid, w, p, new))
        if len(ex) < a.ex:
            ex.append((w, acc, p, new, kk.get(w)))
    print(f"{'情况':24}{'词数':>9}")
    for k, v in tal.most_common():
        print(f"  {k:22}{v:>9,}")

    if a.eval:
        # 🔴 验证必须比「**裸规则会生成什么**」vs「**混合会生成什么**」,都对 kaikki 打分。
        #    第一版拿**库内现值**当"改前",而验证集这些词库里存的就是 kaikki 值(=真值本身),
        #    "改前 100%"是同义反复,任何改动必然显示为倒退 —— 比错了对象。
        #    真正要修的 18.4 万条,库里存的是**裸规则输出**,所以基线就该是裸规则。
        sc = Counter()
        for rid, w, p in tgt:
            kv = kk.get(w)
            if not kv:
                continue
            kvs, ksi = vseq_stress(kv)
            base = word_to_ipa(w)
            base = base.strip("/") if base else None
            hyb = None
            acc = inject(w, espmap.get(w, ""))
            if acc:
                h = word_to_ipa(acc)
                hyb = h.strip("/") if h else None
            for tag, val in (("裸规则", base), ("混合", hyb)):
                sc[(tag, "可比")] += 1
                if not val:
                    continue
                vs, si = vseq_stress(val)
                if len(vs) != len(kvs):
                    sc[(tag, "元音数不同")] += 1
                    continue
                if si == ksi:
                    sc[(tag, "重音对")] += 1
                if vs == kvs:
                    sc[(tag, "元音全对(含开闭)")] += 1
                if val == kv:
                    sc[(tag, "逐字一致")] += 1
        print(f"\n■ 验证:同一批 {sc[('裸规则','可比')]:,} 个词(有 kaikki 真值、且无带重音形),"
              f"两种生成法各自对真值打分")
        print(f"  {'指标':20}{'裸规则(=库内现状)':>20}{'混合(espeak 补重音/开闭)':>26}")
        for k in ("逐字一致", "重音对", "元音全对(含开闭)", "元音数不同"):
            line = f"  {k:20}"
            for tag in ("裸规则", "混合"):
                n0, d = sc[(tag, k)], sc[(tag, "可比")]
                line += f"{n0:>12,} {100*n0/max(d,1):>6.1f}%"
            print(line)

    print(f"\n■ 例:")
    for w, acc, p, new, kv in ex:
        tag = f"  kaikki {kv}" if kv else ""
        print(f"    {w[:20]:22} 注入拼写 {acc[:20]:22} {p[:24]:26} → {new[:24]:26}{tag}")

    if not a.apply:
        print(f"\n(预览。--eval 看提升;确认后 --apply 写库)")
        return

    bak = DB.with_name(f"synapse-dict-it.pre-hybrid-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy2(DB, bak)
    print(f"\n已备份 → {bak.name}")
    c = sqlite3.connect(DB)
    byword = {w: new for _, w, _, new in plan}
    cur = c.executemany("UPDATE dict SET ipa=? WHERE word=? AND TRIM(COALESCE(ipa,''))<>''",
                        [(new, w) for w, new in byword.items()])
    c.commit()
    n = lambda s: c.execute(s).fetchone()[0]
    NE = "SELECT COUNT(*) FROM dict WHERE TRIM(COALESCE({},''))<>''"
    print(f"已写入(按词形 {len(byword):,} 个)")
    print(f"不变量 → 总行 {n('SELECT COUNT(*) FROM dict'):,} | "
          f"有音标 {n(NE.format('ipa')):,} | 有中文 {n(NE.format('translation')):,}")
    c.close()


if __name__ == "__main__":
    main()
