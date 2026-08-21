#!/usr/bin/env python3
"""实验：改 prompt 能不能修好那 6 条已知真错？**带正控**。2026-08-19。

═══ 为什么做这个实验 ═══
分层质量普查（`quality_ruler`）给出：E 层 8.6% / F 层 5.0% / I 层 2.5%，
折算约 **3,200 条**真错。要不要重跑这两层，取决于一件事：
**改 prompt 到底能不能修好这类错？**

我手里正好有真值 —— 2026-08-16 逐条读时标成 2a 的 6 条，每条都写了理由。
逐条看，至少 3 条的共同形状是：**判断所需的信息本来就在手边，模型没用**

    zoratteri   意语源明写「属于有翅亚纲(Pterigoti)」⇒ 缺翅目（昆虫）
                中文却写成「土豚目」（哺乳动物）
    porta ad ala di gabbiano   词头自己写着 ala di gabbiano（鸥翼）
                中文却按法语 papillon 写成「蝴蝶门」
    master      源文本写明「本科后的专业文凭」，中文仍写「硕士」

⇒ 假设：**把「词头字面 + 完整源文本」摆到判据位置**能修好一部分。

═══ 🔴 必须带正控 ═══
只测 6 条已知错 = 只跑负控，会把「全部改写」当成满分
（`prompt-self-harm-two-patterns` 的教训：只跑负控会让"全弃权"拿满分）。
⇒ 同时喂 20 条我标成 0（正确）的，看新 prompt 会不会把它们改坏。

用法（在 it/ 目录下）：
    python3 probes/retranslate_pilot.py            # 出题目，不调模型
    python3 probes/retranslate_pilot.py --run
"""
import argparse
import asyncio
import glob
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import ds_batch   # noqa: E402
import paths      # noqa: E402

f = lambda n: format(n, ",")
OUT = paths.WORK / "retranslate_pilot.jsonl"

# 🔴 与现行 prompt 的差别只有「判据段」那三条 —— 其余照抄，
#    否则量出来的是我两版提示的差别，不是这三条的效果（`prompt-beats-model-choice`）。
SYS = """你在给一部意大利语→中文词典写释义。用户是中文母语者。

对每一条，给出**中文对应词**（不是长句翻译）。

🔴 判据（按优先级）：
1. **词头本身的字面含义是第一线索**。`porta ad ala di gabbiano` 里写着
   `ala di gabbiano`（鸥翼），中文就该是「鸥翼门」—— 哪怕别的语言的对应词长得像别的东西。
2. **源文本里点明的上位/类别必须与中文一致**。源里说「属于有翅亚纲(Pterigoti)」，
   那它就是昆虫，中文不能给一个哺乳动物的目名。
3. **源词有多个义支时，选与词头、与源文本其余部分一致的那支**。
   判不出来就直译源文本说的那件事，**不要挑一个看着顺的义支**。
4. 不编造源头没有的信息；不加「（形容词）」这类词性标注。

输出 JSON 对象，键是标识号（原样回传），值是 {"zh": "中文对应词"}。
只输出 JSON，不要解释。"""


def load():
    """→ ([负控 6 条], [正控 20 条])，都带我当初的评级理由。"""
    bad, good = [], []
    for p in glob.glob(str(Path(__file__).resolve().parent / "grades" / "grade_*.json")):
        d = json.load(open(p, encoding="utf-8"))
        for sid, v in d["grades"].items():
            (bad if v["g"] in ("2a", "2b") else (good if v["g"] == "0" else [])).append(
                (int(sid), v.get("w"), v.get("r", "")))
    return bad, good[:20]


def payload(con, rows):
    out = []
    for sid, w, _r in rows:
        zh, en = con.execute(
            "SELECT (SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' AND seq=0),"
            "       (SELECT text FROM sense_gloss WHERE sense_id=? AND lang='en' AND seq=0)",
            (sid, sid)).fetchone()
        it = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='it' "
                         "AND kind='definition' AND seq=0", (sid,)).fetchone()
        sx = con.execute("SELECT text FROM sense_src WHERE sense_id=? LIMIT 1", (sid,)).fetchone()
        out.append({"n": sid, "w": w,
                    "src": (en or [None])[0] or (it or [None])[0] or (sx or [None])[0] or "",
                    "_now": zh})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad, good = load()
    pb, pg = payload(con, bad), payload(con, good)
    print("■ 负控（我标成真错）%s 条 / 正控（我标成正确）%s 条" % (f(len(pb)), f(len(pg))))
    if a.run:
        items = pb + pg
        # 🔴 送进去的不带 `_now`（当前中文）—— 带上就是把答案递给它，量不出真本事
        send = [{k: v for k, v in x.items() if not k.startswith("_")} for x in items]
        B = 6
        batches, meta = [], []
        for i in range(0, len(send), B):
            batches.append(send[i:i + B])
            meta.append([(str(x["n"]), x["n"]) for x in send[i:i + B]])
        tok = asyncio.run(ds_batch.run(SYS, batches, meta, OUT, mode="flash", conc=3,
                                       every=1, thinking="disabled"))
        print("■ token %s" % f(tok))
    got = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                r = json.loads(line)
                got[int(r["id"])] = (r.get("zh") or "").strip()
            except Exception:
                pass
    print("\n═══ 负控：这 6 条以前是错的，新 prompt 改对了吗 ═══")
    for (sid, w, why), it in zip(bad, pb):
        print("   %-22s 旧「%s」 → 新「%s」" % ((w or "")[:22], (it["_now"] or "")[:14],
                                            got.get(sid, "(没答)")[:20]))
        print("        源 %s" % (it["src"] or "")[:76])
        print("        我当初的理由 %s" % why[:74])
    print("\n═══ 正控：这 20 条以前是对的，新 prompt 改坏了吗 ═══")
    same = diff = 0
    for (sid, w, _why), it in zip(good, pg):
        new = got.get(sid, "")
        if not new:
            continue
        if new == (it["_now"] or ""):
            same += 1
        else:
            diff += 1
            print("   ⚠️ %-20s 旧「%s」 → 新「%s」" % ((w or "")[:20], (it["_now"] or "")[:18], new[:18]))
    print("   逐字未变 %s / 改写了 %s" % (f(same), f(diff)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
