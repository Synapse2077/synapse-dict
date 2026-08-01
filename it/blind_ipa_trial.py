#!/usr/bin/env python3
"""it 音标独立复核 —— 请 deepseek-v4-pro 以意语语音学专家身份逐条复核 + 评审转写约定。
2026-08-01。it 独立文件，不 import 其他语种（multilang-decoupling-essence 铁律）。

═══ 这一跑要回答什么 ═══
来源普查(`ipa_census.py`)已确定性量出：库内 584,460 条音标里 **85.2% 是 G2P 规则生成**，
其中 63.1% 走了「kaikki forms 带重音形」路径、36.9% 退回「倒二音节+闭元音」默认。
拿 kaikki 的 8.3 万词形当真值实测：**有重音形路径逐字一致 82.3%，无重音形路径只有 43.2%**。
→ 那 18.4 万条走默认路径的行是 it 的主要风险面，而它们**没有任何真值可比**。
   意语语音学知识是唯一的第二意见来源。它的产出是**线索不是判决**，动手前仍须回 kaikki 核对。

═══ 🔴 正控靠人工注入（it 没有天然的"已知有缺陷层"）═══
es 的正控是「豆包填空」那 1 万条已确证有缺陷的行；it 的豆包填空只有 104 行，用不了。
→ 按 [[llm-as-evaluator-discipline]] ⑦：**从 kaikki 原生行（原值确定正确）里取样做确定性破坏**，
  混进样本当正控。四种破坏都是意语真实错误类型：
    ① 挪重音（ˈa.kwi.la → aˈkwi.la）        ② 开闭翻转（ˈlɛn.te → ˈlen.te）
    ③ 音段替换（t͡ʃ→k、ʃ→s、ʎ→l）           ④ 去双辅音长化（ˈɡat.to → ˈɡa.to）
  **注入行只进 payload，绝不写库。**负控(kaikki原生原样) 与正控(同批行被破坏后)标出率
  **没拉开 ⇒ 本轮意见不可用**，先看这个再看任何缺陷族。

═══ 从 es 那边继承下来的、已验证的工程约定 ═══
· **thinking 必须开**：2026-07-31 es 上 A/B 实测，关思考时 88% 的标出是"空转"
  （标出一条、编个理由、把输入原样抄回当正确答案），负控 53.8%、正负控只差 7.7pp。
· **不做缓存预热**：省 0.3 元不值一轮墙钟，且旧实现会白烧一批、用量还不入账。
· **硬超时**：httpx 的 timeout 是读超时，服务端保活空行会不断重置它（实测挂过 5h45m）。
· **每个任务跑完立刻落盘**：数据任务的结果不能等规则任务。
· **空转闸**：提议音标 == 库内值的意见直接丢弃（确定性、免费）。
· 材料一律**中性陈述**，不写"疑似""残留"——把结论写进标题，两家就会齐齐"发现"我的偏见。

用法（在 it/ 目录）：
  python3 blind_ipa_trial.py --n 1500
  python3 blind_ipa_trial.py --n 100      # 小跑调材料
"""
import argparse, asyncio, json, random, re, sqlite3, time
from collections import Counter, defaultdict
from pathlib import Path

import kaikki_util
from b_ipa import word_to_ipa

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-it.sqlite"
ENV = HERE.parent / ".env"
RUNS = HERE / "runs"

THINK = True
CALL_TIMEOUT = 600          # 单次调用硬上限(秒)

