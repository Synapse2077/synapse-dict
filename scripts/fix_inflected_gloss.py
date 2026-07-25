#!/usr/bin/env python3
"""统一修"变形 lemma 语法译文"缺陷（见 memory clitic-compound-gloss-defect）：
kaikki 对变形词(变位形/附着代词形/分词)的 gloss 是语法描述，豆包照翻语法没给词义。
本脚本揪出"变形 gloss + 译文含语法术语"的 lemma，turbo batch 重译成"词义在前 + 简短形态注"。
逐义项对齐 gloss 数组(多义词只改变形义、保留实词义)，只在 len(zh)==len(gloss) 时写库、清 flag、写 overrides、先备份。

用法（在仓库根）：
  python3 scripts/fix_inflected_gloss.py --lang it --dry
  python3 scripts/fix_inflected_gloss.py --lang it --run
支持 --lang it/pt/fr。es/de 量少已手工。
"""
import argparse, asyncio, json, re, shutil, sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
CHUNK, CONC, TIMEOUT = 15, 100, 1800

# 语法术语标记：译文含这些=漏了词义的目标
GRAM = re.compile(r'(复合形式|结合形式|缩合|命令式|不定式|动名词|副动词|分词|变位|变格|人称|直陈式|陈述式|虚拟式|与格|宾格|属格|过去时|将来时|现在时|完成时|愈过去|先过时|越过去|时态|变化形式)')

BASE_SYS = """你是{LANG}语→简体中文词典翻译专家。给你一批{LANG}语「变形词」（动词变位形/附着代词形/分词等），每条含词形 w、词性 pos、英文释义数组 gloss（每个元素一个义项；变形义项的 gloss 会写明基础词与形态，如 "third-person plural preterite of X" 或 "compound of the infinitive X with Y"）。
逐义项翻译成中文，返回 "zh" 数组，**长度严格等于 gloss 数组、一一对应**：
- 对**变形义项**：**实际中文词义在前 + 简短形态说明放括号**。词义 = 基础词的意思 结合 该形态的语义（人称/时态/语气/代词宾语等）。**绝对禁止**只写语法/形态描述而不给词义。
- 对**非变形义项**（本身是实词、形容词义等）：正常给中文释义，不必加形态说明。
- 一个义项内多个近义中文用"，"分隔；只给释义本身，不加词性标注。
严格输出 JSON：{"1":{"zh":["义项1",...]},...}，无多余文字。

示例（输入词 → 期望 zh）：
{FEWSHOT}"""

FEWSHOT = {
 "it": """averti（compound of the infinitive avere with ti）→ ["有你，拥有你（avere不定式 + 代词ti）"]
lavandosi（compound of lavando, the gerund of lavare, with si）→ ["（自己）洗，洗着自己（lavare动名词 + 反身代词si）"]
amati（compound of ama, the second-person singular imperative of amare, with ti）→ ["爱你自己，自爱（amare命令式 + 代词ti）"]
dallo（compound of da' lo）→ ["给它（命令式da' + 代词lo）"]""",
 "pt": """foram（third-person plural preterite/pluperfect indicative of ir / ser）→ ["（他们/她们）去了；曾是（ir / ser 第三人称复数简单过去时/愈过去时）"]
precisaram（third-person plural preterite of precisar）→ ["（他们）需要了（precisar 第三人称复数过去时）"]""",
 "fr": """content（gloss1: content, satisfied; gloss2: third-person plural present of conter）→ ["满意的，满足的", "（他们）讲述（conter 第三人称复数现在时/虚拟式）"]  ← 多义词：实词义保留、只给变位义词义
conseillé（past participle of conseiller）→ ["建议，被建议的（conseiller 过去分词）"]""",
}

# gloss 模式收紧到「动词语气/时态专属标记」——只认变位/附着代词/分词，排除代词/冠词等功能词定义
# （功能词 gloss 常是 "third-person singular pronoun used as object of a preposition"，靠 mood 词过滤掉）
LANGS = {
 "it": ("it/synapse-dict-it.sqlite", "意大利", ["compound of%"]),
 "pt": ("pt/synapse-dict-pt.sqlite", "葡萄牙", ["%indicative of %","%subjunctive of %","%imperative of %","%participle of %"]),
 "fr": ("fr/synapse-dict-fr.sqlite", "法", ["%indicative of %","%subjunctive of %","%imperative of %","%participle of %"]),
}


def load_env():
    e = {}
    for ln in open(ENV):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1); e[k] = v
    return e


