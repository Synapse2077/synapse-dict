#!/usr/bin/env python3
"""给西语版新收的 54,206 个 lemma 填中文译文。2026-08-03。

分两段，**顺序不能反**：

  ① `--tmpl`  确定性模板（本段，不花钱、不调模型）
     西语版的释义高度模板化：单是 `Apellido.` 就占 41.1%。
     43.0% 的义项（26,136 条）能由规则直接译出，剩下的才值得送模型。
     其中 `Aumentativo de cazuela` 这类不写成"cazuela 的增大形式"这种元描述 ——
     **回库查 cazuela 的中文**，写成"砂锅的增大形式"，让它带真实语义。
     查不到中文的，本段不碰，留给 ②。

  ② `--llm`   deepseek-v4-flash 关思考翻剩下的 34,581 条
     flash 关思考已在 2026-08-03 验证过够用（约 46 tokens/义项）；
     翻译是生成不是推导，不需要思考模式。

🔴 `definition_es` 是西语版原文，**本脚本一个字节都不动它**。译文只进 `translation`。

用法（在 es/ 目录）：
    python3 pipeline/translate_intake.py --tmpl
    python3 pipeline/translate_intake.py --tmpl --apply
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

SRC_TMPL = "template-es-edition"

# 模板：(正则, 组装函数)。**只放语义完全确定的**，一点含糊都不放 ——
# 词典里错一条比缺一条更伤权威，模板译错是会成千上万条一起错的。
FIXED = {
    "Apellido": "姓氏",
    "Nombre de pila de mujer": "女性名字",
    "Nombre de pila de varón": "男性名字",
    "Nombre de pila": "名字",
}
# 🔴 `Aumentativo/Diminutivo/Superlativo de X` **不做模板**（480 条，撤掉了）。
#    做过一版："查库里 X 的中文首义 + 的指小形式"。抽样第一眼就翻车：
#      doctorcito → Diminutivo de doctor → 库里 doctor 首义是"博士" → "博士的指小形式"
#    而 doctorcito 说的是"小医生"。**取第一义就是在替源头选义，会成批选错。**
#    480 条不值得为它冒这个险 → 连同原形的完整译文一起送 ②，让模型看着全部义项选。
DERIV = ()


def zh_of(word, lex):
    """库里这个词的中文首义。取不到返回 None。

    只取**第一行**：派生形式的语义锚在本义上，把全部义项拼进来会得到一坨。
    """
    t = lex.get(word.lower())
    if not t:
        return None
    first = t.split("\n")[0].strip()
    return first or None


def translate(gloss, lex):
    """一条西语释义 → 中文；模板不认返回 None（留给 LLM 段）。"""
    s = gloss.strip().rstrip(".").strip()
    if s in FIXED:
        return FIXED[s]
    for rx, suffix in DERIV:
        m = rx.match(s)
        if not m:
            continue
        base = m.group(1).strip().rstrip(".").strip()
        zh = zh_of(base, lex)
        if not zh:
            return None          # 查不到本义就别硬写元描述，交给 ②
        return zh + suffix
    return None


def build():
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    lex = {w.lower(): t for w, t in conn.execute(
        "SELECT word, translation FROM dict WHERE is_lemma=1 "
        "AND TRIM(COALESCE(translation,''))<>''")}
    rows = conn.execute(
        "SELECT id, word, definition_es, meta FROM dict "
        "WHERE TRIM(COALESCE(definition_es,''))<>'' "
        "AND TRIM(COALESCE(translation,''))=''").fetchall()
    conn.close()

    plan, samples, stat = [], [], collections.Counter()
    for rid, w, dfn, mj in rows:
        gl = dfn.split("\n")
        zh = [translate(g, lex) for g in gl]
        done = sum(1 for x in zh if x)
        stat["义项总数"] += len(gl)
        stat["模板译出"] += done
        if done != len(gl):
            # **整行要么全译要么不译**：translation 与 meta 逐行对齐，
            # 半行译文会让第 3 个义项的中文落在第 2 行上 —— topics 那次就是这么错的。
            stat["整行留给LLM"] += 1
            continue
        stat["整行译出"] += 1
        meta = json.loads(mj) if mj else []
        assert len(meta) == len(gl), w
        plan.append(("\n".join(zh), SRC_TMPL, rid))
        if len(samples) < 500:
            samples.append((w, gl[0][:34], " / ".join(zh)[:26]))
    return plan, samples, stat


# ═══ ② LLM 段 ═══

RAW = paths.WORK / "runs" / "intake_flash.jsonl"      # 逐块原始返回，可断点续跑
SRC_LLM = "llm-flash"
CHUNK = 30            # 每请求的词条数（义项平均 76 字符，约 1,200 tokens 输入）
PAR = 12              # 并发

SYS = """你是西班牙语→中文词典译者。给你若干西班牙语词条，每条带词性和它在
**西语版维基词典**里的西班牙语释义。把每条西语释义翻成**中文词典式释义**。

