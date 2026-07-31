#!/usr/bin/env python3
"""es 独立复验：拿 deepseek-v4-pro 当第二判官，抽检**释义**与**音标**。见对话 2026-07-31。

为什么再验一遍(库已判"服务级收尾完结"):
  ① 原 qa_report 全是**豆包判豆包自己写的译文** —— 违反"谁写的不能由谁判"。
     换一家判官(v4-pro)才是独立复核,数字才有意义。
  ② en 那边昨天的教训:判据命令"从宽、拿不准判 ok"会**放过空壳**,标尺比被测物宽就测不出东西。
     这里的判据写死了要看错位/空壳/漏译,不给"从宽"的口子。
  ⚠️ 但据此产生的 bad 率**不能和 es 历史 qa_report 的数字相减** —— 换了判官又换了判据,
     两个自变量都动了。此轮数字只与自己的分层横向比、以及与其他语种同判据的跑次比。

⭐ 分层而不是纯随机。es 库 767k = 10.5万 lemma(豆包写的中文) + 66.2万 变形(infl_compose
   确定性拼的语法说明)。这两层的**缺陷机理完全不同**,混在一起算平均数没有任何可操作性:
   - lemma 层问的是"中文译得对不对、跟 gloss 有没有错位";
   - 变形层问的是"原形指对没有、变形类型标对没有"(即 clitic/复合词 gloss 缺陷那一族)。
   故两层用**两套判据、分开出数**,绝不合并成一个总 bad 率。

音标同理分层:纯随机 3000 抽不到已知可疑族(含拉丁字母残留全库才 324 条),
   而它们恰恰是缺陷所在 —— 分层保证每族有足够样本量能算出比例(见下 IPA_STRATA 注释)。

🔴 **必须开思考模式**(THINK=True)。这和 en 那边"一律关思考"的惯例相反,因为任务性质不同:
   en 的判官是读中文译文顺不顺 —— "阅读"任务,关思考够用且省钱;
   es 这三个判官要**真的去变位、真的去转写** —— "推导"任务,关了思考就没有推导的地方。
   2026-07-31 负控实测(人工塞入已知缺陷,同一输入连跑三次,temperature=0):
     判官     关思考                                     开思考
     lemma   5/5,但更早一次整批返回 {}                   5/5,三次全稳
     变形    **0/2,三次全 0**(comes 说成 comprar 的      2/2,三次全稳
             变形都照样放过)
     音标    0→1→3 /4,**三次结果各不相同**              4/4,三次全稳
   关思考时输出恒为 1 token(`{}`)—— 模型直接摆烂。这种判官报出来的 0% 缺陷率是假的。
   ⚠️ 教训:换判据/换语种/换模型后**必须先跑负控**(塞已知缺陷看抓不抓得到)再信数字。
     标尺没校准就去量,量出来的 0% 只说明尺子是坏的。负控脚本见 git 历史/对话记录。

⚠️ DeepSeek 两个坑(和 en 那边同源,这里重述以免本文件被单独拿走后失传):
   ① 非流式请求等待期**持续返回空行**保活 → 解析前要容忍前导空白;
   ② JSON Output 要求 prompt 里含 "json" 字样 —— 三个 SYS 里都有 "JSON",满足。
   走原生 REST(httpx),不为它装 openai SDK。
   (第三个坑"思考默认 enabled"在别处要显式关掉,这里反而是要的,别顺手关了。)

read-only,不写库。用法(在 es/ 目录):
  python3 verify_v4pro.py --qa 3000            # 释义(lemma 判据 + 变形判据,分层)
  python3 verify_v4pro.py --ipa 3000           # 音标
  python3 verify_v4pro.py --qa 100 --conc 8    # 调判据时的小跑
"""
import argparse, asyncio, json, random, re, sqlite3, time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-es.sqlite"
ENV = HERE.parent / ".env"
RUNS = HERE / "runs"
MODEL = "deepseek-v4-pro"
THINK = True      # 🔴 见文件头负控表,关掉会让判官摆烂返回 {}。除非重跑负控证明没问题,不要改。

# ---------------------------------------------------------------- 判据

