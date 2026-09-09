#!/usr/bin/env python3
"""量 en 例句层的**规模与构成** —— 为阶段 5 报价。2026-09-07。

用户 2026-09-07 问「这个花费还只是刚开始对吧」。是。义项释义 198 元只是 1.5c 一项，
剩下最大的一笔在**例句翻译**。pt 那轮 4 万条句子，en 是另一个量级 —— 必须实测。

═══ 🔴 英文版和其他五门有一个结构差别：书证 ═══
英文 Wiktionary 的 `examples` 里混着两族：
    type=example  一句话的用例，**这才是词典要的**
    type=quote    书证引文（带 ref：作者/书名/年份），常常两三行
书证对**词典产品**几乎无用（用户要的是划词弹窗），但它按字符收费，
而且长度是用例的好几倍 ⇒ 不分开量就会把报价抬到天上去。

⇒ 本脚本分开量两族的**条数 / 去重后条数 / 字符数**，
   并且按「内容键去重」（同一句给多个义项当例句只翻一次，pt 实测省 21%）。

⚠️ 只读 dump，不碰库。
    cd en && python3 -u probes/example_scale.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
from collections import Counter

import paths

POINTER = ("form-of", "alt-of")


def main():
    n_line = n_sense = 0
    cnt = Counter()          # (kind) -> 条数
    chars = Counter()        # (kind) -> 字符数
    seen = {}                # kind -> set(内容键)
    has_en_tr = 0            # 已带英文译文（本语种是英语，这一栏应为 0，做负控）
    with_zh = 0
    for kind in ("example", "quote", "other"):
        seen[kind] = set()

    with paths.KK.open(encoding="utf-8") as f:
        for ln in f:
            n_line += 1
            try:
                o = json.loads(ln)
            except Exception:
                continue
            if o.get("source") == "thesaurus":
                continue
            for s in o.get("senses") or []:
                tags = set(s.get("tags") or [])
                if s.get("form_of") or tags & set(POINTER):
                    continue
                n_sense += 1
                for ex in s.get("examples") or []:
                    t = (ex.get("text") or "").strip()
                    if not t:
                        continue
                    ty = ex.get("type") or ""
                    k = "quote" if ty == "quote" or ex.get("ref") else \
                        "example" if ty == "example" else "other"
                    cnt[k] += 1
                    chars[k] += len(t)
                    seen[k].add(t)
                    if ex.get("english"):
                        has_en_tr += 1
                    if any("一" <= c <= "鿿" for c in t):
                        with_zh += 1
            if n_line % 200000 == 0:
                print("   … %s 行  例句 %s" % (format(n_line, ","), format(sum(cnt.values()), ",")),
                      flush=True)

    print("\n═══ dump 扫完：%s 行 ／ %s 个实义项 ═══" % (format(n_line, ","), format(n_sense, ",")))
    print("   %-10s %12s %12s %10s %9s" % ("族", "条数", "去重后", "去重率", "平均字符"))
    tot_u = 0
    for k in ("example", "quote", "other"):
        c, u, ch = cnt[k], len(seen[k]), chars[k]
        if not c:
            continue
        tot_u += u
        print("   %-10s %12s %12s %9.1f%% %9.1f"
              % (k, format(c, ","), format(u, ","), 100 * (1 - u / c), ch / c))
    print("   %-10s %12s %12s" % ("合计", format(sum(cnt.values()), ","), format(tot_u, ",")))
    print("\n   负控：例句自带 english 译文 %s 条（英语版应为 0 —— 非 0 说明我误读了字段）"
          % format(has_en_tr, ","))
    print("   例句正文里含汉字 %s 条" % format(with_zh, ","))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
