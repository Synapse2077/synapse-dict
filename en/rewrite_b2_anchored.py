#!/usr/bin/env python3
"""B2 [网络]众包·其余:以 kaikki 英文释义为锚重写。见对话 2026-07-29。

B2 = 带 [网络] 标记但**不是**纯音译的那批(单行含拉丁字母/分号多候选/长译文),231,103 条,
抽样实测 **bad 22.3%** —— 除 B1 外最差。典型错法是乱码残片与张冠李戴:
    cumguzzler → "cum zz"      whyr → "链涜繙"      chapyter → "。子"
    berlinetta → "伯林尼塔;拉斯维加斯;限量"(实为双门跑车)
但它并非全坏:`clear title→清白产权`、`e-stop→紧急停止` 都对 —— **不能整桶删**。

kaikki 覆盖 **52,594/231,103 = 22.8%**,这批有权威英文释义可锚,方法与已完成的 B1 各批完全一致。
⭐ 英文释义已在输入里 = 翻译题 → lite;验收用 pro。

用法:
  python3 en/rewrite_b2_anchored.py --limit 400   # pilot
  python3 en/rewrite_b2_anchored.py --run
"""
import argparse, asyncio, json, re, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S
import buckets as B

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
GLOSS = HERE / "b2_kaikki_gloss.json"
LOG = HERE / "b2_anchored_fix.tsv"
CHUNK = 20

SYS = """你是英汉词典编纂专家。给你一批英语词条,每条含:
  word 英语词或词组
  zh   当前中文译文(来自网络众包,**约四分之一是错的:乱码残片、张冠李戴、机翻残句,不要盲信**)
  en   该词在 Wiktionary 的英文释义(可信,以它为准)
请依据 en 给出准确的中文译文:
- 直接给中文词义,1–3 个,简洁自然;
- 动词 v./vt./vi.,名词 n.,形容词 adj.,副词 adv.;缩写用 abbr. 并给出英文全称;
- 可用 <罕><古><俚><非正式><方> 标记;有学科属性可带 [医][化][计][法][植][动][经] 等标签;
- **以 en 为准**:zh 与 en 冲突时以 en 为准;zh 恰好与 en 一致时可沿用其措辞;
- **绝不能只写"X 的变体/异体/非标准拼写"就交差** —— 那等于没解释。必须给出**实际词义**,
  形态关系写在括注里,例:`'aircut` → `n. 理发(haircut 的省音拼写)`,不能只写"haircut 的非标准读音拼写";
- 专有名词(人名/地名/机构/作品名)给通行译名并注明类别;
- **不要在译文里写 [网络] 这个标记**(它在本库中另有含义);网络用语请写 <网络用语>。
**若 en 无实质信息、或你无法确定其含义,不要编造**,返回 {"fix":"skip","why":"原因"}。
每条返回 {"fix":"rewrite","zh":"译文"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""


def collect(conn):
    gl = json.load(open(GLOSS, encoding="utf-8"))
    rej = Counter(); out = []
    for rid, w, t, bk in B.load_tail(conn):
        if bk != "B2":
            continue
        k = w.strip().lower()
        g = gl.get(k)
        if not g:
            rej["kaikki 无释义"] += 1; continue
        en = g[0] if isinstance(g, list) else g
        if not en or len(en.strip()) < 4:
            rej["英文释义过短"] += 1; continue
        out.append((rid, w.strip(), (t or "").strip(), en.strip()))
    return out, rej


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    rows, rej = collect(conn)
    if a.limit:
        rows = rows[:a.limit]
    print(f"[B2 [网络]其余 · lite 依英文释义重写] {len(rows)} 条")
    for k, v in rej.most_common():
        print(f"  剔除 {k:14} {v:>7}")

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "zh": r[2][:120], "en": r[3][:180]}
                            for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await S.run_batches(SYS, batches, env["DOUBAO_MODEL_BATCH_LITE"],
                                       cl.batch.chat.completions,
                                       (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 300))
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); fixes = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, r in enumerate(meta, 1):
            v = res.get(str(k))
            act = v.get("fix") if isinstance(v, dict) else None
            if act == "rewrite" and isinstance(v.get("zh"), str) and v["zh"].strip():
                tally["rewrite"] += 1
                fixes.append((r[0], r[1], r[2], v["zh"].strip()))
            else:
                tally["skip(保持现状)"] += 1

    print(f"\n===== {sum(tally.values())} 条 token {tok} =====")
    for k, v in tally.most_common():
        print(f"  {k:18} {v:>6}")
    for rid, w, old, new in fixes[:8]:
        print(f"\n  {w}\n    前: {old.replace(chr(10),' / ')[:44]}\n    后: {new.replace(chr(10),' / ')[:66]}")

    if not a.run or not fixes:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-b2-{tag}.bak"))
    conn = sqlite3.connect(DB)
    if LOG.exists():   # 重跑保护
        for i, ln in enumerate(open(LOG, encoding="utf-8")):
            if i:
                c = ln.rstrip("\n").split("\t")
                conn.execute("UPDATE stardict SET translation=? WHERE id=?",
                             (c[2].replace("\\n", "\n"), int(c[0])))
        conn.commit()
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tbefore\tafter\n")
        for rid, w, old, new in fixes:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            conn.execute("UPDATE stardict SET qual='fixed' WHERE id=? AND qual NOT IN ('core','judged')", (rid,))
            f.write("\t".join([str(rid), w,
                               old.replace("\t", " ").replace("\n", "\\n"),
                               new.replace("\t", " ").replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已重写 {len(fixes)} 条(qual 已同步),留痕 → {LOG.name};备份 pre-b2-{tag}.bak")


if __name__ == "__main__":
    main()
