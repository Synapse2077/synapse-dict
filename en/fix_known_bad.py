#!/usr/bin/env python3
"""清掉全库**确证为 bad** 的残留条目(pro 重写)。见对话 2026-07-28。

来源:历次抽样/全量 judge 留下的 verify_*.jsonl / sweep_a1.jsonl 里 v=bad 的条目,
且**当前库中内容仍与被判时一致**(没被后续流程改掉)的那些 —— 共 686 条。
分布:B2 220 / C3 145 / C6 92 / C1 78 / C5 72 / C4 49 / B1 27 / C2 3。

⚠️ 这 686 **不等于"全库只剩 686 条错译"**。抽样比例极低(C6 仅 0.07%、C4 仅 0.18%),
   按各桶实测 bad 率外推全库实际错译约 37 万(≈9.5%)。686 只是"有名有姓、可定点清除"的部分。

用 pro 而非 lite:这批**没有英文释义可依**(不同于 B1 那几批有 kaikki 锚),
属于**知识题**——要模型自己认得这个生僻词才能给出正确释义。
按今天的经验:翻译题(答案在输入里)用 lite;知识题必须上 pro。

判官已给出 note(错在哪),一并喂给 pro 作为线索。
无法给出正确释义的返回 skip → **保持现状**(不动),因为这批的"原状"本身就是坏的,
撤回无处可撤(它们不是回填产物,是原始数据)。

用法:
  python3 en/fix_known_bad.py            # dry-run
  python3 en/fix_known_bad.py --run      # 备份后写库,留痕 known_bad_fix.tsv
"""
import argparse, asyncio, json, os, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
LOG = HERE / "ledgers/known_bad_fix.tsv"
CHUNK = 10

SOURCES = [
    ("runs/sweep_a1.jsonl", "zh"), ("runs/verify_a1a.jsonl", "zh"), ("runs/verify_a1a_round2.jsonl", "zh"),
    ("runs/verify_a1a_round3.jsonl", "zh"), ("runs/verify_a1d.jsonl", "zh"),
    ("runs/verify_b1_kaikki.jsonl", "after"), ("runs/verify_b1_rewrite.jsonl", "after"),
    ("runs/verify_bucket_C1.jsonl", "zh"), ("runs/verify_bucket_C2.jsonl", "zh"),
    ("runs/verify_bucket_C3.jsonl", "zh"), ("runs/verify_bucket_C4.jsonl", "zh"),
    ("runs/verify_bucket_C5.jsonl", "zh"), ("runs/verify_bucket_C6.jsonl", "zh"),
    ("runs/verify_bucket_B2.jsonl", "zh"),
]

SYS = """你是英汉词典编纂专家。给你一批**已被质检判定为错误**的英语词条,每条含:
  word 英语词或词组
  zh   当前中文译文(**是错的**)
  note 质检员指出的具体问题(重要线索,通常已说明正确方向)
请依据你自身的英语知识给出**正确**的中文译文:
- 直接给中文词义,1–3 个,简洁自然;
- 动词用 v./vt./vi.,名词 n.,形容词 adj.,副词 adv.;缩写用 abbr. 并给出英文全称;
- 可用 <罕><古><俚><非正式><方> 标记;有学科属性可带 [医][化][计][法][植][动][经] 等标签;
- 专有名词(人名/地名/机构/作品名)给通行译名并注明类别。

**若你无法确定该词的正确含义,不要编造**,返回 {"fix":"skip","why":"原因"}:
- 该拼写不是一个真实英语词;
- 你对该词没有可靠知识,给不出确定释义;
- note 指出的问题你无法核实。
宁可 skip 也不要硬编 —— 编造的释义比保留原错误更有害(它看起来更可信)。

每条返回 {"fix":"rewrite","zh":"正确译文(可含换行\\n)"} 或 {"fix":"skip","why":"…"}。
严格输出 JSON {"1":{...},...},键与输入一致,无多余文字。"""


def collect(conn):
    seen = set(); out = []
    for f, zk in SOURCES:
        p = HERE / f
        if not p.exists():
            continue
        for ln in open(p, encoding="utf-8"):
            d = json.loads(ln)
            if d.get("v") != "bad":
                continue
            w = d.get("w")
            zh = d.get(zk) or d.get("zh") or ""
            if not w or w in seen:
                continue
            r = conn.execute(
                "SELECT id, translation FROM stardict WHERE word=? COLLATE NOCASE LIMIT 1", (w,)
            ).fetchone()
            if not r or (r[1] or "") != zh:      # 库中已被后续流程改掉 → 跳过
                continue
            seen.add(w)
            out.append((r[0], w, zh, d.get("note", ""), f))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    rows = collect(conn)
    print(f"[确证 bad 残留 · pro 重写] {len(rows)} 条")
    print("  来源分布: " + "  ".join(f"{k.replace('verify_bucket_','').replace('.jsonl','')}:{v}"
                                  for k, v in Counter(r[4] for r in rows).most_common()))

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=A.TIMEOUT)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "zh": r[2], "note": r[3][:120]}
                            for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await A.run_batches(SYS, batches, env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions)
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
        print(f"  {k:18} {v:>5}")
    for rid, w, old, new in fixes[:10]:
        print(f"\n  {w}\n    错: {old.replace(chr(10),' / ')[:44]}\n    正: {new.replace(chr(10),' / ')[:64]}")

    if not a.run or not fixes:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(DB, DB.with_name(f"synapse-dict-en.pre-knownbad-{tag}.bak"))
    conn = sqlite3.connect(DB)
    if LOG.exists():
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
            f.write("\t".join([str(rid), w,
                               old.replace("\t", " ").replace("\n", "\\n"),
                               new.replace("\t", " ").replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"\n已修 {len(fixes)} 条,留痕 → {LOG.name};备份 pre-knownbad-{tag}.bak")


if __name__ == "__main__":
    main()