def loads_lenient(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    out = {}
    for m in re.finditer(r'"(\d+)"\s*:\s*(?=\{)', s):
        key = m.group(1); i = m.end(); depth = 0
        for j in range(i, len(s)):
            if s[j] == '{':
                depth += 1
            elif s[j] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        out[key] = json.loads(s[i:j + 1])
                    except Exception:
                        pass
                    break
    if out:
        return out
    raise json.JSONDecodeError("lenient failed", s, 0)


def targets(db, pats):
    c = sqlite3.connect(db)
    where = " OR ".join("definition LIKE ?" for _ in pats)
    rows = c.execute(
        f"SELECT id, word, pos, definition, translation FROM dict "
        f"WHERE is_lemma=1 AND word NOT LIKE '-%' AND word NOT LIKE '%-' "
        f"AND translation IS NOT NULL AND TRIM(translation)<>'' AND ({where})", pats).fetchall()
    c.close()
    out = []
    for _id, w, pos, en, zh in rows:
        if zh and GRAM.search(zh):
            out.append((_id, w, pos, en.split("\n"), zh.split("\n")))
    return out


async def acall(comps, model, sys, payload, batch=True):
    kw = {"thinking": {"type": "disabled"}} if batch else {"reasoning_effort": "minimal"}
    delay = 3
    for att in range(5 if batch else 3):
        try:
            r = await comps.create(model=model, temperature=0.2, **kw,
                messages=[{"role": "system", "content": sys},
                          {"role": "user", "content": "输入：\n" + json.dumps(payload, ensure_ascii=False)}])
            out = r.choices[0].message.content.strip()
            out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
            out = out[out.find("{"):out.rfind("}") + 1]
            return loads_lenient(out), getattr(getattr(r, "usage", None), "total_tokens", 0)
        except Exception:
            if att == (4 if batch else 2):
                raise
            await asyncio.sleep(delay if batch else 1); delay = min(delay * 2, 30)


async def run_batches(sys, batches, model, comps, hedge):
    results = [{} for _ in batches]
    q = asyncio.Queue()
    for i, b in enumerate(batches):
        q.put_nowait((i, b))
    tok = [0]; done = [0]; hedged = [0]

    async def one(p):
        om, oc, after = hedge
        try:
            return await asyncio.wait_for(acall(comps, model, sys, p, True), after)
        except Exception:
            hedged[0] += 1
            return await acall(oc, om, sys, p, False)

    async def worker():
        while True:
            try:
                i, p = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, t = await one(p)
                results[i] = res; tok[0] += t
            except Exception as e:
                print(f"  ✗ {e}")
            done[0] += 1
            if done[0] % 20 == 0 or done[0] == len(batches):
                print(f"  [{done[0]}/{len(batches)}] token {tok[0]} (切online {hedged[0]})", flush=True)
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(batches)))])
    return results, tok[0]


def do_run(lang):
    db, langname, pats = LANGS[lang]
    db = str(ROOT / db)
    rows = targets(db, pats)
    print(f"[{lang}] 待修变形语法译文: {len(rows)} 条")
    if not rows:
        return
    bak = Path(db).with_suffix(f".pre-inflfix-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy(db, bak); print(f"已备份 {bak.name}")
    env = load_env()
    sys = BASE_SYS.replace("{LANG}", langname).replace("{FEWSHOT}", FEWSHOT[lang])
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=TIMEOUT)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            p = {str(k): {"w": r[1], "pos": r[2] or "", "gloss": r[3]} for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        print(f"turbo batch 重译 {len(rows)} 词 / {len(batches)} 批（慢批切pro online）")
        hedge = (env["DOUBAO_SEED_2_1_PRO"], client.chat.completions, 180)
        results, tok = await run_batches(sys, batches, model, client.batch.chat.completions, hedge)
        await client.close()
        return metas, results, tok

    metas, results, tok = asyncio.run(go())
    ov = ROOT / lang / "overrides.tsv"
    conn = sqlite3.connect(db)
    fixed = badlen = novote = 0
    ov_lines = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, gl, old) in enumerate(meta, 1):
            v = res.get(str(k))
            if not isinstance(v, dict) or "zh" not in v:
                novote += 1; continue
            zh = v["zh"] if isinstance(v["zh"], list) else [str(v["zh"])]
            if len(zh) == len(gl):
                new = "\n".join(str(x) for x in zh)
                conn.execute("UPDATE dict SET translation=?, flag=NULL WHERE id=?", (new, rid))
                ov_lines.append(f"{w}\ttranslation\t{'/ '.join(old)}\t{'/ '.join(str(x) for x in zh)}")
                fixed += 1
            else:
                badlen += 1
    conn.commit(); conn.close()
    if ov_lines:
        with open(ov, "a", encoding="utf-8") as f:
            f.write("\n".join(ov_lines) + "\n")
    print(f"\n✅ [{lang}] 写库 {fixed} | 义项数不符未写 {badlen} | 无返回 {novote} | token {tok}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=["it", "pt", "fr"])
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    db, _, pats = LANGS[a.lang]
    if a.dry:
        rows = targets(str(ROOT / db), pats)
        print(f"[{a.lang}] 待修: {len(rows)} 条\n样本:")
        for r in rows[:6]:
            print(f"  {r[1]}: gloss={r[3]}  旧zh={r[4]}")
    elif a.run:
        do_run(a.lang)
    else:
        ap.print_help()
