#!/usr/bin/env python3
"""族 A — 例句译文取错义项的，**先判后修**。2026-08-27。

═══ 为什么不无差别重跑 ═══
`translate_examples.py` 的 payload 是 `fields=("id","fr")` —— 只喂句子、不喂它挂在
哪条义项下。风险面 119,164 条（多义词 **且** 挂在 rank>1）。
但**探针证明无差别重跑是错的做法**（`probes/` 三个脚本）：

    · 重跑会让 **85%** 的译文文本变化 —— 这个任务的抖动基线就这么高
    · 归因于义项上下文的只有 2.7 pp，**≤40 字符的短句上是 +0.0 pp**
    · 而且重跑**会把对的改错**（`squish` 一条，带上下文反而更差）

⇒ 无差别重跑 = 拿 106,000 条好译文去赌那批坏的。**只修被判坏的。**

═══ 判官是可信的（用前跑过正控负控）═══
`probes/judge_example_sense.py`：

    负控（外审挑出、我已回源确认的错案）  逮到 5/6
    正控（40 条**单义词**例句，无歧义）    40/40 ok，误判率 **0.0%**
    重复判同一批                        11.07% / 11.41% —— **判官稳定**
    旧译文 11.07% → 带上下文重翻 3.69%    ⇒ 重翻确实修得好

⚠️ 但判官**不是真值**：我逐条读了它圈中的 14 条，只有 2 条是真·译文错，
   7 条是「中文释义窄于它自己的法语定义」（族 E，译文和挂载都对），
   5 条是判官边界。⇒ **落库前必须我自己抽读**，`--read` 就是干这个的。

═══ 四段，每段都可续跑 ═══
    ① --judge        判 119,164 条现有译文        ≈ 16.0M token
    ② --retranslate  只重翻被判坏的（带义项上下文）  ≈ 1.5M
    ③ --verify       判新译文
    ④ --apply        **只在「旧的判坏、新的判好」时才替换**

④ 那条判据是整件事的安全性所在：判官过宽只会让某些条目白重翻一次，
  不会把好译文换掉；判官漏判只是维持现状。**两个方向都不伤已有数据。**

用法（在 fr/ 目录下，**排低谷跑**，价格减半）：
    python3 -u pipeline/fix_example_sense_mismatch.py --judge
    python3 -u pipeline/fix_example_sense_mismatch.py --retranslate
    python3 -u pipeline/fix_example_sense_mismatch.py --verify
    python3 -u pipeline/fix_example_sense_mismatch.py --read 30
    python3 -u pipeline/fix_example_sense_mismatch.py --apply
"""
import argparse
import importlib.util
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from pipeline import slot_translate              # noqa: E402

f = lambda n: format(n, ",")
DIR = paths.WORK / "examples"
J1 = DIR / "fixA_judge_old.jsonl"      # ① 判旧译文
RT = DIR / "fixA_retranslated.jsonl"   # ② 重翻
J2 = DIR / "fixA_judge_new.jsonl"      # ③ 判新译文
SRC = "model:example:sensefix"
slot_translate.CHUNK = 40
slot_translate.CONC = 100


