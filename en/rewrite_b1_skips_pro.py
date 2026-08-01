#!/usr/bin/env python3
"""turbo 判 skip 的 B1 可疑条目,交 pro 复核重写。见对话 2026-07-28。

rewrite_b1_suspect.py(turbo batch)对 4,164 条可疑的处理:rewrite 2,946 / skip 1,218。
抽 200 条给 pro 复核这批 skip:**pro 能救 53%,只有 46% 确实不成立**。
turbo 的失败模式很一致 —— **它不认识罕用的动词化用法,就判定"这词不存在"**:
    tobaccoed  turbo保持 n.烟草,香烟   → pro: <罕>用烟草处理;给…供应烟草
    saucering  turbo保持 n.茶碟,茶托   → pro: <罕>(使)成碟状;(眼睛)睁大呈碟形
    smegged    turbo保持 弹簧制造者出口集团 → pro: <俚>弄脏;(感叹)该死(源自《红矮星号》)
→ 这批只有 1,218 条,全量走 pro online 约 13 万 token,很便宜。
   ⭐ 经验:**turbo 能校对、能处理常规义,但长尾/罕用/俚语的判断力不够,该上 pro**
   (与 [[doubao-seed21-adjudicator]] 里"turbo 能校对不能判性别"是同一类分工问题)。

⚠️ skip 分支 = **保持现状**(kaikki 回填版),不退回 [网络] —— B1 的原状本身 bad 53.6%,退回更差。

用法:
  python3 en/rewrite_b1_skips_pro.py            # dry-run
  python3 en/rewrite_b1_skips_pro.py --run      # 备份后写库,留痕 b1_skips_pro.tsv
"""
import argparse, asyncio, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import rewrite_b1_suspect as RW

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
DONE = paths.WORK / "ledgers/b1_rewrite.tsv"
LOG = paths.WORK / "ledgers/b1_skips_pro.tsv"
CHUNK = 10

SYS = """你是英汉词典编纂专家。给你一批英语词条,每条含 word、rel(形态关系)、zh(当前译文,有问题)。
一个较小的模型认为这些词条"不成立、无法给出正确释义"。请你复核 —— 它常常是**不认识罕用的动词化用法**就误判。
- 若该词确实存在(哪怕生僻、古体、方言、俚语、网络用语、罕用动词化),给出准确中文释义:
  {"fix":"rewrite","zh":"首行保留 rel 这句形态说明,换行后给该词本身的词义"}
  词义 1–3 个,简洁;动词用 v./vt./vi.,名词 n.,形容词 adj.;可用 <罕><古><俚><非正式> 等标记;有学科属性可带 [医][化] 标签。
- 若确实不成立(原形是纯名词/形容词且不存在该动词变形、原形其实是缩写、该拼写不是真实英语词),返回
  {"fix":"skip","why":"原因"}
严格输出 JSON {"1":{...},"2":{...}},键与输入一致,无多余文字。"""


def load_skips(conn):
    done = set()
    if DONE.exists():
        for i, ln in enumerate(open(DONE, encoding="utf-8")):
            if i:
                done.add(int(ln.split("\t")[0]))
    return [r for r in RW.load_suspect(conn) if r[0] not in done]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    rows = load_skips(conn)
    if a.limit:
        rows = rows[:a.limit]
    print(f"[B1 skip → pro 复核] {len(rows)} 条", flush=True)

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=A.TIMEOUT)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "rel": r[2], "zh": r[3]}
                            for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await A.run_batches(SYS, batches, env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions)
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); rewrites = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, rel, after, why) in enumerate(meta, 1):
            v = res.get(str(k))
            act = v.get("fix") if isinstance(v, dict) else None
            if act == "rewrite" and isinstance(v.get("zh"), str) and v["zh"].strip():
                tally["pro 救回"] += 1
                rewrites.append((rid, w, after, v["zh"].strip()))
            else:
                tally["确认不成立(保持现状)"] += 1

    print(f"\n===== {sum(tally.values())} 条 token {tok} =====")
    for k, v in tally.most_common():
        print(f"  {k:22} {v:>5}")
    for rid, w, old, new in rewrites[:6]:
        print(f"\n  {w}\n    前: {old.replace(chr(10),' / ')[:56]}\n    后: {new.replace(chr(10),' / ')[:68]}")

    if not a.run or not rewrites:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-b1skip-{tag}.bak"))
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
    print(f"\n已重写 {len(rewrites)} 条,留痕 → {LOG.name};备份 pre-b1skip-{tag}.bak")


if __name__ == "__main__":
    main()
