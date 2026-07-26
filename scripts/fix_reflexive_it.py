#!/usr/bin/env python3
"""it 专用:重修"反身附着代词动词变形形"译文(见对话 2026-07-26)。
gloss='compound of ... with si' 的反身/代词式动词变形(Xsi),上一轮变形修复常逐字拼成
"（自己）V，V着自己"生硬累赘,或在 Xsi 有独立地道义时译错(invaghirsi迷恋→"爱上自己"、
ingegnarsi努力→"设计我们"、sbellicarsi笑破肚皮→"解开扣子")。
本脚本用改进提示词 turbo batch 重译:给反身式的自然/地道义、禁止"V着自己"累赘、保留形态注。
逐义项对齐 gloss、has_meaning 兜底、只在有真义且与旧不同时写库、先备份。

用法(仓库根):
  python3 scripts/fix_reflexive_it.py --dry
  python3 scripts/fix_reflexive_it.py --pilot 60     # 试译60条,打印新旧对比,不写库
  python3 scripts/fix_reflexive_it.py --run
"""
import argparse, asyncio, json, re, shutil, sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
DB = str(ROOT / "it/synapse-dict-it.sqlite")
CHUNK, CONC, TIMEOUT = 15, 100, 1800

LATIN = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9'\.\-·]*")
PAREN = re.compile(r'[（(][^（）()]*[）)]')
CJK = re.compile(r'[一-鿿]')
BOILER = set("同近义词缩略语旧拼正字法改革前后写式异体变形上使沿用巴西葡萄牙意大利法德西班牙年月至误现之仍偶见作可出协定议执生效未标准表示指的是为即与和或在有种一个也可能对应现代当今如今日常另称俗俚学名术那此该其被将把只主要多用于")


def has_meaning(zh):
    for sense in zh.split("\n"):
        s = PAREN.sub("", sense); s = LATIN.sub("", s)
        s = re.sub(r'[\s，,、；;。.·\-—/：:()（）0-9%]', "", s)
        s = "".join(ch for ch in s if ch not in BOILER)
        if CJK.search(s):
            return True
    return False


SYS = """你是意大利语→简体中文词典翻译专家。给你一批意大利语**反身/代词式动词的附着代词变形形**,每条含词形 w、词性 pos、英文释义数组 gloss(形如 "compound of the infinitive/gerund X with si",表示基础动词 X 的反身式 Xsi 的某个变形)。
之前的译文常有两种毛病:①逐字拼成"（自己）V，V着自己"这类生硬累赘的重复;②当 Xsi(反身式)有独立地道义时译错。请重译成自然准确的中文:
- 给出该**反身式动词的自然中文词义**。若 Xsi 有独立/地道义,**必须用地道义**,不要按"基础动词+自己"硬拼。例:invaghirsi=迷恋、爱上;ingegnarsi=努力、设法、想方设法;avventarsi=猛扑、扑向;sbellicarsi(dalle risa)=笑破肚皮;stufarsi=厌烦、受够了;accorgersi=察觉、发觉。
- 若确是普通直义反身(lavarsi=洗漱、洗自己;abbassarsi=降低、俯身;vestirsi=穿衣),给自然说法即可,**严禁写"V着自己""V着自身""V我们自己""V你们自己""V着我们""V着你们"这种累赘重复**。
- 附着代词 **si=第三人称/泛指反身,ci=noi(我们)反身,vi=voi(你们/您诸位)反身**——都指该动词的反身义,人称不同而已,自然表达即可(如 lavarci=（我们）洗漱、stufandovi=（你们）厌烦、腻烦)。
- 格式:「自然词义（基础词+形态注）」,形态注保留基础词与形态,如"（lavare动名词 + 反身代词si）"。多个近义中文用"，"分隔。
- 逐义项翻译,返回 "zh" 数组,**长度严格等于 gloss 数组、一一对应**;只给释义本身,不加词性标注。
严格输出 JSON:{"1":{"zh":["义项1",...]},...},无多余文字。

示例(输入词 → 期望 zh):
lavandosi（compound of lavando, the gerund of lavare, with si）→ ["（自己）洗漱，梳洗（lavare动名词 + 反身代词si）"]
invaghendosi（compound of invaghendo, the gerund of invaghire, with si）→ ["迷恋上，爱上（invaghirsi 动名词 + 反身代词si）"]
stufandosi（compound of stufando, the gerund of stufare, with si）→ ["厌烦，腻烦，受够了（stufarsi 动名词 + 反身代词si）"]
abbassandosi（compound of abbassando, the gerund of abbassare, with si）→ ["降低，下降；俯身，屈就（abbassare动名词 + 反身代词si）"]"""


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


def _base(d):
    m = re.search(r'\bof (\w+),? with (?:si|ci|vi)\b', d) or re.search(r'gerund of (\w+),? with', d) \
        or re.search(r'infinitive (\w+) with', d)
    return m.group(1) if m else None


