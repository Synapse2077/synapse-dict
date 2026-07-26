#!/usr/bin/env python3
"""整体验收抽样(read-only,不改库)。见对话 2026-07-26。
两部分:
  Part A 结构全库扫(确定性,免费,精确):flag=0 / 译文非空 / 义项数 zh==gloss / IPA 非空 / 名词有 gender / pos 非空。
  Part B 译文抽样(pro online,LLM 擅长的部分):每门随机 N 条 is_lemma=1,pro 逐条判 ok/warn/bad。
    —— 不让 LLM 当 gender/IPA 事实真值裁判(信 kaikki),只判译文准确/完整/是否纯语法/义项对齐。
用法(仓库根):
  python3 scripts/acceptance_sample.py --struct                 # 只跑 Part A(全库结构,秒出)
  python3 scripts/acceptance_sample.py --lang it --n 1200 --run  # Part B 单门
  python3 scripts/acceptance_sample.py --all --n 1200 --run      # Part B 五门
"""
import argparse, asyncio, json, random, re, sqlite3, time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
CHUNK, CONC, TIMEOUT = 20, 80, 600

# 每门: db 路径, 中文名, ipa 列(元组=多列都空才算空), 变形词 gloss 特征
LANGS = {
 "es": ("es/synapse-dict-es.sqlite", "西班牙", ("phonetic",)),
 "it": ("it/synapse-dict-it.sqlite", "意大利", ("ipa",)),
 "fr": ("fr/synapse-dict-fr.sqlite", "法",     ("ipa",)),
 "pt": ("pt/synapse-dict-pt.sqlite", "葡萄牙", ("ipa_br", "ipa_pt")),
 "de": ("de/synapse-dict-de.sqlite", "德",     ("ipa",)),
}
# 变形词 gloss 判别(用于分层统计,非硬指标)
INFL = re.compile(r'\b(compound of|indicative of|subjunctive of|imperative of|participle of|'
                  r'inflection of|form of|preterite|gerund of|plural of)\b', re.I)

JUDGE_SYS = """你是{LANG}语词典质检专家。给你一批词典条目,每条含词形 w、词性 pos、英文释义数组 gloss、中文译文数组 zh。
逐条判断**译文整体质量**(只判译文,不判音标/性别对错):
- zh 是否准确对应 gloss 每个义项的意思;
- zh 义项数是否与 gloss 对齐、有无漏义或凭空多义;
- 若是变形词(gloss 写明是某词的变位形/附着代词形/分词形),zh 是否给了**实际中文词义**(而不是只写语法/形态描述);
- 中文是否自然、无明显错译。
每条返回 {"v":"ok|warn|bad","note":"简短问题,ok可省"}。
ok=可直接上线;warn=可用但有小瑕疵(缺形态注/略生硬/义项注解不全);bad=真错(错译/只有语法描述没给词义/漏义/义项与gloss错位)。
严格输出 JSON {"1":{"v":"ok"},"2":{"v":"bad","note":"..."},...},键与输入一致,无多余文字。"""


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


def struct_audit(lang):
    db, name, ipacols = LANGS[lang]
    c = sqlite3.connect(str(ROOT / db))
    N = c.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    flag_bad = c.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND flag IS NOT NULL AND TRIM(flag)<>''").fetchone()[0]
    zh_empty = c.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND (translation IS NULL OR TRIM(translation)='')").fetchone()[0]
    pos_empty = c.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND (pos IS NULL OR TRIM(pos)='')").fetchone()[0]
    ipa_cond = " AND ".join(f"({col} IS NULL OR TRIM({col})='')" for col in ipacols)
    ipa_empty = c.execute(f"SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND {ipa_cond}").fetchone()[0]
    # 名词缺 gender(仅供参考)
    noun_nog = c.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND pos LIKE '%n%' "
                         "AND (gender IS NULL OR TRIM(gender)='') "
                         "AND definition LIKE '%noun%'").fetchone()[0] if lang != "es" else None
    # 义项数错位: zh 换行数 != definition 换行数
    misalign = 0
    for zh, df in c.execute("SELECT translation, definition FROM dict WHERE is_lemma=1 "
                            "AND translation IS NOT NULL AND TRIM(translation)<>'' "
                            "AND definition IS NOT NULL AND TRIM(definition)<>''"):
        if zh.count("\n") != df.count("\n"):
            misalign += 1
    c.close()
    return dict(N=N, flag_bad=flag_bad, zh_empty=zh_empty, pos_empty=pos_empty,
               ipa_empty=ipa_empty, misalign=misalign)


def sample_rows(lang, n, seed=20260726):
    db, name, _ = LANGS[lang]
    c = sqlite3.connect(str(ROOT / db))
    rows = c.execute("SELECT id, word, pos, definition, translation FROM dict "
                     "WHERE is_lemma=1 AND translation IS NOT NULL AND TRIM(translation)<>''").fetchall()
    c.close()
    random.seed(seed)
    samp = random.sample(rows, min(n, len(rows)))
    return [(i, w, pos, (df or "").split("\n"), (zh or "").split("\n")) for i, w, pos, df, zh in samp]


