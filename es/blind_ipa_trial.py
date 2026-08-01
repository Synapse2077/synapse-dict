#!/usr/bin/env python3
"""es 音标**双专家独立复核** —— 同一批 1500 条 + 同一份规则,分别请 deepseek-v4-pro 与
豆包 seed-2.1-turbo 各自独立给出音标学意见。见对话 2026-07-31。

═══ 定位:请专家,不是请判官 ═══
不是让模型"给我的工作打分"。今天已经验证过那条路走不通 —— 上午两家模型收敛的五个缺陷族,
**四个经回源核对是错的**(coda 浊化、短语次重音、过去分词指针,以及 w̝ 那 83 条:我照着
模型结论把 kaikki 原文改坏了)。用一个不可靠的评判者去验收另一个,不会收敛。
这轮请它们做的是**它们能做而确定性方法做不到的事**:全库 763,124 条音标里只有 140,031 条
(18.4%)逐条有人工源确认,**其余 623,093 条没有任何真值可比**。那 62 万条上,
西语语音学知识是唯一的第二意见来源。

它们的产出是**线索,不是判决**:指出的每一族,动手前仍须回 kaikki / 音系事实逐条核对。

═══ 给什么、不给什么 ═══
给:① 完整转写约定(RULE_DOC,原样);② 词形;③ **原形**(变形形给出它的 lemma,
     让专家能顺着"原形→规则→结果"这条链推,而不是孤立看一个字符串);④ 库里实际存的音标。
不给:**该词在 kaikki 的音标原文**。理由不是防作弊,而是:
     - kaikki 覆盖的那 18% 上,"库值==kaikki值"我一行代码就能确定性算出,不必花钱问;
     - 给了之后 kaikki 原生层必然 0 标出,负控失效,就无从知道这批意见值不值得看。
     约定给、单条答案不给 —— 专家不会因为不认识本词典约定而误报,但必须真的去推导。

═══ 分层即正负控 ═══
  `kaikki原生` = 负控(人工源,标出率应低)   `豆包填空` = 正控(已确定性证实含真缺陷)
  两层标出率**没拉开 ⇒ 本轮意见不可用**,先看这个再看任何缺陷族。
  另塞 5% 重复条测**自噪**(同一条数据前后是否自相矛盾;上午实测高达 45%)。
  材料一律**中性陈述**,不写"疑似过度""这是坑" —— 上午把结论写进统计项标题,
  两家于是齐齐"发现"了它,收敛的是我的偏见。见 [[llm-as-evaluator-discipline]] ⑨。

🔴 两家都开思考(音标是推导任务,关思考实测摆烂)。两家数字**不能相减**(不同尺),
   只能各自看自己内部的层间对比。

用法(在 es/ 目录):
  python3 blind_ipa_trial.py --n 1500
  python3 blind_ipa_trial.py --n 100 --only v4pro     # 小跑调材料
"""
import argparse, asyncio, json, random, re, sqlite3, time
from collections import Counter, defaultdict
from pathlib import Path

import kaikki_util
from b_ipa import word_to_ipa

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
ENV = paths.ENV
RUNS = paths.WORK / "runs"

