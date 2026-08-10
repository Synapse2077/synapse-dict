#!/usr/bin/env python3
"""给只有长定义的义项生成**短对应词**（≤10 字）。2026-08-07。

═══ 为什么需要它 ═══
`sense` 表 328,665 条义项里，**172,617 条只有长定义、没有短对应词**：

    ojo #7  （用于几何）任何与眼睑开口可见的眼部相似的平面几何形状，类似两端尖的椭圆

划词弹窗里这样的条目扫不动。`ojo` 有 25 条义项，只有 4 条带短标签。

⭐ 这个需求是 v4-pro 在义项归并评审里点出来的（2026-08-07）：
   「把子定义做成**极短的义项标签**，每一条控制在十字以内 ——
     （生理）眼，视觉器官 / （引申）眼状装置 / （解剖）眼珠；虹膜 / （几何）两端尖的椭圆状」
   它比义项层级更能解决「高频词义项滚不动」：层级只把 ojo 的 29 条压到 22 条，
   短标签让 25 条都能一眼扫过。

═══ 不是翻译，是**压缩** ═══
中文已经有了（长定义），要的是从中提炼出词典体例的对应词。所以：
  · 输入喂**西语原文 + 已有中文长定义**（两者互校，防止从译文的译文再退化一层）
  · 喂**同一个词其他义项已有的短标签**，避免产出「眼睛」×4 这种看着像重复条目的结果
  · 领域标记不要写进标签（`（用于几何）` 那部分已经在 `sense_tag` 里，展示层单独渲染）

═══ 落点 ═══
`sense_gloss(sense_id, lang='zh', kind='equivalent', seq=0)`，`src='llm-label-<模型>'`。
**只填空不覆盖**（[[replay-scripts-undo-fixes]]）：已有 zh/equivalent 的义项一律不碰。

用法（在仓库根）：
    python3 -m es.pipeline.gen_sense_labels --sample 200            # 出样本，不发请求
    python3 -m es.pipeline.gen_sense_labels --sample 200 --model both --ask
    python3 -m es.pipeline.gen_sense_labels --all --model flash --ask --apply
"""
import argparse
import asyncio
import collections
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

RAW = paths.WORK / "sense_labels_llm.jsonl"
# ⚠️ flash 的输出上限比另两家小，40 条一块会截断成半个 JSON（实测 200 条丢 40）。
#    按模型给不同块大小，别为了"统一"让最便宜的那家掉链子。
CHUNK = {"flash": 20, "v4pro": 40, "doubao": 40}
PAR = 12

