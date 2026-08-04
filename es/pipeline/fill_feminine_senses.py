#!/usr/bin/env python3
"""补回被当成变形丢掉的「阴性对应词」义项。2026-08-03。

═══ 缺陷是怎么来的 ═══
kaikki 英文版里 **4,986 条** `female equivalent of X` 义项**带 `form-of` 标签**，
`build.py` 的 `DROP_TAGS = {"form-of","alt-of","combined-form"}` 把它们整族丢了。
判据本身没错（`performados` 那类指针必须丢），但这一族的 form-of 义项**承载的是词义本身**。

后果分两档（全量普查，不是抽样）：
| | 词数 | 用户看到什么 |
|---|---|---|
| **A** 中文只剩变形标签 | 4,387 | `amiga → amigo 的 阴性`。弹窗会内联原形释义，轻症 |
| **C** 有冷僻义排在前面 | **587** | `novia → 甜面包卷`、`gata → 劫车`、`tía → 姑娘，女人，小妞`、`maestra → 蜂王` |

🔴 **C 桶才是真伤**：不是没答案，是**错答案排在第一位**——看上去是个像样的释义，
   但那不是这个词最常用的意思。

⚠️ **这推翻了我 2026-08-02 的结论**。当时把 gata/buena/perra/maestra 判成
   "两家模型误报，原形已带该义"。原形确实带，但用户划的是 `gata`。

═══ 两步，先确定性后模型 ═══
**① `--zh`：中文版直接补**（人工源，零成本，可回滚）。
   只补**我们一个义项都对不上**的那些（判据沿用 `zh_translation_divergence` 的 L1/L2 两层）。
   🔴 中文版的三个坑必须先处理，否则补进来的是垃圾：
     · 跨语言污染：`mística` 的 `神秘论，神秘文学==葡萄牙語==\\n神秘` → 从 `==` 截断；
     · wikitext 残渣：`amiga` 拖着 `* 正體: Amiga 家用電腦` → 丢掉 `*` 开头的行；
     · 元描述里裹着真义：`novia → novio 的陰性等價詞：女朋友` → **取冒号后**，
       别整条丢（第一版就是整条丢，novia 因此被算成"中文版没有"）。

**② `--pro`：豆包 pro 关思考**，补 ① 覆盖不到的 C 桶。
   🔴 payload 必须给**原形的全部义项**，不能只给第一义 —— 这个坑已经咬过三次
   （doctorcito 模板 / ref_zh / 词根线索，见 [[flash-translation-validated]]）。
   `gato` 有 11 个义项（猫／千斤顶／井字棋／马德里人…），只有一部分能有阴性形式，
   **挑哪些是模型该干的活，选第一个是我替源头选义**。
   关思考：这是生成不是推导（用户 2026-08-03「开思考太贵」）。

═══ 三列怎么写（沿用 2026-08-02 `fixes/append_zh_senses.py` 定下的 schema）═══
    definition   留空行（那一列的性质是"英文版原值"，来源信息不进值里）
    translation  中文义项
    meta         追加 {"pos":…, "src":"zh-wiktionary"|"llm-doubao-fem", "batch":…}
落库前逐行对齐强校验 + `dbtool.align_check()`。

用法（在 es/ 目录）：
    python3 pipeline/fill_feminine_senses.py --scan
    python3 pipeline/fill_feminine_senses.py --zh   [--apply]
    python3 pipeline/fill_feminine_senses.py --pro  [--apply]
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import asyncio
import collections
import json
import re
import sqlite3
import time

import dbtool
import paths
from probes.zh_translation_divergence import META_GLOSS, agrees, shares_char, toks
from pipeline.translate_intake import clean_zh, load_env, loads_lenient

CAND = paths.WORK / "runs" / "feminine_candidates.json"
RAW = paths.WORK / "runs" / "feminine_pro.jsonl"
RAW_V4 = paths.WORK / "runs" / "feminine_v4pro.jsonl"
BATCH_ZH = "fem-zh-20260803"
BATCH_PRO = "fem-pro-20260803"
SRC_ZH = "zh-wiktionary"
SRC_PRO = "llm-doubao-fem"
SRC_V4 = "llm-v4pro-fem"


def raw_path(bucket, model):
    """C 桶的两个文件是先跑出来的，保留原名不改（改名等于把已花的钱作废重跑）。"""
    if bucket == "C":
        return RAW if model == "doubao" else RAW_V4
    return paths.WORK / "runs" / ("feminine_A_%s.jsonl" % model)


def base_levels(bases, words):
    """词 → 它原形的 CEFR。🔴 一次性全表取，别逐词查——`word` 列没索引，
    4,355 次单词查询＝ 4,355 次全表扫，我上一版就这么把自己卡了十几分钟。"""
    need = {bases.get(w, "") for w in words} - {""}
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    lv = {}
    for w, l, lem in conn.execute("SELECT word, level, is_lemma FROM dict"):
        if w in need and (w not in lv or lem):
            lv[w] = l
    conn.close()
    return {w: lv.get(bases.get(w, "")) for w in words}

EQ = re.compile(r"(?:fe)?male equivalent of ([^\s,:(]+)")
# 变形标签行：`amigo 的 阴性`、`amigar 的 陈述式·现在时·第三人称·单数`
LABEL = re.compile(r"^\S+ 的 [^ ]+$")
# 中文版把真义裹在元描述里：`novio 的陰性等價詞：女朋友`
FEM_COLON = re.compile(r"(?:陰性|阴性|陽性|阳性)(?:等價詞|等价词|形式|形)?\s*[：:]\s*(.+)")
POS_PREFIX = re.compile(r"^\s*(?:v[itr]?|n|adj|adv|prep|conj|pron|interj|num|art|m|f|mf)\.\s*", re.I)


# ═══ 家底 ═══

def scan_kaikki():
    """→ {词: 被丢掉的 female-equivalent gloss 列表}，以及原形词。"""
    out, base = {}, {}
    for ln in open(paths.KK, encoding="utf-8"):
        if "equivalent of" not in ln:
            continue
        e = json.loads(ln)
        if e.get("lang_code") != "es":
            continue
        got = []
        for s in e.get("senses", []):
            g = " ".join(s.get("glosses") or [])
            if "equivalent of" in g and "form-of" in set(s.get("tags") or []):
                got.append(g)
        if got:
            out.setdefault(e["word"], []).extend(got)
            m = EQ.search(got[0])
            if m:
                base.setdefault(e["word"], m.group(1))
    return out, base


def db_rows(words):
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = ("SELECT id, word, pos, is_lemma, definition, translation, meta, exchange "
         "FROM dict WHERE word IN (%s)" % ",".join("?" * len(words)))
    rows = conn.execute(q, list(words)).fetchall()
    conn.close()
    out = {}
    for rid, w, pos, lem, dfn, tr, mj, ex in rows:
        # 同词多行时取 is_lemma=1 那行；都不是就取第一行
        if w not in out or (lem and not out[w]["is_lemma"]):
            out[w] = {"id": rid, "word": w, "pos": pos or "", "is_lemma": lem,
                      "def": dfn or "", "tr": tr or "", "meta": mj or "",
                      "exchange": ex or ""}
    return out


def real_senses(tr):
    """我们这一行里**真的是释义**的那些（剔掉变形标签行）。"""
    return [x.strip() for x in tr.split("\n") if x.strip() and not LABEL.match(x.strip())]


def bucket(rows):
    A, C = [], []
    for w, r in rows.items():
        (C if real_senses(r["tr"]) else A).append(w)
    return sorted(A), sorted(C)


# ═══ ① 中文版 ═══

# 中文版还有一类元描述我原来的表没收：`bosnio 的变格（阴性单数）`
MORE_META = re.compile(r"的(?:变格|變格|变位形式|變位形式)")


def zh_senses():
    """→ {词: [干净的中文义项]}。中文版的坑都在这里处理，逐条都有实例。"""
    import zhconv
    d = collections.defaultdict(list)
    for ln in open(paths.WORK / "zh_es.jsonl", encoding="utf-8"):
        e = json.loads(ln)
        for s in e["senses"]:
            for g in s["g"]:
                for part in g.split("\n"):
                    part = part.split("==")[0].strip()      # 跨语言污染（mística）
                    if not part or part.startswith("*"):    # wikitext 残渣（amiga）
                        continue
                    m = FEM_COLON.search(part)
                    if m:
                        part = m.group(1).strip()           # 元描述裹着的真义（novia）
                    elif META_GLOSS.search(part) or MORE_META.search(part):
                        continue
                    part = POS_PREFIX.sub("", part).strip(" 。.")
                    # 🔴 落库必须转简：中文版繁简混排（`女護士` `雌鴨` `產卵道`），
                    #    而库里 76.7 万条译文全是简体。比对时 toks() 本来就转简，
                    #    但**存进去的是原文**——第一版就这么把繁体写进了预览。
                    part = zhconv.convert(part, "zh-cn")
                    # 体例：中文版用 [植]〈俗〉标域和语域，本库用（）
                    part = re.sub(r"[\[【〈<]([^\]】〉>]{1,6})[\]】〉>]", r"（\1）", part)
                    if part and toks(part):
                        d[e["word"]].append(part)
    return {k: list(dict.fromkeys(v)) for k, v in d.items()}


def novel(cands, ours):
    """留下我们一个义项都对不上的（L1 词级 / L2 共字，两层都不中才算新）。"""
    ot = [toks(x) for x in ours]
    out = []
    for c in cands:
        t = toks(c)
        if not t or any(agrees(t, o) or shares_char(t, o) for o in ot):
            continue
        if any(agrees(t, toks(x)) for x in out):     # 组内去重
            continue
        out.append(c)
    return out


# ═══ 落库 ═══

def append_plan(r, adds, src, batch):
    """三列同步追加；meta 缺失的行（is_lemma=0 那批）先按现有义项数补齐占位。"""
    try:
        meta = json.loads(r["meta"]) if r["meta"].strip() else []
    except Exception:
        return None, "meta 不是合法 JSON"
    tr_lines = [x for x in r["tr"].split("\n")] if r["tr"] else []
    df = r["def"]
    df_lines = [x for x in df.split("\n")] if df else []

    if meta and len(meta) != len(tr_lines):
        return None, "改前就没对齐 meta%d/tr%d" % (len(meta), len(tr_lines))
    if df_lines and len(df_lines) != len(tr_lines):
        return None, "改前 def/tr 不等 %d/%d" % (len(df_lines), len(tr_lines))
    if not meta:
        # 🔴 不是伪造结构：这一行本来就没有 meta，补空对象只是把"每个义项一项"这个
        #    不变量建立起来，好让 align_check 从此能管到它、也好记录本次的来源。
        meta = [{} for _ in tr_lines]

    new_tr = "\n".join(tr_lines + adds) if tr_lines else "\n".join(adds)
    new_df = "\n".join(df_lines + [""] * len(adds)) if df_lines else df
    new_meta = meta + [{"pos": (r["pos"] or "").split("/")[0], "src": src,
                        "batch": batch} for _ in adds]
    if len(new_meta) != len(new_tr.split("\n")):
        return None, "改后不对齐"
    if new_df and len(new_df.split("\n")) != len(new_meta):
        return None, "改后 def 不对齐"
    return (new_df, new_tr, json.dumps(new_meta, ensure_ascii=False), r["id"]), None


def write(plan, tag, new_meta_rows):
    """🔴 `expect` 必须把 `meta` 的增量写出来。

    A 桶那批行（`amiga` 这类 is_lemma=0 的）**原本 meta 是空的**，补完义项后
    第一次有了 meta —— 于是 `meta` 列的非空计数会涨。第一次跑我按"只追加内容、
    计数不变"写了 `expect={}`，闸门当场拦下（"未声明的列 meta 变了 +33"）。
    它拦得对：**我确实改到了一个我没在脑子里过一遍的列**。
    """
    with dbtool.session(tag, expect={"meta": new_meta_rows}) as s:
        s.executemany("UPDATE dict SET definition=?, translation=?, meta=? "
                      "WHERE id=?", plan)
    dbtool.align_check()


# ═══ ② 豆包 pro ═══

SYS_PRO = """你在修一部西汉词典的一个系统性缺漏。

