"""
根据 exchange 字段为词形变化词追加变形说明

原理：
  exchange 字段编码了单词的词形关系，例如：
    destroyed: 0:destroy/1:dp  → 表示原形是 destroy，dp 表示过去式+过去分词

  本脚本根据这些编码规则，在 translation 前追加一行变形说明，如：
    "v. destroy的过去式和过去分词"
  原有释义完全不动。

编码对照表：
  0:xxx  → 原形是 xxx
  1:s    → 复数
  1:p    → 过去式
  1:d    → 过去分词
  1:i    → 现在分词
  1:3    → 第三人称单数
  1:r    → 比较级
  1:t    → 最高级
  1:dp   → 过去式和过去分词（同形）

用法：python scripts/patch-exchange-translation.py
"""

import sqlite3

from paths import DB_PATH

# exchange 编码 → 中文描述
FORM_MAP = {
    "s": "复数",
    "p": "过去式",
    "d": "过去分词",
    "dp": "过去式和过去分词",
    "pd": "过去式和过去分词",
    "i": "现在分词",
    "3": "第三人称单数",
    "r": "比较级",
    "t": "最高级",
}

# 已有翻译中包含这些关键词的，视为已有变形说明，跳过
SKIP_KEYWORDS = [
    "过去式", "过去分词", "现在分词", "复数", "比较级", "最高级",
    "第三人称", "的一种形式", "的变形",
]


def parse_exchange(exchange: str) -> tuple[str | None, list[str]]:
    """解析 exchange 字段，返回 (原形, 变形类型列表)"""
    if not exchange:
        return None, []

    base = None
    forms = []

    for part in exchange.split("/"):
        if part.startswith("0:"):
            base = part[2:]
        elif part.startswith("1:"):
            code = part[2:]
            forms.append(code)

    return base, forms


def build_prefix(base: str, forms: list[str]) -> str | None:
    """根据原形和变形类型构建前缀说明"""
    descriptions = []
    for code in forms:
        desc = FORM_MAP.get(code)
        if desc:
            descriptions.append(desc)

    if not descriptions:
        return None

    return f"{base}的{'、'.join(descriptions)}"


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 查询有 exchange 且有原形标记的词
    rows = conn.execute("""
        SELECT id, word, exchange, translation FROM stardict
        WHERE exchange LIKE '%0:%'
        AND translation IS NOT NULL AND translation != ''
    """).fetchall()

    print(f"共 {len(rows)} 条有 exchange 原形标记且有翻译的记录")

    updates = []
    for row in rows:
        translation = row["translation"]

        # 已有变形说明的跳过
        if any(kw in translation for kw in SKIP_KEYWORDS):
            continue

        base, forms = parse_exchange(row["exchange"])
        if not base or not forms:
            continue

        prefix = build_prefix(base, forms)
        if not prefix:
            continue

        new_translation = f"{prefix}\n{translation}"
        updates.append((new_translation, row["id"]))

    print(f"需要追加变形说明的: {len(updates)} 条")

    if not updates:
        print("无需更新")
        conn.close()
        return

    # 批量更新
    conn.executemany("UPDATE stardict SET translation = ? WHERE id = ?", updates)
    conn.commit()
    conn.close()

    print(f"更新完成: {len(updates)} 条")

    # 抽样展示
    import random
    samples = random.sample(updates, min(10, len(updates)))
    print(f"\n{'='*60}")
    print(f"抽样检查（{len(samples)} 条）：")
    print(f"{'='*60}")
    for new_trans, _id in samples:
        lines = new_trans.split("\n")
        print(f"  [{lines[0]}]")
        print(f"    原译: {lines[1][:60]}...")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
