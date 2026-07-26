#!/usr/bin/env python3
"""修"元指针 gloss 回显"缺陷(见对话 2026-07-26,与 clitic-compound-gloss-defect 同宗、不同 gloss 家族):
kaikki 释义是指针("synonym of X"/"abbreviation of X"/"pre-reform spelling of X"/"* spelling of X"),
豆包照抄成"X的同义词/旧拼写",没给 X 的真词义。本脚本用 has_meaning 分类器精确挑出**纯回显(A类)**条目,
turbo batch 重译成"词义在前 + 简短来源注",逐义项对齐 gloss、只在 len(zh)==len(gloss) 且新译确实给了真词义时写库。

安全设计:
- 分类器 has_meaning 已双向验证:正确排除 2870+ 条"已含真词义+拼写注"的 B 类好条目(不误伤)。
- 新译"词义（X的旧拼写）"把词义放括号外 → 幂等,再跑不会二次选中。
- 兜底:豆包若仍回显(新译 has_meaning=False)则不写库,绝不降质。

用法(仓库根):
  python3 scripts/fix_pointer_gloss.py --lang pt --dry
  python3 scripts/fix_pointer_gloss.py --lang pt --run
  python3 scripts/fix_pointer_gloss.py --all --run
"""
import argparse, asyncio, json, re, shutil, sqlite3, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
CHUNK, CONC, TIMEOUT = 15, 100, 1800

# ---- has_meaning 分类器(与对话中双向验证过的完全一致) ----
LATIN = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9'\.\-·]*")
PAREN = re.compile(r'[（(][^（）()]*[）)]')
CJK = re.compile(r'[一-鿿]')
BOILER = set("同近义词缩略语旧拼正字法改革前后写式异体变形上使沿用巴西葡萄牙意大利法德西班牙年月至误现之仍偶见作可出协定议执生效未标准表示指的是为即与和或在有种一个也可能对应现代当今如今日常另称俗俚学名术那此该其被将把只主要多用于类中本词形态说明")


def has_meaning(zh):
    """去括号注+拉丁词+boilerplate 后,任一义项仍有真中文=有词义(True)。"""
    for sense in zh.split("\n"):
        s = PAREN.sub("", sense)
        s = LATIN.sub("", s)
        s = re.sub(r'[\s，,、；;。.·\-—/：:()（）0-9%]', "", s)
        s = "".join(ch for ch in s if ch not in BOILER)
        if CJK.search(s):
            return True
    return False


# 指针族(gloss闸):has_meaning=False 再叠加,双闸挡住"本义就是拼写/同义"的实词(gloss=orthographic/synonymous 不在此列)。
# "%spelling of %" 已涵盖 alternative/obsolete/dated/standard/post-1990/pre-1990 spelling of;pre-reform 因中间插字单列。
GLOSS_PATS = ["%synonym of %", "%abbreviation of %", "%pre-reform spelling%", "%spelling of %",
              "%initialism of %", "%clipping of %", "%transliteration of %"]

LANGS = {
 "es": ("es/synapse-dict-es.sqlite", "西班牙"),
 "it": ("it/synapse-dict-it.sqlite", "意大利"),
 "fr": ("fr/synapse-dict-fr.sqlite", "法"),
 "pt": ("pt/synapse-dict-pt.sqlite", "葡萄牙"),
 "de": ("de/synapse-dict-de.sqlite", "德"),
}

BASE_SYS = """你是{LANG}语→简体中文词典翻译专家。给你一批{LANG}语词条,每条的英文释义 gloss 是**指针式描述**(如 "synonym of X"、"abbreviation of X"、"pre-reform spelling of X"、"alternative/obsolete spelling of X"),它只说明本词是某个词 X 的同义词/缩写/旧拼写,**没有直接给出词义**。之前的译文把这句指针照抄了(如"X的旧拼写"),用户查词只看到指针、看不到意思。
请逐义项翻译,返回 "zh" 数组,**长度严格等于 gloss 数组、一一对应**:
- 对**指针义项**:先给出 X 的**实际中文词义**,再用括号补简短来源注。格式:「词义（X 的旧拼写/缩写/同义词）」。
  例:pre-reform spelling of hipocrisia → "伪善，虚伪（hipocrisia 的旧拼写）";abbreviation of cónfer → "参见，比较（cónfer 的缩写）";synonym of resalto → "突出，突起（同 resalto）"。
  X 是专有名词(人名/地名)时,给中文译名即可(如 "庞贝（旧拼写）")。
- 若某义项的原译文**已经给了真实词义**(不是纯指针),原样保留、不要改。
- **绝对禁止**只写"X的旧拼写/缩写/同义词"而不给 X 的实际意思。
- 一个义项内多个近义中文用"，"分隔,只给释义本身,不加词性标注。
严格输出 JSON:{"1":{"zh":["义项1",...]},...},无多余文字。

示例(输入词 → 期望 zh):
{FEWSHOT}"""

