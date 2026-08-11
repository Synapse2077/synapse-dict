#!/usr/bin/env python3
"""审计 `sense_add` 那 1,963 条补收义项的中文质量。2026-08-11。

═══ 为什么单独写这个 ═══
2026-08-10 补收了 1,963 条 dump 里有、库里没有的义项，中文由 flash 生成（1,888 条）
和模板生成（75 条）。当天只跑了**格式**检查（元描述泄漏 / 句末标点 / 学名照抄，全 0），
**准确性一条没核过**。而随手 15 条随机样本里就撞到两个真错：
  · `alpes`  「Montes muy altos」(很高的山) → 中文写成「至高者（对上帝的称呼）」＝纯幻觉
  · `peón`   「pawn / checker」(棋子) 被判重并进了已有的「行人。」＝**义项错配**
⇒ 必须量。

═══ 两个面，性质不同，分开处理 ═══
① **判重合并面（186 条）**：`dup_zh` 非空且 ≠ 自己的 zh。风险是**错配**（把 A 义并进 B 义），
   后果比翻错一个词严重得多（用户 2026-08-07：「不要把义项和释义错配了，那才是真灾难」）。
   数量小 ⇒ **全量普查，不抽样**。
② **独立成条面（1,757 条）**：风险是**翻错/幻觉**。数量大 ⇒ 分层抽样。
   分层按「模型容易出错的类型」切：专名 / 学名生物 / 缩写符号 / 子义(有 parent) / 普通词。

模板生成的 75 条不送模型 —— 那是确定性字符串替换，`--tmpl` 用规则全量回核。

═══ 🔴 尺子的尺子 ═══
判官不是真值（纪律①）。所以每一批里掺进去：
  · **负控**：把 A 词的中文安到 B 词的原文上（跨词性、跨语义域），本应 100% 被判 bad。
    抓不住 ⇒ 判官在摆烂，这轮数字全部作废（v4-pro 关思考在 es 上 0/2 摆烂过）。
  · **正控**：`sense_gloss` 里 `es-edition` 原生、且中文来自更早已验收批次的条目，本应基本判 ok。
    正控 bad 率就是**判官自噪底**，最终 bad 率要减掉它才有意义。
负控/正控在 payload 里与真样本**完全同形**，判官分不出来。

两家独立跑（v4-pro + 豆包 pro，都**开思考** —— 这是推导型判断，纪律⑦）。
两家都判 bad ⇒ 高置信；只有一家 ⇒ 进人工裁决清单。**不取平均、不相减**。

用法（在 es/ 目录）：
    python3 probes/audit_sense_gap_zh.py --tmpl              # 模板 75 条，确定性回核，不花钱
    python3 probes/audit_sense_gap_zh.py --build             # 只看抽样构成
    python3 probes/audit_sense_gap_zh.py --run --n 250       # 真跑
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import collections
import json
import random
import re
import sqlite3
import time

import httpx

import paths

OUT = paths.WORK / "runs" / "sense_gap_zh_audit.json"
CHUNK = 25
SEED = 20260811

# ── 学名判据：属名首字母大写 + 种加词小写（Picconia excelsa / Solanum rostratum）
SCI = re.compile(r"\b[A-Z][a-z]{2,} +[a-z]{3,}\b")


# ═══════════════════════════════════════════════════════════════════
#  取数
# ═══════════════════════════════════════════════════════════════════
def rows(con):
    return [dict(r) for r in con.execute("""
        SELECT id, word, lang, pos, gloss, zh, zh_src, dup_zh, meta, src
          FROM sense_add WHERE TRIM(COALESCE(zh,''))<>''
    """)]


def stratum(r):
    """样本分层 —— 按「模型在哪类东西上容易出错」切，不按数据来源切。"""
    if r["pos"] in ("abbrev", "symbol", "character"):
        return "缩写符号"
    if SCI.search(r["gloss"] or ""):
        return "学名生物"
    if r["pos"] == "name":
        return "专名"
    if "parent" in (r["meta"] or ""):
        return "子义"
    return "普通词"


def parent_of(r):
    try:
        return (json.loads(r["meta"] or "{}") or {}).get("parent")
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
#  负控 / 正控
# ═══════════════════════════════════════════════════════════════════
def make_negctl(pool, k, rnd):
    """错配负控：把中文换成**另一个语义域完全无关**的词的中文。
    为了不制造「碰巧也对」的假负控，两条必须词性不同且中文无公共字。"""
    out, tries = [], 0
    while len(out) < k and tries < k * 200:
        tries += 1
        a, b = rnd.sample(pool, 2)
        if a["pos"] == b["pos"]:
            continue
        if set(a["zh"]) & set(b["zh"]):
            continue
        out.append({**a, "zh": b["zh"], "_ctl": "neg", "_truth": b["word"]})
    return out


def make_posctl(con, k, rnd):
    """正控：已验收批次里 es 原文 + 中文成对的义项（同形喂给判官）。
    这些是 8 月初那轮跑完并抽验过的，判官在它们身上的 bad 率＝自噪底。"""
    cand = con.execute("""
        SELECT d.word AS word, s.pos AS pos, ge.text AS gloss, gz.text AS zh
          FROM sense s
          JOIN dict d          ON d.id = s.word_id
          JOIN sense_gloss ge  ON ge.sense_id = s.id AND ge.lang='es' AND ge.src='es-edition'
          JOIN sense_gloss gz  ON gz.sense_id = s.id AND gz.lang='zh' AND gz.src='llm-doubao'
         WHERE LENGTH(ge.text) BETWEEN 20 AND 120
           AND s.id NOT IN (SELECT sense_id FROM sense_gloss WHERE src='sense_add')
         LIMIT 4000""").fetchall()
    cand = [dict(c) for c in cand]
    rnd.shuffle(cand)
    return [{**c, "lang": "es", "meta": None, "id": -1,
             "_ctl": "pos", "_truth": None} for c in cand[:k]]


# ═══════════════════════════════════════════════════════════════════
#  Prompt
# ═══════════════════════════════════════════════════════════════════
SYS_TRANS = """你在校对一部**西班牙语→中文**学习词典的义项中文释义。产品是划词弹窗，
用户是中国的西语学习者。

