#!/usr/bin/env python3
"""es coda 清音规则的**双家评审** —— 豆包 pro + DeepSeek v4-pro，各自独立。2026-08-01。

用户 2026-08-01 的要求：关键判断与重要规则的编写不能独断，必要时同时咨询两家，
但最终决断权在我。本脚本就是那次咨询的载体。

═══ 设计遵守判官纪律（见 llm-as-evaluator-discipline）═══
⑦ v4-pro **开思考**（这是推导型任务）；
⑧ **把本词典的约定明确写进 prompt**（跟 RAE 标准写清音、擦音归塞音、不标音节点）——
   不给逐条答案，但给约定，否则会因不知道我们的记法而连片误报；
⑨ **材料标题不写结论**：不说"我认为这条规则是对的"，只给规则与样本；
⑩ 逐行事实能确定性回源的部分**不问模型** —— 所以问的是**规则本身有没有洞**，
   以及**哪些输出看着不对**，而不是"这个词的音标是什么"；
② 两家的数字不相减，各自独立看。

═══ 可核验性 ═══
样本里混了三类行（规则改了 / 规则故意跳过 / 本来就不涉及），
**它们的西语版真值我手上有但不给模型看** —— 模型标出的"错"回头拿西语版对，
就能算出各自的精确率，而不是听它们自说自话。

用法（在 es/ 目录）：
  python3 review_coda_rule.py --build     # 只生成材料，看看要发什么
  python3 review_coda_rule.py --run       # 两家各跑一次，落盘
  python3 review_coda_rule.py --score     # 拿西语版真值给两家的标注打分
"""
import argparse
import asyncio
import gzip
import json
import random
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

import httpx

import ipa_norm as N

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
EDITION = paths.EDITION   # 见 dumps/README.md
ENV = paths.ENV
OUT = paths.WORK / "runs" / "coda_rule_review.json"

RULE_DOC = """【本词典的西语音标约定】
1. 只存音位式，不存严式；不标音节点、不标长音符、不带连结弧。
2. 擦音变体归音位：ð→d、β→b、ɣ→ɡ、ŋ→n（RAE 教学式写 /b d ɡ n/，不写同位异音）。
3. 音节末（coda）由清音字母派生的塞音写**清音**，跟 RAE 标准；
   英文版维基那边写的是口语浊化形（raptor→rabˈtoɾ），本词典不采用。
4. 存裸串，展示层再加斜杠。

【规则 devoice_coda 的算法】
输入：词形 word、已完成第 1、2 条归一化的音位式串 s。
① 从**词形拼写**取出处于 coda 的塞音字母序列，按出现顺序，映射到目标音位：
   p→p, t→t, c/k/q→k, b/v→b, d→d, g→ɡ
   判定：该字母后面紧跟一个辅音字母，且这个辅音**不是 h**
   （h 要跳过：`ch` 是二合字母 /t͡ʃ/，其余位置 h 不发音）。
② 从**音位式**取出处于 coda 的塞音（p b t d k ɡ）位置，按出现顺序。
   判定：该音段后面紧跟的音段**不是**元音 a e i o u、不是滑音 j w、
   不是 ʃ ʒ（塞音+ʃ 是塞擦音 t͡ʃ，不是 coda）。
③ **两个序列长度相等才动手**，逐位把音位式里的塞音替换成词形给出的目标音位；
   长度不等则**整条不动**（x→/ks/ 一对多、缩写按字母名读、静音字母等情况）。
④ 改完若**产生了原本没有的叠塞音**（西语音系不允许 /pp tt kk/），整条不动
   —— 外来词 vedette / yuppie / rockers 的双写字母会撞上本规则。

【全量实测】76.3 万行中该规则改动 19,967 行；两侧长度不等而跳过 2,985 行、
因叠塞音而跳过 664 行。

⚠️ 本文档已更新到**当前**规则。2026-08-01 那次评审送出的是更早一版，
   当时 ① 还额外排除了流音 l/r —— 豆包正是据此指出 `tl`/`dl` 族被漏掉，
   回西语版 dump 核实后已采纳并去掉了该排除。"""