# ═════════════════════════════════════════════════ 转写约定(原样给两家)
# ⚠️ 从 b_ipa.py / spanish.ts 逐条提取的**行为**,不含对错评价、不含来历说明。
#   两家收到同一字节的这份文本。改它 = 改实验条件,改了要两家一起重跑。
RULE_DOC = """【本词典西语音标的转写约定】

一、字母 → 音位
  a e i o u（含 á é í ó ú）→ a e i o u ；ü → u
  c 在 e/i/é/í 前 → θ ；其余 c → k ；ch → t͡ʃ
  q 在 ue/ui 中 → k ；其余 q → k
  g 在 e/i 前 → x ；gu 在 e/i 前 → ɡ ；gü 在 e/i 前 → ɡw ；gu 在 a/o 前 → ɡw ；其余 g → ɡ
  ll → ʝ
  rr → r ；r 在词首或 n/l/s 之后 → r ；其余 r → ɾ
  y 在元音前 → ʝ ；其余 y → 元音 i
  h 不发音，跳过；但 hu + 元音 → w̝
  j → x ；v → b ；z → θ ；x → ks ；ñ → ɲ
  b d f k l m n p s t w → b d f k l m n p s t w
  出现以上之外的字母（à ç ø 等或非拉丁字符）→ 该词不生成音标
  含空格或连字符的词 → 该词不生成音标

二、音节与双元音
  无重音符的弱元音 i/u 与相邻元音合成双元音：升双元音写作滑音 j / w，降双元音保留元音符号
  两辅音之间切分音节；pl pɾ bl bɾ fl fɾ kl kɾ ɡl ɡɾ tɾ dɾ 视为同一音节的起始丛

三、音位调整（在重音位置确定之后施加）
  n 在 b / p / m 之前 → m
  p / t / k 在另一辅音之前（且二者不构成上列起始丛）→ b / d / ɡ

四、重音
  词形带重音符 → 重音标在该音节
  单音节词 → 重音标在该音节
  词形无重音符：词尾是元音或 n / s → 倒数第二音节；否则 → 最后一音节
  只输出主重音 ˈ，不输出次重音 ˌ

五、存储与展示
  库内存**裸串**（不带斜杠），展示层再加 /…/
  展示时：串中若含 /…/ 则只取斜杠内内容，否则删去 […] 段；
          删连接弧 ͡（t͡ʃ → tʃ）；删音节点 . 与长音符 ː；删升符 ̝ 与降符 ̞
  拉美音由半岛音派生：所有 θ → s"""

# ═════════════════════════════════════════════════ 任务一:逐条复核
SYS_DATA = """你是独立的西班牙语语音学专家。一部西汉词典请你复核它的西语音标。
你不是在给谁打分，是请你以专业身份给出你自己的判断：**这条音标对不对**。

每条给你：
  w     西语词形
  base  该词形的原形（若这是一个变形形式；lemma 本身没有这一项）
  ipa   词典目前存的音标（**裸串，不带斜杠**；缺斜杠不是缺陷，不要报）

词典采用的转写约定如下，请**顺着「原形 → 约定 → 结果」这条链去推**，
而不是孤立地看一个字符串：

""" + RULE_DOC + """

对每条判断：这个 ipa 是否**既符合上述约定、又与该词的实际读音相符**。

字母码：
  A 音位错：某个字母转写成了错误的音位（θ/s、b/v、x/h、ɾ/r、ʝ/ʎ 等混用）。
  B 重音错：ˈ 的位置不符合上述重音规则，或多音节词整条没有 ˈ。
  C 正字法残留：音标里混进了未转写的拼写字母，像是把词形抄了一段而不是转写。
  D 整体读错：音标与该词形明显对不上（元音/辅音串接不上）。
  E 符号不属于西语音系：出现了西语音位系统里没有的符号。
  F 与上述约定不符（但你认为读音本身没错）。

以下**不要列出**：
- 词生僻、专业、古旧、方言、外来词、专有名词 —— 只要转写没错；
- 单音节词或虚词没标 ˈ；
- 多词短语的音标中间有空格；
- w / j 作半元音（cuando → ˈkwando、bien → ˈbjen）。

宁可漏报，不要凑数；拿不准就不列出该条。
严格输出 JSON，只含**你认为有问题**的条目，键与输入的键一致：
{"3":{"c":"A","ipa":"你认为正确的音标","why":"12字以内"},"7":{"c":"B","ipa":"…","why":"…"}}
全部没问题则输出 {}。不要任何解释文字。"""

