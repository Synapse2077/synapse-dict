#!/usr/bin/env python3
"""变形层的原形写成「X and Y」：拆成两行，不是删掉 and。2026-08-21。

═══ 怎么发现的 ═══
2026-08-21 点测评审，两家外审都指出 `ha` 的变位区块写着
**「avere and 的 陈述式现在时第三人称单数」** —— `and` 不是意大利语。

═══ 但它不是残渣 ═══
🔴 第一反应是「把 ` and` 剥掉」。回源看 `desc_en` 才发现**源头本来就给了两个原形**：

    ha        ← third-person singular present indicative of avere and (obsolete) havere
    esse      ← plural of ella and essa; they, them (female)
    spento    ← past participle of spegnere and spengere
    arruolo   ← first-person singular present indicative of arruolare and arrolare

`esse` 确实**同时**是 `ella` 和 `essa` 的复数；`spegnere`/`spengere` 是同一动词的
两个不定式写法。剥掉 ` and` 会丢掉第二个原形的链接 —— 那正是 `clean_inflection_base`
在管的「悬空原形」缺陷，只不过换了个方向。
⇒ **拆成两行**，每行一个原形，各自解析 `base_id`。30 行 → 60 行。

═══ 解析规则与一个顺序坑 ═══
从 `desc_en` 的 ` of ` 之后取原形列表。
🔴 **必须先去掉 `(obsolete)` 这类圆括号标记，再按 ` and ` 切** —— 顺序反了的话，
   `avere and (obsolete) havere` 会在 `(` 处被砍断，只剩 `avere`，
   而 `havere` 这个真原形（库里有）就丢了。第一版就是这么丢的 4 条。
   ⚠️ 「归一/切分的先后顺序就是判据」——这已经是第三次踩。

验收：30 行全部解析出 ≥2 个原形，且**每个原形都在 dict 里查得到**（实测 30/30）。

用法（在 it/ 目录下）：
    python3 fixes/split_multi_base_inflection.py            # 干跑
    python3 fixes/split_multi_base_inflection.py --apply
    python3 fixes/split_multi_base_inflection.py --verify
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")


def has_multi_base(base):
    """判据：`base` 里混着英文 and。回归闸 D2 用的就是这条。"""
    s = (base or "").strip()
    return " and " in s or s.endswith(" and")


def bases_from_desc(desc):
    """从 `... of X and Y` 解析出全部原形。

    🔴 两步的**顺序**是判据：① 先抹掉 `(obsolete)` 这类圆括号标记
       ② 再砍冒号/破折号之后的说明。反过来会把 `(obsolete) havere` 整条丢掉。
    """
    if not desc:
        return []
    m = re.search(r"\bof\s+(.*)$", desc)
    if not m:
        return []
    tail = re.sub(r"\([^)]*\)", " ", m.group(1))        # ①
    tail = re.split(r"[:;]|\s—|\s“", tail)[0]           # ②
    out = []
    for p in re.split(r"\s+and\s+", tail):
        p = p.strip().strip(".,;:")
        if p:
            out.append(p)
    return out


def scan(con):
    """→ [(row, [原形…])]，row 是 inflection 的整行 dict。"""
    cols = [r[1] for r in con.execute("PRAGMA table_info(inflection)")]
    words = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    out = []
    for r in con.execute("SELECT %s FROM inflection WHERE base LIKE '%% and%%'"
                         % ",".join(cols)):
        row = dict(zip(cols, r))
        bs = bases_from_desc(row["desc_en"])
        if len(bs) < 2 or not all(b in words for b in bs):
            raise SystemExit("🔴 解析不出两个都在库里的原形：id=%s desc=%r → %r"
                             % (row["id"], row["desc_en"], bs))
        out.append((row, bs, [words[b] for b in bs]))
    return out


def gate(con):
    """--verify：读取路径（inflQuery 就是读 base 这一列）上不该再有 and。"""
    n = sum(1 for (b,) in con.execute("SELECT base FROM inflection") if has_multi_base(b))
    dangling = con.execute(
        "SELECT COUNT(*) FROM inflection WHERE base_id IS NULL AND base IN "
        "(SELECT word FROM dict)").fetchone()[0]
    print("■ base 里仍含 and：%s 条" % f(n))
    print("■ base 在 dict 里、base_id 却为空（悬空）：%s 条" % f(dangling))
    return n == 0


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        ok = gate(ro)
        ro.close()
        return 0 if ok else 1
    items = scan(ro)
    ro.close()
    extra = sum(len(bs) - 1 for _r, bs, _ids in items)
    print("■ 要拆的行：%s 条 → 拆成 %s 行（净增 %s）"
          % (f(len(items)), f(len(items) + extra), f(extra)))
    for row, bs, _ids in items[:8]:
        print("     %-14s %-30r → %s" % (row["id"], row["base"], " | ".join(bs)))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("split-multi-base-inflection",
                        expect={"__rows__": 0, "#inflection": extra}) as s:
        for row, bs, ids in items:
            # 原行改成第一个原形
            s.execute("UPDATE inflection SET base=?, base_id=? WHERE id=?",
                      (bs[0], ids[0], row["id"]))
            # 其余各插一行。🔴 `src_ref` 有 UNIQUE 约束，必须给新值。
            for k, (b, bid) in enumerate(zip(bs[1:], ids[1:]), start=2):
                s.execute(
                    "INSERT INTO inflection (word_id,entry_id,base,base_id,label_zh,"
                    "desc_en,tags,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?)",
                    (row["word_id"], row["entry_id"], b, bid, row["label_zh"],
                     row["desc_en"], row["tags"], row["src"],
                     "%s|and%d" % (row["src_ref"], k)))
        s.written = len(items) + extra
    print("\n■ 已拆 %s 条为 %s 行" % (f(len(items)), f(len(items) + extra)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
