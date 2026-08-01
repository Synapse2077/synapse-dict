#!/usr/bin/env python3
"""A1a+A1d 回填结果**全量** judge + 撤回 bad。见对话 2026-07-27。

为什么全量而不是继续加规则闸:
  抽样验到 bad≈3.7% 后逐条看根因,**7/11 是 base 词条自身译文就错**
  (basker→"巴斯克"实为晒太阳的人 / budworm→"蚜虫"实为芽虫 / alderfly→"蜻蜓科"实为泥蛉)。
  回填只是原样抄了一条本来就错的 base —— **这种规则天生判不了**,再扩闸只会误伤
  (试过用"河/岛/山/湖"扩专名闸,精度仅 50%,capibara「产于南美湖泊溪流间」这种好条目全被误杀)。
  → 直接把 10,506 条**全量**交 judge,判 bad 的撤回(撤回=恢复成原来那句没用的元描述,不新增伤害)。

turbo batch 半价 + pro 超时兜底(同 sweep_core.py)。
用法:
  python3 en/sweep_a1.py                # 全量判,只产清单
  python3 en/sweep_a1.py --revert       # 判完直接撤回 bad(先备份)
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
OUT = paths.WORK / "runs/sweep_a1.jsonl"
CHUNK = 20

JUDGE_SYS = """你是英汉词典质检专家。给你一批英语词条,每条含 word(英语词)、zh(中文译文)。
这些 word 是**变形词**(复数/分词等)或**异体拼写词**,译文格式为「X的复数/X的替代拼写」+ 换行 + 原形/标准词 X 的词义。
凭你自身英语知识,判断这条中文对该英语词是否有**硬伤**。只把下列情况判 bad:
- **词义错**:给出的中文与该词实际意思不符(basker 给成"巴斯克"、budworm 给成"蚜虫"、alderfly 给成"蜻蜓科昆虫");
- **原形/标准词认错**:元描述里的 X 根本不是该词的原形或标准拼写(waterskied 说成 watersky 的、skuil 说成 school 的);
- **词义张冠李戴**:给的是另一个词的义(airmailer 给成 airmail 的义、upstager 给成 upstage 的义);
- **整条无有效词义**:回填过来的还是"X的变形"之类空话。

**以下一律判 ok(务必从宽)**:
- 词条生僻、古旧、方言、俚语 —— 只要词义对就是 ok;
- 带 [医][化][计][法] 学科标签、<美俚><德> 等语源标记 —— 有用信息,判 ok;
- 元描述把变形类型标错(实为第三人称单数却写"复数")、或专名/不可数名词本无复数 —— **这类只判 warn,不判 bad**;
- 义项列得多、保留了生僻义、缺词性前缀等格式小瑕 —— ok。

拿不准就判 ok。目标是产出**干净的硬伤清单**,宁可放过也不要误伤正确词条。
严格输出 JSON {"1":{"v":"ok"},"2":{"v":"bad","note":"简短问题"},...},键与输入一致,无多余文字。"""


def load_filled():
    """当前实际生效的回填行(fill 减去 reverted),连同回填前原文。"""
    rev = set()
    for f in ("ledgers/a1a_reverted.tsv", "ledgers/a1d_reverted.tsv"):
        p = HERE / f
        if p.exists():
            for i, ln in enumerate(open(p, encoding="utf-8")):
                if i:
                    rev.add(int(ln.split("\t")[0]))
    rows = []
    for f in ("ledgers/a1a_fill.tsv", "ledgers/a1d_fill.tsv"):
        p = HERE / f
        if not p.exists():
            continue
        for i, ln in enumerate(open(p, encoding="utf-8")):
            if not i:
                continue
            c = ln.rstrip("\n").split("\t")
            if len(c) < 5 or int(c[0]) in rev:
                continue
            rows.append((int(c[0]), c[1], c[3].replace("\\n", "\n"), c[4].replace("\\n", "\n")))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    rows = load_filled()
    if a.limit:
        rows = rows[:a.limit]
    print(f"[A1] 全量 judge 回填结果: {len(rows)} 条", flush=True)

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        hedge = (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 180)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "zh": r[3]} for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await S.run_batches(JUDGE_SYS, batches, model, cl.batch.chat.completions, hedge)
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter()
    bad = []
    with open(OUT, "w", encoding="utf-8") as f:
        for meta, res in zip(metas, results):
            res = res or {}
            for k, (rid, w, before, after) in enumerate(meta, 1):
                v = res.get(str(k))
                verdict = v.get("v") if isinstance(v, dict) else None
                if verdict not in ("ok", "warn", "bad"):
                    verdict = "novote"
                note = v.get("note", "") if isinstance(v, dict) else ""
                tally[verdict] += 1
                if verdict == "bad":
                    bad.append((rid, w, before, note))
                f.write(json.dumps(dict(id=rid, w=w, v=verdict, note=note, zh=after),
                                   ensure_ascii=False) + "\n")

    tot = sum(tally.values()); scored = tot - tally["novote"]
    print(f"\n===== A1 全量 judge {tot}(有效 {scored}) token {tok} =====")
    for lab in ("ok", "warn", "bad"):
        print(f"  {lab:5} {tally[lab]:>6} ({100*tally[lab]/max(scored,1):5.2f}%)")
    print(f"  novote {tally['novote']}")
    print(f"  清单 → {OUT.name}")

    if not a.revert or not bad:
        if not a.revert:
            print("\n(未撤回;加 --revert 把 bad 恢复成回填前原文)")
        return

    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-a1sweep-{tag}.bak"))
    conn = sqlite3.connect(DB)
    # 追加进禁止重填名单(a1a_reverted.tsv 同时是 fix_a1a.py 的 blocklist)
    with open(paths.WORK / "ledgers/a1a_reverted.tsv", "a", encoding="utf-8") as f:
        for rid, w, before, note in bad:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (before, rid))
            f.write("\t".join([str(rid), w, "", before.replace("\n", "\\n"), "J_全量judge判bad"]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已撤回 bad {len(bad)} 条,并写入禁止重填名单;备份 pre-a1sweep-{tag}.bak")


if __name__ == "__main__":
    main()
