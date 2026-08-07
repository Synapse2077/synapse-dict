#!/usr/bin/env python3
"""给 `sense_es` 的西语单语义项填中文，顺带产出与英文义项的对齐。2026-08-06。

═══ 两段，顺序不能反 ═══
① `--copy`  从 `dict.translation` 逐行复制（**不花钱**）
   54,067 个词的西语义项在 2026-08-03 那轮已经翻过了（`translate_intake.py`，
   源头就是同一批 `definition_es`），`sense_es` 里那份是同内容的结构化副本。
   逐条文本比对一致才复制，对不上的（139 个词）不碰、留给 ②。
   ⇒ 60,451 条免费拿到中文。

② `--llm`   deepseek-v4-flash 关思考，翻剩下的 103,887 条

═══ 🔴 为什么翻译和对齐要合在一次调用里 ═══
"西语版 7 条、英文版 4 条 ⇒ 多了 3 条"是**算术差，不是识别** —— 它没说是哪 3 条，
甚至没保证真多了 3 个意思。`escalera` 就是反例：两边都是 4 条，但英文把"顺子"
合成一条 `straight`，西语拆成"连续牌组"和"五张同花顺"两条。**条数相等，切分不同。**

要知道哪条是新的只能做语义对齐。而翻译时**本来就要把英文义项喂进去消歧** ——
输入一分钱不多花，只让模型每条多吐一个下标 `en_i`，就顺带拿到了对齐表。

⭐ `en_i` 只落在 `sense_es` 自己的列里，**不改动义项结构**，所以可逆。
   义项要不要真合并（合错就拆不回来）是另一件事，等看过这份对齐表再定。

═══ payload 纪律（都是踩过的坑）═══
· 喂英文义项 + 我们已有的中文 → 消歧，并让术语与主释义保持一致
· 🔴 元标记要**转括注不许直译**：`Por metonimia, precaución` → `（转喻）谨慎`，
  不是"转喻，谨慎"。全库 3,954 条（2.5%）以这类标记开头，不说明就会写进释义。
· 译**定义**不译对应词：西语版写"这个词指什么"，中文也要是"指什么"。
  只写"楼梯"是对应词，那个已经在 `dict.translation` 里了。
· 条数必须与输入完全相等 —— 逐词校验，不符的整词丢回重跑，绝不按下标硬对。

═══ 分块按**义项数**不按词数 ═══
`hacer` 一个词就有 59 条义项，按词数切块会让某些请求爆掉输出上限。
按义项数累计到 ~120 切一刀，请求大小才均匀。

用法（在仓库根）：
    python3 -m es.pipeline.translate_sense_es --copy          # 报告
    python3 -m es.pipeline.translate_sense_es --copy --apply
    python3 -m es.pipeline.translate_sense_es --llm --limit 200
    python3 -m es.pipeline.translate_sense_es --llm           # 全量（可中断续跑）
    python3 -m es.pipeline.translate_sense_es --merge         # 把 LLM 产出写回库
"""
import argparse
import asyncio
import collections
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

RAW = paths.WORK / "sense_es_llm.jsonl"     # 模型原始返回，逐块追加，续跑靠它
MODEL = "deepseek-v4-flash"
SENSES_PER_CHUNK = 120
PAR = 16

SYS = """你是西班牙语→简体中文的词典编纂专家。输入是一批西语词条，每条含：
  w 词形 / pos 词性 / en 英文版义项 / zh 我们已有的中文（与 en 逐条对应） / es 西语版**单语定义**

对 es 的每一条输出 "zh" 和 "en_i"：

【zh】该定义的简体中文翻译
 · 译**定义**不译对应词。西语版写"这个词指什么"，中文也要是"指什么"。
   Construcción formada por una serie de escalones… → "由一系列台阶构成的建筑构件，供人上下不同高度"
   不要只写"楼梯"——对应词已经在 zh 里了。
 · 🔴 开头的元标记**不是正文**，要转成括注，不许直译成句子：
     "Por extensión, la batalla en sí"      → "（引申）战斗本身"      不要写"引申义，战斗本身"
     "Por metonimia, precaución."           → "（转喻）谨慎、当心"    不要写"转喻，谨慎"
     "Dicho de una persona: que…"           → "（用于人）…"          不要写"说的是一个人…"
   同类还有 Por analogía（类比）/ Por antonomasia（专指）/ Figuradamente、En sentido figurado（比喻）/
   En general（泛指）/ Específicamente（特指）/ Dicho de una cosa（用于物）。
 · 保持词典体例：不加"指"、"表示"这类开场白；地区和语域标注不要写进译文。

【en_i】这条西语定义对应 en 的第几条（下标从 0）
 · 对应多条取最贴近的一条；en 里没有任何一条表达这个意思写 null；en 为空全写 null。
 · 依据是**语义**不是顺序。两版顺序不一定一致、条数不一定相等
   （英文版常把西语版拆开的两条并成一条，此时两条都指同一个下标）。

只输出 JSON：{"结果":[{"w":词形,"s":[{"zh":"…","en_i":0或null},…]},…]}
s 的条数必须与输入 es **完全相等**、顺序一致，绝不增删。"""


