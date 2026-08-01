#!/usr/bin/env python3
"""A1a 回填的六道闸 + 撤回误填。见对话 2026-07-27。

fix_a1a.py 先回填了 15,675 条,pro 抽 300 判:ok 78.0% / warn 10.3% / bad 11.7%。
查 35 条 bad 的成因 —— **几乎都不是"抄错词义",而是词条本身是伪变形**:
  pakistans/ukraines/GoYas/sinais/Cretes  专名(国名/人名/地名)根本没有复数
  pixes ← PIXE                            base 是全大写缩写,不是词
  heires/blacklions/wulds                 base 压根不是英语词,译文是裸音译
  doughts ← dow                           元描述里的 base 本身就认错了
⚠️ 第一版只有 A/B/C 三闸,漏掉专名是因为**建 base 索引时 lower() 把原始大小写抹了**,
   `Pakistan`/`Goya`/`PIXE` 的专名/缩写信号就此失效 → D/E 两闸必须查原始词头形态。

六道闸(全确定性):
  A base译文含 人名/地名/姓氏/《》/国家/城市 等专名标记
  B base译文以 abbr./[=…] 开头(缩写)
  C 形态不一致:word ≠ base + 常规后缀(catches doughts←dow)
  D base 在库中的**原始词头**首字母大写 → 专名
  E base 原始词头全大写 → 缩写
  F base 译文无词性前缀、且是 ≤8 个纯汉字 → 裸音译(与 B1 同形,只是没带 [网络] 标记)

效果(在 pro 判过的 300 条上回测):
  三闸 → 留存 bad 6.6% / ok 84.1%(撤回 3184)
  六闸 → 留存 bad 4.1% / ok 85.6%(撤回 5001,占 31.9%)
⭐ 取舍依据:**两类错代价不对等**。撤回=恢复原状(还是那句没用的"X的复数",不新增伤害);
   留下坏回填=主动给用户错词义。故宁可多撤(撤回集里约 2/3 其实是好的,认了)。

用法:
  python3 en/fix_a1a_guard.py            # dry-run
  python3 en/fix_a1a_guard.py --run      # 备份后把命中闸的行恢复成回填前原文
"""
import argparse, re, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
LOG = paths.WORK / "ledgers/a1a_fill.tsv"
OUT = paths.WORK / "ledgers/a1a_reverted.tsv"

PROP = re.compile(r"人名|地名|姓氏|《|城市|首府|州名|国家|品牌")
ABBR = re.compile(r"^\s*(abbr\.|\[?=)")
POS = re.compile(r"(^|\n)\s*(n|v|vt|vi|a|adj|adv|un|na|prep|conj|int|pron|num|art)\s*\.")
MW = (r"(复数形式|复数|现在分词和动名词形式|现在分词|过去式和过去分词|过去式与过去分词形式|"
      r"过去式|过去分词|第三人称单数|第三人称 ?-s ?形式|最高级|比较级)")
BASEMETA = re.compile(r"([A-Za-z][\w'\-]*)\s*的" + MW)
POSPFX = re.compile(r"^\s*(?:[a-z]{1,4}\.\s*)+")
VAR = re.compile(r"[A-Za-z][\w'\-]*\s*的(变形|变化形式|变体形式|变化形)")
NPROP = re.compile(r"[（(]\s*姓\s*[）)]")


def morph_ok(w, b):
    w, b = w.lower(), b.lower()
    if w == b:
        return False
    for suf in ("s", "es", "ies", "ed", "ied", "ing", "est", "er", "d", "n", "en", "ren"):
        if w == b + suf:
            return True
    if b.endswith("y") and (w == b[:-1] + "ies" or w == b[:-1] + "ied"):
        return True
    if b.endswith("e") and (w == b[:-1] + "ing" or w == b[:-1] + "ed" or w == b[:-1] + "es"):
        return True
    if len(b) > 2 and (w == b + b[-1] + "ing" or w == b + b[-1] + "ed"):
        return True
    return False


def build_index(conn):
    forms, trans = {}, {}
    for w, t in conn.execute("SELECT word, translation FROM stardict"):
        k = w.strip().lower()
        forms.setdefault(k, set()).add(w.strip())   # ⚠️ 保留原始大小写
        trans.setdefault(k, (t or "").strip())
    return forms, trans


# ⭐ 闸的分工(2026-07-27 复盘后改):
#   第一轮是"先闸后判",九道闸撤回 6,033 条,而按 pro 标注回测**撤回集里约 60% 其实是好的**
#   —— 白扔了约 3,600 条正确回填。当时那样做是因为没打算全量判(撤回=恢复原状,代价不对称)。
#   既然现在每批都会走 sweep_a1.py 全量 judge,闸就该只留"确定性极高、判官必然同意"的,
#   模糊的(专名/裸音译/词头大写)交给判官逐条裁,能多留几万条好数据。
# STRICT=True 时只开三道:base 是[网络] / base 自己是空壳 / 形态不一致。
STRICT_KEEP = ("C形态不一致",)   # 另两道在 fix_a1a.py 的 collect() 里以剔除项实现


