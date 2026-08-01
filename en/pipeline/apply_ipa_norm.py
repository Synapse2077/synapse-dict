#!/usr/bin/env python3
"""en 音标记法归一 —— 落库。2026-08-01。

把 `ipa_norm.normalize()` 的结果写回 `phonetic_uk` / `phonetic_us`，
源值留档到 `phonetic_uk_raw` / `phonetic_us_raw`。

═══ 只动记法噪声 ═══
判据：**归一之后源头原本的陈述能否复原？**能才动。详见 `en/ipa_norm.py` 文件头。
    动：音节点 · 连结弧 · 非成音节符 ̯ · 送气 ʰ · 连接符 ‿ · 暗 l → l · ASCII g → ɡ · **r → ɹ**
    不动：`(…)` 可选音段 · `̩` 成音节辅音 · `ɾ` 闪音 · `ʔ` 喉塞 —— 交展示层
    只标记不改：非英语音位（印度英语转写混入，uk 315 / us 350 行）

⚠️ `phonetic` 列（ECDICT 遗留 370,203 行）**不碰**：90 年代教材式记法，
   用户 2026-08-01 定为「已无参考价值，象征性保留」。

落库前验收：`tests/test_ipa_norm.py` 17 例全绿，且**基线绿的前提下**变异 7/7 被拦
（第一版变异"全过"是假的 —— 测试文件当时有语法错误，每次都失败，基线也失败）。

用法（在 en/ 目录）：
  python3 pipeline/apply_ipa_norm.py            # 预览
  python3 pipeline/apply_ipa_norm.py --apply    # 写库（dbtool 闸门）
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3
from collections import Counter

import dbtool
import ipa_norm as N

COLS = ("phonetic_uk", "phonetic_us")


def plan():
    conn = sqlite3.connect(f"file:{dbtool.DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, word, phonetic_uk, phonetic_us FROM stardict "
        "WHERE TRIM(COALESCE(phonetic_uk,''))<>'' OR TRIM(COALESCE(phonetic_us,''))<>''"
    ).fetchall()
    conn.close()
    tal = Counter()
    changes = {c: [] for c in COLS}
    flags = {c: [] for c in COLS}
    samples = []
    for rid, w, uk, us in rows:
        for col, v in zip(COLS, (uk, us)):
            if not (v or "").strip():
                continue
            tal[(col, "有值")] += 1
            n = N.normalize(v)
            if n != v:
                tal[(col, "改写")] += 1
                changes[col].append((n, rid))
                if len(samples) < 12:
                    samples.append((w, col[-2:], v, n))
            if N.non_english(n):
                tal[(col, "非英语音位")] += 1
                flags[col].append(rid)
    return tal, changes, flags, samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    tal, changes, flags, samples = plan()
    print(f"{'':16}{'uk':>12}{'us':>12}")
    for k in ("有值", "改写", "非英语音位"):
        print(f"  {k:14}{tal[('phonetic_uk', k)]:>12,}{tal[('phonetic_us', k)]:>12,}")
    for c in COLS:
        d, t = tal[(c, "改写")], tal[(c, "有值")]
        print(f"  {c} 改写率 {100*d/max(t,1):.1f}%")
    dbtool.sample_check(samples, 12, ("词", "列", "改前", "改后"))

    if not a.apply:
        print("\n(预览。确认后 --apply)")
        return

    n_uk = tal[("phonetic_uk", "有值")]
    n_us = tal[("phonetic_us", "有值")]
    with dbtool.session("ipanorm",
                        expect={"phonetic_uk": 0, "phonetic_us": 0,
                                "phonetic_uk_raw": n_uk, "phonetic_us_raw": n_us}) as s:
        # 🔴 顺序：先留档源值，再覆盖 —— 反过来源值就没了。
        for c in COLS:
            s.execute(f"UPDATE stardict SET {c}_raw={c} WHERE TRIM(COALESCE({c},''))<>''")
        for c in COLS:
            s.executemany(f"UPDATE stardict SET {c}=? WHERE id=?", changes[c])
        # 非英语音位只标记，不改值
        for c in COLS:
            s.executemany(f"UPDATE stardict SET {c}_src='flag:non-english' WHERE id=?",
                          [(r,) for r in flags[c]])


if __name__ == "__main__":
    main()