def nl(s):
    return [x.strip() for x in (s or "").split("\n")]


# ═══════════════════ ① 复制段 ═══════════════════
def copy_stage(apply: bool) -> None:
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT word, definition_es, translation FROM dict "
        "WHERE is_lemma=1 AND TRIM(COALESCE(definition_es,''))<>''").fetchall()
    se = collections.defaultdict(list)
    for w, i, g in con.execute("SELECT word, idx, gloss FROM sense_es ORDER BY word, idx"):
        se[w].append((i, g))
    con.close()

    plan, misfit = [], []
    for w, des, tr in rows:
        gl = [x for x in nl(des) if x]
        zh = nl(tr)
        cur = se.get(w, [])
        # 逐条文本一致 + 中文行数够 才复制；差一点都不硬对
        if len(cur) == len(gl) and [g for _, g in cur] == gl and len(zh) >= len(gl):
            for (i, _), z in zip(cur, zh):
                if z:
                    plan.append((z, "copied-from-dict", w, i))
        elif cur:
            misfit.append(w)

    # 🔴 只填空，不覆盖 —— 与 merge() 同一条规矩，理由见那里的 docstring。
    #    2026-08-06 实测：`ramplug` 的 2 条已由 LLM 译好的义项，因为清掉重复行之后
    #    行数恰好对上了，被复制段**默默改写**成 dict 里的版本。这次两版内容都对，
    #    但「本该只补 584 条新行、实际动了 586 行」本身就是不该发生的事。
    con2 = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    pending = {(w, i) for w, i in
               con2.execute("SELECT word, idx FROM sense_es WHERE zh IS NULL")}
    con2.close()
    n_all = len(plan)
    plan = [p for p in plan if (p[2], p[3]) in pending]

    print(f"可复制 {n_all:,} 条，其中待填空的 {len(plan):,} 条"
          f"（{len({p[2] for p in plan}):,} 个词）")
    print(f"  已有译文、跳过不覆盖：{n_all - len(plan):,}")
    print(f"对不上、留给 LLM：{len(misfit):,} 个词")
    # 🔴 项目教训：「跳过」那栏必须看得见
    print(f"  样例：{misfit[:8]}")
    if not apply:
        print("\n未加 --apply，不写库。")
        return
    with dbtool.session("copy-sense-es-zh", expect={}) as s:
        s.executemany("UPDATE sense_es SET zh=?, zh_src=? WHERE word=? AND idx=?", plan)
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM sense_es WHERE zh IS NOT NULL").fetchone()[0]
    con.close()
    print(f"落库后有中文的义项：{n:,}")


# ═══════════════════ ② LLM 段 ═══════════════════
def llm_items(limit=None):
    """待译清单。

    🔴 别逐词查 `dict`。第一版对 need 里的**每个词**单发一次
    `SELECT … WHERE word=?`，`word` 上没有索引 ⇒ 4.7 万次全表扫，
    而且 `--limit` 截的是最后的输出列表、截不住这个循环，跑十分钟不出声。
    → 一次 JOIN 全取回来（项目铁律：别逐行查、别全表扫）。
    """
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    need = collections.defaultdict(list)
    meta = {}
    for w, i, g, de, tr, pos in con.execute(
            "SELECT s.word, s.idx, s.gloss, d.definition, d.translation, d.pos "
            "FROM sense_es s JOIN dict d ON d.id = s.dict_id "
            "WHERE s.zh IS NULL ORDER BY s.word, s.idx"):
        need[w].append((i, g))
        meta[w] = (de, tr, pos)
    con.close()
    out = []
    for w, sens in need.items():
        de, tr, pos = meta[w]
        # 🔴 `en` 为空时 `translation` 装的**不是释义，是指针文本**
        #    （`build.py:395`：`translation = None if is_lemma else infl`，
        #     值形如 `-ido 的 过去分词·阴性·单数`）。
        #    prompt 里 `zh` 那一栏写明是「我们已有的中文（与 en 逐条对应）」，
        #    en 空着却塞进一句指针，是在给模型喂噪声 —— 2026-08-06 收进
        #    7,138 条变形层义项时才暴露出来（此前本表只服务 lemma，`en` 必非空）。
        has_en = bool((de or "").strip())
        out.append({"w": w, "pos": pos,
                    "en": nl(de) if has_en else [],
                    "zh": nl(tr) if has_en else [],
                    "es": [g for _, g in sens], "_idx": [i for i, _ in sens]})
        if limit and len(out) >= limit:
            break
    return out


