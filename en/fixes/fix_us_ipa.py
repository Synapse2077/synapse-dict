#!/usr/bin/env python3
"""美式音标列里混着英式音标 —— 重生成。见对话 2026-07-30。

问题:phonetic_us 与 phonetic_uk **逐字节相同**且带英式独有标记(ɒ / əʊ / 可选 r / ɜːɑːɔː)。
  'sfar   UK sfɑː(ɹ)  US sfɑː(ɹ)   ← 美式是儿化音,"可选 r"这个记法根本不成立
  4x4     UK ˌfɔː(ɹ)baɪˈfɔː(ɹ)  US 同上
2026-07-27 那轮修过同族(`us=uk 含 ɒ` 638 条),**只用了 ɒ 一个信号**,漏了其余几个。

⭐ 打法:**拿现成英式音标当锚**,让模型做 RP→GA 转换,不从零生成。
   这批的英式列本身是对的(来自 Wiktionary),所以这是"翻译题"不是"知识题" ——
   按 [[doubao-seed21-adjudicator]] 的分工,翻译题用便宜模型即可,不必上 pro。

⚠️ DB 存**裸音标**(无外层斜杠),展示层 App.tsx 自己加 /.../。模型输出的斜杠必须剥掉。

五道本地闸(纯确定性):
  ① 剥完斜杠后非空、含 IPA 字符、无汉字/无拉丁字母残渣
  ② **不得含 ɒ / əʊ / (r) / (ɹ)** —— 这几个正是要消除的英式标记,还在就是没转
  ③ 必须与英式不同(相同 = 模型原样抄回)
  ④ 长度在英式的 0.5–2 倍之间(挡截断和暴走)
  ⑤ 库内现值仍等于选中时的值
  ⑥ **英式有几个 r,美式不能更少** —— 美式是儿化音,只可能比英式多 r。
     实测 pilot 逮到 Tonyrefail ˌtɒnəɹˈɛvəl → ˌtɑnəˈɛvəl,模型把词中的真 ɹ 一起丢了。

用法:
  python3 en/fix_us_ipa.py --pilot 300     # 抽样,不写库
  python3 en/fix_us_ipa.py --run           # 全量写库,备份 + 留痕
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, asyncio, json, re, shutil, sqlite3, random, time
from collections import Counter
from datetime import datetime
from pathlib import Path

import acceptance_en as A
import sweep_core as S
from judge_sample import ds_call

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
LOG = paths.WORK / "ledgers/us_ipa_fix.tsv"
CHUNK = 25

# 美式列里出现即为"没美式化"的英式独有标记
BRIT = ["ɒ", "əʊ", "(r)", "(ɹ)"]
TARGET = ("COALESCE(phonetic_us,'')<>'' AND phonetic_us = phonetic_uk AND ("
          "phonetic_us LIKE '%ɒ%' OR phonetic_us LIKE '%əʊ%' "
          "OR phonetic_us LIKE '%(ɹ)%' OR phonetic_us LIKE '%(r)%' "
          "OR phonetic_us LIKE '%ɑː%' OR phonetic_us LIKE '%ɔː%' OR phonetic_us LIKE '%ɜː%')")

IPA_CHARS = re.compile(r"^[\sˈˌːa-zæɑɒɔəɜɛɪʊʌθðʃʒŋɡɹɾʔçjwʍ()ˑ.̀-ͯ‿ɐɨɫɚɝ⁽⁾ʲ|-]+$", re.I)
HAN = re.compile(r"[一-鿿]")

SYS = """你是英语语音学专家。给你一批英语词条,每条含:
  w   单词或短语
  uk  该词的**英式(RP)音标**,来自 Wiktionary,可信

请给出对应的**美式(GA / General American)音标**。