每条给你：
  word    西班牙语词
  pos     词性
  src     原文语言（en＝英文版维基词典的 gloss，es＝西语版维基词典的定义）
  gloss   **原文（权威源真值，一切以它为准）**
  parent  该义项在原文里的上位义（可能没有）
  zh      我们生成的中文释义（**被审对象**）

判 `zh` 是否忠实于 `gloss`。判据，按严重度：
  bad   —— 所指错了。包括：译成了另一个意思、凭空编造原文没有的内容、
           张冠李戴（把别的词的意思写上去）、上位义与本义搞反。
  weak  —— 所指对，但有明显缺陷：过度笼统到失去区分度、把学名硬造成不存在的中文名、
           漏掉 gloss 里的限定成分（地域/领域/时代）导致会误导学习者。
  ok    —— 所指正确。**措辞风格、详略、是否带括注一律不算问题**；
           中文里保留学名/原文拉丁名是允许的；只要中国学习者读了能对上原文的意思就是 ok。

⚠️ 你的任务**不是**改写得更好，是判断有没有错。宁可判 ok 也不要因为「我会译得更漂亮」判 weak。
⚠️ 专名（地名/人名/星座/机构）只要音译合理、括注的地理或范畴信息与 gloss 一致，就是 ok。

严格输出 JSON，不要解释文字：
{"v":[{"id":<原样回传的 id>,"r":"ok|weak|bad","why":"仅当 weak/bad 时给不超过25字的理由"}]}"""

SYS_MERGE = """你在校对一部**西班牙语→中文**学习词典的**义项合并**决定。

我们从词典源里补收了一些义项，其中一部分被判定为「与该词已有的某条义项是同一个意思」，
于是**并进了那条已有义项**（并进去之后，两边的释义会在同一个义项下并排显示）。
现在请你复核这个合并对不对。

每条给你：
  word    西班牙语词
  pos     词性
  gloss   **补收义项的原文（权威源真值）**
  target  它被并进去的那条已有义项的中文释义

判据：
  bad   —— 两者是**不同的所指**，合并会造成义项错配（例：「棋子」并进「行人」）。
  weak  —— 同一大类但补收的是明显更具体的独立小义，合并会淹没它
           （例：具体某一种植物并进「多种植物的统称」尚可接受；但若 target 的统称
             与该物种明显不符，则算 bad）。
  ok    —— 同一所指，合并正确。措辞详略不同不算问题；
           target 更概括、gloss 更具体但确实属于 target 所指范围内的，算 ok。

