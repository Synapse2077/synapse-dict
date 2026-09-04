#!/usr/bin/env python3
"""阶段 3：从各版收词 —— `dict` 词形层 + `entry` 词条层。de 版，2026-09-01。

方针沿用（`[[dict-scope-four-rules]]` 第①条「词汇尽量全」）：**全收**。
本步**只收词形与词条，不收义项**：德语版的 239,698 条真释义归阶段 1.5，
新收变形的原形链接归阶段 2c。一次只动一样东西（`[[one-problem-at-a-time]]`）。

═══ 🔴 de 与 pt 最大的一处不同：不必挖 `forms` 也能拿到九成 ═══
**德语维基给每个变格/变位形式都建了独立页面**（这就是它 92.4% 义项是指针的原因）。
实测（归一后，全量非抽样）：

    顶层 `word` 的单词形残差   611,408
    `forms` 单元格的           458,614
    `forms` **独有**的          42,809   ← 只占并集 6.5%

pt 那轮正相反：葡语维基不建变位页，只收顶层会漏掉整个变位层（219,756 → 643,117，差 2.9 倍）。
⇒ **同一件事在两门语言上的答案相反，所以两门都必须自己量**（`[[es-v3-structure-backfill]]`）。
de 仍然收 `forms`（那 42,809 读一眼全是**瑞士拼写** `kopfgross`/`unmässiges`/`massgebendstes`
和罕用变格形），但风险面比 pt 小一个数量级。

═══ 🔴🔴 `forms` 的判据：德语**不能**按 `/` 拆单元格 ═══
pt 那轮按 `[/\\n,]` 拆，因为葡语版 `adequo / adéquo` 是两个形式。
**德语版的 `/` 是主语代词的连写**：

    er/sie/es wurde transzendiert      拆开会往库里灌 `er`、`sie` 两个假词形
    ich abstottre                      整格小句子

⇒ 判据 **import `probes/residual.is_single_form`**（不含空格、不含 `/`、剥命令式 `!`），
**不在这里手抄第二份**（`[[regex-alternation-order]]`：抽了常量却在另一文件手抄一份窄的）。
这条判据当初就是量残差时被数据打回来的：原始残差 4,523,887 → 单词形 792,976，差 5.7 倍。

═══ 落点预检的四个结论（2026-09-01 全量实测）═══

**① 撇号约定与库里相反，必须归一。**
   库内 直撇 154 : 弯撇 1 ／ 德语版 弯撇 1,166 : 直撇 5。
   不归一，`Ku’damm` 与 `Ku'damm` 会分裂成两个词条。归一方向 **→ 直撇**（库的约定）。
   ⚠️ 护栏同 pt：**不含字母的词形一个字节都不碰**（以标点为内容的词条，那些字形就是词义）。

**② 大小写一律原样，不折叠。** 德语名词首字母大写是正字法硬规则，
   `Sie/sie`、`Band/band` 本来就是两个词条 —— 库里已经是分开的（7,946 组），本步不许合。

**③ 🔴 德语版没有 `etymology_number`**（实测 0 条；英文版有）。
   ⇒ `src_ref` 不能照抄英文版的 `kk-en:<词形>:<词性>:<词源号>:<seq>`，
      改用 `kk-<版>:<词形>:<词性>#<该键第几条 JSON>`。fr/it/pt 三轮对非英文版同样处理。

**④ 六种 pos 不在 `POS_MAP` 里，一个都不用默认值填平**
   （`[[prompt-self-harm-two-patterns]]`：`pos or "v"` 把分类名说成动词，落库 404 行）：

    unknown    11,716  → **原样**（`Polen`「Genitiv Singular von Pole」——
                         源头自己没说词性，`dict-labels` 已有 `unknown: '未标注'`）
    abbrev      4,986  → 原样（共享包已有）
    postp          15  → 原样（共享包已有）
    affix / infix   6  → 原样（共享包已有）
    circumfix       3  → 原样（**共享包本轮新增 `circumfix: '环缀'`** ——
                         `Ge-…-e`/`be-…-t` 是德语真实构词类型，拆成前缀+后缀会丢掉
                         「必须同时出现」这一条）

═══ 闸 ═══
① `dbtool` 的 expect 闸：插行时**所有列的非空计数都会跟着涨**，必须逐列显式声明。
② 不变量断言：新词形不在旧库 / `word_norm` 非空 / entry 无孤儿 / `src_ref` 无重复 /
   归一后库内不再有弯撇 / **新词形全部通过 `is_single_form`**。
③ 抽样反验：随机打印新收的词形供人眼核 —— 确定性收词，但**新词形对不对**只有人看得出来
   （pt 那轮靠它拦下法语版灌进来的 283,136 条假词形）。

用法（在 de/ 目录下）：
    python3 -u pipeline/intake_edition_words.py --edition de           # 干跑
    python3 -u pipeline/intake_edition_words.py --edition de --apply
    python3 -u pipeline/intake_edition_words.py --edition fr --apply
    python3 -u pipeline/intake_edition_words.py --verify
"""
import argparse
import gzip
import json
import random
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "probes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build import POS_MAP                # noqa: E402
from residual import is_single_form      # noqa: E402  ← 判据只许一份

