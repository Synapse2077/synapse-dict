#!/usr/bin/env python3
"""es 音标残留修复 —— 只修**回源核对后确认是错的**那几族。见对话 2026-07-31。

🔴 先读这段,否则会去修不该修的东西:
   2026-07-31 两家模型(豆包pro + v4-pro)独立评审,一致认定两个"最大缺陷":
     ① coda 塞音浊化 31,890 条(acto→ˈaɡto)  ② 多词非末词标次重音 ˌ 7,889 条
   **回源查 kaikki 后两条都不成立** —— kaikki 自己就写 /ˈaɡto/ /ˈabto/ /ˈtaɡsi/ /doɡˈtoɾ/、
   短语也确实给非末词次重音(`matamoros`→`ˌmataˈmoɾos`)。
   实测:受影响 lemma 在 kaikki 查得到的 2,485 条中 **2,482 条与库内逐字相同(99.9%)**;
        多词次重音核 4,000 条 **96.8% 与 kaikki 一致**。
   `b_ipa.py` 文件头本就写明"对齐 kaikki 约定",`b_ipa_eval.py` 实测 98.42% —— 规则是照抄的,不是写错的。
   → 改它们等于**背离 kaikki**,违反本项目"IPA 归信人工源"的既定策略,属换约定(产品决策),不在本脚本范围。
   ⚠️ 两家模型为什么会齐齐判错:我喂的评审材料里,统计项标题被写成「…**(疑似 coda 浊化过度)**」,
     **把结论写进了提示**。两家收敛的是我的偏见不是事实。**回源核对优先于任何模型共识。**

⭐ 本脚本的判据(不是"模型说它错",而是确定性的):
   **kaikki 里查不到这个词** → 该音标是豆包填的,没有人工源背书;
   **且它违反西语音系或本库既定约定** → 才修。两个条件都满足才动。

三族(都很小,合计约 644 条):
  --cqv   正字法字母 c/q/v 残留 324 条。西语无 /v/ 音位;c/q 是拼写字母不是 IPA 符号。
          例:vamp→ˈvamp、fotovoltaico→fotovoltaˈiko、slapstick→ˈslapstick。
  --lleismo  ʎ 237 条。kaikki 100% 无此词 → 豆包填的,与本库 yeísmo 约定(b_ipa 恒 ll→ʝ)冲突。
          注意:ʎ 本身是合法读音(lleísmo),这里修的是**内部不一致**,不是"ʎ 错"。
  --wraised  w̝ 误用 83 条。w̝ 本身是 kaikki 约定(331 条与 kaikki 一致、0 条冲突),
          但被误用到**字母 w 的外来词**上(software/hardware/watt/Wellington),这些词 kaikki 无、
          且不是 hu+元音结构。只修这 83 条,**不动真 hu- 词的 1,009 条**。

做法:能用 b_ipa 规则重算的就重算(确定、与全库同一套约定);重算不出来的(多词/外文字符)
      走字符级映射兜底。**两条路都先 --dry 打全表人工过一遍再写库。**

默认 --dry(只看不写)。写库前自动备份。用法(在 es/ 目录):
  python3 fix_ipa_residue.py --cqv            # 先看
  python3 fix_ipa_residue.py --cqv --apply    # 再写
"""
import argparse, re, shutil, sqlite3, sys, time
from pathlib import Path

from b_ipa import word_to_ipa

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB

# 字符级替换表。**顺序是判据的一部分**,双字母组合必须排在单字母前面:
#   ch → t͡ʃ 若不先做,`fecha` 会变成 ˈfekha(c→k 之后剩个孤零零的 h);
#   ck → k  同理,`slapstick` 否则变 ˈslapstikk。
# c 的 θ 语境除 e/i/é/í 外**还要含滑音 j** —— 库里 `presencia` 存成 pɾeˈsencja(i 已转写成滑音 j),
#   只看 [eiéí] 会漏判成 k,得出 pɾeˈsenkja。同理 `nacionalización` 的 cio。
FALLBACK = [
    (re.compile(r"ch"), "t͡ʃ"),
    (re.compile(r"ck"), "k"),
    (re.compile(r"qu(?=[eiéí])"), "k"),
    (re.compile(r"q"), "k"),
    (re.compile(r"c(?=[eiéíj])"), "θ"),
    (re.compile(r"c"), "k"),
    (re.compile(r"v"), "b"),
]

FAMS = {
    "cqv": ("正字法 c/q/v 残留", "TRIM(COALESCE(phonetic,''))<>'' AND phonetic GLOB '*[cqv]*'"),
    "lleismo": ("ʎ 与 yeísmo 约定冲突", "phonetic LIKE '%ʎ%'"),
    "wraised": ("w̝ 误用在字母 w 的外来词",
                "phonetic LIKE '%'||char(797)||'%' AND lower(word) NOT LIKE '%hu%'"),
    # ↓ 第二轮:同样先回源核对过 kaikki 才纳入(见文件头判据)
    "trill": ("rɾ/ɾr 双颤音符(kaikki 全无,豆包填坏)",
              "phonetic LIKE '%rɾ%' OR phonetic LIKE '%ɾr%'"),
    "initr": ("词首 ɾ 应为颤音 r", "phonetic LIKE 'ɾ%' OR phonetic LIKE 'ˈɾ%' "
                                 "OR phonetic LIKE '% ɾ%' OR phonetic LIKE '% ˈɾ%'"),
    "bare": ("斜杠/方括号残留(违反裸串存储约定)",
             "phonetic LIKE '%/%' OR phonetic LIKE '%[%'"),
}
# 不纳入的两族(回源核对后否决,别再来动它们):
#   含 h 27 条 —— 8 条与 kaikki 一致(外来词 hard/lahar 西语确有送气读法),不是干净缺陷族。
#   多音节无重音 101 条 —— **66 条与 kaikki 逐字一致**,其余多为逐字母读的缩写(CDT→θe de te),
#     每个字母算独立词、不标主重音是合理的。判官报的 36% 标出率在这族上不成立。


def propose(fam, word, cur):
    """给出建议音标。优先规则重算,失败走字符兜底。返回 (新值, 来源) 或 (None, 原因)。"""
    if fam == "lleismo":
        return cur.replace("ʎ", "ʝ"), "映射 ʎ→ʝ"
    if fam == "wraised":
        return cur.replace("̝", ""), "剥掉升音符 ̝"
    if fam == "trill":
        return re.sub(r"[rɾ]{2,}", "r", cur), "rɾ/ɾr→r"
    if fam == "bare":
        # kaikki 的 sounds 串整个被塞进了格子:`/ˈɡɾaθjas/ [ˈɡɾa.θjas]`。取音位式那段、去斜杠。
        m = re.search(r"/([^/]+)/", cur)
        if m:
            return m.group(1), "取 /音位/ 段"
        return re.sub(r"\s*\[[^\]]*\]\s*", "", cur).strip().strip("/") or None, "剥方括号"
    if fam == "initr":
        # 只在**正字法上确实以 r 开头**的词上改 ɾ→r。
        # 排除:后缀条目(-ra/-re/-res 的 r 是词中音,kaikki 写 ɾ 是对的)、
        #      单字母词(字母名 r 本身 kaikki 就写 ɾ)、词形不以 r 开头的(Hrodna)。
        ws, ps = word.split(), cur.split()
        if len(ws) != len(ps):
            return None, "词数与音标段数不符,不敢动"
        out, hit = [], False
        for ow, op in zip(ws, ps):
            bare = ow.lstrip("-").lower()
            if (not ow.startswith("-") and len(bare) > 1 and bare.startswith("r")
                    and re.match(r"ˈ?ɾ", op)):
                op = re.sub(r"^(ˈ?)ɾ", r"\1r", op); hit = True
            out.append(op)
        return (" ".join(out), "词首 ɾ→r") if hit else (None, "非正字法词首 r")
    # cqv:**只做字符级替换,绝不整条重算**。
    # 2026-07-31 试过用 b_ipa.word_to_ipa 重算,结果很糟 —— 它把外来词按西语正字法重读一遍,
    # 还会重算重音、覆盖掉原本正确的部分:
    #   eigenvector ˈeɡenvektor → eixembeɡˈtoɾ(g 在 e 前被读成 x,整条报废)
    #   Schwartz ˈʃvaɾts → ˈst͡ʃwaɾdθ、rottweiler ˈrotvajleɾ → roddweiˈleɾ、curvy ˈkuɾvi → kuɾˈbi(重音跑了)
    # 这批词恰恰**全是外来词/专名**(kaikki 查不到才轮到豆包填),正是 b_ipa 文件头写明的"借词坑"。
    # → 只把非法字母换掉,其余一个字符都不动,把改动面压到最小。
    out = cur
    for rx, rep in FALLBACK:
        out = rx.sub(rep, out)
    if re.search(r"[cqv]", out):
        return None, "替换后仍有残留"
    return (out, "字符替换") if out != cur else (None, "无变化")


