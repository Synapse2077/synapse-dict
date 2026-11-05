#!/usr/bin/env python3
"""B29（vi）：中文释义／例句译文的出版正文（简体）同步。2026-10-30。

    python3 -u vi/pipeline/zh_pub.py            # 干跑：数要改多少、抽样印出来
    python3 -u vi/pipeline/zh_pub.py --apply    # 写库（走 dbtool 闸门）

═══ 为什么要一列 ═══
中文版白送的释义／例句译文是繁体（`代表，表示，表現，體現`），与付费的简体印在同一页。
vi 的 `*_gloss.text` 约定是**源头原文**（外锚闸逐字比）⇒ 简体写进 `text_pub`，见 `build_v3_schema.ADD_COLUMNS`。

═══ 判据 ═══
`scripts/zh_t2s.t2s`（跨门一份：汉字/喃字原形 `［保領］`、`nhà Hậu Lê（後黎朝）`、同音字表不动）。
**只转中文版白送的**（`src` 以 `zh-edition` 开头）；模型写的那批大半在讲汉字/喃字原形，**按逐行裁决清单改**
（`vi/fixes/b29_model_zh.json`，读法在 `scripts/fix_model_zh_trad.overrides()`，2026-10-31）：
清单里的 23 行用裁决的出版正文，其余照抄原文。清单里记的原文与库对不上就炸，不静默退回照抄。

═══ 约定 ═══
`lang='zh'` 的行 `text_pub` **全部有值**（不变的照抄），展示层只读它 —— 与 `example.text_pub` 同一条（不写 COALESCE）。
幂等：再跑一遍 0 改动。`text` 一个字不动。
"""
import argparse
import collections
import random
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
import build_v3_schema as SCHEMA  # noqa: E402
import paths  # noqa: E402
from zh_t2s import t2s  # noqa: E402
from fix_model_zh_trad import overrides  # noqa: E402  —— B29 模型写的那批：逐行裁决
from stage6_sources import clean_markup  # noqa: E402  —— 2026-11-01：释义出版正文去 wiki 标记（与例句出版正文同一个函数）
import json  # noqa: E402

# 2026-11-01：通用清洗还原不了的残缺模板 —— 逐行裁决，原文漂了就炸（与 B29 清单同一个约定）
MARKUP_DECISIONS = HERE.parent / "fixes" / "markup_pub.json"

TABLES = ("sense_gloss", "example_gloss", "sense_src", "etymology")   # sense_src：「这个词形指向」区直接印它
# 词源正文里「來自 X」的 X 是被引的汉字原形（与 en 版 `from 醫` 同一个意思）⇒ 不转；只转框架文字
_CITED = re.compile(r"(來自|来自|源自|借自|出自)([\u3400-\u9fff\U00020000-\U0003ffff]+)")
CONVERT_SRC = "zh-edition"


def scope(t):
    """哪些行必须有出版正文。闸 import 它，不重写。

    etymology 没有 lang 列 ⇒ 全部行；**sense_gloss 自 2026-11-01 起全部语言**（en/vi 的释义里也有 wiki 标记残渣：
    `càn khôn` 的 `[[w:…|…]]`、`Châu Đại Dương` 的半截 `{{place`；`text` 是源头原文不能改 ⇒ 只能进出版列，
    展示层三种语言都只读 `text_pub`）；其余表是 zh 行。
    """
    if t in ("etymology", "sense_gloss"):
        return "1"
    return "lang='zh'"


def markup_decisions(con):
    """→ {(表, id): 出版正文}。原文与库对不上就炸 —— 不许静默退回清洗结果。"""
    rows = json.loads(MARKUP_DECISIONS.read_text(encoding="utf-8"))["rows"] if MARKUP_DECISIONS.exists() else []
    bad = []
    for d in rows:
        cur = con.execute("SELECT text FROM %s WHERE id=?" % d["table"], (d["id"],)).fetchone()
        if cur is None or cur[0] != d["orig"]:
            bad.append((d["table"], d["id"]))
    if bad:
        raise SystemExit("🔴 标记裁决清单与库对不上 %d 条（原文变了或行不在了）：%s" % (len(bad), bad))
    return {(d["table"], d["id"]): d["new"] for d in rows}