# ═════════════════════════════════════════════════ 任务二:评审约定本身
# ⚠️ 统计项一律**中性命名**:只写现象和条数,不写"疑似""残留""缺陷"。
SYS_RULES = """你是独立的西班牙语语音学专家。下面是一部西汉词典的音标转写约定，以及这套约定
在全库产生的统计。请以专业身份评审**约定本身**（不是评审个别词条）。

""" + RULE_DOC + """

【全库统计（共 763,124 条音标；其中 140,031 条另有 Wiktionary 人工音标可逐字对照）】
{STATS}

【按上述约定生成的实际输出（供你引用；**只准引用这些词**，不得自行举其他例词）】
{EXAMPLES}

请指出这套约定里**你认为不成立的条款**，每条说明：
  rule   你质疑的条款（引用上面的原文片段）
  why    为什么不成立（一句话，须落到具体音系事实）
  fix    你建议改成什么
  cases  从上面给定例词里选出能支撑你观点的词（**不得编造未给出的词**）
  conf   你的把握 high / mid / low

不要评论存储格式、斜杠、展示层这类工程问题，只看音系。
你认为成立的条款，不要列出。
严格输出 JSON：{"issues":[{"rule":"…","why":"…","fix":"…","cases":["…"],"conf":"high"}]}
没有问题则输出 {"issues":[]}。不要任何解释文字。"""

LAB = {"A": "音位错", "B": "重音错", "C": "正字法残留", "D": "整体读错",
       "E": "非西语音系符号", "F": "与约定不符"}


# ═════════════════════════════════════════════════ 抽样
def classify(rows, kk):
    """与 ipa_census.py 同一口径的来源判定。"""
    out = []
    for rid, w, p, isl, exch in rows:
        kv, rv = kk.get(w), word_to_ipa(w)
        rv = rv.strip("/") if rv else None
        if kv is not None and kv == p:
            src = "kaikki原生"
        elif rv is not None and rv == p:
            src = "规则生成"
        elif kv is not None:
            src = "kaikki被改写"
        elif rv is not None:
            src = "规则算得出但不同"
        else:
            src = "豆包填空"
        base = ""
        for ln in (exch or "").split("\n"):          # exchange 每行 "0:原形"
            ln = ln.strip()
            if ln:
                base = ln.split(":", 1)[-1].strip()
                break
        out.append((rid, w, p, isl, src, base))
    return out


DOUBLE = re.compile(r"(pp|ss|tt|ff|mm|gg|bb|dd|kk|zz)", re.I)
CODA = re.compile(r"[ɡbd][ptkθsfx]")

# 分层配额(合计 1500)。⭐ 依据是**背书程度**,不是体量比例:
#   变形层 588,952 条占全库 77%,但它的质量目前只有一个**未经检验的外推假设**支撑
#   (拿 kaikki 恰好收录的 6.7 万变形形比对得 98.02%,而那批词不在这 58.9 万里)。
#   给它 450+150 条,就是为了检验这个假设 —— 若其标出率与 kaikki 原生层(负控)接近,
#   外推成立;若显著更高,说明规则在 kaikki 未收词上退化,那是几十万条的事。
QUOTA = [
    ("kaikki原生·负控",   200),
    ("规则生成·变形层",   450),
    ("变形层·定向弱项",   150),
    ("多词无次重音",      150),
    ("规则生成·lemma",    150),
    ("规则算得出但不同",  200),
    ("豆包填空·正控",     200),
]