# ═════════════════════════════════════ 转写约定(原样给它)
# ⚠️ 从 b_ipa.py / italian.ts 逐条提取的**行为**，不含对错评价、不含来历说明。
RULE_DOC = """【本词典意大利语音标的转写约定】

一、字母 → 音位
  a e i o u → a e i o u ；带重音标注的 à→a è→ɛ é→e ì→i ò→ɔ ó→o ù→u
  c 在 e/i 前 → t͡ʃ ；ch → k ；ci+元音 → t͡ʃ（i 不单独发音）；其余 c → k
  g 在 e/i 前 → d͡ʒ ；gh → ɡ ；gi+元音 → d͡ʒ ；gli(+元音) → ʎ ；gn → ɲ ；其余 g → ɡ
  sc 在 e/i 前 → ʃ ；sch → sk ；sci+元音 → ʃ ；其余 sc → s+k
  s 在浊辅音 b/d/g/l/m/n/r/v/z 前 → z ；元音或滑音之后、元音之前的单 s → z ；其余 s → s
  z 在词首 → d͡z ；其余 z → t͡s
  qu → kw ；h 不发音 ；x → ks ；y → i
  b d f l m n p r t v k j w → b d f l m n p r t v k j w
  出现以上之外的字符 → 该词不生成音标

二、音节与滑音
  不带重音标注的 i/u 紧邻另一元音（前或后）→ 滑音 j / w（piano ˈpja.no、causa ˈkaw.za）
  音节点 . 分隔音节；单辅音归后一音节的起始；塞音/f + l/r 不拆开；双写辅音跨音节切分
  ʎ ɲ ʃ 及 t͡s d͡z 在两个元音之间恒为双辅音（长化）
  相邻两个相同塞擦音 → 前者化为其塞音成分（pit.t͡sa、fat.t͡ʃa）

三、重音
  拼写带重音标注（à è é ì ò ù）→ 重音标在该音节
  无标注 → 倒数第二音节的元音核；单音节词 → 该音节
  主重音写 ˈ，次重音写 ˌ，都写在所属音节之前

四、开/闭元音
  e 与 ɛ、o 与 ɔ 在意语是不同音位，但**不体现在普通拼写里**。
  只有当拼写带 è/ò（开）或 é/ó（闭）标注时才能确定；无标注时一律取闭音 e / o。

五、存储与展示
  库内存**裸串**（不带斜杠），展示层再加 /…/
  展示时：去连结弧（t͡ʃ→tʃ）；ʎ ɲ ʃ 的元音间长化还原为单写；
          真双辅音（双写字母来的）写作长音符 ː（ˈɡat.to → ˈɡatːo）；去音节点；开/闭 ɛ ɔ 保留"""

SYS_DATA = """你是独立的意大利语语音学专家。一部意汉词典请你复核它的意语音标。
你不是在给谁打分，是请你以专业身份给出你自己的判断：**这条音标对不对**。

每条给你：
  w     意语词形
  base  该词形的原形（若这是一个变形形式；lemma 本身没有这一项）
  ipa   词典目前存的音标（**裸串，不带斜杠**；缺斜杠不是缺陷，不要报）

词典采用的转写约定如下，请**顺着「原形 → 约定 → 结果」这条链去推**，
而不是孤立地看一个字符串：

""" + RULE_DOC + """

对每条判断：这个 ipa 是否**既符合上述约定、又与该词的实际读音相符**。

字母码：
  A 音位错：某个字母转写成了错误的音位（t͡ʃ/k、d͡ʒ/ɡ、s/z、ʃ/s、ʎ/l 等混用）。
  B 重音错：ˈ 的位置不符合该词实际重音，或多音节词整条没有 ˈ。
  C 开/闭元音错：该用 ɛ/ɔ 的地方写了 e/o，或反之。
  D 长辅音错：双辅音（gemination）该有而没有，或不该有而有。
  E 音节切分错：音节点 . 的位置不合意语音节法。
  F 符号不属于意语音系：出现了意语音位系统里没有的符号。
  G 整体读错：音标与该词形明显对不上。

以下**不要列出**：
- 词生僻、专业、古旧、方言、外来词、专有名词 —— 只要转写没错；
- 单音节词或虚词没标 ˈ；
- 多词短语的音标中间有空格；
- 连结弧 t͡ʃ d͡ʒ t͡s d͡z 的写法；音节点本身的存在。

宁可漏报，不要凑数；拿不准就不列出该条。
严格输出 JSON，只含**你认为有问题**的条目，键与输入的键一致：
{"3":{"c":"B","ipa":"你认为正确的音标","why":"12字以内"},"7":{"c":"C","ipa":"…","why":"…"}}
全部没问题则输出 {}。不要任何解释文字。"""

