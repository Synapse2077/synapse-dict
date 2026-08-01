#!/usr/bin/env python3
"""廉价判官对比:同一批样本,不同供应商/模型各判一遍。见对话 2026-07-30。

目的:两阶段流水线(廉价模型标记 → 贵模型只修被标记的)能把全库成本从 ~700 元压到 ~200 元,
但前提是廉价判官**不漏判**。漏判致命(错译永远进不了修复),误报无害(第二阶段会放回)。

⭐ B 档判据:除 word/zh 外,再喂 `exchange` 解出的**变形关系**(原形+变形类型)。
   这是库内确定性数据,比模型记忆可靠;实测变形词那批 bad 的主要病因就是变形关系标错
   (chosens 说是 choose 的过去分词,exchange 说是 chosen 的复数)。exchange 字符极短,
   输入只涨约 8 token/条(+14%),是性价比最高的一档。definition 覆盖率仅 0.3%,不值得加。

⚠️ DeepSeek 三个坑(按官方文档):
   ① **思考模式默认 enabled** → 必须显式 {"thinking":{"type":"disabled"}},否则白付推理 token;
   ② 非流式请求在等待期**持续返回空行**保活 → 解析前要容忍前导空白;
   ③ JSON Output 要求 prompt 里含 "json" 字样 —— JUDGE_SYS 里有 "JSON",满足。
   走原生 REST(httpx),不为它装 openai SDK。

样本空间:qual NOT IN ('core','fixed') —— core 已是成品(实测 bad 0%),fixed 是本项目改过的。

用法:
  python3 en/judge_sample.py --provider deepseek --model deepseek-v4-flash --n 60   # 连通性/批量验证
  python3 en/judge_sample.py --provider ark --model mini --n 3000 --seed 20260730
  python3 en/judge_sample.py --provider deepseek --model deepseek-v4-flash --n 3000 --seed 20260730
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, asyncio, json, random, sqlite3, time
from collections import Counter
from pathlib import Path

import acceptance_en as A
import buckets as B
from verify_bucket import JUDGE_SYS

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
CHUNK = 20
SPACE = "COALESCE(qual,'') NOT IN ('core','fixed')"
ARK_MODELS = {"mini": "DOUBAO_MODEL_ONLINE_MINI", "lite": "DOUBAO_MODEL_ONLINE_LITE",
              "pro": "DOUBAO_SEED_2_1_PRO", "turbo": "DOUBAO_SEED_2_1_TURBO_BATCH"}

# exchange 类型码 → 中文。ECDICT 约定:0=原形, 1=本词相对原形的类型
CODE = {"p": "过去式", "d": "过去分词", "i": "现在分词", "3": "第三人称单数",
        "r": "比较级", "t": "最高级", "s": "复数"}

# B 档:在原判据后追加 infl 字段的用法。前半段逐字不动 —— 换了判据就没法和历轮数字比。
JUDGE_SYS_B = JUDGE_SYS.replace(
    "严格输出 JSON",
    """另外,部分词条会给出 infl 字段:它是**词典数据里登记的变形关系**(原形 + 变形类型),
属于库内确定性数据,比你的记忆可靠。用法:
- 若 zh 声明的变形关系与 infl 冲突(infl 说是 A 的复数、zh 却说是 B 的过去分词),判 **bad**;
- 若 zh 把变形类型说错(infl 说第三人称单数、zh 说名词复数),判 **bad**;
- infl 只是词形关系,**不代表词义**;zh 的词义对不对仍按上面的标准判。

严格输出 JSON""")


# ⭐ 分类码判据(2026-07-30 重制)。为什么换掉旧 JUDGE_SYS:
#   ① 旧判据命令"务必从宽、拿不准就判 ok",实测会**放过空壳** —— pro 把 "(gintis 的复数)"
#      "= geomagnetic noise" 全判 ok,而这正是本项目一直在修的缺陷族。标尺比被测物宽,测不出东西。
#   ② 旧输出要模型写中文 note,实测 mini 的 168/203 元花在输出上。分类码 1-2 token。
#   ③ 分类能路由:空壳走现成回填流水线、学科标签错近乎零成本、词头坏该下架不该重译 ——
#      不分类就得一视同仁送 pro,为便宜的活付贵价钱。
CODES = "TDPWGH"   # E 已交给 buckets.is_shell() 确定性判定,不再问模型
JUDGE_SYS_CODED = """你是英汉词典质检专家。给你一批英语词条,每条含:
  word  英语词或短语
  zh    词典现有中文译文  ← **只判这个**
  infl  (有则给)该词形在词典数据里登记的变形关系(原形+类型)。库内确定性数据,比你的记忆可靠。
  en    (有则给)该词的英文释义,来自权威词典,可信。

