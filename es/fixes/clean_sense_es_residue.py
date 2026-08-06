#!/usr/bin/env python3
"""清 `sense_es.gloss` 里的 wikitext 残渣。2026-08-05。

送模型翻译**之前**必须先做，理由是项目铁律里那条 payload 纪律：
残渣会被当成释义的一部分翻出来（`:*Sinónimos: escuchar, abrir los ojos`
会变成中文释义里凭空多出一串近义词）。

═══ 全库普查（161,299 条）：数据比预期干净 ═══
    模板 {{}} / 斜体 '' / HTML 标签      0 条
    链接 [[]]                            2 条
    含换行 \\n                          87 条  ← 全部残渣都挂在换行之后
    Ámbito/Sinónimos/Ejemplo 标注       70 条
形态只有三种，都是**正文之后**跟一段 wiki 列表项：

    Carne … cocinada a las brasas.\\n:*Ámbito: Argentina, Chile, Perú
    Poner atención …\\n:*Sinónimos: escuchar, abrir los ojos, aguzar el oído
    :*Ejemplo: sombrerero → sombrerería

⇒ **切掉第一个换行之后的 `:*` 段**，正文保留。少数整条就是 `:*…` 的（12 条以冒号开头），
   正文为空 → 那条本来就不是释义，标记出来单独看，不自作主张删。

🔴 为什么不用「把 Ámbito 的内容搬进 tags」这种更聪明的做法：
   70 条而已，搬运要写解析、要定 tag 词表、要处理 `Ámbito: Argentina, Chile, Perú`
   与我们既有地区标签的对应——为 70 条引入一套映射，错的风险比收益大。
   **正文保住、残渣切掉**就够了；真要地区信息，源头 `tags` 列里本来就有。

用法：
    python3 -m es.fixes.clean_sense_es_residue          # 只报告
    python3 -m es.fixes.clean_sense_es_residue --apply  # 写库
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 一条 wiki 列表项：行首若干 : 或 *，后面跟内容，直到行尾
RESIDUE_LINE = re.compile(r"^\s*[:*]+\s*.*$", re.M)


def clean(g: str):
    """→ (清洗后正文, 被切掉的部分)。正文为空说明整条都是残渣。"""
    # 换行之后的 `:*` 段全切；正文内部的换行压成空格（既有管线的约定）
    parts = g.split("\n")
    body, cut = [], []
    for p in parts:
        (cut if RESIDUE_LINE.match(p) else body).append(p.strip())
    text = " ".join(x for x in body if x).strip()
    text = re.sub(r"\s{2,}", " ", text)
    return text, [x for x in cut if x]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT id, word, gloss FROM sense_es "
        "WHERE gloss LIKE '%'||char(10)||'%' OR gloss LIKE '%[[%'").fetchall()
    con.close()

    plan, empties = [], []
    for rid, w, g in rows:
        text, cut = clean(g)
        if not text:
            empties.append((w, g))          # 整条都是残渣，不动，单独列出来
            continue
        if text != g:
            plan.append((rid, w, g, text, cut))

    print(f"命中 {len(rows)} 条，可清洗 {len(plan)} 条，正文为空 {len(empties)} 条")
    print("\n■ 清洗前后对照（前 8 条）：")
    for _, w, old, new, cut in plan[:8]:
        print(f"  {w}")
        print(f"    改前 {old[:96]!r}")
        print(f"    改后 {new[:96]!r}")
        print(f"    切掉 {cut}")

    # 🔴 项目教训：「跳过」那一栏必须逐条看得见
    if empties:
        print(f"\n⚠️ 整条都是 wiki 残渣、没有正文，**原样不动**（{len(empties)} 条）：")
        for w, g in empties:
            print(f"    {w:<22}{g[:76]!r}")

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    # 建新表不碰 dict ⇒ expect={}；sense_es 不在 snapshot 视野内，自己断言
    with dbtool.session("clean-sense-es-residue", expect={}) as s:
        s.executemany("UPDATE sense_es SET gloss=? WHERE id=?",
                      [(new, rid) for rid, _, _, new, _ in plan])

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    left = con.execute(
        "SELECT COUNT(*) FROM sense_es WHERE gloss LIKE '%'||char(10)||'%'").fetchone()[0]
    empty = con.execute(
        "SELECT COUNT(*) FROM sense_es WHERE TRIM(COALESCE(gloss,''))=''").fetchone()[0]
    con.close()
    print(f"\n落库后：仍含换行 {left} 条（= 上面那 {len(empties)} 条无正文的），空 gloss {empty} 条")
    assert empty == 0, "清洗把某条 gloss 清空了"


if __name__ == "__main__":
    main()
