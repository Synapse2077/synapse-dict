#!/usr/bin/env python3
"""补最后两个缺口：444 条无音标 + 420 条无中文。豆包 pro，关思考。2026-08-03。

═══ 为什么只剩这么点、以及为什么这批必须问模型 ═══
音标缺口原本 4,303 条，其中 4,038 条是**多词词条** —— 已由
`fixes/compose_multiword_ipa.py` 从组件人工音标确定性拼出 3,859 条（纪律⑩）。
剩下的 444 条是拼不出、也算不出的三类：
    外来词   status quo / déjà vu / air bag / cul de sac
             🔴 **绝不能用 G2P 重算** —— 见 es-dict-pipeline：eigenvector 被算成
             `eixembeɡˈtoɾ`。外来词读法是约定俗成，规则推不出来。
    缩写     EEUU / PD / Sra / hnos.  读法是"念字母"还是"念全称"，得看惯例
    符号数字 1ª / &c. / ◌̈           读作 primera / etcétera / diéresis
释义缺口 420 条是 flash 与 v4-pro 都判"拿不准"的（见 fill_nogloss.py），
我已人工写掉 150 条，剩下的交 pro。用户 2026-08-03 拿 `leñatear` 举证：
豆包能给出"拾柴（卡斯蒂利亚乡土词）"，而 v4-pro 标 low 且译错成"用棍棒打"。

═══ 关思考 ═══
用户 2026-08-03："开思考模式，真的太贵了。"这两件都是**生成**不是推导。

═══ 落库前的确定性闸门 ═══
音标：返回值必须**只含本词典的音位字符表**（69 种字符里的核心集），
      有一个越界字符就整条丢弃。这是能确定性做的检查，别指望人眼。
释义：模型给 `conf`，`low` 不落库。

用法（在 es/ 目录）：
    python3 pipeline/fill_last_gaps.py --ipa
    python3 pipeline/fill_last_gaps.py --ipa --apply
    python3 pipeline/fill_last_gaps.py --zh
    python3 pipeline/fill_last_gaps.py --zh --apply
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
import ipa_norm as N
import paths
from pipeline.translate_intake import clean_zh, load_env, loads_lenient

RAW_IPA = paths.WORK / "runs" / "lastgap_ipa.jsonl"
RAW_ZH = paths.WORK / "runs" / "lastgap_zh.jsonl"
RAW_F_IPA = paths.WORK / "runs" / "forced_ipa.jsonl"
RAW_F_ZH = paths.WORK / "runs" / "forced_zh.jsonl"
RAW_F_ZH_D = paths.WORK / "runs" / "forced_zh_doubao.jsonl"
SRC_IPA = "llm-doubao"
SRC_ZH = "llm-doubao"
# 🔴 强推批**单独标源**。用户 2026-08-03 在我提示"硬填准确率约五成"之后仍决定强推，
#    那是他的决定；我的责任是让这批**随时能一条 SQL 撤干净**，而不是混进正常数据里。
#    `conf` 也一并写进 meta 之外的地方？不 —— 保持列语义干净，靠 src 区分就够。
SRC_FORCED = "llm-v4pro-forced"
CHUNK, PAR = 30, 8

# 本词典的音位字符表（从全库 113 万条音标做字符普查得出的核心集）。
# 越界即丢 —— 模型爱吐 ŋ/β/ð/ɣ/ɟ/ç 这些我们不存的符号。
OK_CHARS = set("aeiou" "bdfklmnprstxɡɲɾθʃʝjw" "ˈˌ" " |")

SYS_IPA = """你在给一部西班牙语词典补音标。给你若干词条（词、词性、中文释义）。
给出**西班牙半岛标准音**的音标。

🔴 本词典的记法约定（必须严格遵守，多一个符号整条作废）：
- **裸音标，不加 // 或 []**。
- 只用这些字符：a e i o u b d f k l m n p r s t x ɡ ɲ ɾ θ ʃ ʝ j w ˈ ˌ 空格
- **不要用** ŋ β ð ɣ ɟ ç ʎ ʧ ː . （音节点）等。塞音就写 b d ɡ，不写擦化的 β ð ɣ；
  n 一律写 n，不写 ŋ；ch 写作 tʃ（两个字符）；ll/y 写作 ʝ。