⚠️ **不要判"只说变形关系不给词义"这类空壳** —— 那类由本地正则确定性识别,不在你的职责内。
   看到 zh 里有"是谁的复数/变形/异写形式"之类的说明,**一律当正常写法忽略**,只看词义对不对。

**分两步做,顺序不能颠倒**:
  第一步(这一步决定去留):作为词典条目,这条 zh **能不能用**?
     能用 —— 就**不要把它列进输出**,到此为止,不要去想它属于哪个分类。
  第二步(只对第一步判了"不能用"的):再给一个字母码说明错在哪。
     **归不进下面任何具体类别,就标 W。**

⚠️ 分类只是给已经判定不能用的条目贴标签,**绝不能反过来**——
   不要因为"某条看起来像 T/D/P"就去判它不能用。第一步没判死的,分类就不该出现。

字母码含义:

T 残缺:**必须能具体指出缺了哪个字、或哪个括号不配对**,否则不要打 T。
  例:"佳最终给水温度"(漏首字"最")、"全评价"(漏首字"安")、"池)底坡度"(多一个右括号)。
  ⚠️ 译文完整、只是简短或用词朴素的,不是 T。
D 学科标签错:[医][化][计][机][法][生][地] 等标签挂错领域。例:物理现象标成[医]、复活节算法标成[计]。
  ⚠️ 标签合理或该词确实跨领域的,不是 D。
P 词性或变形关系错:与 infl 冲突(infl 说是 A 的复数、zh 却说是 B 的过去分词),
  或词性标错(现在分词标成形容词、动词三单标成名词复数、比较级只给了原级义)。
W 错译:意思不对、张冠李戴、漏掉最主要义。例:upper center 译成"上止点"(那是 top dead center)。
G 乱码或读不通:机翻残片、字符堆、半个词。也包括 zh 里**压根没有汉字**(只有英文或"= 另一个词")。
  例:"[网络] 。e"、"仓ack"、"[网络] 磨磨挤"、"层的类囊膜"、"= geomagnetic noise"。
H 词头本身坏:**word**(不是 zh)拼写错误、含乱码符号、或是原词典机械加 s 造出的伪变形
  (拉丁学名/人名/地名硬加 s)。例:"aa. ilic?"、"INNERVAITON"、"chamaea fasciatas"。
  ⚠️ 正规的拉丁双名(如 "clanculus gemmulifer")**不是** H。这类建议下架,不建议重译。

**以下一律视为无缺陷,不要列出**:
- 词条生僻、专业、古旧、方言 —— 只要译得对;
- 专业术语的直译(如"轴向后角""分光敏度测量");
- 人名/地名/学名的合理音译或通行译名;
- 带学科标签且标签正确、或给了多个并列候选译名(用;分隔);
- 缺词性前缀这类纯格式小瑕。

宁可漏报,不要为了填满分类而硬报 —— 拿不准就不列出该条。
实测最容易犯的错(务必避免):
  "通道选择信号"(channel-select signal)、"n. 平条, 扁条, [印] (排版用)木嵌条"(reglet)
    —— 译文完整正确,**不是 T**,不要列出;
  "[化] 缔合分子"、"[计] 临界段" —— 标签本来就对,**不是 D**,不要列出;
  "n. 燕尾旗, 丧旗"(bannerol) —— 名词标 n. 没问题,**不是 P**,不要列出。