严格输出 JSON，不要解释文字：
{"v":[{"id":<原样回传的 id>,"r":"ok|weak|bad","why":"仅当 weak/bad 时给不超过25字的理由"}]}"""


def payload_trans(r):
    d = {"id": r["id"], "word": r["word"], "pos": r["pos"],
         "src": r["lang"], "gloss": r["gloss"], "zh": r["zh"]}
    p = parent_of(r)
    if p:
        d["parent"] = p
    return d


def payload_merge(r):
    return {"id": r["id"], "word": r["word"], "pos": r["pos"],
            "gloss": r["gloss"], "target": r["dup_zh"]}


# ═══════════════════════════════════════════════════════════════════
#  模型
# ═══════════════════════════════════════════════════════════════════
def load_env():
    env = {}
    for ln in open(paths.ENV, encoding="utf-8"):
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
        f = re.sub(r"}\s*\n\s*(\{)", r"},\n\1", s)
        return json.loads(re.sub(r",\s*([}\]])", r"\1", f))


async def ask_v4pro(key, sys, body):
    async with httpx.AsyncClient(timeout=2400) as cl:
        r = await cl.post("https://api.deepseek.com/chat/completions",
                          headers={"Authorization": "Bearer " + key},
                          json={"model": "deepseek-v4-pro",
                                "messages": [{"role": "system", "content": sys},
                                             {"role": "user", "content": body}],
                                "temperature": 0,
                                "response_format": {"type": "json_object"},
                                "thinking": {"type": "enabled"}, "stream": False})
        if r.status_code != 200:
            raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
        return json.loads(r.text.lstrip())["choices"][0]["message"]["content"]


async def ask_doubao(env, sys, body):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=2400)
    r = await cl.chat.completions.create(
        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
        thinking={"type": "enabled"},
        messages=[{"role": "system", "content": sys},
                  {"role": "user", "content": body}])
    return r.choices[0].message.content


def collect(raws):
    out = {}
    for raw in raws:
        if isinstance(raw, Exception) or not raw:
            continue
        try:
            d = loads_lenient(raw)
        except Exception:
            continue
        for v in d.get("v") or []:
            if v.get("id") is not None:
                out[int(v["id"])] = (v.get("r", "?"), v.get("why", ""))
    return out


# ═══════════════════════════════════════════════════════════════════
#  模板 75 条：确定性回核（不花钱）
# ═══════════════════════════════════════════════════════════════════
#   措辞与 `translate_sense_gap.ES_TMPL` 一致 —— **故意手抄一遍不 import**：
#   import 就变成「拿代码核代码」，无论代入对不对都必然通过（纪律：量数据不量自己的转换器）。
#   这里核的是**代入**：`{}` 里的词根有没有从原文里正确抽出来（截短 / 括注 / 句点）。
#   八条模板的中文措辞本身我逐条看过，都对。
TMPL_RULES = [
    (r"^Grafía\s+obsoleta\s+de\s+(.+?)\.?$",        "{0} 的已废拼写"),
    (r"^Grafía\s+alternativa\s+de\s+(.+?)\.?$",     "{0} 的另一种写法"),
    (r"^Variante\s+(?:obsoleta\s+)?de\s+(.+?)\.?$", "{0} 的变体"),
    (r"^Apellido\.?$",                              "姓氏"),
    (r"^Nombre\s+de\s+pila\s+de\s+mujer\.?$",       "女性名"),
    (r"^Nombre\s+de\s+pila\s+de\s+varón\.?$",       "男性名"),
    (r"^Forma\s+femenina\s+de\s+(.+?)\.?$",         "{0} 的阴性形式"),
    (r"^Diminutivo\s+de\s+(.+?)\.?$",               "{0} 的指小形式"),
]


def check_tmpl(con):
    """模板那 75 条：原文 → 规则 → 期望中文，与库里逐字比。
    这是外锚闸性质的检查（锚在原文 + 写死的规则），不会过期。"""
    rs = [dict(r) for r in con.execute(
        "SELECT id, word, gloss, zh, zh_src FROM sense_add WHERE zh_src LIKE 'tmpl:%'")]
    print("■ 模板生成 %d 条 —— 确定性回核（原文 → 规则 → 期望值 逐字比）\n" % len(rs))
    bad, unmatched = [], []
    for r in rs:
        g = (r["gloss"] or "").strip()
        hit = None
        for pat, tpl in TMPL_RULES:
            m = re.match(pat, g)
            if m:
                # 括注（'mueble'）这类补充说明不进中文
                args = [re.sub(r"\s*\([^)]*\)\s*$", "", x).strip() for x in m.groups()]
                hit = tpl.format(*args) if args else tpl
                break
        if hit is None:
            unmatched.append(r)
        elif hit != (r["zh"] or "").strip():
            bad.append((r, hit))
    print("  规则命中 %d / 未命中 %d" % (len(rs) - len(unmatched), len(unmatched)))
    for r in unmatched:
        print("    ⚠️ 规则没覆盖：%-18s %s → %s" % (r["word"], r["gloss"], r["zh"]))
    if bad:
        print("\n  🔴 与期望值不符 %d 条：" % len(bad))
        for r, exp in bad:
            print("    %-18s 原文 %-40s 库里「%s」期望「%s」" % (r["word"], r["gloss"], r["zh"], exp))
    else:
        print("  ✅ 命中的全部与期望值逐字相同")
    return bad, unmatched


# ═══════════════════════════════════════════════════════════════════
def build(con, n, rnd):
    all_rows = rows(con)
    llm = [r for r in all_rows if r["zh_src"] == "llm-flash"]
    merge = [r for r in llm if (r["dup_zh"] or "") and r["dup_zh"] != r["zh"]]
    indep = [r for r in llm if r not in merge]

    by = collections.defaultdict(list)
    for r in indep:
        by[stratum(r)].append(r)

    # 按层比例抽，每层至少 25 条（层小于 25 就全取）
    picked = []
    for k, v in sorted(by.items(), key=lambda x: -len(x[1])):
        take = max(25, round(n * len(v) / len(indep)))
        take = min(take, len(v))
        picked += rnd.sample(v, take)
    return merge, indep, by, picked


def merge_redo(ids):
    """补跑判重面里上一轮没收到结果的那些条目。2026-08-11。

    🔴 只用 v4-pro：豆包在这个任务上负控只抓住 4/30（13%），整家作废。
    🔴 限并发 3：上一轮 42 个请求齐发，豆包直接 `RequestBurstTooFast` 挂掉 21 个，
       覆盖率变成随机的 —— 而"没收到"很容易被当成"没问题"。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT id, word, lang, pos, gloss, zh, dup_zh FROM sense_add "
        "WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)]
    con.close()
    env = load_env()
    sem = asyncio.Semaphore(3)

    async def one(chunk):
        async with sem:
            return await ask_v4pro(env["DEEPSEEK_API_KEY"], SYS_MERGE,
                                   json.dumps(chunk, ensure_ascii=False))

    async def go():
        cs = [[payload_merge(r) for r in rows[i:i + 12]] for i in range(0, len(rows), 12)]
        print("■ 补跑 %d 条，切 %d 块，并发上限 3…" % (len(rows), len(cs)))
        return await asyncio.gather(*[one(c) for c in cs], return_exceptions=True)

    res = asyncio.run(go())
    for x in res:
        if isinstance(x, Exception):
            print("   ✗ %s" % str(x)[:120])
    got = collect(res)
    print("■ 收到 %d/%d" % (len(got), len(rows)))

    # 并回既有结果文件（**只填空不覆盖**，别把上一轮的判决冲掉）
    d = json.loads(OUT.read_text(encoding="utf-8"))
    mv = d.setdefault("merge_v4", {})
    added = 0
    for k, v in got.items():
        if str(k) not in mv:
            mv[str(k)] = v
            added += 1
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 并入 %d 条新判决（已有的不覆盖）→ %s" % (added, OUT))

    by = {r["id"]: r for r in rows}
    for i, (v, why) in sorted(got.items()):
        if v in ("bad", "weak"):
            r = by.get(i, {})
            print("   %-4s %-18s %-40s ⇒「%s」 │ %s" % (
                v, r.get("word", ""), str(r.get("gloss", ""))[:40],
                str(r.get("dup_zh", ""))[:18], why[:30]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tmpl", action="store_true", help="只跑模板确定性回核")
    ap.add_argument("--build", action="store_true", help="只看抽样构成")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--merge-redo", metavar="IDS_JSON",
                    help="补跑判重面未覆盖的条目（v4-pro，限并发 3）")
    ap.add_argument("--n", type=int, default=250)
    a = ap.parse_args()

    if a.merge_redo:
        merge_redo(json.loads(open(a.merge_redo).read()))
        return

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    con.row_factory = sqlite3.Row

    if a.tmpl:
        check_tmpl(con)
        return

    rnd = random.Random(SEED)
    merge, indep, by, picked = build(con, a.n, rnd)

    print("■ `sense_add` 有中文的条目：%d" % len(rows(con)))
    print("  ① 判重合并面 %d 条 —— **全量普查**" % len(merge))
    print("  ② 独立成条面 %d 条 —— 分层抽 %d 条：" % (len(indep), len(picked)))
    cnt = collections.Counter(stratum(r) for r in picked)
    for k in sorted(by, key=lambda x: -len(by[x])):
        print("       %-6s 总 %5d → 抽 %3d  (%.0f%%)" % (
            k, len(by[k]), cnt[k], 100 * cnt[k] / len(by[k])))

    neg = make_negctl(indep, 30, rnd)
    pos = make_posctl(con, 20, rnd)
    print("  ③ 负控 %d 条（跨词性换中文，应 100%% 判 bad）" % len(neg))
    print("     正控 %d 条（已验收批次原样，bad 率＝判官自噪底）" % len(pos))

    if not a.run:
        print("\n样例：")
        for r in picked[:3]:
            print("  ", json.dumps(payload_trans(r), ensure_ascii=False))
        for r in merge[:2]:
            print("  ", json.dumps(payload_merge(r), ensure_ascii=False))
        return

    # ── 组装。负控/正控用负 id，与真样本混洗后同形送入
    trans_items = []
    for r in picked:
        trans_items.append((r["id"], payload_trans(r), "真"))
    for i, r in enumerate(neg):
        rr = {**r, "id": -1000 - i}
        trans_items.append((rr["id"], payload_trans(rr), "负控"))
    for i, r in enumerate(pos):
        rr = {**r, "id": -2000 - i}
        trans_items.append((rr["id"], payload_trans(rr), "正控"))
    rnd.shuffle(trans_items)
    kind = {i: k for i, _, k in trans_items}

    merge_items = [(r["id"], payload_merge(r)) for r in merge]

    env = load_env()
    t0 = time.time()

    def chunks(xs):
        return [xs[i:i + CHUNK] for i in range(0, len(xs), CHUNK)]

    async def go():
        tasks, tag = [], []
        for c in chunks([p for _, p, _ in trans_items]):
            b = json.dumps(c, ensure_ascii=False)
            tasks.append(ask_v4pro(env["DEEPSEEK_API_KEY"], SYS_TRANS, b)); tag.append(("T", "v4"))
            tasks.append(ask_doubao(env, SYS_TRANS, b));                    tag.append(("T", "db"))
        for c in chunks([p for _, p in merge_items]):
            b = json.dumps(c, ensure_ascii=False)
            tasks.append(ask_v4pro(env["DEEPSEEK_API_KEY"], SYS_MERGE, b)); tag.append(("M", "v4"))
            tasks.append(ask_doubao(env, SYS_MERGE, b));                    tag.append(("M", "db"))
        print("\n■ %d 个请求并行发出（开思考）…" % len(tasks))
        return tag, await asyncio.gather(*tasks, return_exceptions=True)

    tag, res = asyncio.run(go())
    nerr = sum(1 for x in res if isinstance(x, Exception))
    print("■ 跑完 %.0fs，失败 %d/%d" % (time.time() - t0, nerr, len(res)))
    for t, x in zip(tag, res):
        if isinstance(x, Exception):
            print("   ✗ %s/%s %s" % (t[0], t[1], str(x)[:120]))

    def pick(face, who):
        return collect([x for t, x in zip(tag, res) if t == (face, who)])

    out = {"trans": {"v4": pick("T", "v4"), "db": pick("T", "db")},
           "merge": {"v4": pick("M", "v4"), "db": pick("M", "db")},
           "kind": kind}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "trans_v4": {str(k): v for k, v in out["trans"]["v4"].items()},
        "trans_db": {str(k): v for k, v in out["trans"]["db"].items()},
        "merge_v4": {str(k): v for k, v in out["merge"]["v4"].items()},
        "merge_db": {str(k): v for k, v in out["merge"]["db"].items()},
        "kind": {str(k): v for k, v in kind.items()},
        "neg": [{"id": -1000 - i, "word": r["word"], "gloss": r["gloss"],
                 "zh": r["zh"], "truth": r["_truth"]} for i, r in enumerate(neg)],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    report(out, trans_items, merge_items, merge, picked)
    print("\n  明细 → %s" % OUT)


def report(out, trans_items, merge_items, merge, picked):
    tv, td = out["trans"]["v4"], out["trans"]["db"]
    kind = out["kind"]

    # ── 先验尺子：负控抓住了吗
    print("\n═══ 尺子自检 ═══")
    for who, d in (("v4-pro", tv), ("豆包pro", td)):
        neg = [i for i in kind if kind[i] == "负控"]
        pos = [i for i in kind if kind[i] == "正控"]
        nb = sum(1 for i in neg if d.get(i, ("?",))[0] == "bad")
        pb = sum(1 for i in pos if d.get(i, ("?",))[0] == "bad")
        pw = sum(1 for i in pos if d.get(i, ("?",))[0] == "weak")
        print("  %-8s 负控抓住 %d/%d (%.0f%%)   正控误判 bad %d/%d、weak %d" % (
            who, nb, len(neg), 100 * nb / max(1, len(neg)), pb, len(pos), pw))

    print("\n═══ ① 独立成条面（抽样 %d 条）═══" % len(picked))
    ids = [i for i in kind if kind[i] == "真"]
    verdict = {}
    for i in ids:
        a = tv.get(i, ("?",))[0]
        b = td.get(i, ("?",))[0]
        verdict[i] = (a, b)
    both_bad = [i for i in ids if verdict[i] == ("bad", "bad")]
    any_bad = [i for i in ids if "bad" in verdict[i]]
    any_weak = [i for i in ids if "weak" in verdict[i] and i not in any_bad]
    print("  两家都判 bad（高置信真错）：%3d  = %.1f%%" % (len(both_bad), 100 * len(both_bad) / max(1, len(ids))))
    print("  任一家判 bad（上界）：      %3d  = %.1f%%" % (len(any_bad), 100 * len(any_bad) / max(1, len(ids))))
    print("  任一家判 weak：            %3d" % len(any_weak))

    byid = {r["id"]: r for r in picked}
    st = collections.Counter(stratum(byid[i]) for i in any_bad if i in byid)
    if st:
        print("  bad 分布：%s" % dict(st))
    print("\n  两家都判 bad 的明细：")
    for i in both_bad[:40]:
        r = byid.get(i)
        if r:
            print("    %-20s %-45s → %-22s │ %s" % (
                r["word"], (r["gloss"] or "")[:45], (r["zh"] or "")[:22], tv[i][1][:26]))

    print("\n═══ ② 判重合并面（全量 %d 条）═══" % len(merge_items))
    mv, md = out["merge"]["v4"], out["merge"]["db"]
    mids = [i for i, _ in merge_items]
    mb = [i for i in mids if mv.get(i, ("?",))[0] == "bad" and md.get(i, ("?",))[0] == "bad"]
    ma = [i for i in mids if "bad" in (mv.get(i, ("?",))[0], md.get(i, ("?",))[0])]
    mw = [i for i in mids if "weak" in (mv.get(i, ("?",))[0], md.get(i, ("?",))[0]) and i not in ma]
    print("  两家都判错配：%3d  = %.1f%%" % (len(mb), 100 * len(mb) / max(1, len(mids))))
    print("  任一家判错配：%3d  = %.1f%%" % (len(ma), 100 * len(ma) / max(1, len(mids))))
    print("  任一家判 weak：%3d" % len(mw))
    bym = {r["id"]: r for r in merge}
    print("\n  两家都判错配的明细（这些要撤销合并）：")
    for i in mb:
        r = bym.get(i)
        if r:
            print("    %-20s %-42s ⇒ 并进「%s」 │ %s" % (
                r["word"], (r["gloss"] or "")[:42], (r["dup_zh"] or "")[:20], mv[i][1][:26]))


if __name__ == "__main__":
    main()
