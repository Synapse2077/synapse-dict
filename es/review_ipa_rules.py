#!/usr/bin/env python3
"""es 音标**规则 + 映射规则**评审:同一份材料交 豆包2.1pro 与 deepseek-v4-pro 各判一遍。
见对话 2026-07-31。

⭐ 本脚本存在的唯一理由,是 en 那边踩过的坑:**只给代码不给数据的抽象评审会凭空举例**。
   en 上一轮 review_ipa_rules.py 里,v4-pro 拿德语借词 "Kuchen" 论证 kç 规则,
   而 en 库里根本没有这种词 —— 整条建议悬空,白评一轮。
   所以这里强制三件事:
     ① 材料里带**全库真实统计**(每个可疑族到底有多少条,不是"可能会有");
     ② 每个可疑族附**从库里现抽的真实例词**(词形+当前音标),模型只能就这些词说话;
     ③ 判据里明写"只准引用我给的例词,自己编的词一律不算" —— 并要求每条结论回填 `ev` 字段
        指出它依据的是哪几个例词,没有 ev 的结论视为空谈直接丢弃。

⭐ 第二件事:**结合抽样审计的实证结果**(--audit 传入 verify_v4pro.py --ipa 产出的 jsonl)。
   规则评审说的是"规则应该怎样",抽样审计说的是"用户实际看到什么错"。
   两者对不上时以抽样为准 —— 规则再漂亮,库里没这种词就不值得改;
   反过来抽样里高频出现、规则却没覆盖的,才是真正该补的规则。

⚠️ 两家**独立判,不给对方答案**。上一轮的教训:**标签收敛 ≠ 内容收敛**
   (en 那次两家都答"分英美处理",但英式做法一个是删、一个是留,完全相反)。
   所以输出里两家结论逐条并排,不做任何自动合并。

read-only。用法(在 es/ 目录):
  python3 review_ipa_rules.py                                  # 只评规则
  python3 review_ipa_rules.py --audit runs/ipa_v4pro_3000_*.jsonl   # 带上实证结果(推荐)
  python3 review_ipa_rules.py --only ds
"""
import argparse, asyncio, glob, json, re, sqlite3, time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-es.sqlite"
ENV = HERE.parent / ".env"
RUNS = HERE / "runs"
TS = HERE.parent / "packages/dict-core/src/spanish.ts"

SYS = """你是西班牙语语音学 + 词典工程双背景的评审专家。评审一套**已经上线**的西语词典音标流水线。

产品语境:中文用户的**划词弹窗**。用户扫一眼音标就要能读出来,不是给语言学家看的严式转写。

材料分五部分:① 口径约定 ② 规则 G2P 源码 ③ 展示层映射源码 ④ 全库真实统计 ⑤ 真实例词
(可能还有 ⑥ 抽样审计实证结果)。

🔴 **铁律:只准引用材料里给出的真实例词。你自己想出来的词一律不算数。**
   每条结论必须回填 `ev` 字段,列出它依据的例词(从材料里原样抄)。
   给不出 ev 的结论**不要写出来** —— 宁可少写几条,也不要写"某些外来词可能会…"这种悬空判断。
   材料里没有的现象,就当它不存在,不要提醒我"要注意 X",除非统计或例词里真有 X。

请输出**可执行的缺陷清单**,每条含:
  id     短标识(小写下划线,如 approximant_inconsistency)
  where  出在哪:g2p / display / convention / data
  what   缺陷是什么,一句话
  ev     依据的真实例词或统计数字(从材料里抄,可多个)
  impact 用户实际会看到什么错;并说明这是**高频**还是**边缘**(用材料里的条数说话)
  fix    具体怎么改(能写规则就写规则,别写"建议进一步研究")
  conf   你的把握 high/mid/low

按 impact 从高到低排。**没有真凭据的不要凑数** —— 宁可只报 3 条硬的,不要报 10 条软的。
如果某个地方你认为设计是对的、不要改,也可以单列一条 where="ok" 说明理由(同样要 ev)。

严格输出 JSON:{"findings":[{...},{...}],"overall":"两句话总评"}。不要任何解释文字。"""


def load_env():
    env = {}
    for ln in open(ENV, encoding="utf-8"):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def q1(conn, sql):
    return conn.execute(sql).fetchone()[0]


def samples(conn, sql, n=8):
    """现抽真实例词。返回 '词形 → 音标' 列表,模型只能就这些说话。"""
    rows = conn.execute(sql + f" LIMIT {n}").fetchall()
    return [f"{r[0]} → {r[1]}" + (f"  (变形层)" if len(r) > 2 and r[2] == 0 else "") for r in rows]