# lemma 释义判据。zh 与 gloss 是**等长对齐数组**(一行一义项),错位曾是本库的真实缺陷族
# (fix_misalign.py 修过 678 条),所以判官必须逐位对齐着看,而不是整体读个大意。
QA_LEMMA_SYS = """你是资深西班牙语→简体中文词典审校专家。给你一批西语词条,每条含:
  w      西语词形
  pos    词性
  gloss  英文释义数组(来自 Wiktionary,是**义项的定义**,可信度高但偶有小误)
  zh     待审的中文译文数组  ← **只判这个**

⚠️ zh 与 gloss **等长、逐位对应**:zh[i] 是 gloss[i] 那个义项的中文。请**逐位对齐着看**,
   不要只读个整体大意 —— 顺序错位(zh[1] 其实是 gloss[2] 的意思)是本词典的已知缺陷族。

**分两步,顺序不能颠倒**:
  第一步(决定去留):作为词典条目,这条 zh **能不能用**?
     能用 —— 就**不要把它列进输出**,到此为止,不要去想它属于哪个分类。
  第二步(只对判了"不能用"的):给一个字母码说明错在哪,归不进具体类别就标 W。

字母码:
A 错位:zh 与 gloss 逐位对不上(zh[2] 明显是 gloss[3] 的意思、或整体错开一位)。
W 错译:某个义项意思不对、张冠李戴、或漏掉该义项最主要的意思。
M 数量不符:zh 与 gloss 长度不等,或某项是空的/占位的。
P 词性错配:译文的词性与 pos 或该义项不符(动词义译成名词、形容词义译成动词)。
X 空壳:zh 没给出词义,只说"是某词的变体/异写/缩写"之类的元描述。
G 乱码或读不通:机翻残片、字符堆、半个词、或**压根没有汉字**(只有西文/英文)。

**以下一律视为无缺陷,不要列出**:
- 词条生僻、专业、古旧、方言、粗俗 —— 只要译得对;
- 译文简短朴素、或用直译,只要意思对;
- 人名/地名/学名的合理音译或通行译名;
- 给了多个并列近义译名(用、或,分隔);
- gloss 本身写得含糊而 zh 取了其中一个合理解读;
- 缺词性前缀、缺标点这类纯格式小瑕。

宁可漏报,不要为了填满分类而硬报 —— 拿不准就不列出该条。
严格输出 JSON,只含有缺陷的条目,键与输入一致,值为 {"c":"字母码","why":"15字以内中文"}:
{"3":{"c":"A","why":"整体错开一位"},"7":{"c":"W","why":"误作医学义"}}
全部无缺陷则输出 {}。不要任何解释文字。"""

# 变形层判据。这一层的 zh 是确定性拼出来的**语法说明**(不是词义),
# 判它"译得好不好"没有意义 —— 只能判"指对了没有"。故单开一套判据。
QA_INFL_SYS = """你是西班牙语形态学专家。给你一批西语**变形词形**,每条含:
  w    实际词形
  zh   词典给这个词形的说明,格式是「原形 的 语法标签」(一行一条,可能多条)

这一层不是词义翻译,**只判形态关系对不对**:w 真的是所说原形的所说变形吗?

字母码:
L 原形错:w 根本不是该原形的任何变形(如说 comes 是 comprar 的变形)。
R 变形类型错:原形对,但语法标签错(说是虚拟式其实是陈述式、说是复数其实是单数、人称/时态标错)。
G 乱码或读不通:标签是残片、原形带乱码符号、或整条读不成话。

**以下一律视为无缺陷,不要列出**:
- 一个词形同时是多个词的变形,列了多条 —— 这是正确做法,不是缺陷;
- 标签用「第一/三人称」这种合并写法;
- 原形是生僻词、古词、方言词、专有名词;
- 只写了语法关系没给中文词义 —— 这一层**本来就**只给语法关系,不是空壳;
- voseo、命令式否定形等区域性/边缘形态,只要标注合理。

宁可漏报。严格输出 JSON,只含有缺陷的条目,键与输入一致,值为 {"c":"字母码","why":"15字以内中文"}:
{"4":{"c":"R","why":"应为陈述式非虚拟式"}}
全部无缺陷则输出 {}。不要任何解释文字。"""

