#!/usr/bin/env python3
"""B1 中"kaikki 有自己真实英文释义"的 125,395 条:以英文释义为锚重写。见对话 2026-07-28。

B1 剩余 354,636 的成分(全部实测):
  ① kaikki 有**词条自己的**真实英文释义 125,395  ← 本脚本处理,锚最直接
  ② kaikki 是元描述但原形不可用          10,321   无锚
  ③ kaikki 完全没收录                 218,920   无锚(单词形 105,991 bad 50.0% / 短语形 112,929 bad 21.8%)
⚠️ ③ **不是垃圾堆**:`Photinia megaphylla→大叶石楠`、`moving-coil-type galvanometer→动圈式检流计`
   都是对的,只是 Wiktionary 不收专业术语/词组。别想当然判它死。

与 rewrite_b1_stuck.py 的差别:
  那批是**变形词**,锚是**原形**的英文释义 → 输出要保留"X的复数形式"首行;
  这批是**词条本身**有释义 → **直接给词义,不要形态说明**。任务更直接,lite 只会更稳。
  (上一批 lite 实测 pro 验收 ok 97.2%,起点 bad≈56%。)

⭐ 模型选型同上批:**这是翻译题不是知识题**(英文释义已在输入里),用最便宜的 lite。
   反例:需要模型自己"认得"生僻词的知识题(如判断罕用动词化是否存在),必须上 pro。

用法:
  python3 en/rewrite_b1_ownreal.py --limit 300   # 小跑
  python3 en/rewrite_b1_ownreal.py --run         # 备份后写库,留痕 b1_ownreal_fill.tsv
"""
import argparse, asyncio, json, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
POOL = paths.WORK / "runs/b1_ownreal_pool.json"
LOG = paths.WORK / "ledgers/b1_ownreal_fill.tsv"
CHUNK = 20   # 20 而非 10:system prompt 是每请求固定开销,摊到 20 条可省约 20% token

SYS = """你是英汉词典编纂专家。给你一批英语词条,每条含:
  word 英语词或词组
  zh   当前中文译文(来自网络众包,**过半是错的,不要信它**)
  en   该词在 Wiktionary 的**英文释义**(可信,以它为准)
请依据 en 给出该词条准确的中文译文:
- **直接给中文词义,不要加"XX的复数形式"这类形态说明**;
- 词义 1–3 个,简洁自然;动词用 v./vt./vi.,名词 n.,形容词 adj.,副词 adv.;
  可用 <罕><古><俚><非正式><方> 标记;有学科属性可带 [医][化][计][法][植][动] 等标签;
- **以 en 为准**:zh 与 en 冲突时以 en 为准;zh 恰好与 en 一致时可沿用;
- 专有名词(人名/地名/姓氏)给通行译名并注明,如"n. 史密斯(姓氏)"。
若 en 本身无实质信息(如仅是"See X."之类)、无法给出词义,返回 {"fix":"skip","why":"原因"}。
每条返回 {"fix":"rewrite","zh":"中文译文(可含换行\\n)"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    pool = json.load(open(POOL, encoding="utf-8"))
    if a.limit:
        pool = pool[:a.limit]
    print(f"[B1 自带英文释义批 · lite 重写] {len(pool)} 条", flush=True)

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        batches, metas = [], []
        for j in range(0, len(pool), CHUNK):
            sub = pool[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "zh": r[2].split("]")[-1].strip(), "en": r[3][:180]}
                            for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await S.run_batches(SYS, batches, env["DOUBAO_MODEL_BATCH_LITE"],
                                       cl.batch.chat.completions,
                                       (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 300))
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); rewrites = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, r in enumerate(meta, 1):
            v = res.get(str(k))
            act = v.get("fix") if isinstance(v, dict) else None
            if act == "rewrite" and isinstance(v.get("zh"), str) and v["zh"].strip():
                tally["rewrite"] += 1
                rewrites.append((r[0], r[1], r[2], v["zh"].strip()))
            else:
                tally["skip/novote(保持现状)"] += 1

    print(f"\n===== {sum(tally.values())} 条 token {tok} =====")
    for k, v in tally.most_common():
        print(f"  {k:24} {v:>7}")
    for rid, w, old, new in rewrites[:6]:
        print(f"\n  {w}\n    前: {old.split(']')[-1].strip()[:26]}\n    后: {new.replace(chr(10),' / ')[:66]}")

    if not a.run or not rewrites:
        print("\n(dry-run;加 --run 写库)")
        return

    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-b1own-{tag}.bak"))
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
        for rid, w, old, new in rewrites:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            f.write("\t".join([str(rid), w, old.replace("\n", "\\n"), new.replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已重写 {len(rewrites)} 条,留痕 → {LOG.name};备份 pre-b1own-{tag}.bak")


if __name__ == "__main__":
    main()
