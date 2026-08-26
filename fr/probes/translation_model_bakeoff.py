#!/usr/bin/env python3
"""豆包翻译模型（Doubao-Seed-Translation）vs DeepSeek flash：同一批真实数据。2026-08-24。

═══ 为什么做这个 ═══
用户开通了 `Doubao-Seed-Translation`（1.2 / 3.6 元每百万 token），
问「是否可以对比看一下」。剩下 297,627 条真要送模型的释义是本项目最大的一笔，
换模型的决定必须**用真数据量出来**，不能看模型卡上的宣传。

⚠️ 用户 2026-08-15 的禁令针对的是**豆包 pro/turbo 跑批贵**；这是一个**新的、更便宜的
   专用模型**，且用户明确要求评估 ⇒ 在线小样测试，不解 `ark_batch.DOUBAO_DISABLED`。

═══ 先测「能不能用」，再测「翻得好不好」 ═══
🔴 翻译模型的 API 形状和 chat 完全不同，先探到三条**硬限制**（本文件 smoke 阶段实测）：
  ① `input` 只允许**一个 item** ⇒ **没有 system 角色**，400
  ② `content` 只允许**一条** ⇒ 不能一个请求发数组
  ③ `translation_options` 只认 `source_language` / `target_language`；
     `context` / `glossary` / `style` 一律 400（unknown field）
  ④ 指令写进正文 ⇒ **被当成正文翻译了**，原样出现在译文里
  ⇒ **它没有任何提示通道。** 我们那套 prompt 规则（保留区分性信息 / 句末不加标点 /
     不确定就留空 / 领域限定）**一条都传不进去**。

⇒ 所以本测试量三件事，缺一不可：
  A. **质量**：同一批 60 条，两家并排，我逐条读
  B. **行对齐**：翻译模型只能靠"多行塞一条"来分摊成本 ——
     它会不会合并/拆分/丢行？错位就是 `[[model-answer-files-key-by-id]]` 那个坑
  C. **成本**：每条实际 token（豆包侧能直接算成元；DeepSeek 侧仓库没记过币价，只给 token）

═══ 实测结论（2026-08-24，60 条通用样本 + 两族定向样本）═══
🔴 **不换。** 省下 23–70 元，代价是至少七千条硬错 + 整套复用/续跑机制作废。

| | DeepSeek flash | 豆包翻译·逐条 | 豆包翻译·多行×40 |
|---|---|---|---|
| token/条 | 62.7 | 61.4 | **37.8** |
| 29.8 万条 | **47 元**（低谷）/ 95 元（高峰） | 35 元 | **24 元** |
| 提示通道 | 完整 | **无** | **无** |
| 批上限 | 160（缺条 0） | 1 | **40**（60 行起 HTTP 500） |
| 确定性 | temperature=0 | 🔴 **6 条问两次，3 条不一致** | 同 |
| 不确定时 | 按规则留空 | 🔴 **从不留空，一律硬编** | 同 |

**质量（我逐条读，不是让模型判）：**
· `Qui …` 族（库里 **14,526** 条，法语词典里形容词释义的标准句式）：
  抽 25 条，**12 条被译成问句** —— `Qui a peur de la nouveauté.`
  → 豆包「谁会害怕新鲜事物呢？」／flash「恐惧新事物的」。**这一族约七千条会坏。**
· `Forme pronominale de X` 族（**3,634** 条）：抽 25 条出现**五种**译法
  （代词形式／自反形式／宾格形式／动词形式／祈使形式），且 `s'enforcir`
  →「加强的**祈使**形式」、`se carnifier`→「**杀害某人**的动词形式」全错。
  🔴 更要命的是**方向错了**：这句法语本身是**指针**，flash 拿到 `word` 字段后给的是
  真实义（`se barricader`→「设防，筑街垒自守」），豆包在**翻译那个指针**。
· 60 条通用样本里 16 条硬错：`aragonite` 霰石→「方解石」／`nerprun` 鼠李→「黑加仑」／
  `apopatophobie` 恐排便症→「死亡恐惧症」／`tarière` 钻→「抽水泵」／vinalon 朝鲜→「韩国」／
  `langue papoue` **整句意思翻反**／`asperges` **凭空编造**成「龙胆属植物的变种」／
  `greigite`、`interfeuiller` **原样留法语没翻**／`azurin` 把色号 `#A9EAFE` 漏进译文。

⇒ 它是个**好翻译模型**，但我们要的不是译文是**释义**：压缩成词典体、保留区分性信息、
   不确定就留空、同一句式全库一个译法 —— 这四件**全靠提示**，而它没有提示通道。
   `[[prompt-beats-model-choice]]` 的检查在这里得到的答案是「**通道本身不存在**」。

跑：python3 -u probes/translation_model_bakeoff.py --n 60      （在 fr/ 目录下）
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probes.model_bakeoff import SYS, env, sample   # noqa: E402

ARK = "https://ark.cn-beijing.volces.com/api/v3/responses"
DS = "https://api.deepseek.com/chat/completions"

# 牌价（元/百万 token）。豆包＝用户给的；DeepSeek＝官网 USD 折算，**汇率是估的**。
PRICE_DOUBAO_IN, PRICE_DOUBAO_OUT = 1.2, 3.6
FX = 7.1
# DeepSeek flash（USD/M）：未命中入 / 命中入 / 出。低谷是高峰的一半，
# 高峰＝周一至周五 UTC 01–04 与 06–10 时。
DS_PEAK = (0.44, 0.014, 1.32)
DS_OFF = (0.22, 0.007, 0.66)


async def ds_call(cl, key, items):
    """DeepSeek flash：完整 prompt，一次请求整批，关思考（跑批口径）。"""
    body = {"model": "deepseek-v4-flash", "temperature": 0, "stream": False,
            "thinking": {"type": "disabled"}, "reasoning_effort": "none",
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": json.dumps(items, ensure_ascii=False)}]}
    t0 = time.time()
    r = await cl.post(DS, headers={"Authorization": "Bearer " + key}, json=body, timeout=600)
    dt = time.time() - t0
    if r.status_code != 200:
        return {}, {}, dt, "HTTP %s %s" % (r.status_code, r.text[:160])
    d = r.json()
    txt = re.sub(r"^```(?:json)?|```$", "", d["choices"][0]["message"]["content"].strip(),
                 flags=re.M).strip()
    try:
        got = {str(o["id"]): o.get("zh", "") for o in json.loads(txt)}
    except Exception as ex:
        return {}, d.get("usage") or {}, dt, "解析失败 %s" % ex
    return got, d.get("usage") or {}, dt, None


def _body(text):
    return {"model": EP, "input": [{"role": "user", "content": [
        {"type": "input_text", "text": text,
         "translation_options": {"source_language": "fr", "target_language": "zh"}}]}]}


async def ark_one(cl, key, text):
    r = await cl.post(ARK, headers={"Authorization": "Bearer " + key},
                      json=_body(text), timeout=300)
    if r.status_code != 200:
        return None, {}, "HTTP %s %s" % (r.status_code, r.text[:160])
    d = r.json()
    return d["output"][0]["content"][0]["text"], d.get("usage") or {}, None


# 🔴 实测上限：10/20/40 行都稳（行对齐 0 丢失），**60 行起 HTTP 500，三次全失败**
# —— 模型卡写的 4K 上下文 / 3K 输出在这里咬人。取 40。
ARK_LINES = 40


async def ark_batch(cl, key, items):
    """B. 多行塞一条 —— 翻译模型唯一能分摊成本的形状。行对齐必须校验。"""
    t0 = time.time()
    got, usage, diag = {}, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, \
        {"无编号行": 0, "行数": 0}
    err = None
    for k in range(0, len(items), ARK_LINES):
        ch = items[k:k + ARK_LINES]
        text = "\n".join("%d\t%s" % (i + 1, x["fr"]) for i, x in enumerate(ch))
        txt, u, e = await ark_one(cl, key, text)
        if e:
            err = e
            continue
        for f in usage:
            usage[f] += u.get(f, 0)
        for ln in txt.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            diag["行数"] += 1
            m = re.match(r"^(\d+)[\t\.、:：\s]+(.*)$", ln)
            if not m:
                diag["无编号行"] += 1
                continue
            n = int(m.group(1))
            if 1 <= n <= len(ch):
                got[str(ch[n - 1]["id"])] = m.group(2).strip()
    return got, usage, time.time() - t0, err, diag


async def main():
    global EP
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    a = ap.parse_args()
    import httpx

    e = env()
    EP = e["DOUBAO_SEED_TRANSLATION"].strip()
    ark_key, ds_key = e["ARK_API_KEY"].strip(), e["DEEPSEEK_API_KEY"].strip()
    items = sample(a.n)
    print("■ 样本 %d 条（真实剩余数据，已排除可模板化的族）\n" % len(items))

    async with httpx.AsyncClient() as cl:
        ds, ds_u, ds_dt, ds_err = await ds_call(cl, ds_key, items)
        print("── DeepSeek flash（完整 prompt，1 请求）  %5.1fs  入 %s 出 %s 合计 %s %s"
              % (ds_dt, ds_u.get("prompt_tokens"), ds_u.get("completion_tokens"),
                 ds_u.get("total_tokens"), "🔴 " + ds_err if ds_err else ""))

        bt, bt_u, bt_dt, bt_err, diag = await ark_batch(cl, ark_key, items)
        print("── 豆包翻译·多行塞一条（1 请求）        %5.1fs  入 %s 出 %s 合计 %s %s"
              % (bt_dt, bt_u.get("input_tokens"), bt_u.get("output_tokens"),
                 bt_u.get("total_tokens"), "🔴 " + bt_err if bt_err else ""))
        print("     行对齐：应答 %d 行 / 认出编号 %d 条 / 无编号行 %d / **丢 %d 条**"
              % (diag.get("行数", 0), len(bt), diag.get("无编号行", 0), len(items) - len(bt)))

        sem = asyncio.Semaphore(8)

        async def one(x):
            async with sem:
                return await ark_one(cl, ark_key, x["fr"])
        t0 = time.time()
        res = await asyncio.gather(*[one(x) for x in items])
        so_dt = time.time() - t0
        so = {str(x["id"]): (t or "").strip() for x, (t, _u, _e) in zip(items, res)}
        so_in = sum((u or {}).get("input_tokens", 0) for _t, u, _e in res)
        so_out = sum((u or {}).get("output_tokens", 0) for _t, u, _e in res)
        print("── 豆包翻译·逐条（%d 请求，并发 8）      %5.1fs  入 %s 出 %s 合计 %s"
              % (len(items), so_dt, format(so_in, ","), format(so_out, ","),
                 format(so_in + so_out, ",")))

    n = len(items)
    print("\n══ 每条成本 ══")
    if ds_u:
        hit = ds_u.get("prompt_cache_hit_tokens", 0)
        miss = ds_u.get("prompt_cache_miss_tokens", ds_u.get("prompt_tokens", 0) - hit)
        out_t = ds_u.get("completion_tokens", 0)
        for tag, (pm, ph, po) in (("低谷", DS_OFF), ("高峰", DS_PEAK)):
            usd = (miss * pm + hit * ph + out_t * po) / 1e6 / n * 297627
            print("DeepSeek flash·%s   %6.1f token/条 ⇒ 29.8 万条 $%.2f ≈ %.0f 元"
                  % (tag, ds_u.get("total_tokens", 0) / n, usd, usd * FX))
    if bt_u:
        y = (bt_u.get("input_tokens", 0) * PRICE_DOUBAO_IN
             + bt_u.get("output_tokens", 0) * PRICE_DOUBAO_OUT) / 1e6
        print("豆包翻译·多行         %6.1f token/条 = %.6f 元/条 ⇒ 29.8 万条约 %.1f 元"
              % (bt_u.get("total_tokens", 0) / n, y / n, y / n * 297627))
    y2 = (so_in * PRICE_DOUBAO_IN + so_out * PRICE_DOUBAO_OUT) / 1e6
    print("豆包翻译·逐条         %6.1f token/条 = %.6f 元/条 ⇒ 29.8 万条约 %.1f 元"
          % ((so_in + so_out) / n, y2 / n, y2 / n * 297627))

    print("\n%-16s %-46s %-26s %-26s %s"
          % ("词形", "法语释义", "DeepSeek flash", "豆包翻译·多行", "豆包翻译·逐条"))
    print("-" * 150)
    for x in items:
        k = str(x["id"])
        print("%-16s %-46s %-26s %-26s %s"
              % (x["word"][:16], x["fr"][:46], (ds.get(k) or "—")[:26],
                 (bt.get(k) or "—")[:26], (so.get(k) or "—")[:34]))

    # C. 稳定性：同一条问两次，答案一样吗？（我们的复用策略依赖确定性）
    print("\n══ 确定性抽查（同一条问两次）══")
    async with httpx.AsyncClient() as cl:
        for x in items[:6]:
            t1, _u, _e = await ark_one(cl, ark_key, x["fr"])
            t2, _u, _e = await ark_one(cl, ark_key, x["fr"])
            same = "一致" if (t1 or "").strip() == (t2 or "").strip() else "🔴 不一致"
            print("  %-6s %-30s | %s | %s" % (same, x["fr"][:30],
                                              (t1 or "").strip()[:22], (t2 or "").strip()[:22]))


if __name__ == "__main__":
    asyncio.run(main())