- 区分 θ（z、ce、ci）与 s；区分 r（词首/rr，颤音）与 ɾ（单闪音）。
- 主重音 ˈ 放在重读音节**之前**，次重音 ˌ。多词词条每个实词各带自己的重音。
- 例：perro → ˈpero ；gracias → ˈɡɾaθjas ；chico → ˈtʃiko ；calle → ˈkaʝe ；
      Costa Rica → ˈkosta ˈrika

这批词的特点与处理：
- **外来词**（status quo / déjà vu / air bag / cul de sac）：按**西语使用者的实际读法**
  转写，不要照搬原语言音系，也不要用规则硬拼。
- **缩写**（EEUU / PD / Sra / hnos.）：按西语惯例——念字母的就写字母名
  （PD → ˈpe ˈde），念全称的就写全称（Sra → seˈɲoɾa）。
- **符号与序数**（1ª / &c. / ◌̈）：写它读出来的那个词（1ª → pɾiˈmeɾa）。
- 🔴 **拿不准就给空字符串**，我宁可留空也不要一个编的音标。

严格输出 JSON：{"r":[{"w":"词","ipa":"音标 或 空字符串"}]}"""

SYS_ZH = """你是西班牙语→中文词典编纂者。给你若干**真实存在但维基词典没写释义**的西语词，
请给出中文词典式释义。这些词大多是 DRAE 收录的罕用词、古语或拉美方言词。

线索（都只是线索）：pos 词性；ety 西语版词源；root 我们词典里已有的疑似词根及其中文
（机器拆的，会拆错，与词义对不上就别用）。

要求：
- 输出**中文词典式释义**，近义说法用逗号分隔，多义用「；」分隔。句末不加句号。
- 地域性强的词请标出地区，如「（智利）」「（墨西哥）」「（卡斯蒂利亚）」。
- 每条给 `conf`：high＝你认识这个词或构词完全透明；medium＝方向明确措辞有余地；
  low＝基本靠猜。
- 🔴 **不要写元描述**（"某某的变体""动词，及物"），要写词义本身。
- 以 -se 结尾的是自复动词，中文用不及物说法。
- 🔴 真的认不出就给空字符串。留空比编一个强。

严格输出 JSON：{"r":[{"w":"词","zh":"释义 或 空字符串","conf":"high|medium|low"}]}"""

# ── 强推模式：不许弃权 ──
SYS_F_ZH = """你是西班牙语→中文词典编纂者。给你若干**极其生僻**的西语词 ——
维基词典六个语言版都没写释义，前面几轮模型都判"拿不准"。

🔴 **这一轮不接受弃权，每个词都必须给出中文释义。**
按下面的顺序尽最大努力：
  ① 你确实认识这个词（DRAE 罕用词、古语、拉美方言词）→ 直接给。
  ② 不认识但构词可解 → 按前缀＋词根＋后缀推（`des-`＝反向，`a-/en-`＋名词＝使成为，
     `-ear`＝反复/从事，`-izar`＝使…化，`-se`＝自复）。
  ③ 连词根都认不出 → 也要给一个最合理的推测。

`conf` 照实标：high＝认识或构词全透明；medium＝构词可解；low＝基本靠猜。
**标 low 不丢分**，我要的是诚实的把握度，不是好看的分布。

其余要求同词典体例：中文释义词组，近义用逗号、多义用「；」，句末不加句号，
地域词标出地区，不写元描述，-se 结尾用不及物说法。
若给了 `n_senses`，必须返回**正好这么多条**中文（用「；」分隔算一条，换行不算）。