# 音标判据。库内 phonetic **存裸**(不带斜杠),展示层再加 /.../,所以喂给判官的也是裸串,
# 判官不该因为"没有斜杠"而报错 —— 提示里点明。
IPA_SYS = """你是西班牙语语音学专家。审核一个**中文用户划词弹窗**里显示的西语音标。

每条给你:
  w    西语词形
  ipa  该词的音标(**裸串,不带斜杠** —— 展示层才加 /.../,缺斜杠不是缺陷,不要报)

本词典采用**半岛(Castilian)音位式**转写约定:
  c(e/i)、z、ç → θ    ll、y → ʝ    j 及 g(e/i) → x
  词中单 r → ɾ,rr / 词首 r → r    b/v → b(词间可作 β)    h 不发音(不出现在音标里)
  主重音标 ˈ,标在**重读音节之前**

只挑**有问题的**条目列出,每条给一个字母码 + 建议的正确形式:
  A 音位错:该 θ 写成了 s、该 b 写成了 v、该 x 写成了 h/j、ɾ 与 r 混用等。
  B 重音错:ˈ 位置不对,或多音节词整条没有 ˈ。
  C 拼写残留:音标里混进了未转写的**西语正字法字母**(如 ck、qu、h、c 在 θ/k 位置、v),
    看起来是把词形原样抄了一段而不是转写。
  D 整体读错:与该词实际读音明显不符(元音/辅音串对不上词形)。
  E 其他。

⚠️ 以下**不要列出**:
- 音标正确、只是词生僻/专业/是外来词或专有名词;
- 单音节词或虚词(如 a、de、en、y)没标 ˈ —— 正常,不是 B;
- 多词短语音标中间有空格 —— 正常;
- 拉美音(seseo/yeísmo)与半岛音的风格差异本身不算错,本词典按半岛音;
- w 作半元音(如 cuando → ˈkwando)、j 作半元音(如 hay → ˈai / bien → ˈbjen) —— 正常,不是 C。

宁可漏报不要凑数。严格输出 JSON,只含有问题的条目,键与输入一致:
{"3":{"c":"A","ipa":"建议的正确音标","why":"12字以内"},"7":{"c":"C","ipa":"…","why":"…"}}
没问题的条目**不要出现在输出里**。全部没问题则输出 {}。"""

LAB_QA = {"A": "错位", "W": "错译", "M": "数量不符", "P": "词性错配",
          "X": "空壳", "G": "乱码", "L": "原形错", "R": "变形类型错"}
LAB_IPA = {"A": "音位错", "B": "重音错", "C": "拼写残留", "D": "整体读错", "E": "其他"}

# ---------------------------------------------------------------- 分层

NOTEMPTY = "TRIM(COALESCE(translation,''))<>''"
HASIPA = "TRIM(COALESCE(phonetic,''))<>''"

# 释义分层:核心/尾巴/变形。核心词池才 1.6 万但**用户命中率最高**,必须单列出数,
# 不能被 8.9 万尾巴的数字稀释(尾巴多是生僻词,错了用户也碰不到)。
QA_STRATA = [
    ("lemma核心A1-B1", f"is_lemma=1 AND {NOTEMPTY} AND level IN ('A1','A2','B1')", 0.30, "lemma"),
    ("lemma尾巴B2-C2", f"is_lemma=1 AND {NOTEMPTY} AND level IN ('B2','C1','C2')", 0.50, "lemma"),
    ("变形层",         f"is_lemma=0 AND {NOTEMPTY}",                               0.20, "infl"),
]

# 音标分层。后四族是**已知可疑族**,全库总量才几百条,纯随机一条都抽不到;
# 按固定条数(不是比例)抽满,才能对每族单独算出缺陷比例。池不足则全取。
IPA_STRATA = [
    ("lemma核心",     f"is_lemma=1 AND {HASIPA} AND level IN ('A1','A2','B1')", 0.20),
    ("lemma尾巴",     f"is_lemma=1 AND {HASIPA} AND level IN ('B2','C1','C2')", 0.20),
    ("变形层G2P",     f"is_lemma=0 AND {HASIPA}",                               0.30, ),
    ("疑符cqv残留",   f"{HASIPA} AND phonetic GLOB '*[cqv]*'",                   0.10),
    ("无重音符",      f"{HASIPA} AND phonetic NOT LIKE '%ˈ%'",                   0.07),
    ("多词含空格",    f"{HASIPA} AND phonetic LIKE '% %'",                       0.07),
    ("其余随机",      f"{HASIPA}",                                               0.06),
]


