#!/usr/bin/env python3
"""豆包 lite vs DeepSeek flash：同一批、同一 prompt，跑法语释义→中文。2026-08-22。

═══ 为什么做这个 ═══
用户 2026-08-15 明令**跑批不用豆包**，理由是 pro/turbo「贵的离谱」。
2026-08-22 用户提出：**那条禁令针对的是 pro/turbo，lite 从没单独评估过。**
（`.env` 里确实有 `DOUBAO_MODEL_BATCH_LITE` / `DOUBAO_MODEL_ONLINE_LITE`，
 而 `quality_pass.model_comps` 引用的 pro/turbo 端点在 .env 里**已经没有了**。）

⚠️ `ark_batch.DOUBAO_DISABLED` 是硬拦截，留的口子是
「显式传 `allow_doubao=True`，并**先跟用户确认花费**」。本脚本是**在线小样测试**，
不走 batch、不解除拦截，量的是 **40 条**。

═══ 这个测试量什么、不量什么 ═══
量：**质量**（我逐条读）、**token 用量**、**耗时**。
不量：**钱** —— 仓库里没有记过币价，单价由用户判断。
    我能给的是"每条多少 token"，乘价格是用户那边的事。

🔴 `[[prompt-beats-model-choice]]`：选模型前先问「这个差距是不是提示能补的」。
   所以两家**用完全相同的 prompt**，差别只在模型。

🔴 样本**故意取"其余"那一族**（真需要模型的那 39.9 万条），
   不取姓氏/地名那些能模板化的 —— 拿简单样本比模型是自欺。

跑：python3 probes/model_bakeoff.py            （在 fr/ 目录下）
    python3 probes/model_bakeoff.py --n 40
"""
import argparse
import asyncio
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

SYS = """你是法语—中文词典助手。输入是**法语词条在法语维基词典里的释义**（法语原文），
把它转成**中文释义**，供中文用户查词用。

规则：
1. 输出中文释义本身，不是逐字翻译法语句子。`Oiseau de proie diurne.` → `昼行性猛禽`
2. 🔴 **保留区分性信息**。同名的不同事物必须能区分开：
   `Commune française du département de la Charente.` → `法国夏朗德省市镇`
   **不要**压成`法国市镇` —— 那会让十个同名市镇的中文一模一样
3. 专业领域词保留领域限定：`(Botanique) Plante de la famille des rosacées.` → `（植物学）蔷薇科植物`
4. **句末不加标点**；多个对应词用中文顿号分隔，最多 3 个
5. 不要出现"意为""指""该词"这类元话语
6. 🔴 法语释义本身没有信息量、或你无法确定时，`zh` 输出空字符串 ""，**不要猜**

输入是 JSON 数组，每项有 `id`、`word`（法语词形）、`fr`（法语释义）。
输出**只有** JSON 数组，每项 {"id": 原样, "zh": "中文"}，不要围栏、不要解释。"""

# 已能模板化的几族排除在外 —— 拿简单样本比模型是自欺
SKIP = re.compile(r"^(Commune|Ville|Village|Municipalité|Hameau|Localité|Bourg|Rivière|"
                  r"Fleuve|Montagne|Île|Lac)\b|^Nom de famille\b|^Pr[ée]nom\b", re.I)


def env():
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines()
                if "=" in l and not l.startswith("#"))


def sample(n, seed=20260822):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = [(sid, w, t) for sid, w, t in con.execute("""
        SELECT s.id, d.word, g.text FROM sense s
        JOIN dict d ON d.id = s.word_id
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL""") if not SKIP.match(t)]
    random.Random(seed).shuffle(rows)
    return [{"id": r[0], "word": r[1], "fr": r[2]} for r in rows[:n]]


async def call(cl, url, key, model, items, think=False):
    body = {"model": model, "temperature": 0, "stream": False,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
            "thinking": {"type": "enabled" if think else "disabled"}}
    t0 = time.time()
    r = await cl.post(url, headers={"Authorization": "Bearer " + key}, json=body, timeout=300)
    dt = time.time() - t0
    if r.status_code != 200:
        return None, {}, dt, "HTTP %s: %s" % (r.status_code, r.text[:160])
    d = r.json()
    return d["choices"][0]["message"]["content"], d.get("usage") or {}, dt, None


def parse(txt):
    """🔴 带容错。豆包**偶发**吐坏 JSON（`loads_lenient` 本来就是为它写的）——
    第一次跑 40 条时解析失败，**重跑三次 40/20/10 全部成功** ⇒ 是偶发不是能力问题。
    `[[prompt-beats-model-choice]]`：两次差点因「模型能力」买贵的、两次都是我的解析器问题。
    """
    if txt is None:
        return {}
    t = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    for fix in (lambda x: x,
                lambda x: re.sub(r"}\s*\n\s*(\{)", r"},\n\1", x),   # 条目间缺逗号
                lambda x: re.sub(r",\s*([}\]])", r"\1", x),           # 尾逗号
                lambda x: x[:x.rfind("}") + 1] + "]"):                # 截断收尾
        try:
            return {str(o["id"]): o.get("zh", "") for o in json.loads(fix(t))}
        except Exception:
            continue
    return {"__err__": t[:140]}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    import httpx

    e = env()
    items = sample(a.n)
    print("■ 样本 %d 条（已排除姓氏/地名等可模板化的族）\n" % len(items))

    runs = [
        ("豆包 lite", "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
         e["ARK_API_KEY"].strip(), e["DOUBAO_MODEL_ONLINE_LITE"].strip()),
        ("DeepSeek flash", "https://api.deepseek.com/chat/completions",
         e["DEEPSEEK_API_KEY"].strip(), "deepseek-v4-flash"),
    ]
    out = {}
    async with httpx.AsyncClient() as cl:
        for name, url, key, model in runs:
            txt, usage, dt, err = await call(cl, url, key, model, items)
            got = parse(txt)
            out[name] = got
            print("── %-16s 耗时 %5.1fs  token 入 %s 出 %s  合计 %s%s"
                  % (name, dt, usage.get("prompt_tokens", "?"),
                     usage.get("completion_tokens", "?"), usage.get("total_tokens", "?"),
                     "  🔴 " + err if err else ""))
            if "__err__" in got:
                print("   🔴 解析失败：%s" % got["__err__"])
            else:
                miss = [x["id"] for x in items if str(x["id"]) not in got]
                blank = [k for k, v in got.items() if not v]
                print("   返回 %d 条 / 缺 %d 条 / 主动留空 %d 条"
                      % (len(got), len(miss), len(blank)))
    print()
    print("%-22s %-40s %-24s %-24s" % ("词形", "法语释义", "豆包 lite", "DeepSeek flash"))
    print("-" * 116)
    for x in items:
        k = str(x["id"])
        print("%-22s %-40s %-24s %-24s"
              % (x["word"][:22], x["fr"][:40],
                 (out["豆包 lite"].get(k) or "—")[:24],
                 (out["DeepSeek flash"].get(k) or "—")[:24]))


if __name__ == "__main__":
    asyncio.run(main())
