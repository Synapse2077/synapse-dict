#!/usr/bin/env python3
"""A1a:纯元描述空壳 → 确定性回填 base 词义。见对话 2026-07-27。

背景(尾巴 387 万九桶分区):
  A1「纯元描述空壳」76,384 条 = 整条译文只交代"它是谁的复数/分词",无任何实际词义。
    cofferdams → "cofferdam的复数"   (用户划到它,弹窗不告诉他 cofferdam 是"围堰"=白查)
  A1 不能整桶回填:69.5% 的 base 译文本身就是 [网络] 众包(回填=扩散垃圾),
  40.3% 的 base 是多词短语(saint bedes / genus aldrovandas 这类机械造的伪复数,该删不该补)。
  → 只切出 **A1a = base 是单词、非 [网络]、自身有实义** 这一刀,才是真·确定性回填。

判定(全部确定性,不用 LLM):
  1. 本条译文剥掉元描述子句后残留为空 → 是空壳;
     ⚠️ 元描述正则**尾部不可贪婪**:`…的复数[^\n;；]*` 会把后面的真实义一起吃掉,
     误判 playbooks「(playbook 的复数) n. 剧本, 剧本集」为空壳(旧口径多吞 17%)。
  2. 从元描述里提 base;base 必须是单词(排除短语/连字符 → 伪复数族)。
  3. base 在库、译文非空、不含 [网络]、自身不是空壳、含汉字、不等于词条自身。
回填格式:保留原元描述为首行,base 译文按行追加(App.tsx parseTranslation 按 \n 切行,
无 n./v. 前缀的行原样显示,与 DB 既有多行译文一致)。

用法:
  python3 en/fix_a1a.py            # dry-run,只统计+抽样
  python3 en/fix_a1a.py --run      # 备份后写库,留痕 a1a_fill.tsv

⚠️ **幂等**:七道闸(见 fix_a1a_guard.py)已内联进 collect(),重跑不会把闸撤回的行再填回去。
   早期版本没内联,重跑会把 5,959 条撤回全部复原 —— 改脚本时别把这层去掉。
"""
import argparse, re, shutil, sqlite3, random
from collections import Counter
from datetime import datetime
from pathlib import Path

import fix_a1a_guard as G  # 七道闸:A专名 B缩写 C形态 D词头大写 E全大写 F裸音译 G变形之上再造变形

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-en.sqlite"
LOG = HERE / "a1a_fill.tsv"
REVLOG = HERE / "a1a_reverted.tsv"

CORE = ("(COALESCE(collins,0)>0 OR COALESCE(oxford,0)>0 OR COALESCE(frq,0)>0 "
        "OR COALESCE(bnc,0)>0 OR COALESCE(TRIM(tag),'')<>'')")
MW = (r"(复数形式|复数|现在分词和动名词形式|现在分词|过去式和过去分词|"
      r"过去式与过去分词形式|过去式|过去分词|第三人称单数|第三人称 ?-s ?形式|最高级|比较级)")
META = re.compile(r"的" + MW)
CLAUSE = re.compile(r"[（(]?\s*[A-Za-z][\w '\-]*\s*的" + MW + r"\s*[)）]?")
BASE = re.compile(r"([A-Za-z][\w '\-]*)\s*的" + MW)
# ⚠️ 词性前缀必须先剥:剥掉元描述后残留一个 `n.`,而 strip 字符集不含字母 → 残留非空
#    → 被误判成"有实义"。这个 bug 让 A1 桶漏判 13.7 万条(horse brasses / Chinese hawthorns
#    / Gamow factors 全是纯空壳却分进了 C6/C5/C1),并在每个桶里制造假 bad。
POSPFX = re.compile(r"^\s*(?:[a-z]{1,5}\.(?:form)?\s*)+", re.M)
# 真·伪变形来源:分类阶元/圣人名/地名限定词开头的短语,本身无复数
TAXONPFX = re.compile(r"^(genus|family|order|class|subclass|suborder|phylum|division|tribe|saint|st|lake|mount|cape|fort|port|new|san|santa|los|las|el|la)\\b", re.I)


def is_shell(body):
    """整条只有元描述、无任何实义。"""
    if not META.search(body):
        return False
    return not POSPFX.sub("", CLAUSE.sub("", body)).strip(" \n;；,，/()（）.·-")


def load_blocklist():
    """a1a_reverted.tsv = 禁止重填名单(七道闸撤回的 + pro 判 bad 手工撤回的)。
    没有它,重跑会把手工撤回的 21 条 pro 判 bad 又填回来。"""
    ids = set()
    if REVLOG.exists():
        for i, ln in enumerate(open(REVLOG, encoding="utf-8")):
            if i:
                ids.add(int(ln.split("\t")[0]))
    return ids