要点:
- 这是**口音转换**,不是重新标音 —— 音节数、重音位置应与英式一致,只改英美有差异的音;
- 常见对应:ɒ→ɑ(lot) | əʊ→oʊ(goat) | ɑː→ɑ 或保留 | 词末/辅音前的 r **必须读出**(英式 ə→美式 ər);
- 英式的"可选 r"记法 (r)/(ɹ) 在美式里不存在,**一律写成实读的 r**;
- ɜː(nurse) 美式作 ɜr;ə 后接 r 时美式作 ər;
- t/d 在元音间的闪音**不要**写成 ɾ,按 t 写;
- **不要加外层斜杠**,直接给裸音标;
- 若该词英美读音本就相同,原样返回英式音标即可(但要把可选 r 括号展开成实读 r)。

严格输出 JSON,键与输入一致:{"1":"ˈæbdʌktər","2":"ˌfɔrbaɪˈfɔr"}
不要任何解释文字。"""


def clean(s):
    """剥外层斜杠/方括号/空白。DB 存裸音标。"""
    s = (s or "").strip().strip("/[]").strip()
    return re.sub(r"\s+", " ", s)


def gate(new, uk):
    if not new:
        return "空"
    if HAN.search(new):
        return "含汉字"
    if not IPA_CHARS.match(new):
        return "含非 IPA 字符"
    for b in BRIT:
        if b in new:
            return f"仍含英式标记 {b}"
    if new == uk:
        return "与英式相同(原样抄回)"
    n, m = len(new), len(uk)
    if not (0.5 * m <= n <= 2 * m):
        return "长度异常"
    # 闸⑥:美式儿化,r 只能多不能少。英式的可选 r 括号也计入(它在美式里必读)
    if _rcount(new) < _rcount(uk):
        return "美式 r 比英式少"
    return None


def _rcount(s):
    return (s or "").count("r") + (s or "").count("ɹ")


def pick(pilot, seed):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        f"SELECT id, word, phonetic_uk, phonetic_us, COALESCE(qual,'') "
        f"FROM stardict WHERE {TARGET}").fetchall()
    conn.close()
    if pilot:
        random.seed(seed)
        rows = random.sample(rows, min(pilot, len(rows)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--provider", choices=["turbo", "ds"], default="ds",
                    help="turbo=豆包 turbo batch(半价但排队慢);ds=DeepSeek v4-pro(快一个数量级)")
    ap.add_argument("--conc", type=int, default=40)
    a = ap.parse_args()

    rows = pick(a.pilot, a.seed)
    print(f"目标 {len(rows):,} 条"
          f"{'(pilot 抽样)' if a.pilot else ''}", flush=True)
    q = Counter(r[4] for r in rows)
    print("  按 qual:", ", ".join(f"{k}={v:,}" for k, v in q.most_common()), flush=True)

    env = A.load_env()
    metas, batches = [], []
    for j in range(0, len(rows), CHUNK):
        sub = rows[j:j + CHUNK]
        batches.append({str(k): {"w": r[1], "uk": r[2]} for k, r in enumerate(sub, 1)})
        metas.append(sub)

    async def go_turbo():
        from volcenginesdkarkruntime import AsyncArk
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        print(f"  → {len(batches)} 批 × {CHUNK},豆包 turbo batch", flush=True)
        # hedge 1200s:低了会每批切 online pro,单价差一个数量级(见 verify_bucket.py 注释)
        hedge = (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 1200)
        res, tok = await S.run_batches(SYS, batches, env["DOUBAO_SEED_2_1_TURBO_BATCH"],
                                       cl.batch.chat.completions, hedge)
        await cl.close()
        return metas, res, tok

    async def go_ds():
        import httpx
        cl = httpx.AsyncClient(timeout=httpx.Timeout(900.0))
        print(f"  → {len(batches)} 批 × {CHUNK},DeepSeek v4-pro 并发 {a.conc}", flush=True)
        sem = asyncio.Semaphore(a.conc)
        out = [None] * len(batches); tk = [0]; done = [0]
        try:
            await ds_call(cl, env["DEEPSEEK_API_KEY"], "deepseek-v4-pro", SYS, batches[0])
        except Exception:
            pass

        async def one(i, p):
            async with sem:
                d = 3
                for att in range(4):
                    try:
                        txt, (pi, co, _) = await ds_call(cl, env["DEEPSEEK_API_KEY"],
                                                         "deepseek-v4-pro", SYS, p)
                        tk[0] += pi + co
                        out[i] = A.loads_lenient(txt.strip())
                        break
                    except Exception:
                        if att == 3:
                            print(f"    ✗ 批{i}", flush=True)
                        else:
                            await asyncio.sleep(d); d = min(d * 2, 30)
                done[0] += 1
                if done[0] % 50 == 0 or done[0] == len(batches):
                    print(f"    [{done[0]}/{len(batches)}]", flush=True)

        await asyncio.gather(*[one(i, p) for i, p in enumerate(batches)])
        await cl.aclose()
        return metas, out, tk[0]

    async def go():
        return await (go_ds() if a.provider == "ds" else go_turbo())

    t0 = time.time()
    metas, results, tok = asyncio.run(go())

    tal = Counter(); fixes = []
    for meta, r in zip(metas, results):
        r = r or {}
        for k, (rid, w, uk, us, ql) in enumerate(meta, 1):
            v = r.get(str(k))
            new = clean(v if isinstance(v, str) else (v or {}).get("us", ""))
            bad = gate(new, uk)
            if bad:
                tal[f"✗ {bad}"] += 1
            else:
                tal["✓ 可写入"] += 1
                fixes.append((rid, w, uk, us, new, ql))

    print(f"\n===== {len(rows)} 条  {time.time()-t0:.0f}s  token {tok:,} =====")
    for k, v in tal.most_common():
        print(f"  {k:24} {v:>6,}")
    print("\n  样例:")
    for rid, w, uk, us, new, ql in fixes[:12]:
        print(f"    {w[:22]:24} 英 {uk[:22]:24} 美(旧) {us[:20]:22} 美(新) {new[:22]}")

    if a.pilot:      # pilot 结果落盘,便于逐条核而不必重跑(重跑要再花钱)
        outp = HERE / f"runs/us_ipa_pilot_{a.provider}_{len(rows)}_{time.strftime('%Y%m%d-%H%M')}.jsonl"
        with open(outp, "w", encoding="utf-8") as f:
            for rid, w, uk, us, new, ql in fixes:
                f.write(json.dumps(dict(id=rid, w=w, uk=uk, before=us, after=new,
                                        qual=ql), ensure_ascii=False) + "\n")
        print(f"\n  明细 → {outp.name}")

    if not a.run:
        print(f"\n[未写库] 可写入 {len(fixes):,} 条。加 --run 真写。")
        return

    tag = datetime.now().strftime("%Y%m%d-%H%M")
    bak = HERE / "backups" / f"synapse-dict-en.pre-usipa-{tag}.bak"
    shutil.copy2(DB, bak)
    conn = sqlite3.connect(DB)
    cur = dict(conn.execute("SELECT id, COALESCE(phonetic_us,'') FROM stardict"))
    wrote = 0
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("id\tword\tuk\tbefore\tafter\tqual\n")
        for rid, w, uk, us, new, ql in fixes:
            if cur.get(rid) != us:          # 闸⑤ 库内现值已变,跳过
                continue
            conn.execute("UPDATE stardict SET phonetic_us=? WHERE id=?", (new, rid))
            f.write(f"{rid}\t{w}\t{uk}\t{us}\t{new}\t{ql}\n")
            wrote += 1
    conn.commit(); conn.close()
    print(f"\n已写入 {wrote:,} 条 phonetic_us,留痕 → {LOG.name}")
    print(f"备份 → {bak.name}")


if __name__ == "__main__":
    main()