SYS = """你是双语词典（西班牙语→中文）的资深编纂者。给每条义项写一个**短对应词**。

输入每条含：w 词形 / pos 词性 / es 西语单语定义 / zh 已有的中文长释义 /
            sibs 该词其他义项已有的短对应词（避免与它们雷同）

输出 label：该义项的中文对应词，规则：
 · **≤10 个汉字**，越短越好。是词典里加粗的那一行，不是解释。
   「任何与眼睑开口可见的眼部相似的平面几何形状」→「眼状形」
   「锁芯中插入钥匙的孔洞」→「锁眼；钥匙孔」
   「桥墩或桥基之间的空间」→「桥孔」
 · 多个近义对应词用中文分号「；」隔开，最多 2 个。

 · 🔴 **专名必须带范畴词**，光写音译等于没写。用户看到「莱菲尔」不知道那是什么：
     姓氏      Lefil「莱菲尔」        → 「莱菲尔（姓氏）」
     人名      Igor「伊戈尔」         → 「伊戈尔（男名）」
     行政区    Salto「萨尔托」        → 「萨尔托县」（定义说它是"党/县"就写县，是市就写市）
     地点      Bílbilis「比尔比利斯」  → 「比尔比利斯古城」
     舞曲/乐种  farruca「法鲁卡」      → 「法鲁卡舞曲」
     动植物    deinoterio            → 「恐象」（已是范畴名，不必再加）
   范畴词从**定义里取**，别自己猜：定义说 Apellido 就写「（姓氏）」，
   说 Ciudad 就写「…市」，说 Nombre de pila de varón 就写「（男名）」。

 · 🔴 **但不要写领域标记**：不要「（用于几何）」「（转喻）」「（用于人）」这类前缀 ——
   它们说的是**这条义项属于哪个领域**，已单独存储。
   两者的区别：范畴词回答「它是什么东西」（姓氏、县、舞曲），领域标记回答
   「这个义项用在哪个领域」（几何、扑克、医学）。前者进标签，后者不进。
 · 🔴 **不要与 sibs 雷同**。同一个词的不同义项必须能互相区分 ——
   若已有「眼睛」，这条就不能再写「眼睛」，要写出区别（「眼珠；虹膜」「眼状装置」）。

 · 🔴 **译「定义说的那个意思」，不是这个词的本义。** 定义描述的若是引申义、比喻义，
   标签就必须是引申义，写成本义是错的：
     kriptonita  定义「任何削弱某人自然能力或技能的物质或事物」
                 ✅「克星；致命弱点」   ❌「氪石」（那是字面物质，定义说的不是它）
     palo        定义「（口语）一百万，尤指钱」
                 ✅「一百万（钱）」     ❌「棍子」

 · 🔴 **先找汉语里现成的说法，别自己拼词组。** 汉语有成语、有行话，用它们：
     「经常且琐碎地挑剔缺陷的」  ✅「吹毛求疵的」   ❌「挑剔的」（弱）「爱挑剔的」（拼的）
     「暴饮暴食至胃部过度饱胀」  ✅「暴饮暴食」     ❌「暴食暴饮」（成语不能倒装）
     「船尾和船头交替上下起伏」  ✅「纵摇」         ❌「船首尾起伏」（描述不是词）
     「将船舶划分为水密隔舱」    ✅「隔舱化」       ❌「分隔水密舱」（翻译腔）
   判断法：把你写的标签念一遍，像不像**中文词典里会出现的词条**。
   像「预先安排」「用杠杆撬」「呈现样子」这种，是把西语语法搬进了中文，重写。


 · 🔴 **标签必须脱离定义也看得懂。** 用户只看到标签，看不到定义。宁可多两个字：
     「倾向于控球而不传给队友的足球运动员」 ✅「独球的球员」 ❌「独的」（看不懂）
     「强度最高的点或时刻」               ✅「高潮点；顶点」 ❌「高潮」（有歧义）
     「（比喻）贪婪、狡猾且恶毒的人」       ✅「狡诈恶毒的人」 ❌「黄鼠狼般的人」（明喻不是对应词）
   ⚠️ 别为了凑词性后缀牺牲可读性：副词义项不必硬加「地」，形容词义项不必硬加「的」，
     怎么自然怎么写。

 · 汉语里确实没有对应词的（多为西语特有事物），写最贴近的名词短语，仍≤10 字。
 · 🔴 **输出必须是纯中文**（专名音译、拉丁学名、化学式除外）。
   出现「克ryptonite」这种中英混排一律算错。
 · 不加句号、不加引号、不写拼音。

只输出 JSON：{"结果":[{"id":义项id,"label":"…"},…]}，条数与输入完全相等、顺序一致。"""


