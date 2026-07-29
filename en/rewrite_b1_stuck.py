#!/usr/bin/env python3
"""B1 卡住批(原形也是 [网络]):以 kaikki 英文释义为锚重写。见对话 2026-07-28。

处理对象:B1 里 kaikki 判定为变形/异体、但**原形在库中也是 [网络] 众包**的 45,881 条。
词条自己的中文不可信、原形的中文也不可信 —— 但 **kaikki 里原形有真实英文释义(覆盖 92.7%)**,
这是唯一可信的锚。

⚠️ **处置不是"抄原形",而是"拿英文释义重写"**。三种情况都真实存在:
    absenters   词条对(缺席者) / 原形错(absenter→痢疾)      ← 只信原形会把对的改坏
    lugmarks    词条错(宝石)   / 原形对(耳标)
    somnolites  两个都错(睡莲,实际是"处于催眠状态者")
  只有英文释义能同时管住这三种。

现状与效果(均 pro 判,同一批 300 条):
    现状 ok 46.0%(独立复测 100 条 ok 41.0%,两次取中 bad≈56%)
    turbo 重写后 ok 95.9% / bad 4.1%
    lite  重写后 ok 95.0% / bad 5.0%   ← **用 lite**
⭐ **这是翻译题不是知识题**:英文释义已在输入里,模型不需要自己"认识"这个生僻词,
   所以便宜模型够用(turbo 与 lite 只差 0.9pt,且两者 bad **高度重合**
   —— gloars/mispersoned/gazzette/gutsful 两轮都错 —— 说明残留是**数据问题**
   (词本身不存在/kaikki 原形指错),换更强的模型也修不掉,只会多花钱)。
⭐ 原译文的错法全是**看词形猜**(buggalow 见 bug→"臭虫"、ficlets 见 fic→"烟丝"、
   antimatroids 见 anti+matr→"抗菌素"),那是**无锚**时的必然结果;给了锚这条路径就不存在了。
   (已核实:这批译文在原始 ecdict.sqlite 中逐字节相同 = ECDICT 自带众包数据,非本项目 LLM 产出。)

用法:
  python3 en/rewrite_b1_stuck.py --limit 500   # 小跑
  python3 en/rewrite_b1_stuck.py --run         # 备份后写库,留痕 b1_stuck_fill.tsv
"""
import argparse, asyncio, json, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
POOL = HERE / "b1_stuck_pool.json"
LOG = HERE / "b1_stuck_fill.tsv"
CHUNK = 10

SYS = """你是英汉词典编纂专家。给你一批英语词条,每条含:
  word 英语词    rel 形态关系(如"X的复数形式")
  zh   当前中文译文(来自网络众包,**过半是错的,不要信它**)
  en   该词原形在 Wiktionary 的**英文释义**(可信,以它为准)
请依据 en 给出该词条准确的中文译文:
- 首行保留 rel 这句形态说明,换行后给中文词义;
- 词义 1–3 个,简洁自然;动词 v./vt./vi.,名词 n.,形容词 adj.;
  可用 <罕><古><俚><非正式> 标记;有学科属性可带 [医][化][计] 标签;
- **以 en 为准**:zh 与 en 冲突时以 en 为准;zh 恰好与 en 一致时可沿用。
若 en 本身无实质信息、无法给出词义,返回 {"fix":"skip","why":"原因"}。
每条返回 {"fix":"rewrite","zh":"完整译文(可含换行\\n)"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    pool = json.load(open(POOL, encoding="utf-8"))
    if a.limit:
        pool = pool[:a.limit]
    print(f"[B1 卡住批 · 英文释义锚重写] {len(pool)} 条", flush=True)

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        batches, metas = [], []
        for j in range(0, len(pool), CHUNK):
            sub = pool[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "rel": r[3] + r[4],
                                     "zh": r[2].split("]")[-1].strip(), "en": r[5][:180]}
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
        print(f"  {k:24} {v:>6}")
    for rid, w, old, new in rewrites[:6]:
        print(f"\n  {w}\n    前: {old.split(']')[-1].strip()[:26]}\n    后: {new.replace(chr(10),' / ')[:66]}")

    if not a.run or not rewrites:
        print("\n(dry-run;加 --run 写库)")
        return

    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-b1stuck-{tag}.bak"))
    conn = sqlite3.connect(DB)
    if LOG.exists():   # 重跑保护:先退回上一轮
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
    print(f"\n已重写 {len(rewrites)} 条,留痕 → {LOG.name};备份 pre-b1stuck-{tag}.bak")


if __name__ == "__main__":
    main()
