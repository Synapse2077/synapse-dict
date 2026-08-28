#!/usr/bin/env python3
"""探针（族 E）— **中文释义是不是比它自己的法语定义窄？** 2026-08-27。

═══ 起因 ═══
族 A 收尾时逐条读判官圈中的 14 条，发现 7 条**译文和挂载都是对的**，
错的是义项自己的中文释义 —— 它是照**英文对应词**翻的，而英文对应词只覆盖
法语定义的一支：

    aller #9959
      FR  Fonctionner, en parlant d'un mécanisme, d'un projet **ou de la santé**.
      EN  to be (feeling)                     ← 英文版只给了"健康"这一支
      ZH  （健康）处于，感觉                    ← 中文照英文翻，另外两支没了
    ⇒ `Ça va ?` 是对的，`La voiture va bien` 在我们词典里查不到

🔴 **不要拿长度当判据。** 我第一版算过一个"上界 44,243"（法语定义 >60 字符
   且中文 <14 字符），那是 `[[criteria-from-meaning-not-form]]` 点名的形式代理：
   `homotopique` 的 FR 一句话、ZH「同伦的」三个字，**完全正确**。
   「窄不窄」只能语义比对 ⇒ 这件事**判官就是判据本身**，不该先用尺子筛一遍。

═══ 本脚本只出判断，一个字不写库 ═══
产物是「有多少条、长什么样」，不是改写。改不改、怎么改，看到数再定。

═══ 两个控制组（`[[llm-as-evaluator-discipline]]`：判官不是真值）═══
    负控（必须判 narrow）  上面四条我已逐条回源确认的
    正控（必须判 ok）      单支概念的术语词条 —— 中文本来就该只有几个字，
                          判官若把这些也判 narrow，说明它把"简练"当成了"窄"

═══ 两个抽样臂 ═══
    ① base  在三语齐全的 98,305 条里**平均抽** ⇒ 诚实的基础率
    ② freq  按 `freq_zipf` 取高频词的义项      ⇒ 读者真正会查到的那一批
    ⚠️ ② **不是**缺陷的形式代理，是**价值加权** —— 同样一条缺陷，
       长在 `aller` 上和长在 `algoïde` 上，对词典的伤害不是一个量级。

═══ 实测结果（2026-08-27，n=400 × 2 臂）═══
    ① 平均臂  narrow 34 / 400 = **8.5%**   母体 98,305 ⇒ 外推 ≈ 8,355
    ② 高频臂  narrow 29 / 400 = **7.2%**   母体 25,703 ⇒ 外推 ≈ 1,863
    控制组：负控召回 2/4（判官偏保守，如 prompt 第 5 条要求的）、正控误判 0/7
    ⇒ 判官报的是**下界**。

🔴🔴 **抽读 23 条推翻了我给这一族起的名字。** 真实形状不是「窄」，是
    **中文是照英文对应词翻的，法语定义根本没参与** —— 英文对应词一旦错或偏，
    中文就跟着错，而这已经不是"少一支"，是**整条错**：

      passif    FR 性交中的接受方              EN bottom       ZH 底部
      vedette   FR 提供勤务的**小艇**          EN flagship     ZH 旗舰（英文源头就错）
      presser   FR 互相挤在一起                EN to hurry up  ZH 赶快（英文取了另一义项）
      pédestre  FR 表现人物**站立全身**的雕像   EN representing someone walking
                                                             ZH 表现行走姿态的
      trapézoïde FR 腕骨远排的一块小骨          EN trapezoid bone  ZH **跗**三角骨（腕→跗）

    23 条里：真窄 14 / 判官过宽 4 / **中文直接错 5**，且 5 条全在高频段。
    ⇒ 这一族的价值不在"补全"，在**改错**。

用法（在 fr/ 目录下）：
    python3 -u probes/judge_gloss_coverage.py --control
    python3 -u probes/judge_gloss_coverage.py --n 400
"""
import argparse
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                  # noqa: E402
from pipeline import slot_translate           # noqa: E402
from wordfreq import tokenize as _tok         # noqa: E402
from wordfreq import zipf_frequency as _zipf  # noqa: E402

f = lambda n: format(n, ",")
DIR = paths.WORK / "senses"
slot_translate.CHUNK = 30
slot_translate.CONC = 32

