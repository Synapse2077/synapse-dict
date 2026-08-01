#!/usr/bin/env python3
"""收口 59 条 __misalign__ 残留 flag。
分两类处理：
  A. 已对齐(now gloss行数==zh行数)：flag 是旧残留，直接清 flag，不重译。
  B. 真错位(gloss行数!=zh行数)：交 pro online 重新逐义项对齐，
     要求 zh 数组长度严格==gloss 数组长度；对齐成功写库清 flag，失败留 flag 报出来人工兜。

用法（在 es/）：
  python3 resolve_misalign59.py --dry     # 分类统计 + 样本，不调用
  python3 resolve_misalign59.py --run      # A 清flag + B 走pro对齐写库（自动备份）
"""
import argparse, asyncio, json, re, shutil, sqlite3, time
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
ENV = paths.ENV

SYS = """你是西班牙语→简体中文词典翻译专家。给你一批西语词条，每条含词形 w、词性 pos、英文释义数组 gloss（每个元素是一个义项）。
逐义项翻译成地道简体中文，返回 "zh" 数组：
- **长度必须严格等于 gloss 数组长度，一一对应**，绝不合并、拆分、增删义项。
- 英文释义仅作参考，以西语实际含义为准（英文可能有误或过窄）。
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


def load_flagged():
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "SELECT id, word, pos, flag, definition, translation FROM dict "
        "WHERE flag LIKE '__misalign__%' ORDER BY word").fetchall()
    c.close()
    aligned, bad = [], []
    for _id, w, pos, flag, en, zh in rows:
        gl = (en or "").split("\n"); zl = (zh or "").split("\n")
        (aligned if len(gl) == len(zl) else bad).append((_id, w, pos, gl, zl))
    return aligned, bad


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


async def solve_bad(bad, env):
    from volcenginesdkarkruntime import AsyncArk
    client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
    model = env["DOUBAO_SEED_2_1_PRO"]
    payload = {str(k): {"w": r[1], "pos": r[2] or "", "gloss": r[3]} for k, r in enumerate(bad, 1)}
    res = await acall(client.chat.completions, model, payload)
    await client.close()
    return res or {}


def do_run():
    aligned, bad = load_flagged()
    print(f"A 已对齐(清flag): {len(aligned)} | B 真错位(pro对齐): {len(bad)}")
    bak = DB.with_suffix(f".pre-resolve59-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy(DB, bak); print(f"已备份 {bak.name}")

    conn = sqlite3.connect(str(DB))
    # A: 直接清 flag
    for _id, *_ in aligned:
        conn.execute("UPDATE dict SET flag=NULL WHERE id=?", (_id,))
    conn.commit()
    print(f"A 清 flag 完成: {len(aligned)} 条")

    # B: pro online 对齐
    env = load_env()
    res = asyncio.run(solve_bad(bad, env))
    fixed, fail = 0, []
    for k, (rid, w, pos, gl, old) in enumerate(bad, 1):
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
    print(f"\nB pro 对齐成功写库: {fixed}/{len(bad)}")
    if fail:
        print(f"\n⚠️ pro 未搞定 {len(fail)} 条，需人工兜：")
        for rid, w, gl, old, zh, got in fail:
            print(f"  [{rid}] {w}: 需{len(gl)}义 得{got}")
            print(f"     EN: {gl}")
            print(f"     旧ZH: {old}")
            print(f"     pro: {zh}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.dry:
        aligned, bad = load_flagged()
        print(f"A 已对齐(清flag): {len(aligned)} | B 真错位(pro对齐): {len(bad)}")
        print("\nB 真错位样本:")
        for r in bad[:6]:
            print(f"  {r[1]}: gloss{len(r[3])} vs zh{len(r[4])}  EN={r[3]}  ZH={r[4]}")
    elif a.run:
        do_run()
    else:
        ap.print_help()
