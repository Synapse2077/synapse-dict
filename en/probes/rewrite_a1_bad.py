#!/usr/bin/env python3
"""对 A1 回填中被 judge 判 bad 的条目做**重写**(而不是退回空壳)。见对话 2026-07-28。

sweep_a1.py 的默认处置是把 bad 撤回成回填前原文(那句"X的复数",没用但不骗人)。
但判官其实已经知道错在哪(note:"basker 实为晒太阳的人"),让它直接给正确译文,
就能把这批**救回来**而不是丢掉;而且 bad 只占几个百分点,成本约是全量判的 6%。

两类 bad 的救法不同:
  ① base 词条译文本身就错(baskers←basker「n. 巴斯克」实为晒太阳的人)→ 重写该变形词的译文;
  ② 变形关系本身不成立(pakistans/GoYas,国名人名无复数;waterskied 真词元是 waterski)
     → **不该重写,该退回空壳**(硬编一个译文等于承认这个伪词条合法)。
故 prompt 要求判官先判 fixable,不可救的显式返回 skip。

输入:sweep_a1.jsonl(需含 v=bad 的条目) + a1a_fill.tsv(取回填前原文)
用法:
  python3 en/rewrite_a1_bad.py            # dry-run,只看重写结果
  python3 en/rewrite_a1_bad.py --run      # 备份后写库,留痕 a1_rewrite.tsv
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, asyncio, json, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
SWEEP = paths.WORK / "runs/sweep_a1.jsonl"
FILL = paths.WORK / "ledgers/a1a_fill.tsv"
LOG = paths.WORK / "ledgers/a1_rewrite.tsv"
CHUNK = 10

SYS = """你是英汉词典编纂专家。给你一批**有问题**的英语词条,每条含:
  word 英语词(多为变形词:复数/分词/第三人称单数等)
  zh   当前中文译文(有问题)
  note 质检员指出的问题

请你**重写**该词条的中文译文。要求:
- 用你自身的英语知识给出**该词本身**的准确中文释义(不是它原形的、也不是形近词的);
- 保留"X的复数/现在分词"这类形态说明作为首行,再换行给出真实词义,格式如:
    horse brass的复数形式
    n. 马饰铜牌
- 词义要给最常用的 1–3 个,简洁;有学科属性可带 [医][化] 等标签;动词用 v./vt./vi.,名词 n.,形容词 adj.。

**但如果这个词条根本不该存在,就不要硬编译文**,返回 {"fix":"skip","why":"…"}:
- 专有名词被机械加了复数(pakistans/GoYas/Newsweeks —— 国名、人名、刊物名无复数);
- 元描述里的原形认错且该词并非真实英语词(heires/blacklions/wulds);
- 该拼写就是错拼,不是一个词。

每条返回 {"fix":"rewrite","zh":"重写后的完整译文(可含换行\\n)"} 或 {"fix":"skip","why":"原因"}。
严格输出 JSON {"1":{...},"2":{...}},键与输入一致,无多余文字。"""


def load_bad():
    fill = {}
    for i, ln in enumerate(open(FILL, encoding="utf-8")):
        if i:
            c = ln.rstrip("\n").split("\t")
            if len(c) >= 5:
                fill[int(c[0])] = c[3].replace("\\n", "\n")
    rows = []
    for ln in open(SWEEP, encoding="utf-8"):
        d = json.loads(ln)
        if d.get("v") == "bad" and d["id"] in fill:
            rows.append((d["id"], d["w"], d["zh"], d.get("note", ""), fill[d["id"]]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    rows = load_bad()
    if a.limit:
        rows = rows[:a.limit]
    print(f"[A1 重写] judge 判 bad 且可定位原文的 {len(rows)} 条", flush=True)
    if not rows:
        return

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "zh": r[2], "note": r[3]}
                            for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await S.run_batches(SYS, batches, env["DOUBAO_SEED_2_1_TURBO_BATCH"],
                                       cl.batch.chat.completions,
                                       (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 180))
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); rewrites = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, zh, note, before) in enumerate(meta, 1):
            v = res.get(str(k))
            act = v.get("fix") if isinstance(v, dict) else None
            if act == "rewrite" and isinstance(v.get("zh"), str) and v["zh"].strip():
                tally["rewrite"] += 1
                rewrites.append((rid, w, before, v["zh"].strip()))
            elif act == "skip":
                tally["skip(退回空壳)"] += 1
            else:
                tally["novote(退回空壳)"] += 1

    print(f"\n===== 重写 {sum(tally.values())} 条 token {tok} =====")
    for k, v in tally.most_common():
        print(f"  {k:18} {v:>6}")
    for rid, w, before, new in rewrites[:10]:
        print(f"\n  {w}\n    前: {before.replace(chr(10),' ⏎ ')[:60]}\n    后: {new.replace(chr(10),' ⏎ ')[:76]}")

    if not a.run or not rewrites:
        print("\n(dry-run;加 --run 写库。skip/novote 的保持撤回后的空壳原状)")
        return

    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-a1rewrite-{tag}.bak"))
    conn = sqlite3.connect(DB)

    # ⚠️ 重跑安全:先把上一轮写过的重写**全部退回空壳**,再落本轮结果。
    #    判官有随机性,同一条两次可能一次 rewrite 一次 skip;若不先退,
    #    上一轮写入、这一轮改判 skip 的条目会**留在库里且不在留痕中**(我踩过,83 条孤儿)。
    #    保守取向:只要有一轮判 skip 就退回空壳,不硬编译文。
    if LOG.exists():
        undo = 0
        for i, ln in enumerate(open(LOG, encoding="utf-8")):
            if not i:
                continue
            c = ln.rstrip("\n").split("\t")
            if len(c) >= 3:
                conn.execute("UPDATE stardict SET translation=? WHERE id=?",
                             (c[2].replace("\\n", "\n"), int(c[0])))
                undo += 1
        conn.commit()
        print(f"  (重跑保护:先退回上一轮重写 {undo} 条)")

    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tbefore\tafter\n")
        for rid, w, before, new in rewrites:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            f.write("\t".join([str(rid), w, before.replace("\n", "\\n"),
                               new.replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已重写 {len(rewrites)} 条,留痕 → {LOG.name};备份 pre-a1rewrite-{tag}.bak")


if __name__ == "__main__":
    main()
