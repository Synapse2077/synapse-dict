#!/usr/bin/env python3
"""核心缺音标 turbo 生成 IPA(见对话 2026-07-27)。
现成源(ecdict/kaikki 自身)对这 8008 缺音标词收割≈0(全是派生词/专名,Wiktionary 也没标音),只剩 LLM 生成。
不造规则 G2P,turbo batch 生成英式(RP)+美式(GA) IPA。
  python3 en/gen_ipa.py --pilot 300   # 抽样生成,不写库,打印验质量
  python3 en/gen_ipa.py --run [--names]  # 全量写库(默认只真词,--names 含专名)
"""
import argparse, asyncio, json, re, shutil, sqlite3, random, time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich_core as ec

import paths

HERE = Path(__file__).resolve().parent
DB = str(paths.DB)
CORE = "(collins>0 OR oxford>0 OR frq>0 OR bnc>0 OR (tag IS NOT NULL AND TRIM(tag)<>''))"
NOPH = "(COALESCE(TRIM(phonetic),'')='' AND COALESCE(TRIM(phonetic_uk),'')='' AND COALESCE(TRIM(phonetic_us),'')='')"
IPA_OK = re.compile(r'^/[^/]+/$')

SYS = """你是英语语音学专家。给你一批英语词条,每条含 word、pos(词性,可能空)、def(简短英文/中文释义,帮你消歧同形词)。请输出每个词的**国际音标(IPA)**:
- 给**英式(RP)**和**美式(GA)**两种读音,各用斜杠包裹,如 /ˈnɔːməl/;
- **变形词按其实际读音**(normalized 读 /ˈnɔːməlaɪzd/,不是原形 normal 的音);
- **专有名词/姓氏**给最通行的英语读音;
- 只给音标,不要额外解释、不要重音以外的注释。
返回 JSON {"1":{"uk":"/.../","us":"/.../"},...},键与输入一致,无多余文字。"""


def rows_missing(limit=None, names=True, sample=None):
    c = sqlite3.connect(DB)
    sql = f"SELECT id, word, pos, translation FROM stardict WHERE {CORE} AND {NOPH} AND word NOT LIKE '% %'"
    if not names:
        sql += " AND word = lower(word)"
    rows = c.execute(sql).fetchall()
    c.close()
    if sample:
        random.seed(7); rows = random.sample(rows, min(sample, len(rows)))
    if limit:
        rows = rows[:limit]
    return rows


def gen(rows, env):
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=ec.TIMEOUT)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        hedge = (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 180)
        batches, metas = [], []
        for j in range(0, len(rows), ec.CHUNK):
            sub = rows[j:j + ec.CHUNK]
            p = {str(k): {"word": r[1], "pos": r[2] or "", "def": (r[3] or "")[:50]}
                 for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        res, tok = await ec.run_batches(SYS, batches, model, cl.batch.chat.completions, hedge)
        await cl.close(); return metas, res, tok

    return asyncio.run(go())


def do_pilot(n):
    rows = rows_missing(sample=n)
    print(f"[en] IPA pilot 生成 {len(rows)} 条(不写库)")
    env = ec.load_env()
    metas, results, tok = gen(rows, env)
    ok = bad = 0
    out = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, tr) in enumerate(meta, 1):
            v = res.get(str(k)) or {}
            uk = v.get("uk", ""); us = v.get("us", "")
            good = bool(IPA_OK.match(uk or "")) or bool(IPA_OK.match(us or ""))
            ok += good; bad += (not good)
            out.append((w, uk, us, good))
    print(f"生成 token {tok} | 格式合规 {ok} | 异常 {bad}\n")
    print("=== 抽看(真词优先,验准确度) ===")
    for w, uk, us, good in out[:60]:
        print(f"  {'✓' if good else '✗'} {w}: uk={uk} us={us}")


def do_run(names):
    rows = rows_missing(names=names)
    print(f"[en] IPA 全量生成: {len(rows)} 条 (含专名={names})")
    bak = Path(DB).with_suffix(f".pre-ipa-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy(DB, bak); print(f"已备份 {bak.name}")
    env = ec.load_env()
    metas, results, tok = gen(rows, env)
    conn = sqlite3.connect(DB)
    ov = paths.WORK / "ledgers/overrides.tsv"
    wrote = skip = 0
    ov_lines = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, tr) in enumerate(meta, 1):
            v = res.get(str(k)) or {}
            uk = (v.get("uk") or "").strip(); us = (v.get("us") or "").strip()
            # 存**裸** IPA(无外层斜杠)——展示层 App.tsx 会自己包 /.../,DB 带斜杠会双斜杠
            uk = uk[1:-1] if IPA_OK.match(uk) else ""
            us = us[1:-1] if IPA_OK.match(us) else ""
            if not uk and not us:
                skip += 1; continue
            ph = us or uk
            conn.execute("UPDATE stardict SET phonetic=?, phonetic_uk=?, phonetic_us=? WHERE id=?",
                         (ph, uk, us, rid))
            ov_lines.append(f"{w}\tphonetic\t\tuk={uk} us={us}")
            wrote += 1
    conn.commit(); conn.close()
    if ov_lines:
        with open(ov, "a", encoding="utf-8") as f:
            f.write("\n".join(ov_lines) + "\n")
    print(f"\n✅ [en] IPA 写库 {wrote} | 跳过(无合规音标) {skip} | token {tok}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, metavar="N")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--names", action="store_true", help="全量时含专名")
    a = ap.parse_args()
    if a.pilot:
        do_pilot(a.pilot)
    elif a.run:
        do_run(a.names)
    else:
        ap.print_help()