FEWSHOT = {
 "es": """cf.（abbreviation of cónfer / confróntese）→ ["参见，比较（cónfer 的缩写）", "参见，试比较（confróntese 的缩写）"]
resalte（synonym of resalto）→ ["突出，突起，凸起（同 resalto）"]
ene.（abbreviation of enero）→ ["一月（enero 的缩写）"]""",
 "it": """dimagramento（synonym of dimagrimento）→ ["消瘦,减肥,变瘦（同 dimagrimento）"]
abantico（alternative spelling of ab antico）→ ["自古,从古时起（ab antico 的异拼）"]""",
 "fr": """aremberge（synonym of ramberge）→ ["（植物）水杨梅；快速帆船（同 ramberge）"]
diner（post-1990 spelling of dîner）→ ["晚餐,晚宴（dîner 的1990年改革后拼写）"]
connaitre（post-1990 spelling of connaître）→ ["认识,知道,了解（connaître 的1990年改革后拼写）"]""",
 "pt": """hypocrisia（pre-reform spelling of hipocrisia）→ ["伪善，虚伪（hipocrisia 的旧拼写）"]
these（pre-reform spelling of tese）→ ["论文，论点（tese 的旧拼写）"]
epônimo（Brazilian Portuguese standard spelling of epónimo）→ ["同名的；名祖，名源人物（epónimo 的巴西葡语标准拼写）"]
beber uma（synonym of tomar uma）→ ["喝一杯,小酌（同 tomar uma）"]""",
 "de": """Jänner（synonym of Januar）→ ["一月（奥地利/南德对 Januar 的说法）"]
Prädikativum（synonym of Prädikativ）→ ["表语,谓语性成分（同 Prädikativ）"]""",
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


def targets(db):
    c = sqlite3.connect(db)
    where = " OR ".join("definition LIKE ?" for _ in GLOSS_PATS)
    rows = c.execute(
        f"SELECT id, word, pos, definition, translation FROM dict "
        f"WHERE is_lemma=1 AND word NOT LIKE '-%' AND word NOT LIKE '%-' "
        f"AND translation IS NOT NULL AND TRIM(translation)<>'' AND ({where})", GLOSS_PATS).fetchall()
    c.close()
    out = []
    for _id, w, pos, en, zh in rows:
        if not has_meaning(zh):          # 只挑纯回显(A类)
            out.append((_id, w, pos, en.split("\n"), zh.split("\n")))
    return out


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


def do_run(lang):
    db, langname = LANGS[lang]
    db = str(ROOT / db)
    rows = targets(db)
    print(f"[{lang}] 待修元指针回显(A类): {len(rows)} 条")
    if not rows:
        return
    bak = Path(db).with_suffix(f".pre-ptrfix-{time.strftime('%Y%m%d-%H%M')}.bak")
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
        print(f"turbo batch 重译 {len(rows)} 词 / {len(batches)} 批(慢批切pro online)")
        hedge = (env["DOUBAO_SEED_2_1_PRO"], client.chat.completions, 180)
        results, tok = await run_batches(sys, batches, model, client.batch.chat.completions, hedge)
        await client.close()
        return metas, results, tok

    metas, results, tok = asyncio.run(go())
    ov = ROOT / lang / "overrides.tsv"
    conn = sqlite3.connect(db)
    fixed = badlen = novote = still_echo = 0
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
            if not has_meaning(new):          # 兜底:仍是回显=不写库,不降质
                still_echo += 1; continue
            if new == "\n".join(old):
                continue
            conn.execute("UPDATE dict SET translation=?, flag=NULL WHERE id=?", (new, rid))
            ov_lines.append(f"{w}\ttranslation\t{'/ '.join(old)}\t{'/ '.join(str(x) for x in zh)}")
            fixed += 1
    conn.commit(); conn.close()
    if ov_lines:
        with open(ov, "a", encoding="utf-8") as f:
            f.write("\n".join(ov_lines) + "\n")
    print(f"\n✅ [{lang}] 写库 {fixed} | 义项数不符 {badlen} | 仍回显未写 {still_echo} | 无返回 {novote} | token {tok}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=list(LANGS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    langs = list(LANGS) if a.all else ([a.lang] if a.lang else [])
    if not langs:
        ap.print_help(); raise SystemExit
    if a.dry:
        for lang in langs:
            db, _ = LANGS[lang]
            rows = targets(str(ROOT / db))
            print(f"[{lang}] 待修: {len(rows)} 条  样本:")
            for r in rows[:5]:
                print(f"  {r[1]}: gloss={r[3][0][:55]} | 旧zh={'/'.join(r[4])[:45]}")
    elif a.run:
        for lang in langs:
            do_run(lang)
    else:
        ap.print_help()