def build_corpus():
    """④ 全库真实统计 + ⑤ 每族真实例词。全部现查,不写死数字。"""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    H = "TRIM(COALESCE(phonetic,''))<>''"
    stats = {
        "总条目": q1(conn, "SELECT count(*) FROM dict"),
        "lemma(kaikki+豆包来源)": q1(conn, "SELECT count(*) FROM dict WHERE is_lemma=1"),
        "变形层(b_ipa.py 规则生成)": q1(conn, "SELECT count(*) FROM dict WHERE is_lemma=0"),
        "有音标": q1(conn, f"SELECT count(*) FROM dict WHERE {H}"),
        "含 θ(拉美需派生 seseo)": q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%θ%'"),
        "含近音 β/ð/ɣ": q1(conn, "SELECT count(*) FROM dict WHERE phonetic GLOB '*[βðɣ]*'"),
        "含 ʎ(区分 ll,与 yeísmo 冲突)":
            q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%ʎ%'"),
        "含 ʝ(yeísmo)": q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%ʝ%'"),
        "含连结弧 t͡ʃ(展示层会去掉)":
            q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%'||char(865)||'%'"),
        "含 w̝(hu+元音规则产物)":
            q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%'||char(797)||'%'"),
        "含音节点 .(展示层会去掉)":
            q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%.%'"),
        "含长音符 ː(展示层会去掉)": q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%ː%'"),
        "含方括号 [(展示层会剥)": q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%[%'"),
        "含斜杠 /(库已改存裸串,残留)": q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%/%'"),
        "含正字法残留字母 c/q/v":
            q1(conn, f"SELECT count(*) FROM dict WHERE {H} AND phonetic GLOB '*[cqv]*'"),
        "无重音符 ˈ": q1(conn, f"SELECT count(*) FROM dict WHERE {H} AND phonetic NOT LIKE '%ˈ%'"),
        # ↓ 2026-07-31 抽样审计当场挖出来的两族,单列统计交评审确认
        "浊塞音 ɡ/b/d 紧跟清辅音(疑似 coda 浊化过度)":
            q1(conn, "SELECT count(*) FROM dict WHERE phonetic GLOB '*[ɡbd][ptkθsfx]*'"),
        "  └ 其中 ɡt(如 acto→ˈaɡto)": q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%ɡt%'"),
        "  └ 其中 ɡs(如 taxi→ˈtaɡsi,x=ks 再浊化)":
            q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%ɡs%'"),
        "  └ 其中 bt(如 apto→ˈabto)": q1(conn, "SELECT count(*) FROM dict WHERE phonetic LIKE '%bt%'"),
        "多词条目(音标含空格)": q1(conn, f"SELECT count(*) FROM dict WHERE {H} AND phonetic LIKE '% %'"),
        "  └ 多词且含次重音 ˌ(疑似非末词被降级为次重音)":
            q1(conn, f"SELECT count(*) FROM dict WHERE {H} AND phonetic LIKE '% %' "
                     "AND phonetic LIKE '%ˌ%'"),
        "缺音标(lemma)":
            q1(conn, f"SELECT count(*) FROM dict WHERE is_lemma=1 AND NOT ({H})"),
        "缺音标(变形层)":
            q1(conn, f"SELECT count(*) FROM dict WHERE is_lemma=0 AND NOT ({H})"),
    }
    S = "SELECT word, phonetic, is_lemma FROM dict WHERE "
    ex = {
        "含近音 β/ð/ɣ 的(多来自 kaikki lemma)":
            samples(conn, S + "phonetic GLOB '*[βðɣ]*' AND is_lemma=1"),
        "同类词但走规则生成的变形层(看是否与上面写法不一致)":
            samples(conn, S + "is_lemma=0 AND phonetic LIKE '%b%'"),
        "含 ʎ 的(与 ll→ʝ 规则冲突?)": samples(conn, S + "phonetic LIKE '%ʎ%'"),
        "含 w̝ 的(hu+元音)": samples(conn, S + "phonetic LIKE '%'||char(797)||'%'"),
        "含正字法残留 c/q/v 的": samples(conn, S + "phonetic GLOB '*[cqv]*'", 12),
        "无重音符 ˈ 的": samples(conn, S + "TRIM(COALESCE(phonetic,''))<>'' "
                                          "AND phonetic NOT LIKE '%ˈ%'", 12),
        "含音节点 . 的": samples(conn, S + "phonetic LIKE '%.%'"),
        "含方括号/斜杠残留的":
            samples(conn, S + "phonetic LIKE '%[%' OR phonetic LIKE '%/%'"),
        "含 ks(字母 x 的规则产物)": samples(conn, S + "phonetic LIKE '%ks%' AND is_lemma=1"),
        "普通高频词(对照组,应当没问题)":
            samples(conn, S + "is_lemma=1 AND level='A1' AND phonetic LIKE '%ˈ%'", 12),
        # ↓ 抽样审计挖出的两族,附真实例词请评审判定是不是缺陷
        "浊塞音紧跟清辅音(ɡt/bt 类,请判定对错)":
            samples(conn, S + "phonetic GLOB '*[ɡb][tkθs]*' AND is_lemma=1", 14),
        "多词条目里出现次重音 ˌ(请判定非末词该标 ˈ 还是 ˌ)":
            samples(conn, S + "phonetic LIKE '% %' AND phonetic LIKE '%ˌ%'", 12),
    }
    conn.close()
    return stats, ex


def extract_ts():
    """③ 展示层映射源码:从 spanish.ts 里抠出两个函数,原样喂,不转述。"""
    src = TS.read_text(encoding="utf-8")
    out = []
    for fn in ("seseoLatam", "normalizeSpanishIpa"):
        m = re.search(r"(?:^//[^\n]*\n)*^function " + fn + r"\b.*?^}", src, re.S | re.M)
        if m:
            out.append(m.group(0))
    return "\n\n".join(out)


def build_material(audit_path=None):
    stats, ex = build_corpus()
    g2p_src = (HERE / "b_ipa.py").read_text(encoding="utf-8")

    parts = ["## ① 口径约定", """
- 目标口径:半岛(Castilian)**音位式**转写,对齐 kaikki/Wiktextract 的西语约定。
- 数据来源分两层,**写法必须一致**,否则同一个词根在原形和变位形下长得不一样:
    lemma 层(10.5万):音标主要来自 kaikki,少量外来词交豆包补;
    变形层(66万):由本仓 b_ipa.py 规则 G2P 生成(拿 14 万有 kaikki 真值的词自证过,准确率 98.42%)。
- 库内 phonetic **存裸串**(不带斜杠);展示层再套 /.../ 给用户看。
- 展示层还会派生一条拉美音(seseo)与半岛音并列显示。
""", "## ② 规则 G2P 源码(es/b_ipa.py,变形层 66 万条音标由它生成)", "```python\n" + g2p_src + "\n```",
             "## ③ 展示层映射源码(packages/dict-core/src/spanish.ts,用户看到的是它的输出)",
             "```typescript\n" + extract_ts() + "\n```",
             "## ④ 全库真实统计(现查,不是估计)"]
    parts.append("\n".join(f"- {k}: {v:,}" for k, v in stats.items()))
    parts.append("\n## ⑤ 真实例词(从库里现抽 —— **你只能引用这些词**)")
    for k, v in ex.items():
        parts.append(f"\n**{k}**\n" + "\n".join(f"  - {x}" for x in v))

    if audit_path:
        parts.append(build_audit_section(audit_path))
    return "\n".join(parts)


def build_audit_section(path):
    """⑥ 抽样审计实证:把 verify_v4pro.py --ipa 判出来的真实缺陷喂进来。"""
    p = Path(path)
    if not p.is_absolute():
        p = HERE / p
    lines = [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
    meta = lines[0]
    recs = [r for r in lines[1:]]
    LAB = {"A": "音位错", "B": "重音错", "C": "拼写残留", "D": "整体读错", "E": "其他"}
    out = [f"\n## ⑥ 抽样审计实证结果(deepseek-v4-pro 判 {meta.get('n')} 条真实词条)",
           "这是**用户实际会看到的错**。规则评审的结论必须能解释这些,或说明为什么它们不重要。",
           "\n各分层标出率:"]
    for st, c in (meta.get("strata") or {}).items():
        n, bad, nv = c.get("n", 0), c.get("bad", 0), c.get("novote", 0)
        eff = n - nv
        out.append(f"- {st}: {n} 条,标出 {bad} 条 ({100*bad/max(eff,1):.2f}%)")
    cc = Counter(r.get("c") for r in recs)
    out.append("\n缺陷分类:")
    for ch, n in cc.most_common():
        out.append(f"- {ch} {LAB.get(ch,ch)}: {n} 条")
    out.append("\n判官标出的**具体条目**(词形 / 当前音标 / 判官建议 / 理由):")
    for r in recs[:70]:
        out.append(f"  - [{r.get('c')}] {r.get('w')} / {r.get('ipa')} / "
                   f"建议 {r.get('sug') or '—'} / {r.get('why')}")
    if len(recs) > 70:
        out.append(f"  …(另有 {len(recs)-70} 条同类,略)")
    return "\n".join(out)


# ---------------------------------------------------------------- 调用

async def ark_call(env, material):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
    r = await cl.chat.completions.create(
        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": material}])
    await cl.close()
    u = r.usage
    return r.choices[0].message.content, (getattr(u, "prompt_tokens", 0),
                                          getattr(u, "completion_tokens", 0))


async def ds_call(env, material):
    import httpx
    cl = httpx.AsyncClient(timeout=httpx.Timeout(1800.0))
    r = await cl.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {env['DEEPSEEK_API_KEY']}",
                 "Content-Type": "application/json"},
        json={"model": "deepseek-v4-pro",
              "messages": [{"role": "system", "content": SYS},
                           {"role": "user", "content": material}],
              "temperature": 0, "response_format": {"type": "json_object"},
              # 评审是重推理任务,必须开思考(见 verify_v4pro.py 文件头负控表)
              "thinking": {"type": "enabled"}, "stream": False})
    await cl.aclose()
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    d = json.loads(r.text.lstrip())
    u = d.get("usage") or {}
    return (d["choices"][0]["message"]["content"],
            (u.get("prompt_tokens", 0), u.get("completion_tokens", 0)))


def parse(txt):
    s = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
    if "{" in s:
        s = s[s.find("{"):s.rfind("}") + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {"findings": [], "overall": "(解析失败)", "_raw": txt[:2000]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", help="verify_v4pro.py --ipa 产出的 jsonl(支持通配)")
    ap.add_argument("--only", choices=["ds", "ark"])
    a = ap.parse_args()

    audit = None
    if a.audit:
        hits = sorted(glob.glob(str(HERE / a.audit))) or sorted(glob.glob(a.audit))
        if not hits:
            raise SystemExit(f"找不到审计文件: {a.audit}")
        audit = hits[-1]
        print(f"带入抽样实证: {Path(audit).name}")

    material = build_material(audit)
    RUNS.mkdir(exist_ok=True)
    (RUNS / "ipa_review_material.md").write_text(material, encoding="utf-8")
    print(f"材料 {len(material):,} 字符 → runs/ipa_review_material.md")

    env = load_env()
    tags = [a.only] if a.only else ["ds", "ark"]

    async def go():
        async def one(t):
            try:
                return await (ds_call(env, material) if t == "ds" else ark_call(env, material))
            except Exception as e:
                print(f"  ✗ [{t}] {type(e).__name__}: {str(e)[:200]}", flush=True)
                return None, (0, 0)
        return await asyncio.gather(*[one(t) for t in tags])

    t0 = time.time()
    res = asyncio.run(go())
    print(f"两家返回,用时 {time.time()-t0:.0f}s")

    out = {}
    for tag, (txt, tk) in zip(tags, res):
        out[tag] = parse(txt) if txt else {"findings": [], "overall": "(调用失败)"}
        out[tag]["_tokens"] = list(tk)

    outp = RUNS / f"ipa_review_{time.strftime('%Y%m%d-%H%M')}.json"
    outp.write_text(json.dumps(dict(audit=Path(audit).name if audit else None, result=out),
                               ensure_ascii=False, indent=1), encoding="utf-8")

    NAME = {"ds": "deepseek-v4-pro", "ark": "豆包2.1pro"}
    for tag in tags:
        r = out[tag]
        fs = r.get("findings") or []
        print("\n" + "=" * 76)
        print(f"【{NAME[tag]}】{len(fs)} 条  (token 入 {r['_tokens'][0]:,} 出 {r['_tokens'][1]:,})")
        print("=" * 76)
        print(f"总评: {r.get('overall','')}\n")
        for i, f in enumerate(fs, 1):
            print(f" {i}. [{f.get('where','?')}/{f.get('conf','?')}] {f.get('id','')}")
            print(f"    缺陷: {f.get('what','')}")
            print(f"    凭据: {f.get('ev','')}")
            print(f"    影响: {f.get('impact','')}")
            print(f"    改法: {f.get('fix','')}")
    if len(tags) == 2:
        ids = {t: {f.get("id") for f in (out[t].get("findings") or [])} for t in tags}
        both = ids["ds"] & ids["ark"]
        print("\n" + "=" * 76)
        print(f"两家都提到的 id: {sorted(both) if both else '(无同名 id)'}")
        print("⚠️ id 相同**不等于**结论相同 —— 必须逐条读 fix 再判,"
              "en 那次两家都说'分英美处理'但做法完全相反。")
    print(f"\n→ {outp.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