def sample(strata, n, seed, cols):
    """按分层抽样,先到先得去重(靠前的层优先占有交叉条目,可疑族排在后面故不被抢)。"""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    picked, seen = [], set()
    for st in strata:
        name, cond, frac = st[0], st[1], st[2]
        kind = st[3] if len(st) > 3 else ""
        rows = conn.execute(f"SELECT {cols} FROM dict WHERE {cond}").fetchall()
        rows = [r for r in rows if r[0] not in seen]
        random.seed(seed + sum(map(ord, name)))
        take = random.sample(rows, min(int(n * frac), len(rows)))
        for r in take:
            seen.add(r[0])
        picked += [(*r, name, kind) for r in take]
        print(f"  {name:14} 池 {len(rows):>7,} → 抽 {len(take):>4}", flush=True)
    conn.close()
    random.shuffle(picked)
    return picked


# ---------------------------------------------------------------- 调用

def load_env():
    env = {}
    for ln in open(ENV, encoding="utf-8"):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def loads_lenient(s):
    """容错解析:去 ```json 围栏、掐到首尾大括号、补条目间缺失的逗号、去尾逗号。"""
    s = s.strip()
    s = re.sub(r"^```(json)?|```$", "", s, flags=re.M).strip()
    if "{" in s:
        s = s[s.find("{"):s.rfind("}") + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        f = re.sub(r'}\s*\n\s*(")', r'},\n\1', s)
        f = re.sub(r'}\s+(")', r'}, \1', f)
        f = re.sub(r',\s*([}\]])', r'\1', f)
        return json.loads(f)


async def ds_call(cl, key, sysp, payload):
    r = await cl.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": MODEL,
              "messages": [{"role": "system", "content": sysp},
                           {"role": "user",
                            "content": "输入:\n" + json.dumps(payload, ensure_ascii=False)}],
              "temperature": 0,                                  # 判官是分类任务,贪心解码
              "response_format": {"type": "json_object"},
              "thinking": {"type": "enabled" if THINK else "disabled"},   # 🔴 见文件头
              "stream": False})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    d = json.loads(r.text.lstrip())                               # 坑② 前导空行保活
    u = d.get("usage") or {}
    return (d["choices"][0]["message"]["content"],
            (u.get("prompt_tokens", 0), u.get("completion_tokens", 0),
             u.get("prompt_cache_hit_tokens", 0)))


async def run_job(name, sysp, batches, key, conc):
    """跑一组同判据的批次,返回 (results, 输入tok, 输出tok, 缓存命中, 失败批数)。"""
    import httpx
    cl = httpx.AsyncClient(timeout=httpx.Timeout(900.0))
    out = [None] * len(batches)
    tk = [0, 0, 0]; done = [0]; fails = [0]
    # ⭐ 缓存预热:系统提示每批相同,但并发一起发时开局全部未命中(会白付一整轮全价)。
    #   先单发一发把前缀缓存建起来,再放并发。
    try:
        await ds_call(cl, key, sysp, batches[0])
        print(f"  [{name}] 预热完成", flush=True)
    except Exception as e:
        print(f"  [{name}] 预热失败(不影响主跑): {type(e).__name__}", flush=True)

    sem = asyncio.Semaphore(conc)

    async def one(i, p):
        async with sem:
            delay = 3
            for att in range(4):
                try:
                    txt, (pi, co, hi) = await ds_call(cl, key, sysp, p)
                    tk[0] += pi; tk[1] += co; tk[2] += hi
                    out[i] = loads_lenient(txt)
                    break
                except Exception as e:
                    if att == 3:
                        fails[0] += 1
                        print(f"    ✗ [{name}] 批{i} {type(e).__name__}: {str(e)[:100]}", flush=True)
                    else:
                        await asyncio.sleep(delay); delay = min(delay * 2, 30)
            done[0] += 1
            if done[0] % 20 == 0 or done[0] == len(batches):
                print(f"    [{name}] {done[0]}/{len(batches)}  输入 {tk[0]:,}"
                      f"(命中 {tk[2]:,}) 输出 {tk[1]:,}", flush=True)

    t0 = time.time()
    await asyncio.gather(*[one(i, p) for i, p in enumerate(batches)])
    await cl.aclose()
    print(f"  [{name}] 完成 {time.time()-t0:.0f}s", flush=True)
    return out, tk[0], tk[1], tk[2], fails[0]


def chunked(rows, size, build):
    """切批 + 构造 payload。返回 (metas, batches),每批用本地键 '1'..'N'。
    ⚠️ 不能用全局唯一键 —— 模型会把 '20_1' 重编号成 '1',全局键必错配。"""
    metas, batches = [], []
    for j in range(0, len(rows), size):
        sub = rows[j:j + size]
        batches.append({str(k): build(r) for k, r in enumerate(sub, 1)})
        metas.append(sub)
    return metas, batches