def chunks_of(items):
    """按**义项数**切块：hacer 一个词 59 条，按词数切会让请求忽大忽小。"""
    out, cur, n = [], [], 0
    for it in items:
        if cur and n + len(it["es"]) > SENSES_PER_CHUNK:
            out.append(cur)
            cur, n = [], 0
        cur.append(it)
        n += len(it["es"])
    if cur:
        out.append(cur)
    return out


async def one(cl, key, chunk):
    body = {"model": MODEL,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": json.dumps(
                             [{k: v for k, v in it.items() if k != "_idx"} for it in chunk],
                             ensure_ascii=False)}],
            "temperature": 0, "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"}, "stream": False}
    r = await cl.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": "Bearer " + key}, json=body)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    d = json.loads(r.text)
    return d["choices"][0]["message"]["content"], (d.get("usage") or {})


async def run_llm(limit=None):
    import httpx
    env = dict(l.split("=", 1) for l in paths.ENV.read_text().splitlines()
               if "=" in l and not l.startswith("#"))
    key = env["DEEPSEEK_API_KEY"].strip()

    # 🔴 续跑判据必须是 **idx 级**，不能只看词名。2026-08-06 连踩三次：
    #    `esquela` 因清残渣被 2 条拆成 3 条并重新编号后，RAW 里那条旧记录
    #    （idx=[0,1]）失效了，但按词名判"已完成"就会跳过它，`--merge` 再拿旧
    #    idx 往新编号上套 ⇒ [1] 装了本属于 [2] 的译文。**改数据之后旧记录就作废。**
    #    → 只有当 RAW 覆盖了该词当前**全部待译 idx** 时，才算这个词做完了。
    covered = collections.defaultdict(set)
    if RAW.exists():
        with RAW.open(encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    covered[d["w"]].update(d["idx"])
                except Exception:
                    pass

    items = [it for it in llm_items(limit)
             if not set(it["_idx"]) <= covered.get(it["w"], set())]
    chunks = chunks_of(items)
    ns = sum(len(it["es"]) for it in items)
    print(f"■ 待译 {len(items):,} 词 / {ns:,} 条义项（RAW 已覆盖 {len(covered):,} 词），"
          f"{len(chunks):,} 块，并发 {PAR}")
    if not chunks:
        return

    RAW.parent.mkdir(parents=True, exist_ok=True)
    f = RAW.open("a", encoding="utf-8")
    sem = asyncio.Semaphore(PAR)
    lock = asyncio.Lock()
    usage = collections.Counter()
    stat = collections.Counter()
    t0 = time.time()

    async def go(i, chunk):
        async with sem:
            async with httpx.AsyncClient(timeout=600) as cl:
                for attempt in range(3):
                    try:
                        raw, u = await one(cl, key, chunk)
                        break
                    except Exception as e:
                        if attempt == 2:
                            print(f"\n🔴 块 {i} 三次失败：{e}")
                            stat["块失败"] += 1
                            return
                        await asyncio.sleep(2 * (attempt + 1))
            try:
                res = {r["w"]: r for r in json.loads(raw).get("结果", [])}
            except Exception as e:
                print(f"\n🔴 块 {i} JSON 解析失败：{e}")
                stat["块失败"] += 1
                return
            async with lock:
                for k, v in u.items():
                    if isinstance(v, int):
                        usage[k] += v
                for it in chunk:
                    r = res.get(it["w"])
                    # 🔴 条数不符整词丢弃，绝不按下标硬对（错位比缺失更伤）
                    if not r or len(r.get("s", [])) != len(it["es"]):
                        stat["条数不符"] += 1
                        continue
                    f.write(json.dumps({"w": it["w"], "idx": it["_idx"], "s": r["s"]},
                                       ensure_ascii=False) + "\n")
                    stat["成功"] += 1
                f.flush()
                el = time.time() - t0
                print(f"\r  {stat['成功']:,}/{len(items):,} 词  "
                      f"{usage['total_tokens']/1e6:.2f}M tokens  "
                      f"{el/60:.1f} 分钟", end="", flush=True)

    await asyncio.gather(*(go(i, c) for i, c in enumerate(chunks)))
    f.close()
    print(f"\n完成：成功 {stat['成功']:,} 词，条数不符 {stat['条数不符']:,}，块失败 {stat['块失败']:,}")
    print(f"tokens 入 {usage['prompt_tokens']:,} 出 {usage['completion_tokens']:,} "
          f"共 {usage['total_tokens']:,}")


def merge(apply: bool, overwrite: bool = False) -> None:
    """把 RAW 里的模型产出写回 `sense_es`。

    🔴 **默认只填空（`zh IS NULL`），绝不覆盖已有译文。** 2026-08-06 立此规矩：
    RAW 是**只追加**的历史全量（此刻 112,381 条），而 `--merge` 原先是无差别重放。
    库里的行在那之后被别的脚本改过，重放就会把修复**撤销**：

      · `clear_invalid_en_i.py` 把 945 条越界 `en_i` 清成了 null（确定性判定为无效），
        RAW 里存的还是那些越界值 —— 重放 = 越界值原样回来
      · `fix_sense_es_residue2.py` 拆分并**重新编号**过若干词，RAW 里的旧 idx
        会套到新编号上 —— 重放 = `esquela` 那个错位坑再来一次

    「只填空」让本步骤幂等且单调：跑多少次结果都一样，且任何后续修复都不会被回卷。
    真要重译某批，先显式把那批 `zh` 清成 NULL，或用 `--overwrite`（危险，见上）。
    """
    if not RAW.exists():
        sys.exit("没有 LLM 产出文件")
    plan, bad = [], 0
    with RAW.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if len(d["idx"]) != len(d["s"]):
                bad += 1
                continue
            for i, s in zip(d["idx"], d["s"]):
                zh = (s.get("zh") or "").strip()
                if not zh:
                    continue
                ei = s.get("en_i")
                plan.append((zh, ei if isinstance(ei, int) else None,
                             "llm-flash", d["w"], i))
    print(f"RAW 累计 {len(plan):,} 条；条数不符丢弃 {bad}")

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    pending = {(w, i) for w, i in
               con.execute("SELECT word, idx FROM sense_es WHERE zh IS NULL")}
    con.close()
    if not overwrite:
        skipped = len(plan)
        plan = [p for p in plan if (p[3], p[4]) in pending]
        print(f"  已有译文、跳过不覆盖：{skipped - len(plan):,}   ← 见 merge() docstring")
    else:
        print("  ⚠️ --overwrite：连已有译文一起重写，会撤销后续修复")
    print(f"待写回 {len(plan):,} 条")
    missing = len(pending) - len({(p[3], p[4]) for p in plan})
    print(f"  库里仍待译、RAW 里也没有的：{missing:,}")
    newn = sum(1 for p in plan if p[1] is None)
    print(f"  判为「英文版没有」的新义项：{newn:,}  {newn/max(len(plan),1)*100:.1f}%")
    if not apply:
        print("未加 --apply，不写库。")
        return
    with dbtool.session("merge-sense-es-zh", expect={}) as s:
        s.executemany(
            "UPDATE sense_es SET zh=?, en_i=?, zh_src=? WHERE word=? AND idx=?", plan)
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    tot = con.execute("SELECT COUNT(*) FROM sense_es").fetchone()[0]
    has = con.execute("SELECT COUNT(*) FROM sense_es WHERE zh IS NOT NULL").fetchone()[0]
    con.close()
    print(f"落库后：{has:,}/{tot:,} 条有中文（{has/tot*100:.1f}%）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", action="store_true")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--addcols", action="store_true", help="给 sense_es 加 en_i / zh_src 列")
    ap.add_argument("--overwrite", action="store_true",
                    help="🔴 危险：连已有译文一起重写，会撤销后续修复（见 merge docstring）")
    args = ap.parse_args()

    if args.addcols:
        with dbtool.session("sense-es-addcols", expect={}) as s:
            s.execute("ALTER TABLE sense_es ADD COLUMN en_i INTEGER")
        print("已加 en_i 列（zh_src 建表时就有）")
        return
    if args.copy:
        copy_stage(args.apply)
    elif args.llm:
        asyncio.run(run_llm(args.limit))
    elif args.merge:
        merge(args.apply, args.overwrite)
    else:
        ap.error("要 --copy / --llm / --merge / --addcols 之一")


if __name__ == "__main__":
    main()