def want(text, src, cited=False):
    """这一行该印什么。`cited`：词源正文 —— 「來自」后面的汉字原形先换成占位符护住，转完再换回来。"""
    if not (src or "").startswith(CONVERT_SRC):
        return text
    if not cited:
        return t2s(text)
    keep = []

    def hide(m):
        if m.group(2)[-1] in "語语文":            # `來自法語 xénon`／`源自英語` —— 语言名不是被引的原形
            return m.group(0)
        keep.append(m.group(2))
        return m.group(1) + "\ue000%d\ue001" % (len(keep) - 1)
    def hide_after_lang(m):                       # `來自中古漢語 學 (hjæwk)` —— 语言名后面空一格引的原字
        keep.append(m.group(2))
        return m.group(1) + "\ue000%d\ue001" % (len(keep) - 1)
    text = _CITED.sub(hide, text)
    text = re.sub(r"([語语]\s+)([\u3400-\u9fff\U00020000-\U0003ffff]+)", hide_after_lang, text)
    out = t2s(text)
    return re.sub("\ue000(\\d+)\ue001", lambda m: keep[int(m.group(1))], out)


def plan(con):
    """→ {表: [(text_pub, id)]}、统计"""
    out, st = {}, collections.Counter()
    ov = overrides(con, "vi")
    mk = markup_decisions(con)
    for t in TABLES:
        has = any(c[1] == "text_pub" for c in con.execute("PRAGMA table_info(%s)" % t))
        up = []
        # sense_src 只有「指针」那一类上页面；其余大半是汉字表记本身（`鉀`、`賡韻`，W2）—— 不转，照抄，
        #   免得「出版正文」里出现一个被转成简体的汉字写法
        only_ptr = t == "sense_src"
        # etymology 没有 lang 列：**全部行**都要有出版正文（展示层只读它），中文版的才转
        where = scope(t)
        for rid, text, src, pub, ptr in con.execute(
                "SELECT id, text, src, %s, %s FROM %s WHERE %s"
                % ("text_pub" if has else "NULL", "ptr_class" if only_ptr else "NULL", t, where)):
            w = want(text, src, cited=t == "etymology") if (not only_ptr or ptr == "pointer") else text
            if (t, rid) in ov:
                w = ov[(t, rid)]
            if t in ("sense_gloss", "etymology"):   # 2026-11-01：释义／词源的出版正文去 wiki 标记（W18 的 `^(…)` 也在这里）；
                w = mk.get((t, rid)) or clean_markup(w)   #   清洗还原不了的走逐行裁决
            if w != pub:
                up.append((w, rid))
                st["%s：%s" % (t, "改写（转简体／去标记／裁决）" if w != text else "照抄")] += 1
        out[t] = up
    return out, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    up, st = plan(con)
    W = scope
    n_zh = {t: con.execute("SELECT COUNT(*) FROM %s WHERE %s" % (t, W(t))).fetchone()[0] for t in TABLES}
    con.close()
    print("■ B29 vi 中文出版正文")
    for k, v in sorted(st.items()):
        print("   %-28s %8s" % (k, format(v, ",")))
    conv = [(t, w, r) for t in TABLES for w, r in up[t]]
    for t, w, r in random.Random(29).sample(conv, min(10, len(conv))):
        print("   %-13s %s" % (t, w[:60].replace("\n", " / ")))
    if not a.apply or not conv:
        print("\n（干跑。加 --apply 才写库）" if conv else "\n（无事可做）")
        return
    import dbtool
    have = {t: {c[1] for c in sqlite3.connect(paths.DB).execute("PRAGMA table_info(%s)" % t)} for t in TABLES}
    # 非空计数的增量 ＝ 范围内现在还是 NULL 的行（写完全部有值）；已有值再改写的不改变非空计数。
    #   原来写 `len(up[t])`，在「全是 NULL → 有值」的首轮恰好相等；2026-11-01 扩到 en/vi 时两者第一次不等。
    _c = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n_null = {t: (_c.execute("SELECT COUNT(*) FROM %s WHERE %s AND text_pub IS NULL" % (t, W(t))).fetchone()[0]
                  if "text_pub" in have[t] else n_zh[t]) for t in TABLES}
    _c.close()
    with dbtool.session("b29-vi-zh-pub",
                        expect={"__rows__": 0, **{"%s.text_pub" % t: n_null[t] for t in TABLES}},
                        invalidates=None) as s:
        # 列先补上再写：`ADD_COLUMNS` 是建表那一侧的登记表，这里调它而不是自己写 DDL
        for tbl, col, typ in SCHEMA.ADD_COLUMNS:
            if tbl in TABLES and col not in have[tbl]:
                s.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, typ))
        for t in TABLES:
            s.executemany("UPDATE %s SET text_pub=? WHERE id=?" % t, up[t])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left, _ = plan(con)
    nulls = {t: con.execute("SELECT COUNT(*) FROM %s WHERE %s AND text_pub IS NULL" % (t, W(t))).fetchone()[0]
             for t in TABLES}
    con.close()
    print("\n■ 写后回核：仍要改 %d（期望 0）｜zh 行 text_pub 为空 %s（期望全 0）｜zh 行数 %s"
          % (sum(len(v) for v in left.values()), nulls, n_zh))
    if any(left.values()) or any(nulls.values()):
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