严格输出 JSON：{"r":[{"w":"词","zh":"释义","conf":"high|medium|low"}]}"""

SYS_F_IPA = SYS_IPA.replace(
    "- 🔴 **拿不准就给空字符串**，我宁可留空也不要一个编的音标。",
    "- 🔴 **这一轮不接受空字符串，每个词都必须给出音标。**\n"
    "  英语借词按西语使用者的实际读法转写（talk shows → ˈtok ˈʃows）；\n"
    "  符号组合读出它的名称；地名按拼写照西语音系读。")


def ipa_targets():
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word, pos, translation FROM dict "
        "WHERE TRIM(COALESCE(phonetic,''))='' ORDER BY id").fetchall()
    conn.close()
    return [{"id": r[0], "w": r[1], "pos": r[2] or "",
             "zh": (r[3] or "").split("\n")[0][:40]} for r in rows]


def zh_targets():
    ev = {x["w"]: x for x in json.loads(
        (paths.WORK / "nogloss_evidence.json").read_text(encoding="utf-8"))}
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 🔴 **必须同时要求 definition_es 为空。**
    #    只按"translation 为空"选，会捞进那些**有多个义项**、只是先前批次
    #    因条数不符被丢掉的行（jarciería 有 5 个义项）。给它们写一行中文，
    #    meta 5 项 / translation 1 行 —— 正是 align_check 要防的错位，我犯了 7 条。
    #    有 definition_es 的行归 translate_intake 管，那条管线有逐条数校验。
    rows = conn.execute(
        "SELECT id, word, pos FROM dict WHERE is_lemma=1 "
        "AND TRIM(COALESCE(translation,''))='' "
        "AND TRIM(COALESCE(definition_es,''))='' ORDER BY id").fetchall()
    conn.close()
    out = []
    for rid, w, pos in rows:
        it = {"id": rid, "w": w, "pos": pos or ""}
        e = ev.get(w, {})
        if e.get("ety"):
            it["ety"] = e["ety"]
        if e.get("root"):
            it["root"] = e["root"]
        out.append(it)
    return out


# 模型爱吐、而我们不存的符号 → 归一到本词典的写法。
# 🔴 **先归一再过闸，不是直接丢**：第一版直接丢，拦下 67 条里绝大多数是
#    β/ð（擦化的 b/d），那正是 `ipa_norm.spirants_to_stops` 每天在做的转换 ——
#    我们自己有现成的、已验证的规则，却把数据扔了。
EXTRA_MAP = {"ŋ": "n", "z": "s", "ʎ": "ʝ", "ç": "θ", "ɟ": "ʝ", "ʧ": "tʃ",
             "ɱ": "m", "ʈ": "t", "ʂ": "s", "ʒ": "ʝ", "ː": "", ".": "", "'": "ˈ"}


def norm_ipa(word, s):
    """模型返回值 → 本词典的裸音位串。用我们自己那套已验证的归一化。"""
    s = (s or "").strip().strip("/[]").strip()
    if not s:
        return ""
    s = N.normalize(word, s)
    for a, b in EXTRA_MAP.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def bad_ipa(s):
    """越界字符 → 返回它们；干净则返回空。确定性闸门，不靠人眼。"""
    return "".join(sorted({c for c in s if c not in OK_CHARS}))


async def run(items, sysmsg, raw_path, key_out):
    import httpx  # noqa: F401  （豆包走 SDK，这里只为统一异常处理）
    from volcenginesdkarkruntime import AsyncArk
    env = load_env()
    done = set()
    if raw_path.exists():
        for ln in open(raw_path, encoding="utf-8"):
            try:
                done.add(json.loads(ln)["w"])
            except Exception:
                pass
    todo = [x for x in items if x["w"] not in done]
    chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    print("■ 待补 {:,}（已完成 {:,}），{} 块，豆包 pro 关思考".format(
        len(todo), len(done), len(chunks)))
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=900)
    sem, lock = asyncio.Semaphore(PAR), asyncio.Lock()
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(raw_path, "a", encoding="utf-8")
    stat = collections.Counter()
    t0 = time.time()

    async def one(chunk):
        async with sem:
            for a in range(3):
                try:
                    r = await cl.chat.completions.create(
                        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
                        thinking={"type": "disabled"},
                        messages=[{"role": "system", "content": sysmsg},
                                  {"role": "user", "content": json.dumps(
                                      [{k: v for k, v in x.items() if k != "id"}
                                       for x in chunk], ensure_ascii=False)}])
                    raw = r.choices[0].message.content
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
                    rec = {"w": it["w"], "id": it["id"], key_out: g.get(key_out) or ""}
                    if "conf" in g:
                        rec["conf"] = g["conf"]
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    stat["有返回"] += 1
                stat["块"] += 1

    await asyncio.gather(*[one(c) for c in chunks])
    f.close()
    print("■ 跑完 {:.0f}s：{}".format(time.time() - t0, dict(stat)))


def load_raw(path, key):
    out = {}
    if not path.exists():
        return out
    for ln in open(path, encoding="utf-8"):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        out[r["id"]] = r
    return out


def apply_ipa(do):
    cur = {x["id"]: x["w"] for x in ipa_targets()}
    raw = load_raw(RAW_IPA, "ipa")
    plan, samples, stat = [], [], collections.Counter()
    for rid, r in raw.items():
        if cur.get(rid) != r["w"]:
            continue
        if not (r.get("ipa") or "").strip():
            stat["模型弃权"] += 1
            continue
        v = norm_ipa(r["w"], r["ipa"])
        bad = bad_ipa(v)
        if bad:
            stat["越界字符被拦"] += 1
            if stat["越界字符被拦"] <= 8:
                print("   拦下 %-16s %-24s 越界字符=%s" % (r["w"], v, bad))
            continue
        stat["落库"] += 1
        plan.append((v, v, SRC_IPA, rid))
        samples.append((r["w"], v))
    print("■ 音标：{}".format(dict(stat)))
    dbtool.sample_check(samples, n=18, cols=("词", "豆包给的音标"))
    if not do or not plan:
        return
    with dbtool.session("lastgap-ipa",
                        expect={"phonetic": len(plan), "phonetic_raw": len(plan),
                                "phonetic_src": len(plan)}) as s:
        s.executemany(
            "UPDATE dict SET phonetic=?, phonetic_raw=?, phonetic_src=? WHERE id=?",
            plan)


def apply_zh(do):
    cur = {x["id"]: x["w"] for x in zh_targets()}
    raw = load_raw(RAW_ZH, "zh")
    plan, samples, stat = [], [], collections.Counter()
    for rid, r in raw.items():
        if cur.get(rid) != r["w"]:
            continue
        v = clean_zh(r.get("zh") or "")
        conf = r.get("conf", "?")
        if not v:
            stat["弃权"] += 1
            continue
        if conf == "low":
            stat["low 不落库"] += 1
            continue
        if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", re.sub(r"\([^)]*\)|（[^）]*）", "", v)):
            stat["译文里残留西语词，拦下"] += 1
            continue
        stat["落库 " + conf] += 1
        plan.append((v, SRC_ZH, rid))
        samples.append((r["w"], conf, v[:40]))
    print("■ 释义：{}".format(dict(stat)))
    dbtool.sample_check(samples, n=18, cols=("词", "把握", "豆包给的中文"))
    if not do or not plan:
        return
    with dbtool.session("lastgap-zh", expect={"translation": len(plan)}) as s:
        s.executemany(
            "UPDATE dict SET translation=?, translation_src=? WHERE id=?", plan)
    dbtool.align_check()


async def run_v4pro(items, sysmsg, raw_path, key_out, model="v4pro"):
    """强推。model='v4pro' 走 deepseek 端点，'doubao' 走 Ark。都关思考。"""
    import httpx
    env = load_env()
    key = env["DEEPSEEK_API_KEY"]
    ark = None
    if model == "doubao":
        from volcenginesdkarkruntime import AsyncArk
        ark = AsyncArk(api_key=env["ARK_API_KEY"], timeout=900)
    done = set()
    if raw_path.exists():
        for ln in open(raw_path, encoding="utf-8"):
            try:
                done.add(json.loads(ln)["w"])
            except Exception:
                pass
    todo = [x for x in items if x["w"] not in done]
    chunks = [todo[i:i + 25] for i in range(0, len(todo), 25)]
    print("■ 强推 {:,} 条（已完成 {:,}），{} 块，v4-pro 关思考".format(
        len(todo), len(done), len(chunks)))
    sem, lock = asyncio.Semaphore(8), asyncio.Lock()
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(raw_path, "a", encoding="utf-8")
    stat = collections.Counter()

    async def one(chunk):
        body = {"model": "deepseek-v4-pro",
                "messages": [{"role": "system", "content": sysmsg},
                             {"role": "user", "content": json.dumps(
                                 [{k: v for k, v in x.items() if k != "id"}
                                  for x in chunk], ensure_ascii=False)}],
                "temperature": 0, "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"}, "stream": False}
        async with sem:
            for a in range(3):
                try:
                    if ark is not None:
                        rr = await ark.chat.completions.create(
                            model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
                            thinking={"type": "disabled"},
                            messages=body["messages"])
                        raw = rr.choices[0].message.content
                    else:
                        async with httpx.AsyncClient(timeout=900) as cl:
                            r = await cl.post(
                                "https://api.deepseek.com/chat/completions",
                                headers={"Authorization": "Bearer " + key}, json=body)
                            if r.status_code != 200:
                                raise RuntimeError(str(r.status_code))
                            raw = json.loads(r.text.lstrip())["choices"][0]["message"]["content"]
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
                    rec = {"w": it["w"], "id": it["id"], key_out: g.get(key_out) or "",
                           "conf": g.get("conf", "?")}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    stat["有返回"] += 1

    await asyncio.gather(*[one(c) for c in chunks])
    f.close()
    print("■ {}".format(dict(stat)))


def forced(do_ipa, do_zh, apply_it):
    if do_ipa:
        items = ipa_targets()
        if not apply_it:
            asyncio.run(run_v4pro(items, SYS_F_IPA, RAW_F_IPA, "ipa"))
        cur = {x["id"]: x["w"] for x in ipa_targets()}
        raw = load_raw(RAW_F_IPA, "ipa")
        plan, samples, stat = [], [], collections.Counter()
        for rid, r in raw.items():
            if cur.get(rid) != r["w"]:
                continue
            v = norm_ipa(r["w"], r.get("ipa") or "")
            if not v or bad_ipa(v):
                stat["仍拿不到合规音标"] += 1
                continue
            stat["落库"] += 1
            plan.append((v, v, SRC_FORCED, rid))
            samples.append((r["w"], r.get("conf", "?"), v))
        print("■ 强推音标：{}".format(dict(stat)))
        dbtool.sample_check(samples, n=20, cols=("词", "把握", "音标"))
        if apply_it and plan:
            with dbtool.session("forced-ipa", expect={
                    "phonetic": len(plan), "phonetic_raw": len(plan),
                    "phonetic_src": len(plan)}) as s:
                s.executemany("UPDATE dict SET phonetic=?, phonetic_raw=?, "
                              "phonetic_src=? WHERE id=?", plan)
        return
    if do_zh:
        conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        rows = conn.execute(
            "SELECT id, word, pos, definition_es FROM dict WHERE is_lemma=1 "
            "AND TRIM(COALESCE(translation,''))='' ORDER BY id").fetchall()
        conn.close()
        ev = {x["w"]: x for x in json.loads(
            (paths.WORK / "nogloss_evidence.json").read_text(encoding="utf-8"))}
        items, nsense = [], {}
        for rid, w, pos, de in rows:
            it = {"id": rid, "w": w, "pos": pos or ""}
            e = ev.get(w, {})
            if e.get("ety"):
                it["ety"] = e["ety"]
            if e.get("root"):
                it["root"] = e["root"]
            n = len(de.split("\n")) if de and de.strip() else 1
            nsense[rid] = n
            if n > 1:
                it["n_senses"] = n
                it["es"] = de.split("\n")
            items.append(it)
        if not apply_it:
            asyncio.run(run_v4pro(items, SYS_F_ZH, RAW_F_ZH, "zh"))
        cur = {rid: w for rid, w, _, _ in rows}
        raw = load_raw(RAW_F_ZH, "zh")
        plan, samples, stat = [], [], collections.Counter()
        for rid, r in raw.items():
            if cur.get(rid) != r["w"]:
                continue
            v = clean_zh(r.get("zh") or "")
            if not v:
                stat["仍空"] += 1
                continue
            # 多义项行：条数必须对上 meta，否则不落（这正是我上一轮踩的坑）
            if nsense.get(rid, 1) > 1 and len(v.split("\n")) != nsense[rid]:
                stat["多义项条数不符，不落"] += 1
                continue
            stat["落库 " + r.get("conf", "?")] += 1
            plan.append((v, SRC_FORCED, rid))
            samples.append((r["w"], r.get("conf", "?"), v[:40]))
        print("■ 强推释义：{}".format(dict(stat)))
        dbtool.sample_check(samples, n=20, cols=("词", "把握", "中文"))
        if apply_it and plan:
            with dbtool.session("forced-zh", expect={"translation": len(plan)}) as s:
                s.executemany("UPDATE dict SET translation=?, translation_src=? "
                              "WHERE id=?", plan)
            dbtool.align_check()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ipa", action="store_true")
    ap.add_argument("--zh", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="强推：v4-pro，不许弃权，单独标 llm-v4pro-forced")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.force:
        forced(a.ipa, a.zh, a.apply)
        return
    if a.ipa:
        items = ipa_targets()
        if not a.apply:
            asyncio.run(run(items, SYS_IPA, RAW_IPA, "ipa"))
        apply_ipa(a.apply)
    elif a.zh:
        items = zh_targets()
        if not a.apply:
            asyncio.run(run(items, SYS_ZH, RAW_ZH, "zh"))
        apply_zh(a.apply)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
