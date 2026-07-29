#!/usr/bin/env python3
"""C6(无标记多词短语)有锚部分:lite **核对**(不是重写)。见对话 2026-07-29。

🔴 **C6 与前面几段本质不同,打法必须变**:B1/B2 的原文是 [网络] 众包垃圾(bad 22–54%),
   删什么都不亏,所以 prompt 写"别信 zh,重写它";**C6 原文来自 ECDICT 人工审校,九成是对的**
   (整桶抽样 bad 9.3%,有锚子集实测 bad 5.3%)。沿用"别信 zh"会让模型把 90% 的好条目也翻一遍
   —— 既费钱又制造回归。→ 改成**核对**:对的就 keep,只改真错的。实测 keep 率 86.2%。

⭐ **必须喂全部义项,不能只喂 kaikki 首义**(pilot v1 踩过,用户举 honky-tonk piano 才查清):
   `honky-tonk piano` kaikki 有两个 sense —— "An out of tune piano" + "**A style of ragtime music**",
   库里 `n. 走音钢琴 / n. 一种雷格泰姆音乐风格` 两个义都对、忠实对应。
   v1 只喂了 gloss[0],模型判第二个义是"错误增义"给删了 —— **纯损失,而且判官抓不到**
   (它只判"剩下的对不对",不判"丢没丢")。全库 C5+C6 有锚词形里 **7.8% 是多义**,
   与 v1 实测删义率 8.4%(7/83)吻合。→ 用 `c56_all_senses.json`(全量扫 kaikki 得到的所有 sense)。
   prompt 里还要明写"**en 未必穷尽全部义项,zh 有 en 没提到的义不算错,绝不能删**"。

📊 pilot v2(500 条,与 v1 同一批可直比;pro 对同 300 条做"改写前/改写后"配对判):
     keep 86.2% / 改写 13.8%(v1 是 16.6%,含 7 条删义)
     改写前 ok 279 warn 5 **bad 16 (5.3%)** → 改写后 ok 285 warn 9 **bad 6 (2.0%)**
   ⭐ **配对判是关键**:拿"改写后 bad%"去比"整桶 9.3%"是两个样本,比不出净增益。

⚠️ 性价比明显低于前面几段:约 2,900 token/个错译(B1/B2 残留那轮是 545),
   因为原文本来就 95% 对,钱主要花在确认"这条没问题"上。做不做是产品决策。

用法:
  python3 en/rewrite_c6_anchored.py --limit 500     # pilot
  python3 en/rewrite_c6_anchored.py --run           # 备份后写库,留痕 c6_anchored_fix.tsv
  python3 en/rewrite_c6_anchored.py --run --bucket C5   # 同法跑 C5(251,081 条,约 23.8M token)
"""
import argparse, asyncio, json, re, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S
import buckets as B
import rewrite_residue_anchored as R

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
GLOSS = HERE / "residue_kaikki_gloss.json"      # 词形 → kaikki 首义
ALLSENSE = HERE / "c56_all_senses.json"         # 词形 → **全部** sense(去元描述)
CHUNK = 20
HEDGE_AFTER = 1200   # ⚠️ 别用 300:batch 队列一堵会每批都切 online pro,单价差一个量级