严格输出 JSON,只含有缺陷的条目,键与输入一致,值为字母码字符串:
{"3":"W","7":"ET","15":"H"}
全部无缺陷则输出 {}。不要任何解释文字、不要 note。"""


def infl(exchange):
    """从 exchange 解出 '<原形> 的<类型>';解不出返回 None。"""
    d = {}
    for p in (exchange or "").split("/"):
        if ":" in p:
            k, v = p.split(":", 1)
            d[k] = v
    lem, typ = d.get("0", "").strip(), d.get("1", "").strip()
    if not lem or not typ:
        return None
    names = [CODE[ch] for ch in typ if ch in CODE]
    return f"{lem} 的{'/'.join(names)}" if names else None


# ---------- 供应商 ----------
# ⚠️ temperature=0(不是 0.2):2026-07-30 实测同一 prompt 连跑三次,dev 召回率极差 22.2pp,
#   和"改了 prompt 之后掉 22pp"同一量级 —— 采样噪声大到能把改动效果完全淹掉。
#   判官是分类任务不需要多样性,一律走贪心解码。
async def ark_call(cl, model, sysp, payload):
    r = await cl.chat.completions.create(
        model=model, temperature=0, reasoning_effort="minimal",
        messages=[{"role": "system", "content": sysp},
                  {"role": "user", "content": "输入:\n" + json.dumps(payload, ensure_ascii=False)}])
    u = r.usage
    det = getattr(u, "prompt_tokens_details", None)
    hit = (getattr(det, "cached_tokens", 0) or 0) if det else 0
    return r.choices[0].message.content, (getattr(u, "prompt_tokens", 0),
                                          getattr(u, "completion_tokens", 0), hit)


async def ds_call(cl, key, model, sysp, payload, think=False):
    r = await cl.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model,
              "messages": [{"role": "system", "content": sysp},
                           {"role": "user",
                            "content": "输入:\n" + json.dumps(payload, ensure_ascii=False)}],
              "temperature": 0,
              "response_format": {"type": "json_object"},
              "thinking": {"type": "enabled" if think else "disabled"},  # 坑① 默认是开的
              **({"reasoning_effort": "high"} if think else {}),
              "stream": False})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    d = json.loads(r.text.lstrip())               # 坑② 前导空行保活
    u = d.get("usage") or {}
    return d["choices"][0]["message"]["content"], (u.get("prompt_tokens", 0),
                                                   u.get("completion_tokens", 0),
                                                   u.get("prompt_cache_hit_tokens", 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["ark", "deepseek"])
    ap.add_argument("--model", required=True, help="ark: mini/lite/pro/turbo;deepseek: 模型名")
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=20260730, help="固定以便两模型判同一批")
    ap.add_argument("--conc", type=int, default=40)
    ap.add_argument("--coded", action="store_true",
                    help="用分类码判据(E/T/X/D/P/W/G/H),输出只列有缺陷的条目")
    ap.add_argument("--with-en", action="store_true",
                    help="C 档:再喂 definition(英文释义)当锚。全库覆盖 17.9%")
    ap.add_argument("--thinking", action="store_true",
                    help="DeepSeek 开思考模式(默认关)。V4 的原生模式,漏判可能来自被掐断思考")
    ap.add_argument("--eval-set", action="store_true",
                    help="只判 eval_set.json 里那 83 条人工标注样本(调 prompt 时用)")
    ap.add_argument("--extend-from", action="append", default=[],
                    help="先纳入这些 jsonl 里已判过的 id(可多次),再补随机样本到 --n。"
                         "用于新旧判据在**同一批词**上逐条对比")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ids = [r[0] for r in conn.execute(f"SELECT id FROM stardict WHERE {SPACE}")]
    random.seed(a.seed)

    seeded = set()
    if a.eval_set:
        ev = json.load(open(paths.WORK / "runs/eval_set.json", encoding="utf-8"))
        seeded = {r["id"] for r in ev}
        a.n = len(seeded)          # 只判这批,不补随机样本
        print(f"[评测集] 只判人工标注的 {len(seeded)} 条", flush=True)
    for f in a.extend_from:
        for ln in open(HERE / f, encoding="utf-8"):
            r = json.loads(ln)
            if not r.get("_meta") and r.get("v") != "novote":
                seeded.add(r["id"])
    if seeded:
        print(f"[对比基线] 纳入已判过的 {len(seeded):,} 条", flush=True)
    rest = [i for i in ids if i not in seeded]
    need = max(0, a.n - len(seeded))
    pick = seeded | set(random.sample(rest, min(need, len(rest))))

    cols = "id, word, translation, exchange, qual" + (", definition" if a.with_en else "")
    rows = []
    for r in conn.execute(f"SELECT {cols} FROM stardict"):
        if r[0] not in pick:
            continue
        rows.append((r[0], r[1], r[2], r[3], r[4] or "", B.classify(r[1], r[2]),
                     (r[5] if a.with_en else None)))
    conn.close()
    rows.sort(key=lambda r: r[0])          # 固定顺序,两模型批次划分完全一致
    nin = sum(1 for r in rows if infl(r[3]))
    print(f"样本空间 {len(ids):,} 条(排除 core/fixed);抽 {len(rows):,}  seed={a.seed}", flush=True)
    print(f"  其中有 infl 变形关系 {nin:,} ({nin/max(len(rows),1)*100:.1f}%) —— B 档只对这批多喂一个字段",
          flush=True)

    env = A.load_env()
    sysp = JUDGE_SYS_CODED if a.coded else JUDGE_SYS_B
    metas = [rows[j:j + CHUNK] for j in range(0, len(rows), CHUNK)]
    batches = []
    nen = 0
    for m in metas:
        b = {}
        for k, r in enumerate(m, 1):
            d = {"word": r[1], "zh": r[2]}
            iv = infl(r[3])
            if iv:
                d["infl"] = iv
            if a.with_en and (r[6] or "").strip():
                d["en"] = (r[6] or "").strip().replace("\n", " ")[:180]
                nen += 1
            b[str(k)] = d
        batches.append(b)
    if a.with_en:
        print(f"  其中有 en 英文释义 {nen:,} ({nen/max(len(rows),1)*100:.1f}%)", flush=True)
    print(f"  → {len(batches)} 批 × {CHUNK},{a.provider}/{a.model},"
          f"判据={'分类码' if a.coded else 'B档ok/bad'},并发 {a.conc}", flush=True)

    async def go():
        sem = asyncio.Semaphore(a.conc)
        pt = [0]; ct = [0]; done = [0]; fails = [0]; hit = [0]
        out = [None] * len(batches)

        if a.provider == "ark":
            from volcenginesdkarkruntime import AsyncArk
            cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
            model = env[ARK_MODELS[a.model]]
            call = lambda p: ark_call(cl, model, sysp, p)
        else:
            import httpx
            cl = httpx.AsyncClient(timeout=httpx.Timeout(900.0))
            call = lambda p: ds_call(cl, env["DEEPSEEK_API_KEY"], a.model, sysp, p,
                                     think=a.thinking)

        # ⭐ 缓存预热:系统提示每批相同,但并发一起发时开局全部未命中(实测 conc=40 会白付 40 批全价)。
        #   先单发一发把前缀缓存建起来,再放并发。DeepSeek 实测第 2 发起 1024/1068 命中。
        try:
            await call(batches[0])
            print("  [预热] 已建立前缀缓存", flush=True)
        except Exception as e:
            print(f"  [预热] 失败(不影响主跑): {type(e).__name__}", flush=True)

        async def one(i, p):
            async with sem:
                delay = 3
                for att in range(4):
                    try:
                        txt, (pi, co, hi) = await call(p)
                        pt[0] += pi; ct[0] += co; hit[0] += hi
                        out[i] = A.loads_lenient(
                            txt.strip().strip("`").replace("json\n", "", 1)
                            if txt.strip().startswith("`") else txt.strip())
                        break
                    except Exception as e:
                        if att == 3:
                            fails[0] += 1
                            print(f"  ✗ 批{i} {type(e).__name__}: {str(e)[:120]}", flush=True)
                        else:
                            await asyncio.sleep(delay); delay = min(delay * 2, 30)
                done[0] += 1
                if done[0] % 25 == 0 or done[0] == len(batches):
                    print(f"  [{done[0]}/{len(batches)}] 输入 {pt[0]:,}(缓存命中 {hit[0]:,}) "
                          f"输出 {ct[0]:,} 失败 {fails[0]}", flush=True)

        t0 = time.time()
        await asyncio.gather(*[one(i, p) for i, p in enumerate(batches)])
        if a.provider == "ark":
            await cl.close()
        else:
            await cl.aclose()
        return out, pt[0], ct[0], fails[0], time.time() - t0, hit[0]

    res, pin, cout, fails, dt, chit = asyncio.run(go())

    tally = Counter(); recs = []; codec = Counter()
    for bi, (meta, r) in enumerate(zip(metas, res)):
        failed = r is None                       # 整批失败 → 不能把它当"全 ok"
        r = r or {}
        for k, (rid, w, t, e, q, bk, dfn) in enumerate(meta, 1):
            v = r.get(str(k))
            if a.coded:
                # 分类码模式:键出现即有缺陷;整批失败记 novote,否则未出现即 ok
                if failed:
                    vv, cs = "novote", ""
                elif v is None:
                    vv, cs = "ok", ""
                else:
                    cs = "".join(ch for ch in str(v if isinstance(v, str) else
                                                  (v.get("code") or v.get("v") or "")).upper()
                                 if ch in CODES)
                    vv = "bad" if cs else "ok"
                for ch in cs:
                    codec[ch] += 1
            else:
                vv = v.get("v") if isinstance(v, dict) else None
                if vv not in ("ok", "warn", "bad"):
                    vv = "novote"
                cs = ""
            tally[vv] += 1
            recs.append(dict(id=rid, w=w, zh=t, infl=infl(e), qual=q, bucket=bk, v=vv,
                             codes=cs,
                             note=("" if a.coded else
                                   (v.get("note", "") if isinstance(v, dict) else ""))))

    # ⚠️ 文件名必须含判据:coded 与 B 档同模型/同 n/同 seed 会**静默互相覆盖**
    #   (2026-07-30 踩过,第二次跑把第一次的结果冲掉了)。判据是自变量,得进文件名。
    tag = f"{a.provider}-{a.model}".replace("/", "_") + ("-coded" if a.coded else "-B")
    outp = HERE / f"runs/judge_{tag}_{a.n}_seed{a.seed}.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(_meta=True, provider=a.provider, model=a.model, n=len(recs),
                                seed=a.seed, space=SPACE, grade="B",
                                prompt_tokens=pin, completion_tokens=cout, cache_hit=chit,
                                fails=fails, seconds=round(dt, 1)), ensure_ascii=False) + "\n")
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    tot = len(recs); scored = tot - tally["novote"]
    print(f"\n===== {a.provider}/{a.model}  {tot} 条(有效 {scored})  {dt:.0f}s =====")
    for lab in ("ok", "warn", "bad"):
        print(f"  {lab:5} {tally[lab]:>5} ({100*tally[lab]/max(scored,1):5.1f}%)")
    print(f"  novote {tally['novote']}   批次失败 {fails}")
    print(f"  token 输入 {pin:,} / 输出 {cout:,} / 合计 {pin+cout:,}"
          f"   输出占比 {100*cout/max(pin+cout,1):.0f}%   每条 {(pin+cout)/max(tot,1):.1f}")
    print(f"  缓存命中 {chit:,} / 输入 {pin:,} = {100*chit/max(pin,1):.1f}%"
          f"   (未命中 {pin-chit:,})")
    if a.provider == "deepseek":   # flash: 命中 0.02元/M 未命中 1元/M 输出 2元/M
        yuan = (chit*0.02 + (pin-chit)*1.0 + cout*2.0) / 1e6
        print(f"  实付 ≈ {yuan:.4f} 元  → 折算全库 3,450,964 条 ≈ "
              f"{yuan/max(tot,1)*3450964:.0f} 元")
    if a.coded and codec:
        LAB = {"E": "空壳", "T": "残缺", "X": "非中文", "D": "学科错",
               "P": "词性/变形错", "W": "错译", "G": "乱码", "H": "词头坏"}
        print("\n  —— 缺陷分类(可多码,故合计>bad 数) ——")
        for ch, n in codec.most_common():
            print(f"    {ch} {LAB.get(ch,ch):<12} {n:>5}  ({100*n/max(tally['bad'],1):5.1f}% of bad"
                  f" / {100*n/max(scored,1):5.2f}% of 样本)")
    print(f"\n  → {outp.name}")


if __name__ == "__main__":
    main()
