#!/usr/bin/env python3
"""顶层账本 `docs/BACKLOG.md` 自己的闸（B5②）。2026-10-27。

═══ 为什么 ═══
BACKLOG 建好之后一直没有闸：汇总行写着「开着 B1–B8」而 B9–B18 早就在表里；
「这仓库总共欠什么」要逐份读九份计划表才答得出。`[[lesson-must-become-mechanism]]`。

═══ 判据 ═══
  G1 账目每一行六栏齐；开着的「影响哪几门」「什么算结清」非空；划掉的写了「结清」和日期。
  G2 编号唯一、从 B1 连续到 `EXPECT_MAX`（**独立声明**：删掉最后一条，「连续」逮不到它）。
  G3 文末「合计」行的两个数 ＝ 从表里数出来的（汇总行会自己过期，所以不许手写了不核）。
  G4 索引 vs 各门计划表：ja／ko／vi／ru 表里**开着的编号**与索引**逐字相等**。
     「开着」的判据在 vi 的收尾交接上逐条对过（W1/W3/W8/W11/W18/W21/W22，7/7）。
  G5 完结门的残差清单（de／pt／fr 收尾单）与 en §16.7 锁**行数**：加了一行就红，逼人判它是残差还是待办。

用法：
    python3 -u scripts/test_backlog_gate.py            # 红了退出码非 0
    python3 -u scripts/test_backlog_gate.py --mutate   # 在内存里的文本上注入
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
EXPECT_MAX = 29          # 新增一条 B 就改这里 —— 删掉最后一条时它是唯一会响的东西

# (门, 计划表, 节起始标题, 编号前缀)。节＝起始标题到下一个同级或更高级标题。
SECTIONS = [
    ("ja", "JA_PLAN.md", "## 六、📋 欠账", ""),
    ("ja", "JA_PLAN.md", "## 收尾单的交接", "交接"),
    ("ko", "KO_PLAN.md", "## 六、📋 欠账", ""),
    ("vi", "VI_PLAN.md", "## 五、📋 欠账", ""),
    ("ru", "RU_PLAN.md", "### 📋 欠账", ""),
]
# 锁行数的表：(名字, 计划表, 节起始标题, 期望行数)。行数取自 2026-10-27 逐份读过的那一版。
LOCKED = [
    ("de 收尾单", "DE_PLAN.md", "# 📋 de 收尾单", 46),
    ("pt 收尾单", "PT_PLAN.md", "# 📋 pt 收尾单", 67),
    ("fr 收尾单", "FR_PLAN.md", "# 📋 fr 收尾单", 46),
]
EN_UNFIXED = ("EN_PLAN.md", "### 16.7 顺带记账", 3)   # 「未修」的条数

ROW = re.compile(r"^\|\s*(~~)?\**([A-Z]{0,2}\d+[a-z]?)\**(~~)?\s*\|")
CLOSED = re.compile(r"✅\s*\**\s*(已结|已完成|已做|已解决|已否决|结清|已修|已还|完成)|已结清|⚪\s*\**已裁决|"
                    r"❌\s*\**(不做|量过之后不做)|已否决")


def cells_of(l):
    """按**未转义**的 `|` 切（单元格里的正则写成 `\\|`，B23 就有）。"""
    return [c.strip() for c in re.split(r"(?<!\\)\|", l)[1:-1]]


def section(text, head):
    """→ 从 head 那一行到下一个同级或更高级标题之间的行。找不到 head 返回 None。"""
    L = text.splitlines()
    level = len(head) - len(head.lstrip("#"))
    for i, l in enumerate(L):
        if l.strip().startswith(head):        # 标题后面常带日期：`# 📋 fr 收尾单（2026-08-27 建）`
            out = []
            for m in L[i + 1:]:
                h = re.match(r"^(#+) ", m)
                if h and len(h.group(1)) <= level:
                    break
                out.append(m)
            return out
    return None


def open_ids(lines, prefix):
    got = []
    for l in lines:
        m = ROW.match(l)
        if not m or m.group(2) in ("#",):
            continue
        cells = cells_of(l)
        # ⚪ 开头＝落了账的否定结论（「有意为空」「量过不做」），不是待办 —— ja #24 那种
        struck = bool(m.group(1)) or cells[1].startswith("~~") or cells[1].lstrip("*").startswith("⚪")
        closed = struck or any(CLOSED.search(c[:60]) for c in cells[1:])
        # ja 交接表里「挂着」的才算开着（其余几行是已完成的交接说明）
        if prefix == "交接" and "挂着" not in l:
            continue
        if not closed:
            got.append(prefix + m.group(2))
    return got


def id_rows(lines):
    return [l for l in lines if ROW.match(l)]


def parse_backlog(text):
    acct = section(text, "## 账目") or []
    rows = []
    for l in acct:
        m = re.match(r"^\|\s*(~~)?\*\*B(\d+)\*\*(~~)?\s*\|", l)
        if m:
            rows.append((int(m.group(2)), bool(m.group(1)), cells_of(l)))
    idx = section(text, "## 各门开着的账（索引）") or []
    index = {}
    for l in idx:
        cells = cells_of(l)
        if len(cells) == 4 and cells[0] in ("ja", "ko", "vi", "ru", "en", "pt", "es", "it") and cells[1] != "—":
            index.setdefault(cells[0], []).extend(cells[1].split())
    return rows, index, idx


def check(backlog, plans):
    """→ [(编号, 说明)]。backlog/plans 是文本，方便变异在内存里改。"""
    bad = []
    rows, index, idx = parse_backlog(backlog)
    nums = [n for n, _s, _c in rows]
    for n, struck, c in rows:
        if len(c) != 6:
            bad.append(("G1", "B%d 有 %d 栏，应为 6" % (n, len(c))))
            continue
        if struck:
            if "结清" not in c[1] or not re.search(r"20\d\d-\d\d-\d\d", c[1]):
                bad.append(("G1", "B%d 划掉了而状态栏没写「结清」和日期" % n))
        elif not c[2] or not c[5]:
            bad.append(("G1", "B%d 开着而「影响哪几门」或「什么算结清」是空的" % n))
    if len(set(nums)) != len(nums):
        bad.append(("G2", "B 编号重复：%s" % sorted({n for n in nums if nums.count(n) > 1})))
    if sorted(set(nums)) != list(range(1, EXPECT_MAX + 1)):
        miss = sorted(set(range(1, EXPECT_MAX + 1)) - set(nums))
        extra = sorted(set(nums) - set(range(1, EXPECT_MAX + 1)))
        bad.append(("G2", "B 编号应为 B1–B%d：缺 %s，多 %s（新增一条要改 EXPECT_MAX）"
                    % (EXPECT_MAX, miss or "无", extra or "无")))
    n_open_b = sum(1 for _n, s, _c in rows if not s)
    n_index = sum(len(v) for v in index.values())
    tot = [l for l in idx if l.startswith("**合计")]
    if len(tot) != 1:
        bad.append(("G3", "索引节里应有恰好一行「**合计…」，有 %d 行" % len(tot)))
    else:
        m = re.search(r"各门待办\s*(\d+)\s*笔.*?顶层 B 系列开着\s*(\d+)\s*条", tot[0])
        if not m:
            bad.append(("G3", "合计行认不出两个数：%s" % tot[0][:80]))
        else:
            if int(m.group(1)) != n_index:
                bad.append(("G3", "合计写各门待办 %s 笔，索引里数出 %d" % (m.group(1), n_index)))
            if int(m.group(2)) != n_open_b:
                bad.append(("G3", "合计写顶层开着 %s 条，账目里数出 %d" % (m.group(2), n_open_b)))
    want = {}
    for lang, f, head, prefix in SECTIONS:
        sec = section(plans[f], head)
        if sec is None:
            bad.append(("G4", "%s 找不到节标题「%s」—— 标题改了就改 SECTIONS" % (f, head)))
            continue
        want.setdefault(lang, []).extend(open_ids(sec, prefix))
    for lang in sorted(want):
        have, w = index.get(lang, []), want[lang]
        if sorted(have) != sorted(w):
            bad.append(("G4", "%s：计划表开着 %s，索引登记 %s —— 多出 %s／缺 %s"
                        % (lang, len(w), len(have), sorted(set(have) - set(w)) or "无",
                           sorted(set(w) - set(have)) or "无")))
    for name, f, head, n in LOCKED:
        sec = section(plans[f], head)
        got = len(id_rows(sec)) if sec is not None else -1
        if got != n:
            bad.append(("G5", "%s 行数 %d ≠ 锁定 %d —— 新加的那行是残差还是待办？待办要进索引，然后改锁" % (name, got, n)))
    f, head, n = EN_UNFIXED
    sec = section(plans[f], head)
    got = sum("未修" in l for l in sec) if sec is not None else -1
    if got != n:
        bad.append(("G5", "en §16.7「未修」%d 条 ≠ 锁定 %d —— 修了就从索引划掉并改锁" % (got, n)))
    return bad, n_open_b, n_index


def load():
    return ((DOCS / "BACKLOG.md").read_text(encoding="utf-8"),
            {f: (DOCS / f).read_text(encoding="utf-8")
             for f in {s[1] for s in SECTIONS} | {s[1] for s in LOCKED} | {EN_UNFIXED[0]}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    backlog, plans = load()
    bad, nb, ni = check(backlog, plans)
    print("■ 顶层账本闸：顶层 B 开着 %d 条 ／ 各门待办 %d 笔" % (nb, ni))
    for cid, why in bad:
        print("  🔴 %-3s %s" % (cid, why))
    print("  ✅ 全绿" if not bad else "  🔴 %d 处" % len(bad))
    if not a.mutate:
        sys.exit(1 if bad else 0)

    print("\n■ 变异（内存里的文本）")
    ko = plans["KO_PLAN.md"]
    k14 = next(l for l in ko.splitlines() if l.startswith("| **K14** |"))
    last_b = next(l for l in reversed(backlog.splitlines()) if re.match(r"^\| (~~)?\*\*B\d+", l))
    de = plans["DE_PLAN.md"]
    c4 = next(l for l in de.splitlines() if l.startswith("| C4 |"))
    b1 = next(l for l in backlog.splitlines() if l.startswith("| **B1** |"))
    b1c = re.split(r"(?<!\\)\|", b1)
    cases = [
        ("ko 新开一笔没进索引", "G4", backlog, dict(plans, **{"KO_PLAN.md": ko.replace(k14, k14 + "\n" + k14.replace("K14", "K99"))})),
        ("ko 结清 K14 而索引没划", "G4", backlog, dict(plans, **{"KO_PLAN.md": ko.replace(k14, k14.replace("| **K14** |", "| ~~**K14**~~ |"))})),
        ("删掉最后一条 B", "G2", backlog.replace(last_b + "\n", ""), plans),
        ("合计行数字过期", "G3", re.sub(r"各门待办 \d+", "各门待办 1", backlog), plans),
        ("de 收尾单加一行", "G5", backlog, dict(plans, **{"DE_PLAN.md": de.replace(c4, c4 + "\n" + c4.replace("C4", "C99"))})),
        ("B1 的结清条件被清空", "G1", backlog.replace(b1, "|".join(b1c[:6] + [" "] + b1c[7:])), plans),
        ("（反控）原样", None, backlog, plans),
    ]
    dead = 0
    for name, want, bt, pl in cases:
        got, _x, _y = check(bt, pl)
        ids = {c for c, _w in got}
        ok = (not got) if want is None else (want in ids)
        dead += not ok
        print("  %s %-22s → %s" % ("✅" if ok else "🔴 没逮到", name, "；".join(sorted(ids)) or "（绿）"))
    print("  变异 %d/%d" % (len(cases) - dead, len(cases)))
    sys.exit(1 if dead or bad else 0)


if __name__ == "__main__":
    main()
