#!/usr/bin/env python3
"""收口 fix_misalign.py 跑完后残留的 __misalign__ flag（葡语）。
全是真错位（turbo 多把近义词 gloss 合并/拆分对不上数）。改走 pro online 二次强拆对齐，
chunk 并发；要求 zh 数组长度严格==gloss 数组，对齐成功写库清 flag，失败留 flag 报出来人工兜。
（照搬 es/resolve_misalign59.py，去掉"已对齐清flag"分支——这批全是真错位。）

用法（在 pt/）：
  python3 resolve_misalign_residual.py --dry     # 分类统计 + 样本
  python3 resolve_misalign_residual.py --run      # pro online 对齐写库（自动备份）
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, asyncio, json, re, shutil, sqlite3, time
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
ENV = paths.ENV
CHUNK, CONC = 20, 20

SYS = """你是葡萄牙语→简体中文词典翻译专家。给你一批葡语词条，每条含词形 w、词性 pos、英文释义数组 gloss（每个元素是一个义项）。
逐义项翻译成地道简体中文，返回 "zh" 数组：
- **长度必须严格等于 gloss 数组长度，一一对应，一个不多一个不少**。哪怕两个义项是近义词也绝不合并成一条；哪怕一条 gloss 内含多个近义英文也绝不拆成多条。
- 英文释义仅作参考，以葡语实际含义为准（英文可能有误或过窄）。
- 一个义项内多个近义中文用"，"分隔；只给中文释义本身，不加词性/性别等标注。
严格输出 JSON，键与输入一致：{"1":{"zh":["义项1","义项2",...]},...}，无多余文字。"""


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
        pass
    out = {}
    for m in re.finditer(r'"(\d+)"\s*:\s*(?=\{)', s):
        key = m.group(1); i = m.end(); depth = 0
        for j in range(i, len(s)):
            if s[j] == '{':
                depth += 1
            elif s[j] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        out[key] = json.loads(s[i:j + 1])
                    except Exception:
                        pass
                    break
    if out:
        return out
    raise json.JSONDecodeError("lenient failed", s, 0)


def load_bad():
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "SELECT id, word, pos, definition, translation FROM dict "
        "WHERE flag LIKE '__misalign__%' ORDER BY word").fetchall()
    c.close()
    return [(_id, w, pos, (en or "").split("\n"), (zh or "").split("\n"))
            for _id, w, pos, en, zh in rows]


async def acall(comps, model, payload):
    delay = 2
    for att in range(4):
        try:
            r = await comps.create(
                model=model, temperature=0.2, reasoning_effort="minimal",
                messages=[{"role": "system", "content": SYS},
                          {"role": "user", "content": "输入：\n" + json.dumps(payload, ensure_ascii=False)}])
            out = r.choices[0].message.content.strip()
            out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
            out = out[out.find("{"):out.rfind("}") + 1]
            return loads_lenient(out)
        except Exception:
            if att == 3:
                raise
            await asyncio.sleep(delay); delay = min(delay * 2, 20)


async def solve(bad, env):
    from volcenginesdkarkruntime import AsyncArk
    client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
    model = env["DOUBAO_SEED_2_1_PRO"]
    batches, metas = [], []
    for j in range(0, len(bad), CHUNK):
        sub = bad[j:j + CHUNK]
        batches.append({str(k): {"w": r[1], "pos": r[2] or "", "gloss": r[3]} for k, r in enumerate(sub, 1)})
        metas.append(sub)
    results = [{} for _ in batches]
    q = asyncio.Queue()
    for i, b in enumerate(batches):
        q.put_nowait((i, b))

    async def worker():
        while True:
            try:
                i, p = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                results[i] = await acall(client.chat.completions, model, p) or {}
            except Exception as e:
                print("  ✗", e)
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(batches)))])
    await client.close()
    return metas, results


def do_run():
    bad = load_bad()
    print(f"残留真错位: {len(bad)} 条")
    if not bad:
        return
    bak = DB.with_suffix(f".pre-resolveres-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy(DB, bak); print(f"已备份 {bak.name}")
    env = load_env()
    metas, results = asyncio.run(solve(bad, env))
    conn = sqlite3.connect(str(DB))
    fixed, fail = 0, []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, gl, old) in enumerate(meta, 1):
            v = res.get(str(k))
            zh = v.get("zh") if isinstance(v, dict) else None
            if isinstance(zh, list) and len(zh) == len(gl):
                conn.execute("UPDATE dict SET translation=?, flag=NULL WHERE id=?",
                             ("\n".join(str(x) for x in zh), rid))
                fixed += 1
            else:
                got = len(zh) if isinstance(zh, list) else "无返回"
                fail.append((rid, w, gl, old, zh, got))
    conn.commit(); conn.close()
    print(f"\npro 对齐成功写库: {fixed}/{len(bad)} | 仍未搞定 {len(fail)}")
    if fail:
        print("\n⚠️ 需人工兜（逐条）：")
        for rid, w, gl, old, zh, got in fail:
            print(f"  [{rid}] {w}: 需{len(gl)} 得{got}  EN={gl}  旧ZH={old}  pro={zh}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.dry:
        bad = load_bad()
        print(f"残留真错位: {len(bad)} 条\n样本:")
        for r in bad[:8]:
            print(f"  {r[1]}: gloss{len(r[3])} vs zh{len(r[4])}  EN={r[3]}")
    elif a.run:
        do_run()
    else:
        ap.print_help()
