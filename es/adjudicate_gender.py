#!/usr/bin/env python3
"""gender 冲突裁决（盲投）：conflict_review.tsv 里 3070 条 kaikki↔豆包 性别分歧。
turbo batch 盲投——**只给词形+中文消歧，不给任何候选值**，让它独立判性别，避免复读。
再与 库(=kaikki 权威) + 冲突文件的豆包值 三方比对：
  盲投==库(kaikki)        → keep（kaikki 对，不动）
  盲投==豆包(≠kaikki)     → override（两个独立信号 vs kaikki → 覆盖库为盲投值）
  盲投=第三值/无           → three_way（存疑，保库不动）
应用 override 到库 gender，写 overrides.tsv 耐重建，自动备份。
用法：
  python3 adjudicate_gender.py --run       # turbo batch 盲投 → 三方比对 → 应用 override
  python3 adjudicate_gender.py --check 60   # pro 抽样验收 override 的对错
"""
import argparse
import asyncio
import json
import random
import sqlite3
import time
from collections import Counter
from pathlib import Path

from fix_misalign import load_env, run_batches   # 复用鲁棒批处理

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
CONFLICT = paths.WORK / "conflict_review.tsv"
OVERRIDES = paths.WORK / "overrides.tsv"
DECISIONS = paths.WORK / "gender_decisions.tsv"
CHUNK, CONC = 30, 100

VOTE_SYS = """你是西班牙语词典专家。给你一批西语名词（含中文词义消歧）。判断每个词的语法性别，只回：
m（阳性，el）、f（阴性，la）、mf（共性，同形兼阳阴，如 el/la estudiante、el/la artista、el/la testigo）。
按你的西语知识独立判断该名词最主要的语法性别，严格输出 JSON {"1":"m","2":"f",...}，键与输入一致，无多余文字。"""

CHECK_SYS = """你是西班牙语词典专家。给你一批西语名词，含词形 w、中文词义 zh、以及一个"待核性别" g。
判断该 g 是否正确（m=el / f=la / mf=共性）。返回每词 "v": "ok"(正确) | "bad"(错误)，bad 时 "right" 给正确性别。
严格输出 JSON {"1":{"v":"ok"},"2":{"v":"bad","right":"f"},...}，无多余文字。"""


def read_gender_conflicts():
    """返回 {word: doubao_gender}（冲突文件里 field=gender 的）。"""
    out = {}
    for i, ln in enumerate(open(CONFLICT, encoding="utf-8")):
        if i == 0:
            continue
        p = ln.rstrip("\n").split("\t")
        if len(p) >= 4 and p[1] == "gender":
            out[p[0]] = p[3]   # doubao 值
    return out


def load_db_gender_gloss(words):
    c = sqlite3.connect(str(DB))
    m = {}
    for i in range(0, len(words), 400):
        batch = words[i:i + 400]
        ph = ",".join("?" * len(batch))
        for w, g, zh in c.execute(
                f"SELECT word, gender, translation FROM dict WHERE word IN ({ph}) "
                f"COLLATE NOCASE AND is_lemma=1", batch):
            if w not in m:
                m[w] = (g, (zh or "").split("\n")[0][:40])
    c.close()
    return m


