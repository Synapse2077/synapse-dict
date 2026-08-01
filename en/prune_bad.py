#!/usr/bin/env python3
"""删繁纠错:对 sweep 硬伤里"混入原形全义/假形态/错译"这族做 prune(见对话 2026-07-27)。
与 enrich(补漏)相反——enrich 保留形态说明会把假说明也留下;这里明确指令**删**。
只碰 prune_llm_ids.json 名单,turbo batch,放开长度闸(删繁就是变短),备份+overrides。用法(仓库根):
  python3 en/prune_bad.py
"""
import asyncio, json, re, shutil, sqlite3, time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich_core as ec

import paths

HERE = Path(__file__).resolve().parent
DB = str(paths.DB)
IDS = paths.WORK / "runs/prune_llm_ids.json"
CJK = re.compile(r'[一-鿿]')

PRUNE_SYS = """你是英汉词典编辑,负责给词条**删繁纠错**(不是补充)。给你一批英语词条,每条含 word、pos、def(英文释义,可能空)、zh(现有中文译文,混进了不属于该词的错误或冗余)。请**删掉**混入项,只留该词真正、正确的义项:
- **删假形态说明**:把专有名词或普通词误标成某词的"复数/最高级/比较级/第三人称单数/过去式"等(armrest 不是"armr的最高级";Abbas 不是"abba的复数")——删掉这种错误说明;
- **删混入的原形义**:变形词(现在分词/过去式/复数等)硬塞了原形的名词/人名义而这些义不适用——删掉。变形词只保留:正确的形态说明(如"advocate的过去式和过去分词")+该形态本身适用的义项;
- **删错译**:与该词实际意思不符的义项(adduction 无"氧化"义;banque 是法语"银行"不是"宴会";bois 是法语"树林"不是"木香")——删掉;**若删后该词没有正确义项了,补上正确义**;
- **保留**该词所有正确、适用的义项;学科标签([医][计][化]等)只要义项对就**留着**,不要删标签。
保持 ECDICT 风格:词性前缀(n./v./a./vt./vi.)、简洁、多义换行或逗号分隔。
若现有译文已无可删且正确,原样返回。返回 JSON {"1":{"zh":"改后的完整中文译文"},...},键与输入一致,无多余文字。"""


def enrich_prune(rows, env):
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=ec.TIMEOUT)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        hedge = (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 180)
        batches, metas = [], []
        for j in range(0, len(rows), ec.CHUNK):
            sub = rows[j:j + ec.CHUNK]
            p = {str(k): {"word": r[1], "pos": r[2] or "", "def": (r[3] or "")[:120], "zh": r[4]}
                 for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        res, tok = await ec.run_batches(PRUNE_SYS, batches, model, cl.batch.chat.completions, hedge)
        await cl.close(); return metas, res, tok

    return asyncio.run(go())


def main():
    ids = json.load(open(IDS))
    conn = sqlite3.connect(DB)
    qm = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, word, pos, definition, translation FROM stardict WHERE id IN ({qm})", ids).fetchall()
    conn.close()
    print(f"[en] prune 删繁: {len(rows)} 条", flush=True)

    bak = Path(DB).with_suffix(f".pre-prunellm-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy(DB, bak); print(f"已备份 {bak.name}")

    env = ec.load_env()
    metas, results, tok = enrich_prune(rows, env)

    conn = sqlite3.connect(DB)
    ov = paths.WORK / "ledgers/overrides.tsv"
    fixed = same = skip = 0
    ov_lines = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, dfn, old) in enumerate(meta, 1):
            v = res.get(str(k))
            new = v.get("zh") if isinstance(v, dict) else None
            if not new or not isinstance(new, str) or not CJK.search(new):
                skip += 1; continue
            if new.strip() == old.strip():
                same += 1; continue
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            ov_lines.append(f"{w}\ttranslation\t{old.replace(chr(10),' / ')}\t{new.replace(chr(10),' / ')}")
            fixed += 1
    conn.commit(); conn.close()
    if ov_lines:
        with open(ov, "a", encoding="utf-8") as f:
            f.write("\n".join(ov_lines) + "\n")
    print(f"\n✅ [en] prune 写库 {fixed} | 未变 {same} | 跳过 {skip} | token {tok}", flush=True)


if __name__ == "__main__":
    main()