def cost(pin, cout, hit):
    """v4-pro 计价(元/M token):命中 0.2 / 未命中 4 / 输出 12。粗算,用于判断值不值得放全量。"""
    return (hit * 0.2 + (pin - hit) * 4.0 + cout * 12.0) / 1e6


def report(title, recs, total, lab, codec):
    print(f"\n===== {title}:{total} 条,标出 {len(recs)} 条 "
          f"({100*len(recs)/max(total,1):.2f}%) =====")
    for ch, cnt in codec.most_common():
        print(f"    {ch} {lab.get(ch,ch):<10} {cnt:>4}  "
              f"({100*cnt/max(total,1):5.2f}% of 样本)")


# ---------------------------------------------------------------- 释义

def qa(n, seed, conc, chunk):
    rows = sample(QA_STRATA, n, seed,
                  "id, word, COALESCE(pos,''), COALESCE(definition,''), translation, "
                  "COALESCE(level,''), is_lemma")
    print(f"共 {len(rows)} 条", flush=True)
    lem = [r for r in rows if r[8] == "lemma"]
    inf = [r for r in rows if r[8] == "infl"]

    def b_lem(r):
        return {"w": r[1], "pos": r[2],
                "gloss": [x for x in r[3].split("\n") if x.strip()][:12],
                "zh": [x for x in r[4].split("\n") if x.strip()][:12]}

    def b_inf(r):
        return {"w": r[1], "zh": [x for x in r[4].split("\n") if x.strip()][:8]}

    m_lem, b1 = chunked(lem, chunk, b_lem)
    m_inf, b2 = chunked(inf, chunk, b_inf)
    print(f"  → lemma {len(lem)} 条 / {len(b1)} 批;变形 {len(inf)} 条 / {len(b2)} 批", flush=True)
    key = load_env()["DEEPSEEK_API_KEY"]

    async def go():
        return await asyncio.gather(
            run_job("lemma", QA_LEMMA_SYS, b1, key, conc) if b1 else _nil(),
            run_job("变形", QA_INFL_SYS, b2, key, conc) if b2 else _nil())

    (r1, p1, c1, h1, f1), (r2, p2, c2, h2, f2) = asyncio.run(go())

    recs, per = [], {}
    for tag, metas, res in (("lemma", m_lem, r1), ("infl", m_inf, r2)):
        for meta, out in zip(metas, res or []):
            failed = out is None
            out = out or {}
            for k, r in enumerate(meta, 1):
                st = r[7]
                per.setdefault(st, Counter())["n"] += 1
                if failed:
                    per[st]["novote"] += 1
                    continue
                v = out.get(str(k))
                if not isinstance(v, dict):
                    continue
                ch = str(v.get("c", "W"))[:1].upper()
                per[st][ch] += 1; per[st]["bad"] += 1
                # ⚠️ level 是 r[5];r[6] 是 is_lemma(2026-07-31 修过一次错位)
                recs.append(dict(id=r[0], w=r[1], pos=r[2], level=r[5], layer=tag, strat=st,
                                 c=ch, why=str(v.get("why", ""))[:40],
                                 zh=r[4].replace("\n", " ǀ "),
                                 gloss=r[3].replace("\n", " ǀ ")[:300]))

    RUNS.mkdir(exist_ok=True)
    outp = RUNS / f"qa_v4pro_{len(rows)}_{time.strftime('%Y%m%d-%H%M')}.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(_meta=True, job="qa", model=MODEL, n=len(rows), seed=seed,
                                strata={k: dict(v) for k, v in per.items()},
                                prompt_tokens=p1 + p2, completion_tokens=c1 + c2,
                                cache_hit=h1 + h2, fails=f1 + f2), ensure_ascii=False) + "\n")
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n" + "=" * 74)
    print("释义复验 · deepseek-v4-pro  ⚠️ 两层判据不同,**不要合并成一个总 bad 率**")
    print("=" * 74)
    for name, _, _, kind in QA_STRATA:
        c = per.get(name, Counter())
        tot, bad, nv = c["n"], c["bad"], c["novote"]
        eff = tot - nv
        print(f"\n  【{name}】{tot} 条(有效 {eff})  缺陷 {bad} 条 = {100*bad/max(eff,1):.2f}%")
        for ch, cnt in sorted(((k, v) for k, v in c.items()
                               if k not in ("n", "bad", "novote")),
                              key=lambda x: -x[1]):
            print(f"      {ch} {LAB_QA.get(ch,ch):<10} {cnt:>4} ({100*cnt/max(eff,1):5.2f}%)")
        if nv:
            print(f"      novote {nv}")
    pin, cout, hit = p1 + p2, c1 + c2, h1 + h2
    print(f"\n  token 输入 {pin:,}(命中 {hit:,}) 输出 {cout:,}   实付 ≈ {cost(pin,cout,hit):.2f} 元")
    print(f"  → {outp.relative_to(HERE.parent)}")


