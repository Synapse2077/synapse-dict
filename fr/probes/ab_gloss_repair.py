#!/usr/bin/env python3
"""收尾单 A5 的**盲测 A/B 复核** —— 我重写的 816 条释义，到底比旧的好还是坏。2026-08-28。

═══ 为什么还要这一步 ═══
A5 的第④道闸是「旧的判错、新的判对才替换」，可那两次判断**是同一个判官**下的。
`[[llm-as-evaluator-discipline]]` 第⑥条：谁写的就不能由谁判。
判官说新的对，只说明它自己前后一致，**不说明新的真比旧的好**。
⇒ 拿旧新两版并排、**不说哪个是新的**，交给两家外部模型盲判。

═══ 盲测怎么盲 ═══
· 甲/乙 的顺序按 `sense_id` 的奇偶决定 —— 确定性、可复现，而我事先不知道哪条落哪边
· 材料里**不出现**「旧」「新」「修复」「重写」这些词（第⑨条：别把结论写进材料）
· 允许「两个都不对」和「差不多」——**不给二选一的强制选择**，否则会造出 50% 的假胜率
· 权威源（法语定义）逐条给出（第⑧条）

用法（在 fr/ 目录下）：
    python3 -u probes/ab_gloss_repair.py --n 60
    python3 scripts/consult.py data/work/fr/senses/ab_gloss.md --out data/work/fr/senses
"""
import argparse
import random
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                   # noqa: E402

OUT = paths.WORK / "senses" / "ab_gloss.md"
SRC = "model:gloss:a5fix"

HEAD = """# 法汉词典：两版中文释义，哪一版说的是法语定义说的那件事

下面每条给出一个法语词条的一条义项：`词条`、`词性`、**法语定义（权威源，一切以它为准）**，
以及两版候选中文释义 `甲` 和 `乙`。

请逐条判断：**哪一版说的是这条法语定义说的那件事。**

取值只能是这四个之一，写在行首：
- `甲` —— 甲对，乙不对（或明显更差）
- `乙` —— 乙对，甲不对（或明显更差）
- `都对` —— 两版说的是同一件事，只是措辞不同
- `都不对` —— 两版说的都不是这条法语定义说的意思

判断纪律
1. **以法语定义为准。** 不要按你对这个法语词的整体印象判，只看这一条定义。
2. **简练不等于错。** 法语写一整句、中文只有两三个字，只要那两三个字就是这个概念本身，就算对。
3. **词性要对上**：`Qui…` / `Qualifie…` 是形容词性描述，中文该是「…的」；
   `Celui qui…` / `Celle qui…` 指的是人，中文该是名词。
4. 法语定义只有一个词时，那是**交叉引用** —— 它指的是那个词在这个词条上适用的那一支意思。
5. 拿不准就给 `都对`。

输出格式：每条一行 `<编号> <取值> <一句话理由>`。**每一条都要有一行**，不要跳过。
不要复述我给你的内容，不要写总结。

---

"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    a = ap.parse_args()

    # 旧值从**写库前的自动备份**里取 —— 这一步顺带证明了备份是可用的。
    baks = sorted(paths.BACKUPS.glob("synapse-dict-fr.pre-keep-v3-a5-gloss-wrong-*.bak"))
    if not baks:
        sys.exit("🔴 找不到 A5 落库前的备份，无法取旧值")
    new = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    old = sqlite3.connect("file:%s?mode=ro" % baks[-1], uri=True)
    print("■ 旧值取自 %s" % baks[-1].name)

    rows = new.execute(
        "SELECT s.id, d.word, s.pos, "
        "  (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='fr' ORDER BY seq LIMIT 1), "
        "  (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' ORDER BY seq LIMIT 1) "
        "FROM sense s JOIN dict d ON d.id=s.word_id "
        "WHERE s.id IN (SELECT sense_id FROM sense_gloss WHERE lang='zh' AND src=?)", (SRC,)
    ).fetchall()
    pick = random.Random(20260828).sample(rows, min(a.n, len(rows)))

    out, key = [], []
    for n, (sid, w, pos, fr, zh_new) in enumerate(pick, 1):
        o = old.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' "
                        "ORDER BY seq LIMIT 1", (sid,)).fetchone()
        if not o or not fr:
            continue
        zh_old = o[0]
        # 顺序由 sense_id 奇偶定 —— 确定性、可复现，而我事先不知道哪条落哪边
        first_is_new = (sid % 2 == 0)
        jia, yi = (zh_new, zh_old) if first_is_new else (zh_old, zh_new)
        key.append((n, sid, w, "甲" if first_is_new else "乙", zh_old, zh_new))
        out.append("%d. **%s**（%s）\n   法语定义：%s\n   甲：%s\n   乙：%s\n"
                   % (n, w, pos or "?", " ".join(fr.split()), jia, yi))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HEAD + "\n".join(out), encoding="utf-8")
    (OUT.parent / "ab_gloss.key.tsv").write_text(
        "\n".join("%d\t%d\t%s\t%s\t%s\t%s" % k for k in key), encoding="utf-8")
    print("✓ %d 条 → %s（%.0f KB）；答案表 → ab_gloss.key.tsv"
          % (len(out), OUT, len(OUT.read_bytes()) / 1024))
    new.close()
    old.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