STRICT = True   # A 方案:闸只留确定性极高的三道,模糊的交给 sweep_a1.py 全量 judge


def collect(conn):
    forms, trans = G.build_index(conn)   # ⚠️ forms 保留**原始大小写**,专名/缩写闸靠它
    allw = trans
    blocked = load_blocklist()
    rej = Counter()
    out = []
    for i, w, t in conn.execute(f"SELECT id, word, translation FROM stardict WHERE NOT {CORE}"):
        ws, body = w.strip(), (t or "").strip()
        if not is_shell(body):
            continue
        if i in blocked:
            rej["在禁止重填名单(已撤回过)"] += 1; continue
        m = BASE.search(body)
        if not m:
            rej["无法提取base"] += 1; continue
        base = m.group(1).strip().lower()
        # 短语 base 曾被整体当"伪复数族"剔除 —— 那条规则是从 saint bedes / genus aldrovandas
        # (圣人名、拉丁学名,本无复数)总结的,但**误伤了合法复合词**:horse brasses / social scientists
        # / home movies / big wheels / yellow peppers 都是正经名词的正经复数(误伤 36,205 条)。
        # → 改成只挡真正的伪变形来源:学名/地名式前缀 + 词头大写的专名,其余照常回填。
        if " " in base or "-" in base:
            if TAXONPFX.match(base):
                rej["base学名/地名式前缀(伪复数)"] += 1; continue
            if any(f[:1].isupper() for f in forms.get(base, set())):
                rej["base短语且词头大写(专名)"] += 1; continue
        bt = allw.get(base, "")
        if not bt:
            rej["base不在库"] += 1; continue
        if "[网络]" in bt:
            rej["base是[网络]众包"] += 1; continue
        if is_shell(bt):
            rej["base自己也是空壳"] += 1; continue
        if base == ws.lower():
            rej["base=词条自身"] += 1; continue
        if not re.search(r"[一-鿿]", bt):
            rej["base译文无汉字"] += 1; continue
        g = G.guards(ws, base, forms, trans, strict=STRICT)   # ← 闸,同时保证幂等
        if g:
            rej["闸拦下(" + g[0][0] + "…)"] += 1; continue
        out.append((i, ws, body, base, bt))
    return out, rej


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--all-guards", action="store_true", help="回到九道闸全开(B 方案)")
    a = ap.parse_args()

    global STRICT
    STRICT = not a.all_guards

    conn = sqlite3.connect(DB)
    cand, rej = collect(conn)
    print(f"[闸模式] {'A 方案·三道闸(模糊的交判官)' if STRICT else 'B 方案·九道闸全开'}")
    print("A1 空壳 → 筛 A1a,逐条剔除原因:")
    for k, v in rej.most_common():
        print(f"  {k:24} {v:>7}")
    print(f"\nA1a 候选 {len(cand)}")

    random.seed(2)
    for i, w, b, base, bt in random.sample(cand, min(8, len(cand))):
        print(f"\n  {w}\n    前: {b}\n    后: {(b + chr(10) + bt).replace(chr(10), ' ⏎ ')[:96]}")

    if not a.run:
        print("\n(dry-run;加 --run 写库)")
        return
    if not cand:
        print("\n无新候选,不动库(也不覆盖 a1a_fill.tsv 留痕)。")
        return

    conn.close()
    tag = datetime.now().strftime("%Y%m%d-%H%M")
    bak = DB.with_name(f"synapse-dict-en.pre-a1a-{tag}.bak")
    shutil.copy2(DB, bak)
    print(f"\n已备份 → {bak.name}")

    # ⚠️ 追加不覆盖:LOG 存着历次回填的"回填前原文",sweep_a1.py 要靠它撤回 bad。
    #    用 "w" 会把上一批(今天的 15,675 条)的留痕整个抹掉,那批就再也退不回去了。
    conn = sqlite3.connect(DB)
    fresh = not LOG.exists()
    with open(LOG, "a", encoding="utf-8") as f:
        if fresh:
            f.write("id\tword\tbase\tbefore\tafter\n")
        for i, w, b, base, bt in cand:
            new = b + "\n" + bt
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, i))
            conn.execute("UPDATE stardict SET qual='fixed' WHERE id=? AND qual NOT IN ('core','judged')", (i,))
            f.write("\t".join([str(i), w, base, b.replace("\t", " ").replace("\n", "\\n"),
                               new.replace("\t", " ").replace("\n", "\\n")]) + "\n")
    conn.commit()
    conn.close()
    print(f"已回填 {len(cand)} 条,留痕 → {LOG.name}")


if __name__ == "__main__":
    main()