要求：
- 输出**中文释义词组**，近义说法用逗号分隔，例如「裁纸刀」「急迫，渴望」。
- 一条西语释义对应一条中文释义，**顺序一一对应，条数必须相同**。
- 不要输出解释、不要加引号、不要重复西语原文、不要加"意思是"这类话。
- 释义里的括号内学名（如 (Sambucus ebulus)）保留在中文里，写成「(Sambucus ebulus) 接骨草」。
- 西语释义若本身是元描述（"某词的同义词/变体/缩写"），中文也照实写。
- **句末不要加句号**（本词典的中文释义一律不带句末标点）。
- 若给了 `base_zh`，那是该词原形在本词典里的**全部**中文义项；
  请从中挑**语境相符的那一个**再加派生说明（如「小医生」而不是「博士的指小形式」），
  不要默认取第一个。
- 若给了 `ref_zh`（形如 {"brincar": ["蹦跳，跳跃"]}），那是本条释义所指向的那个西语词
  在本词典里的中文。🔴 **译文里不许只留一个西语词**：`blincar` 要译成
  「蹦跳，跳跃（brincar 的变体）」，不能写成「brincar 的变体」——
  用户看到的是中文弹窗，留个西语词等于没释义。
  🔴 **但输出条数仍然等于 `es` 的条数**：`ref_zh` 里有 4 条义项、而 `es` 只有 1 条时，
  要把它们**压成一行**（用「；」分隔），末尾只写一次变体说明，例如
  「甲；乙；丙（Abajador 的旧拼写）」。不要拆成 4 行 —— 条数一错整条会被丢弃。
- 若给了 `tag`，那是本词的**使用范围标注**（地区/语域），供你判断语境用，
  🔴 **不要把它写进释义正文**。原文没说"旧称/过时"就不要写。
- 🔴 词形以 **-se** 结尾、或释义写着 `uso pronominal / forma pronominal` 的，
  是**自复（代词式）动词**，中文要用**不及物/自身承受**的说法：
  `afofarse` = 「变松软」不是「使某物变松软」；`malvezarse` = 「染上坏习惯」不是
  「使养成坏习惯」；`descristianizarse` = 「变得非基督教化」不是「使非基督教化」。
- 🔴 被引词有多条义项、而本词是**固定短语或俗语**时，只取**语境相符的那一条**，
  不要把被引词的义项全搬过来：`en pelota picada` 的原文是 `Desnudo.`，
  译「赤身裸体的」即可，不要连 desnudo 的"一贫如洗""明显的"一起搬。

