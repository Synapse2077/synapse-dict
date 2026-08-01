#!/usr/bin/env python3
"""派生词空壳(「X的变形」)→ 以词根中文为参考,让模型按构词法推出该词自身词义。见对话 2026-07-28。

来源:`fix_a1d.py` 一度把"X的变形"当异体拼写处理、**直接抄词根译文**,实测 **bad 85.5%**,8,804 条已全部退回。
原因:「变形」在这批数据里指的是**派生词**(insectology→insectologist),
      派生词的词义 **≠** 词根的词义 —— 抄过去必然错。

正确做法(用户提出,实测有效):**别抄,给参考让模型推**。
输入 = 词条 + 词根 + **词根的中文释义**(库里现成、可信),让模型按后缀规则推出该派生词自己的词义。
  pilot 400 条:lite 重写 379 / skip 21 → **pro 全验 ok 96.6% / bad 3.4%**(对照"直接抄"的 85.5%)。
  rebukable   「a. rebuke的变形」  → adj. 可指责的,应受斥责的
  waspiness   「n. waspy的变形」   → n. 似黄蜂的特性;脾气暴躁,尖刻
⭐ 这是"半有锚"任务:虽无英文释义,但词根中文 + 构词法足够 → 仍属翻译/推理题,lite 够用。

pilot 残留 bad 的两类,已在 prompt 里针对性加闸:
  ① 复数词条只写"XX复数"不给实义(vomicae→"脓腔复数") → 明确要求给出实际词义;
  ② 词本身不存在被硬编(dyeder/freakishly ad) → 强调宁可 skip。

用法:
  python3 en/fix_derivational.py --limit 400   # 小跑
  python3 en/fix_derivational.py --run         # 备份后写库,留痕 derivational_fix.tsv
"""
import argparse, asyncio, re, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
REV = paths.WORK / "ledgers/a1d_reverted.tsv"
LOG = paths.WORK / "ledgers/derivational_fix.tsv"
CHUNK = 20

PAT = re.compile(r"([A-Za-z][\w'’\- ]*?)\s*的(变形|变化形式)")

SYS = """你是英汉词典编纂专家。给你一批英语**派生词**,每条含:
  word 该派生词    root 它的词根    root_zh 词根的中文释义(可信)
当前译文只写了"root的变形",没有该词自己的词义。请依据构词法给出**该派生词本身**的准确中文:
- 直接给中文词义,1–3 个;动词 v./vt./vi.,名词 n.,形容词 adj.,副词 adv.;
- 注意词性与词义随后缀改变:-ist/-er/-or=从事者(人)、-ism=主义/现象、-ness/-ment/-tion=抽象名词、
  -ful/-less/-ic/-al/-ous=形容词、-ly=副词、-ize/-ify=动词化、-able=可…的;
  例:insectology(昆虫学)+ -ist → insectologist = 昆虫学家;
- **复数/变形词条也必须给出实际词义,不能只写"XX的复数"**:
  vomicae 要写「n. [医] 脓腔,咳脓痰(vomica 的复数)」,不能只写「脓腔复数」;
- 有学科属性可带 [医][化][计] 等标签;可用 <罕><古> 标记。
**若该拼写不是真实英语词(如多了冗余字母、明显错拼)、或你无法确定其含义,不要编造**,
返回 {"fix":"skip","why":"原因"} —— 编造的释义比留着空壳更有害,它看起来更可信。
每条返回 {"fix":"rewrite","zh":"中文译文"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""


def collect(conn):
    trans = {}
    for w, t in conn.execute("SELECT word, translation FROM stardict"):
        trans.setdefault(w.strip().lower(), (t or "").strip())
    out = []
    rej = Counter()
    for i, ln in enumerate(open(REV, encoding="utf-8")):
        if not i:
            continue
        c = ln.rstrip("\n").split("\t")
        if len(c) < 4 or "的变形" not in c[-1]:
            continue
        rid, w, cur = int(c[0]), c[1], c[2].replace("\\n", "\n")
        m = PAT.search(cur.replace("\n", " "))
        if not m:
            rej["提不出词根"] += 1; continue
        root = m.group(1).strip().lower()
        rt = trans.get(root, "")
        if not rt:
            rej["词根不在库"] += 1; continue
        if "[网络]" in rt:
            rej["词根是[网络]"] += 1; continue
        if not re.search(r"[一-鿿]", rt):
            rej["词根译文无汉字"] += 1; continue
        out.append((rid, w, cur, root, rt))
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
    print(f"[派生词空壳 · lite 按构词法推义] {len(rows)} 条")
    for k, v in rej.most_common():
        print(f"  剔除 {k:16} {v:>6}")

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "root": r[3], "root_zh": r[4][:100]}
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
                tally["skip(保持空壳)"] += 1

    print(f"\n===== {sum(tally.values())} 条 token {tok} =====")
    for k, v in tally.most_common():
        print(f"  {k:18} {v:>6}")
    for rid, w, old, new in fixes[:6]:
        print(f"\n  {w}\n    前: {old.replace(chr(10),' / ')[:34]}\n    后: {new.replace(chr(10),' / ')[:60]}")

    if not a.run or not fixes:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-deriv-{tag}.bak"))
    conn = sqlite3.connect(DB)
    if LOG.exists():   # 重跑保护:先退回上一轮
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
    print(f"\n已修 {len(fixes)} 条(qual 已同步),留痕 → {LOG.name};备份 pre-deriv-{tag}.bak")


if __name__ == "__main__":
    main()
