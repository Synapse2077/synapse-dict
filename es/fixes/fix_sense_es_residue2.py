#!/usr/bin/env python3
"""清 `sense_es` 第二批脏数据：残渣行、粘连义项、非释义行。2026-08-06。

═══ 这批是**模型帮我们找出来的** ═══
10.4 万条翻译跑完后，有 5 个词无论重试几次，模型给出的义项条数都和输入对不上，
而且**每次都错同一个数**——不是随机波动，是输入有问题。挨条看原文才发现三类脏数据，
它们全都躲过了昨天那轮清洗（`clean_sense_es_residue.py`）：

  昨天的 WHERE 是 `gloss LIKE '%换行%' OR '%[[%'`，
  而这批残渣**整行开头就是 `:*`，前面没有换行** ⇒ 整批漏网。

⭐ 值得记：模型拒绝翻译这些行，是**正确行为**，它当了一次免费的数据校验器。
   如果当初对不上条数时按下标硬对，这些垃圾就会被当成义项译出来并落库。

═══ 四类，逐条列过、逐条判过（共 21 条，全库 164,338 条的 0.01%）═══
① 纯残渣 15 条 → **删**。整行是维基列表项，不是释义：
     :*Sinónimos: hierba del sapo, cabezona…     :*Ámbito: Perú
     :*Ejemplo: sombrerero → sombrerería          *Derivado: correazo
② 非释义 1 条 → **删**。`acetona` 的一条"义项"是化学反应式：
     C₆H₅CH(CH₃)₂ + O₂ → C₆H₅OH + OC(CH₃)₂
③ 被误伤的真释义 2 条 → **剥掉前缀 `: ` 保留**。它们只是前面多了个冒号：
     `flotación`：": Acción de dejar que la moneda tome el valor que fija el mercado…"
     `nota`     ：": Cada uno de los sonidos que tienen una frecuencia de oscilación…"
   🔴 这两条差点被我按"以 : 开头"一起删掉 —— 判据是**看内容**不是看前缀。
④ `;N:` 粘连 3 条 → **拆成 6 条**。维基义项编号残留把两条义项粘在一起：
     "…abierta a las ideas de los demás.;6: Disposición a la tolerancia…"
   ⚠️ `medianoche` 的 "Mitad de la noche; 12:00 am; …" 也匹配 `;\\d+:`，
     但那是**时间不是分隔符** —— 正则误报，不动它。

处理方式：受影响的词整词重建（读出全部义项 → 变换 → 重新编号 0..n-1 → 删旧插新），
`zh` / `en_i` 随行携带，不会错位。

用法：
    python3 -m es.fixes.fix_sense_es_residue2
    python3 -m es.fixes.fix_sense_es_residue2 --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 逐条核过的 id，不用正则现扫 —— 21 条而已，写死比"再匹配一次"可靠
DROP_IDS = {415, 56066, 58684, 58687, 61448, 61846, 69791, 73647,
            109315, 109316, 120783, 136533, 158892, 158894}      # ① 纯残渣 14
STRIP_IDS = {91931, 120343}                                      # ③ 剥前缀保留 2
SPLIT_IDS = {44998, 87445, 90737}                                # ④ 粘连拆分 3
ACETONA_FORMULA = "C₆H₅CH(CH₃)₂"                                  # ② 靠内容认，别靠 id

# ⑤ 抢救：垃圾前缀后面跟着真内容的，剥前缀而不是整条删。
#    `Kaliningrado` 差点被我按"以 :* 开头"一起删掉 —— 前缀之后是
#    "es un puerto de Rusia en el Mar Báltico, Capital de la provincia homónima,
#     situada cerca de la desembocadura del río Pregolja…"，
#    这些细节比库里现有的英文释义还多。**判据永远是看内容，不是看前缀。**
SALVAGE = {17787: ":*Nombre oficial: 1 csem, ciudades: Ciudad, "}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    drop_ids = {i for i in DROP_IDS if isinstance(i, int)}
    for i, g in con.execute("SELECT id, gloss FROM sense_es WHERE word='acetona'"):
        if ACETONA_FORMULA in g:
            drop_ids.add(i)

    words = set()
    for i, w in con.execute("SELECT id, word FROM sense_es"):
        if i in drop_ids or i in STRIP_IDS or i in SPLIT_IDS or i in SALVAGE:
            words.add(w)

    plans = {}
    for w in sorted(words):
        rows = con.execute(
            "SELECT id, idx, gloss, pos, pos_title, tags, raw_tags, zh, zh_src, src, "
            "src_word, dict_id, en_i FROM sense_es WHERE word=? ORDER BY idx", (w,)).fetchall()
        out = []
        for r in rows:
            rid, _idx, gloss = r[0], r[1], r[2]
            rest = r[3:]
            if rid in drop_ids:
                continue
            if rid in SALVAGE:
                body = gloss.replace(SALVAGE[rid], "", 1).strip()
                out.append((body[:1].upper() + body[1:], *rest))
            elif rid in STRIP_IDS:
                out.append((gloss.lstrip(": *").strip(), *rest))
            elif rid in SPLIT_IDS:
                import re
                parts = [p.strip() for p in re.split(r";\s*\d+\s*:", gloss) if p.strip()]
                for p in parts:
                    out.append((p, *rest))
            else:
                out.append((gloss, *rest))
        plans[w] = (rows, out)
    con.close()

    print(f"受影响 {len(plans)} 个词")
    for w, (old, new) in plans.items():
        flag = "" if len(old) == len(new) else f"  {len(old)}→{len(new)} 条"
        print(f"\n  {w}{flag}")
        for g, *_ in new:
            print(f"      {g[:84]}")
        dropped = [r[2] for r in old if r[0] in drop_ids]
        for d in dropped:
            print(f"      ✗ 删 {d[:80]}")

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    ins = []
    for w, (_old, new) in plans.items():
        for i, row in enumerate(new):
            gloss, pos, pos_title, tags, raw_tags, zh, zh_src, src, src_word, did, en_i = row
            ins.append((w, did, i, gloss, pos, pos_title, tags, raw_tags,
                        zh, zh_src, src, src_word, en_i))

    with dbtool.session("fix-sense-es-residue2", expect={}) as s:
        for w in plans:
            s.execute("DELETE FROM sense_es WHERE word=?", (w,))
        s.executemany(
            "INSERT INTO sense_es(word,dict_id,idx,gloss,pos,pos_title,tags,raw_tags,"
            "zh,zh_src,src,src_word,en_i) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ins)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM sense_es").fetchone()[0]
    dup = con.execute("SELECT COUNT(*) FROM (SELECT word,idx FROM sense_es "
                      "GROUP BY 1,2 HAVING COUNT(*)>1)").fetchone()[0]
    orph = con.execute("SELECT COUNT(*) FROM sense_es WHERE dict_id NOT IN "
                       "(SELECT id FROM dict)").fetchone()[0]
    con.close()
    print(f"\n落库后 sense_es {n:,} 行   (word,idx) 重复 {dup}   悬空 dict_id {orph}")
    assert dup == 0 and orph == 0


if __name__ == "__main__":
    main()