SYS = """你在检查一部法汉词典里，**中文释义有没有漏掉法语定义里的某一支意思**。

输入是 JSON 数组，每项：
- `id`：标识号，**不是序号**，原样回传。
- `w`：词条。
- `fr`：这条义项的**法语定义**（权威源，以它为准）。
- `zh`：这条义项现有的**中文释义**。

只判断一件事：**法语定义说的意思，中文释义有没有整支整支地漏掉？**

- `ok`：中文覆盖了法语定义说的意思。
- `narrow`：法语定义说的是 A、B、C 几支（或一个更宽的概念），
  而中文只说了其中一支，读者按中文理解会**用不到**另外几支。

判断纪律 —— 下面几条都判 `ok`，不许判 narrow：
1. **中文简练不等于窄。** 法语定义写一整句、中文只有两三个字，只要那两三个字
   就是这个概念本身，就是 `ok`（`Qui ressemble à une algue.` / 「藻状的」= ok）。
2. **不要求逐支列举同义词。** 法语用三个近义动词描述同一个动作、中文给一个词，
   是 `ok`。只有**不同的**意思被漏掉才算 narrow。
3. **括号里的领域限定不算窄。** 中文写「（数学）…」而法语没写领域，是 `ok`。
4. 法语定义本身是「X 的变体 / 复数 / 缩写」这类**指针**时，一律 `ok`。
5. **拿不准就给 `ok`。** 这一步的代价不对称：判成 narrow 会让一条本来够用的
   释义被重写，而重写有风险；漏一条只是维持现状。

输出 JSON 数组：
  [{"id": <标识号>, "v": "ok"}] 或 [{"id": <标识号>, "v": "narrow"}]
只输出 JSON，不要解释。"""
# 🔴 第一版还要模型在 `miss` 里写清漏了哪一支 —— **那个字段永远落不了盘**：
#    `slot_translate._ask` 只把 `answer_field` 那一个值存下来（`out[key] = v`），
#    应答对象的其余键当场丢掉。跑完看到 34 条 `漏` 全是空的才发现。
#    ⇒ 要么改共享代码存整个对象，要么别问。我选别问：抽读时 FR/EN/ZH 三行并排
#      已经够我判，多问一个字段是白烧输出 token。

# 负控：我已逐条回源确认「中文窄于法语定义」的
#   9959  aller   机器/项目/健康 三支，中文只剩「（健康）」
#   14180 tirer   「把人弄出某地」是及物，中文「离开」成了不及物
#   5594  porter  「随身带着 或 手里拿着」，中文只剩「搬运，扛」（戴手表不叫扛）
#   10795 tenir   「抵住、在时空中持续、经得起批评、合适」，中文只剩「停留，维持」
# 🔴 第一版我还列了 `10793 tenir`（FR 用手牢牢拿住 / ZH 拿着，握住，拥有）——
#    判官判 ok，我回去逐条读**判官是对的，中文完全够用**。
#    `[[llm-as-evaluator-discipline]]` 那条「判官不是真值」的反面：**我的真值也不是真值**。
#    控制组错一条，量出来的召回率就错 20 个百分点，所以这里写清每一条凭什么。
NEG = [9959, 14180, 5594, 10795]
# 正控：单支概念的术语词条，中文本来就该只有几个字
# 🔴 第一版把 `72045 clayette` 列在这里，判官判 narrow 被我记成"误判"。
#    回去读：FR `Étagère d'un cellier, d'un réfrigérateur.` = **地窖或冰箱**的搁架，
#    中文「（冰箱）搁架」确实把地窖那支丢了 —— **判官对，我的正控错**。已移出。
POS = [69594, 87111, 91287, 28582, 78746, 73607, 79395]

ROW = """SELECT s.id, d.word,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='fr' ORDER BY seq LIMIT 1) fr,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' ORDER BY seq LIMIT 1) zh,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='en' ORDER BY seq LIMIT 1) en
  FROM sense s JOIN dict d ON d.id=s.word_id
  WHERE s.hidden=0 AND %s"""

TRI = ("EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='fr') "
       "AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh') "
       "AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='en')")


def zipf(w):
    """🔴 `[[wordfreq-ruler-traps]]`：多词条目 wordfreq 是**把各词的频次拼**出来的，
    词缀会被静默剥掉再查。判据只能是 `tokenize(w)==[w.lower()]`，
    对不上就返回 None（= 这把尺子量不了它），**不是返回 0**。"""
    try:
        if _tok(w, "fr") != [w.lower()]:
            return None
        return _zipf(w, "fr")
    except Exception:
        return None