这些西语词是**某个阳性词的阴性对应词**（`amiga`←`amigo`、`gata`←`gato`）。
我们的数据源把这类义项当成"变形指针"丢掉了，于是词条里只剩下冷僻义或什么都没有。
请你把**这个阴性词应该有的中文义项**补出来。

给你的每一条包含：
  w        这个阴性词
  gloss    源头对它的描述（如 "female equivalent of gato"）
  base     原形（阳性词）
  base_zh  **原形的全部中文义项**（按顺序）
  base_en  原形的全部英文义项（同序，作参考）
  ours     我们这个词条现有的中文义项（不要重复它们）

🔴 **关键：原形的义项不是每一个都有阴性形式。**
   `gato` 的义项有：猫／公猫／仆人／C形夹／千斤顶／井字棋／马德里人／…
   —— `gata` 只对应得上「母猫」「（女）马德里人」这类**指人指动物**的义项；
   千斤顶、井字棋没有阴性。**挑出对得上的那些，其余不要写。**
   如果一个都对不上（原形全是器物义），返回空数组。

要求：
- 中文词典式释义，近义用逗号分隔；**句末不加句号**；不写元描述（不要写"…的阴性形式"）。
- 指人的义项要体现性别：`amigo`＝朋友 → `amiga`＝女性朋友，女友（视语义）。
- 一般 1–3 条，最多 4 条。**不要把原形的义项照抄一遍。**
- `conf`：high＝这个词常用且你有把握；medium＝方向明确；low＝拿不准。