async def acall(comps, model, sys, payload):
    delay = 1
    for att in range(3):
        try:
            r = await comps.create(model=model, temperature=0.2, reasoning_effort="minimal",
                messages=[{"role": "system", "content": sys},
                          {"role": "user", "content": "输入:\n" + json.dumps(payload, ensure_ascii=False)}])
            out = r.choices[0].message.content.strip()
            out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
            out = out[out.find("{"):out.rfind("}") + 1]
            return loads_lenient(out), getattr(getattr(r, "usage", None), "total_tokens", 0)
        except Exception:
            if att == 2:
                raise
            await asyncio.sleep(delay); delay *= 2


async def run_batches(sys, batches, model, comps):
    results = [{} for _ in batches]
    q = asyncio.Queue()
    for i, b in enumerate(batches):
        q.put_nowait((i, b))
    tok = [0]; done = [0]

    async def worker():
        while True:
            try:
                i, p = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, t = await acall(comps, model, sys, p); results[i] = res; tok[0] += t
            except Exception as e:
                print(f"  ✗ {e}")
            done[0] += 1
            if done[0] % 20 == 0 or done[0] == len(batches):
                print(f"  [{done[0]}/{len(batches)}] token {tok[0]}", flush=True)
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(batches)))])
    return results, tok[0]


def judge_lang(lang, n):
    db, name, _ = LANGS[lang]
    rows = sample_rows(lang, n)
    infl_n = sum(1 for r in rows if INFL.search("\n".join(r[3])))
    print(f"[{lang}] 抽样 {len(rows)} 条(其中变形词约 {infl_n})")
    env = load_env()
    sys = JUDGE_SYS.replace("{LANG}", name)
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=TIMEOUT)
        model = env["DOUBAO_SEED_2_1_PRO"]
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            p = {str(k): {"w": r[1], "pos": r[2] or "", "gloss": r[3], "zh": r[4]} for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        res, tok = await run_batches(sys, batches, model, cl.chat.completions)
        await cl.close(); return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); infl_tally = Counter(); bad = []
    outp = ROOT / "scripts" / f"acceptance_{lang}.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        for meta, res in zip(metas, results):
            res = res or {}
            for k, (rid, w, pos, gl, zh) in enumerate(meta, 1):
                v = res.get(str(k))
                verdict = v.get("v") if isinstance(v, dict) else None
                if verdict not in ("ok", "warn", "bad"):
                    verdict = "novote"
                is_infl = bool(INFL.search("\n".join(gl)))
                tally[verdict] += 1
                if is_infl:
                    infl_tally[verdict] += 1
                note = v.get("note", "") if isinstance(v, dict) else ""
                if verdict == "bad":
                    bad.append((w, "/".join(gl)[:50], "/".join(zh)[:40], note))
                f.write(json.dumps(dict(w=w, infl=is_infl, v=verdict, note=note,
                                        gloss=gl, zh=zh), ensure_ascii=False) + "\n")
    tot = sum(tally.values()); scored = tot - tally["novote"]
    ok, warn, bd = tally["ok"], tally["warn"], tally["bad"]
    print(f"\n===== [{lang}] 译文抽样验收 {tot} 条(有效 {scored}) token {tok} =====")
    print(f"  ok   {ok} ({100*ok/max(scored,1):.1f}%)")
    print(f"  warn {warn} ({100*warn/max(scored,1):.1f}%)")
    print(f"  bad  {bd} ({100*bd/max(scored,1):.1f}%)   novote {tally['novote']}")
    it = sum(v for k, v in infl_tally.items() if k != "novote")
    if it:
        print(f"  [变形词分层] ok {infl_tally['ok']} / warn {infl_tally['warn']} / bad {infl_tally['bad']} "
              f"(bad {100*infl_tally['bad']/max(it,1):.1f}%)")
    print(f"  bad 样本:")
    for w, g, z, note in bad[:12]:
        print(f"    {w}: gloss={g} | zh={z} | {note}")
    print(f"  明细 → {outp.name}")
    return dict(lang=lang, tot=tot, scored=scored, ok=ok, warn=warn, bad=bd, tok=tok)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--struct", action="store_true", help="Part A 全库结构扫(五门)")
    ap.add_argument("--lang", choices=list(LANGS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.struct or not (a.run):
        print("========== Part A 结构全库扫(is_lemma=1) ==========")
        for lang in LANGS:
            s = struct_audit(lang)
            N = s["N"]
            print(f"[{lang}] 共 {N} 条 | flag残留 {s['flag_bad']} | 译文空 {s['zh_empty']} | "
                  f"pos空 {s['pos_empty']} | IPA空 {s['ipa_empty']}({100*s['ipa_empty']/N:.1f}%) | "
                  f"义项错位 {s['misalign']}")
        if not a.run:
            raise SystemExit
    if a.run:
        langs = list(LANGS) if a.all else [a.lang]
        summ = [judge_lang(l, a.n) for l in langs if l]
        print("\n========== Part B 五门译文达标率汇总 ==========")
        for s in summ:
            print(f"  {s['lang']}: ok {100*s['ok']/max(s['scored'],1):.1f}% "
                  f"warn {100*s['warn']/max(s['scored'],1):.1f}% "
                  f"bad {100*s['bad']/max(s['scored'],1):.1f}%")