def fetch(con, limit=None, sample=None, seed=7, target=False):
    """待处理的义项：有 zh/definition 但没有 zh/equivalent。

    `target=True` 只取**真正扫不动的那批**：中文 >14 字 **且** 所属词有 ≥5 条义项。

    ⚠️ 全部缺 zh/equivalent 的有 111,412 条，但其中 56% 中文本来就 ≤10 字
    （`妓女` / `污水排水管`）—— 它们已经是合格的标题，不需要再提炼。
    单义词和 2–4 义词一屏放得下，长一点也不影响扫读。
    两条一筛，13,838 条。**早先按「缺标记」估的 17.2 万是三倍虚高**
    （量标记不量内容，见 [[measure-landing-not-source]]）。
    """
    cond = ("" if not target else
            " AND LENGTH(g.text) > 14"
            " AND (SELECT COUNT(*) FROM sense x WHERE x.word_id = s.word_id) >= 5")
    rows = con.execute(f"""
        SELECT s.id, d.word, s.pos, g.text
        FROM sense s
        JOIN dict d ON d.id = s.word_id
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='zh'
                          AND g.kind='definition' AND g.seq=0
        WHERE NOT EXISTS (SELECT 1 FROM sense_gloss e
                          WHERE e.sense_id = s.id AND e.lang='zh' AND e.kind='equivalent')
        {cond}
        ORDER BY s.word_id, s.rank""").fetchall()
    es = dict(con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='es' AND kind='definition' AND seq=0"))
    # 同词的兄弟标签（已有的短对应词），喂进去防止产出雷同
    sib = collections.defaultdict(list)
    for w, t in con.execute("""
            SELECT d.word, g.text FROM sense_gloss g
            JOIN sense s ON s.id = g.sense_id JOIN dict d ON d.id = s.word_id
            WHERE g.lang='zh' AND g.kind='equivalent'"""):
        sib[w].append(t)
    out = [{"id": i, "w": w, "pos": p, "es": es.get(i, ""), "zh": z,
            "sibs": sib.get(w, [])[:6]} for i, w, p, z in rows]
    if sample:
        # 分层抽样：按「该词有几条义项」分层，别只抽到单义项词
        random.seed(seed)
        by = collections.defaultdict(list)
        for it in out:
            n = len(sib.get(it["w"], [])) + 1
            by["多义" if n > 3 else "少义"].append(it)
        pick = []
        for k, v in by.items():
            pick += random.sample(v, min(sample // 2, len(v)))
        return pick
    return out[:limit] if limit else out


def chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


async def call_deepseek(cl, key, chunk, model):
    body = {"model": model,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": json.dumps(
                             [{k: v for k, v in it.items()} for it in chunk],
                             ensure_ascii=False)}],
            "temperature": 0, "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"}, "stream": False}
    r = await cl.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": "Bearer " + key}, json=body)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    d = json.loads(r.text)
    return d["choices"][0]["message"]["content"], (d.get("usage") or {})


async def call_doubao(cl, model, chunk):
    r = await cl.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": json.dumps(chunk, ensure_ascii=False)}],
        temperature=0, response_format={"type": "json_object"},
        thinking={"type": "disabled"})       # 成批当判官/生成：关思考
    u = r.usage
    return r.choices[0].message.content, {"total_tokens": getattr(u, "total_tokens", 0)}


