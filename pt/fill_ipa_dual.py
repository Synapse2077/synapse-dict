#!/usr/bin/env python3
"""pt 双读音 IPA 补空：给 ipa_br 或 ipa_pt 任一为空的 lemma 补音标，pro online 一次返回
巴西(br)+欧洲(pt)两个 IPA，各自写回对应列（只在返回合法 /.../ 时写，符号/缩写返回 null 跳过）。
用法（在 pt/）：
  python3 fill_ipa_dual.py --dry
  python3 fill_ipa_dual.py --run     # 自动备份
"""
import argparse, asyncio, json, re, shutil, sqlite3, time
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
ENV = paths.ENV
CHUNK, CONC = 20, 20

IPA_SYS = """你是葡萄牙语语音专家。给你一批词（可能含外来词、地名、缩写、词缀、古拼写等），逐个给**两个**音位式 IPA：
- "br" = 巴西葡萄牙语(pt-BR)，"pt" = 欧洲葡萄牙语(pt-PT)。
约定：标主重音 ˈ；把 br/pt 差异体现出来（欧葡非重读元音弱化/央化 ɐ/ɨ、词尾 -e 欧葡→ɨ 巴葡→i、词尾/音节末 -s 欧葡→ʃ 巴葡→s、r 的实现差异等）；两侧加斜杠，例 br /ˈkazɐ/ pt /ˈkazɐ/。
缩写、纯数字序号、词缀(以 - 开头或结尾)、无单词读音的 → br 和 pt 都返回 null。
严格输出 JSON，键与输入序号一致：{"1":{"br":"/.../","pt":"/.../"},"2":{"br":null,"pt":null},...}，无多余文字。"""


def load_env():
    e = {}
    for ln in open(ENV):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1); e[k] = v
    return e


def loads_lenient(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        s = re.sub(r'}\s*\n\s*(")', r'},\n\1', s)
        s = re.sub(r'}\s+(")', r'}, \1', s)
        s = re.sub(r',\s*([}\]])', r'\1', s)
        return json.loads(s)


def targets():
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "SELECT id, word FROM dict WHERE is_lemma=1 AND "
        "((ipa_br IS NULL OR TRIM(ipa_br)='') OR (ipa_pt IS NULL OR TRIM(ipa_pt)=''))").fetchall()
    c.close()
    return rows


async def acall(comps, model, payload):
    delay = 2
    for att in range(4):
        try:
            r = await comps.create(model=model, temperature=0.1, reasoning_effort="minimal",
                messages=[{"role": "system", "content": IPA_SYS},
                          {"role": "user", "content": "输入：\n" + json.dumps(payload, ensure_ascii=False)}])
            out = r.choices[0].message.content.strip()
            out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
            out = out[out.find("{"):out.rfind("}") + 1]
            return loads_lenient(out), getattr(getattr(r, "usage", None), "total_tokens", 0)
        except Exception:
            if att == 3:
                raise
            await asyncio.sleep(delay); delay = min(delay * 2, 20)


async def run(rows):
    from volcenginesdkarkruntime import AsyncArk
    env = load_env()
    client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
    model = env["DOUBAO_SEED_2_1_PRO"]
    batches, metas = [], []
    for j in range(0, len(rows), CHUNK):
        sub = rows[j:j + CHUNK]
        batches.append({str(k): w for k, (_id, w) in enumerate(sub, 1)}); metas.append(sub)
    results = [{} for _ in batches]
    q = asyncio.Queue()
    for i, b in enumerate(batches):
        q.put_nowait((i, b))
    tok = [0]
    async def worker():
        while True:
            try:
                i, p = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, t = await acall(client.chat.completions, model, p)
                results[i] = res; tok[0] += t
            except Exception as e:
                print("  ✗", e)
            q.task_done()
    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(batches)))])
    await client.close()
    return metas, results, tok[0]


def do_run():
    rows = targets()
    print(f"需补(任一空): {len(rows)} 条")
    if not rows:
        return
    bak = DB.with_suffix(f".pre-fillipa-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy(DB, bak); print(f"已备份 {bak.name}")
    metas, results, tok = asyncio.run(run(rows))
    conn = sqlite3.connect(str(DB))
    nb = np = 0
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w) in enumerate(meta, 1):
            v = res.get(str(k))
            if not isinstance(v, dict):
                continue
            br, pt = v.get("br"), v.get("pt")
            if isinstance(br, str) and br.startswith("/"):
                conn.execute("UPDATE dict SET ipa_br=? WHERE id=? AND (ipa_br IS NULL OR TRIM(ipa_br)='')", (br, rid)); nb += 1
            if isinstance(pt, str) and pt.startswith("/"):
                conn.execute("UPDATE dict SET ipa_pt=? WHERE id=? AND (ipa_pt IS NULL OR TRIM(ipa_pt)='')", (pt, rid)); np += 1
    conn.commit(); conn.close()
    print(f"写库 ipa_br {nb} / ipa_pt {np}。token {tok}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.dry:
        rows = targets()
        print(f"需补(任一空): {len(rows)} 条\n样本:", [w for _, w in rows[:15]])
    elif a.run:
        do_run()
    else:
        ap.print_help()
