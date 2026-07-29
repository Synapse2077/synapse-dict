#!/usr/bin/env python3
"""A1d:纯指针空壳(X的另一种写法/替代拼写) → 回填 target 词义。见对话 2026-07-27。

A1a 收尾时扫全尾巴,发现**同性质但不同措辞**的一族:整条译文只说"我是另一个词的异体拼写",
自身无任何词义 —— 与 A1「变形元描述空壳」病理相同,只是不是变形关系:
    hoquet   → n. hocket的替代拼写
    geniza   → n. genizah的替代拼写
    akhoond  → n. akhund的替代拼写
(即 [[clitic-compound-gloss-defect]] 里其他语种修过的 pointer gloss 族,英语这边此前未处理。)

与 A1a 的差别:异体拼写**不是形态派生**,故不套形态一致闸(C);其余闸沿用
(A专名 / B缩写 / F裸音译 / target 非[网络] / target 自身不是空壳或指针)。
回填格式同 A1a:保留原指针说明为首行,target 译文按行追加。

用法:
  python3 en/fix_a1d.py            # dry-run
  python3 en/fix_a1d.py --run      # 备份后写库,留痕 a1d_fill.tsv
"""
import argparse, re, shutil, sqlite3, random
from collections import Counter
from datetime import datetime
from pathlib import Path

import fix_a1a_guard as G

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
LOG = HERE / "a1d_fill.tsv"
REVLOG = HERE / "a1d_reverted.tsv"   # 禁止重填名单(pro 判 bad 撤回过的,别再填回去)

CORE = ("(COALESCE(collins,0)>0 OR COALESCE(oxford,0)>0 OR COALESCE(frq,0)>0 "
        "OR COALESCE(bnc,0)>0 OR COALESCE(TRIM(tag),'')<>'')")
# ⚠️ 两处曾漏判(与 B1 提原形是同一族 bug):
#   ① 捕获组必须含**空格**,否则多词 target 被漏(只匹配到单词的那部分);
#   ② KIND 列表要覆盖全部措辞(变形/变化形式/变体形式…),窄列表只捞到 301/14307。
#   ③ **同义词整类不收**:B1 已证同义词关系下 target 多义时抄来的常是另一个义
#      (tropical yam→ñame 被抹成 name→"名字";South American fox→zorro→"佐罗")。
# 🔴 **"变形/变化形式"整类不可收**(实测 bad 85.5%,全批 8,804 条已退回):
#   它不是"同一个词的异体拼写",而是"**由 X 派生出的另一个词**",派生词词义与词根不同:
#     insectologists→insectology的变形+"昆虫学"(实为昆虫学家们) / co-publisher→co-publish的变形+"合作出版"(实为出版商)
#     definements→define的变形+"定义(动词)"(实为名词复数)
#   与"同义词"栽的是同一个跟头:**target 的词义 ≠ 该词的词义** 的关系一律不能抄。
#   分层实测:替代拼写 2.0% / 替代拼写形式 3.8% / 另一种写法 1.2% / 另一种拼写 4.0% / 变体 0% —— 只有"变形"是灾难。
KIND = (r"(另一种写法|另一种拼写|替代拼写形式|替代拼写|变体形式|变体|异体|旧形式|旧拼写)")
PTR = re.compile(r"^\s*(?:[a-z]{1,8}\.(?:form)?\s*)*([A-Za-z][\w'’À-ɏ\- ]*?)\s*的" + KIND + r"\s*$")
# `=X` / `＝X` 型:整条只是指向另一个词
EQ = re.compile(r"^\s*(?:[a-z]{1,8}\.\s*)*[=＝]\s*([A-Za-z][\w'’À-ɏ\- ]*?)\s*$")
MW = (r"(复数形式|复数|现在分词和动名词形式|现在分词|过去式和过去分词|过去式与过去分词形式|"
      r"过去式|过去分词|第三人称单数|第三人称 ?-s ?形式|最高级|比较级)")
SHELL_META = re.compile(r"[A-Za-z][\w '\-]*\s*的" + MW)


def collect(conn):
    forms, trans = G.build_index(conn)
    blocked = set()
    if REVLOG.exists():
        for i, ln in enumerate(open(REVLOG, encoding="utf-8")):
            if i:
                blocked.add(int(ln.split("\t")[0]))
    rej = Counter()
    out = []
    for i, w, t in conn.execute(f"SELECT id, word, translation FROM stardict WHERE NOT {CORE}"):
        ws = w.strip()
        body = (t or "").strip()
        # ⚠️ 只在**匹配时**把换行归一化成空格;写回必须用原文 body,
        #    否则 'n.\nwych-elm 的异体' 会被压成一行 → 破坏"只增不改"不变式(审计靠它)
        if i in blocked:
            rej["在禁止重填名单"] += 1; continue
        flat = body.replace("\n", " ")
        m = PTR.match(flat)
        kindzh = "的异体拼写"
        if m:
            tgt = m.group(1).strip().lower()
        else:
            m = EQ.match(flat)
            if not m:
                continue
            tgt = m.group(1).strip().lower()
            kindzh = "的同义/等价形式"
        tt = trans.get(tgt, "")
        if not tt:
            rej["target 不在库"] += 1; continue
        if "[网络]" in tt:
            rej["target 是[网络]众包"] += 1; continue
        if PTR.match(tt.replace("\n", " ")):
            rej["target 自己也是指针"] += 1; continue
        if SHELL_META.search(tt) and not re.sub(SHELL_META, "", tt).strip(" \n;；,，/()（）.·-"):
            rej["target 自己是变形空壳"] += 1; continue
        if tgt == ws.lower():
            rej["target=词条自身"] += 1; continue
        if not re.search(r"[一-鿿]", tt):
            rej["target 译文无汉字"] += 1; continue
        # 沿用 A1a 的闸,但**去掉形态一致闸 C**(异体拼写不是形态派生)
        g = [x for x in G.guards(ws, tgt, forms, trans) if not x.startswith("C")]
        if g:
            rej["闸拦下(" + g[0][0] + "…)"] += 1; continue
        out.append((i, ws, body, tgt, tt))
    return out, rej


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    cand, rej = collect(conn)
    print("A1d 指针空壳 → 逐条剔除原因:")
    for k, v in rej.most_common():
        print(f"  {k:22} {v:>6}")
    print(f"\nA1d 候选 {len(cand)}")
    random.seed(3)
    for i, w, b, tgt, tt in random.sample(cand, min(8, len(cand))):
        print(f"\n  {w}\n    前: {b}\n    后: {(b + chr(10) + tt).replace(chr(10), ' ⏎ ')[:96]}")

    if not a.run:
        print("\n(dry-run;加 --run 写库)")
        return
    if not cand:
        print("\n无候选,不动库。")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    bak = DB.with_name(f"synapse-dict-en.pre-a1d-{tag}.bak")
    shutil.copy2(DB, bak)
    print(f"\n已备份 → {bak.name}")

    # ⚠️ 追加不覆盖:LOG 存历次"回填前原文",是回退与验收的依据
    conn = sqlite3.connect(DB)
    fresh = not LOG.exists()
    with open(LOG, "a", encoding="utf-8") as f:
        if fresh:
            f.write("id\tword\ttarget\tbefore\tafter\n")
        for i, w, b, tgt, tt in cand:
            new = b + "\n" + tt
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, i))
            f.write("\t".join([str(i), w, tgt, b.replace("\t", " ").replace("\n", "\\n"),
                               new.replace("\t", " ").replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"已回填 {len(cand)} 条,留痕 → {LOG.name}")


if __name__ == "__main__":
    main()
