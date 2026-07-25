#!/usr/bin/env python3
"""修 B 组（语义存疑 flag，非 misalign，363 条）：pro online 逐词审校+修正。
pro 判 v(ok/warn/bad)+给 fix（与原 zh 等长）；bad/warn 应用 fix、ok 保留，**全部清 flag**（已复核）。
备份 + 写 overrides.tsv。用 pro online（小、快、便宜、判断力强）。
用法：
  python3 fix_flagged.py --dry     # 看目标集
  python3 fix_flagged.py --run     # pro 审校+修正+清flag+写库
"""
import argparse
import asyncio
import sqlite3
import time
from collections import Counter
from pathlib import Path

from fix_misalign import load_env, run_batches   # 复用鲁棒批处理（本地键+容错解析+重试）

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-fr.sqlite"
OVERRIDES = HERE / "overrides.tsv"
CHUNK = 20

SYS = """你是资深法语→简体中文词典审校专家。给你一批词条（这些是标记为"存疑"的词），每条含：词形 w、词性 pos、英文 gloss（消歧参考，可能有误或过窄）、当前中文译文数组 zh。
请**独立**用你的法语知识逐义项核对 zh 是否准确地道、有无错义/漏译/多译/词性错配。英文 gloss 仅参考，以法语实际含义为准。
对每个词返回：
  "v": "ok"(合格) | "warn"(不够精准可优化) | "bad"(有明确错译)
  "fix": 仅 v!="ok" 时给整条修正中文数组（**与原 zh 数组等长、逐项对应**，不增删义项）
  "note": v!="ok" 时一句话说明
严格输出 JSON，键与输入一致：{"1":{"v":"ok"},"2":{"v":"bad","fix":["..."],"note":"..."},...}，无多余文字。"""


def select_b():
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "SELECT id, word, pos, definition, translation FROM dict "
        "WHERE is_lemma=1 AND translation IS NOT NULL AND TRIM(translation)<>'' "
        "AND flag IS NOT NULL AND TRIM(flag)<>'' AND flag NOT LIKE '%misalign%'").fetchall()
    c.close()
    return rows


def do_run():
    rows = select_b()
    print(f"B 组存疑词: {len(rows)} 条")
    if not rows:
        return
    bak = DB.with_suffix(f".pre-flagged-{time.strftime('%Y%m%d-%H%M')}.bak")
    import shutil; shutil.copy(DB, bak); print(f"已备份 {bak.name}")
    env = load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
        model = env["DOUBAO_SEED_2_1_PRO"]
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            p = {str(k): {"w": r[1], "pos": r[2] or "", "gloss": (r[3] or "").split("\n"),
                          "zh": (r[4] or "").split("\n")} for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        print(f"pro online 审校 {len(rows)} 词 / {len(batches)} 批")
        res, tok = await run_batches(SYS, batches, model, cl.chat.completions, False)
        await cl.close()
        return metas, res, tok
    metas, results, tok = asyncio.run(go())

    conn = sqlite3.connect(str(DB))
    tally = Counter(); applied = 0; skipped_len = 0
    ov_lines = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, en, zh) in enumerate(meta, 1):
            v = res.get(str(k))
            verdict = v.get("v", "novote") if isinstance(v, dict) else "novote"
            tally[verdict] += 1
            if verdict in ("bad", "warn") and isinstance(v.get("fix"), list):
                old = (zh or "").split("\n")
                fix = [str(x) for x in v["fix"]]
                if len(fix) == len(old):        # 只在义项数一致才应用，防错位
                    conn.execute("UPDATE dict SET translation=?, flag=NULL WHERE id=?",
                                 ("\n".join(fix), rid))
                    applied += 1
                    ov_lines.append(f"{w}\ttranslation\t{(zh or '').replace(chr(10),' / ')}\t{' / '.join(fix)}")
                else:
                    skipped_len += 1        # 长度不符不动译文，但清 flag
                    conn.execute("UPDATE dict SET flag=NULL WHERE id=?", (rid,))
            elif verdict != "novote":
                conn.execute("UPDATE dict SET flag=NULL WHERE id=?", (rid,))   # ok/复核过→清flag
    conn.commit(); conn.close()
    if ov_lines:
        with open(OVERRIDES, "a", encoding="utf-8") as f:
            f.write("\n".join(ov_lines) + "\n")
    tot = sum(tally.values())
    print(f"\npro 审校 {tot} 条: ok {tally['ok']} / warn {tally['warn']} / bad {tally['bad']} / novote {tally['novote']}")
    print(f"  应用修正 {applied} 条（bad/warn 且义项数一致，已写库+overrides+清flag）")
    print(f"  义项数不符未改译文(仅清flag) {skipped_len}")
    print(f"  ok/复核过清 flag。token {tok}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--chunk", type=int, help="每批词数（话痨词调小防输出截断,如4）")
    a = ap.parse_args()
    if a.chunk:
        CHUNK = a.chunk
    if a.dry:
        rows = select_b()
        print(f"B 组存疑词: {len(rows)} 条\n样本:")
        c = sqlite3.connect(str(DB))
        for r in rows[:6]:
            fl = c.execute("SELECT flag FROM dict WHERE id=?", (r[0],)).fetchone()[0]
            print(f"  {r[1]}: flag='{fl[:40]}'  zh={(r[4] or '')[:30]}")
    elif a.run:
        do_run()
    else:
        ap.print_help()
