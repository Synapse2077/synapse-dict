#!/usr/bin/env python3
"""全库整体抽样验收(read-only,绝不写库)。见对话 2026-07-29。

与 verify_bucket.py 的区别:后者**按桶**抽,各测各的;本脚本**对全库 3,929,564 条
均匀随机抽**,给一个有分母的总体数字。用途:回答"这轮改造后全库到底什么水平"。

⚠️ 服务面是全部 392 万(含核心 5.9 万 + 尾巴 387 万)。短语同样在服务面内 ——
   dict-core getEntry() 是 `WHERE word = ? COLLATE NOCASE`,划选原文精确匹配,
   'clear title' 这类多词短语照样命中。所以均匀抽样对全库,不做任何桶/词形过滤。

⭐ 随机性:对全部 id 做 random.sample(无放回均匀抽样)。seed 默认取系统熵并**打印+落盘**,
   保证事后可复跑核对;传 --seed N 可重放某次抽样。

模型:**pro online**(judge 是知识题,不是翻译题)。hedge=None → run_batches 走 acall(batch=False)。

用法:
  python3 en/verify_global.py --n 2000
  python3 en/verify_global.py --n 2000 --seed 12345    # 重放
"""
import argparse, asyncio, json, random, sqlite3, secrets
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S
import buckets as B

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
CHUNK = 20

# ⭐ 词频分层。frq/bnc 是**排名**(the=1,最大 47062),不是计数 —— 直接拿来当权重是错的。
#    且全库只有 1.5% 有词频信号,朴素 Zipf 加权会几乎只抽到 core(实测 bad 0%),得出的
#    "命中面 bad≈0" 是自欺欺人;方向还反了:用户划词不划 the/and,划的是不认识的词。
#    → 没有使用日志就别编查询分布。分层各测各的,谁要加权谁自己套系数。
#    七层互斥且穷尽,合计 == 3,929,564(脚本会自检)。
STRATA = [
    ("S1 超高频 frq≤2000", "COALESCE(frq,0) BETWEEN 1 AND 2000"),
    ("S2 frq 2001-10000", "COALESCE(frq,0) BETWEEN 2001 AND 10000"),
    ("S3 frq 10001+", "COALESCE(frq,0) > 10000"),
    ("S4 无frq有bnc", "COALESCE(frq,0)=0 AND COALESCE(bnc,0)>0"),
    ("S5 无词频有词典标记", "COALESCE(frq,0)=0 AND COALESCE(bnc,0)=0 "
                            "AND (COALESCE(collins,0)>0 OR COALESCE(oxford,0)>0)"),
    ("S6 无信号·单词形", "COALESCE(frq,0)=0 AND COALESCE(bnc,0)=0 AND COALESCE(collins,0)=0 "
                          "AND COALESCE(oxford,0)=0 AND word NOT LIKE '% %'"),
    ("S7 无信号·多词短语", "COALESCE(frq,0)=0 AND COALESCE(bnc,0)=0 AND COALESCE(collins,0)=0 "
                            "AND COALESCE(oxford,0)=0 AND word LIKE '% %'"),
]