严格输出 JSON：{"r":[{"w":"词","zh":["义项1","义项2"],"conf":"high|medium|low"}]}"""

CHUNK, PAR = 20, 8


async def run_pro(items, model="doubao", bucket="C"):
    """model='doubao' 走 Ark，'v4pro' 走 deepseek。都关思考、都记 usage。

    🔴 记 usage 是这一轮才补的：上一轮跑完只知道"36 秒"，不知道花了多少钱 ——
    于是"pro 贵不贵"只能靠印象争，不能靠数字定。
    """
    from volcenginesdkarkruntime import AsyncArk
    import httpx
    env = load_env()
    out_path = raw_path(bucket, model)
    done = set()
    if out_path.exists():
        for ln in open(out_path, encoding="utf-8"):
            try:
                done.add(json.loads(ln)["w"])
            except Exception:
                pass
    todo = [x for x in items if x["w"] not in done]
    chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    print("■ 送 %s %d 条（已完成 %d），%d 块，关思考" % (model, len(todo), len(done), len(chunks)))
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=900) if model == "doubao" else None
    sem, lock = asyncio.Semaphore(PAR), asyncio.Lock()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(out_path, "a", encoding="utf-8")
    stat = collections.Counter()
    t0 = time.time()

    async def one(chunk):
        async with sem:
            msgs = [{"role": "system", "content": SYS_PRO},
                    {"role": "user", "content": json.dumps(chunk, ensure_ascii=False)}]
            for a in range(3):
                try:
                    if cl is not None:
                        r = await cl.chat.completions.create(
                            model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
                            thinking={"type": "disabled"}, messages=msgs)
                        raw = r.choices[0].message.content
                        u = r.usage
                        stat["in"] += getattr(u, "prompt_tokens", 0)
                        stat["out"] += getattr(u, "completion_tokens", 0)
                    else:
                        async with httpx.AsyncClient(timeout=900) as hc:
                            rr = await hc.post(
                                "https://api.deepseek.com/chat/completions",
                                headers={"Authorization": "Bearer " + env["DEEPSEEK_API_KEY"]},
                                json={"model": "deepseek-v4-pro", "messages": msgs,
                                      "temperature": 0, "stream": False,
                                      "thinking": {"type": "disabled"},
                                      "response_format": {"type": "json_object"}})
                            if rr.status_code != 200:
                                raise RuntimeError(str(rr.status_code))
                            j = json.loads(rr.text.lstrip())
                            raw = j["choices"][0]["message"]["content"]
                            us = j.get("usage") or {}
                            stat["in"] += us.get("prompt_tokens", 0)
                            stat["out"] += us.get("completion_tokens", 0)
                            stat["cached"] += us.get("prompt_cache_hit_tokens", 0)
                    break
                except Exception as e:
                    if a == 2:
                        print("🔴 一块三次失败：%s" % e)
                        return
                    await asyncio.sleep(2 * (a + 1))
            try:
                got = {x.get("w"): x for x in (loads_lenient(raw).get("r") or [])}
            except Exception as e:
                print("🔴 解析失败：%s" % e)
                return
            async with lock:
                for it in chunk:
                    g = got.get(it["w"])
                    if not g:
                        stat["无输出"] += 1
                        continue
                    f.write(json.dumps({"w": it["w"], "zh": g.get("zh") or [],
                                        "conf": g.get("conf", "?")},
                                       ensure_ascii=False) + "\n")
                    stat["有返回"] += 1
                stat["块"] += 1

    await asyncio.gather(*[one(c) for c in chunks])
    f.close()
    print("■ 跑完 %.0fs：%s" % (time.time() - t0, dict(stat)))
    if model == "v4pro":
        # 官方价（2026-07-31 回官方页核实）：未命中 3 / 命中 0.025 / 输出 6 元每 M，
        # 北京时间 9–12 点、14–18 点全部 ×2。
        h = (time.time() // 3600 % 24 + 8) % 24
        mult = 2 if (9 <= h < 12 or 14 <= h < 18) else 1
        miss = stat["in"] - stat["cached"]
        print("■ v4-pro 花费 ≈ %.3f 元（未命中 %d×3 + 命中 %d×0.025 + 输出 %d×6，%s）"
              % ((miss * 3 + stat["cached"] * 0.025 + stat["out"] * 6) / 1e6 * mult,
                 miss, stat["cached"], stat["out"], "高峰×2" if mult == 2 else "平峰"))


def pro_payload(words, rows, glosses, bases):
    """🔴 词缀不送（`-aca` `-adora` 这类）。它们的"释义"本来就只能是
    「-aco 的阴性后缀」这种元描述，模型给不出别的东西，送了只会被闸门拦回来。

    🔴 原形的中文**一次性全表取**，不逐词查 —— `word` 列没索引，逐词查就是
    每次全表扫 113 万行。同一个坑今天踩过两次（先是统计脚本卡了十几分钟，
    然后是这里），第二次才想起来根因一样。
    """
    need = {bases.get(w, "") for w in words} - {""}
    need |= {(rows[w]["exchange"].split(":")[-1].split("\n")[0])
             for w in words if rows[w]["exchange"]}
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    base_db = {}
    for w, tr, dfn, lem in conn.execute(
            "SELECT word, translation, definition, is_lemma FROM dict"):
        if w in need and (w not in base_db or lem):
            base_db[w] = (tr or "", dfn or "")
    conn.close()

    items = []
    for w in words:
        if w.startswith("-") or w.endswith("-"):
            continue
        r = rows[w]
        b = bases.get(w) or (r["exchange"].split(":")[-1].split("\n")[0]
                             if r["exchange"] else "")
        got = base_db.get(b)
        bz = [x for x in (got[0] if got else "").split("\n") if x.strip()]
        be = [x for x in (got[1] if got else "").split("\n") if x.strip()]
        if not bz:                      # 原形没中文 → 模型没线索，不送
            continue
        items.append({"w": w, "gloss": glosses[w][0][:80], "base": b,
                      "base_zh": bz[:14], "base_en": be[:14],
                      "ours": real_senses(r["tr"])[:8]})
    return items


# ═══ main ═══

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--zh", action="store_true")
    ap.add_argument("--pro", action="store_true")
    ap.add_argument("--bucket", default="C", choices=["A", "C"])
    ap.add_argument("--core", action="store_true",
                    help="只跑核心层：原形的 CEFR 是 A1/A2/B1")
    ap.add_argument("--model", default="doubao", choices=["doubao", "v4pro"],
                    help="生成用哪家。v4pro 便宜，质量由本轮对照实测决定")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    glosses, bases = scan_kaikki()
    rows = db_rows(list(glosses))
    A, C = bucket(rows)
    print("■ kaikki 里被丢掉 female-equivalent 义项的词：%d（库里有 %d）" %
          (len(glosses), len(rows)))
    print("   A 只剩变形标签 %d ｜ C 有冷僻义在前 %d" % (len(A), len(C)))

    if a.scan:
        CAND.parent.mkdir(parents=True, exist_ok=True)
        CAND.write_text(json.dumps({"A": A, "C": C}, ensure_ascii=False), encoding="utf-8")
        print("→ %s" % CAND)
        return

    if a.zh:
        zh = zh_senses()
        plan, samples, bad = [], [], []
        stat = collections.Counter()
        for w in A + C:
            r = rows[w]
            cand = zh.get(w)
            if not cand:
                stat["中文版没有"] += 1
                continue
            adds = novel(cand, real_senses(r["tr"]))
            if not adds:
                stat["中文版有但我们已覆盖"] += 1
                continue
            p, err = append_plan(r, adds, SRC_ZH, BATCH_ZH)
            if err:
                bad.append((w, err))
                continue
            stat["补入 " + ("A" if w in set(A) else "C")] += 1
            stat["义项数"] += len(adds)
            if not r["meta"].strip():
                stat["meta 由空变非空"] += 1
            plan.append(p)
            samples.append((w, (r["tr"] or "").replace("\n", " / ")[:30],
                            " / ".join(adds)[:34]))
        print("■ 中文版补入：%s" % dict(stat))
        if bad:
            print("   🔴 跳过 %d 条：%s" % (len(bad), bad[:6]))
        dbtool.sample_check(samples, 14, ("词", "原有", "补入"))
        if a.apply and plan:
            write(plan, "fem-zh", stat["meta 由空变非空"])
        elif not a.apply:
            print("\n(预览。确认后 --apply)")
        return

    if a.pro:
        zh = zh_senses()
        bkt = A if a.bucket == "A" else C
        # 中文版已经补掉的不再送模型（判据与 --zh 那步完全相同，避免两批打架）
        left = [w for w in bkt
                if not novel(zh.get(w, []), real_senses(rows[w]["tr"]))]
        if a.core:
            lv = base_levels(bases, left)
            left = [w for w in left if lv.get(w) in ("A1", "A2", "B1")]
        items = pro_payload(left, rows, glosses, bases)
        print("■ %s 桶 %d，中文版补不到 %d%s，原形有中文可送 %d" %
              (a.bucket, len(bkt), len(left),
               "（核心层：原形 A1/A2/B1）" if a.core else "", len(items)))
        if not a.apply:
            asyncio.run(run_pro(items, a.model, a.bucket))

        # 落库时把两家的产出合并：**豆包优先，v4-pro 只补它空手的**。
        # 依据是本轮 594 条对照：两家重叠部分 447/448 一致（质量等价），
        # 但 v4-pro 覆盖率低 12 个点（80% vs 92%），且有一批标 conf=high 却返回空。
        raw = {}
        for path, src in ((raw_path(a.bucket, "v4pro"), SRC_V4),
                          (raw_path(a.bucket, "doubao"), SRC_PRO)):
            if not path.exists():
                continue
            for ln in open(path, encoding="utf-8"):
                try:
                    x = json.loads(ln)
                except Exception:
                    continue
                if [y for y in (x.get("zh") or []) if y.strip()] or x["w"] not in raw:
                    x["src"] = src
                    raw[x["w"]] = x
        plan, samples, bad = [], [], []
        stat = collections.Counter()
        for w in left:
            g = raw.get(w)
            if not g:
                continue
            if g.get("conf") == "low":
                stat["low 不落库"] += 1
                continue
            adds = []
            for z in (g.get("zh") or [])[:4]:
                z = clean_zh(z)
                # 形容词义项模型爱缀个「（阴性）」（`洪都拉斯的（阴性）`，15 条）。
                # 性别属于 meta.g，不进释义正文 —— 剥掉标记，别丢义项。
                z = re.sub(r"[（(](?:阴性|陰性|阳性|陽性)[）)]\s*$", "", z).strip()
                if not z:
                    continue
                if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}",
                             re.sub(r"\([^)]*\)|（[^）]*）", "", z)):
                    stat["残留西语词，拦下"] += 1
                    continue
                if re.search(r"的(?:阴性|陰性)(?:形式|形|对应词)?$", z):
                    stat["元描述，拦下"] += 1
                    continue
                adds.append(z)
            adds = novel(adds, real_senses(rows[w]["tr"]))
            if not adds:
                stat["模型没给新义项"] += 1
                continue
            p, err = append_plan(rows[w], adds, g["src"],
                                 "fem-%s-20260803" % a.bucket)
            if err:
                bad.append((w, err))
                continue
            stat["落库 %s·%s" % (g["src"].split("-")[1], g.get("conf", "?"))] += 1
            stat["义项数"] += len(adds)
            if not rows[w]["meta"].strip():
                stat["meta 由空变非空"] += 1
            plan.append(p)
            samples.append((w, g.get("conf", "?"),
                            (rows[w]["tr"] or "").replace("\n", " / ")[:26],
                            " / ".join(adds)[:34]))
        print("■ 补入：%s" % dict(stat))
        if bad:
            print("   🔴 跳过 %d 条：%s" % (len(bad), bad[:6]))
        dbtool.sample_check(samples, 16, ("词", "把握", "原有", "补入"))
        if a.apply and plan:
            write(plan, "fem-" + a.bucket, stat["meta 由空变非空"])
        elif not a.apply:
            print("\n(预览。确认后 --apply)")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
