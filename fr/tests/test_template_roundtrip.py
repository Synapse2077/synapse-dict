#!/usr/bin/env python3
"""模板生成结果的**可逆性回核**：100% 全量，不抽样。2026-08-24。

═══ 为什么要这个 ═══
四个模板模块一共生成了 198,632 条中文。我此前的"验收"是：
按形状各看两条、随机看二十条 —— **那验的是模板写得对不对，不是每一行配得对不对**。
`[[verification-gates-not-sampling]]`：能确定性回核的东西不许用抽样。

音译准不准只能抽样（没有权威中文表可比）；
但**「这一行的省名/市镇名是不是来自这一行的法语原文」是可判定的**。

═══ 怎么核 ═══
把译名表**反向**（中文 → 法语原串），从**存进库的中文**里把槽值抠回来，
再跟**该行自己的法语原文**逐字比。任一对不上就是配错了。

    法国约讷省圣但尼市镇的居民
      ↓ 反查
    省=Yonne  市镇=Saint-Denis
      ↓ 与本行法语原文比对
    Habitant de Saint-Denis, commune française … du département de l’Yonne.   ✓

🔴 反查会遇到**一个中文对应多个法语名**（1,229 个中文被 1,520 个法语名共用，
   音译撞车是必然的）。所以判据不是「反查出唯一原串」，而是
   **「反查出的候选集合里，包含本行法语原文里的那个」** —— 这仍然是可判定的，
   而且能逮住真正的错配（贴了完全不相干的名字）。

跑：python3 tests/test_template_roundtrip.py        （在 fr/ 目录下）
"""
import argparse
import io
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                                             # noqa: E402
from pipeline.demonym_render import (P_DEP, P_DEP2, P_CTY, WHO_ZH,   # noqa: E402
                                     COUNTRY_ZH, GEO_SLOT, PLACE_SLOT, fix_wangwen,
                                     _ART)