严格输出 JSON：{"r":[{"w":"词","zh":["释义1","释义2"]}]}"""

DERIV_RX = re.compile(r"^(Aumentativo|Diminutivo|Despectivo|Superlativo) de (.+?)\.?$")

# 交叉引用型释义：西语版直接写"见 X"。全库 3,185 行（占 flash 译文 11.1%）。
# 🔴 2026-08-03 验收逮出来的**最大一族真缺陷**：这类词 flash 会照抄成
#    `blincar → "brincar 的变体"` —— 用户点开只看到**另一个西语词**，等于没释义。
#    而 X 的中文我们库里明明有（brincar = 蹦跳，跳跃）。
#    → payload 必须把 X 的中文一并给（纪律⑧：权威源真值要进 payload）。
#    这与 [[clitic-compound-gloss-defect]] 记的"gloss=元描述"是同一族缺陷，又长出来一次。
XREF_RX = [re.compile(p, re.I) for p in (
    r"^(?:variante|sinónimo|grafía|forma|otra forma|variante gráfica)\b[^.]*?"
    r"\bde\s+([A-Za-zÁÉÍÓÚÑáéíóúñü][\w áéíóúñü'-]{2,}?)\.?$",
    r"^([A-Za-zÁÉÍÓÚÑáéíóúñü][\wáéíóúñü'-]{2,})\s*"
    r"\((?:uso pronominal|forma pronominal|variante)[^)]*\)\.?$",
    r"^([A-Za-zÁÉÍÓÚÑáéíóúñü][\wáéíóúñü'-]{2,})\.?$",
)]
# 译文里剩下的拉丁字母 —— 括号内是有意保留的（学名、原词附注），先剔掉再看
PAREN_ANY = re.compile(r"\([^)]*\)|（[^）]*）")
LATIN = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñü]{3,}")


def xrefs_of(word, glosses, lex):
    """这条释义指向的西语词 → 它在本词典里的中文。没有返回 {}。"""
    out = {}
    for g in glosses:
        s = g.strip()
        for rx in XREF_RX:
            m = rx.match(s)
            if not m:
                continue
            x = m.group(1).strip().lower()
            if x != word.lower() and lex.get(x):
                out[m.group(1).strip()] = lex[x].split("\n")
            break
    return out

# 维基的上标残渣，wiktextract 把它当成释义的一部分带了进来：
# `Hacer aséptica alguna cosa.^([cita requerida])`，`arterializar` 更是整条只剩这个。
# 全库 301 条。**只在送模型的 payload 里剥掉，不动 `definition_es`** ——
# 那一列的性质是"西语版原值"，动了就再也证明不了。
# 剥完为空的（1 条）不送模型：宁可留空，也不让它照着词形编一个。
ARTIFACT = re.compile(r"\^\(\[[^\]]*\]\)")
# flash 爱在句末加「。」，而库里已有的 8,363 行豆包译文**没有一行**以句号结尾。
# 风格不统一在弹窗里一眼就看得出来 → 落库前统一剥掉。
TAIL = "。.；;，,、 \t"


def clean_zh(x):
    return (x or "").strip().strip("\"'“”「」").rstrip(TAIL).strip()


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
        return json.loads(re.sub(r",\s*([}\]])", r"\1", s))


# 族②：译文凭空断言"旧称/过时/变体"，而西语原文一个字都没说。
# 根因是我把 reg/lex 标签塞进 payload 却没说明它是什么（`Chiloé` → "奇洛埃岛旧称"）。
# ⚠️ 第一版判据只查中文侧，误报一大片 —— `Islas Gilbert` 的"旧称"，
#    西语原文里就写着 `nombre con el que se conocía`。西语侧的说法**远不止**
#    antiguo/desusado 几个词，漏一个就是一条误报。
ASSERT_ZH = re.compile(r"旧称|旧式|旧形式|过时|古语|废弃|已废|旧拼写")
ASSERT_ES = re.compile(
    r"antigu|desusad|anticuad|obsolet|arcai|variante|grafía|se conocía|antaño|"
    r"en el pasado|se llamaba|actualmente|hoy |desus|former|poco usad", re.I)


PRON_ES = re.compile(r"\((?:uso pronominal|forma pronominal)", re.I)
CAUSATIVE_ZH = re.compile(r"^(?:使|令|让)")


def retranslate_targets():
    """要定点重翻的行。两族：

    ① **全部**交叉引用行 —— 不只是"译文残留西语词"的那些。
       `cortaviento` 的第二义 `Variante de rompevientos.` 被译成"破风机的变体"，
       中文里一个拉丁字母都没有，残留检测**逮不住**；病在瞎译，不在残留。
       库里明明有 rompevientos = 防风林 —— 只要 payload 给了它就不会错。
       → 判据从"看译文长什么样"改成"**看这条释义是不是交叉引用**"。
    ② 译文凭空断言"旧称/过时"的（标签泄漏）。
    """
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    lex = {w.lower(): t for w, t in conn.execute(
        "SELECT word, translation FROM dict WHERE is_lemma=1 "
        "AND TRIM(COALESCE(translation,''))<>''")}
    rows = conn.execute(
        "SELECT id, word, definition_es, translation FROM dict "
        "WHERE translation_src=?", (SRC_LLM,)).fetchall()
    conn.close()
    ids, stat = set(), collections.Counter()
    for rid, w, d, t in rows:
        gl, zh = d.split("\n"), (t or "").split("\n")
        if xrefs_of(w, gl, lex):
            ids.add(rid)
            stat["① 交叉引用"] += 1
            continue
        if any(ASSERT_ZH.search(z) and not ASSERT_ES.search(g)
               for g, z in zip(gl, zh)):
            ids.add(rid)
            stat["② 凭空断言旧称/过时"] += 1
            continue
        # ③ 自复动词被译成及物使动：`afofarse` → "使某物变松软"（应为"变松软"）。
        #    第二轮验收逮出来的，713 条自复义项里 154 条中招。
        if any(PRON_ES.search(g) and CAUSATIVE_ZH.search(z) for g, z in zip(gl, zh)):
            ids.add(rid)
            stat["③ 自复译成了使动"] += 1
    print("■ 重翻对象：{}".format(dict(stat)))
    return ids


def llm_items(limit=None, words=None, ids=None):
    """待译清单。payload 带权威源真值：西语原文 + 词性 + 地区语域 + 派生词的原形译文。"""
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    lex = {w.lower(): t for w, t in conn.execute(
        "SELECT word, translation FROM dict WHERE is_lemma=1 "
        "AND TRIM(COALESCE(translation,''))<>''")}
    rows = conn.execute(
        ("SELECT id, word, pos, definition_es, meta FROM dict "
         "WHERE TRIM(COALESCE(definition_es,''))<>''" +
         ("" if ids else " AND TRIM(COALESCE(translation,''))=''") +
         " ORDER BY id")).fetchall()
    conn.close()
    out = []
    for rid, w, pos, dfn, mj in rows:
        if words is not None and w not in words:
            continue
        if ids is not None and rid not in ids:
            continue
        gl = dfn.split("\n")
        clean = [ARTIFACT.sub("", g).strip() for g in gl]
        if not all(clean):
            continue           # 剥完有空行 → 整条不送（条数对不上，且没东西可译）
        meta = json.loads(mj) if mj else []
        it = {"id": rid, "w": w, "pos": pos, "es": clean}
        hint = sorted({x for m in meta for x in (m.get("reg") or []) + (m.get("lex") or [])})
        if hint:
            it["tag"] = hint
        for g in gl:
            m = DERIV_RX.match(g.strip())
            if m and lex.get(m.group(2).lower()):
                it["base_zh"] = lex[m.group(2).lower()].split("\n")
                break
        ref = xrefs_of(w, clean, lex)
        if ref:
            it["ref_zh"] = ref
        out.append(it)
        if limit and len(out) >= limit:
            break
    return out


async def _one(cl, key, chunk):
    body = {"model": "deepseek-v4-flash",
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": json.dumps(
                             [{k: v for k, v in it.items() if k != "id"} for it in chunk],
                             ensure_ascii=False)}],
            "temperature": 0, "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},    # 翻译是生成不是推导，不开思考
            "stream": False}
    r = await cl.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": "Bearer " + key}, json=body)
    if r.status_code != 200:
        raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:160]))
    d = json.loads(r.text.lstrip())
    return d["choices"][0]["message"]["content"], (d.get("usage") or {})


async def run_llm(items, done):
    import httpx
    key = load_env()["DEEPSEEK_API_KEY"]
    todo = [it for it in items if it["w"] not in done]
    chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    print("■ 待译 {:,} 词条（已完成 {:,}），切成 {:,} 块，并发 {}".format(
        len(todo), len(done), len(chunks), PAR))
    sem = asyncio.Semaphore(PAR)
    lock = asyncio.Lock()
    usage = collections.Counter()
    t0 = time.time()
    RAW.parent.mkdir(parents=True, exist_ok=True)
    f = open(RAW, "a", encoding="utf-8")

    async def go(i, chunk):
        async with sem:
            async with httpx.AsyncClient(timeout=600) as cl:
                for attempt in range(3):
                    try:
                        raw, u = await _one(cl, key, chunk)
                        break
                    except Exception as e:
                        if attempt == 2:
                            print("🔴 块 %d 三次失败：%s" % (i, e))
                            return
                        await asyncio.sleep(2 * (attempt + 1))
            try:
                got = {x.get("w"): (x.get("zh") or [])
                       for x in (loads_lenient(raw).get("r") or [])}
            except Exception as e:
                print("🔴 块 %d 解析失败：%s" % (i, e))
                return
            async with lock:
                for it in chunk:
                    zh = [clean_zh(x) for x in (got.get(it["w"]) or [])]
                    zh = zh if all(zh) else None
                    # 🔴 **条数不等就整条丢弃**：translation 与 meta 逐行对齐，
                    #    少一条会让后面所有义项的中文错位一行。宁可留空。
                    if not zh or len(zh) != len(it["es"]):
                        usage["条数不符/无输出"] += 1
                        continue
                    f.write(json.dumps({"w": it["w"], "id": it["id"], "zh": zh},
                                       ensure_ascii=False) + "\n")
                    usage["已译"] += 1
                usage["tokens"] += u.get("total_tokens") or 0
                usage["块"] += 1
                if usage["块"] % 40 == 0:
                    f.flush()
                    print("   {:>5}/{:<5} 块  已译 {:>6,}  tokens {:>10,}  {:.0f}s".format(
                        usage["块"], len(chunks), usage["已译"], usage["tokens"],
                        time.time() - t0))

    await asyncio.gather(*[go(i, c) for i, c in enumerate(chunks)])
    f.close()
    print("■ 跑完 {:.0f}s：已译 {:,}，条数不符/无输出 {:,}，tokens {:,}".format(
        time.time() - t0, usage["已译"], usage["条数不符/无输出"], usage["tokens"]))


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


def apply_llm(pending_only=True):
    """把 RAW 里的译文落库。**再校一次条数**（RAW 可能来自旧一轮）。

    `pending_only=False` 用于重翻：那批行本来就有译文，只是内容不合格。
    """
    done = load_done()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cur = {rid: (w, d) for rid, w, d in conn.execute(
        "SELECT id, word, definition_es FROM dict "
        "WHERE TRIM(COALESCE(definition_es,''))<>''" +
        (" AND TRIM(COALESCE(translation,''))=''" if pending_only else ""))}
    conn.close()
    plan, samples, skip = [], [], 0
    for r in done.values():
        row = cur.get(r["id"])
        if not row or row[0] != r["w"]:
            continue
        gl = row[1].split("\n")
        zh = [clean_zh(x) for x in r["zh"]]
        if len(zh) != len(gl) or not all(zh):
            skip += 1
            continue
        plan.append(("\n".join(zh), SRC_LLM, r["id"]))
        if len(samples) < 600:
            samples.append((r["w"], gl[0][:38], " / ".join(zh)[:30]))
    print("■ RAW 里 {:,} 条，可落库 {:,}，条数对不上跳过 {:,}".format(
        len(done), len(plan), skip))
    dbtool.sample_check(samples, n=16, cols=("词", "西语版原文", "flash 中文"))
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tmpl", action="store_true")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--pilot", type=int, default=0, help="只跑前 N 条试水")
    ap.add_argument("--fix-xref", action="store_true",
                    help="定点重翻交叉引用型缺陷行（译文仍是个西语词的）")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if a.fix_xref:
        global RAW
        RAW = paths.WORK / "runs" / "intake_flash_xref.jsonl"
        ids = retranslate_targets()
        # 先前批次因条数不符被丢掉、至今 translation 仍空的行，一并捡回来
        _c = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        ids |= {r[0] for r in _c.execute(
            "SELECT id FROM dict WHERE TRIM(COALESCE(definition_es,''))<>'' "
            "AND TRIM(COALESCE(translation,''))=''")}
        _c.close()
        items = llm_items(ids=ids)
        print("■ 交叉引用型缺陷行 {:,}，取到待重翻 {:,}".format(len(ids), len(items)))
        if not a.apply:
            asyncio.run(run_llm(items, load_done()))
        plan = apply_llm(pending_only=False)
        if a.apply and plan:
            # 大多数行**本来就有译文**（只是内容不合格）→ 非空计数不变；
            # 但捡回来的漏网行是空的，会让计数上涨 —— 必须**按实际数出增量**，
            # 不能想当然写 0。2026-08-03 就是写了 0，闸门当场拦下（内容是对的，
            # 但"我以为没变"这个判断错了，正是这道闸要抓的东西）。
            _c = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
            _empty = {r[0] for r in _c.execute(
                "SELECT id FROM dict WHERE TRIM(COALESCE(translation,''))=''")}
            _c.close()
            _delta = sum(1 for _, _, rid in plan if rid in _empty)
            with dbtool.session("intake-xref-retranslate",
                                expect={"translation": _delta}) as s2:
                s2.executemany(
                    "UPDATE dict SET translation=?, translation_src=? WHERE id=?", plan)
            dbtool.align_check()
        return

    if a.llm:
        items = llm_items(limit=a.pilot or None)
        if a.apply and not a.pilot:
            plan = apply_llm()
            if not plan:
                return
            with dbtool.session("intake-llm-translate",
                                expect={"translation": len(plan)}) as s:
                s.executemany(
                    "UPDATE dict SET translation=?, translation_src=? WHERE id=?", plan)
            dbtool.align_check()
            return
        asyncio.run(run_llm(items, load_done()))
        apply_llm()
        return

    if not a.tmpl:
        ap.print_help()
        return

    plan, samples, stat = build()
    print("■ 待译 lemma 的义项 {:,}，模板译出 {:,} ({:.1f}%)".format(
        stat["义项总数"], stat["模板译出"],
        stat["模板译出"] * 100 / max(stat["义项总数"], 1)))
    print("■ 整行全部译出、可落库 {:,} 行；有义项译不出、整行留给 LLM {:,} 行".format(
        stat["整行译出"], stat["整行留给LLM"]))
    dbtool.sample_check(samples, n=14, cols=("词", "西语版原文", "中文"))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库)")
        return
    with dbtool.session("intake-tmpl-translate",
                        expect={"translation": len(plan)}) as s:
        s.executemany(
            "UPDATE dict SET translation=?, translation_src=? WHERE id=?", plan)
    dbtool.align_check()


if __name__ == "__main__":
    main()
