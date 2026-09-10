#!/usr/bin/env python3
"""撤掉阶段 1.5b「免费直接贴」的 11,479 条 ECDICT 原文，交给 1.5c 重翻。2026-09-10。

═══ 用户看页面看出来的 ═══
    mariposa
    释义  名词
      n. = mariposa lily 蝴蝶百合；<西>斗牛士在身后挥动披风的逗牛动作
      EN A mariposa lily (Calochortus spp.).
用户问了两件事：「上面标出了名词，为什么下面还有个 n 呢」「明明是两个解释，
为什么要放到一行」。两件是同一个根：**这条中文是 ECDICT 词条级原文，原样贴进了义项级字段。**

═══ 🔴 判据错在哪 ═══
`translate_defs.pool()` 里免费贴的四个条件：

    qual in ("core",)                        # 质量桶
    and real.get(wid, 0) == 1                # 这个词只有一条实义项
    and len(set(POS_RE.findall(txt))) <= 1   # ECDICT 那行只有一个词性码
    and "\\n" not in txt                      # 只有一行

**四条全是形式判据。「这段中文说的是不是就是这条英文义项」—— 从来没验过。**
`mariposa` 四条全过：1 条义项 ✓ 1 个词性码 ✓ 单行 ✓ core 桶 ✓ —— 而它错了一半。

⇒ `[[criteria-narrower-than-you-think]]`：我拿「几行、几个词性」当了「几个意思」的代理。
   **「这个词只有一条 kaikki 义项」不等于「ECDICT 那条说的就是它」。**

═══ 实测：错的那类没有分号也一样错 ═══
抽读 14 条多段的，大多数其实没问题（`beautifully` 美好地／出色地是同一个意思的两种说法）。
真错的是另一类：

    Te      EN The realm of the dead in Egyptian mythology.  ← 埃及神话的冥界
            [化] 碲（52号元素）；[医] 破伤风                   ✗ 完全无关
    scores  EN A bag of cannabis worth £20.                  ← 一包大麻
            大量，众多；二十；得分；百分数                     ✗ 完全无关
    battlefield  EN The area where a land battle is fought…  ← 字面义
                 战场，沙场；争论领域，斗争舞台                ✗ 后半是比喻义，属另一条义项

⇒ **分号本身也是形式代理**，不能按它拆、也不能按它删。唯一能治的是回到内容。

顺带一个免费信号：拿 ECDICT 的词性码去对 `sense.pos`（`n`≈`name` 视为相容，
ECDICT 没有「专名」这一类），**202 条对不上**，其中一眼可见的真错配：

    hippy  ECDICT n. 嬉皮士  ←→ 义项 pos=adj（"having wide hips"）
    tarp   ECDICT n. 防水布  ←→ 义项 pos=v（"to cover with a tarp"）

═══ 为什么是「删掉重翻」而不是「剥前缀 + 按分号拆」 ═══
后者治得了 `n.` 和分号，**治不了 `Te` 和 `scores`** —— 那是内容错，不是格式错。
而 1.5c 那条付费路径本来就同时管这三件事：
  · 输出**词典体**（`RULES` 第 1 条）⇒ 不带词性码
  · 多个近义中文用「，」分隔、不同义项不合并（第 2 条）
  · **`ref` 规则**（`ANCHOR_RULE` 第 8 条）原文：
      「语义确实吻合 → 可以采用它的用词与术语选择；**不吻合 → 完全无视它**，
        按 `en` 的意思译。绝不把 `ref` 里与本义项无关的部分抄进输出。」
    —— 这正是 1.5b 缺的那道内容检查，只不过它由模型在翻译时顺带做掉。
译出来的口径还与另外 106 万条 `model:def` 一致，库里不再有一撮外来格式。

═══ 本脚本只做一件事 ═══
删掉 `sense_gloss` 里 `src='ecdict-core'` 的行。之后：
    python3 -m en.pipeline.translate_defs --plan      # 确认它们进了付费池
    python3 -m en.pipeline.translate_defs --run
    python3 -m en.pipeline.translate_defs --apply

🔴 `translate_defs.pool()` 的免费分支**必须同时删掉**，否则 `--plan` 会把它们
   原样再算回 `free`，跑了等于没跑（`[[replay-scripts-undo-fixes]]`：
   修复会被后一步静默撤销）。本脚本的闸④直接查那份源码，改漏了就报红。

用法（仓库根目录）：
    python3 -m en.fixes.redo_ecdict_core_gloss            # 干跑
    python3 -m en.fixes.redo_ecdict_core_gloss --apply
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SRC = "ecdict-core"
POS_RE = re.compile(r"^\s*([a-z]{1,6}\.)\s*")
# ECDICT 没有「专名」这一类，国名/人名一律记 `n.` ⇒ n≈name 视为相容，不算冲突
POS_MAP = {"n.": "n", "v.": "v", "vt.": "v", "vi.": "v", "a.": "adj", "adj.": "adj",
           "ad.": "adv", "adv.": "adv", "pron.": "pron", "prep.": "prep",
           "conj.": "conj", "num.": "num", "int.": "intj", "art.": "art", "aux.": "v"}
COMPAT = {("n", "name"), ("name", "n")}
DEFS = Path(__file__).resolve().parent.parent / "pipeline" / "translate_defs.py"


def survey(con):
    """→ (rows, 统计)。**只读，不改任何东西。**"""
    q = con.execute
    rows = q("""SELECT g.sense_id, g.text, s.pos, d.word FROM sense_gloss g
                JOIN sense s ON s.id = g.sense_id
                JOIN dict d ON d.id = s.word_id
                WHERE g.lang = 'zh' AND g.src = ?""", (SRC,)).fetchall()
    pos_pref = sum(1 for _, t, _, _ in rows if POS_RE.match(t))
    semi = sum(1 for _, t, _, _ in rows if "；" in t or ";" in t)
    dis = []
    for sid, t, pos, w in rows:
        m = POS_RE.match(t)
        if not m:
            continue
        want = POS_MAP.get(m.group(1))
        if want is None or want == pos or (want, pos) in COMPAT:
            continue
        dis.append((w, m.group(1), pos))
    return rows, {"pos_pref": pos_pref, "semi": semi, "pos_conflict": dis}


def gates(con, rows, stat):
    """🔴 删之前先证明「我删的就是我说的那一批，一条不多一条不少」。"""
    q = con.execute
    n = len(rows)
    total = q("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND src=?", (SRC,)).fetchone()[0]
    # ① 这批义项**只有**这一条中文 —— 删完它们就没中文了，正是要交给 1.5c 的那批。
    ids = [s for s, _, _, _ in rows]
    multi = 0
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        multi += q("SELECT COUNT(*) FROM (SELECT sense_id FROM sense_gloss "
                   "WHERE lang='zh' AND sense_id IN (%s) GROUP BY 1 HAVING COUNT(*)>1)"
                   % ",".join("?" * len(chunk)), chunk).fetchone()[0]
    # ② 一条都不许碰别的来源
    others = q("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND src<>?", (SRC,)).fetchone()[0]
    # ③ 负控：这批词的 `legacy_gloss` 原文**必须一个字节不动**（重翻要拿它当锚）
    lg = q("SELECT COUNT(*) FROM legacy_gloss").fetchone()[0]
    # ④ 🔴 生成侧的免费分支必须已经删掉，否则重跑会把同样的东西再贴一遍
    # ⚠️ **判据要去掉注释再查** —— 我第一版直接 `"free.append(" in 源码`，
    #    而废除那个分支时写的注释里**原样引用了这行代码**，判据被自己的注释骗过，
    #    分支删没删都报绿。同一个形状：判据比它要描述的东西宽
    #    （`[[criteria-narrower-than-you-think]]`）。
    code = "\n".join(l for l in DEFS.read_text(encoding="utf-8").splitlines()
                     if not l.lstrip().startswith("#"))
    free_alive = int("free.append(" in code)

    checks = [
        ("🔴 survey 数出来的 == 库里 src=ecdict-core 的", n, total),
        ("🔴 这批义项不许已经有第二条中文", multi, 0),
        ("要删的条数 > 0", int(n > 0), 1),
        ("🔴 生成侧免费分支已删（否则重跑等于没跑）", free_alive, 0),
    ]
    print("═══ 闸：删之前 ═══")
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-44s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    print("   ⭐ 不动的：别的来源中文 %s 条 ｜ legacy_gloss %s 行（重翻的锚）"
          % (format(others, ","), format(lg, ",")))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, stat = survey(con)

    print("═══ 阶段 1.5b「免费直接贴」的产物 ═══")
    print("   总行           %s" % format(len(rows), ","))
    print("   带词性前缀     %s  (%.1f%%)"
          % (format(stat["pos_pref"], ","), 100.0 * stat["pos_pref"] / max(len(rows), 1)))
    print("   含分号         %s  (%.1f%%)"
          % (format(stat["semi"], ","), 100.0 * stat["semi"] / max(len(rows), 1)))
    print("   🔴 词性与义项冲突 %s 条（ECDICT 的 n. 对我们的 name 不算冲突）"
          % format(len(stat["pos_conflict"]), ","))
    for w, ec, pos in stat["pos_conflict"][:6]:
        print("        %-16s ECDICT %-6s ←→ 义项 %s" % (w, ec, pos))
    print()

    bad = gates(con, rows, stat)
    con.close()
    if bad:
        print("\n🔴 闸红，不删。")
        return 1
    if not a.apply:
        print("\n(干跑。--apply 才真删)")
        return 0

    with dbtool.session("en-15b-undo", expect={"#sense_gloss": -len(rows)}) as s:
        s.execute("DELETE FROM sense_gloss WHERE lang='zh' AND src=?", (SRC,))
    print("\n✅ 已删 %s 条，交给 1.5c 重翻" % format(len(rows), ","))
    print("   下一步：python3 -m en.pipeline.translate_defs --plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
