#!/usr/bin/env python3
"""ko 展示层**值域覆盖闸**：库里出现的每一个码，映射表里都得有一格。2026-09-25（阶段 9）。

═══ 为什么要有这道闸 ═══
写 `packages/dict-labels/src/ko.ts` 时，`KO_RELATION_LABELS` 我**照着我以为有的写**
—— 抄的是前面一次 `SELECT … LIMIT 12` 的输出，没回头重新量值域。
结果缺了 7 个关系类型（counter / descendant / dialectal / holonym /
hypernym / hyponym / meronym），页面上那 1,172 条边的标题会是**空的**。

🔴🔴 当时是一段**临时脚本**逮到的，跑完就扔了。
   `[[lesson-must-become-mechanism]]`：**做成机制的全守住了、写成文字的一条没守住。**
   一段只跑过一次的检查不是闸 —— 下次加一层、源头多出一个码，没有人会再想起它。
   ⇒ 落成这个文件。

═══ 两个方向都要查（`[[verification-gates-not-sampling]]`）═══
  ① **库里有、表里缺** ⇒ 页面上那个徽标是空的（这次犯的就是这个）
  ② **表里有、库里没有** ⇒ 我在凭想象写表。它不会让页面出错，
     但它说明**我写表的依据不是实测**，而下一格就可能写错。
     ⚠️ 这个方向**有意只警告不拦**：源头下一版多给一个码是正常的，
        映射表提前备着不是缺陷。但它必须**被看见**。

═══ 🔴 这道闸**管不到**什么（变异验证当场量出来的）═══
把 `part: '助词'` 从 ko 覆盖层删掉，闸**报绿** —— 因为全局表有 `part: '小品词'`，
"有一格"这个条件仍然满足。**它问的是「有没有名字」，问不了「这个名字对不对」。**
⇒ 语义覆盖（`part` 助词 vs 小品词、`det` 冠形词 vs 限定词、`unknown` 留白）
  靠的是那几条注释和 code review，**这道闸背不了那个书**。
  `[[fr-dict-pipeline]]`：**闸问「有没有」，判官问「对不对」。**

═══ 🔴 闸自己的闸 ═══
这道闸靠正则从 TS 里抠对象字面量。**正则没匹配上 ⇒ 表被读成空 ⇒
"库里有、表里缺" 会把整个值域报成缺失、或者（更糟）`ko.ts` 改名之后
`ALLOW` 机制把它整个吞掉报全绿**。
⇒ 每张表都**独立声明一个最小条目数**（`MIN_KEYS`），抠不到就直接红。
  `[[expectation-must-be-declared]]`：期望值要独立声明，不能从现状推。

跑：`python3 ko/tests/test_display_labels.py`
"""
import re
import sys
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths

TS = HERE.parent.parent / "packages" / "dict-labels" / "src" / "ko.ts"

COMMON_TS = HERE.parent.parent / "packages" / "dict-labels" / "src" / "common.ts"

# (表名, 取值域的 SQL, 说明, 表里至少该有几格, 落回哪张全局表)
# 🔴 `MIN_KEYS` 是**独立声明的**下界，不是从文件里数出来的 —— 它挡的是
#    "正则抠了个空还报全绿"。数字写得比实际小一点，是为了正常增删不误报。
#
# 🔴🔴 **SQL 必须查展示层真正读的那一列。** 第一版词性那行查的是 `entry.pos_raw`，
#    而 `korean.ts` 的 entries 查询 SELECT 的是 `entry.pos` —— 两列值域完全不同
#    （`pos_raw`＝`noun`/`character`，`pos`＝`n`/`hanja`）。
#    于是我按长码写了一张 26 格的表、闸按长码查、**双方一致报全绿**，
#    而页面上每一个徽标都是空的。⇒ `[[correct-steps-can-compose-a-hole]]`：
#    **闸至少要有一条是读者口径** —— 这里的读者口径就是「展示层 SELECT 了哪一列」。
SHEETS = [
    ("KO_POS_LABELS",
     "SELECT DISTINCT pos FROM entry WHERE pos IS NOT NULL",
     "词性", 5, "POS_LABELS"),
    ("KO_RELATION_LABELS",
     "SELECT DISTINCT kind FROM sense_relation",
     "关系", 18, None),
    ("KO_CONJ_CLASS_LABELS",
     "SELECT DISTINCT conj_class FROM entry WHERE conj_class IS NOT NULL",
     "活用类", 10, None),
    ("KO_CONJ_SRC_LABELS",
     "SELECT DISTINCT conj_class_src FROM entry WHERE conj_class_src IS NOT NULL",
     "活用类来源", 2, None),
]