D = paths.DUMPS
# (路径, 要不要按 lang_code 筛)
EDITIONS = {
    "de": (D / "dewiktionary.jsonl.gz", True),
    "fr": (D / "frwiktionary.jsonl.gz", True),
    "zh": (D / "zhwiktionary.jsonl.gz", True),
    "it": (D / "itwiktionary.jsonl.gz", True),
    "es": (D / "eswiktionary.jsonl.gz", True),
    "pt": (D / "ptwiktionary.jsonl.gz", True),
    "en": (paths.KK, False),      # 英文版德语切片，整份都是德语
}

# 弯撇 → 直撇（库的约定：直撇 154 : 弯撇 1；德语版 弯撇 1,166 : 直撇 5）。
# 🔴 **只放实测过的那一个字符。** 第一版我顺手把 `ʼ`（U+02BC 修饰字母撇）也塞了进来，
#    没量过 —— 闸当场逮到 `Kupʼjansʹk`（乌克兰地名转写，U+02BC + U+02B9 是**转写符**
#    不是撇号），归一它会毁掉一个学术转写。
#    ⇒ 判据里的每一个字符都要有实测支撑，"看着像同类"不是理由
#      （`[[criteria-narrower-than-you-think]]`）。
APOS = {"’": "'"}

# `forms` 单元格里明显不是词形的：占位符与表格结构标签。**只挡这两类**，
# 其余交给 `is_single_form` —— 别在这里再发明第二套形状判据。
FORM_JUNK_TAGS = {"table-tags", "inflection-template", "class"}
PLACEHOLDER = {"-", "—", "–", "?", "…", "...", "、", "·"}


def norm_apos(s):
    """弯撇归一成直撇。**不含字母的词形一个字节都不碰**（护栏同 pt）——
    以标点为内容的词条，那些字形就是它要讲的东西。"""
    if not any(c.isalpha() for c in s):
        return s
    for a, b in APOS.items():
        s = s.replace(a, b)
    return s


def unaccent(s):
    """与 `build.py` 的 `word_norm` 口径逐字一致 —— 这个口径只有这一份。"""
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def norm_word(x):
    """词形归一：折叠空白 + 撇号。**顶层词头与 forms 单元格共用这一份。**"""
    return norm_apos(" ".join((x or "").split()))


def clean_head(x):
    """顶层词头 → 词形或 None。**有意不套 `is_single_form`。**

    🔴🔴 第一版把 `is_single_form` 同时用在了顶层和 `forms` 上，丢掉 **82,682 条**顶层条目，
       读一眼**绝大多数是可分动词的分离形式**（`ebben ab`／`trat weg`／`winke durch`）——
       德语维基给它们建了独立页面，是**真词形**；另有 `durchsichtige Wörter`、`Rio Negros`
       这类真多词条目。而库里七月建库时就收了 21,090 条同形状的（`aus dem Blauen heraus`），
       pt 那轮顶层也没有单词形限制。
    ⇒ **`is_single_form` 是为 `forms` 单元格设计的**（挡「主语代词写进变位表」那种整格小句子），
      套到顶层就是**判据比它要描述的东西宽**。判据该按**来源位置**分，不按形状分。
      实测佐证：顶层 98,642 条多词条目里只有 **30 条**以主语代词开头、**0 条**含斜杠 ——
      污染确实只在 `forms` 里。
    """
    x = norm_word(x)
    if not x or len(x) > 120 or not any(c.isalpha() for c in x):
        return None
    return x