def _probe(name):
    """判官与带上下文的 prompt 都住在 probes/ 里，**不重抄**（判据只许一份）。"""
    p = HERE.parent / "probes" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, str(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


JUD = _probe("judge_example_sense")
CTX = _probe("example_sense_context")

# 风险面：多义词 **且** 挂在 rank>1。挂在 rank=1 的，模型没上下文时默认就按
# 最常见义翻，方向本来就是对的（探针实测那一桶差异 +0.0 pp）。
RISK = """
  SELECT e.id, e.text, d.word, s.rank,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' ORDER BY seq LIMIT 1) zs,
    (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='fr' ORDER BY seq LIMIT 1) fs,
    (SELECT text FROM example_gloss WHERE example_id=e.id AND lang='zh') ze
  FROM example e JOIN sense s ON s.id=e.sense_id JOIN dict d ON d.id=s.word_id
  WHERE e.hidden=0 AND s.rank>1
    AND (SELECT COUNT(*) FROM sense x WHERE x.word_id=s.word_id AND x.hidden=0)>1
"""


def pool(con):
    out = []
    for eid, text, word, rank, zs, fs, ze in con.execute(RISK):
        if not zs or not ze:
            continue
        ctx = {"w": word, "zh": zs}
        if fs:
            ctx["d"] = fs
        out.append({"id": str(eid), "fr": text, "w": word, "sense": zs,
                    "zh": ze, "s": ctx, "_rank": rank})
    return out


def flagged(items):
    """→ 判官判 bad 的那些。"""
    got = slot_translate.done_keys(J1)
    return [i for i in items
            if str((got.get(i["fr"]) or {}).get("v", "")).strip().lower() == "bad"]


def main():
    ap = argparse.ArgumentParser()
    for x in ("judge", "retranslate", "verify", "apply"):
        ap.add_argument("--" + x, action="store_true")
    ap.add_argument("--read", type=int, default=0)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool(con)
    print("■ 风险面 %s 条（多义词且 rank>1，均有中文）" % f(len(items)))

    if a.judge:
        slot_translate.translate(items, JUD.SYS, J1,
                                 fields=("id", "fr", "w", "sense", "zh"),
                                 keep=("fr",), key_field="id", answer_field="v")
    got1 = slot_translate.done_keys(J1)
    c = Counter(str((got1.get(i["fr"]) or {}).get("v", "—")).strip().lower() for i in items)
    print("   ① 判旧译文：%s" % dict(c))
    bad = flagged(items)
    if got1:
        print("   ⇒ 判为错配 %s / %s = **%.2f%%**"
              % (f(len(bad)), f(c["ok"] + c["bad"]),
                 100.0 * len(bad) / max(c["ok"] + c["bad"], 1)))

    if a.retranslate:
        slot_translate.translate(bad, CTX.SYS_CTX, RT, fields=("id", "fr", "s"),
                                 keep=("fr",), key_field="id", answer_field="zh")
    new = slot_translate.done_keys(RT)
    if new:
        print("   ② 已重翻 %s" % f(len(new)))

    if a.verify:
        chk = [dict(i, zh=(new.get(i["fr"]) or {}).get("zh", ""), id="N" + i["id"])
               for i in bad if new.get(i["fr"])]
        chk = [i for i in chk if i["zh"].strip()]
        slot_translate.translate(chk, JUD.SYS, J2,
                                 fields=("id", "fr", "w", "sense", "zh"),
                                 keep=("fr",), key_field="id", answer_field="v")
    got2 = slot_translate.done_keys(J2)

    # ④ 只在「旧的判坏、新的判好」时替换
    repl = []
    for i in bad:
        n = (new.get(i["fr"]) or {}).get("zh", "").strip()
        if not n or n == i["zh"].strip():
            continue
        if str((got2.get(i["fr"]) or {}).get("v", "")).strip().lower() != "ok":
            continue
        repl.append((int(i["id"]), i["zh"], n, i["w"], i["sense"], i["fr"]))
    if got2:
        print("   ③④ 旧坏+新好 ⇒ **可替换 %s 条**（新译文判官仍判坏的 %s 条不动）"
              % (f(len(repl)), f(len(bad) - len(repl))))

    if a.read:
        print("\n══ 抽读（判官不是真值，落库前我要自己看）══")
        import random
        for eid, old, nw, w, sense, fr in random.Random(7).sample(
                repl, min(a.read, len(repl))):
            print("\n[%s] 义项：%s" % (w, sense))
            print("   FR %s" % fr[:130])
            print("   旧 %s" % old[:110])
            print("   新 %s" % nw[:110])

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not repl:
        print("🔴 没有可替换的")
        return 1
    with dbtool.session("keep-v3-example-sensefix", expect={}) as s:
        s.executemany(
            "UPDATE example_gloss SET text=?, src=? WHERE example_id=? AND lang='zh'",
            [(n, SRC, eid) for eid, _o, n, _w, _s, _f in repl])
    print("✓ 替换 %s 条（旧文本仍在 %s 里，可原样写回）" % (f(len(repl)), RT.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
