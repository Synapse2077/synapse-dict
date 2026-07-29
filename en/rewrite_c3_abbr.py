#!/usr/bin/env python3
"""C3 缩写/首字母词:以 kaikki 英文释义为锚重写。见对话 2026-07-29。

C3 = 词头全大写或译文以 abbr. 开头的缩写词,41,092 条,抽样实测 **bad 14.4%**(除 B1/B2 外最差)。
典型错法是**缩写展开错**:
    c-fo  → "首席财务官(Chief Finance Officer)"   实际标准缩写是 CFO,c-fo 不对应
    sab   → "abbr. Sabbath 安息日"                实为 science advisor(科学顾问)
    D-SLR → 英文全称拼错 "Digital Singular Lens Reflex"(应为 Single Lens Reflex)
    AAB   → "Aircraft Accident…"                 实为 army air base
    IXS   → 拿了 IX 的释义(Jesus Christ),张冠李戴

kaikki 覆盖 **12,015/41,092 = 29.2%**,这批有权威英文释义可锚(多为 "Initialism of X" / "Abbreviation of X")。
⭐ 模型选型:**英文释义已在输入里 = 翻译题,用 lite**;验收用 pro。
   (对照:需要模型自己认得生僻词的知识题必须上 pro,见 rewrite_b1_skips_pro.py。)
⚠️ 缩写特有要求:译文必须**同时给中文和英文全称**,只给中文对缩写没用。

用法:
  python3 en/rewrite_c3_abbr.py --limit 400   # pilot
  python3 en/rewrite_c3_abbr.py --run         # 备份后写库,留痕 c3_abbr_fix.tsv
"""
import argparse, asyncio, json, re, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S
import buckets as B

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
GLOSS = HERE / "c3_kaikki_gloss.json"
LOG = HERE / "c3_abbr_fix.tsv"
CHUNK = 20

SYS = """你是英汉词典编纂专家。给你一批英语**缩写/首字母词**,每条含:
  word 缩写本身
  zh   当前中文译文(**常把缩写展开错、或张冠李戴,不要信它**)
  en   该缩写在 Wiktionary 的英文释义(可信,以它为准;多为 "Initialism of X" / "Abbreviation of X")
请依据 en 给出准确的中文译文:
- 格式:`abbr. 中文含义(英文全称)`,例:`abbr. 科学顾问(science advisor)`;
- **必须同时给中文和英文全称** —— 只给中文对缩写没有用;
- 若该缩写有多个常见义,给最主要的 1–2 个,用分号隔开;
- 有学科属性可带 [医][化][计][法][军] 等标签;
- en 里的全称若明显拼错,按你的知识订正后再译。
**若 en 无实质信息、或你无法确定其含义,不要编造**,返回 {"fix":"skip","why":"原因"}。
每条返回 {"fix":"rewrite","zh":"译文"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""


def collect(conn):
    gl = json.load(open(GLOSS, encoding="utf-8"))
    rej = Counter(); out = []
    for rid, w, t, bk in B.load_tail(conn):
        if bk != "C3":
            continue
        k = w.strip().lower()
        g = gl.get(k)
        if not g:
            rej["kaikki 无释义"] += 1; continue
        en = g[0] if isinstance(g, list) else g
        if not en or len(en.strip()) < 4:
            rej["英文释义过短"] += 1; continue
        out.append((rid, w.strip(), (t or "").strip(), en.strip()))
    return out, rej


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    rows, rej = collect(conn)
    if a.limit:
        rows = rows[:a.limit]
    print(f"[C3 缩写 · lite 依英文释义重写] {len(rows)} 条")
    for k, v in rej.most_common():
        print(f"  剔除 {k:14} {v:>7}")

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "zh": r[2][:120], "en": r[3][:180]}
                            for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await S.run_batches(SYS, batches, env["DOUBAO_MODEL_BATCH_LITE"],
                                       cl.batch.chat.completions,
                                       (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 300))
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); fixes = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, r in enumerate(meta, 1):
            v = res.get(str(k))
            act = v.get("fix") if isinstance(v, dict) else None
            if act == "rewrite" and isinstance(v.get("zh"), str) and v["zh"].strip():
                tally["rewrite"] += 1
                fixes.append((r[0], r[1], r[2], v["zh"].strip()))
            else:
                tally["skip(保持现状)"] += 1

    print(f"\n===== {sum(tally.values())} 条 token {tok} =====")
    for k, v in tally.most_common():
        print(f"  {k:18} {v:>6}")
    for rid, w, old, new in fixes[:8]:
        print(f"\n  {w}\n    前: {old.replace(chr(10),' / ')[:44]}\n    后: {new.replace(chr(10),' / ')[:66]}")

    if not a.run or not fixes:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-c3-{tag}.bak"))
    conn = sqlite3.connect(DB)
    if LOG.exists():   # 重跑保护
        for i, ln in enumerate(open(LOG, encoding="utf-8")):
            if i:
                c = ln.rstrip("\n").split("\t")
                conn.execute("UPDATE stardict SET translation=? WHERE id=?",
                             (c[2].replace("\\n", "\n"), int(c[0])))
        conn.commit()
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tbefore\tafter\n")
        for rid, w, old, new in fixes:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            conn.execute("UPDATE stardict SET qual='fixed' WHERE id=? AND qual NOT IN ('core','judged')", (rid,))
            f.write("\t".join([str(rid), w,
                               old.replace("\t", " ").replace("\n", "\\n"),
                               new.replace("\t", " ").replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已重写 {len(fixes)} 条(qual 已同步),留痕 → {LOG.name};备份 pre-c3-{tag}.bak")


if __name__ == "__main__":
    main()
