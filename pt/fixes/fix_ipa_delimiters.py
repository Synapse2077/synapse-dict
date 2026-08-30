#!/usr/bin/env python3
"""阶段 4a 前置清洗：`dict.ipa_br`/`ipa_pt` 里粘着两个音标的 3 条。2026-08-29。

═══ 缺陷 ═══
阶段 4a 的闸②逮到 3 个值**首尾带定界符**，违反六语种统一的「DB 存裸」约定
（`[[ipa-bare-storage-convention]]`：DB 存裸 / normalize 输出裸 / 展示层统一加 `/…/`）。

看清楚之后不是"带定界符"，是**两个音标粘在一个字段里**——
源头（英文版）在同一个 `sounds[].ipa` 里同时给了音位式和音值式：

    pintelheira      '/pĩ.tɨˈʎei̯.ɾɐ/ [pĩtˈʎeɾɐ]'
    tem avonde       '/ˈtẽj̃ ɐˈvõ.dɨ/ [ˈtẽ ɐˈvõd]'
    como o caralho   '/ˈko.mu u kɐˈɾa.ʎu/ [ko.mɔ kɐˈɾa.ʎu]'

`dict.ipa_br` 这一列的契约是「**一个**音标、存裸」，装两个是**建库时的缺陷**。

═══ 为什么在源列修，而不是在 `pronunciation` 里拆成两行 ═══
拆成两行（`phonemic` + `narrow`）看着更"正确"，但**会破坏 4a 的可逆性回核** ——
那道闸从新表重建两列、与原列逐字节比对，拆开之后就得再拼回去，
而"拼回去"要记住原来的分隔写法，等于把缺陷编码进重建逻辑。
⇒ 在源列修正成音位式，回核继续 100%。

⚠️ **音值式不会丢**：它在 dump 里，4b 跨版收割时按定界符判 `notation='narrow'` 收回来。
   这不是"删数据"，是"把它挪到该去的地方"。

⚠️ 判据**按含义写**：不是"含 `/` 或 `[`"（那是形状），是
   **「这个字段里装了不止一个音标」** —— 用 `/…/` 与 `[…]` 两个定界段来判定。

用法（在 pt/ 目录下）：
    python3 fixes/fix_ipa_delimiters.py            # 只看要改哪些
    python3 fixes/fix_ipa_delimiters.py --apply
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

PHONEMIC = re.compile(r"/([^/]+)/")
NARROW = re.compile(r"\[([^\]]+)\]")


def split_ipa(v):
    """→ (音位式, 音值式|None)，或 None 表示这个值本来就只有一个音标。"""
    if not v:
        return None
    p, n = PHONEMIC.search(v), NARROW.search(v)
    if not (p and n):
        return None                     # 只有一个（或一个都没有）⇒ 不是本缺陷
    return p.group(1).strip(), n.group(1).strip()


def find(con):
    out = []
    for col in ("ipa_br", "ipa_pt"):
        for rid, w, v in con.execute(
                "SELECT id, word, %s FROM dict WHERE %s IS NOT NULL AND %s<>''" % (col, col, col)):
            r = split_ipa(v)
            if r:
                out.append((col, rid, w, v, r[0], r[1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = find(con)
    con.close()

    print("■ 一个字段装了两个音标的：%d 条" % len(todo))
    for col, rid, w, old, ph, na in todo:
        print("   %-7s id=%-7d %-18s" % (col, rid, w))
        print("      原   %r" % old)
        print("      改为 %r   （音值式 %r 交 4b 从 dump 收回）" % (ph, na))
    if not todo or not a.apply:
        print("\n(未加 --apply，不写库)" if todo else "\n✓ 没有要改的")
        return 0

    with dbtool.session("ipa-delimiters", expect={}) as s:
        for col, rid, _, _, ph, _ in todo:
            s.execute("UPDATE dict SET %s=? WHERE id=?" % col, (ph, rid))

    dbtool.sample_check([(w, old, ph) for _, _, w, old, ph, _ in todo],
                        n=len(todo), cols=("词", "改前", "改后"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
