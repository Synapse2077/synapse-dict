#!/usr/bin/env python3
"""西语版 36.9 万行入库后的记法归一 —— 把新收的行拉回库内既有约定。2026-08-03。

═══ 为什么这一轮是必需的 ═══
`ingest_edition.py` 落库时跑了 `ipa_norm.normalize()`，但那时的 normalize 少三条规则，
于是同一个 `phonetic` 列里出现了**两套记法并存**（全列字符普查，不是抽样）：

| 家族 | 现值 | 库内既有约定 | 行数 |
|---|---|---|---|
| 后置滑音 | `aˈxewsja` `ˈkoktejl` | `au/eu/ai/ei`（kaikki-en + 我们的 G2P 共 97,829 行） | **55,705** |
| 腭化 ʲ | `pinʲˈtʃila` | `ancho→ˈantʃo`、`colcha→ˈkoltʃa` | 5,591 |
| 唇齿化 ɱ | `koɱfɾiˈkaɾ` | `enfermo→enˈfeɾmo`、`triunfo→ˈtɾjunfo` | 3,923 |
| 可选段括号 | `moʝˈ(ɡ)welo` | 音位式格子里不该有括号 | 942 |

🔴 **三条都不是新决策**：
· 滑音折叠 2026-08-01 就定了（FRAMEWORK §五之二"跟英文版 `ˈeuɾo` 而非 `ˈewɾo`"），
  只是入库时没实现 —— `apply_edition_confirm.glide_fold` 当时只用来**比对**，没用来**落值**；
· ʲ/ɱ 的目标值来自**库内同一位置的既有写法**，不是我的偏好；
· 括号是源头的严式标注，`canon_edition` 只剥组合附加符，独立字母与括号漏了进来。

═══ 不做什么 ═══
🔴 **唇音前的 n→m 不动**（`convertir→kombeɾˈtiɾ`、`un poco→um ˈpoko`，7,216 行）。
   它与 ʲ/ɱ 同族，但**全库六个来源写法一致**（kaikki-en 611 / 我们的 G2P 4,677 /
   es-edition 1,907）—— 那是继承自英文版的既有约定，不是这批新收数据的不一致。
   要改是产品决策（且与已落库的 ŋ→n 有张力），单独提，不夹带在一致性修复里。
🔴 `phonetic_raw` **一个字节都不动** —— 它存的是各源的原值，覆盖它就等于把 provenance 抹了。

═══ 验收 ═══
· 32 个金标准用例（`tests/test_ipa_norm.py`）+ 三条规则各自的变异验证，全绿；
· dbtool 闸门：`expect={}` —— 只改内容，任何列的非空计数都必须零变化；
· 字符差分闸（**不对称**）：只许删 `ʲ ɱ ( ) ɡ j w`、只许增 `n i u`，
  多删或多增一个字符就整批中止。对称写法太松 —— 它会放过"n 被删掉""ɡ 被凭空加上"。

用法（在 es/ 目录）：
    python3 fixes/normalize_notation.py           # 预览 + 残渣报告
    python3 fixes/normalize_notation.py --apply   # 落库
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import ipa_norm as N

# 本词典的音位字符表（全库音标字符普查得出）。用于残渣报告，不作落库闸门。
INVENTORY = set("aeiou" "bdfklmnprstxɡɲɾθʃʝjw" "ˈˌ" " |")
# 字符差分闸，**故意做成不对称的** —— 三条规则只会删掉这些、只会加上那些。
# 对称写法（"差异落在这几个字符上"）太松：它允许 n 被删、ɡ 被凭空加。
DROP_OK = set("ʲɱ()ɡjw")   # ʲ 删；ɱ 换掉；括号与插音 ɡ 删；j/w 换掉
ADD_OK = set("niu")        # ɱ→n；j→i；w→u。除此之外一个字符都不许新增
PAREN = re.compile(r"\(([^)]*)\)")


def new_value(w, v):
    """只跑本轮**新增**的三条规则。

    🔴 不跑整条 `normalize()` —— 库里的值已经过一遍老流水线，整条重跑等于把
    `devoice_coda` 的对位判断在"已经清化过的值"上再算一次，那是另一件事、另一批风险。
    """
    return N.fold_glides(N.resolve_optional(w, N.assimilated_nasals(v)))


def plan():
    conn = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word, phonetic, COALESCE(phonetic_src,'?') FROM dict "
        "WHERE TRIM(COALESCE(phonetic,''))<>''").fetchall()
    conn.close()

    tal, by_src = collections.Counter(), collections.Counter()
    changes, samples, violations = [], [], []
    residue = collections.Counter()
    residue_rows = collections.defaultdict(list)

    for rid, w, v, src in rows:
        tal["有音标"] += 1
        a = N.assimilated_nasals(v)
        b = N.resolve_optional(w, a)
        c = N.fold_glides(b)
        if a != v:
            tal["ʲ/ɱ 归回 n"] += 1
        if b != a:
            tal["可选段落定"] += 1
        if c != b:
            tal["后置滑音折叠"] += 1
        if c != v:
            # 字符差分闸：删掉的必须在 DROP_OK 内，新增的必须在 ADD_OK 内。
            # 带括号的行（940 条）另放宽两处，且**放宽的范围由这一行自己决定**，
            # 不是给全库开口子：可以删的多了"这行括号里的那个字符"，
            # 可以加的多了"这个词拼写末字母对应的塞音"（`president` 的 t）。
            drop_ok, add_ok = DROP_OK, ADD_OK
            if "(" in v:
                drop_ok = drop_ok | {ch for grp in PAREN.findall(v) for ch in grp}
                add_ok = add_ok | {N.LETTER_STOP.get(w[-1:].lower(), "")}
            dropped = set(collections.Counter(v) - collections.Counter(c)) - drop_ok
            added = set(collections.Counter(c) - collections.Counter(v)) - add_ok
            if dropped or added:
                violations.append((w, v, c, "删=%s 增=%s" % ("".join(sorted(dropped)),
                                                            "".join(sorted(added)))))
            changes.append((c, rid))
            by_src[src] += 1
            if len(samples) < 400:
                samples.append((w, v, c, src))
        bad = "".join(sorted({ch for ch in c if ch not in INVENTORY}))
        if bad:
            residue[bad] += 1
            if len(residue_rows[bad]) < 3:
                residue_rows[bad].append((w, c, src))
    return tal, by_src, changes, samples, violations, residue, residue_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    tal, by_src, changes, samples, violations, residue, residue_rows = plan()
    total = tal["有音标"]
    print("%-16s%10s%9s" % ("情况", "行数", "占比"))
    for k in ("有音标", "后置滑音折叠", "ʲ/ɱ 归回 n", "可选段落定"):
        print("  %-14s%10s%8.2f%%" % (k, "{:,}".format(tal[k]), 100 * tal[k] / total))
    print("  %-14s%10s%8.2f%%" % ("合计将改写", "{:,}".format(len(changes)),
                                  100 * len(changes) / total))
    print("  按来源：", dict(by_src))
    dbtool.sample_check(samples, 16, ("词", "改前", "改后", "来源"))

    if violations:
        print("\n🔴 字符差分闸拦下 %d 条（差异不在 ʲɱ()jw/iu 上），整批中止：" % len(violations))
        for x in violations[:20]:
            print("   %-24s %-28s %-28s 异常字符=%s" % x)
        return

    print("\n■ 归一后仍在字符表之外的残渣（本轮不处理，逐条留给下一轮）：%d 行 / %d 族"
          % (sum(residue.values()), len(residue)))
    for k, n in residue.most_common(12):
        print("   %-6r %5d  %s" % (k, n, residue_rows[k][:2]))

    if not a.apply:
        print("\n(预览。确认后 --apply)")
        return

    # expect 全零：只改内容，任何列的非空计数都不该动 —— 未声明的列变了 dbtool 会报错。
    with dbtool.session("notation-fold", expect={}) as s:
        s.executemany("UPDATE dict SET phonetic=? WHERE id=?", changes)


if __name__ == "__main__":
    main()