SYS = """你是西班牙语音系与词典编纂专家。下面给你一条本词典正在使用的音标归一化规则，
以及它在真实数据上的一批输出（含它改过的、它故意跳过的、以及它不涉及的）。

请做两件事，严格输出 JSON：
{
 "rule_holes": [
   {"issue":"规则的什么情况没考虑到","example_words":["具体西语词1","词2"],"why":"为什么会出错","severity":"high|medium|low"}
 ],
 "wrong_outputs": [
   {"i":样本序号,"should_be":"你认为正确的音位式","why":"理由"}
 ],
 "convention_comment": "对『coda 写清音』这个约定选择本身的看法，一两句"
}

要求：
- rule_holes 必须给出**真实存在的西语词**作为反例，不要举抽象的可能性；举不出词就别写这一条。
- wrong_outputs 只标你确信写错了的；没有就给空数组。别为了凑数。
- 判断依据是西班牙语标准音（RAE / 半岛音，区分 θ/s），不是拉美音，也不是口语弱化形。
- 不要评论音节点、斜杠、严式这些已在约定里写明的记法选择。"""


def load_env():
    env = {}
    for ln in open(ENV, encoding="utf-8"):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def loads_lenient(s):
    s = re.sub(r"^```(json)?|```$", "", s.strip(), flags=re.M).strip()
    if "{" in s:
        s = s[s.find("{"):s.rfind("}") + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        f = re.sub(r'}\s*\n\s*(")', r'},\n\1', s)
        f = re.sub(r',\s*([}\]])', r'\1', f)
        return json.loads(f)


def _bare(s):
    """去所有结合附加符与音节点 —— 只用于把西语版真值拉到可比形态。"""
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace(".", "")


def build(n_changed=34, n_skipped=10, n_plain=8, seed=11):
    random.seed(seed)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT word, phonetic FROM dict "
                        "WHERE TRIM(COALESCE(phonetic,''))<>''").fetchall()
    conn.close()
    changed, skipped, plain = [], [], []
    seen = set()
    for w, p in rows:
        if w in seen or not w.isalpha():
            continue
        seen.add(w)
        cc = N.spirants_to_stops(N.basic(N.strip_narrow(p)))
        d = N.devoice_coda(w, cc)
        want, pos = N._coda_stops_from_spelling(w), N._coda_stop_positions(cc)
        if d != cc:
            changed.append((w, p, d))
        elif want and len(want) != len(pos):
            skipped.append((w, p, cc))
        elif not want and not pos:
            plain.append((w, p, N.normalize(w, p)))
    pick = ([("改动", *x) for x in random.sample(changed, min(n_changed, len(changed)))]
            + [("跳过", *x) for x in random.sample(skipped, min(n_skipped, len(skipped)))]
            + [("不涉及", *x) for x in random.sample(plain, min(n_plain, len(plain)))])
    random.shuffle(pick)
    samples = [{"i": i, "词": w, "英文版维基原值": p, "本词典输出": d}
               for i, (_, w, p, d) in enumerate(pick, 1)]
    truth = {w: None for _, w, _, _ in pick}
    return pick, samples, truth


def fill_truth(truth):
    """从西语版 dump 取真值 —— **不进 payload**，只用于事后打分。"""
    want = set(truth)
    with gzip.open(EDITION, "rt", encoding="utf-8", errors="replace") as f:
        for ln in f:
            if not want:
                break
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            w = d.get("word")
            if w not in want:
                continue
            for s in (d.get("sounds") or []):
                tg = set(s.get("tags") or [])
                if "seseante" in tg and "no seseante" not in tg:
                    continue
                m = re.match(r"\s*[\\/\[]([^\\/\]]+)[\\/\]]", s.get("ipa") or "")
                if m:
                    truth[w] = _bare(m.group(1))
                    want.discard(w)
                    break
    return truth