def inverted(path, fix=None):
    """中文 → {法语原串, …}。音译撞车 ⇒ 一个中文可能对应多个法语名。

    🔴 `fix` 必须与**渲染时用的后处理一致**。渲染侧加了望文生义修正
       （`南特雷`→`楠特雷`）而这里没加 ⇒ 反查不到，闸报 747 条红 —— **又是闸错**。
       同一个变换要在两侧同时施加，否则可逆性回核就不再可逆。
    """
    inv = defaultdict(set)
    if not Path(path).exists():
        return inv
    for ln in io.open(path, encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("zh"):
            z = fix(o["zh"]) if fix else o["zh"]
            inv[z].add(o["fr"])
    return inv


DEMONYM = re.compile(r"^法国(.+?)省(.+?)市镇的(居民|女居民|)$")
CTY_RE = re.compile(r"^(.+?)(.+?)的(居民|女居民|)$")


def demonym_rows(con):
    return con.execute("""
        SELECT g.sense_id, g.text,
               (SELECT text FROM sense_gloss WHERE sense_id=g.sense_id AND lang='fr' LIMIT 1)
        FROM sense_gloss g WHERE g.src='template:demonym'""").fetchall()


def check_demonym(rows, dep_inv, plc_inv):
    """→ (总数, 失败列表)。**行由调用方传进来** —— 变异测试要能喂被污染的行。"""
    fail = []
    for sid, zh, fr in rows:
        fr = " ".join((fr or "").split())
        m = DEMONYM.match(zh)
        if not m:
            # 国家那一族（`比利时 X 的居民`）单独判：国名必须在闭集里且出现在原文
            # 🔴 `P_CTY` 有 3 个捕获组：1=通名 2=**地名** 3=**国名**。
            #    第一版我写 group(2) 当国名 ⇒ 3,704 条全报红，**是闸错不是数据错**。
            #    教训：闸报红先验闸（`[[criteria-narrower-than-you-think]]`）。
            mc = P_CTY.match(fr)
            if mc and COUNTRY_ZH.get(mc.group(3).strip()) and \
                    zh.startswith(COUNTRY_ZH[mc.group(3).strip()]):
                continue
            fail.append((sid, "中文形状认不出", zh, fr))
            continue
        dep_zh_s, plc_zh_s, who_zh_s = m.group(1), m.group(2).strip(), m.group(3)

        ms = P_DEP.match(fr) or P_DEP2.match(fr)
        if not ms:
            fail.append((sid, "法语原文重新解析失败", zh, fr))
            continue
        who_fr, plc_fr, dep_fr = ms.group(1), ms.group(2).strip(), ms.group(3).strip()

        if WHO_ZH[who_fr] != who_zh_s:
            fail.append((sid, "居民/女居民/形容词 配错", zh, fr))
            continue
        # ⚠️ 比对前**两边都去定冠词**，与 `demonym_render.dep_lookup` 同一个口径。
        #    海外省源文写 `département de La Réunion`，省表里存的是 `Réunion`；
        #    闸不跟着做这一步，就会把 71 条**正确**的渲染报成红（第四次「闸比渲染旧」了）。
        got = {_ART.sub("", x) for x in dep_inv.get(dep_zh_s, set())}
        if _ART.sub("", dep_fr) not in got:
            fail.append((sid, "省名配错", zh, fr))
            continue
        # 市镇名：有音译则反查，无音译则中文里应原样保留法语名
        if plc_zh_s in plc_inv:
            if plc_fr not in plc_inv[plc_zh_s]:
                fail.append((sid, "市镇名配错", zh, fr))
        elif plc_zh_s != plc_fr:
            fail.append((sid, "退回原名但对不上", zh, fr))
    return len(rows), fail


def check_no_orphan(con):
    """每条模板生成的中文，其 sense 必须真有对应的法语原文 —— **按来源拆开**。

    🔴 `template:alt_of` / `template:fr-alt_of` 是从 **kaikki dump 的结构化字段**
       建的，本来就没有法语 gloss 行 ⇒ 它们不算孤儿。合并成一个数会把
       「正常」和「异常」搅在一起（第一版就报了 4,984 让我以为出事了）。
    """
    return con.execute("""
        SELECT g.src, count(*) FROM sense_gloss g
        WHERE g.src LIKE 'template:%'
          AND NOT EXISTS (SELECT 1 FROM sense_gloss f
                          WHERE f.sense_id=g.sense_id AND f.lang='fr')
        GROUP BY g.src ORDER BY 2 DESC""").fetchall()


def check_dup(con):
    return con.execute("""
        SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='zh'
                              GROUP BY sense_id HAVING count(*)>1)""").fetchone()[0]


def mutate(rows, dep_inv, plc_inv):
    """**证明这道闸会红**。一道从来没红过的闸和没有闸没区别。

    四种变异各污染一行，每种都必须被逮到。`check_demonym` 的行由调用方传入
    就是为了这个 —— 不动库、不留痕。
    """
    import copy
    cases = []
    base = [r for r in rows if "市镇的" in r[1]][:4]
    if len(base) < 4:
        return []
    a, b, c, d = copy.deepcopy(base)
    cases.append(("整行换成另一条的中文", [(a[0], base[1][1], a[2])]))
    cases.append(("省名换成别的省", [(b[0], b[1].replace("法国", "法国XX", 1), b[2])]))
    cases.append(("市镇名换成别条的", [(c[0], re.sub(r"省.+?市镇", "省巴黎市镇", c[1]), c[2])]))
    cases.append(("居民↔女居民", [(d[0], d[1].replace("的居民", "的女居民"), d[2])]))
    out = []
    for tag, rs in cases:
        _n, f = check_demonym(rs, dep_inv, plc_inv)
        out.append((tag, bool(f), f[0][1] if f else "—"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true", help="验这道闸本身还能不能报红")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    dep_inv = inverted(GEO_SLOT)
    plc_inv = inverted(PLACE_SLOT, fix_wangwen)
    print("■ 反查表：省名 %s 个中文 / 市镇名 %s 个中文"
          % (format(len(dep_inv), ","), format(len(plc_inv), ",")))

    rows = demonym_rows(con)
    n, fail = check_demonym(rows, dep_inv, plc_inv)
    print("\n① 居民族可逆性回核：%s 条全量核对，失败 %s（%.4f%%）"
          % (format(n, ","), format(len(fail), ","), 100.0 * len(fail) / max(n, 1)))
    for k, v in Counter(f[1] for f in fail).most_common():
        print("     %-22s %s" % (k, format(v, ",")))
    for f in fail[:6]:
        print("     · [%s] %s\n         ← %s" % (f[1], f[2][:60], f[3][:76]))

    rows_o = check_no_orphan(con)
    # 这两类**本来就**没有法语 gloss（从 dump 的结构化字段建的），不算异常
    OK_NO_FR = {"template:alt_of", "template:fr-alt_of"}
    orph = sum(n for src, n in rows_o if src not in OK_NO_FR)
    print("\n② 模板中文的 sense 无法语原文：")
    for src, n in rows_o:
        print("     %-22s %8s %s" % (src, format(n, ","),
                                     "（正常：源自 dump 结构化字段）" if src in OK_NO_FR
                                     else "🔴 异常"))
    dup = check_dup(con)
    print("③ 一个 sense 两条中文（重复上架）：%s" % format(dup, ","))

    bad = len(fail) + orph + dup
    print("\n%s" % ("🔴 有 %s 项不通过" % format(bad, ",") if bad else "✓ 三项全绿"))

    if a.mutate:
        print("\n④ 变异测试（这道闸自己会不会红）")
        ms = mutate(rows, dep_inv, plc_inv)
        for tag, caught, why in ms:
            print("     %s %-20s %s" % ("✓ 逮到" if caught else "🔴 漏了", tag, why))
        if not all(c for _t, c, _w in ms):
            print("🔴 闸失灵：有变异没被逮到")
            return 1
        print("     %d/%d 全部逮到" % (len(ms), len(ms)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