def main():
    ap = argparse.ArgumentParser()
    for k in FAMS:
        ap.add_argument(f"--{k}", action="store_true")
    ap.add_argument("--apply", action="store_true", help="真写库(默认只看)")
    ap.add_argument("--show", type=int, default=40, help="打印前 N 条")
    a = ap.parse_args()
    picked = [k for k in FAMS if getattr(a, k)]
    if not picked:
        ap.print_help(); sys.exit(1)

    conn = sqlite3.connect(str(DB) if a.apply else f"file:{DB}?mode=ro", uri=not a.apply)
    for fam in picked:
        label, cond = FAMS[fam]
        rows = conn.execute(
            f"SELECT id, word, phonetic, is_lemma FROM dict WHERE {cond}").fetchall()
        ups, skips = [], []
        for rid, w, cur, isl in rows:
            new, why = propose(fam, w, cur)
            (ups if new else skips).append((rid, w, cur, new, why, isl))
        print(f"\n{'='*78}\n■ {fam} — {label}:命中 {len(rows)} 条,"
              f"可修 {len(ups)},跳过 {len(skips)}\n{'='*78}")
        src = {}
        for _, _, _, _, why, _ in ups:
            src[why] = src.get(why, 0) + 1
        for k, v in sorted(src.items(), key=lambda x: -x[1]):
            print(f"    来源 {k}: {v}")
        print()
        for rid, w, cur, new, why, isl in ups[:a.show]:
            print(f"  {w[:26]:28} {cur[:26]:28} → {new[:26]:28} [{'lemma' if isl else '变形'}]")
        if len(ups) > a.show:
            print(f"  …(另 {len(ups)-a.show} 条)")
        if skips:
            print(f"\n  ── 跳过的 {len(skips)} 条 ──")
            for rid, w, cur, _, why, _ in skips[:12]:
                print(f"  {w[:26]:28} {cur[:26]:28} ({why})")

        if a.apply and ups:
            bak = HERE / f"synapse-dict-es.pre-{fam}-{time.strftime('%Y%m%d-%H%M')}.bak"
            shutil.copy2(DB, bak)
            print(f"\n  备份 → {bak.name}")
            conn.executemany("UPDATE dict SET phonetic=? WHERE id=?",
                             [(n, r) for r, _, _, n, _, _ in ups])
            conn.commit()
            print(f"  ✅ 已写库 {len(ups)} 条")
        elif not a.apply:
            print("\n  （--dry：未写库。确认无误后加 --apply）")
    conn.close()


if __name__ == "__main__":
    main()