async def ask_v4pro(key, payload):
    async with httpx.AsyncClient(timeout=900) as cl:
        r = await cl.post("https://api.deepseek.com/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": "deepseek-v4-pro",
                                "messages": [{"role": "system", "content": SYS},
                                             {"role": "user", "content": payload}],
                                "temperature": 0,
                                "response_format": {"type": "json_object"},
                                "thinking": {"type": "enabled"},   # 纪律⑦：推导型任务必须开
                                "stream": False})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        d = json.loads(r.text.lstrip())
        return d["choices"][0]["message"]["content"], d.get("usage") or {}


async def ask_doubao(env, payload):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=900)
    r = await cl.chat.completions.create(
        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
        thinking={"type": "enabled"},
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": payload}])
    return r.choices[0].message.content, {"prompt_tokens": r.usage.prompt_tokens,
                                          "completion_tokens": r.usage.completion_tokens}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()

    pick, samples, truth = build()
    payload = RULE_DOC + "\n\n【真实输出样本】\n" + json.dumps(samples, ensure_ascii=False, indent=1)

    if a.build or not (a.run or a.score):
        print(payload[:2600])
        print(f"\n… 共 {len(samples)} 条样本（改动/跳过/不涉及混排），payload 约 {len(payload):,} 字符")
        return

    if a.run:
        env = load_env()
        OUT.parent.mkdir(exist_ok=True)

        async def go():
            t0 = time.time()
            res = await asyncio.gather(
                ask_v4pro(env["DEEPSEEK_API_KEY"], payload),
                ask_doubao(env, payload), return_exceptions=True)
            print(f"两家跑完 {time.time()-t0:.0f}s")
            return res

        (v4, dou) = asyncio.run(go())
        rec = {"samples": samples, "ts": time.strftime("%Y-%m-%d %H:%M")}
        for name, r in (("v4pro", v4), ("doubao", dou)):
            if isinstance(r, Exception):
                print(f"🔴 {name} 失败：{r}")
                rec[name] = {"error": str(r)}
            else:
                txt, u = r
                rec[name] = {"raw": txt, "usage": u}
                print(f"■ {name} 用量 {u}")
        OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {OUT}")

    if a.score or a.run:
        rec = json.loads(OUT.read_text(encoding="utf-8"))
        fill_truth(truth)
        have = sum(1 for v in truth.values() if v)
        print(f"\n■ 西语版真值覆盖 {have}/{len(truth)} 个样本词（其余无法判分）")
        byi = {s["i"]: s for s in rec["samples"]}
        for name in ("v4pro", "doubao"):
            r = rec.get(name) or {}
            if "raw" not in r:
                continue
            try:
                d = loads_lenient(r["raw"])
            except Exception as e:
                print(f"🔴 {name} 解析失败：{e}")
                continue
            print(f"\n{'='*72}\n■ {name}")
            print(f"  约定评价：{d.get('convention_comment','(无)')}")
            holes = d.get("rule_holes") or []
            print(f"  指出的规则漏洞 {len(holes)} 条：")
            for h in holes:
                print(f"    [{h.get('severity','?')}] {h.get('issue','')}")
                print(f"        举例 {h.get('example_words')}  ← {h.get('why','')[:90]}")
            wr = d.get("wrong_outputs") or []
            ok = bad = unk = 0
            print(f"  标为错误的输出 {len(wr)} 条（拿西语版真值核）：")
            for x in wr:
                s = byi.get(x.get("i"))
                if not s:
                    continue
                t = truth.get(s["词"])
                prop = _bare(x.get("should_be", ""))
                if not t:
                    unk += 1
                    mark = "?无真值"
                elif prop == t:
                    ok += 1
                    mark = "✓它对"
                elif _bare(s["本词典输出"]) == t:
                    bad += 1
                    mark = "✗误报"
                else:
                    unk += 1
                    mark = "?都不等"
                print(f"    {mark}  {s['词'][:20]:22} 我们 {s['本词典输出'][:22]:24} "
                      f"它说 {str(x.get('should_be'))[:22]:24} 西语版 {str(t)[:22]}")
            print(f"  → 有真值可判的里：它对 {ok} / 误报 {bad} / 无法判 {unk}")


if __name__ == "__main__":
    main()