async def run(items, which, env):
    ck = chunks(items, CHUNK.get(which, 40))
    out, usage = {}, collections.Counter()
    t0 = time.time()
    if which in ("flash", "v4pro"):
        import httpx
        cl = httpx.AsyncClient(timeout=900)
        key = env["DEEPSEEK_API_KEY"].strip()
        mdl = "deepseek-v4-flash" if which == "flash" else "deepseek-v4-pro"
        fn = lambda c: call_deepseek(cl, key, c, mdl)  # noqa: E731
    else:
        from volcenginesdkarkruntime import AsyncArk
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
        model = env["DOUBAO_SEED_2_1_PRO"]
        fn = lambda c: call_doubao(cl, model, c)       # noqa: E731
    sem = asyncio.Semaphore(PAR)

    async def go(c):
        async with sem:
            try:
                txt, u = await fn(c)
            except Exception as ex:
                print(f"\n  🔴 块失败：{ex}")
                return
            for k, v in (u or {}).items():
                if isinstance(v, int):
                    usage[k] += v
            # 🔴 容错取 key：模型不保证用我们指定的 `结果`，v4-pro 有一半的块写成
            #    `result`。第一版只认 `结果`，于是把这些块记成「条数不符 0 vs 40」，
            #    看起来像 v4-pro 完成率只有 60% —— **是解析器的锅，不是模型的**。
            #    差点据此把它判出局。任何值是 list 的顶层 key 都收。
            try:
                d = json.loads(txt)
            except json.JSONDecodeError:
                print("\n  🔴 JSON 解析失败")
                return
            res = next((v for v in d.values() if isinstance(v, list)), [])
            if len(res) != len(c):
                print(f"\n  🔴 条数不符 {len(res)} vs {len(c)}  keys={list(d.keys())}")
                return
            # 按 id 对，不按位置 —— 位置对齐是「行号契约」的又一个变体
            want = {it["id"] for it in c}
            for r in res:
                rid = r.get("id")
                if rid in want:
                    out[rid] = (r.get("label") or "").strip()
    await asyncio.gather(*(go(c) for c in ck))
    if which in ("flash", "v4pro"):
        await cl.aclose()
    else:
        await cl.close()
    print(f"  {which}: {len(out):,}/{len(items):,} 条，"
          f"{usage.get('total_tokens', 0):,} tokens，{time.time()-t0:.0f} 秒")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--target", action="store_true",
                    help="只跑真正扫不动的那批（>14 字且所属词 ≥5 条义项）")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default="flash",
                    choices=["flash", "v4pro", "doubao", "both", "all"])
    ap.add_argument("--ask", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    items = fetch(con, limit=args.limit, sample=args.sample, target=args.target)
    total = con.execute("""
        SELECT COUNT(*) FROM sense s WHERE EXISTS(
          SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh' AND g.kind='definition')
        AND NOT EXISTS(
          SELECT 1 FROM sense_gloss e WHERE e.sense_id=s.id AND e.lang='zh' AND e.kind='equivalent')
        """).fetchone()[0]
    con.close()
    print(f"缺短对应词的义项：{total:,}    本次处理 {len(items):,}")

    if not args.ask:
        for it in items[:6]:
            print(f"\n  [{it['id']}] {it['w']} ({it['pos']})  兄弟标签={it['sibs']}")
            print(f"      es: {it['es'][:70]}")
            print(f"      zh: {it['zh'][:70]}")
        print("\n未加 --ask，不发请求。")
        return

    env = dict(l.split("=", 1) for l in paths.ENV.read_text().splitlines()
               if "=" in l and not l.startswith("#"))
    which = ({"both": ["flash", "doubao"],
              "all": ["flash", "v4pro", "doubao"]}).get(args.model, [args.model])
    res = {w: asyncio.run(run(items, w, env)) for w in which}

    # 横向对比表
    print("\n" + "=" * 96)
    print(f"{'词':<14}{'已有兄弟标签':<20}" + "".join(f"{w:<16}" for w in which) + "长定义")
    print("=" * 96)
    for it in items[:40]:
        cells = "".join(f"{res[w].get(it['id'], '—')[:14]:<16}" for w in which)
        print(f"{it['w'][:12]:<14}{str(it['sibs'])[:18]:<20}{cells}{it['zh'][:34]}")

    # 客观尺子：长度、是否雷同、是否带领域前缀
    print("\n客观指标：")
    for w in which:
        v = [x for x in res[w].values() if x]
        over = sum(1 for x in v if len(x.replace("；", "")) > 10)
        pref = sum(1 for x in v if x.startswith("（") or x.startswith("("))
        dup = sum(1 for it in items
                  if res[w].get(it["id"]) and res[w][it["id"]] in it["sibs"])
        avg = sum(len(x) for x in v) / max(len(v), 1)
        print(f"  {w:<8}产出 {len(v):>4}  均长 {avg:>4.1f} 字  "
              f"超10字 {over:>3}  带领域前缀 {pref:>3}  与兄弟雷同 {dup:>3}")

    RAW.parent.mkdir(parents=True, exist_ok=True)
    with RAW.open("a", encoding="utf-8") as f:
        for w in which:
            for sid, lab in res[w].items():
                f.write(json.dumps({"model": w, "id": sid, "label": lab},
                                   ensure_ascii=False) + "\n")
    print(f"\n已追加 → {RAW}")

    if not args.apply:
        print("未加 --apply，不写库。")
        return
    if len(which) != 1:
        sys.exit("--apply 时只能指定一个模型")
    plan = [(sid, "zh", "equivalent", 0, lab, f"llm-label-{which[0]}")
            for sid, lab in res[which[0]].items() if lab]
    with dbtool.session("gen-sense-labels", expect={}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
            "VALUES (?,?,?,?,?,?)", plan)
    print(f"落库 {len(plan):,} 条")


if __name__ == "__main__":
    main()
