#!/usr/bin/env python3
"""
从原形 kaikki IPA 向变位形继承 e/o 开闭 —— 补 G2P 的先天缺陷。

背景：意语 e/ɛ、o/ɔ 是音位对立（pésca 钓鱼 / pèsca 桃子），但**不在拼写里**、拼写规则推不出。
b_ipa_fill.py 的 G2P 只在输入带 è/ò 时才出开 ɛ/ɔ，而 kaikki forms 数组的变位形拼写极少带开闭标注，
于是 43 万变位形几乎一律默认闭 e/o —— prove(应 /ˈprɔve/) 被填成 /ˈpro.ve/、sono/siete/quote/crepe… 同错。

钥匙：开闭是**词根的词汇属性**，在一个词的所有变位形里稳定不变；而**原形的 kaikki IPA 记对了开闭**
（cielo /ˈt͡ʃɛlo/、prova /ˈprɔva/）。故：拿原形 kaikki IPA 的重读元音开闭，覆盖变位形 G2P 的默认闭音。

安全对齐（高精度、宁缺毋滥）：只在【原形与变位形的重读音节 声母+韵核同类】时继承——
  · prova /ˈprɔ.va/(声母 pr, 韵 o类, 开) → prove /ˈpro.ve/(声母 pr, 韵 o类) ⇒ 改 /ˈprɔ.ve/  ✓
  · essere → sono/siete：补充式，声母不匹配 ⇒ **跳过**（不误伤，宁可留 G2P 原值）
只改 e/o 一位、其余 IPA 原样保留。原形开闭一律取自 **kaikki JSONL 的 sounds**（纯 kaikki，
不碰豆包/G2P 写进 DB 的 lemma ipa，杜绝污染）。

用法（在 it/ 目录）：
  python3 b_ipa_inherit.py            # --dry 默认：只统计+抽样，不写库
  python3 b_ipa_inherit.py --write    # 写回 DB（先自动备份 .inherit.bak）
  python3 b_ipa_inherit.py --sample 40   # 抽样条数
"""
import argparse
import json
import re
import shutil
import sqlite3
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
JSONL_PATH = HERE / "kaikki.org-dictionary-Italian.jsonl"
DB_PATH = HERE / "synapse-dict-it.sqlite"

VOWELS = set("aeiouɛɔ")
# 重读韵核为 e类/o类 时，抓 (ˈ 之后的声母串, 韵核字母)
STRESS_RE = re.compile(r"ˈ([^aeiouɛɔ]*)([eɛoɔ])")


def strip_marks(s):
    """归一化声母串比较用：去连结弧、长音符、音节点、次重音、空格。"""
    return (s.replace("͡", "").replace("ː", "").replace(".", "")
             .replace("ˌ", "").replace(" ", ""))


def stressed_eo(ipa):
    """返回 (声母归一, 'e'/'o' 类, is_open) 或 None（重读非 e/o、或无主重音）。"""
    if not ipa:
        return None
    inner = ipa.strip().strip("/")
    m = STRESS_RE.search(inner)
    if not m:
        return None
    onset, nuc = m.group(1), m.group(2)
    cat = "e" if nuc in "eɛ" else "o"
    return (strip_marks(onset), cat, nuc in "ɛɔ")


def flip_stressed(ipa, to_open):
    """把 ipa 主重读的 e/o 韵核改成 开(to_open=True)或闭。只动那一位，返回新串。"""
    inner_has_slash = ipa.strip().startswith("/")
    s = ipa
    m = STRESS_RE.search(s)
    if not m:
        return ipa
    pos = m.start(2)          # 韵核字符位置
    ch = s[pos]
    new = {"e": "ɛ", "ɛ": "e", "o": "ɔ", "ɔ": "o"}
    cur_open = ch in "ɛɔ"
    if cur_open == to_open:
        return ipa            # 已是目标开闭
    return s[:pos] + new[ch] + s[pos + 1:]
    _ = inner_has_slash


def build_lemma_quality():
    """从 kaikki JSONL 抽 word(lower) → (stressed_eo, pos集合)。纯 kaikki。
    pos 集合用于**排除动词**：动词变位重音常落后缀(-endo/-ente/-ò 自带开音)，
    拼写对齐分不清是词根 e 还是后缀 e，继承词根质量会误伤 → 只对纯名词/形容词继承。"""
    q = {}          # word -> stressed_eo(第一个可用 sounds.ipa)
    pos = {}        # word -> set(pos)
    n_ipa = 0
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "it":
                continue
            w = (e.get("word") or "").strip().lower()
            if not w:
                continue
            pos.setdefault(w, set()).add(e.get("pos") or "")
            if w in q:
                continue
            for snd in e.get("sounds") or []:
                ipa = snd.get("ipa")
                if not ipa:
                    continue
                info = stressed_eo(ipa)
                q[w] = info            # 可能 None（重读非 e/o）；占位防重复扫
                if info is not None:
                    n_ipa += 1
                break
    print(f"kaikki lemma 质量表：{len(q)} 词（其中重读含 e/o 的 {n_ipa}）")
    return q, pos


