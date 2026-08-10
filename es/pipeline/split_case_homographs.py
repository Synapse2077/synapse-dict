#!/usr/bin/env python3
"""拆开「小写普通名词 + 大写专名压成一行」的词条。2026-08-07。

`docs/SCHEMA.md` §9 缺陷②。西语用大小写承载词汇区别，而我们建库时按
`word.lower()` 归并（`build.py:225` 的 `key = word.lower()`），于是：

    concepción   1. 受孕，受精            ← 普通名词
                 2. 概念，观念，构想        ← 普通名词
                 3. 女性名字              ← 其实是 Concepción
                 4. 康塞普西翁（拉美地名）   ← 其实是 Concepción
    toledo       厕所，盥洗室 ｜ 托莱多省 ｜ 托莱多市
    leo          利奥 ｜ 狮子座 ｜ 莱昂纳多的昵称

实测 **2,469 组**（记录里记的 1,899 偏低）。

═══ ⭐ v2 之后这件事才安全 ═══
拆分只需改 `sense.word_id` 一个整数字段 —— **`dict` 的
`definition`/`translation`/`meta` 三列一个字节都不动**。
v2 之前要拆那三列的行号对齐数组，那是最危险的操作（`novia` 那一族）。

═══ 判据分两段，第一段不问模型 ═══
① **确定性 3,039 条**：来自 `sense_es` 且 `src_word`（dump 原拼写）是大写形。
   `fix_sense_es_case.py` 当初把 `Japón` 的义项挂到了库里的 `japón` 行上，
   同时把原拼写留在了 `src_word` —— 那就是现成的凭据。
② **模型判 6,083 条**：来自英文版（`dict` 那套）。
   🔴 **英文版源头就没分大小写**：`concepción` 一个词条里同时有
   `conception (fertilization…)`、`a female given name`、
   `any of a number of places in Latin America`。没有任何确定性凭据可用，
   只能看释义内容判。模型只回答一个封闭问题：这条义项属于小写普通词还是大写专名。

⚠️ **不能只做①**：西语版那 18 条分出去、英文版那 2 条留在原地，
   同一个「Concepción 地名」概念会被劈成两半，比不拆更乱。

═══ 可逆 ═══
改的是 `sense.word_id`。判错了改回来即可，`sense_src` / `sense_gloss` /
`example` / `sense_relation` 全部通过 `sense_id` 挂靠，不受影响。

用法（在仓库根）：
    python3 -m es.pipeline.split_case_homographs                 # 只统计
    python3 -m es.pipeline.split_case_homographs --sample 60     # 出模型判的样本
    python3 -m es.pipeline.split_case_homographs --ask           # 送模型
    python3 -m es.pipeline.split_case_homographs --ask --apply
"""
import argparse
import asyncio
import collections
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

RAW = paths.WORK / "split_case_llm.jsonl"
CHUNK = 25
PAR = 12
MODEL = "deepseek-v4-pro"

SYS = """你在给一部西汉词典拆分**因大小写被合并的词条**。

西语靠大小写区别词：`concepción`（受孕、概念）与 `Concepción`（人名、地名）是**两个词**，
但英文维基把它们的释义写在了同一个条目里。请逐条判断每个义项属于哪一个。

输入每条含：id / lower 小写词形 / upper 大写词形 / zh 中文释义 / en 英文释义

输出 `w`：
  "lower" —— 这条义项属于**小写的普通词**（普通名词、动词、形容词…）
  "upper" —— 这条义项属于**大写的专名**（人名、姓氏、地名、机构名、星座、节日、商标…）

判断要点：
 · 看释义**说的是什么**，不看词形本身。
     `conception (fertilization of an ovum)`        → lower（普通名词）
     `a female given name`                          → upper（人名）
     `any of a number of places in Latin America`   → upper（地名）
     `the Immaculate Conception`                    → upper（宗教专名）
 · 🔴 **星座/黄道宫算专名**：`Leo`（狮子座）是 upper，而 `leo`（我读）是 lower。
   但「狮子」这个动物义是 lower。
 · 🔴 **元素符号、字母名、缩写**：`Be`（铍）是 upper，`be`（字母 B 的名称）是 lower。
 · 语言名、民族名在西语里**小写**（`español`、`chino`）⇒ lower。
 · 月份、星期在西语里**小写** ⇒ lower。
 · 拿不准时选 "lower"（保持现状），错误方向更安全 —— 少拆一条只是分组不够细，
   拆错一条会让用户在错误的词条下看到不属于它的释义。

只输出 JSON：{"结果":[{"id":义项id,"w":"lower"或"upper"},…]}，条数与输入完全相等。"""


