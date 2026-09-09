#!/usr/bin/env python3
"""1.5c 换模型打样：**豆包 mini vs DeepSeek flash**。2026-09-07。

用户 2026-09-07：「你试一下 mini，看看它的质量如何」。

═══ 🔴 先说边界 ═══
`it/pipeline/ark_batch.py:37` 有 `DOUBAO_DISABLED = True` —— 用户 2026-08-15 下的硬禁令
（我在 it 上烧掉 509 万 token、其中 418 万因我 prompt 的缺陷作废，导致账户欠费）。
那条禁令禁的是**跑批**；`[[consult-two-models-on-rules]]` 划的口子是**打样与咨询可以**。
本脚本是打样：**条数写死在切片集内，拿不到全量池子**，跑不成批。

═══ 判据（不是"读几条觉得还行"）═══
四条，每条都能出数：
  ① **同题同 prompt** —— 复用 `translate_slice.RULES` + `ANCHOR_RULE`，不另写一份
     （`[[refactor-mindset-code-quality]]`：判据重复两份就会各自漂移）
  ② **外锚负控** —— 只取核心层里有 ECDICT 人工中文的那批（bad≈0.02%）。
     这是 en 独有的资产，五门都没有。⚠️ 判据不是"字面一样"（同义表述本来就该不同），
     是**有没有共同词条**，两个模型用同一把尺子量，比的是相对值。
  ③ **丢条率** —— it 实测 flash 会静默丢批里一部分（2,069 条）。换模型必须重新量。
  ④ **入/出 token 分开记** —— 出方向通常贵 3 倍，只记 total 报不出价。

🔴 **不用模型判模型**（`[[llm-as-evaluator-discipline]]` ⑩）：分歧逐条并排打出来给人看。
⚠️ 豆包单价**本项目从没记过**，所以只报 token 不折算成钱（`[[prove-free-path-before-quoting]]`）。

    cd en && python3 -u probes/model_bakeoff.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import asyncio
import json
import re
import sqlite3

import httpx

import paths
import slot_translate as ST
from translate_slice import ANCHOR_RULE, RULES

ARK = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
OUT = paths.WORK / "slice"
HAN = re.compile(r"[㐀-䶿一-鿿]")
CHUNK, CONC = 80, 4          # 打样，不求快


def frags(ref):
    if not ref:
        return set()
    s = re.sub(r"^[a-z]{1,5}\.\s*|\s*/\s*[a-z]{1,5}\.\s*", " ", ref)
    s = re.sub(r"\[[^\]]{1,6}\]", " ", s)
    return {x.strip() for x in re.split(r"[；;，,、/\s]+", s)
            if len(x.strip()) >= 2 and HAN.search(x)}


def pool():
    """题目 = 切片里**两轮都做过、且有 ECDICT 人工中文、且属核心层**的那批。"""
    A = {json.loads(l)["id"]: json.loads(l) for l in (OUT / "slice_noanchor.jsonl").open(encoding="utf-8")}
    B = {json.loads(l)["id"]: json.loads(l) for l in (OUT / "slice_anchor.jsonl").open(encoding="utf-8")}
    ids = [i for i in B if i in A]
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = []
    for k in range(0, len(ids), 900):
        ck = ids[k:k + 900]
        qs = ",".join("?" * len(ck))
        for sid, w, pos, en, frq, tag, ref in con.execute(
                "SELECT s.id, d.word, s.pos, g.text, d.freq_rank, d.exam_tag, lg.text "
                "FROM sense s JOIN dict d ON d.id=s.word_id "
                "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' "
                "LEFT JOIN legacy_gloss lg ON lg.word_id=s.word_id "
                "WHERE s.id IN (%s)" % qs, ck):
            if not (frq or tag) or not ref:
                continue
            rows.append({"id": sid, "word": w, "pos": pos or "", "en": en,
                         "ref": " / ".join(x.strip() for x in ref.split("\n") if x.strip())[:180]})
    con.close()
    rows.sort(key=lambda r: r["id"])
    return rows, A, B


async def ask(cl, key, model, items):
    body = {"model": model, "temperature": 0, "stream": False,
            "thinking": {"type": "disabled"},
            "messages": [{"role": "system", "content": RULES + ANCHOR_RULE},
                         {"role": "user", "content": json.dumps(
                             [{k: it[k] for k in ("id", "word", "pos", "en", "ref")} for it in items],
                             ensure_ascii=False)}]}
    r = await cl.post(ARK, headers={"Authorization": "Bearer " + key}, json=body, timeout=300)
    if r.status_code != 200:
        raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:300]))
    d = r.json()
    txt = re.sub(r"^```(?:json)?|```$", "", d["choices"][0]["message"]["content"].strip(), flags=re.M)
    got = {}
    for o in ST._loads(txt.strip()):
        if isinstance(o, dict) and "id" in o:
            got[str(o["id"])] = str(o.get("zh") or "")
    u = d.get("usage") or {}
    return got, (u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


async def run(rows, key, model):
    chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]
    sem = asyncio.Semaphore(CONC)
    res, tin, tout = {}, 0, 0

    async with httpx.AsyncClient() as cl:
        async def one(ch):
            nonlocal tin, tout
            async with sem:
                for att in range(3):
                    try:
                        got, (i, o) = await ask(cl, key, model, ch)
                        tin += i
                        tout += o
                        res.update(got)
                        return
                    except Exception as e:
                        if att == 2:
                            print("   🔴 放弃一批 %s 条：%s" % (len(ch), str(e)[:120]), flush=True)
                        await asyncio.sleep(2 * (att + 1))
        await asyncio.gather(*(one(c) for c in chunks))
    return res, tin, tout


def report(rows, A, B, M, tin, tout):
    by = {r["id"]: r for r in rows}
    n = len(rows)
    print("\n═══ ① 交付完整性 ═══")
    miss = [r["id"] for r in rows if str(r["id"]) not in M]
    empty = [r["id"] for r in rows if not (M.get(str(r["id"])) or "").strip()]
    print("   题目 %s ｜ mini 未回 %s (%.1f%%) ｜ 回了但为空 %s"
          % (format(n, ","), format(len(miss), ","), 100 * len(miss) / n, format(len(empty), ",")))
    print("\n═══ ② 单价（入/出分开）═══")
    print("   mini  入 %.1f ／ 出 %.1f token/条   （flash 带锚实测 入 71.0 ／ 出 22.5）"
          % (tin / n, tout / n))
    print("   ⚠️ 豆包单价本项目从没记过 ⇒ 只报 token，不折算成钱。")

    print("\n═══ ③ 外锚负控：与 ECDICT 人工中文有共同词条 ═══")
    print("   （同一把尺子量两个模型；⚠️ 无重合不等于错，看的是**相对值**）")
    def ov(get):
        hit = 0
        for r in rows:
            f = frags(r["ref"])
            z = get(r["id"]) or ""
            if f and any(x in z for x in f):
                hit += 1
        return hit
    hf = ov(lambda i: (B.get(i) or {}).get("zh"))
    hm = ov(lambda i: M.get(str(i)))
    print("   flash %s / %s = %.1f%%" % (format(hf, ","), format(n, ","), 100 * hf / n))
    print("   mini  %s / %s = %.1f%%" % (format(hm, ","), format(n, ","), 100 * hm / n))

    print("\n═══ ④ 分歧逐条（人眼裁决，不用模型判模型）═══")
    diff = [r for r in rows
            if (M.get(str(r["id"])) or "").strip() != ((B.get(r["id"]) or {}).get("zh") or "").strip()]
    print("   两个模型输出不同 %s 条 %.1f%%\n" % (format(len(diff), ","), 100 * len(diff) / n))
    import random
    random.seed(7)
    for r in random.sample(diff, min(25, len(diff))):
        print("   ── %s (%s)  %s" % (r["word"], r["pos"], r["en"][:70]))
        print("      flash: %s" % ((B.get(r["id"]) or {}).get("zh") or "")[:60])
        print("      mini : %s" % (M.get(str(r["id"])) or "")[:60])
        print("      人工 : %s" % r["ref"][:60])
    (OUT / "slice_mini.jsonl").write_text(
        "\n".join(json.dumps({"id": r["id"], "word": r["word"], "zh": M.get(str(r["id"]), "")},
                             ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print("\n   → 逐条存档 %s" % (OUT / "slice_mini.jsonl"))


def main(run_it=False):
    rows, A, B = pool()
    print("═══ 题目：切片内 核心层 ∩ 有人工中文 ∩ 两轮都做过 = %s 条 ═══" % format(len(rows), ","))
    if not run_it:
        print("(干跑。加 --run 才发请求)")
        return 0
    e = ST.env()
    key, model = e["ARK_API_KEY"], e["DOUBAO_MODEL_ONLINE_MINI"]
    print("   模型：豆包 mini（在线）｜ 关思考 ｜ 批 %d ／ 并发 %d\n" % (CHUNK, CONC))
    M, tin, tout = asyncio.run(run(rows, key, model))
    report(rows, A, B, M, tin, tout)
    return 0


if __name__ == "__main__":
    _sys.exit(main(run_it="--run" in _sys.argv))