def build_sample(n, seed):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT id, word, phonetic, is_lemma, COALESCE(exchange,'') FROM dict "
                        "WHERE TRIM(COALESCE(phonetic,''))<>''").fetchall()
    conn.close()
    print(f"全库有音标 {len(rows):,} 行,判定来源中…", flush=True)
    kk = kaikki_util.phonemic_ipa({r[1] for r in rows})
    print(f"  kaikki 音位式 {len(kk):,} 词", flush=True)
    allr = classify(rows, kk)
    by = defaultdict(list)
    for r in allr:
        by[r[4]].append(r)
    rule = by["规则生成"]
    pools = {
        "kaikki原生·负控":  by["kaikki原生"],
        "规则生成·变形层":  [r for r in rule if not r[3]],
        "变形层·定向弱项":  [r for r in rule if not r[3] and (CODA.search(r[2]) or DOUBLE.search(r[1]))],
        "多词无次重音":     [r for r in allr if " " in r[1] and "ˌ" not in r[2]],
        "规则生成·lemma":   [r for r in rule if r[3]],
        "规则算得出但不同": by["规则算得出但不同"],
        "豆包填空·正控":    by["豆包填空"],
    }
    k = n / 1500
    picked, seen = [], set()
    for name, q in QUOTA:
        pool = [r for r in pools[name] if r[0] not in seen]
        random.seed(seed + sum(map(ord, name)))
        take = random.sample(pool, min(int(q * k), len(pool)))
        for r in take:
            seen.add(r[0])
        picked += [(*r, name) for r in take]
        print(f"  {name:18} 池 {len(pool):>7,} → 抽 {len(take):>4}", flush=True)

    random.seed(seed + 999)                       # 自噪标定:5% 复制,打乱后落在不同批次
    dups = random.sample(picked, max(1, int(len(picked) * 0.05)))
    picked = [(*r, False) for r in picked] + [(*r, True) for r in dups]
    random.shuffle(picked)
    print(f"共 {len(picked)} 条(含重复 {len(dups)} 条用于自噪标定)", flush=True)
    return picked          # (id, w, ipa, is_lemma, src, base, layer, is_dup)


# ═════════════════════════════════════════════════ 调用
def load_env():
    env = {}
    for ln in open(ENV, encoding="utf-8"):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def loads_lenient(s):
    """容错解析:去 ``` 围栏、掐首尾大括号、补条目间缺失逗号、去尾逗号。两家都会犯这些。"""
    s = re.sub(r"^```(json)?|```$", "", s.strip(), flags=re.M).strip()
    if "{" in s:
        s = s[s.find("{"):s.rfind("}") + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        f = re.sub(r'}\s*\n\s*(")', r'},\n\1', s)
        f = re.sub(r'}\s+(")', r'}, \1', f)
        f = re.sub(r',\s*([}\]])', r'\1', f)
        return json.loads(f)


# 🔴 思考开关**必须用负控量,不能靠论证**。2026-07-31 用户质疑"这不就是个简单的音标判断,
#   要开思考吗" —— 我原来的理由(推导任务)其实是从**另一份 prompt**(verify_v4pro 判据)上
#   测到的退化行为外推来的,证明的是"那个模型+那个 prompt+关思考会退化",不是本任务的性质。
#   → `--nothink` 就是为跑这个 A/B 而加:同材料同抽样,只切这一个变量,看正负控差值与自噪。
THINK = True

# 单次调用的硬上限(秒)。开思考时 25 条一批实测约 190s;规则任务单批约 170s。
# 600s 已经很宽,超了就是卡住,重试比干等强 —— 见 one() 里的注释(实测挂过 5h45m)。
CALL_TIMEOUT = 600


async def call_v4pro(cl, key, sysp, payload):
    r = await cl.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": "deepseek-v4-pro",
                            "messages": [{"role": "system", "content": sysp},
                                         {"role": "user", "content": "输入:\n" + json.dumps(payload, ensure_ascii=False)}],
                            "temperature": 0,
                            "response_format": {"type": "json_object"},
                            "thinking": {"type": "enabled" if THINK else "disabled"},
                            "stream": False})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    d = json.loads(r.text.lstrip())          # 坑:非流式等待期持续返回空行保活
    u = d.get("usage") or {}
    return d["choices"][0]["message"]["content"], (
        u.get("prompt_tokens", 0), u.get("completion_tokens", 0), u.get("prompt_cache_hit_tokens", 0))


async def call_turbo(ep, model, sysp, payload):
    r = await ep.create(model=model, temperature=0,
                        thinking={"type": "enabled" if THINK else "disabled"},
                        messages=[{"role": "system", "content": sysp},
                                  {"role": "user", "content": "输入:\n" + json.dumps(payload, ensure_ascii=False)}])
    u = r.usage
    return r.choices[0].message.content, (u.prompt_tokens, u.completion_tokens, 0)


