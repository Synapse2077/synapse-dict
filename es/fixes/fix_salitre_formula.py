#!/usr/bin/env python3
"""改正 `salitre` 中文详解里的化学式：硝酸钠 NaNO₂ → NaNO₃。2026-09-13。

═══ 怎么发现的（顺带说明为什么值得写成脚本）═══
2026-09-13 解开 es 的真人录音展示时，契约闸的取样面从「今天动过的三族」扩到
「**有录音的 9,709 个词形**」，`salitre` 第一次被渲染到，当场报红：
「页面文字里出现 NaN」。那是**假红** —— `NaNO₂` 里恰好含 `NaN`，判据用 `includes` 太宽
（已在 `contract-check-es.tsx` 收窄成独立词匹配）。但顺着假红看见了**真错**：

    富含硝酸钾（KNO₃）和硝酸钠（NaNO₂）的矿物……
                    ↑ 硝酸钠 = NaNO₃；NaNO₂ 是**亚硝酸钠**，另一种东西

⭐ 判据不是"我觉得应该是 ₃"，是这句话**自己跟自己打架**：中文写的是「硝酸钠」，
   化学式却给了亚硝酸钠。另有旁证：智利硝石（Chile saltpeter）本就是硝酸钠。

═══ 🔴 最要紧的一条：错在**源头**，不在翻译 ═══
回源看 `sense_src`，es.wiktionary 的原文写的就是 `nitrato sódico (Na NO₂)` ——
连空格带下标都错。也就是说 llm-flash 的中文是**忠实翻译了一个错的源**，不是译错。
⇒ 所以本脚本**只改中文两处（我们自己的出版文本），三处西语原文一个字不动**：
   · `sense_gloss`（zh/definition）—— 出版层，页面上读者看的那一句
   · `sense_es.zh`             —— 西语版义项层的同一句中文（两处不改齐会漂开）
   · ❌ `sense_src.text`        —— **证据层，永远是源头原样**（[[two-layer-sense-model]]）
   · ❌ `sense_gloss`（es/definition）/ `sense_es.gloss` —— 页面上挂在 `ES` 徽标下面的
        **引文**。把引文改成源头没说过的话，比留着源头的错更糟。
   ⇒ 页面因此会出现「中文 NaNO₃ / ES 引文 Na NO₂」的可见差异。那是**诚实的状态**：
     我们的话是对的，被引的源有笔误，读者点开原文能自己核对。

═══ 顺带核过 ═══
六门语言全库大小写敏感扫 `NaNO₂` / `Na NO₂` / `NaNO2`，除本词外只有 en 的
`sodium nitrite`「The sodium salt of nitrous acid, NaNO₂」—— 那条是**对的**，不动。

用法（仓库根）：
    python3 -m es.fixes.fix_salitre_formula
    python3 -m es.fixes.fix_salitre_formula --apply
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402

WRONG, RIGHT = "硝酸钠（NaNO₂）", "硝酸钠（NaNO₃）"

# 🔴 只改中文两处。**逐处写死表名与判据**，不写成「全库 replace 'NaNO₂'」——
#    那种写法会连西语引文和证据层一起扫掉，正是本脚本存在的理由要避免的事。
#    判据同时卡 `lang='zh'`，哪怕将来这两行的 id 变了也不会误伤西语行。
PLAN = [
    ("sense_gloss",
     "UPDATE sense_gloss SET text = REPLACE(text, ?, ?) "
     "WHERE lang='zh' AND instr(text, ?) > 0",
     "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND instr(text, ?) > 0"),
    ("sense_es",
     "UPDATE sense_es SET zh = REPLACE(zh, ?, ?) "
     "WHERE zh IS NOT NULL AND instr(zh, ?) > 0",
     "SELECT COUNT(*) FROM sense_es WHERE zh IS NOT NULL AND instr(zh, ?) > 0"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with dbtool.session("fix-salitre-formula", dry=not args.apply) as s:
        for tbl, upd, cnt in PLAN:
            n_before = s.execute(cnt, (WRONG,)).fetchone()[0]
            print(f"   {tbl}: 待改 {n_before} 处")
            if args.apply and n_before:
                s.execute(upd, (WRONG, RIGHT, WRONG))
                s.written += n_before

    # 写后复查走**新开的只读连接**，不复用会话里那条 —— 会话里读到的是未提交的视图，
    # 等于拿自己的中间状态给自己发合格证（[[verification-gates-not-sampling]]）。
    if args.apply:
        import sqlite3
        c = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
        left = (c.execute("SELECT COUNT(*) FROM sense_gloss WHERE instr(text,?)>0", (WRONG,)).fetchone()[0]
                + c.execute("SELECT COUNT(*) FROM sense_es WHERE instr(COALESCE(zh,''),?)>0", (WRONG,)).fetchone()[0])
        got = (c.execute("SELECT COUNT(*) FROM sense_gloss WHERE instr(text,?)>0", (RIGHT,)).fetchone()[0]
               + c.execute("SELECT COUNT(*) FROM sense_es WHERE instr(COALESCE(zh,''),?)>0", (RIGHT,)).fetchone()[0])
        # 证据层与西语引文必须**一处没动** —— 这条断言就是本脚本的边界，缺了它
        # 「只改中文」只是注释里的一句话，不是机制（[[lesson-must-become-mechanism]]）。
        src = c.execute("SELECT COUNT(*) FROM sense_src WHERE instr(text,?)>0", ("Na NO₂",)).fetchone()[0]
        es_quote = (c.execute("SELECT COUNT(*) FROM sense_gloss WHERE instr(text,?)>0", ("Na NO₂",)).fetchone()[0]
                    + c.execute("SELECT COUNT(*) FROM sense_es WHERE instr(gloss,?)>0", ("Na NO₂",)).fetchone()[0])
        c.close()
        print(f"\n■ 复查：残留 {WRONG} {left} 处｜已是 {RIGHT} {got} 处｜"
              f"西语原文原样保留 证据层 {src} + 引文 {es_quote} 处")
        if left or got != 2 or src != 1 or es_quote != 2:
            raise SystemExit("🔴 复查不符")
        print("■ 复查通过 ✓")


if __name__ == "__main__":
    main()
