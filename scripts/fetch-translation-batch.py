"""
使用火山引擎 Ark SDK（豆包大模型）批量生成缺失的中文释义

功能：
  对 SQLite 词典中 translation 为空的单词，调用豆包大模型生成中文释义。
  支持断点续传——已翻译的结果保存在 JSONL 文件中，重启后自动跳过。

流程：
  1. 从 data/intermediate/doubao-translation.jsonl 加载已完成的单词
  2. 从 data/final/synapse-dict.sqlite 查询 translation 为空且未处理的单词
  3. 每批 BATCH_SIZE(40) 个词，最多 MAX_CONCURRENT(100) 个并发请求
  4. 结果追加写入 JSONL 文件（每批写一次，支持中断恢复）
  5. 翻译完成后，需手动运行 merge-translation.ts 合并到 SQLite

环境变量（.env）：
  ARK_API_KEY          - 火山引擎 API 密钥
  DOUBAO_MODEL_BATCH_LITE - 豆包模型 ID

前置安装：pip install --upgrade "volcengine-python-sdk[ark]" python-dotenv
用法：python scripts/fetch-translation-batch.py
"""

import os
import sys
import json
import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from volcenginesdkarkruntime import AsyncArk
from paths import DB_PATH, DOUBAO_TRANSLATION_PATH

# 加载 .env
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

ARK_API_KEY = os.environ.get("ARK_API_KEY", "").strip()
BATCH_MODEL = os.environ.get("DOUBAO_MODEL_BATCH_LITE", "").strip()
if not ARK_API_KEY or not BATCH_MODEL:
    print("Missing ARK_API_KEY or DOUBAO_MODEL_BATCH_LITE in .env", file=sys.stderr)
    sys.exit(1)

OUTPUT_PATH = DOUBAO_TRANSLATION_PATH
BATCH_SIZE = 40
MAX_CONCURRENT = 100
RETRY_MAX = 3


def load_done_words() -> set[str]:
    done = set()
    if not OUTPUT_PATH.exists():
        return done
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("word"):
                    done.add(obj["word"].lower())
            except json.JSONDecodeError:
                pass
    return done


def load_missing_words(done: set[str]) -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT word, definition FROM stardict
        WHERE (translation IS NULL OR translation = '')
        AND LENGTH(word) BETWEEN 1 AND 80
        ORDER BY word
        """
    ).fetchall()
    conn.close()
    return [
        {"word": r["word"], "definition": r["definition"]}
        for r in rows
        if r["word"].lower() not in done
    ]


def build_prompt(batch: list[dict]) -> str:
    items = []
    for w in batch:
        defn = (w["definition"] or "")[:200]
        items.append(f"{w['word']}: {defn}" if defn else w["word"])

    return f"""你是一个专业词典编辑。请为以下英文单词提供简洁的中文释义。

要求：
- 每个词的释义控制在 50 字以内
- 格式为"词性. 释义"，多个词性用换行分隔，如 "n. 苹果\\nv. 适用"
- 如果有英文释义参考，请据此翻译
- 如果是俚语/网络用语，标注"[俚]"或"[网络]"
- 返回严格的 JSON 对象，key 为单词（保持原始大小写），value 为中文释义字符串
- 不要返回任何其他内容，只返回 JSON

单词列表：
{chr(10).join(items)}"""


def parse_response(content: str) -> dict:
    text = content.strip()
    text = text.removeprefix("```json").removeprefix("```")
    text = text.removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


# 统计
stats = {"done": 0, "failed": 0}
lock = asyncio.Lock()


async def worker(
    worker_id: int,
    client: AsyncArk,
    queue: asyncio.Queue,
    output_file,
):
    while True:
        batch = await queue.get()
        try:
            result = await call_with_retry(client, batch)
            async with lock:
                count = 0
                for w in batch:
                    translation = result.get(w["word"]) or result.get(w["word"].lower())
                    if translation:
                        line = json.dumps(
                            {"word": w["word"], "translation": translation},
                            ensure_ascii=False,
                        )
                        output_file.write(line + "\n")
                        output_file.flush()
                        count += 1
                stats["done"] += count
        except Exception as e:
            stats["failed"] += len(batch)
            print(f"Worker {worker_id} error: {e}", file=sys.stderr)
        finally:
            queue.task_done()


async def call_with_retry(client: AsyncArk, batch: list[dict], attempt: int = 1) -> dict:
    try:
        completion = await client.batch.chat.completions.create(
            model=BATCH_MODEL,
            messages=[{"role": "user", "content": build_prompt(batch)}],
            temperature=0.1,
            max_tokens=4096,
        )
        content = completion.choices[0].message.content or ""
        return parse_response(content)
    except Exception as e:
        if attempt < RETRY_MAX:
            await asyncio.sleep(1 * attempt)
            return await call_with_retry(client, batch, attempt + 1)
        raise


async def main():
    start = datetime.now()

    print("Loading done words from JSONL...")
    done = load_done_words()
    print(f"Already done: {len(done)}")

    print("Loading missing words from SQLite...")
    words = load_missing_words(done)
    print(f"Words to process: {len(words)}")

    if not words:
        print("Nothing to do!")
        return

    # 分批
    batches = [words[i : i + BATCH_SIZE] for i in range(0, len(words), BATCH_SIZE)]
    print(f"Total batches: {len(batches)}, max concurrency: {MAX_CONCURRENT}")

    queue: asyncio.Queue = asyncio.Queue()
    for batch in batches:
        await queue.put(batch)

    client = AsyncArk(api_key=ARK_API_KEY, timeout=300)

    output_file = open(OUTPUT_PATH, "a", encoding="utf-8")

    # 启动 worker
    num_workers = min(MAX_CONCURRENT, len(batches))
    tasks = [
        asyncio.create_task(worker(i, client, queue, output_file))
        for i in range(num_workers)
    ]

    # 进度打印
    total = len(words)

    async def progress_printer():
        while True:
            await asyncio.sleep(5)
            pct = ((len(done) + stats["done"]) / (total + len(done))) * 100
            print(
                f"  Progress: +{stats['done']} done, {stats['failed']} failed, "
                f"{queue.qsize()} batches remaining ({pct:.1f}%)"
            )

    progress_task = asyncio.create_task(progress_printer())

    await queue.join()

    # 清理
    progress_task.cancel()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, progress_task, return_exceptions=True)
    await client.close()
    output_file.close()

    elapsed = datetime.now() - start
    print(f"\nDone! +{stats['done']} words, {stats['failed']} failed. Time: {elapsed}")
    print(f"Results in: {OUTPUT_PATH}")

    # 抽样展示，供人工检查
    import random
    all_entries = []
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                all_entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    sample_size = min(20, len(all_entries))
    samples = random.sample(all_entries, sample_size)
    print(f"\n{'='*60}")
    print(f"抽样检查（随机 {sample_size} 条）：")
    print(f"{'='*60}")
    for s in samples:
        print(f"  [{s['word']}] → {s['translation']}")
    print(f"{'='*60}")
    print("请检查以上翻译质量，确认无误后运行：")
    print("  npx tsx scripts/merge-translation.ts")


if __name__ == "__main__":
    asyncio.run(main())
