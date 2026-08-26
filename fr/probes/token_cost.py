#!/usr/bin/env python3
"""阶段 1.5(b) 的 **token 成本实测**。2026-08-23。

🔴 `FR_PLAN` 写死过一条：「**先做切片实测，在那个数出来前不许写工期**」。
   这里量的就是那个数 —— 不从已跑过的批次外推，因为那些批带 `ctx` 上下文、
   分批大小也不同，**外推会把两个变量混在一起**。

量两条路线，各跑真数据：
  A **短槽值**：市镇名（居民族要翻 25,682 个）—— 不带 ctx，最省的形态
  B **整句翻译**：真正没法模板化的那批法语释义

每条路线跑三种批大小，因为 **system prompt 是按批摊的**：
批越大越省，但太大模型会丢条（it 阶段 5 实测静默丢 2,069 条）。

跑：python3 probes/token_cost.py            （在 fr/ 目录下）
"""
import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                              # noqa: E402
from pipeline import slot_translate       # noqa: E402

DEMO = re.compile(
    r"^(Habitante?|Relatif|Relative) (?:de|d’|d'|à|au|aux|en) (.+?), (?:une |la |le )?"
    r"(commune|ville|village|municipalit[ée]) française,? situ[ée]e? dans le d[ée]partement "
    r"(?:de la|de l’|de l'|des|du|de|d’|d')\s*(.+?)\.?$")
SKIP = re.compile(
    r"^(Commune|Ville|Village|Municipalité|Hameau|Localité|Bourg|Quartier|Paroisse)\b"
    r"|^Nom de famille\b|^Pr[ée]nom\b|^Habitante?\b|^Relatif|^Relative"
    r"|^D[ée]finition manquante", re.I)

SYS_A = """你在给一部法汉词典做**法国市镇名**的中文译名。输入是 JSON 数组，每项有 `fr`。
规则：
1. 输出该市镇名的中文音译，按法语读音，用《世界地名翻译大辞典》常规用字。
2. 有约定俗成译名的用约定译名（`Saint-Cloud`→`圣克卢`、`Versailles`→`凡尔赛`）。
3. 复合名保留连字符。只输出译名本身，不要「市镇」「法国」这类词。
4. 拿不准输出空字符串 ""，不要猜。
输出**只有** JSON 数组，每项 {"fr": 原样, "zh": "译名"}，不要围栏、不要解释。"""

SYS_B = """你是法语—中文词典助手。输入是**法语词条在法语维基词典里的释义**，
把它转成**中文释义**，供中文用户查词用。输入 JSON 数组，每项有 `id`、`word`、`fr`。
规则：
1. 输出中文释义本身，不是逐字翻译。`Oiseau de proie diurne.` → `昼行性猛禽`
2. 🔴 **保留区分性信息**，同名的不同事物必须能区分开。
3. 领域词保留领域限定：`(Botanique) Plante de la famille des rosacées.` → `（植物学）蔷薇科植物`
4. 句末不加标点；多个对应词用顿号分隔，最多 3 个。
5. 不要出现「意为」「指」「该词」这类元话语。
6. 🔴 法语释义本身没有信息量、或你无法确定时，`zh` 输出 ""，不要猜。
输出**只有** JSON 数组，每项 {"id": 原样, "zh": "中文"}，不要围栏、不要解释。"""


def samples():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("""
        SELECT s.id, d.word, g.text FROM sense s
        JOIN dict d ON d.id = s.word_id
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL""").fetchall()
    names, plain = [], []
    seen = set()
    for sid, w, raw in rows:
        t = " ".join(raw.split())
        m = DEMO.match(t)
        if m:
            x = m.group(2).strip()
            if x not in seen:
                seen.add(x)
                names.append({"fr": x})
        elif not SKIP.match(t):
            plain.append({"id": sid, "word": w, "fr": t})
    return names, plain


async def one(cl, key, sys_prompt, items):
    body = {"model": slot_translate.MODEL, "temperature": 0, "stream": False,
            "messages": [{"role": "system", "content": sys_prompt},
                         {"role": "user", "content": json.dumps(items, ensure_ascii=False)}]}
    r = await cl.post(slot_translate.URL, headers={"Authorization": "Bearer " + key},
                      json=body, timeout=600)
    if r.status_code != 200:
        return None
    d = r.json()
    u = d.get("usage") or {}
    txt = d["choices"][0]["message"]["content"]
    try:
        got = len(json.loads(re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()))
    except Exception:
        got = -1
    return {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0),
            "tot": u.get("total_tokens", 0), "n": len(items), "got": got}


async def main():
    import httpx
    key = slot_translate.env()["DEEPSEEK_API_KEY"].strip()
    names, plain = samples()
    print("■ 可测样本：市镇名 %s 个（去重后）；整句 %s 条\n"
          % (format(len(names), ","), format(len(plain), ",")))

    async with httpx.AsyncClient() as cl:
        for label, sys_p, pool in (("A 短槽值（市镇名）", SYS_A, names),
                                   ("B 整句翻译", SYS_B, plain)):
            print("── %s ──" % label)
            print("   批大小   条数  入token  出token  合计   **每条**  回条数")
            for size in (20, 40, 80):
                r = await one(cl, key, sys_p, pool[:size])
                if not r:
                    print("   %4d     — HTTP 失败" % size)
                    continue
                print("   %4d   %5d %8s %8s %8s   %6.1f    %d%s"
                      % (size, r["n"], format(r["in"], ","), format(r["out"], ","),
                         format(r["tot"], ","), r["tot"] / r["n"], r["got"],
                         "  🔴丢条" if r["got"] not in (r["n"], -1) else ""))
            print()


if __name__ == "__main__":
    asyncio.run(main())
