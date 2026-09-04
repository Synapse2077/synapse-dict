#!/usr/bin/env python3
"""阶段 1：建 `entry` 词条层与 `sense_src` 证据层，把每条义项锚回 dump。2026-08-31。

设计见 `docs/SCHEMA.md` §10，计划见 `docs/DE_PLAN.md` 阶段 1。
本文件是 `pt/pipeline/build_entry_layer.py` 的德语版。**一次扫描产出三样东西**：

    复刻 build.py 生成 `definition` 的循环
      → 每条义项来自哪个 entry           （entry 层）
      → 每条义项在 dump 里的原文与坐标     （sense_src 证据层）
      → 每个 entry 自己的德语一等字段      （🔴 pt/fr 那两版没做这一步，见下 ③）

═══ 复刻的是哪条规则（读自 `de/pipeline/build.py:385-475`）═══
遍历 `lang_code=='de'` 的 dump entry（**文件顺序**）→ 每个 entry 的 senses（顺序）→
  · `fo = form_of or alt_of`，且该词非词缀 ⇒ 变形指针，进 `infl`，**不算义项**
  · 否则 `g = re.sub(r"\\s+"," ", glosses[0]).strip()`；`g` 为空或**已见过**则跳过
  · 已见过 = `rec["real_seen"]`，按 **`key = word`** 累积
⇒ 给定同一份 dump，输出逐字节可复现。

═══ 🔴 de 与 pt 的四处不同 —— 逐条量过，不是照搬 ═══

① 🔴🔴 **`build.py:394` 的键是 `key = word`，德语不折叠大小写。**
   pt/fr 那两版用 `word.lower()`，各吃掉 1,627 / 3,776 个词形，复刻时必须把折叠也复刻一遍。
   **de 没有这一步** —— 德语名词首字母大写是正字法硬规则（`Sie`/`sie`、`Band`/`band`
   是不同的词），当年就没折。⇒ 本脚本**不许**照抄那段折叠代码；
   相反，`word_src == dict.word` 成了一条可断言的不变量（闸②）。
   ⚠️ 这也意味着 **de 不需要 pt 的阶段 3a「拆开大小写折叠」**。

② **义项去重的作用域是「同一个词形」跨全部词性**（`real_seen` 挂在 `rec` 上）。
   所以同一个词的 noun 和 verb 若有逐字相同的英文释义，**第二个会被吃掉**。
   这不是缺陷，是当年的行为；本步照复刻，实际吃掉多少由试算打印。

③ ⭐ **德语一等字段本步就填进 `entry`，并逐字节回核** —— pt 那版只建列不填。
   能这么做是因为 `build.py` 的 `extract_noun/extract_verb/extract_adj` 是**纯函数**，
   本脚本**直接 import 它们**，不手抄（`[[regex-alternation-order]]`：
   抽了常量却在另一文件又手抄一份窄的，坏了 43 条）。
   ⇒ 闸①因此多出一半：从 `entry` 按 build.py 的「取第一个非空」规则重建 `dict` 的
   **13 列**德语字段，与原列逐字节比对。这是 pt/fr 都没有的一道回核。

④ **`etym_no`**：kaikki 的 `etymology_number` 可能缺失，缺就记 `"0"`。
   词形自带冒号的情况：de 实测由试算打印；`src_ref` 解析一律 `rsplit(":", 3)`。

═══ 🔴 本步会量出、但**不在本步修**的缺陷 ═══
`build.py:450` 写的是 `fo = s.get("form_of") or s.get("alt_of")` ——
**把 `alt_of` 和 `form_of` 一起当变形丢了**。可 `alt_of` 是异体/缩写/误拼，
它们是**独立词条、有自己的释义**（fr 5,011 / it 7,028 / es 5,701 / pt 8,008 —— **四门全中**）。
⚠️ 本步的任务是**忠实复刻当年的行为**，好让闸①能逐字节回核。修复归阶段 2。
   本脚本把这批义项**照样写进 `sense_src` 证据层**（`sense_id` 留空），
   阶段 2 直接从证据层捞，不用再扫一遍 dump。

═══ 🔴🔴 判据被数据打回两次（2026-08-31，第一版闸①两半全红）═══

**第一版写的是「逐字节全等」，而那条判据假设了两件不成立的事：**

① **假设「dump 是稳定工件」——不成立。** 建库主源七月被清掉，今天重下回来的是
   **新版本**。上游改过：143 个词条的释义文本被改写（`Dorn` 'bolt (with plural Dorne)'
   → 'bolt'）、9 个词条不再产生义项（`fürs`/`ums`/`ins`/`hinters` 这些介词+冠词缩合形式
   上游改成了纯指针）、370 个词条是新增的。
   ⭐ **但锚定率 99.88%**（116,554 / 116,694 条义项逐字节找得到）。
   ⇒ 判据改成：**能锚上的必须逐字节一致 + 锚不上的必须全部落进已分类的四类**
     （未分类必须为 0），外加一条漂移率上限。
   ⚠️ 这动摇了 `PLAYBOOK` 七节「锚外部 dump 的闸永不过期」那句话的前提 ——
     **kaikki 会重新生成 dump**。外锚闸仍然比自比闸强得多，但它锚的是"当前上游"，
     不是"一份不变的真值"。已记进 `DE_PLAN` 收尾单。

② **假设「dict 的德语字段全部来自 build.py」——不成立。**
   `de/pipeline/b_translate.py`（七月的豆包流水线）**给这些列补过空**
   （`if not c_cmp: sets.append("comparative=?")` —— 只填空、不覆盖，冲突另记）。
   实测**约 21,000 个字段值是豆包补的**（comparative 6,205／plural 9,009／genitive 3,711／
   gender 758／aux 304／praeteritum 306／partizip2 300／separable 232），
   而且已知含错（`in` → `iner`／`am insten`）。
   ⇒ 判据改成：**kaikki 有值 ⇒ dict 必须等于它**；「dict 有值而 kaikki 无」是**豆包补空层**，
     计数记账，不算错。这正是 `ipa_src`/`gender_src` 两列当初该记的东西
     （`[[ipa-provenance-columns]]`：证明不了就写 unknown）。

═══ 三道闸 ═══
① **可逆性回核**（两半，都是 100% 非抽样）：
   (a) 义项序列：能锚上的逐字节一致；锚不上的全部归类，未分类必须为 0
   (b) 德语 13 列：kaikki 有值处必须与 dict 逐字节一致；两边都有值而不同的 ≤ 上限
② 不变量断言：每条 sense 恰好一条 en 侧 sense_src / entry 无孤儿 / src_ref 无重复 /
   **`word_src` == `dict.word`**（de 特有，见 ①）
③ 抽样：确定性复刻，无判断成分，不适用。

用法（在 de/ 目录下）：
    python3 pipeline/build_entry_layer.py            # 试算 + 闸①，不写库
    python3 pipeline/build_entry_layer.py --apply    # 建表并写入
    python3 pipeline/build_entry_layer.py --mutate   # 变异验证：闸必须报出人为破坏
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402
# 🔴 判据只许一份：直接 import 建库用的那几个纯函数，不手抄
from pipeline.build import (POS_MAP, extract_noun, extract_verb, extract_adj,   # noqa: E402
                            compose_noun_variants, meta_of_sense)

SRC = "en-edition"
AFFIX_POS = {"suffix", "prefix", "infix", "interfix"}   # 与 build.py:408 逐字一致

DDL_ENTRY = """CREATE TABLE entry (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id  INTEGER NOT NULL,        -- → dict.id
  word_src TEXT NOT NULL,           -- dump 里的真实拼写；🔴 德语不折叠 ⇒ 恒等于 dict.word
  pos      TEXT NOT NULL,           -- POS_MAP 映射后的展示值
  pos_raw  TEXT NOT NULL,           -- dump 原始词性；phrase/prep_phrase 都映射成 phr，主键用它
  etym_no  TEXT NOT NULL,           -- 词源号；源头可能是 "1.1" 这种串，没编号记 "0"
  seq      INTEGER NOT NULL,        -- 同键内序号，正常 0
  -- ── 德语一等字段（`docs/lang/de-DESIGN.md` §0），**本步就填**──
  gender      TEXT,                 -- m|f|n|mf（三性 der/die/das）
  genitive    TEXT,                 -- 属格单数
  plural      TEXT,                 -- 复数
  aux         TEXT,                 -- haben|sein|both
  praeteritum TEXT,
  partizip2   TEXT,
  vclass      TEXT,                 -- strong|weak|mixed
  separable   INTEGER,
  sep_prefix  TEXT,
  reflexive   INTEGER,
  comparative TEXT,
  superlative TEXT,
  src      TEXT NOT NULL,           -- 行级来源（照 it 不照 es：全收之后分不清就再也分不清了）
  src_ref  TEXT NOT NULL,           -- kk-en:<word_src>:<pos_raw>:<etym_no>:<seq>
                                    -- 🔴 解析一律 rsplit(":",3)
  UNIQUE(src_ref)
)"""
IDX_ENTRY = ["CREATE INDEX idx_entry_word ON entry(word_id)",
             "CREATE INDEX idx_entry_wordsrc ON entry(word_src)"]

# 从 entry 重建 dict 的这些列（build.py 的规则一律是「取第一个非空」）
FIRST_WINS = ["gender", "genitive", "plural", "aux", "praeteritum", "partizip2",
              "vclass", "sep_prefix", "comparative", "superlative"]
FLAGS = ["separable", "reflexive"]      # 任一 entry 为真则为 1，否则 NULL


def scan():
    """复刻 build.py 的循环 → (entries, senses_by_word, src_rows, stat)

    entries:        [(word, pos_raw, etym_no, seq, 一等字段 dict)]，文件顺序
    senses_by_word: {word: [(gloss, meta, entry_idx, sense_idx)]}  去重后的义项序列
    src_rows:       [(word, entry_idx, sense_idx, kind, gloss, tags, targets)]  证据层（含 alt_of）
                    🔴 `targets` 只有 `kind=="alt_of"` 时非空 —— 阶段 2a 拼中文要用它
                    （`alt_of` 数组里的目标词）。**判据只许一份**：2a 不许自己再扫一遍 dump
                    去认「哪条是 alt_of」，它 import 本函数。
    """
    entries, src_rows = [], []
    senses_by_word = defaultdict(list)
    seen_gloss = defaultdict(set)          # word → 已见过的 gloss（复刻 rec["real_seen"]）
    key_seq = Counter()                    # (word,pos_raw,etym_no) → 已出现次数 ⇒ seq
    noun_forms = defaultdict(lambda: defaultdict(list))   # word → gender → [(gen,pl)]
    stat = Counter()

    with open(paths.KK, encoding="utf-8") as f:
        for line in f:
            stat["dump 行"] += 1
            try:
                e = json.loads(line)
            except Exception:
                stat["解析失败"] += 1
                continue
            if e.get("lang_code") != "de":
                continue
            word = (e.get("word") or "").strip()
            if not word:
                stat["无词头（丢）"] += 1
                continue
            pos_raw = e.get("pos", "")
            etym_no = str(e.get("etymology_number") or "0")
            k = (word, pos_raw, etym_no)
            seq = key_seq[k]
            key_seq[k] += 1
            if seq:
                stat["🔴 同键重复（seq>0）"] += 1
            if ":" in word:
                stat["⚠️ 词形自带冒号"] += 1

            senses = e.get("senses", []) or []
            is_affix = pos_raw in AFFIX_POS

            # —— 德语一等字段：**import build.py 的纯函数**，不手抄 ——
            f1 = {}
            if pos_raw in ("noun", "name"):
                g, gen, pl = extract_noun(e, word, senses)
                f1 = {"gender": g or None, "genitive": gen or None, "plural": pl or None}
                if g and pos_raw == "noun":
                    for gg in g.split("/"):
                        noun_forms[word][gg].append((gen, pl))
            elif pos_raw == "verb":
                aux, praet, pp2, vclass, sep_prefix, refl = extract_verb(e, word, senses)
                f1 = {"aux": aux or None, "praeteritum": praet or None,
                      "partizip2": pp2 or None, "vclass": vclass or None,
                      "sep_prefix": sep_prefix or None,
                      "separable": 1 if sep_prefix else None,
                      "reflexive": 1 if refl else None}
            elif pos_raw == "adj":
                comp, sup = extract_adj(e, word)
                f1 = {"comparative": comp or None, "superlative": sup or None}

            ei = len(entries)
            entries.append((word, pos_raw, etym_no, seq, f1))

            for si, s in enumerate(senses):
                fo = s.get("form_of") or s.get("alt_of")
                is_infl_sense = bool(fo) and not is_affix
                if is_infl_sense:
                    # 🔴 alt_of 被当变形一起丢掉了（四门全中）—— 证据层照收，阶段 2 再捞
                    if s.get("alt_of") and not s.get("form_of"):
                        g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
                        src_rows.append((
                            word, ei, si, "alt_of", g, s.get("tags") or [],
                            [(t.get("word") or "").strip()
                             for t in (s.get("alt_of") or [])]))
                        stat["🔴 alt_of 义项（当年被当变形丢了，证据层收下）"] += 1
                    else:
                        stat["变形指针义项（form_of）"] += 1
                    continue
                g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
                if not g:
                    stat["空 gloss（丢）"] += 1
                    continue
                if g in seen_gloss[word]:
                    stat["同词形内重复 gloss（丢）"] += 1
                    src_rows.append((word, ei, si, "dup", g, s.get("tags") or [], []))
                    continue
                seen_gloss[word].add(g)
                senses_by_word[word].append((g, meta_of_sense(s, pos_raw), ei, si))
                src_rows.append((word, ei, si, "sense", g, s.get("tags") or [], []))
                stat["义项"] += 1
    stat["entry"] = len(entries)
    stat["词形"] = len(senses_by_word)
    return entries, senses_by_word, src_rows, noun_forms, stat


# ════════════════════════ 闸① 可逆性回核 ════════════════════════

# 漂移预算：上游 dump 换版必然带来一些锚不上的义项。**写成"上限"而不是写死行数**
# —— `tests/test_no_literal_counts.py` 禁止把期望值写成行数字面量，而这本来就是个阈值。


def classify(con, senses_by_word):
    """→ (分类计数, 未锚义项数, 库内义项总数, 样本)。判据只在这里写一份，闸与诊断共用。"""
    have = defaultdict(list)
    q = ("SELECT d.word, s.rank, g.text FROM sense s "
         " JOIN dict d ON d.id=s.word_id "
         " JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' AND g.kind='equivalent' "
         "ORDER BY d.word, s.rank")
    for w, rank, text in con.execute(q):
        have[w].append(text)
    mine = {w: [g for g, _, _, _ in v] for w, v in senses_by_word.items()}
    c, unanchored, samples = Counter(), 0, defaultdict(list)
    samples["per_word"] = {}          # 词形 → 落进哪个桶（基线就是这张表）
    for w in set(have) | set(mine):
        a, b = have.get(w, []), mine.get(w, [])
        if a == b:
            c["逐字节相同"] += 1
            continue
        if not b:
            c["🔴 库里有、新 dump 不再产生义项"] += 1
            samples["per_word"][w] = "不再产生义项"
            unanchored += len(a)
            if len(samples["gone"]) < 4:
                samples["gone"].append((w, a[:1]))
        elif not a:
            c["上游新增词条（库里没有）"] += 1
            samples["per_word"][w] = "上游新增"
        elif set(a) == set(b):
            c["同一批义项、只是顺序变了"] += 1
            samples["per_word"][w] = "顺序变了"
        else:
            c["🔴 上游改写了释义文本/条数"] += 1
            samples["per_word"][w] = "上游改写"
            unanchored += len(set(a) - set(b))
            if len(samples["drift"]) < 4:
                samples["drift"].append((w, sorted(set(a) - set(b))[:1],
                                         sorted(set(b) - set(a))[:1]))
    return c, unanchored, sum(len(v) for v in have.values()), samples


BASELINE = Path(__file__).resolve().parent.parent / "tests" / "dump_drift_baseline.txt"


def gate1a(con, senses_by_word, rebaseline=False):
    """(a) 义项序列：**锁漂移清单**（不是锁比率）。

    🔴🔴 **第一版锁的是"漂移率 ≤ 1%"，变异当场证明它是瞎的**：
       把一个词的义项顺序倒过来，率只动 1e-5，闸一声不吭。
       `[[criteria-narrower-than-you-think]]` 的老形状 —— 判据比它要描述的东西宽。
       ⇒ 改成把**每一个对不上的词形逐条记进基线文件**，与本次结果做集合比较：
         多一个、少一个、换个桶，全都当场红。
       上游哪天再发新版，这道闸会红 —— 那是**对的**：换基线必须是一次有意的动作
       （`--rebaseline`），不是静默接受。
    """
    print("\n═══ 闸①(a) 义项序列回核（全量，非抽样）═══")
    c, unanchored, total, samples = classify(con, senses_by_word)
    for k, v in c.most_common():
        print("   %-38s %8s" % (k, f"{v:,}"))
    print("   库内义项 %s ／ **锚定 %s（%.2f%%）** ／ 锚不上 %s"
          % (f"{total:,}", f"{total - unanchored:,}",
             100 * (1 - unanchored / max(total, 1)), f"{unanchored:,}"))
    for w, a in samples["gone"]:
        print("   [不再产生义项] %-22s 库=%s" % (w, a))
    for w, a, b in samples["drift"]:
        print("   [上游改写]     %-22s 库=%s → 新=%s" % (w, a, b))

    now = sorted("%s\t%s" % (w, b) for w, b in samples["per_word"].items())
    if rebaseline:
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text("\n".join(now) + "\n", encoding="utf-8")
        print("   ⚠️ 已重写基线 %s（%s 条）—— 这必须是一次**有意**的动作"
              % (BASELINE.name, f"{len(now):,}"))
        return True
    if not BASELINE.exists():
        print("   🔴 基线文件不存在：%s" % BASELINE)
        print("      第一次建立请跑：python3 pipeline/build_entry_layer.py --rebaseline")
        return False
    old_ = [x for x in BASELINE.read_text(encoding="utf-8").splitlines() if x.strip()]
    add, rm = sorted(set(now) - set(old_)), sorted(set(old_) - set(now))
    print("   基线 %s 条 ／ 本次 %s 条 ／ 新增 %s ／ 消失 %s"
          % (f"{len(old_):,}", f"{len(now):,}", f"{len(add):,}", f"{len(rm):,}"))
    for x in (add[:4] + rm[:4]):
        print("      ~ %s" % x)
    ok = not add and not rm
    print("   %s 漂移清单与基线逐条一致" % ("✓" if ok else "🔴"))
    return ok


def rebuild_de_fields(entries, noun_forms):
    """从 entry 层按 build.py 的规则重建 dict 的德语列 → {word: {列: 值}}。

    规则一律「**取第一个非空**」（`build.py:410-445` 全是 `if x and not rec[...]`），
    两个布尔列是「任一为真则 1」。`noun_variants` 走 `compose_noun_variants`（import 的）。
    """
    out = defaultdict(dict)
    for word, pos_raw, etym_no, seq, f1 in entries:
        r = out[word]
        for c in FIRST_WINS:
            v = f1.get(c)
            if v and not r.get(c):
                r[c] = v
        for c in FLAGS:
            if f1.get(c):
                r[c] = 1
    for word, nf in noun_forms.items():
        nv = compose_noun_variants(nf)
        if nv:
            out[word]["noun_variants"] = nv
    return out


FIELD_BASELINE = Path(__file__).resolve().parent.parent / "tests" / "field_drift_baseline.txt"


def gate1b(con, entries, noun_forms, rebaseline=False):
    """(b) 德语 13 列：**kaikki 有值处必须与 dict 一致**；其余两桶锁清单。

    三桶，判据是语义的不是形式的：
      · 一致                —— kaikki 与 dict 相同
      · **豆包补空层**       —— dict 有值、kaikki 无值。七月 `b_translate.py` 补的
                             （`if not c_cmp: …` 只填空不覆盖），说不出来源 ⇒ 记账不当错
      · **两边都有值但不同**  —— 真冲突，逐条进基线让人读（实测 21 行，两边各有对错）

    🔴🔴 **第一版把判据写成「冲突 ≤ 上限 50」，变异当场证明它是瞎的**：
       改错一个 gender 只让 21 变 22，闸一声不吭 —— 与闸①(a) 第一版同一个病
       （**用阈值代替清单**）。⇒ 冲突逐条锁、补空层逐列锁计数，动一个字就红。
    """
    print("\n═══ 闸①(b) 德语一等字段回核（13 列，全量非抽样）═══")
    cols = FIRST_WINS + FLAGS + ["noun_variants"]
    mine = rebuild_de_fields(entries, noun_forms)
    same, llm, conflict, upstream = Counter(), Counter(), [], Counter()
    for row in con.execute("SELECT word, %s FROM dict" % ", ".join(cols)):
        w, vals = row[0], row[1:]
        r = mine.get(w, {})
        for c, v in zip(cols, vals):
            v, got = (v or None), (r.get(c) or None)
            if v == got:
                same[c] += 1
            elif got is None:
                llm[c] += 1
            elif v is None:
                upstream[c] += 1
            else:
                conflict.append((w, c, v, got))
    print("   %-14s %10s %12s %12s %10s" % ("列", "一致", "豆包补空层", "上游新增", "🔴冲突"))
    for c in cols:
        n = sum(1 for x in conflict if x[1] == c)
        print("   %-14s %10s %12s %12s %10s"
              % (c, f"{same[c]:,}", f"{llm[c]:,}", f"{upstream[c]:,}", f"{n:,}"))
    print("   —— 豆包补空层合计 **%s** 个字段值（无来源标记，收尾单 C7）" % f"{sum(llm.values()):,}")
    for w, c, v, got in conflict[:6]:
        print("   🔴 %-20s %-12s 库=%-22r 新dump=%r" % (w, c, v, got))

    now = sorted(["CONFLICT\t%s\t%s\t%s\t%s" % (w, c, v, g) for w, c, v, g in conflict]
                 + ["LLMFILL\t%s\t%d" % (c, llm[c]) for c in cols]
                 + ["UPSTREAM\t%s\t%d" % (c, upstream[c]) for c in cols])
    if rebaseline:
        FIELD_BASELINE.parent.mkdir(exist_ok=True)
        FIELD_BASELINE.write_text("\n".join(now) + "\n", encoding="utf-8")
        print("   ⚠️ 已重写字段基线 %s（%s 条）" % (FIELD_BASELINE.name, f"{len(now):,}"))
        return True
    if not FIELD_BASELINE.exists():
        print("   🔴 基线文件不存在：%s（先跑 --rebaseline）" % FIELD_BASELINE)
        return False
    old_ = [x for x in FIELD_BASELINE.read_text(encoding="utf-8").splitlines() if x.strip()]
    add, rm = sorted(set(now) - set(old_)), sorted(set(old_) - set(now))
    print("   字段基线 %s 条 ／ 新增 %s ／ 消失 %s" % (f"{len(old_):,}", len(add), len(rm)))
    for x in (add[:4] + rm[:4]):
        print("      ~ %s" % x[:110])
    ok = not add and not rm
    print("   %s 冲突清单与补空层计数逐条一致" % ("✓" if ok else "🔴"))
    return ok


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    def q(s):
        return con.execute(s).fetchone()[0]
    checks = [
        ("entry 条数 == 期望", q("SELECT count(*) FROM entry"), expect["entry"]),
        ("sense_src 条数 == 期望", q("SELECT count(*) FROM sense_src"), expect["src"]),
        ("孤儿 entry（word_id 不在 dict）",
         q("SELECT count(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
           "WHERE d.id IS NULL"), 0),
        ("孤儿 sense_src（word_id 不在 dict）",
         q("SELECT count(*) FROM sense_src x LEFT JOIN dict d ON d.id=x.word_id "
           "WHERE d.id IS NULL"), 0),
        ("sense_src.sense_id 指向不存在的 sense",
         q("SELECT count(*) FROM sense_src x LEFT JOIN sense s ON s.id=x.sense_id "
           "WHERE x.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        # 🔴 de 特有：德语不折叠大小写 ⇒ word_src 必须逐字节等于 dict.word
        ("word_src <> dict.word（德语不折叠，必须为 0）",
         q("SELECT count(*) FROM entry e JOIN dict d ON d.id=e.word_id "
           "WHERE e.word_src <> d.word"), 0),
        ("有 en 义项却没有证据行的 sense",
         q("SELECT count(*) FROM sense s WHERE NOT EXISTS("
           "SELECT 1 FROM sense_src x WHERE x.sense_id=s.id) "
           "  AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='en')"),
         expect["sense_no_src"]),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--rebaseline", action="store_true",
                    help="🔴 重写漂移基线 —— 只在**确认上游换版**之后有意执行")
    a = ap.parse_args()

    print("■ 扫 %s" % paths.KK.name)
    entries, senses_by_word, src_rows, noun_forms, stat = scan()
    for k, v in stat.items():
        print("   %-50s %10s" % (k, f"{v:,}"))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.mutate:
        return mutate(con, senses_by_word, entries, noun_forms)
    ok1a = gate1a(con, senses_by_word, a.rebaseline)
    ok1b = gate1b(con, entries, noun_forms, a.rebaseline)
    if not (ok1a and ok1b):
        print("\n🔴 闸①未通过 —— **不写库**。复刻与库不一致，先查规则哪条没对上。")
        return 1
    if not a.apply:
        print("\n✓ 闸① 两半全过（未加 --apply，不写库）")
        return 0

    # ── 组装写库行 ────────────────────────────────────────────────
    wid = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    # 🔴🔴 **证据行挂到义项上，判据必须是「释义文本」，不能是「第几条」。**
    #    上游 dump 换过版：143 个词条的释义被改写、9 个不再产生义项、370 个是新增的
    #    ⇒ 复刻序列的下标与库里的 rank **在这些词上根本对不齐**，按下标挂就是错配。
    #    `[[model-answer-files-key-by-id]]`：`registrare` 那次中文贴到别的义项上，
    #    根因就是"编号用了序号不是主键"。这里用内容做键，挂不上的**留空**，不猜。
    sense_by_text = defaultdict(dict)
    for s_id, w, text in con.execute(
            "SELECT s.id, d.word, g.text FROM sense s JOIN dict d ON d.id=s.word_id "
            " JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' AND g.kind='equivalent'"):
        sense_by_text[w][text] = s_id
    con.close()

    erows, eref = [], {}
    for i, (word, pos_raw, etym_no, seq, f1) in enumerate(entries):
        ref = "kk-en:%s:%s:%s:%d" % (word, pos_raw, etym_no, seq)
        eref[i] = ref
        if word not in wid:
            continue                       # 上游新增的词形，库里没有 dict 行 ⇒ 阶段 3 收词
        erows.append((wid[word], word, POS_MAP.get(pos_raw, pos_raw), pos_raw, etym_no, seq,
                      f1.get("gender"), f1.get("genitive"), f1.get("plural"),
                      f1.get("aux"), f1.get("praeteritum"), f1.get("partizip2"),
                      f1.get("vclass"), f1.get("separable"), f1.get("sep_prefix"),
                      f1.get("reflexive"), f1.get("comparative"), f1.get("superlative"),
                      SRC, ref))
    srows, n_linked, n_free = [], 0, 0
    for word, ei, si, kind, gloss, tags, _targets in src_rows:
        if word not in wid:
            continue
        s_id = sense_by_text.get(word, {}).get(gloss) if kind == "sense" else None
        if kind == "sense":
            n_linked += bool(s_id)
            n_free += (not s_id)
        srows.append((wid[word], s_id, SRC, "%s#%d" % (eref[ei], si), "en", gloss,
                      json.dumps(tags, ensure_ascii=False) if tags else None))
    print("   证据行挂到义项：**按释义文本**挂上 %s ／ 挂不上 %s（上游改写的那批，留空不猜）"
          % (f"{n_linked:,}", f"{n_free:,}"))
    miss = {w for w, *_ in entries if w not in wid}
    if miss:
        print("   ⚠️ 上游新增、库里还没有的词形 %s 个 ⇒ 本步不建 entry（阶段 3 收词）"
              % f"{len(miss):,}")

    print("\n   → entry 行 %s ／ sense_src 行 %s" % (f"{len(erows):,}", f"{len(srows):,}"))
    now = dbtool.snapshot()
    expect = {"#entry": len(erows) - now.get("#entry", 0),
              "#sense_src": len(srows) - now.get("#sense_src", 0)}
    with dbtool.session("keep-v3-entry", expect=expect) as s:
        s.execute("DROP TABLE IF EXISTS entry")
        s.execute(DDL_ENTRY)
        for q in IDX_ENTRY:
            s.execute(q)
        s.execute("DELETE FROM sense_src")
        s.executemany(
            "INSERT INTO entry (word_id,word_src,pos,pos_raw,etym_no,seq,"
            " gender,genitive,plural,aux,praeteritum,partizip2,vclass,separable,"
            " sep_prefix,reflexive,comparative,superlative,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", erows)
        s.executemany(
            "INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
            "VALUES (?,?,?,?,?,?,?)", srows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    _, unanchored, _, _ = classify(con, senses_by_word)
    ok2 = gate2(con, {"entry": len(erows), "src": len(srows),
                      # 🔴 期望值来自**独立算出来的漂移数**，不是照抄结果（否则就是自证）：
                      #    库里有 en 义项却没有证据行的，恰恰应该是上游改写掉的那批。
                      "sense_no_src": unanchored})
    print("\n%s" % ("✓ 全部通过" if ok2 else "🔴 闸②有未通过项"))
    return 0 if ok2 else 1


def mutate(con, senses_by_word, entries, noun_forms):
    """🔴 变异验证：闸①的两半各造两处破坏，必须全被报出来。

    ⚠️ 变异**必须真的把被断言的东西拿走**（`[[fix-regression-and-gate]]`：
       pt 那轮三条变异只改文档不改世界，做完之后一条都打不中）。
       这里改的是**复刻结果**（内存），等价于"复刻算错了"，闸①必须报。
    """
    print("\n═══ 变异验证 ═══")
    cases = []

    def broke(name, fn):
        ok = fn()
        cases.append(ok)
        print("   %s  %s" % ("✓ 逮到" if ok else "🔴 **漏了**", name))

    w0 = next(w for w, v in senses_by_word.items() if len(v) > 1)
    broke("闸①(a)：把一个词的义项顺序倒过来", lambda: not gate1a(
        con, {**senses_by_word, w0: list(reversed(senses_by_word[w0]))}))
    w1 = next(w for w, v in senses_by_word.items() if v)
    broke("闸①(a)：删掉一个词的最后一条义项", lambda: not gate1a(
        con, {**senses_by_word, w1: senses_by_word[w1][:-1]}))

    i0 = next(i for i, (_, _, _, _, f1) in enumerate(entries) if f1.get("gender"))
    bad_e = list(entries)
    w, p, en_, sq, f1 = bad_e[i0]
    bad_e[i0] = (w, p, en_, sq, {**f1, "gender": "zzz"})
    broke("闸①(b)：把一个 entry 的 gender 改错", lambda: not gate1b(con, bad_e, noun_forms))

    i1 = next(i for i, (_, _, _, _, f1) in enumerate(entries) if f1.get("plural"))
    bad_e2 = list(entries)
    w, p, en_, sq, f1 = bad_e2[i1]
    bad_e2[i1] = (w, p, en_, sq, {k: v for k, v in f1.items() if k != "plural"})
    broke("闸①(b)：把一个 entry 的复数丢掉", lambda: not gate1b(con, bad_e2, noun_forms))

    print("\n   变异 %d/%d" % (sum(cases), len(cases)))
    return 0 if all(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