async def run(tag, caller, sysp, batches, conc):
    out = [None] * len(batches)
    tk = [0, 0, 0]; done = [0]; fails = [0]
    todo = list(range(len(batches)))
    # 🔴 **不做缓存预热**(2026-07-31 用户拍板去掉)。原设计是第 0 批先串行跑一次,把相同的
    #   系统提示写进 provider 缓存,后面并发批才不会开局全部未命中。三个理由都不成立:
    #   ① 赚得极少:缓存只省输入的 (4−0.2) 元/M。1500 条那跑系统提示约 1,400 token × 62 批
    #      ≈ 8.7 万 token 命中,**总共省 0.33 元**,而整跑要 8 元。
    #   ② 亏墙钟:并发开始前先串行等一整批 —— 开思考时一批就是 3~4 分钟,占整跑墙钟 12%。
    #   ③ 旧实现还额外犯错:返回值被丢弃导致第 0 批跑两遍、预热用量不进 tk 导致报出的成本
    #      少算一批、单批任务(规则评审)预热等于纯翻倍。
    #   → 全部批次直接并发齐发。少赚 0.33 元,换回一轮墙钟和一份不会算错的账。
    sem = asyncio.Semaphore(conc)

    async def one(i, p):
        async with sem:
            delay = 3
            for att in range(4):
                try:
                    # 🔴 硬性总时限。httpx 的 timeout 是**读超时**(多久没收到字节),而 deepseek
                    #   非流式等待期会持续发空行保活,每个空行都把读超时重置 → 永远不触发。
                    #   2026-07-31 实测:一次规则调用挂了 5 小时 45 分,连接始终 ESTABLISHED,
                    #   进程内已跑完的数据任务结果(34,199 token)因此全部拿不出来。
                    txt, (pi, co, hi) = await asyncio.wait_for(caller(sysp, p), CALL_TIMEOUT)
                    tk[0] += pi; tk[1] += co; tk[2] += hi
                    out[i] = loads_lenient(txt)
                    break
                except Exception as e:
                    if att == 3:
                        fails[0] += 1
                        print(f"    ✗ [{tag}] 批{i} {type(e).__name__}: {str(e)[:110]}", flush=True)
                    else:
                        await asyncio.sleep(delay); delay = min(delay * 2, 30)
            done[0] += 1
            if done[0] % 10 == 0 or done[0] == len(todo):
                print(f"    [{tag}] {done[0]}/{len(todo)} 输入 {tk[0]:,} 输出 {tk[1]:,}", flush=True)

    t0 = time.time()
    await asyncio.gather(*[one(i, batches[i]) for i in todo])
    print(f"  [{tag}] 完成 {time.time()-t0:.0f}s 失败批 {fails[0]}", flush=True)
    return out, tuple(tk), fails[0]


