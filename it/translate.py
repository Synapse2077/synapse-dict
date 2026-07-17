"""
意大利语 lemma 中文释义：豆包批量补 translation 为空的词条。

变位形式在 build.py 已生成中文（translation 非空），不会被选中——
所以这里只翻真正的 lemma，量按 lemma 算（约 54 万）。

流程：读 synapse-dict-it.sqlite 里 translation 为空的词 → 豆包批翻
     → 结果追加写 doubao-it.jsonl（断点续传）→ 跑完 merge 回库。

环境变量（synapse-dict/.env）：ARK_API_KEY, DOUBAO_MODEL_BATCH_LITE
用法：python3 translate.py         # 翻译并自动 merge
      python3 translate.py --merge # 只把已有 JSONL 结果 merge 回库
"""

import os
import sys
import json
import asyncio
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from volcenginesdkarkruntime import AsyncArk

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = HERE / "synapse-dict-it.sqlite"
OUT_PATH = HERE / "doubao-it.jsonl"

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

ARK_API_KEY = os.environ.get("ARK_API_KEY", "").strip()
BATCH_MODEL = os.environ.get("DOUBAO_MODEL_BATCH_LITE", "").strip()
ONLINE_MODEL = os.environ.get("DOUBAO_MODEL_ONLINE_LITE", "").strip()
if not ARK_API_KEY:
    sys.exit("Missing ARK_API_KEY in .env")

BATCH_SIZE = 40
RETRY_MAX = 3

# 运行时按 --batch / 默认(online) 决定：
#   online 实时、快，适合中小语言(西语 10.5 万 lemma)；batch 异步便宜，适合以后大库。
USE_BATCH = False
MODEL = ""
MAX_CONCURRENT = 32


def load_done() -> set:
    done = set()
    if not OUT_PATH.exists():
        return done
    with open(OUT_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
                if o.get("word"):
                    done.add(o["word"])
            except json.JSONDecodeError:
                pass
    return done


def load_todo(done: set) -> list:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT word, definition FROM stardict
           WHERE (translation IS NULL OR translation = '')
           AND LENGTH(word) BETWEEN 1 AND 80"""
    ).fetchall()
    conn.close()
    return [{"word": r["word"], "definition": r["definition"]}
            for r in rows if r["word"] not in done]


def build_prompt(batch: list) -> str:
    items = []
    for w in batch:
        d = (w["definition"] or "")[:200]
        items.append(f'{w["word"]}: {d}' if d else w["word"])
    return f"""你是专业的意大利语-中文词典编辑。请为以下意大利语单词提供简洁准确的中文释义。

要求：
- 每个词释义控制在 50 字以内
- 格式为"词性. 释义"，多个词性用换行分隔，如 "n. 房子\\nv. 居住"
- 附有英文释义参考时，请据此翻译
- 返回严格的 JSON 对象，key 为意大利语单词（保持原始大小写），value 为中文释义字符串
- 只返回 JSON，不要任何其他内容

单词列表：
{chr(10).join(items)}"""


def parse_response(content: str) -> dict:
    t = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return {}


stats = {"done": 0, "failed": 0}
lock = asyncio.Lock()


async def call_with_retry(client, batch, attempt=1):
    try:
        api = client.batch.chat.completions if USE_BATCH else client.chat.completions
        r = await api.create(
            model=MODEL,
            messages=[{"role": "user", "content": build_prompt(batch)}],
            temperature=0.1, max_tokens=4096,
        )
        return parse_response(r.choices[0].message.content or "")
    except Exception:
        if attempt < RETRY_MAX:
            await asyncio.sleep(attempt)
            return await call_with_retry(client, batch, attempt + 1)
        raise


async def worker(client, queue, out):
    while True:
        batch = await queue.get()
        try:
            res = await call_with_retry(client, batch)
            async with lock:
                for w in batch:
                    tr = res.get(w["word"]) or res.get(w["word"].lower())
                    if tr:
                        out.write(json.dumps({"word": w["word"], "translation": tr}, ensure_ascii=False) + "\n")
                        out.flush()
                        stats["done"] += 1
        except Exception as e:
            stats["failed"] += len(batch)
            print("worker error:", e, file=sys.stderr)
        finally:
            queue.task_done()


def merge():
    if not OUT_PATH.exists():
        print("无 JSONL 可 merge")
        return
    conn = sqlite3.connect(str(DB_PATH))
    n = 0
    with open(OUT_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("word") and o.get("translation"):
                conn.execute(
                    "UPDATE stardict SET translation=? WHERE word=? AND (translation IS NULL OR translation='')",
                    (o["translation"], o["word"]),
                )
                n += 1
    conn.commit()
    conn.close()
    print(f"merge 回库 {n} 条")


async def main():
    global USE_BATCH, MODEL, MAX_CONCURRENT
    USE_BATCH = "--batch" in sys.argv
    MODEL = BATCH_MODEL if USE_BATCH else ONLINE_MODEL
    MAX_CONCURRENT = 100 if USE_BATCH else 32
    if not MODEL:
        sys.exit("对应 model 未在 .env 配置")
    print(f"接口: {'batch(异步省钱)' if USE_BATCH else 'online(实时)'}, model={MODEL}, 并发={MAX_CONCURRENT}")
    limit = None
    if "--limit" in sys.argv:
        i = sys.argv.index("--limit")
        if i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
    done = load_done()
    print("已完成", len(done))
    todo = load_todo(done)
    if limit:
        todo = todo[:limit]
        print(f"[小样模式] 只翻前 {limit} 个")
    print("待翻译 lemma", len(todo))
    if not todo:
        merge()
        return
    batches = [todo[i:i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
    print(f"批次 {len(batches)}, 并发 {MAX_CONCURRENT}")
    queue = asyncio.Queue()
    for b in batches:
        await queue.put(b)
    client = AsyncArk(api_key=ARK_API_KEY, timeout=300)
    out = open(OUT_PATH, "a", encoding="utf-8")
    tasks = [asyncio.create_task(worker(client, queue, out))
             for _ in range(min(MAX_CONCURRENT, len(batches)))]

    async def prog():
        while True:
            await asyncio.sleep(5)
            print(f"  +{stats['done']} done, {stats['failed']} failed, {queue.qsize()} batches left")

    pt = asyncio.create_task(prog())
    await queue.join()
    pt.cancel()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, pt, return_exceptions=True)
    await client.close()
    out.close()
    print(f"翻译完成 +{stats['done']}, failed {stats['failed']}")
    merge()


if __name__ == "__main__":
    if "--merge" in sys.argv:
        merge()
    else:
        asyncio.run(main())