def pack(rows):
    out = []
    for sid, w, fr, zh, en in rows:
        if not fr or not zh:
            continue
        out.append({"id": str(sid), "w": w, "fr": fr, "zh": zh, "_en": en or "",
                    "_z": zipf(w)})
    return out


def ask(items, tag):
    out = DIR / ("cover_%s.jsonl" % tag)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 🔴 `land="id"` 不是随手写的：同一句法语定义配不同中文的义项有 6,352 条，
    #    按默认的 `fr` 落盘会让其中一条领走另一条的判断（见 slot_translate 那段注释）。
    slot_translate.translate(items, SYS, out, fields=("id", "w", "fr", "zh"),
                             keep=("id", "w"), key_field="id", answer_field="v",
                             land="id")
    got = slot_translate.done_keys(out, "id")
    c, bad = Counter(), []
    for it in items:
        r = got.get(it["id"])
        if not r:
            c["未答"] += 1
            continue
        v = str(r.get("v", "")).strip().lower()
        c[v if v in ("ok", "narrow") else "越权值:%r" % v] += 1
        if v == "narrow":
            bad.append(it)
    return c, bad


def show(bad, n):
    for it in bad[:n]:
        print("\n[%s] #%s  zipf %s"
              % (it["w"], it["id"], "—" if it["_z"] is None else "%.2f" % it["_z"]))
        print("   FR   %s" % it["fr"][:150])
        print("   EN   %s" % it["_en"][:100])
        print("   ZH   %s" % it["zh"][:90])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--read", type=int, default=14)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    R = random.Random(20260827)

    if a.control or not a.n:
        ids = lambda xs: "s.id IN (%s)" % ",".join(str(i) for i in xs)
        neg = pack(con.execute(ROW % ids(NEG)).fetchall())
        pos = pack(con.execute(ROW % ids(POS)).fetchall())
        cn, bn = ask(neg, "neg")
        cp, bp = ask(pos, "pos")
        print("\n══ 负控（%d 条已回源确认中文窄于法语定义，判官应全判 narrow）══" % len(neg))
        print("   ", dict(cn), " ⇒ 逮到 %d/%d" % (len(bn), len(neg)))
        got = {i["id"] for i in bn}
        for it in neg:
            print("      %-8s #%-6s %s  %s"
                  % (it["w"], it["id"], "✅" if it["id"] in got else "🔴 漏",
                     it["zh"][:40]))
        print("\n══ 正控（%d 条单支概念术语，中文本就该简练，判官应全判 ok）══" % len(pos))
        print("   ", dict(cp), " ⇒ 误判率 %.1f%%" % (100.0 * len(bp) / max(len(pos), 1)))
        for it in bp:
            print("      🔴 误判 %-14s FR %s\n              ZH %s"
                  % (it["w"], it["fr"][:80], it["zh"][:50]))
        if not a.n:
            return 0

    all_rows = pack(con.execute(ROW % TRI).fetchall())
    # 🔴 fr 库还没有 `freq_zipf` 列（那是后面的阶段），高频臂现算。
    #    量不了的（多词条目）**排除出高频臂**，不是当成 0 —— 当 0 会把它们
    #    全塞进"低频"，而 `pièce jointe` 这种恰恰是常用词。
    hi = [r for r in all_rows if r["_z"] is not None and r["_z"] >= 3.0]
    for tag, rows, label in (
            ("base", all_rows, "① 平均抽（三语齐全的全部义项）"),
            ("freq", hi, "② 高频臂（wordfreq zipf ≥ 3.0，读者真会查到的）")):
        items = R.sample(rows, min(a.n, len(rows)))
        c, bad = ask(items, tag)
        n = sum(v for k, v in c.items() if k in ("ok", "narrow"))
        print("\n══ %s ══  母体 %s 条" % (label, f(len(rows))))
        print("   ", dict(c))
        print("   ⇒ 判为「中文窄于法语定义」 %s / %s = **%.1f%%**  外推 ≈ %s 条"
              % (f(len(bad)), f(n), 100.0 * len(bad) / max(n, 1),
                 f(int(len(rows) * len(bad) / max(n, 1)))))
        print("\n── 抽读（判官不是真值，我要自己逐条看）──")
        show(bad, a.read)
    return 0


if __name__ == "__main__":
    sys.exit(main())