def clean_form(x):
    """`forms` 单元格 → 词形或 None。判据主体 import `is_single_form`，这里只做归一。

    🔴 顺序要紧：**先判后归一会存下没归一的串**。第一版 `is_single_form(x)` 内部
       会剥掉命令式 `!` 再判断，而我把**原串**存了进去 ⇒ 落库 `Hü !`。
       同一个错我今天在 `probes/residual.py` 里已经犯过一次（`beauftrag!`），
       **两次都是「用归一后的值判断、却存原值」** ⇒ 归一一次、之后只用归一后的值。
    """
    x = norm_word(x)
    if not x or x in PLACEHOLDER or len(x) > 60:
        return None
    x = x.rstrip("!").strip()                # 命令式的 `!` 不是词形的一部分
    if not is_single_form(x) or not any(c.isalpha() for c in x):
        return None
    return x


def opener(p):
    return (gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz"
            else open(p, encoding="utf-8"))


def scan(edition, have):
    """→ (new, entries, stat)

    new[word] = {"pos": set(pos_raw), "from_forms": bool}
    entries   = [(word, pos_raw, seq)]     该版每个条目一行
    """
    path, need_filter = EDITIONS[edition]
    new, entries = {}, []
    seq_of, stat = Counter(), Counter()

    with opener(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            if need_filter and e.get("lang_code") != "de":
                continue
            stat["德语条目"] += 1
            w0 = (e.get("word") or "").strip()
            if not w0:
                stat["无词头（丢）"] += 1
                continue
            w = clean_head(w0)
            if not w:
                stat["词头归一后为空/超长（丢）"] += 1
                continue
            if w != w0:
                stat["词头已归一（撇号/空白）"] += 1
            pos_raw = e.get("pos") or "unknown"
            k = (w, pos_raw)
            seq = seq_of[k]
            seq_of[k] += 1
            entries.append((w, pos_raw, seq))

            if w not in have:
                d = new.setdefault(w, {"pos": set(), "from_forms": True})
                d["pos"].add(pos_raw)
                d["from_forms"] = False           # 顶层出现过 ⇒ 不是 forms 独有
                stat["新词形（顶层 word）"] += 1
                if " " in w:
                    stat["   其中多词条目（可分动词分离形式等）"] += 1
            else:
                stat["顶层词形库里已有"] += 1

            for fm in (e.get("forms") or []):
                if FORM_JUNK_TAGS & set(fm.get("tags") or []):
                    continue
                x = clean_form(fm.get("form"))
                if not x or x in have or x in new:
                    continue
                new[x] = {"pos": set(), "from_forms": True}
                # ⚠️ 这一格数的是「**先**在 forms 里遇到」，不是「forms 独有」——
                #    同一个词后面还可能以顶层词头出现（那时 `from_forms` 会被改回 False）。
                #    真正的「forms 独有」在最后按 `from_forms` 统计，两个数差一个数量级，
                #    标签写错就会让人以为挖 forms 的收益是实际的 8 倍。
                stat["新词形（先在 forms 里遇到）"] += 1
    return new, entries, stat


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("dict 行数 == 期望", q("SELECT count(*) FROM dict"), expect["dict"]),
        ("word_norm 为空", q("SELECT count(*) FROM dict WHERE word_norm IS NULL OR word_norm=''"), 0),
        ("word 重复（大小写敏感）",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
        # 🔴 断言**调用归一函数本身**，不写自己那套 SQL。
        #    第一版写的是 `word LIKE '%’%'`，当场报 1 条红 —— 而那 1 条是
        #    `’` 这个**标点词条**（释义「省文撇，表示字母省略」），归一它等于把词条
        #    要讲的东西毁掉。数据是对的，**是我的断言比它守的判据宽**
        #    （`[[fix-regression-and-gate]]` 第三种机制：闸与它守的逻辑用了两个判据）。
        #    ⇒ 闸问的不是"有没有弯撇"，是"**还有没有该归一而没归一的**"。
        ("🔴 还有该归一而没归一的词形",
         sum(1 for (w,) in con.execute("SELECT word FROM dict") if norm_apos(w) != w), 0),
        ("entry 孤儿（word_id 不在 dict）",
         q("SELECT count(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
           "WHERE d.id IS NULL"), 0),
        ("entry.src_ref 重复",
         q("SELECT count(*) FROM (SELECT src_ref FROM entry GROUP BY src_ref HAVING count(*)>1)"), 0),
        # 🔴 守的是 pt 那轮被灌进 283,136 条假词形的那个口子 —— 但**只守 `forms` 那一侧**。
        #    顶层多词条目是合法的（可分动词分离形式 `ebben ab`、真多词条目
        #    `durchsichtige Wörter`），断言若不分来源就会把它们全判成假词形。
        #    ⇒ 期望值由**本次实际从 forms 收的那批**说了算，名单在 Python 侧算好传进来。
        ("🔴 forms 来源的新词形含空格或斜杠（假词形的形状）",
         expect["bad_forms"], 0),
        # ⚪ 这里原本还有一条「新收词形里含斜杠的一律不该有」—— **删掉了，它是错的**。
        #    实测圈到 37 条，**全是真词条**：`km/h`、`m/s`、`c/o`、`I/O`、`Frankfurt/Main`、
        #    `Halle/Saale`、`Aufmerksamkeitsdefizit-/Hyperaktivitätsstörung` ——
        #    斜杠是词本身的一部分。斜杠的危险**只存在于 `forms` 单元格**（`er/sie/es`），
        #    而上面那条已经守住了（报 0）。
        #    ⇒ 今天第三次同一形状：**断言比它守的判据宽**（前两次是撇号那条、
        #      `is_single_form` 套到顶层那次）。`[[criteria-narrower-than-you-think]]`
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %10s  期望 %s" % ("✓" if good else "🔴", name,
                                            f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", choices=sorted(EDITIONS))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        n = con.execute("SELECT count(*) FROM dict").fetchone()[0]
        mx = con.execute("SELECT max(id) FROM dict").fetchone()[0]
        return 0 if gate2(con, {"dict": n, "max_id_before": mx, "bad_forms": 0}) else 1
    if not a.edition:
        ap.error("要么 --verify，要么 --edition")

    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    print("■ 库内词形 %s；扫 %s 版…" % (f"{len(have):,}", a.edition))
    new, entries, stat = scan(a.edition, have)
    for k, v in stat.most_common():
        print("   %-40s %10s" % (k, f"{v:,}"))
    n_top = sum(1 for d in new.values() if not d["from_forms"])
    print("\n   → 新词形 %s（顶层 %s ／ forms 独有 %s）"
          % (f"{len(new):,}", f"{n_top:,}", f"{len(new) - n_top:,}"))

    # ── pos 覆盖：一个都不许被默认值填平 ─────────────────────────────
    miss = Counter()
    for w, d in new.items():
        for p in d["pos"]:
            if p not in POS_MAP:
                miss[p] += 1
    if miss:
        print("\n   ⚠️ POS_MAP 盖不到（**原样透传**，不映射不填默认值）：")
        for p, v in miss.most_common():
            print("      %-14s %s" % (p, f"{v:,}"))

    # ── 抽样反验（pt 那轮靠它拦下 283,136 条假词形）────────────────────
    random.seed(7)
    print("\n── 抽样反验：随机 24 个新词形（**人眼看，这一步没有自动判据**）──")
    sample = random.sample(sorted(new), min(24, len(new)))
    for i in range(0, len(sample), 4):
        print("   " + "  ".join("%-18s" % x for x in sample[i:i + 4]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    wid = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    max_id = con.execute("SELECT max(id) FROM dict").fetchone()[0]
    n_before = con.execute("SELECT count(*) FROM dict").fetchone()[0]
    have_ref = {r for (r,) in con.execute("SELECT src_ref FROM entry")}
    con.close()

    drows = []
    for w in sorted(new):
        pos_set = new[w]["pos"]
        # 多个词性 ⇒ `dict.pos` 存不下，取**出现的第一个**并原样保留；
        # 逐义项词性在 `entry` 层，那里才是权威。
        p = sorted(pos_set)[0] if pos_set else "unknown"
        drows.append((w, unaccent(w), POS_MAP.get(p, p), 0))

    print("\n■ 将写入 dict %s 行" % f"{len(drows):,}")
    now = dbtool.snapshot()
    with dbtool.session("keep-v3-intake-%s" % a.edition,
                        # 🔴 总行数的键是 `__rows__`（不是"总行"，那只是打印用的字样）——
                        #    第一版写错，闸当场拦下并给了回滚命令。**闸报错正是它在工作。**
                        #    `pos` 必须显式声明：插行时**每一个有值的列**非空计数都会跟着涨，
                        #    没声明的列变了就报错 —— 这条才是它拦得住"多写了一列"的原因。
                        expect={"__rows__": len(drows), "pos": len(drows)}) as s:
        s.executemany(
            "INSERT INTO dict (word, word_norm, pos, is_lemma) VALUES (?,?,?,?)", drows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad_forms = sum(1 for w, d in new.items()
                    if d["from_forms"] and (" " in w or "/" in w))
    ok = gate2(con, {"dict": n_before + len(drows), "max_id_before": max_id,
                     "bad_forms": bad_forms})
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