def stem(w):
    """去掉词尾极大元音串 → 词干。用于判「只差词尾元音」的名形变位。
    prova→prov / prove→prov / studio→stud / studi→stud（放行）；
    avere→aver / avente→avent / avendo→avend（词干变 → 排除动词形）。"""
    return w.rstrip("aeiouàèéìíòóù")


def first_base(exchange):
    if not exchange:
        return None
    for line in exchange.splitlines():
        line = line.strip()
        if not line:
            continue
        idx = line.find(":")
        b = (line[idx + 1:] if idx >= 0 else line).strip()
        if b:
            return b.lower()
    return None


def main(dry, sample):
    lq, lpos = build_lemma_quality()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, word, ipa, exchange FROM dict "
        "WHERE is_lemma=0 AND ipa IS NOT NULL AND ipa!=''").fetchall()

    n_scan = len(rows)
    n_base_hit = n_nominal = n_cat_hit = n_onset_hit = 0
    n_change = 0
    to_open = to_close = 0
    updates = []           # (id, new_ipa)
    samples = []
    for r in rows:
        b = first_base(r["exchange"])
        if not b:
            continue
        linfo = lq.get(b)
        if not linfo:
            continue
        n_base_hit += 1
        # 只放行「与原形仅差词尾元音」的名形变位（词干相同 → 重音必在同一词根音节）。
        # 动词形换的是后缀(-endo/-ente/-ò，自带开音)，词干会变，据此排除 → 不误伤。
        # 这比按 pos 判更干净：意语几乎每个名词都与某动词形同形(prova=名词/也是 provare 三单)，
        # 按「有动词读音就排除」会误杀 prove/quote/concrete；按词干只差尾元音则精确放行。
        if stem(r["word"].lower()) != stem(b):
            continue
        n_nominal += 1
        iinfo = stressed_eo(r["ipa"])
        if not iinfo:
            continue
        l_onset, l_cat, l_open = linfo
        i_onset, i_cat, i_open = iinfo
        if l_cat != i_cat:
            continue
        n_cat_hit += 1
        if l_onset != i_onset:
            continue
        n_onset_hit += 1
        # **只做闭→开一个方向**：G2P 系统性把音位开 ɛ/ɔ 默认成闭 e/o，这是要修的确定 bug。
        # 反方向(开→闭)已验不可靠：kaikki 多读音取第一个是任意的(criceto/nesso/nome 都双读音)、
        # 混脏数据(grembo=/paˈta.ta/)、多为俗写变体(perchè)，且会把 G2P 正确的开音改错 → 一律跳过。
        if not (l_open and not i_open):
            continue
        new_ipa = flip_stressed(r["ipa"], l_open)
        if new_ipa == r["ipa"]:
            continue
        n_change += 1
        if l_open:
            to_open += 1
        else:
            to_close += 1
        updates.append((r["id"], new_ipa))
        if len(samples) < sample:
            samples.append((r["word"], r["ipa"], new_ipa, b))

    print(f"\n扫描变位形(有ipa) {n_scan}")
    print(f"  原形在 kaikki 质量表   {n_base_hit}")
    print(f"  与原形仅差尾元音(名形变位) {n_nominal}")
    print(f"  韵核同类(e/o)          {n_cat_hit}")
    print(f"  声母也匹配(安全对齐)   {n_onset_hit}")
    print(f"  ⇒ 需改开闭            {n_change}（闭→开 {to_open} / 开→闭 {to_close}）")
    print(f"\n抽样（word / 旧 / 新 / 原形）:")
    for w, old, new, b in samples:
        print(f"   {w:22} {old:18} → {new:18} <- {b}")

    if dry:
        print(f"\n[dry] 未写库。确认无误后： python3 b_ipa_inherit.py --write")
        conn.close()
        return

    bak = DB_PATH.with_suffix(".sqlite.inherit.bak")
    shutil.copy(DB_PATH, bak)
    print(f"\n已备份 {bak.name}，写回 {len(updates)} 条…")
    conn.executemany("UPDATE dict SET ipa=? WHERE id=?",
                     [(ni, i) for i, ni in updates])
    conn.commit()
    conn.close()
    print("完成。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--sample", type=int, default=30)
    args = ap.parse_args()
    main(dry=not args.write, sample=args.sample)