def guards(w, base, forms, trans, strict=False):
    bt = trans.get(base, "")
    fs = forms.get(base, set())
    g = []
    if PROP.search(bt): g.append("A专名标记")
    if ABBR.search(bt): g.append("B缩写标记")
    if not morph_ok(w, base): g.append("C形态不一致")
    if any(f[:1].isupper() for f in fs): g.append("D词头大写(专名)")
    if any(f.isupper() and len(f) > 1 for f in fs): g.append("E词头全大写(缩写)")
    body = re.sub(r"^\[[^\]]{1,8}\]", "", bt).strip()
    if not POS.search(bt) and re.fullmatch(r"[一-鿿·]{1,8}", body): g.append("F base译文是裸音译")
    # H:base 自己是"X的变形"型空壳 —— 元描述词表(MW)漏收"变形/变化形式"这一说法,
    #   导致 is_shell() 认不出 base 是空壳 → 回填了个"n. vex的变形"过来,等于没填。
    #   42 条,三轮 pro 标注命中的全是 bad。
    body_np = POSPFX.sub("", bt).strip()
    if VAR.search(body_np) and not VAR.sub("", body_np).strip(" \n;；,，/()（）.·-"):
        g.append("H base是'X的变形'空壳")
    # I:base 译文标了"(姓)" —— 姓氏无复数(cheongs←cheong「n. 张/章（姓）」)。
    #   ⚠️ 只认这个窄标记。试过扩到 河/岛/山/湖/半岛 等地理词 → 精度仅 50%,
    #   因为它命中的是"释义里提到地理名词"(capibara「产于南美湖泊溪流间」/cenote「尤卡坦半岛」),不是专名本身。
    if NPROP.search(bt):
        g.append("I base标(姓)")
    # G:base 自身译文里就有指向**另一个词**的元描述 → 该词条是"变形之上再造变形"
    #   beens←been(be的过去分词) / showns←shown / mewlings←mewling(mewl的现在分词)
    #   pro 判该族 warn 46.5%(族外仅 6.0%),是系统性混乱族;撤回精度 54%,优于前六闸的 36%
    if any(m.group(1).lower() != base.lower() for m in BASEMETA.finditer(bt)):
        g.append("G变形之上再造变形")
    if strict:
        g = [x for x in g if x.startswith(STRICT_KEEP)]
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    forms, trans = build_index(conn)
    rows = []
    for i, ln in enumerate(open(LOG, encoding="utf-8")):
        if not i:
            continue
        p = ln.rstrip("\n").split("\t")
        rows.append((int(p[0]), p[1], p[2], p[3].replace("\\n", "\n")))  # id, word, base, before

    flagged, tally = [], Counter()
    for rid, w, base, before in rows:
        g = guards(w, base, forms, trans)
        if g:
            flagged.append((rid, w, base, before, "+".join(g)))
            for x in g:
                tally[x] += 1

    print(f"已回填 {len(rows)}  → 命中闸(撤回) {len(flagged)} ({100*len(flagged)/len(rows):.1f}%)"
          f"  留存 {len(rows)-len(flagged)}")
    print("\n各闸命中(可重叠):")
    for k, v in tally.most_common():
        print(f"  {k:18} {v:>6}")

    if not a.run:
        print("\n(dry-run;加 --run 写库)")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    bak = DB.with_name(f"synapse-dict-en.pre-a1aguard-{tag}.bak")
    shutil.copy2(DB, bak)
    print(f"\n已备份 → {bak.name}")

    # ⚠️ 合并写,不能直接覆盖:OUT 同时是 fix_a1a.py 的**禁止重填名单**,
    #    里面还有 pro 判 bad 后手工撤回的行(闸逮不到),覆盖会把它们丢掉 → 下次重跑又被填回去。
    prior = []
    seen = {rid for rid, *_ in flagged}
    if OUT.exists():
        for i, ln in enumerate(open(OUT, encoding="utf-8")):
            if i and int(ln.split("\t")[0]) not in seen:
                prior.append(ln.rstrip("\n"))

    conn = sqlite3.connect(DB)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("id\tword\tbase\trestored_to\tguards\n")
        for ln in prior:
            f.write(ln + "\n")
        for rid, w, base, before, g in flagged:
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (before, rid))
            flat = before.replace("\n", "\\n")
            f.write("\t".join([str(rid), w, base, flat, g]) + "\n")
    conn.commit()
    conn.close()
    print(f"已撤回 {len(flagged)} 条 → {OUT.name}")


if __name__ == "__main__":
    main()