CIVI_LIT = re.compile(r'我们自己|你们自己|自己|着我们|着你们')


def targets(mode="si"):
    c = sqlite3.connect(DB)
    rows = c.execute(
        "SELECT id, word, pos, definition, translation FROM dict "
        "WHERE is_lemma=1 AND definition LIKE 'compound of%' "
        "AND translation IS NOT NULL AND TRIM(translation)<>''").fetchall()
    c.close()
    if mode == "si":
        return [(i, w, p, en.split("\n"), zh.split("\n")) for i, w, p, en, zh in rows
                if re.search(r'with si\b', en)]
    # civi: base 属反身动词(有 with si 形)集合 + 译文呈逐字拼,挡开正常宾语代词
    si_bases = {_base(en) for _, _, _, en, _ in rows if re.search(r'with si\b', en)}
    si_bases.discard(None)
    return [(i, w, p, en.split("\n"), zh.split("\n")) for i, w, p, en, zh in rows
            if re.search(r'with (ci|vi)\b', en) and _base(en) in si_bases and CIVI_LIT.search(zh)]


async def acall(comps, model, sys, payload, batch=True):
    kw = {"thinking": {"type": "disabled"}} if batch else {"reasoning_effort": "minimal"}
    delay = 3
    for att in range(5 if batch else 3):
        try:
            r = await comps.create(model=model, temperature=0.2, **kw,
                messages=[{"role": "system", "content": sys},
                          {"role": "user", "content": "输入:\n" + json.dumps(payload, ensure_ascii=False)}])
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


def translate(rows, env):
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=TIMEOUT)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            p = {str(k): {"w": r[1], "pos": r[2] or "", "gloss": r[3]} for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        print(f"turbo batch 重译 {len(rows)} 词 / {len(batches)} 批(慢批切pro online)")
        hedge = (env["DOUBAO_SEED_2_1_PRO"], client.chat.completions, 180)
        results, tok = await run_batches(SYS, batches, model, client.batch.chat.completions, hedge)
        await client.close()
        return metas, results, tok

    return asyncio.run(go())


def do_pilot(n, mode="si"):
    rows = targets(mode)[:n]
    print(f"[it] pilot({mode}) 试译 {len(rows)} 条(不写库):")
    metas, results, tok = translate(rows, load_env())
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, gl, old) in enumerate(meta, 1):
            v = res.get(str(k))
            new = v["zh"] if isinstance(v, dict) and isinstance(v.get("zh"), list) else None
            print(f"  {w}:\n     旧 {'/'.join(old)[:50]}\n     新 {'/'.join(new)[:50] if new else '✗无返回'}")
    print(f"token {tok}")


def do_run(mode="si"):
    rows = targets(mode)
    print(f"[it] 反身附着代词形({mode})重修: {len(rows)} 条")
    bak = Path(DB).with_suffix(f".pre-reflfix{mode}-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy(DB, bak); print(f"已备份 {bak.name}")
    metas, results, tok = translate(rows, load_env())
    ov = ROOT / "it" / "overrides.tsv"
    conn = sqlite3.connect(DB)
    fixed = badlen = novote = noecho = same = 0
    ov_lines = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, gl, old) in enumerate(meta, 1):
            v = res.get(str(k))
            if not isinstance(v, dict) or "zh" not in v:
                novote += 1; continue
            zh = v["zh"] if isinstance(v["zh"], list) else [str(v["zh"])]
            if len(zh) != len(gl):
                badlen += 1; continue
            new = "\n".join(str(x) for x in zh)
            if not has_meaning(new):
                noecho += 1; continue
            if new == "\n".join(old):
                same += 1; continue
            conn.execute("UPDATE dict SET translation=?, flag=NULL WHERE id=?", (new, rid))
            ov_lines.append(f"{w}\ttranslation\t{'/ '.join(old)}\t{'/ '.join(str(x) for x in zh)}")
            fixed += 1
    conn.commit(); conn.close()
    if ov_lines:
        with open(ov, "a", encoding="utf-8") as f:
            f.write("\n".join(ov_lines) + "\n")
    print(f"\n✅ [it] 写库 {fixed} | 未变 {same} | 义项数不符 {badlen} | 无真义未写 {noecho} | 无返回 {novote} | token {tok}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--pilot", type=int, metavar="N")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--mode", choices=["si", "civi"], default="si")
    a = ap.parse_args()
    if a.dry:
        rows = targets(a.mode)
        print(f"[it] {a.mode} 反身附着形: {len(rows)} 条  样本:")
        for r in rows[:6]:
            print(f"  {r[1]}: {'/'.join(r[4])[:50]}")
    elif a.pilot:
        do_pilot(a.pilot, a.mode)
    elif a.run:
        do_run(a.mode)
    else:
        ap.print_help()
