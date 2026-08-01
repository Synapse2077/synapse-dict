#!/usr/bin/env python3
"""纯音译尾巴抽样验证(read-only)。见对话 2026-07-27。
背景:非核心 [网络] 尾巴里 65.5%(437k)是"译文≤8汉字、无解释"的人名/地名音译。
问题:这些到底是"用户选中该名时想要的合理音译",还是垃圾?抽 1000 交 pro 判。
分类:name=正确音译/通行译名(合理即 ok) | word=普通词正确义 | bad=音译错/张冠李戴/无意义乱码。
用法: python3 en/verify_translit.py --n 1000
"""
import argparse, asyncio, json, re, sqlite3, random
from pathlib import Path
from collections import Counter
import acceptance_en as A  # 复用 load_env/acall/run_batches/loads_lenient

import paths

HERE = Path(__file__).resolve().parent
DB = str(paths.DB)
CORE = A.CORE
CHUNK = 20

JUDGE_SYS = """你是英汉词典质检专家。给你一批英语词条,每条含 word(英语词)、zh(中文译文,来自网络协作,多为人名/地名音译或短义)。
凭你自身知识,判断该中文对该英语词是否是**准确、可用**的译名/词义:
- name = 是该词的人名/地名/专名的**正确音译或通行译名**(即便生僻,只要音译合理、能对上原词读音即算);
- word = 是**普通词汇**的正确中文义(不是专名);
- bad = 音译**明显错误**/张冠李戴(译成了无关的人或物)/无意义乱码/与该词毫无关系。
每条返回 {"v":"name|word|bad","note":"简短问题(bad时)"}。
严格输出 JSON {"1":{"v":"name"},"2":{"v":"bad","note":"..."},...},键与输入一致,无多余文字。"""


def sample_translit(n, seed=20260727):
    c = sqlite3.connect(DB)
    rows = c.execute(
        f"SELECT id, word, translation FROM stardict "
        f"WHERE translation LIKE '%[网络]%' AND NOT {CORE}").fetchall()
    c.close()
    # 纯音译桶:整条为单行 [网络] + 译文 body 是 ≤8 个纯汉字(与分类器同定义)
    pool = []
    for i, w, t in rows:
        if "\n" in t.strip():
            continue
        body = t.split("]", 1)[-1].strip() if "]" in t else t.strip()
        if re.fullmatch(r"[一-鿿·]{1,8}", body):
            pool.append((i, w, body))
    random.seed(seed)
    return pool, random.sample(pool, min(n, len(pool)))


def do_run(n):
    pool, rows = sample_translit(n)
    print(f"[纯音译桶] 总 {len(pool)} 条,抽样 {len(rows)} 条交 pro")
    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=A.TIMEOUT)
        model = env["DOUBAO_SEED_2_1_PRO"]
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            p = {str(k): {"word": r[1], "zh": r[2]} for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        res, tok = await A.run_batches(JUDGE_SYS, batches, model, cl.chat.completions)
        await cl.close(); return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); bad = []
    outp = paths.WORK / "runs/verify_translit.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        for meta, res in zip(metas, results):
            res = res or {}
            for k, (rid, w, zh) in enumerate(meta, 1):
                v = res.get(str(k))
                verdict = v.get("v") if isinstance(v, dict) else None
                if verdict not in ("name", "word", "bad"):
                    verdict = "novote"
                tally[verdict] += 1
                note = v.get("note", "") if isinstance(v, dict) else ""
                if verdict == "bad":
                    bad.append((w, zh, note))
                f.write(json.dumps(dict(w=w, zh=zh, v=verdict, note=note), ensure_ascii=False) + "\n")
    tot = sum(tally.values()); scored = tot - tally["novote"]
    print(f"\n===== [纯音译] 验证 {tot} 条(有效 {scored}) token {tok} =====")
    for lab in ("name", "word", "bad"):
        print(f"  {lab:5} {tally[lab]} ({100*tally[lab]/max(scored,1):.1f}%)")
    print(f"  novote {tally['novote']}")
    print(f"  合理保留率(name+word): {100*(tally['name']+tally['word'])/max(scored,1):.1f}%")
    print("  bad 样本:")
    for w, z, note in bad[:25]:
        print(f"    {w}: {z} || {note[:40]}")
    print(f"  明细 → {outp.name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    do_run(ap.parse_args().n)