SYS = """你是英汉词典质检+编纂专家。给你一批英语**词条/短语**,每条含:
  word 词条    zh 现有中文译文    en 该词在 Wiktionary 的英文释义(可能有多条,已编号)
这批译文来自人工审校词典,**大部分是准确的**。你的任务是**核对**,不是重写。
🔴 **en 未必穷尽该词全部义项**。zh 里有 en 没提到的义项,**不算错,绝不能删** ——
   删掉一个真实义项比留着它有害得多。只有当某个义项与该词实际意思**明确不符**时才算错。
- zh 与 en 表达同一意思(措辞、详略、术语风格不同都无所谓)→ {"fix":"keep"};
- 只有 zh **确实错了**才改写:错译 / 张冠李戴 / 漏掉 en 里的主要义 / 中文读不通是机翻残片;
- 改写时**必须保留 zh 里原有的正确义项**,在此基础上订正或补充。
判 keep 从宽:术语直译、专业生僻、人名地名合理音译、多个并列候选译名、缺词性前缀等格式小瑕、
zh 比 en 简略但方向正确 —— 一律 keep。
改写格式:词性用 n./v./vt./vi./adj./adv. 等;可带 [医][化][计][法][军] 标签;多义用换行或分号分隔;
必须给实际词义;不要写 `[网络]` 这个标记。
每条返回 {"fix":"keep"} 或 {"fix":"rewrite","zh":"新译文","why":"原译哪里错"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""


def collect(conn, bucket):
    gl = json.load(open(GLOSS, encoding="utf-8"))
    allg = json.load(open(ALLSENSE, encoding="utf-8")) if ALLSENSE.exists() else {}
    q = dict(conn.execute("SELECT id, COALESCE(qual,'?') FROM stardict"))
    rej = Counter(); out = []
    for rid, w, t, bk in B.load_tail(conn):
        if bk != bucket or q.get(rid) != "fair":
            continue
        ws = w.strip()
        en = (gl.get(ws.lower()) or "").strip()
        if len(en) < 4:
            rej["无 kaikki 锚"] += 1; continue
        if R.ENMETA.match(en):
            rej["锚是元描述(plural of X 之类)"] += 1; continue
        out.append((rid, ws, (t or "").strip(), en, allg.get(ws.lower()) or []))
    return out, rej


def enfield(first, senses):
    """多义时把全部 sense 编号列出 —— 只喂首义会让模型误删合法义项。"""
    ss = [s for s in senses if s and not R.ENMETA.match(s)]
    if len(ss) <= 1:
        return (ss[0] if ss else first)[:200]
    return " | ".join(f"{i}) {s}" for i, s in enumerate(ss[:4], 1))[:340]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--bucket", default="C6", choices=["C5", "C6"])
    ap.add_argument("--tag", default="", help="留痕后缀;重跑另一批时必须换,否则会把上一批退回")
    a = ap.parse_args()
    LOG = HERE / f"{a.bucket.lower()}_anchored_fix{a.tag}.tsv"

    conn = sqlite3.connect(DB)
    rows, rej = collect(conn, a.bucket)
    if a.limit:
        rows = rows[:a.limit]
    print(f"[{a.bucket} 有锚 · lite 核对] {len(rows):,} 条")
    for k, v in rej.most_common():
        print(f"  剔除 {k:26} {v:>9,}")
    multi = sum(1 for r in rows if len([s for s in r[4] if not R.ENMETA.match(s)]) > 1)
    print(f"  其中 kaikki 多义 {multi:,} ({multi/max(1,len(rows))*100:.1f}%) —— 这批只喂首义就会误删义项")
    if not rows:
        return
    # ⚠️ 这类脚本是"先调 API 再决定写不写库",所以**不带 --run 的全量 dry-run 会花满钱再把结果扔掉**。
    #   踩过一次(C6 97,064 条)。→ 不写库时必须配 --limit,否则直接退出。
    if not a.run and not a.limit:
        print("\n(未加 --run:全量跑会照常调 API 花满钱再丢弃结果 → 已拦下。"
              "要试跑请加 --limit N;要正式跑请加 --run)")
        return

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        metas = [rows[j:j + CHUNK] for j in range(0, len(rows), CHUNK)]
        batches = [{str(k): {"word": r[1], "zh": r[2][:150], "en": enfield(r[3], r[4])}
                    for k, r in enumerate(m, 1)} for m in metas]
        print(f"  → {len(batches)} 批")
        res, tk = await S.run_batches(SYS, batches, env["DOUBAO_MODEL_BATCH_LITE"],
                                      cl.batch.chat.completions,
                                      (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, HEDGE_AFTER))
        await cl.close()
        return metas, res, tk

    metas, results, tok = asyncio.run(go())
    tally = Counter(); fixes = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, r in enumerate(meta, 1):
            v = res.get(str(k))
            act = v.get("fix") if isinstance(v, dict) else None
            zh = (v.get("zh") or "").strip() if isinstance(v, dict) else ""
            if act != "rewrite" or not zh:
                tally["keep"] += 1
            elif zh == r[2]:
                tally["拦下·零变动"] += 1
            elif B.is_shell(zh):
                tally["拦下·空壳"] += 1
            elif R.PTRONLY.match(zh.replace("\n", " ")):
                tally["拦下·纯指针"] += 1
            elif "[网络]" in zh:
                tally["拦下·[网络]撞车"] += 1
            elif "\t" in zh:
                tally["拦下·含制表符"] += 1
            else:
                tally["改写"] += 1
                fixes.append((r[0], r[1], r[2], zh))

    print(f"\n===== {len(rows):,} 条 token {tok:,} =====")
    for k, v in tally.most_common():
        print(f"  {k:18} {v:>8,}")
    for rid, w, old, new in fixes[:8]:
        print(f"\n  {w}\n    前: {old.replace(chr(10),' / ')[:56]}\n    后: {new.replace(chr(10),' / ')[:72]}")

    if not a.run or not fixes:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-{a.bucket.lower()}-{tag}.bak"))
    conn = sqlite3.connect(DB)
    if LOG.exists():   # 重跑保护
        for i, ln in enumerate(open(LOG, encoding="utf-8")):
            if i:
                c = ln.rstrip("\n").split("\t")
                conn.execute("UPDATE stardict SET translation=?, qual='fair' WHERE id=?",
                             (c[2].replace("\\t", "\t").replace("\\n", "\n"), int(c[0])))
        conn.commit()
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tbefore\tafter\n")
        for rid, w, old, new in fixes:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            conn.execute("UPDATE stardict SET qual='fixed' WHERE id=? AND qual NOT IN ('core','judged')", (rid,))
            f.write("\t".join([str(rid), w,
                               old.replace("\t", "\\t").replace("\n", "\\n"),
                               new.replace("\t", "\\t").replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已改写 {len(fixes):,} 条(qual 已同步),留痕 → {LOG.name};备份 pre-{a.bucket.lower()}-{tag}.bak")


if __name__ == "__main__":
    main()
