#!/usr/bin/env python3
"""ru 阶段 1：骨架层建库 —— `dict`（词形）＋ `entry`（同形异义的分界）。2026-10-07。

**判据一条都不在本文件里写** —— 全部 `from pipeline import criteria` 取用。
vi 的阶段 8 的教训更狠一层：⭐**「哪些行才真的落库」也是判据、也必须只有一个家** ——
收割器把条件写成字面量埋在 `main()` 里，闸重写一遍报了 458 条假缺。
⇒ 本文件的「收不收这一行」也走 `criteria`，不在 `main()` 里写 `if`。

═══ 🔴 七源全收，而「主源」是按层分的（RU_PLAN §6.2）═══
    词元     en 59,851 ／ **ru 477,641（97.6%）**
    屈折形   **en 382,743（86.5%）** ／ ru 11,881
⇒ 骨架层**不挑源**，七份全收并集（976,762 个词形）；
  「哪一版的料更好」是后面各层各自裁决的事，不在这一步决定。

═══ 🔴🔴 三个这一步必须定死的约定 ═══

① **`is_lemma` 取「任一源说它是词元」的或**。
   同一个词形在 A 版是词元、在 B 版是屈折形（`использую` 在 en 版是屈折形，
   而它作为独立词条也可能出现）—— **是词元就是词元**，屈折形身份记在 `entry` 上。
   ⚠️ 反过来（取「全都说是屈折形」的与）会把 38 万个屈折形标成词元，
     而 `is_lemma` **决定一切覆盖率的分母**。

①b **`dict` 的身份单位是 `word`，`entry_type` 按词唯一。**
   🔴 第一版定成 `(word, entry_type)` ⇒ 一个拼写在不同词性下成了多个 dict 行
   （47,110 行虚胖，而 `word_norm` 一对多里 84.2% 是它）。**骨架闸 K10 报出来的。**
   判据 `criteria.entry_type_for_word` 要求**两个独立信号一致**：
   源头词性 ＋ 词头自己的形式（`сердце` 源头说 proverb 而它没有空格 ⇒ 不是谚语）。

② **`dict.pos` ＝ 这个词形所有词性的短码，排序后斜杠连接**（`noun/verb`）。
   🔴🔴 这是 ko 的 **K31** 栽过的位置：那次 `dict.pos` 存**长码＋斜杠**而展示层读
   `pos` 短码，而**我的覆盖闸也查长码 ⇒ 双方一致报全绿而每个徽标都是空的**。
   ⇒ 这里只存**短码**（`criteria.pos_norm` 的输出），而骨架闸查的是
   **读者口径：每一个斜杠段都必须在 `ENTRY_TYPE` 的值域里**。
   值域只有一套，归一只在一个地方做。

③ **落行的语法标签这一步没有家。**
   `criteria.entry_grammar()` 返回两份：落列的四个（`entry` 上）和**落行的那些**
   （`transitive`/`plural-only`/`semelefactive`…）。后者的家是 `sense_tag`，
   而 `sense` 层要到阶段 5 才有 ⇒ **这一步它们一条都落不了库**。
   🔴 **不许静默丢掉**：本文件把它们的条数算出来并落进 `data/work/ru/`，
      同时记欠账 **R11**，而 R11 **带锁**（账的闸：`sense` 一非空而
      `sense_tag(bucket='grammar')` 还是空的就判红）。
      `[[dont-say-source-lacks-what-we-skipped]]`：「源头没有」和「我们没抽」
      要在结构上分开 —— 这一批是**我们还没抽**。

用法：
    python3 ru/pipeline/build.py --dry          # 只统计，不写库
    python3 ru/pipeline/build.py --limit 20000  # 每源前 N 行（调判据时用）
    python3 ru/pipeline/build.py                # 真写库
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                   # noqa: E402
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402

# 源的登记表。**顺序就是 `entry.src` 的书写顺序**，与「谁是主源」无关。
SRC = [
    ("en-edition", paths.KK),
    ("ru-edition", paths.EDITION),
    ("zh-edition-simp", paths.ZH_SIMP),
    ("zh-edition-trad", paths.ZH_TRAD),
    ("fr-edition", paths.FR_EDITION),
    ("vi-edition", paths.VI_EDITION),
    ("pl-edition", paths.PL_EDITION),
]
# 🔴 `src_ref` 的短名表与拼法**不在这里** —— 2026-10-08（阶段 2）搬进
#    `criteria.SRC_SHORT` / `criteria.SrcRef`，因为重音层要靠重算 `src_ref`
#    把 `forms[canonical]` 挂到对应的 entry 上。**两边差一行就整体错位一格。**
#    见 `criteria.py` §⑥。
SHORT = criteria.SRC_SHORT


def rd(p, limit=None):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                return
            yield json.loads(line)


def collect(limit=None, verbose=True):
    """扫七源 → (dict 行, entry 行, 统计)。**只读，不写库。**

    🔴 `dict` 按 `(word, entry_type)` 聚合（那就是它的 UNIQUE）；
       `entry` 一行源头一行，`src_ref` 保证幂等。
    """
    # 🔴 **按 `word` 聚合**，不是 `(word, entry_type)` —— 后者把一个词形切成多行
    #    （第一版的错，是**骨架闸 K10 报出来的**）。
    #    `entry_type` 在最后由这个词形的**全部 pos 一次算出**（按词唯一）。
    # word → {"norm":…, "is_lemma":bool, "pos":set()}
    forms = {}
    entries = []                 # (word, pos, etym_no, etym_sub, seq, cols, src, src_ref)
    ref = criteria.SrcRef()       # 🔴 有状态：序号按扫源顺序走，见 criteria §⑥
    st = {
        "lines": 0, "lang_other": collections.Counter(),
        "pos_unknown": collections.Counter(),
        "formof_via": collections.Counter(),
        "grammar_rows": collections.Counter(),   # 落行的语法标签（这一步没有家）
        "grammar_rows_entries": 0,
        "cols_filled": collections.Counter(),
        "per_src": collections.Counter(),
        "lemma_conflict": 0,
    }
    for src, p in SRC:
        t0 = time.time()
        n = 0
        for e in rd(p, limit):
            st["lines"] += 1
            n += 1
            # 🔴 「这一行会不会落库」是判据，家在 `criteria.entry_accept`（§⑥）——
            #    阶段 2 的重音收割器要重放**同一条**逻辑才能对上 `src_ref`。
            ok, skip, pos = criteria.entry_accept(e)
            if not ok:
                kind, detail = skip
                if kind == "lang":
                    st["lang_other"][detail] += 1
                else:
                    st["pos_unknown"][detail] += 1
                continue
            w = e["word"]
            is_form, via = criteria.is_inflected_form(e)
            if via:
                st["formof_via"][via] += 1
            cur = forms.get(w)
            if cur is None:
                forms[w] = cur = {"norm": criteria.norm_ru(w),
                                  "is_lemma": not is_form, "pos": set()}
            else:
                # ① 任一源说它是词元 ⇒ 它是词元（见文件头）
                if (not is_form) and not cur["is_lemma"]:
                    st["lemma_conflict"] += 1
                cur["is_lemma"] = cur["is_lemma"] or (not is_form)
            cur["pos"].add(pos)

            cols, rows = criteria.entry_grammar(e)
            for k, v in cols.items():
                if v:
                    st["cols_filled"][k] += 1
            if rows:
                st["grammar_rows_entries"] += 1
                for r in rows:
                    st["grammar_rows"][r] += 1
            en_no, en_sub = criteria.etym_no_pair(e)
            sref, seq = ref.take(src, w, pos, en_no, en_sub)
            entries.append((w, pos, en_no, en_sub, seq, cols, src, sref))
            st["per_src"][src] += 1
        if verbose:
            print("  · %-16s %9s 行  %5.1fs" % (src, format(n, ","), time.time() - t0),
                  file=sys.stderr)
    return forms, entries, st


def report(forms, entries, st):
    print("\n■ 阶段 1 骨架层 —— 扫了 %s 行" % format(st["lines"], ","))
    print("   `dict` 词形   %s" % format(len(forms), ","))
    print("   `entry` 词条  %s" % format(len(entries), ","))
    lem = sum(1 for v in forms.values() if v["is_lemma"])
    print("   词元 %s（%.2f%%）／ 屈折形 %s（%.2f%%）"
          % (format(lem, ","), 100.0 * lem / max(len(forms), 1),
             format(len(forms) - lem, ","), 100.0 * (len(forms) - lem) / max(len(forms), 1)))
    print("\n   entry_type 分布：")
    et = collections.Counter(
        criteria.entry_type_for_word(w, v["pos"]) for w, v in forms.items())
    for k, v in et.most_common():
        print("      %-10s %10s" % (k, format(v, ",")))
    print("\n   「这是屈折形」是从哪条路认出来的（三条都要走）：")
    for k, v in st["formof_via"].most_common():
        print("      %-24s %10s" % (k, format(v, ",")))
    print("\n   四个落列语法字段的填充数：")
    for k in ("aspect", "gender", "animacy", "declension"):
        print("      %-12s %10s" % (k, format(st["cols_filled"][k], ",")))
    print("\n   🔴 **落行的语法标签：这一步没有家**（`sense_tag` 要等阶段 5）")
    print("      涉及 %s 个词条、%s 条标签 —— 记欠账 **R11**，且 R11 带锁"
          % (format(st["grammar_rows_entries"], ","),
             format(sum(st["grammar_rows"].values()), ",")))
    for k, v in st["grammar_rows"].most_common(10):
        print("      %-16s %10s" % (k, format(v, ",")))
    if st["lang_other"]:
        print("\n   ⚠️ 切片里混了别的语言（已跳过）：%s" % dict(st["lang_other"]))
    if st["pos_unknown"]:
        print("\n   🔴 认不出的 pos / 空词头（已跳过，**必须处理**）：")
        for k, v in st["pos_unknown"].most_common(6):
            print("      %-66s %s" % (k, format(v, ",")))
    print("\n   同一词形在不同源里词元/屈折形身份不一致：%s 次"
          "（按「任一源说是词元」取或，见文件头①）" % format(st["lemma_conflict"], ","))
    return st


def write(forms, entries, st):
    exp = {
        "__rows__": len(forms),
        "word_norm": len(forms),
        "word_fold": len(forms),
        # 🔴 **这里是 `len(forms)` 不是「词元数」。** `snapshot()` 数的是
        #    `TRIM(COALESCE(col,''))<>''`，而 `is_lemma=0` 转成字符串是 `'0'` —— **非空**。
        #    ⚠️ 我第一版写的是词元数（686,691），那会让闸红在一个**没错的数据**上。
        #    ⭐ 这一列真正要守的是「词元/屈折形有没有分开」，而那条断言在
        #      **骨架闸 K6**（两个方向都断言），不在这儿。写库闸门守的是
        #      「有没有改到不该改的范围」，不是「内容对不对」—— 两件事别混。
        "is_lemma": len(forms),
        "entry_type": len(forms),
        "pos": len(forms),
        "#entry": len(entries),
        "entry.pos": len(entries),
        # 🔴 `etym_no` 是 `NOT NULL DEFAULT 0`，而 `snapshot()` 数的是
        #    `TRIM(COALESCE(col,''))<>''` —— `0` 转成字符串是 `'0'`，**非空** ⇒ 全计入
        "entry.etym_no": len(entries),
        "entry.etym_sub": len(entries),
        "entry.aspect": st["cols_filled"]["aspect"],
        "entry.gender": st["cols_filled"]["gender"],
        "entry.animacy": st["cols_filled"]["animacy"],
        "entry.declension": st["cols_filled"]["declension"],
    }
    # 🔴 收词闸：插了行就必须**显式**声明让哪些层过期了。
    #    这一步是**第一次**插行，下游一层都还不存在 ⇒ 如实写 []，而那是一次显式声明。
    with dbtool.session("build-skeleton", expect=exp, invalidates=[]) as s:
        wid = {}
        rows = []
        for i, (w, v) in enumerate(sorted(forms.items()), start=1):
            wid[w] = i
            rows.append((i, w, v["norm"], criteria.fold_ru(w),
                         criteria.entry_type_for_word(w, v["pos"]),
                         1 if v["is_lemma"] else 0,
                         "/".join(sorted(v["pos"]))))
        s.executemany(
            "INSERT INTO dict(id,word,word_norm,word_fold,entry_type,is_lemma,pos) "
            "VALUES (?,?,?,?,?,?,?)", rows)
        erows = [(wid[w], pos, en, sub, sq, c["aspect"], c["gender"],
                  c["animacy"], c["declension"], src, ref)
                 for (w, pos, en, sub, sq, c, src, ref) in entries]
        s.executemany(
            "INSERT INTO entry(word_id,pos,etym_no,etym_sub,seq,aspect,gender,"
            "animacy,declension,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?)", erows)
    # 落行的语法标签落盘存档（它们这一步没有库里的家，但**不许丢**）
    out = paths.WORK / "stage1_grammar_rows.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"entries": st["grammar_rows_entries"], "tags": dict(st["grammar_rows"])},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n■ 落行的语法标签已存档 → %s（欠账 R11）" % out)


def sync_lemma(forms, dry=False):
    """**只同步 `dict.is_lemma`**，其余一个字节不动。2026-10-23（ru-crit-9）。

    🔴 为什么不重建：`entry`/`stress`/`inflection` 都挂在 id 上，重建要连坐三层；
       而这次判据只改了「哪些词形算词元」这一件事。
    ⭐ 生成侧和落库的行**同时**修（`[[replay-scripts-undo-fixes]]`）：
       值来自同一个 `collect()`，所以下次真重建会得到一样的结果 ——
       这句话由**这个函数自己验**：同步之后再比一遍，差异必须是 0。
    🔴 必须**两个方向都报**：只报 1→0 的话，判据写坏导致的 0→1 会静默写进去。
    """
    con = sqlite3.connect(paths.DB)
    cur = {w: (i, l) for i, w, l in con.execute("SELECT id, word, is_lemma FROM dict")}
    con.close()
    # 🔴 R13（阶段 2）把 7 个**词头自带重音符**的 dict 行并进了孪生行 ⇒ `collect()`
    #    里还有它们而库里没有。折叠规则与阶段 1 同一条：**任一源说是词元就是词元**
    #    ⇒ 孪生行取两者的或。⚠️ R13 当时只重算了 pos/entry_type、没并 is_lemma ——
    #    这里顺带补上（落在下面的 0→1 里，会被印出来）。
    #    映射只许是 R13 那一种（剥重音后在库里）；别的差异一律报错，不猜。
    want = {w: bool(v["is_lemma"]) for w, v in forms.items() if w in cur}
    folded = []
    for w in sorted(set(forms) - set(cur)):
        bare = criteria.strip_stress(w)
        if bare == w or bare not in cur:
            raise SystemExit("🔴 重算出的词形 %r 不在库里、也不是 R13 合并掉的那种 —— "
                             "这不是 is_lemma 的事，**别用同步模式**" % w)
        want[bare] = want.get(bare, False) or bool(forms[w]["is_lemma"])
        folded.append("%s→%s" % (w, bare))
    extra = sorted(set(cur) - set(forms))
    if extra:
        raise SystemExit("🔴 库里有 %d 个词形 collect() 算不出来（如 %s）"
                         % (len(extra), extra[:5]))
    print("\n■ R13 折叠 %d 个：%s" % (len(folded), " ".join(folded)))
    down, up = [], []
    for w, wl in want.items():
        i, l = cur[w]
        want_l = 1 if wl else 0
        if want_l != l:
            (down if want_l == 0 else up).append((want_l, i, w))
    print("\n■ is_lemma 同步：1→0 %s 个 ／ 0→1 %s 个"
          % (format(len(down), ","), format(len(up), ",")))
    for name, lst in (("1→0", down), ("0→1", up)):
        if lst:
            print("   %s 样本：%s" % (name, " ".join(w for _x, _i, w in lst[:20])))
    if dry or not (down or up):
        print("(dry：没写库)" if dry else "(没有差异，不写库)")
        return 0
    # `expect` 为空是对的：`snapshot()` 数的是非空计数，`0`/`1` 都非空 ⇒ 计数不变。
    # 下游哪几道闸过期，由 `gates.dirty()` 从 SQL 里抠出的表名 `dict` 决定。
    with dbtool.session("sync-is-lemma-%s" % criteria.RULE_VER, expect={}) as s:
        s.executemany("UPDATE dict SET is_lemma=? WHERE id=?",
                      [(v, i) for v, i, _w in down + up])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = sum(1 for w, i, l in con.execute("SELECT word, id, is_lemma FROM dict")
               if l != (1 if want[w] else 0))
    con.close()
    if left:
        raise SystemExit("🔴 同步之后仍有 %d 个词形与 collect() 不一致" % left)
    print("■ 同步后复核：库 ＝ collect()，差异 0 ✓")
    return 0


def sync_fold(dry=False):
    """**只同步 `dict.word_fold`**（R30 的 ё 召回键，＝ `criteria.fold_ru(word)`），其余一个字节不动。

    它是 `word` 的纯函数 ⇒ 不用扫源头；同步后再比一遍，差异必须是 0。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("SELECT id, word, word_fold FROM dict").fetchall()
    con.close()
    up = [(criteria.fold_ru(w), i) for i, w, f in rows if f != criteria.fold_ru(w)]
    have = sum(1 for _i, _w, f in rows if f)
    print("■ word_fold 同步：%s 个词形要写（库里已有 %s）" % (format(len(up), ","), format(have, ",")))
    if dry or not up:
        print("(dry：没写库)" if dry else "(没有差异，不写库)")
        return 0
    with dbtool.session("sync-word-fold", expect={"word_fold": len(rows) - have}) as s:
        s.executemany("UPDATE dict SET word_fold=? WHERE id=?", up)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = sum(1 for w, f in con.execute("SELECT word, word_fold FROM dict") if f != criteria.fold_ru(w))
    con.close()
    if left:
        raise SystemExit("🔴 同步之后仍有 %d 个词形的 word_fold 与 fold_ru(word) 不一致" % left)
    print("■ 同步后复核：word_fold ＝ fold_ru(word)，差异 0 ✓")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只统计，不写库")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sync-lemma", action="store_true",
                    help="只把 dict.is_lemma 同步成当前判据的结果（不重建）")
    ap.add_argument("--sync-fold", action="store_true",
                    help="只把 dict.word_fold（R30 ё 召回键）同步成 fold_ru(word)（不扫源头）")
    a = ap.parse_args()
    if a.sync_fold:
        return sync_fold(dry=a.dry)
    print("■ 扫七源……", file=sys.stderr)
    forms, entries, st = collect(a.limit or None)
    report(forms, entries, st)
    if a.sync_lemma:
        if a.limit:
            raise SystemExit("🔴 `--sync-lemma` 不许和 `--limit` 一起用")
        return sync_lemma(forms, dry=a.dry)
    if a.dry:
        print("\n(dry：没写库)")
        return 0
    if a.limit:
        raise SystemExit("🔴 `--limit` 只许和 `--dry` 一起用 —— "
                         "半份数据写进库，之后所有覆盖率都是错的")
    write(forms, entries, st)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
