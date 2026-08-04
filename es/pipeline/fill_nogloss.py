#!/usr/bin/env python3
"""给 2,716 个「源头就没释义」的词补中文。2026-08-03。

═══ 这批词是什么 ═══
西语版收词时带进来的真词头：有拼写、有音标、有变位形式指向它，**但 senses 是
`[{"tags":["no-gloss"]}]`** —— 维基收了词条却没人写释义。几乎全是动词
（2,686/2,716），构词高度规则（-ar 1,452 / -ear 507 / -izar 88）。

═══ 🔴 这批词没有权威源，和前面所有工作不一样 ═══
逐个源头查过：
    西语版      无释义（就是它们来的地方）
    英文版      不在（我们的库就是英文版建的，这些词英文版没有）
    zh 版       **117 个有现成中文释义** ← 白捡
    fr 版 50 / pt 版 9 / it 版 2 / de 版 0
    西语版词源文本 386 个
    能在我们库里拆出词根的 1,784 个（65.7%，但有噪声：`dimir←dima 姓氏` 是错拆）
→ 合计约 178 个有别版释义可直接用，其余 ~2,500 个**六版全无**。

所以本脚本产出的译文，性质是「**模型凭西语知识推的**」，不是「源头说的」。
因此：
  · `translation_src='llm-derived'` 单独标一档，**随时可整批撤销**；
  · `definition_es` 仍然留空 —— 不能因为我们补了中文，就假装西语版说过什么；
  · payload 里把能凑到的证据都给（别版释义 / 词源 / 词根中文），
    但**明确告诉模型这些只是线索**，拿不准就说拿不准，别硬编。

用法（在 es/ 目录）：
    python3 pipeline/fill_nogloss.py --evidence   # 扫六个版本，攒证据（约 4 分钟）
    python3 pipeline/fill_nogloss.py --run        # flash 翻译
    python3 pipeline/fill_nogloss.py --run --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import asyncio
import collections
import gzip
import json
import re
import sqlite3
import unicodedata as U

import dbtool
import paths
from pipeline.translate_intake import (PAR, clean_zh, load_env, loads_lenient,
                                       run_llm)

EVID = paths.WORK / "nogloss_evidence.json"
RAW = paths.WORK / "runs" / "nogloss_flash.jsonl"
RAW_PRO = paths.WORK / "runs" / "nogloss_v4pro.jsonl"
SRC = "llm-derived"
SRC_PRO = "llm-derived-pro"
# 🔴 v4-pro 这一轮**关思考**（用户 2026-08-03："开思考模式，真的太贵了"）。
#    换 v4-pro 的理由与 benchmark 无关：flash 在这 1,128 条上**弃权**了 ——
#    它不是没想明白，是不知道这些冷僻动词是什么意思。那是**世界知识**问题，
#    换个知识面不同的模型才有意义；7/31 flash 更新跳的是 Agent 能力
#    （Terminal Bench / DeepSWE），架构参数量没变，对这件事不构成证据。
MODEL = {"flash": "deepseek-v4-flash", "pro": "deepseek-v4-pro"}
EDITIONS = [("zh", "zhwiktionary"), ("fr", "frwiktionary"), ("pt", "ptwiktionary"),
            ("it", "itwiktionary"), ("de", "dewiktionary")]

SYS = """你是西班牙语→中文词典编纂者。给你若干**真实存在但维基词典没写释义**的西语词。
请给出中文词典式释义。

每条我给你能凑到的线索（**都只是线索，不是定论**）：
  w        西语词
  pos      词性
  other    其它语言版维基对这个词的释义（有的话，**这是最可靠的一条，优先采信**）
  ety      西语版给的词源文本（有的话）
  root     我们词典里已有的疑似词根及其中文（**机器拆的，会拆错**，
           如 `dimir ← dima 姓氏` 就是错拆；与词义对不上就别用）

要求：
- 输出**中文词典式释义**，近义说法用逗号分隔，多义用「；」分隔。句末不加句号。
- 每条还要给 `conf`（你的把握）：
    "high"   —— 你认识这个词，或它是**透明构词**（`desatraer` = des- + atraer「排斥」、
                `preelegir` = pre- + elegir「预先选定」、`entrelucir` = entre- + lucir
                「隐约透出光」），推导链条清楚。
    "medium" —— 词根明确、语义方向明确，但具体落到哪个中文说法有余地。
    "low"    —— 词根都吃不准，基本靠猜。