SYS_RULES = """你是独立的意大利语语音学专家。下面是一部意汉词典的音标转写约定，以及这套约定
在全库产生的统计。请以专业身份评审**约定本身**（不是评审个别词条）。

""" + RULE_DOC + """

【全库统计（共 584,460 条音标）】
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

LAB = {"A": "音位错", "B": "重音错", "C": "开闭元音错", "D": "长辅音错",
       "E": "音节切分错", "F": "非意语符号", "G": "整体读错"}

# ═════════════════════════════════════ 人工注入的确定性破坏(正控)
VOW = "aeiouɛɔ"


def corrupt(ipa):
    """对一条**确定正确**的 kaikki 原文做一处确定性破坏。返回 [(坏值, 破坏类型), …]。
    四种都是意语真实错误类型;做不到就返回空表(该行不用作正控)。

    🔴 破坏必须**只错一处**:挪重音时原重音位要补回音节点,否则音节结构一并畸形
    (`tris.taˈmen.te` → `tris.tamenˈte`,`tamen` 含两个元音),判官会因为切分明显不对
    而抓到它 —— 那样测出来的是"能不能看出畸形串",不是"能不能看出重音错",正控虚高。"""
    cand = []
    # ① 挪重音:与另一个音节边界**对调**(ˈ↔.),音节数与切分保持不变
    dots = [m.start() for m in re.finditer(r"\.", ipa)]
    si = ipa.find("ˈ")
    if si >= 0 and dots:
        tgt = random.choice(dots)
        s = list(ipa)
        s[si], s[tgt] = ".", "ˈ"
        bad = "".join(s).lstrip(".")            # 词首不该留下孤立的点
        if bad != ipa:
            cand.append((bad, "挪重音"))
    # ② 开闭翻转
    if "ɛ" in ipa or "ɔ" in ipa:
        cand.append((ipa.replace("ɛ", "e").replace("ɔ", "o"), "开闭翻转"))
    elif re.search(r"ˈ[^aeiou]*[eo]", ipa):
        cand.append((re.sub(r"(ˈ[^aeiou]*)e", r"\1ɛ", ipa, count=1)
                     if re.search(r"ˈ[^aeiou]*e", ipa)
                     else re.sub(r"(ˈ[^aeiou]*)o", r"\1ɔ", ipa, count=1), "开闭翻转"))
    # ③ 音段替换
    for a, b in (("t͡ʃ", "k"), ("ʃ", "s"), ("ʎ", "l"), ("d͡ʒ", "ɡ"), ("ɲ", "n"), ("z", "s")):
        if a in ipa:
            cand.append((ipa.replace(a, b, 1), f"音段 {a}→{b}"))
            break
    # ④ 去双辅音长化:C.C 同辅音 → 单写
    m = re.search(r"([bdfɡklmnprstv])\.\1", ipa)
    if m:
        cand.append((ipa[:m.start()] + "." + m.group(1) + ipa[m.end():], "去长辅音"))
    return [(v, k) for v, k in cand if v != ipa]


# ═════════════════════════════════════ 抽样
QUOTA = [
    ("kaikki原生·负控",      200),
    ("人工注入·正控",        200),
    ("规则·有重音形",        300),
    ("规则·无重音形",        450),
    ("规则算得出但不同",      200),
    ("豆包未知+小族",        150),
]
EXOTIC = re.compile(r"[øyəäxŋhɹɾɪɜɟg~,|]|ː")


def build_sample(n, seed):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT id, word, ipa, is_lemma, COALESCE(exchange,'') FROM dict "
                        "WHERE TRIM(COALESCE(ipa,''))<>''").fetchall()
    conn.close()
    print(f"全库有音标 {len(rows):,} 行,判定来源中…", flush=True)
    kk, amap = kaikki_util.sounds_and_accent_map(None)
    print(f"  kaikki 音位式 {len(kk):,} 词 / 重音形映射 {len(amap):,} 条", flush=True)

    pools = defaultdict(list)
    for rid, w, p, isl, exch in rows:
        base = ""
        for ln in (exch or "").split("\n"):
            if ln.strip():
                base = ln.split(":", 1)[-1].strip()
                break
        key = kaikki_util.unaccent(w)
        has_acc = key in amap
        rv = word_to_ipa(amap.get(key, w))
        rv = rv.strip("/") if rv else None
        rec = (rid, w, p, isl, base)
        if kk.get(w) == p:
            pools["kaikki原生·负控"].append(rec)
        elif rv is not None and rv == p:
            pools["规则·有重音形" if has_acc else "规则·无重音形"].append(rec)
        elif rv is not None:
            pools["规则算得出但不同"].append(rec)
        else:
            pools["豆包未知+小族"].append(rec)
        if EXOTIC.search(p):
            pools["豆包未知+小族"].append(rec)

    k = n / 1500
    picked, seen = [], set()
    for name, q in QUOTA:
        if name == "人工注入·正控":
            continue
        pool = [r for r in pools[name] if r[0] not in seen]
        random.seed(seed + sum(map(ord, name)))
        take = random.sample(pool, min(int(q * k), len(pool)))
        for r in take:
            seen.add(r[0])
        picked += [(*r, name, None) for r in take]
        print(f"  {name:16} 池 {len(pool):>7,} → 抽 {len(take):>4}", flush=True)

    # 正控:从**未被抽中的** kaikki 原生行里取,破坏后混入。
    # 四类**均衡取样**:挪重音几乎每条都做得到,开闭/音段/长辅音要词里有对应结构才行,
    # 直接 random.choice 会让挪重音占七成 —— 那样只测出对一类缺陷的敏感度。
    random.seed(seed + 4242)
    q = int(200 * k)
    per_kind = defaultdict(list)
    for r in random.sample(pools["kaikki原生·负控"], min(len(pools["kaikki原生·负控"]), q * 40)):
        if r[0] in seen:
            continue
        for bad, kind in corrupt(r[2]):
            per_kind[kind.split()[0]].append((r, bad, kind))
    inj, used = [], set()
    kinds = sorted(per_kind)
    while len(inj) < q and any(per_kind[k] for k in kinds):
        for kd in kinds:                       # 轮转,各类均摊
            if len(inj) >= q:
                break
            while per_kind[kd]:
                r, bad, kind = per_kind[kd].pop()
                if r[0] in used:
                    continue
                used.add(r[0]); seen.add(r[0])
                inj.append((r[0], r[1], bad, r[3], r[4], "人工注入·正控", (r[2], kind)))
                break
    picked += inj
    print(f"  {'人工注入·正控':16} 破坏成功 {len(inj):>4} 条(四类:"
          f"{dict(Counter(x[6][1] for x in inj))})", flush=True)

    random.seed(seed + 999)
    dups = random.sample(picked, max(1, int(len(picked) * 0.05)))
    picked = [(*r, False) for r in picked] + [(*r, True) for r in dups]
    random.shuffle(picked)
    print(f"共 {len(picked)} 条(含重复 {len(dups)} 条用于自噪标定)", flush=True)
    return picked      # (id, w, ipa, is_lemma, base, layer, inj, is_dup)


# ═════════════════════════════════════ 调用
def load_env():
    env = {}
    for ln in open(ENV, encoding="utf-8"):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def loads_lenient(s):
    """容错解析:去 ``` 围栏、掐首尾大括号、补条目间缺失逗号、去尾逗号。"""
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
    d = json.loads(r.text.lstrip())      # 坑:非流式等待期持续返回空行保活
    u = d.get("usage") or {}
    return d["choices"][0]["message"]["content"], (
        u.get("prompt_tokens", 0), u.get("completion_tokens", 0), u.get("prompt_cache_hit_tokens", 0))


async def run(tag, caller, sysp, batches, conc):
    """🔴 不做缓存预热(省 0.3 元不值一轮墙钟,且旧实现白烧一批、用量不入账)。"""
    out = [None] * len(batches)
    tk = [0, 0, 0]; done = [0]; fails = [0]
    sem = asyncio.Semaphore(conc)

    async def one(i, p):
        async with sem:
            delay = 3
            for att in range(4):
                try:
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
            if done[0] % 10 == 0 or done[0] == len(batches):
                print(f"    [{tag}] {done[0]}/{len(batches)} 输入 {tk[0]:,} 输出 {tk[1]:,}", flush=True)

    t0 = time.time()
    await asyncio.gather(*[one(i, p) for i, p in enumerate(batches)])
    print(f"  [{tag}] 完成 {time.time()-t0:.0f}s 失败批 {fails[0]}", flush=True)
    return out, tuple(tk), fails[0]


# ═════════════════════════════════════ 报告
def report(rows, res, metas):
    flags = {}
    for meta, out in zip(metas, res):
        for k, v in (out or {}).items():
            try:
                r = meta[int(k) - 1]
            except (ValueError, IndexError):
                continue
            if isinstance(v, dict):
                flags[(r[0], r[7])] = v

    # 空转闸:提议音标 == 给它看的那个值 → 判官自相矛盾(说它错又原样抄回),丢弃。
    # es 上关思考时这一族占 88%;开思考时占 5%。免费,且对两边一视同仁。
    shown = {(r[0], r[7]): r[2] for r in rows}
    echo = {k for k, v in flags.items()
            if str(v.get("ipa", "")).strip() == shown[k].strip()}
    kept = {k: v for k, v in flags.items() if k not in echo}

    per = defaultdict(lambda: [0, 0])
    codes = Counter()
    for r in rows:
        per[r[5]][0] += 1
        if (r[0], r[7]) in kept:
            per[r[5]][1] += 1
            codes[str(kept[(r[0], r[7])].get("c", "?"))[:1]] += 1

    print(f"\n{'='*72}\n标出率 × 来源层(已丢弃空转 {len(echo)} 条)\n{'='*72}")
    print(f"{'层':20}{'样本':>7}{'标出':>7}{'标出率':>9}")
    for name, _ in QUOTA:
        s, f = per.get(name, [0, 0])
        print(f"{name:20}{s:>7}{f:>7}{100*f/max(s,1):>8.1f}%")

    neg, pos = per.get("kaikki原生·负控", [0, 0]), per.get("人工注入·正控", [0, 0])
    nr = 100 * neg[1] / max(neg[0], 1)
    pr = 100 * pos[1] / max(pos[0], 1)
    print(f"\n  负控(kaikki原文) {nr:.1f}%   正控(人工注入的已知缺陷) {pr:.1f}%   差 {pr-nr:+.1f}pp")
    print("  → " + ("这位专家有分辨力,可用于定位缺陷族" if pr - nr >= 25 else
                    "🔴 正负控没拉开,本轮意见不可用,别看下面的族"))

    # 正控召回率按破坏类型拆
    byk = defaultdict(lambda: [0, 0])
    for r in rows:
        if r[5] != "人工注入·正控" or r[7]:
            continue
        byk[r[6][1]][0] += 1
        if (r[0], r[7]) in kept:
            byk[r[6][1]][1] += 1
    if byk:
        print("\n  正控召回率(按破坏类型):")
        for k, (s, f) in sorted(byk.items()):
            print(f"    {k:12}{f:>4}/{s:<4} = {100*f/max(s,1):5.1f}%")

    dup_ids = {r[0] for r in rows if r[7]}
    if dup_ids:
        ag = sum(((i, False) in kept) == ((i, True) in kept) for i in dup_ids)
        print(f"\n  自噪:重复 {len(dup_ids)} 组,两次一致 {ag} = {100*ag/len(dup_ids):.0f}%")
    print("\n  字母码: " + "  ".join(f"{c}{LAB.get(c,c)} {n}" for c, n in codes.most_common()))
    return kept, echo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--chunk", type=int, default=25)
    ap.add_argument("--conc", type=int, default=8)
    ap.add_argument("--seed", type=int, default=801)
    a = ap.parse_args()

    rows = build_sample(a.n, a.seed)
    metas, batches = [], []
    for j in range(0, len(rows), a.chunk):
        sub = rows[j:j + a.chunk]
        b = {}                       # ⚠️ 本地键 '1'..'N';用全局唯一键模型会重编号
        for i, r in enumerate(sub, 1):
            d = {"w": r[1], "ipa": r[2]}
            if r[4] and r[4] != r[1]:
                d["base"] = r[4]
            b[str(i)] = d
        batches.append(b); metas.append(sub)
    print(f"切 {len(batches)} 批 × {a.chunk}", flush=True)

    stats = ("- 音标总条数 584,460;其中 82,973 条与 Wiktionary 人工音标逐字相同\n"
             "- 由上述规则生成的 498,070 条(85.2%)\n"
             "- 规则生成时,63.1% 的词拿到了带重音标注的拼写形,36.9% 没有、按无标注默认处理\n"
             "- 拿 83,004 个有人工音标可对照的词重跑本规则:逐字相同 46,825 条(56.4%)\n"
             "    其中拿到重音标注形的 28,184 词一致率 82.3%,未拿到的 54,728 词一致率 43.2%\n"
             "- 不一致处最多的几类:音段不同 11,199;重音或音节切分不同 10,942;\n"
             "    开/闭元音不同 6,741;开闭与重音同时不同 7,205\n"
             "- 音标中出现音节点 . 的 1,440,642 处;次重音 ˌ 4,102 处")
    random.seed(a.seed)
    ex = random.sample([r for r in rows if not r[7] and r[5] != "人工注入·正控"], 60)
    sys_rules = (SYS_RULES.replace("{STATS}", stats)
                 .replace("{EXAMPLES}", "\n".join(f"  {r[1]} → {r[2]}" for r in ex)))

    env = load_env()
    RUNS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    rowmeta = [{"id": r[0], "w": r[1], "ipa": r[2], "base": r[4],
                "layer": r[5], "inj": r[6], "dup": r[7]} for r in rows]

    def dump(ra, rb, tka, tkb):
        """🔴 每个任务跑完立刻落盘,数据任务不等规则任务。"""
        p = RUNS / f"blind_ipa_{stamp}_v4pro.json"
        p.write_text(json.dumps({"stamp": stamp, "n": len(rows), "seed": a.seed,
                                 "quota": dict(QUOTA), "rows": rowmeta,
                                 "raw_data": ra, "raw_rules": rb,
                                 "tokens": {"数据": tka, "规则": tkb}}, ensure_ascii=False),
                     encoding="utf-8")
        print(f"  已落盘 → {p.name}", flush=True)

    async def go():
        import httpx
        cl = httpx.AsyncClient(timeout=httpx.Timeout(900.0))
        key = env["DEEPSEEK_API_KEY"]
        c = lambda s, p: call_v4pro(cl, key, s, p)
        print("\n─── v4-pro 数据任务 ───", flush=True)
        ra, tka, _ = await run("数据", c, SYS_DATA, batches, a.conc)
        dump(ra, None, tka, (0, 0, 0))
        print("\n─── v4-pro 规则评审 ───", flush=True)
        rb, tkb, _ = await run("规则", c, sys_rules, [{"go": 1}], 1)
        await cl.aclose()
        dump(ra, rb, tka, tkb)
        return ra, rb, tka, tkb

    ra, rb, tka, tkb = asyncio.run(go())
    report(rows, ra, metas)
    rev = ((rb[0] if rb else None) or {}).get("issues", [])
    print(f"\n对约定本身提出 {len(rev)} 条质疑:")
    for it in rev:
        print(f"  ◆[{it.get('conf','?')}] {str(it.get('rule',''))[:60]}")
        print(f"     why  {str(it.get('why',''))[:100]}")
        print(f"     fix  {str(it.get('fix',''))[:100]}")
        print(f"     例词 {', '.join(map(str, it.get('cases', [])))[:90]}")
    # 计价:官方基准 命中0.025/未命中3/输出6 元每M;高峰(9-12,14-18 北京时间)全项×2
    h = time.localtime().tm_hour
    x = 2.0 if h in set(range(9, 12)) | set(range(14, 18)) else 1.0
    pin, cout, hit = (tka[0] + tkb[0], tka[1] + tkb[1], tka[2] + tkb[2])
    cost = x * (hit * 0.025 + (pin - hit) * 3.0 + cout * 6.0) / 1e6
    print(f"\ntoken 入 {pin:,}(命中 {hit:,}) 出 {cout:,}   "
          f"实付 ≈ {cost:.2f} 元({'高峰×2' if x > 1 else '平峰'})")


if __name__ == "__main__":
    main()