async def _nil():
    return [], 0, 0, 0, 0


# ---------------------------------------------------------------- 音标

def ipa(n, seed, conc, chunk):
    rows = sample(IPA_STRATA, n, seed,
                  "id, word, phonetic, COALESCE(level,''), is_lemma")
    print(f"共 {len(rows)} 条", flush=True)
    metas, batches = chunked(rows, chunk, lambda r: {"w": r[1], "ipa": r[2]})
    print(f"  → {len(batches)} 批 × {chunk}", flush=True)
    key = load_env()["DEEPSEEK_API_KEY"]
    res, pin, cout, hit, fails = asyncio.run(run_job("ipa", IPA_SYS, batches, key, conc))

    recs, per = [], {}
    for meta, out in zip(metas, res):
        failed = out is None
        out = out or {}
        for k, r in enumerate(meta, 1):
            st = r[5]
            per.setdefault(st, Counter())["n"] += 1
            if failed:
                per[st]["novote"] += 1
                continue
            v = out.get(str(k))
            if not isinstance(v, dict):
                continue
            ch = str(v.get("c", "E"))[:1].upper()
            per[st][ch] += 1; per[st]["bad"] += 1
            recs.append(dict(id=r[0], w=r[1], ipa=r[2], level=r[3], is_lemma=r[4], strat=st,
                             c=ch, sug=str(v.get("ipa", ""))[:60],
                             why=str(v.get("why", ""))[:40]))

    RUNS.mkdir(exist_ok=True)
    outp = RUNS / f"ipa_v4pro_{len(rows)}_{time.strftime('%Y%m%d-%H%M')}.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(_meta=True, job="ipa", model=MODEL, n=len(rows), seed=seed,
                                strata={k: dict(v) for k, v in per.items()},
                                prompt_tokens=pin, completion_tokens=cout,
                                cache_hit=hit, fails=fails), ensure_ascii=False) + "\n")
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n" + "=" * 74)
    print("音标复验 · deepseek-v4-pro   ⚠️ 后四族是**定向超采的可疑族**,")
    print("   其比例只代表该族自身,不能当全库比例;全库估计看前三族。")
    print("=" * 74)
    for st in IPA_STRATA:
        name = st[0]
        c = per.get(name, Counter())
        tot, bad, nv = c["n"], c["bad"], c["novote"]
        eff = tot - nv
        print(f"\n  【{name}】{tot} 条(有效 {eff})  标出 {bad} 条 = {100*bad/max(eff,1):.2f}%")
        for ch, cnt in sorted(((k, v) for k, v in c.items()
                               if k not in ("n", "bad", "novote")),
                              key=lambda x: -x[1]):
            print(f"      {ch} {LAB_IPA.get(ch,ch):<10} {cnt:>4} ({100*cnt/max(eff,1):5.2f}%)")
        if nv:
            print(f"      novote {nv}")
    print(f"\n  token 输入 {pin:,}(命中 {hit:,}) 输出 {cout:,}   实付 ≈ {cost(pin,cout,hit):.2f} 元")
    print(f"  → {outp.relative_to(HERE.parent)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", type=int, metavar="N", help="释义抽检条数")
    ap.add_argument("--ipa", type=int, metavar="N", help="音标抽检条数")
    ap.add_argument("--seed", type=int, default=20260731)
    ap.add_argument("--conc", type=int, default=24)
    ap.add_argument("--chunk", type=int, default=20)
    a = ap.parse_args()
    if a.qa:
        qa(a.qa, a.seed, a.conc, a.chunk)
    elif a.ipa:
        ipa(a.ipa, a.seed, a.conc, a.chunk)
    else:
        ap.print_help()