- 🔴 **透明构词的词不要弃权**。这批词生僻是因为维基没人写释义，
  不代表它们没有意义。前缀 des-/re-/pre-/auto-/entre-/sobre- 加一个你认识的动词时，
  照着构词给出中文，标 high 或 medium。
- 🔴 **真的连词根都认不出，才给 `zh` 空字符串**。这一档我会自己人工处理，
  所以不要为了交差硬编 —— 但也不要因为"词冷僻"就一概弃权。
- 🔴 **不要写元描述**：不要输出"某某的变体""动词，及物"这类话，要写词义本身。
- 以 -se 结尾的是自复动词，中文用不及物说法（`变松软`不是`使某物变松软`）。

严格输出 JSON：{"r":[{"w":"词","zh":"中文释义 或 空字符串","conf":"high|medium|low"}]}"""


def targets():
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word, pos FROM dict WHERE is_lemma=1 "
        "AND TRIM(COALESCE(translation,''))='' "
        "AND TRIM(COALESCE(definition,''))='' "
        "AND TRIM(COALESCE(definition_es,''))=''").fetchall()
    conn.close()
    return rows


# ── 词根拆解（机器拆，会拆错，只当线索）──
PRE = ["des", "en", "em", "re", "a", "in", "im", "con", "tras", "sobre", "entre",
       "contra", "pre", "auto", "ante", "inter", "super", "sub", "semi", "extra",
       "mal", "bien", "co", "trans", "ultra", "infra", "pro", "peri", "anti"]
SUF = ["atearse", "etearse", "oteares", "izarse", "ificarse", "earse", "iarse",
       "arse", "erse", "irse",
       "atear", "etear", "otear", "izar", "ificar", "ear", "iar", "ar", "er", "ir"]


def _na(s):
    return "".join(c for c in U.normalize("NFD", s.lower()) if U.category(c) != "Mn")


def roots_of(w, naidx, lex):
    """疑似词根。**两条路都要走**：

    ① 剥前缀、留下的整词直接查 —— 派生动词的底是**动词**：
       `desfortificar`→fortificar、`desatraer`→atraer、`preelegir`→elegir、
       `entrelucir`→lucir、`receñir`→ceñir、`autoinducir`→inducir。
    ② 剥动词词尾、再拼名词形 —— 名源动词的底是名词：
       `encebollar`→cebolla、`ajuglarar`→juglar。

    🔴 只走 ② 会把 `desfortificar` 拆成 `forte`（强的）、`receñir` 拆成 `cena`（晚餐），
       线索比没有还糟 —— 模型看着一个不相干的词根，只会更不敢答。
    """
    lw, out = w.lower(), []
    for p in sorted(PRE, key=len, reverse=True):        # 长前缀优先，先试 ①
        if lw.startswith(p) and len(lw) - len(p) >= 4:
            k = naidx.get(_na(lw[len(p):]))
            if k and k != lw and k not in out:
                out.append(k)
            k2 = naidx.get(_na(lw[len(p):].rstrip("se")))
            if k2 and k2 != lw and k2 not in out:
                out.append(k2)
    for suf in SUF:
        if not lw.endswith(suf):
            continue
        stem = lw[:-len(suf)]
        if len(stem) < 3:
            return []
        cands = [stem, stem + "a", stem + "o", stem + "e", stem + "al"]
        for p in PRE:
            if stem.startswith(p) and len(stem) - len(p) >= 3:
                s2 = stem[len(p):]
                cands += [s2, s2 + "a", s2 + "o", s2 + "e"]
        for cd in cands:
            k = naidx.get(_na(cd))
            if k and k != lw and k not in out:
                out.append(k)
        break
    # 🔴 **给全部义项，不是第一条。**（这是同一个坑第三次咬我。）
    #    `corsear` 的词根 `corso` 在库里是「科西嘉的 / 科西嘉人 / 私掠巡航，海盗行为」，
    #    只传第一行 → 模型看到"科西嘉的"对不上，转去抓 `corsé`（紧身胸衣），
    #    把 corsear 译成了"穿紧身胸衣"。**正确答案就在被我截掉的第三条里。**
    #    模板阶段的 doctorcito 是同一个教训，我当时还把它写进了注释。
    return [{"w": k, "zh": lex[k].replace("\n", "；")[:90]} for k in out[:3]]


def evidence():
    rows = targets()
    want = {w for _, w, _ in rows}
    print("■ 目标 {:,} 个无释义词头".format(len(want)))
    ev = collections.defaultdict(dict)

    for ln in gzip.open(paths.EDITION, "rt", encoding="utf-8", errors="replace"):
        e = json.loads(ln)
        if e.get("lang_code") != "es" or e.get("word") not in want:
            continue
        if e.get("etymology_texts"):
            ev[e["word"]]["ety"] = e["etymology_texts"][0][:160]
    print("   西语版词源 {:,}".format(sum(1 for v in ev.values() if v.get("ety"))))

    for code, name in EDITIONS:
        n = 0
        for ln in gzip.open(paths.DUMPS / (name + ".jsonl.gz"), "rt",
                            encoding="utf-8", errors="replace"):
            if '"es"' not in ln:
                continue
            e = json.loads(ln)
            if e.get("lang_code") != "es" or e.get("word") not in want:
                continue
            g = [x for x in ((s.get("glosses") or [""])[0]
                             for s in (e.get("senses") or [])) if x]
            if not g:
                continue
            ev[e["word"]].setdefault("other", []).extend(
                "[%s] %s" % (code, x[:90]) for x in g[:3])
            n += 1
        print("   {:14} {:,}".format(name, n))

    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    lex = {}
    for w, t in conn.execute("SELECT word, translation FROM dict WHERE is_lemma=1 "
                             "AND TRIM(COALESCE(translation,''))<>''"):
        lex.setdefault(w.lower(), t)
    conn.close()
    naidx = {}
    for k in lex:
        naidx.setdefault(_na(k), k)
    nr = 0
    for _, w, _pos in rows:
        r = roots_of(w, naidx, lex)
        if r:
            ev[w]["root"] = r
            nr += 1
    print("   拆出词根 {:,}".format(nr))

    out = []
    for rid, w, pos in rows:
        it = {"id": rid, "w": w, "pos": pos}
        it.update(ev.get(w, {}))
        out.append(it)
    EVID.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("→ {}（{:,} 条，其中有别版释义 {:,} / 有词源 {:,} / 有词根 {:,}）".format(
        EVID, len(out), sum(1 for x in out if x.get("other")),
        sum(1 for x in out if x.get("ety")), sum(1 for x in out if x.get("root"))))


def load_done():
    if not RAW.exists():
        return {}
    out = {}
    for ln in open(RAW, encoding="utf-8"):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        out[r["w"]] = r
    return out


def apply_rows(src=SRC):
    done = load_done()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cur = {rid: w for rid, w, _ in targets()}
    conn.close()
    plan, samples, stat = [], [], collections.Counter()
    for r in done.values():
        if cur.get(r["id"]) != r["w"]:
            continue
        zh = clean_zh(r["zh"][0] if isinstance(r["zh"], list) else r["zh"])
        conf = r.get("conf", "?")
        if not zh:                       # 模型自己说拿不准 → 留空，别硬填
            stat["弃权"] += 1
            continue
        # 🔴 只落 high/medium。`low` = 模型自己说"词根都吃不准，基本靠猜" ——
        #    这一档留空、交我人工处理（用户 2026-08-03："他们还不确定的，你来就行"）。
        if conf == "low":
            stat["low（留给我人工）"] += 1
            continue
        stat["落库 " + conf] += 1
        plan.append((zh, src, r["id"]))
        if len(samples) < 600:
            samples.append((r["w"], conf, zh[:40]))
    print("■ RAW {:,} 条：{}".format(len(done), dict(stat)))
    dbtool.sample_check(samples, n=18, cols=("词", "把握", "推出的中文"))
    return plan


async def go(items, model="flash", raw=None):
    """复用 translate_intake 的并发骨架，但本脚本每条只有一个义项。"""
    global RAW
    if raw is not None:
        RAW = raw
    import time

    import httpx
    key = load_env()["DEEPSEEK_API_KEY"]
    done = load_done()
    todo = [it for it in items if it["w"] not in done]
    chunks = [todo[i:i + 40] for i in range(0, len(todo), 40)]
    print("■ 待推 {:,}（已完成 {:,}），{} 块".format(len(todo), len(done), len(chunks)))
    sem, lock = asyncio.Semaphore(PAR), asyncio.Lock()
    RAW.parent.mkdir(parents=True, exist_ok=True)
    f = open(RAW, "a", encoding="utf-8")
    stat = collections.Counter()
    t0 = time.time()

    async def one(chunk):
        body = {"model": MODEL[model],
                "messages": [{"role": "system", "content": SYS},
                             {"role": "user", "content": json.dumps(
                                 [{k: v for k, v in it.items() if k != "id"}
                                  for it in chunk], ensure_ascii=False)}],
                "temperature": 0, "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"}, "stream": False}
        async with sem:
            async with httpx.AsyncClient(timeout=600) as cl:
                for a in range(3):
                    try:
                        r = await cl.post(
                            "https://api.deepseek.com/chat/completions",
                            headers={"Authorization": "Bearer " + key}, json=body)
                        if r.status_code != 200:
                            raise RuntimeError(str(r.status_code))
                        raw = json.loads(r.text.lstrip())
                        u = raw.get("usage") or {}
                        raw = raw["choices"][0]["message"]["content"]
                        break
                    except Exception as e:
                        if a == 2:
                            print("🔴 一块三次失败：%s" % e)
                            return
                        await asyncio.sleep(2 * (a + 1))
            try:
                got = {x.get("w"): (x.get("zh"), x.get("conf", "?"))
                       for x in (loads_lenient(raw).get("r") or [])}
            except Exception as e:
                print("🔴 解析失败：%s" % e)
                return
            async with lock:
                for it in chunk:
                    if it["w"] not in got:
                        stat["无输出"] += 1
                        continue
                    f.write(json.dumps({"w": it["w"], "id": it["id"],
                                        "zh": got[it["w"]][0],
                                        "conf": got[it["w"]][1]},
                                       ensure_ascii=False) + "\n")
                    stat["有返回"] += 1
                stat["tokens"] += u.get("total_tokens") or 0

    await asyncio.gather(*[one(c) for c in chunks])
    f.close()
    print("■ 跑完 {:.0f}s：有返回 {:,}，无输出 {:,}，tokens {:,}".format(
        time.time() - t0, stat["有返回"], stat["无输出"], stat["tokens"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--pro", action="store_true",
                    help="flash 弃权的那批交给 v4-pro（关思考）")
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.evidence:
        evidence()
        return
    if not a.run:
        ap.print_help()
        return
    items = json.loads(EVID.read_text(encoding="utf-8"))
    if a.pro:
        # 只取**现在库里仍然没有中文**的（＝flash 弃权的那批）
        left = {w for _, w, _ in targets()}
        items = [x for x in items if x["w"] in left]
        if a.pilot:
            items = items[:a.pilot]
        print("■ flash 弃权、待 v4-pro 推的：{:,}".format(len(items)))
        global RAW
        RAW = RAW_PRO
        if not a.apply:
            asyncio.run(go(items, model="pro", raw=RAW_PRO))
        plan = apply_rows(SRC_PRO)
        if a.apply and plan:
            with dbtool.session("nogloss-pro", expect={"translation": len(plan)}) as s:
                s.executemany(
                    "UPDATE dict SET translation=?, translation_src=? WHERE id=?", plan)
            dbtool.align_check()
        return
    if not a.apply:
        asyncio.run(go(items))
    plan = apply_rows()
    if a.apply and plan:
        with dbtool.session("nogloss-fill", expect={"translation": len(plan)}) as s:
            s.executemany(
                "UPDATE dict SET translation=?, translation_src=? WHERE id=?", plan)
        dbtool.align_check()


if __name__ == "__main__":
    main()