def do_run():
    conf = read_gender_conflicts()
    words = sorted(conf)
    dbm = load_db_gender_gloss(words)
    words = [w for w in words if w in dbm]      # 库里还在的
    print(f"gender 冲突 {len(conf)}，库中可裁 {len(words)}")
    env = load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        batches, metas = [], []
        for j in range(0, len(words), CHUNK):
            sub = words[j:j + CHUNK]
            p = {str(k): {"w": w, "zh": dbm[w][1]} for k, w in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        print(f"turbo batch 盲投 {len(words)} 词 / {len(batches)} 批 / 并发 {CONC}（尾延迟对冲: 慢批切pro online）")
        hedge = (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 180)
        res, tok = await run_batches(VOTE_SYS, batches, model, cl.batch.chat.completions, True, hedge)
        await cl.close()
        return metas, res, tok
    metas, results, tok = asyncio.run(go())

    tally = Counter(); overrides = []; decisions = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, w in enumerate(meta, 1):
            fresh = res.get(str(k))
            fresh = str(fresh).strip() if fresh else None
            kk = dbm[w][0]; db = conf[w]
            if fresh not in ("m", "f", "mf"):
                verdict = "no_vote"
            elif fresh == kk:
                verdict = "keep_kaikki"
            elif fresh == db:
                verdict = "override"; overrides.append((w, kk, fresh))
            else:
                verdict = "three_way"
            tally[verdict] += 1
            decisions.append((w, kk or "", db, fresh or "", verdict))

    # 备份 + 应用 override
    if overrides:
        bak = DB.with_suffix(f".pre-gender-{time.strftime('%Y%m%d-%H%M')}.bak")
        import shutil; shutil.copy(DB, bak); print(f"已备份 {bak.name}")
        conn = sqlite3.connect(str(DB))
        for w, old, new in overrides:
            conn.execute("UPDATE dict SET gender=? WHERE word=? COLLATE NOCASE AND is_lemma=1", (new, w))
        conn.commit(); conn.close()
        # overrides.tsv 耐重建
        with open(OVERRIDES, "a", encoding="utf-8") as f:
            for w, old, new in overrides:
                f.write(f"{w}\tgender\t{old}\t{new}\n")
    with open(DECISIONS, "w", encoding="utf-8") as f:
        f.write("word\tkaikki\tdoubao\tfresh_vote\tverdict\n")
        for r in decisions:
            f.write("\t".join(r) + "\n")
    print(f"\n三方比对 {sum(tally.values())} → {DECISIONS.name}")
    print(f"  keep_kaikki {tally['keep_kaikki']}（kaikki 对，不动）")
    print(f"  override    {tally['override']}（盲投+豆包 vs kaikki → 已覆盖库+写overrides）")
    print(f"  three_way   {tally['three_way']}（存疑，保库）")
    print(f"  no_vote     {tally['no_vote']}")
    print(f"  token {tok}")
    print("下一步：python3 adjudicate_gender.py --check 60")


def do_run_pro():
    """pro online 权威重裁：读 gender_decisions.tsv(有每词原始 kaikki 值)，pro 盲投，
    pro 判定直接作权威落库；no_vote 恢复成 kaikki。清掉 turbo 的错覆盖。重写 overrides.tsv。"""
    if not DECISIONS.exists():
        raise SystemExit("先跑过 --run（要 gender_decisions.tsv 的 kaikki 原值）")
    kaikki = {}
    for r in [ln.rstrip("\n").split("\t") for ln in open(DECISIONS, encoding="utf-8")][1:]:
        if len(r) >= 2:
            kaikki[r[0]] = r[1]           # word -> 原始 kaikki 性别
    words = sorted(kaikki)
    dbm = load_db_gender_gloss(words)
    words = [w for w in words if w in dbm]
    print(f"pro 权威重裁 {len(words)} 条 gender 冲突")
    env = load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
        model = env["DOUBAO_SEED_2_1_PRO"]
        batches, metas = [], []
        for j in range(0, len(words), CHUNK):
            sub = words[j:j + CHUNK]
            p = {str(k): {"w": w, "zh": dbm[w][1]} for k, w in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        res, tok = await run_batches(VOTE_SYS, batches, model, cl.chat.completions, False)
        await cl.close()
        return metas, res, tok
    metas, results, tok = asyncio.run(go())

    bak = DB.with_suffix(f".pre-genderpro-{time.strftime('%Y%m%d-%H%M')}.bak")
    import shutil; shutil.copy(DB, bak); print(f"已备份 {bak.name}")
    conn = sqlite3.connect(str(DB))
    tally = Counter(); changed = []; mf_ct = 0; restored = 0
    for meta, res in zip(metas, results):
        res = res or {}
        for k, w in enumerate(meta, 1):
            v = res.get(str(k))
            v = str(v).strip() if v else None
            kk = kaikki.get(w, "")
            if v in ("m", "f", "mf"):
                conn.execute("UPDATE dict SET gender=? WHERE word=? COLLATE NOCASE AND is_lemma=1", (v, w))
                if v == "mf":
                    mf_ct += 1
                if v != kk:
                    changed.append((w, kk, v)); tally["pro_changed"] += 1
                else:
                    tally["pro==kaikki"] += 1
            else:
                # no_vote：恢复原始 kaikki（清掉 turbo 可能的错覆盖）
                if kk in ("m", "f", "mf"):
                    conn.execute("UPDATE dict SET gender=? WHERE word=? COLLATE NOCASE AND is_lemma=1", (kk, w))
                    restored += 1
                tally["no_vote_restored"] += 1
    conn.commit(); conn.close()
    # 重写 overrides.tsv（清掉 turbo 的，换成 pro 权威的）
    with open(OVERRIDES, "w", encoding="utf-8") as f:
        for w, old, new in changed:
            f.write(f"{w}\tgender\t{old}\t{new}\n")
    print(f"\npro 权威裁决 {sum(tally.values())} 条：")
    print(f"  pro 改动(≠kaikki) {tally['pro_changed']}（已落库+重写 overrides.tsv）")
    print(f"  pro==kaikki {tally['pro==kaikki']}（不动）")
    print(f"  no_vote 恢复kaikki {tally['no_vote_restored']}")
    print(f"  其中判 mf 共性: {mf_ct}（turbo 塌缩的 mf 应被救回）  token {tok}")


def do_check(n):
    """pro 抽样验收 override 后的库性别是否正确。"""
    if not DECISIONS.exists():
        raise SystemExit("先 --run")
    ov = [ln.rstrip("\n").split("\t") for ln in open(DECISIONS, encoding="utf-8")][1:]
    ov = [r for r in ov if len(r) >= 5 and r[4] == "override"]
    if not ov:
        print("无 override 可验"); return
    random.seed(1); samp = random.sample(ov, min(n, len(ov)))
    dbm = load_db_gender_gloss([r[0] for r in samp])
    env = load_env()
    from volcenginesdkarkruntime import AsyncArk
    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
        model = env["DOUBAO_SEED_2_1_PRO"]
        batches, metas = [], []
        for j in range(0, len(samp), 20):
            sub = samp[j:j + 20]
            p = {str(k): {"w": r[0], "zh": dbm.get(r[0], ("", ""))[1], "g": r[3]}
                 for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        res, tok = await run_batches(CHECK_SYS, batches, model, cl.chat.completions, False)
        await cl.close(); return metas, res, tok
    metas, results, tok = asyncio.run(go())
    t = Counter(); wrong = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, r in enumerate(meta, 1):
            v = res.get(str(k))
            if isinstance(v, dict):
                vv = v.get("v", "novote"); t[vv] += 1
                if vv == "bad":
                    wrong.append((r[0], r[3], v.get("right", "?")))
    tot = sum(t.values())
    print(f"\npro 验收 override {tot} 条: 正确(ok) {t['ok']}({100*t['ok']/max(tot,1):.0f}%) / 错(bad) {t['bad']}  token {tok}")
    for w, g, right in wrong[:8]:
        print(f"  误覆盖: {w} 覆成{g} pro说应为{right}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--pro", action="store_true", help="pro online 权威重裁(纠正turbo错覆盖)")
    ap.add_argument("--check", type=int, metavar="N")
    a = ap.parse_args()
    if a.run:
        do_run()
    elif a.pro:
        do_run_pro()
    elif a.check:
        do_check(a.check)
    else:
        ap.print_help()
