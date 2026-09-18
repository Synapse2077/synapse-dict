#!/usr/bin/env python3
"""修：关系层的**类别挂错**与**目标带残渣**。2026-09-17（界面那一轮）。

═══ 怎么发现的 ═══
用户看页面说「乱糟糟」。把 `ja` 接进 `render-dump.tsx`（导出器原来只支持六门，
**第四次**撞上同一条教训）之后，`猫`／`桜` 两页上最扎眼的两坨是：

    谚语  愛猫 青猫 青斑猫 西表山猫 海猫 大山猫 飼猫 怪猫 …（50 个，一个谚语都没有）
    派生词 … 桜蔭(おういん)会(かい) 桜(おう)雲(うん) 観桜(かんおう) 残桜(ざんおう)

**两坨都不是版面问题，是数据问题。** 拿展示层去藏它们正是
`[[aim-for-perfect-not-cheap]]` 说的那种补丁。

═══ ① 类别挂错：`proverb` 里 98.8% 不是谚语 ═══
🔴🔴 **同一个字段名，两版装的不是同一个东西。**
    en 版 `proverbs` ＝ 真谚语（`西と言えば東と言う`／`住めば都`）
    ja 版 `proverbs` ＝ **熟語**（汉字词条下「含这个字的复合词」那一节）

    我照字段名映射，`KIND = {…, "proverbs": "proverb"}` —— **en 版对了，ja 版错了**。
    这是 `[[decision-not-propagated-across-editions]]` 的镜像版本：不是一门做对其余错着，
    而是**同一行代码对一版成立、对另一版不成立**，而两版的行数闸都是绿的
    （行数闸问"收了多少"，不问"收的是不是那个东西"）。

⭐ **判据是量出来的不是猜的**，两个方向都量：
    ja 版 32,932 条：目标 ≤4 字 **94.9%**、目标含词头 **96.0%** ⇒ 复合词
    en 版    384 条：目标 ≤4 字 **9.9%**、随机 12 条逐条读**全是真谚语** ⇒ 谚语
    （不含词头那批也是熟語：词头 `は` 的熟語用汉字写成 `歯車`，形不同音相同。）
⇒ **只改 `src='ja-edition'` 的那批 → `derived`**；en 版 384 条一个字不动。
⚠️ **推翻它需要**：换一份 ja 版 dump 且其 `proverbs` 字段改了语义，
   或者有人报出 ja 版 `proverbs` 里的真谚语实例。

═══ ② 目标带残渣 ═══
`clean_target()`（生成侧）管的是「粘着的英文释义」和「整条是英文句子」，
**没管括号**。四类，每一类的判据都打在**含义**上：

    T1 振假名   `桜蔭(おういん)会(かい)` → `桜蔭会`
       🔴 判据不是"括号里是假名就剥"，是**振假名标的是汉字的读音 ⇒ 括号前必须是汉字**。
          第一版漏了这一条，当场咬到两类：
            `（お）楽しみにしています` —— `（お）` 是**可选前缀**不是注音，剥了改词形
            `+ で（は）ない`           —— `（は）` 同理
          两个都在**串首或假名之后**。加上「前接汉字」这一条，两类全部自动落在判据外。
       🔴 且**只认半角 `()`**：源头用全角 `（）` 的那几处全是可选成分，不是注音。
    T2 用法标签 `(euphemistic) 天(てん)に召(め)される` → `天に召される`
       ⚠️ 源头有一批括号**开口被截断**（`emperors) 崩御する`）—— 同一类残渣的另一种断法，
          一并剥。日语词形不可能以"小写拉丁词 + `)`"开头。
    T3 罗马字回显 `天国へ旅立つ (tengoku e tabidatsu)` → `天国へ旅立つ`（串尾才剥）
    T4 冒号     尾部冒号 117 条剥掉（`酢を乞う:` → `酢を乞う`）；
                命名空间前缀 45 条（`Thesaurus:死ぬ` → `死ぬ`、`附录:魔物` → `魔物`）；
                剥完不含任何日文字符的（`w:en`／`mul:🌠`／`Template:ja-cardinals?action=…`）整条删。

🔴 **「洗完在不在库里」不能当判据。** 我先拿它量过一轮，只有 47.1% 落库，
   逐条读发现落不进去的绝大多数是**洗对了但我们没收这个词**（`彼誰時`／`お仕置き場`／
   `泉下の客となる` 都是正经日语）。拿它当判据会把 53% 洗对的判成洗错
   —— `[[criteria-from-meaning-not-form]]`：**在不在库里是"是不是词"的形式代理**，
   而我们的词表本来就不完整。

    T5 自指     洗完等于词头本身 ⇒ 删（86 条，**本次清洗造出来的**，见 `plan()`）

═══ 🔴 有意不修的一类，明说 ═══
**目标里含空格的 3,572 条**（en 版 3,555）。这一桶是混的，一条判据管不了：
    真词条   `OTC 医薬品`／`○ 丸印`／`JAL 日航 日本航空`
    并列表   `炒る, 煎る, 熬る`（该拆成 3 个目标，不是丢）
    英文散文 `appearing in print in 1763. This derives from the way that…`
写一条"长度 >N 就丢"的判据正是 `[[criteria-narrower-than-you-think]]` 的反面教材
（`蟻の穴より堤の崩れ` 这种真谚语也很长）。⇒ **本轮只落账不动手。**
⚠️ **推翻/开工它需要**：给出能把这三类分开的判据（比如"整串没有日文字符"只覆盖英文散文
   那一类，对并列表和真词条无效），并且两个方向都量过。

跑：
    python3 -u ja/fixes/fix_relation_kind_and_targets.py
    python3 -u ja/fixes/fix_relation_kind_and_targets.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")

KANA = re.compile(r"^[ぁ-ゖァ-ヺーゝゞヽヾ]+$")
HAN = re.compile(r"[一-鿿々〆ヶ]")
JA_CHAR = re.compile(r"[ぁ-ゖァ-ヺ一-鿿々〆ヶー]")
# 串首的英文用法标签。两种断法：括号完整，或源头把开口截掉了。
LABEL_HEAD = re.compile(r"^\s*\(\s*[A-Za-z][A-Za-z ,/'’-]*\)\s*")
LABEL_HEAD_TRUNC = re.compile(r"^\s*[a-z][a-z ]*\)\s*")
# 串尾的罗马字回显 —— **只在串尾**：串中的括号可能是别的东西。
ROMAJI_TAIL = re.compile(r"\s*\(\s*[A-Za-z][A-Za-z0-9 ,.'’-]*\)\s*$")
NAMESPACE = re.compile(
    r"^(Thesaurus|Category|Appendix|Reconstruction|Template|Wiktionary|w|wikipedia|mul|附录|分类|模板)\s*:\s*",
    re.I)


def strip_ruby(s):
    """剥振假名括号：**半角 `()` ＋ 内容全假名 ＋ 紧跟在汉字之后**，三条同时成立。

    🔴 「前接汉字」这一条是判据的全部重量所在，见文件头 T1。
    """
    out = []
    i = 0
    while i < len(s):
        if s[i] == "(":
            j = s.find(")", i)
            inner = s[i + 1:j] if j > 0 else None
            if inner and KANA.match(inner) and out and HAN.match(out[-1]):
                i = j + 1
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def clean(t):
    """→ 洗干净的目标，或 None（整条不是词）。"""
    s = (t or "").strip()
    if not s:
        return None
    if NAMESPACE.match(s):
        s = NAMESPACE.sub("", s, count=1).strip()
        # 剥完没有一个日文字符 ⇒ 是维基内部链接不是词条（`w:en`／`mul:🌠`）
        if not JA_CHAR.search(s):
            return None
    s = LABEL_HEAD.sub("", s, count=1)
    s = LABEL_HEAD_TRUNC.sub("", s, count=1)
    s = ROMAJI_TAIL.sub("", s, count=1)
    s = strip_ruby(s)
    s = s.rstrip(":：").strip()
    return s or None


def plan(con):
    """→ (jobs, old)。jobs＝[(id, word_id, sense_id, 新kind, 新target)]，
    新 target 为 None 表示这一行整条不是词、该删；old[id]＝(旧kind, 旧target)。

    🔴🔴 **洗完等于词头本身 ⇒ 删。** 这 86 条不是原来就有的，是**本次清洗造出来的**：
       `死ぬ` 页的近义词里写着 `死(し)ぬ`，剥掉振假名之后正是它自己。
       「X 的近义词是 X」不是关系，是同义反复。
    ⭐ 逮到它的是回归闸的 F2「关系指向自己」，不是我 —— 我当时已经看着
       「目标残渣清零 ✅」准备收工了。**修一处造出另一处**正是回归闸存在的理由
       （`[[fix-regression-and-gate]]`）。
    """
    jobs, old = [], {}
    for rid, wid, sid, kind, tgt, src, word in con.execute(
            "SELECT r.id, r.word_id, r.sense_id, r.kind, r.target, r.src, d.word"
            " FROM sense_relation r JOIN dict d ON d.id = r.word_id"):
        nk = "derived" if (kind == "proverb" and src == "ja-edition") else kind
        nt = clean(tgt)
        if nt == word:
            nt = None
        if nk != kind or nt != tgt:
            jobs.append((rid, wid, sid, nk, nt))
            old[rid] = (kind, tgt)
    return jobs, old


def split(jobs, old, keys):
    """按 UNIQUE(word_id, sense_id, kind, target) 把 jobs 分成「改」与「删」。

    🔴 撞车的那一行是**同一条关系的重复表述**（洗完两条一模一样）⇒ 删，不是报错。
    ⚠️ 判撞车之前必须先把**要动的这些行自己的旧键**让出来 —— 否则一条只改 kind
       的行会跟"它自己"撞上，被当成重复删掉。
    """
    taken = set(keys)
    for rid, wid, sid, _nk, _nt in jobs:
        taken.discard((wid, sid, *old[rid]))
    upd, dele = [], []
    for rid, wid, sid, nk, nt in jobs:
        if nt is None:
            dele.append(rid)
            continue
        key = (wid, sid, nk, nt)
        if key in taken:
            dele.append(rid)
        else:
            taken.add(key)
            upd.append((nk, nt, rid))
    return upd, dele


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    jobs, old = plan(con)
    keys = set(con.execute(
        "SELECT word_id, sense_id, kind, target FROM sense_relation"))
    upd, dele = split(jobs, old, keys)

    st = collections.Counter()
    for rid, _wid, _sid, nk, nt in jobs:
        k, t = old[rid]
        if nk != k:
            st["① proverb → derived（仅 ja 版）"] += 1
        if nt != t:
            st["② 目标洗掉残渣" if nt is not None else "③ 整条不是词 ⇒ 删"] += 1
    print("■ 命中 %s 行" % f(len(jobs)))
    for k, v in sorted(st.items()):
        print("   %-30s %s" % (k, f(v)))
    print("   ├ UPDATE %s 行" % f(len(upd)))
    print("   └ DELETE %s 行（整条不是词 ＋ 洗完撞 UNIQUE 的重复表述）" % f(len(dele)))
    print("\n   目标改写样例：")
    shown = 0
    for nk, nt, rid in upd:
        k, t = old[rid]
        if nt != t:
            print("      %-44s → %s" % (t[:44], nt[:44]))
            shown += 1
            if shown >= 10:
                break
    con.close()

    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        return

    # ⚠️ `__rows__` 是 **`dict` 的行数**（词形总数），不是"所有表行数之和"——
    #    本步一个词形都不动，它是 0；掉的 9,324 行在 `sense_relation` 里。
    #    🔴 第一版把 `__rows__` 写成 `-len(dele)`，同时漏声明被 `TRACK` 盯着的
    #       `sense_relation.target` 列 ⇒ **写库闸当场打红并给出回滚命令**。
    #       这正是它该干的事：`[[dbtool-and-golden-tests]]`，写库前后各数一遍，
    #       **没声明的变化一律当成"改到了不该改的地方"**。
    with dbtool.session("ja-rel-cleanup", expect={
            "__rows__": 0,
            "#sense_relation": -len(dele),
            "sense_relation.target": -len(dele),
            "#dict": 0, "#entry": 0, "#sense": 0, "#sense_gloss": 0,
            "#example": 0, "#example_gloss": 0, "#inflection": 0,
            "#pronunciation": 0, "#audio": 0}) as con:
        con.executemany(
            "UPDATE sense_relation SET kind=?, target=? WHERE id=?", upd)
        con.executemany("DELETE FROM sense_relation WHERE id=?",
                        [(r,) for r in dele])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left_p = con.execute("SELECT count(*) FROM sense_relation"
                         " WHERE kind='proverb' AND src='ja-edition'").fetchone()[0]
    keep_p = con.execute("SELECT count(*) FROM sense_relation"
                         " WHERE kind='proverb' AND src='en-edition'").fetchone()[0]
    left_t = sum(1 for (t,) in con.execute("SELECT target FROM sense_relation")
                 if clean(t) != t)
    self_ref = con.execute(
        "SELECT count(*) FROM sense_relation r JOIN dict d ON d.id = r.word_id"
        " WHERE d.word = r.target").fetchone()[0]
    print("\n   %s ja 版 proverb 清零（剩 %d）" % ("✅" if left_p == 0 else "🔴", left_p))
    # 🔴 这一条**不该是 0**：只看上面那条，会把「把两版一起删光」当成修得很干净
    #    （`fix_traditional_to_simplified` 的 A5/A6 是同一个形状：单看一条会反过来）。
    # ⚠️ 判据是「还在不在」不是「还是不是 384 条」—— 写死条数的断言必然过期
    #    （字面量闸 `test_no_literal_counts.py` 就是为这个建的）。
    print("   %s en 版真谚语没被误伤（%s 条，**不该是 0**）"
          % ("✅" if keep_p else "🔴", f(keep_p)))
    print("   %s 目标残渣清零（剩 %d）" % ("✅" if left_t == 0 else "🔴", left_t))
    print("   %s 没有指向自己的关系（剩 %d）" % ("✅" if self_ref == 0 else "🔴", self_ref))
    con.close()
    if left_p or not keep_p or left_t or self_ref:
        _sys.exit(1)


if __name__ == "__main__":
    main()