def plan(con):
    """→ (确定性拆分, 待模型判, 大写词形表)"""
    # ① 确定性：sense_es 的 src_word 是大写形
    # 🔴 **方向不能假设**。我一度写成「`src_word` 是大写形」——实测不成立：
    #      word=ADE   src_word=Ade      （全大写 vs 首字母大写）
    #      word=Fani  src_word=FANI     （反过来）
    #      word=AINE  src_word=aine     （库里是大写、dump 是小写）
    #    实测 2,278 组是我假设的方向、**166 组相反**、25 组「差的不是大小写」。
    #    ⇒ 按**谁更大写**定方向（大写字母多的那个当专名形），差的不是大小写就跳过。
    def upper_score(x):
        return sum(1 for ch in x if ch.isupper())

    up = {}          # 库内词形 → 与它仅大小写不同的专名形
    esrc = {}        # sense_es.id → dump 原拼写
    skip = 0
    for esid, w, sw in con.execute("SELECT id, word, src_word FROM sense_es"):
        esrc[esid] = sw or w
        if not sw or sw == w:
            continue
        if sw.lower() != w.lower():
            skip += 1                     # 差的不是大小写（25 组），不属于本缺陷
            continue
        up[w] = sw if upper_score(sw) > upper_score(w) else w
        if up[w] == w:
            up.pop(w)                     # 库内那个已经是专名形，无需拆分方向
    print(f"  （跳过 {skip} 组：两个词形差的不是大小写）")
    rows = con.execute(
        "SELECT s.id, s.word_id, d.word, sr.src_ref, sr.lang, sr.text "
        "FROM sense s JOIN dict d ON d.id = s.word_id "
        "JOIN sense_src sr ON sr.sense_id = s.id "
        "WHERE d.word IN (%s)" % ",".join("?" * len(up)), list(up)).fetchall()
    zh = dict(con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='zh' AND seq=0"))

    sure, ask, seen = [], [], set()
    for sid, wid, w, ref, lang, text in rows:
        if sid in seen:
            continue
        seen.add(sid)
        if ref.startswith("sense_es:"):
            esid = int(ref.split(":", 1)[1])
            if esrc.get(esid) == up[w]:
                sure.append((sid, w, up[w]))
        else:
            ask.append({"id": sid, "lower": w, "upper": up[w],
                        "zh": (zh.get(sid) or "")[:60],
                        "en": (text or "")[:90]})
    return sure, ask, up


async def run(items, env):
    import httpx
    ck = [items[i:i + CHUNK] for i in range(0, len(items), CHUNK)]
    out, tok = {}, collections.Counter()
    t0 = time.time()
    cl = httpx.AsyncClient(timeout=900)
    key = env["DEEPSEEK_API_KEY"].strip()
    sem = asyncio.Semaphore(PAR)

    async def go(c):
        async with sem:
            try:
                r = await cl.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": "Bearer " + key},
                    json={"model": MODEL,
                          "messages": [{"role": "system", "content": SYS},
                                       {"role": "user",
                                        "content": json.dumps(c, ensure_ascii=False)}],
                          "temperature": 0, "response_format": {"type": "json_object"},
                          "thinking": {"type": "disabled"}, "stream": False})
                d = json.loads(r.text)
                for k, v in (d.get("usage") or {}).items():
                    if isinstance(v, int):
                        tok[k] += v
                res = next((v for v in json.loads(
                    d["choices"][0]["message"]["content"]).values()
                    if isinstance(v, list)), [])
            except Exception as ex:
                print(f"\n  🔴 块失败：{ex}")
                return
            if len(res) != len(c):
                print(f"\n  🔴 条数不符 {len(res)} vs {len(c)}")
                return
            want = {x["id"] for x in c}
            for x in res:
                if x.get("id") in want and x.get("w") in ("lower", "upper"):
                    out[x["id"]] = x["w"]
            print(f"\r  {len(out):,}/{len(items):,}  "
                  f"{tok.get('total_tokens', 0)/1e6:.2f}M tokens  "
                  f"{(time.time()-t0)/60:.1f} 分钟", end="", flush=True)

    await asyncio.gather(*(go(c) for c in ck))
    await cl.aclose()
    print(f"\n  完成 {len(out):,}/{len(items):,}，{tok.get('total_tokens', 0):,} tokens")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int)
    ap.add_argument("--ask", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    sure, ask, up = plan(con)
    con.close()
    print(f"待拆词组 {len(up):,}")
    print(f"  ① 确定性（sense_es 有 src_word 凭据）  {len(sure):,} 条 —— 不问模型")
    print(f"  ② 需模型判（来自英文版，源头没分大小写）{len(ask):,} 条")

    if args.sample:
        random.seed(3)
        for it in random.sample(ask, min(args.sample, len(ask))):
            print(f"\n  [{it['id']}] {it['lower']} / {it['upper']}")
            print(f"      zh: {it['zh']}")
            print(f"      en: {it['en']}")
        return
    if not args.ask:
        print("\n未加 --ask，不发请求。")
        return

    # 🔴 **有 RAW 就复用，不重问**。实测重跑同一批、temperature=0，
    #    upper 数从 1,783 变成 1,791 —— 模型不是确定性的。
    #    重问不但多花钱，还会让"已落库的判定"和"当前判定"对不上，无法复核。
    res = {}
    if RAW.exists():
        for line in RAW.open(encoding="utf-8"):
            d = json.loads(line)
            res[d["id"]] = d["w"]
        res = {k: v for k, v in res.items() if k in {it["id"] for it in ask}}
        print(f"  复用已存判定 {len(res):,} 条（RAW），不重问模型")
    if len(res) < len(ask):
        env = dict(l.split("=", 1) for l in paths.ENV.read_text().splitlines()
                   if "=" in l and not l.startswith("#"))
        todo = [it for it in ask if it["id"] not in res]
        print(f"  还缺 {len(todo):,} 条，送模型")
        res.update(asyncio.run(run(todo, env)))
    st = collections.Counter(res.values())
    print(f"  模型判：lower {st['lower']:,}  upper {st['upper']:,}")

    idx = {it["id"]: it for it in ask}
    print("\n判为 upper 的样例（这些会搬到大写词条去）：")
    n = 0
    for sid, w in res.items():
        if w == "upper" and n < 14:
            it = idx[sid]
            print(f"   {it['lower']:<14}→ {it['upper']:<14}{it['zh'][:20]:<22}{it['en'][:44]}")
            n += 1
    RAW.parent.mkdir(parents=True, exist_ok=True)
    with RAW.open("a", encoding="utf-8") as f:
        for sid, w in res.items():
            f.write(json.dumps({"id": sid, "w": w}, ensure_ascii=False) + "\n")
    print(f"\n已存 → {RAW}")

    # ═══ 拆分计划：sense_id → 应归属的专名词形 ═══
    move = {sid: up[idx[sid]["lower"]] for sid, w in res.items() if w == "upper"}
    move.update({sid: tgt for sid, _w, tgt in sure})
    print(f"\n待搬 {len(move):,} 条义项 → {len(set(move.values())):,} 个专名词条")

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    have = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    src = {w: (p, ph, pr, ps) for w, p, ph, pr, ps in con.execute(
        "SELECT word, pos, phonetic, phonetic_raw, phonetic_src FROM dict")}
    con.close()
    need = sorted({t for t in move.values() if t not in have})
    print(f"  其中 {len(need):,} 个专名词条需**新建行**，{len(set(move.values()))-len(need):,} 个已存在")

    # 🔴 全空的词条不要建：某个词形若一条义项都没搬过去，建出来就是空壳
    by_target = collections.Counter(move.values())
    assert all(by_target[t] for t in need)

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    # 新行的音标/词性从小写行复制（同一串字母，读音相同）
    # 专名词形 → 它对应的库内小写词形（用来复制音标/词性）。
    # ⚠️ `setdefault(tgt, None)` 会把 None 占住位，后面再 setdefault 就进不去了 ——
    #    所以只在取到真值时才写。
    lower_of = {}
    for sid, w, tgt in sure:
        lower_of.setdefault(tgt, w)
    for sid, tgt in move.items():
        if sid in idx:
            lower_of.setdefault(tgt, idx[sid]["lower"])
    newrows = []
    for t in need:
        lw = lower_of.get(t)
        p, ph, pr, ps = src.get(lw, (None, None, None, None))
        newrows.append((t, t.lower(), ph, pr, ps, p, 1))

    with dbtool.session("split-case-homographs", expect={
            "__rows__": +len(newrows),
            "phonetic": +sum(1 for r in newrows if r[2]),
            "phonetic_raw": +sum(1 for r in newrows if r[3]),
            "phonetic_src": +sum(1 for r in newrows if r[4]),
            "pos": +sum(1 for r in newrows if r[5]),
    }) as s:
        s.executemany(
            "INSERT INTO dict (word, word_norm, phonetic, phonetic_raw, phonetic_src,"
            " pos, is_lemma) VALUES (?,?,?,?,?,?,?)", newrows)

    # ⚠️ `file:` 前缀必须配 `uri=True`，否则被当成字面文件名 → unable to open database file
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    have = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    con.close()
    plan2 = [(have[t], sid) for sid, t in move.items() if t in have]
    # `sense` 不在 dbtool.TRACK 里（它只看 dict 的列），自己断言
    with dbtool.session("split-case-move-senses", expect={}) as s:
        s.executemany("UPDATE sense SET word_id=? WHERE id=?", plan2)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    ph = ",".join("?" * len(need))
    moved = con.execute(
        "SELECT COUNT(*) FROM sense s JOIN dict d ON d.id = s.word_id "
        f"WHERE d.word IN ({ph})", need).fetchone()[0]
    empty = con.execute(
        f"SELECT COUNT(*) FROM dict d WHERE d.word IN ({ph}) AND NOT EXISTS("
        "SELECT 1 FROM sense s WHERE s.word_id = d.id)", need).fetchone()[0]
    orphan = con.execute(
        "SELECT COUNT(*) FROM sense WHERE word_id NOT IN (SELECT id FROM dict)").fetchone()[0]
    con.close()
    print(f"\n落库：新建 {len(newrows):,} 个专名词条，搬走 {len(plan2):,} 条义项")
    print(f"  新词条名下的义项数 {moved:,}")
    print(f"  🔴 建出来却没有义项的空壳词条：{empty}")
    print(f"  悬空 word_id：{orphan}")
    assert empty == 0 and orphan == 0


if __name__ == "__main__":
    main()