def parse_keys(body):
    """抠出对象字面量的键。**逐字符扫，不靠行首锚点。**

    🔴 前两版都被自己的闸逮到过，值得记下来：
      ① 裸键写成 `[A-Za-z_]\\w*` —— `KO_CONJ_CLASS_LABELS` 的键是**谚文**
         （`규칙:` `ㅂ불규칙:`），一个都匹配不上，抠到 0 格。
      ② 改好之后用 `^\\s*…` 行首锚点 —— 而全局 `POS_LABELS`
         **一行写好几个键**（`n: '名词', name: '专名', adj: '形容词',`），
         于是每行只认出第一个，26 个码报成缺 16 个。
    ⭐ 两次都是 `MIN_KEYS` / 缺项清单当场报红，没有一次静默报「全覆盖」——
      这就是那条自检存在的全部理由（`[[expectation-must-be-declared]]`）。
    """
    keys, tok, i, n = set(), [], 0, len(body)
    while i < n:
        ch = body[i]
        if ch in "'\"`":                       # 字符串字面量：整段吃掉
            q, j = ch, i + 1
            while j < n and body[j] != q:
                j += 2 if body[j] == "\\" else 1
            tok = [body[i + 1:j]]              # 引号键：内容就是键
            i = j + 1
            continue
        if ch == ":":
            s = "".join(tok).strip()
            if s:
                keys.add(s)
            tok = []
        elif ch in ",{}()[]\n":
            tok = []
        else:
            tok.append(ch)
        i += 1
    return keys


def read_sheet(src, name):
    """抠出 `export const <name>: Record<…> = { … };` 里的键。"""
    m = re.search(
        r"export const %s\s*:\s*Record<[^>]*>\s*=\s*\{" % re.escape(name), src)
    if not m:
        return None
    # 从 `{` 起做括号配平 —— 值里可能有 `}`（模板串/注释），不能贪婪到文件尾
    i = src.index("{", m.end() - 1)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                break
    else:
        return None
    body = src[i + 1:j]
    # 去掉行注释，否则 `// a: b` 会被当成一个键
    body = re.sub(r"//[^\n]*", "", body)
    return parse_keys(body)


def check():
    """→ [(级别, 表名, 说明), ...]。级别 'red' 拦，'warn' 只报。"""
    if not TS.exists():
        return [("red", str(TS), "映射表文件不在 —— 闸抠不到任何东西")]
    src = TS.read_text(encoding="utf-8")
    common = COMMON_TS.read_text(encoding="utf-8") if COMMON_TS.exists() else ""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    out = []
    try:
        for name, sql, label, min_keys, fallback in SHEETS:
            keys = read_sheet(src, name)
            # 🔴 覆盖层只放"不一样的"，所以覆盖率要算 **本层 ∪ 全局表**。
            #    只查本层 ⇒ 逼着 ko 把全局表抄一遍（`[[dict-labels-package]]` 反对的事）；
            #    只查全局表 ⇒ 看不见本层有没有覆盖对。
            base = None
            if fallback:
                base = read_sheet(common, fallback)
                if base is None:
                    out.append(("red", name,
                                "🔴 落回的全局表 `%s` 抠不到 —— **闸失效了**"
                                % fallback))
                    continue
            # ── 闸自己的闸 ──
            if keys is None:
                out.append(("red", name,
                            "🔴 正则抠不到这张表 —— **闸失效了**，"
                            "不是「值域全覆盖」。先修闸"))
                continue
            if len(keys) < min_keys:
                out.append(("red", name,
                            "🔴 只抠到 %d 格，独立声明的下界是 %d —— "
                            "多半是解析错了或表被删了一截" % (len(keys), min_keys)))
                continue
            dom = {r[0] for r in con.execute(sql)}
            covered = keys | (base or set())
            missing = sorted(dom - covered)
            extra = sorted(keys - dom)
            if missing:
                out.append(("red", name,
                            "🔴 %s 库里 %d 种，%s里都没有的 %d 个：%s\n"
                            "        ⇒ 页面上这些行的徽标会是**空的**"
                            % (label, len(dom),
                               "本层和 `%s`" % fallback if fallback else "表",
                               len(missing), missing)))
            if extra:
                out.append(("warn", name,
                            "⚠️ 表里多出（库里没有）：%s\n"
                            "        ⇒ 不影响页面，但说明写表的依据不是实测" % extra))
    finally:
        con.close()
    return out


if __name__ == "__main__":
    res = check()
    red = [r for r in res if r[0] == "red"]
    warn = [r for r in res if r[0] == "warn"]
    for _, name, why in warn:
        print("   %-24s %s" % (name, why))
    if not red:
        print("■ ko 展示层值域覆盖闸全绿 ✓（%d 张表）%s"
              % (len(SHEETS), "，%d 条警告" % len(warn) if warn else ""))
        sys.exit(0)
    print("🔴 ko 展示层值域覆盖闸：%d 条红" % len(red))
    for _, name, why in red:
        print("   %-24s %s" % (name, why))
    sys.exit(1)