# 与 verify_bucket.py 逐字一致 —— 换了判据就没法和历轮分桶数字对比
JUDGE_SYS = """你是英汉词典质检专家。给你一批英语词条,每条含 word(英语词或短语)、zh(中文译文)。
凭你自身英语知识,判断 zh 对该 word 是否**准确、可用**。只把下列情况判 bad:
- **错译**:中文与该词/短语实际意思不符;
- **张冠李戴**:译成了无关的人、物或概念;
- **无意义垃圾**:中文读不通、是机翻残片、乱码或明显残缺;
- **漏掉最主要义**:只给了次要/生僻义,把最常用义漏了。

**以下一律判 ok(务必从宽)**:
- 词条生僻、专业、古旧、方言 —— 只要译得对就是 ok;
- 是专业术语的直译(如"轴向后角""分光敏度测量")—— ok;
- 是人名/地名/学名的**合理音译或通行译名** —— ok;
- 带 [医][化][计][法] 学科标签、给了多个并列候选译名(用;分隔) —— ok;
- 缺词性前缀等格式小瑕 —— ok。

warn 只留给"意思大体对但明显不准确/有小错"的中间地带。拿不准就判 ok。
严格输出 JSON {"1":{"v":"ok"},"2":{"v":"bad","note":"简短问题"},...},键与输入一致,无多余文字。"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=None, help="不传则取系统熵,结果会打印并落盘")
    ap.add_argument("--strata", action="store_true",
                    help="按词频分层抽样(每层 --per 条),而非全库均匀抽")
    ap.add_argument("--per", type=int, default=300, help="--strata 模式下每层抽多少")
    ap.add_argument("--ids", help="JSON 文件(id 列表):只在这批里抽 --n 条")
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else secrets.randbelow(2**31)

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    random.seed(seed)
    sizes = {}

    if a.ids:
        pool = json.load(open(a.ids, encoding="utf-8"))
        print(f"[id 白名单] {a.ids} 共 {len(pool):,} 条,随机抽 {a.n:,}  seed={seed}", flush=True)
        pick = {i: Path(a.ids).stem for i in random.sample(pool, min(a.n, len(pool)))}
    elif a.strata:
        pick, chk = {}, 0
        for name, pred in STRATA:
            sids = [r[0] for r in conn.execute(f"SELECT id FROM stardict WHERE {pred}")]
            sizes[name] = len(sids); chk += len(sids)
            for i in random.sample(sids, min(a.per, len(sids))):
                pick[i] = name
        tot_db, = conn.execute("SELECT COUNT(*) FROM stardict").fetchone()
        print(f"全库 {tot_db:,};分层自检 {chk:,} "
              f"{'✅互斥且穷尽' if chk == tot_db else '⚠️分层有重叠或遗漏'}", flush=True)
        for name, _ in STRATA:
            print(f"    {name:<22}{sizes[name]:>11,}  抽 {min(a.per, sizes[name])}", flush=True)
        print(f"  共抽 {len(pick):,} 条  seed={seed}", flush=True)
    else:
        ids = [r[0] for r in conn.execute("SELECT id FROM stardict")]
        print(f"全库 {len(ids):,} 条;均匀随机抽 {a.n:,} 条  seed={seed}", flush=True)
        pick = {i: "ALL" for i in random.sample(ids, min(a.n, len(ids)))}

    rows = [(i, w, t, B.classify(w, t), q or "", pick[i])
            for i, w, t, q in conn.execute(
                "SELECT id, word, translation, qual FROM stardict") if i in pick]
    conn.close()
    random.shuffle(rows)   # 打散,避免同层/同桶连片影响判官

    pre = Counter(r[3] for r in rows)
    print("  抽中构成:" + "  ".join(f"{k}:{v}" for k, v in sorted(pre.items())), flush=True)

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "zh": r[2]} for k, r in enumerate(sub, 1)})
            metas.append(sub)
        print(f"  → {len(batches)} 批,pro online", flush=True)
        # hedge=None → run_batches 内部走 acall(batch=False) = online pro
        res, tok = await S.run_batches(JUDGE_SYS, batches, env["DOUBAO_SEED_2_1_PRO"],
                                       cl.chat.completions, None)
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())

    tally = Counter(); by_bk = Counter(); by_q = Counter(); by_st = Counter(); bad = []
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    mode = "strata" if a.strata else "uniform"
    outp = HERE / f"runs/verify_global_{mode}_{len(rows)}_{tag}.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(_meta=True, seed=seed, n=len(rows), mode=mode,
                                strata_sizes=sizes, model="pro-online"),
                           ensure_ascii=False) + "\n")
        for meta, res in zip(metas, results):
            res = res or {}
            for k, (rid, w, t, bk, q, st) in enumerate(meta, 1):
                v = res.get(str(k))
                verdict = v.get("v") if isinstance(v, dict) else None
                if verdict not in ("ok", "warn", "bad"):
                    verdict = "novote"
                note = v.get("note", "") if isinstance(v, dict) else ""
                tally[verdict] += 1
                by_bk[(bk, verdict)] += 1
                by_q[(q, verdict)] += 1
                by_st[(st, verdict)] += 1
                if verdict == "bad":
                    bad.append((w, t, bk, q, note))
                f.write(json.dumps(dict(id=rid, w=w, zh=t, bucket=bk, qual=q, stratum=st,
                                        v=verdict, note=note), ensure_ascii=False) + "\n")

    tot = sum(tally.values()); scored = tot - tally["novote"]
    print(f"\n===== 全库整体 {tot} 条(有效 {scored}) token {tok:,} seed={seed} =====")
    for lab in ("ok", "warn", "bad"):
        print(f"  {lab:5} {tally[lab]:>5} ({100*tally[lab]/max(scored,1):5.1f}%)")
    print(f"  novote {tally['novote']}")
    print(f"  可用率(ok+warn) {100*(tally['ok']+tally['warn'])/max(scored,1):.1f}%")

    # 二项分布 95% 置信区间(正态近似),提醒别把点估计当精确值
    p = tally["bad"] / max(scored, 1)
    se = (p * (1 - p) / max(scored, 1)) ** 0.5
    print(f"  bad 率 95% CI ≈ {100*(p-1.96*se):.1f}% – {100*(p+1.96*se):.1f}%")

    def block(title, cnt, keys, w=6, ci=False):
        print(f"\n  —— 按{title}拆 ——")
        print(f"    {'':<{w}}{'n':>6}{'ok':>6}{'warn':>6}{'bad':>6}{'bad%':>8}"
              + ("      95% CI" if ci else ""))
        for k in keys:
            n = sum(cnt[(k, v)] for v in ("ok", "warn", "bad", "novote"))
            s = n - cnt[(k, "novote")]
            if not n:
                continue
            pb = cnt[(k, "bad")] / max(s, 1)
            se = (pb * (1 - pb) / max(s, 1)) ** 0.5
            tail = f"   {100*max(0,pb-1.96*se):5.1f}–{100*(pb+1.96*se):.1f}%" if ci else ""
            print(f"    {k:<{w}}{n:>6}{cnt[(k,'ok')]:>6}{cnt[(k,'warn')]:>6}"
                  f"{cnt[(k,'bad')]:>6}{100*pb:>7.1f}%{tail}")

    if a.strata:
        block("词频分层", by_st, [s for s, _ in STRATA], w=22, ci=True)
        # 各层 bad 率 × 该层库存占比 = 全库加权还原(校验分层结果与均匀抽样是否自洽)
        tot_db = sum(sizes.values())
        est = sum((by_st[(s, "bad")] / max(sum(by_st[(s, v)] for v in ("ok", "warn", "bad")), 1))
                  * sizes[s] for s, _ in STRATA) / max(tot_db, 1)
        print(f"\n    按库存占比加权还原全库 bad ≈ {100*est:.1f}%"
              f"   (均匀抽样实测 9.4%,两者应接近)")
    block("桶", by_bk, list(B.LABELS))
    block("qual", by_q, ["core", "judged", "fixed", "good", "fair", "low"])

    print("\n  bad 样本(前 25):")
    for w, t, bk, q, note in bad[:25]:
        print(f"    [{bk}/{q:<6}] {w[:24]:26} {(t or '').replace(chr(10),' / ')[:30]} || {note[:36]}")
    print(f"\n  明细 → {outp.name}(首行含 seed,可 --seed {seed} 重放)")


if __name__ == "__main__":
    main()