# ═════════════════════════════════════════════════ 报告
def report(tag, rows, res, metas):
    flags = {}                                   # (id, is_dup) → 意见
    for meta, out in zip(metas, res):
        for k, v in (out or {}).items():
            try:
                r = meta[int(k) - 1]
            except (ValueError, IndexError):
                continue
            if isinstance(v, dict):
                flags[(r[0], r[7])] = v

    per = defaultdict(lambda: [0, 0])
    codes = Counter()
    for r in rows:
        per[r[6]][0] += 1
        if (r[0], r[7]) in flags:
            per[r[6]][1] += 1
            codes[str(flags[(r[0], r[7])].get("c", "?"))[:1]] += 1

    print(f"\n{'='*72}\n【{tag}】标出率 × 来源层\n{'='*72}")
    print(f"{'层':20}{'样本':>7}{'标出':>7}{'标出率':>9}")
    for name, _ in QUOTA:
        s, f = per.get(name, [0, 0])
        print(f"{name:20}{s:>7}{f:>7}{100*f/max(s,1):>8.1f}%")

    neg, pos = per.get("kaikki原生·负控", [0, 0]), per.get("豆包填空·正控", [0, 0])
    nr, pr = 100*neg[1]/max(neg[0], 1), 100*pos[1]/max(pos[0], 1)
    print(f"\n  负控(kaikki原生) {nr:.1f}%   正控(豆包填空) {pr:.1f}%   差 {pr-nr:+.1f} 个百分点")
    print("  → " + ("这位专家的意见有分辨力,可用于定位缺陷族" if pr - nr >= 10 else
                    "🔴 正负控没拉开,本轮意见不可用,别看下面的族"))

    dup_ids = {r[0] for r in rows if r[7]}
    if dup_ids:
        agree = sum(((i, False) in flags) == ((i, True) in flags) for i in dup_ids)
        print(f"\n  自噪标定:重复条 {len(dup_ids)} 组,两次判定一致 {agree} 组 "
              f"= {100*agree/len(dup_ids):.1f}%")
        print(f"    (不一致 {100-100*agree/len(dup_ids):.1f}% 是它对**同一条数据**前后矛盾的比例)")

    print("\n  字母码分布: " + "  ".join(f"{c}{LAB.get(c,c)} {n}" for c, n in codes.most_common()))
    return flags, {k: v for k, v in per.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--chunk", type=int, default=25)
    ap.add_argument("--conc", type=int, default=8)
    ap.add_argument("--seed", type=int, default=731)
    ap.add_argument("--only", choices=["v4pro", "turbo"])
    ap.add_argument("--nothink", action="store_true", help="关思考(A/B 用,见 THINK 注释)")
    a = ap.parse_args()
    global THINK
    THINK = not a.nothink

    rows = build_sample(a.n, a.seed)
    metas, batches = [], []
    for j in range(0, len(rows), a.chunk):
        sub = rows[j:j + a.chunk]
        # ⚠️ 本地键 '1'..'N'。用全局唯一键模型会重编号成 '1',必错配。
        b = {}
        for i, r in enumerate(sub, 1):
            d = {"w": r[1], "ipa": r[2]}
            if r[5] and r[5] != r[1]:
                d["base"] = r[5]                 # 原形,供顺链推导
            b[str(i)] = d
        batches.append(b); metas.append(sub)
    print(f"切 {len(batches)} 批 × {a.chunk}", flush=True)

    stats = ("- 音标总条数 763,124；其中与 Wiktionary 人工音标逐字相同的 140,031 条\n"
             "- 由上述规则生成的 598,863 条；其余为其他来源\n"
             "- 拿 125,902 个有人工音标可对照的词重跑本规则，逐字相同 119,963 条（95.28%）\n"
             "- 不同的 5,939 词中，差异出现处数最多的几种：\n"
             "    人工有 ˌ 而规则无 2,963 处；人工有 ˈ 而规则无 788 处；规则有 ˈ 而人工无 421 处\n"
             "    人工 ˌ 而规则 ˈ 365 处；规则多出 ɡ 213 处；人工 t 而规则 d 176 处\n"
             "    规则多出 b 171 处；人工 i 而规则 j 169 处；人工 ʃ 而规则 s 140 处\n"
             "- 含空格的词条 9,088 条其音标无 ˌ\n"
             "- 音标中浊塞音 ɡ/b/d 紧跟清辅音的 31,890 条\n"
             "- 词形含 pp/ss/tt/ff 等双写辅音的 1,264 条")
    random.seed(a.seed)
    ex = random.sample([r for r in rows if not r[7]], min(60, len(rows)))
    sys_rules = (SYS_RULES.replace("{STATS}", stats)
                 .replace("{EXAMPLES}", "\n".join(f"  {r[1]} → {r[2]}" for r in ex)))

    env = load_env()
    RUNS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    saved = {"stamp": stamp, "n": len(rows), "seed": a.seed, "quota": dict(QUOTA)}

    rowmeta = [{"id": r[0], "w": r[1], "ipa": r[2], "base": r[5],
                "layer": r[6], "dup": r[7]} for r in rows]

    def dump_raw(tag, ra, rb, tka, tkb):
        """🔴 **每家一跑完立刻落盘**,不等另一家。
        2026-07-31 踩过:两家串行且只在最末尾写文件 —— 第一家跑了 28 分钟、7.8 元,
        第二家刚起步时想中止,才发现一 kill 全丢。任何一家卡住/被中断,另一家的钱不该白花。"""
        p = RUNS / f"blind_ipa_{stamp}_{tag}{'' if THINK else '-nothink'}.json"
        p.write_text(json.dumps(
            {"stamp": stamp, "n": len(rows), "seed": a.seed, "model": tag,
             "quota": dict(QUOTA), "rows": rowmeta,
             "raw_data": ra, "raw_rules": rb, "tokens": {"数据": tka, "规则": tkb}},
            ensure_ascii=False), encoding="utf-8")
        print(f"  [{tag}] 原始结果已落盘 → {p.name}", flush=True)

    async def job_v4pro():
        import httpx
        cl = httpx.AsyncClient(timeout=httpx.Timeout(900.0))
        key = env["DEEPSEEK_API_KEY"]
        c = lambda s, p: call_v4pro(cl, key, s, p)
        print("\n─── v4-pro 起跑(数据 → 规则)───", flush=True)
        ra, tka, _ = await run("v4pro-数据", c, SYS_DATA, batches, a.conc)
        dump_raw("v4pro", ra, None, tka, (0, 0, 0))   # 🔴 数据一跑完立刻落盘,别等规则任务
        rb, tkb, _ = await run("v4pro-规则", c, sys_rules, [{"go": 1}], 1)
        await cl.aclose()
        dump_raw("v4pro", ra, rb, tka, tkb)
        return "v4pro", (ra, rb, tka, tkb)

    async def job_turbo():
        from volcenginesdkarkruntime import AsyncArk
        client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        c = lambda s, p: call_turbo(client.batch.chat.completions, model, s, p)
        print("\n─── 豆包turbo 起跑(数据 → 规则)───", flush=True)
        ra, tka, _ = await run("turbo-数据", c, SYS_DATA, batches, a.conc * 2)
        dump_raw("turbo", ra, None, tka, (0, 0, 0))   # 同上
        rb, tkb, _ = await run("turbo-规则", c, sys_rules, [{"go": 1}], 1)
        dump_raw("turbo", ra, rb, tka, tkb)
        return "turbo", (ra, rb, tka, tkb)

    async def go():
        # ⭐ 两家**并发**。它们之间没有任何依赖(不同厂商/不同 key/不同连接池),
        #   串行只会让墙钟时间翻倍。谁先跑完谁先落盘。
        jobs = []
        if a.only != "turbo":
            jobs.append(job_v4pro())
        if a.only != "v4pro":
            jobs.append(job_turbo())
        return dict(await asyncio.gather(*jobs))

    res = asyncio.run(go())

    for tag, (ra, rb, tka, tkb) in res.items():
        flags, per = report(tag, rows, ra, metas)
        rev = ((rb[0] if rb else None) or {}).get("issues", [])
        print(f"\n【{tag}】对约定本身提出 {len(rev)} 条质疑:")
        for it in rev:
            print(f"  ◆[{it.get('conf','?')}] {str(it.get('rule',''))[:46]}")
            print(f"     why  {str(it.get('why',''))[:80]}")
            print(f"     fix  {str(it.get('fix',''))[:80]}")
            print(f"     例词 {', '.join(map(str, it.get('cases', [])))[:80]}")
        saved[tag] = {"per_layer": per, "tokens": {"数据": tka, "规则": tkb},
                      "opinions": {f"{i}|{int(d)}": v for (i, d), v in flags.items()},
                      "rule_review": rev}

    saved["rows"] = rowmeta
    p = RUNS / f"blind_ipa_{stamp}.json"
    p.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {p.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
