#!/usr/bin/env python3
"""C20：交叉引用义项的中文 —— **免费补，一分钱不花**。2026-08-30。

═══ 这是什么 ═══
2,939 条可见义项没有中文。其中一大类是**交叉引用**：源头的释义本身就是「同某某词」。

    Antárctida   vide Antártida
    Abexia       mesmo que Abissínia
    Baharem      vide Bahrein

这类**不需要模型** —— 被引词的中文库里就有，取过来即可。
⭐ 风格与同族已译出的 1,257 条一致：给**被引词的意思本身**（`o mesmo que xorca` → `手镯`），
   不写「同 xorca」——「同 xorca」对查 `axorca` 的读者等于没说。

═══ 判据被数据打回两次 ═══
🔴 **第一次**：直接抄被引词的中文 ⇒ `Baharem → vide Bahrein → 「Barém 的异体形式」`。
   **被引词的中文本身又是个指针**，抄过来读者还是拿不到答案。⇒ 要顺着链走到底。

🔴 **第二次**：我写的"指针式中文"判据一跑圈了 4,956 条，里面全是**真释义**：
       tesauro  → 同义词词典，类义词词典
       dar      → 同意发生性行为
       civil    → 同国居民间的
       in       → 见于参考文献的
   根因：`^(同|参见|见)\\s*\\S+$` 里的 `\\S+` 把整句都吃了。
   **这是这个项目里同一形状第三次**（`[[criteria-narrower-than-you-think]]`：
   上一次差点隐掉 1,338 条有用释义，也是"指针措辞"这个判据）。
   ⇒ 按含义重写：**纯指针 = 整条中文只由「一个拉丁字母词 + 一个关系标签」构成，再无别的内容**。
     反向查：上面四条现在全部不圈；`á 的异体形式` / `milhão 的缩写` 仍然圈中。

═══ 保守在哪 ═══
· 被引词有**多个带中文的义项** ⇒ **不猜**（记账 C34）。
  「`o mesmo que X`」没说是 X 的第几个义项，猜错就是 `[[verification-gates-not-sampling]]`
  里用户点名的「义项和释义错配，那才是真灾难」。

🔴 **第三次打回**：`sense_gloss` 有 `kind`（equivalent/definition）与 `seq` 两列我一开始没看，
   把被引词的中文**按文本去重成集合**判"多不多义" ⇒ 同一个义项的 `equivalent` 行和
   `definition` 行被当成两个义项、整条跳过。⇒ 改成**按义项聚合、整组照搬**（kind/seq 一并复制），
   补出来的结构与库里其余中文完全同构。
· 被引词不在库里 ⇒ 不补（413 条）。
· 链走不通 / 成环 / 超过 5 跳 ⇒ 不补。
· `src='xref:resolved'` 单独记来源，**将来能一条 SQL 全部撤回**（`[[prefer-reversible-designs]]`）。

用法（在 pt/ 目录下）：
    python3 fixes/fill_xref_zh.py            # 干跑 + 自检 + 抽样
    python3 fixes/fill_xref_zh.py --apply
"""
import argparse
import collections
import random
import re
import sqlite3
import unicodedata
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SRC = "xref:resolved"
MAX_HOPS = 5

# 关系标签：**按含义列** —— 这些词只说"和谁的关系"，不说"是什么意思"。
# ⚠️ 标签可以**叠加**（`阴性复数` = 阴性 + 复数），所以下面用 `{LABEL}+`。
LABEL = (r"(?:异体形式|异体拼写|异体|大小写变体|变体形式|变体|旧称|旧写法|新写法"
         r"|另一种写法|另一种拼写|另一种形式|替代拼写|旧拼写|新拼写"
         r"|简称|缩写|复数|阴性|阳性|单数|同义词|拼写形式|拼法|误拼|错拼)")
LATIN = r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9'\-· ]*"
# 🔴 整条只有「拉丁词 + 关系标签」才算纯指针。`$` 前不许有别的内容 —— 这就是收窄的全部。
PURE = re.compile(rf'^\s*(?:同|参见|见|等同于)?\s*["“«\']?({LATIN})["”»\']?\s*'
                  rf'(?:的)?\s*{LABEL}+\s*[。．.]?\s*$')

# 源头的交叉引用措辞。按含义分组，不按长短。
# 🔴 第二轮扩表（2026-08-30，报价前把免费路径走完）。三条新形状：
#   D 构词指针  `pequenico` → `diminutivo de pequeno`   ⇒ 补「pequeno 的指小形式（小的）」
#   E 裸词指针  `górgone`   → `górgona`（整条释义就是一个词）
#   （另有归一匹配那条：`parquet` ← `parqué` 被归一成库里的 `parque`（**拼花地板 vs 公园**）
#     ⇒ **否掉**。葡语里变音符是区别性的，归一匹配只用于「词头与被引词是同一个词」那一种。）
DERIV_ZH = {"diminutivo": "指小形式", "aumentativo": "指大形式",
            "superlativo": "最高级", "comparativo": "比较级"}
DERIV = re.compile(r"^\s*(diminutivo|aumentativo|superlativo|comparativo)"
                   r"(?:\s+\w+)*\s+d[eoa]\s+(\S[^,;.:()]*)", re.I)
# 整条释义就是一个词（可带前置的括号标注 `(pouco usado) apêndice`）。
# ⚠️ 必须锚到串尾 —— 否则会把真定义的第一个词当成指针。
BARE = re.compile(r"^\s*(?:\([^)]*\)\s*)?([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\- ]{1,40})\s*[.]?\s*$")

REF_PATTERNS = [
    re.compile(r"^o?\s*mesmo que\s+([^,;.:()]+)", re.I),
    re.compile(r"^(?:vide|ver|veja)\s+([^,;.:()]+)", re.I),
    re.compile(r"^(?:variante|variação|grafia|ortografia)\s+(?:de\s+|do\s+|da\s+)?([^,;.:()]+)", re.I),
    re.compile(r"^forma\s+\w*\s*d[eoa]s?\s+([^,;.:()]+)", re.I),
    re.compile(r"^sigla\s+d[eo]\s+([^,;.:()]+)", re.I),
]


def referent(text):
    """源头释义 → (被引词, 附加标签)；不是交叉引用则 (None, None)。"""
    for p in REF_PATTERNS:
        m = p.match(text)
        if m:
            w = m.group(1).strip().strip("«»\"'“”")
            return (w or None), None
    m = DERIV.match(text)
    if m:
        return m.group(2).strip(), DERIV_ZH[m.group(1).lower()]
    m = BARE.match(text)
    if m:
        return m.group(1).strip(), None
    return None, None


def same_word(a, b):
    """词头与被引词是不是同一个词（只差大小写/变音符/连字符）。

    🔴 **只用于这一件事。** 拿它去库里"模糊找被引词"是错的 ——
       实测 `parqué` 会匹配到 `parque`（**拼花地板 vs 公园**），葡语里变音符是区别性的。
    """
    n = lambda x: re.sub(r"[\s\-·']", "",
                         "".join(c for c in unicodedata.normalize("NFD", x.lower())
                                 if not unicodedata.combining(c)))
    return n(a) == n(b)


def pure_pointer(g):
    return PURE.match(g)


def resolve(word, zh, seen=None, hops=0, pos=None, src_word=None):
    """顺着指针链走到底 → (中文行组, 跳数) 或 (None, 为什么不补)。

    `pos` = 发起引用的那条义项的词性。被引词有多个带中文的义项时，
    **若其中恰好一个的词性与之相同，就用它** —— `abissim [adj] → 阿比西尼亚的`
    与 `[n] → 阿比西尼亚人` 是两条不同的引用，词性把它们分得开。
    仍匹配到多条 ⇒ 不猜。
    """
    seen = seen or set()
    if hops > MAX_HOPS:
        return None, "链太长"
    if word in seen:
        return None, "成环"
    seen.add(word)
    senses = zh.get(word)
    if not senses:
        return None, "被引词不在库里"
    # 一个义项算"真释义"，只要它有任何一行不是纯指针
    real = [(p, rows) for p, rows in senses.values()
            if any(not pure_pointer(t) for _k, _q, t in rows)]
    if len(real) == 1:
        return real[0][1], hops
    if len(real) > 1:
        m = [rows for p, rows in real if pos and p == pos]
        if len(m) == 1:
            return m[0], hops
        # 🔴 词头与被引词**是同一个词**（只差大小写/变音符/连字符）⇒ 这不是歧义，
        #    异体拼写继承它全部的义项。`Primavera ← primavera`／`Grã Bretanha ← Grã-Bretanha`
        if src_word and same_word(src_word, word):
            merged = []
            for _p, rows in real:
                merged.extend(rows)
            return merged, hops
        return None, "被引词多义（词性也分不开，不猜）"
    # 全是纯指针 ⇒ 顺着任一条继续往下走
    for _p, rows in senses.values():
        m = pure_pointer(rows[0][2])
        if m:
            return resolve(m.group(1).strip(), zh, seen, hops + 1, pos, src_word)
    return None, "?"


# ⭐ 自检用例。后 6 条是**负控** —— 全部来自第一版判据误圈过的真释义。
CASES = [
    ("á 的异体形式", True), ("milhão 的缩写", True), ("Barém 的异体形式", True),
    ("同“esconder”，隐藏，藏匿", False), ("同义词词典，类义词词典", False),
    ("同意发生性行为", False), ("同国居民间的", False), ("见于参考文献的", False),
    ("南极洲", False),
    # ── 2026-08-30 扩表后新增：这些**必须**判为指针 ──
    ("agerato 的替代拼写", True), ("hemolinfático 的阴性复数", True),
    ("algodão das oliveiras 的旧拼写", True),
    # ── 负控：真释义带指针尾巴，**不许**被圈 ──
    ("食皮动物的阴性复数", False),
    ("研究罪的起源、本质和后果的神学分支；更佳形式为 hamartologia，此为通过增音形成的变体", False),
    ("介词 a 与指示代词 aquelas 及不定代词 outras 的缩合形式，àqueloutro 的阴性复数", False),
]


def main(a):
    print("■ 纯指针判据自检（%d 例，其中 %d 例负控 —— 都是第一版误圈过的真释义）"
          % (len(CASES), sum(1 for _t, w in CASES if not w)))
    bad = 0
    for t, want in CASES:
        got = bool(pure_pointer(t))
        if got != want:
            bad += 1
        print("   %s %-28s 判为%s" % ("✅" if got == want else "🔴", t, "指针" if got else "真释义"))
    if bad:
        print("🔴 自检不过，不动库")
        return 1

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 词 → {义项id: [(kind, seq, text), …]}。**按义项聚合**，不是按文本去重。
    zh = collections.defaultdict(dict)
    for w, sid, spos, kind, seq, g in con.execute(
            "SELECT d.word, s.id, s.pos, g.kind, g.seq, g.text "
            "  FROM sense s JOIN dict d ON d.id=s.word_id "
            "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' "
            " WHERE COALESCE(s.hidden,0)=0 ORDER BY g.seq"):
        zh[w].setdefault(sid, (spos, []))[1].append((kind, seq, g))
    rows = con.execute(
        "SELECT s.id, d.word, ss.text, s.pos FROM sense s JOIN dict d ON d.id=s.word_id "
        "  JOIN sense_src ss ON ss.sense_id=s.id "
        " WHERE COALESCE(s.hidden,0)=0 AND ss.lang='pt' "
        "   AND NOT EXISTS(SELECT 1 FROM sense_gloss g "
        "                   WHERE g.sense_id=s.id AND g.lang='zh')").fetchall()
    stat, hits = collections.Counter(), []
    for sid, w, t, spos in rows:
        r, label = referent(t)
        if not r:
            stat["① 不是交叉引用（判据够不着）"] += 1
            continue
        # 🔴 自指不是引用（`Unesco` 的释义就写着 `Unesco`）—— 那是源头残渣。
        #    放着不管会"碰巧"从这个词自己的另一条义项取到中文，答案对但机制是错的。
        if r == w:
            stat["② 释义就是词头自己（源头残渣）"] += 1
            continue
        g, why = resolve(r, zh, pos=spos, src_word=w)
        if g:
            if label:
                # 构词指针：**不能只写「pequeno 的指小形式」**（那是纯指针，等于没说），
                # 要把原形的意思带上 —— 读者查 `pequenico` 想知道的是「小的」。
                g = [(k, q, "%s 的%s（%s）" % (r, label, txt)) for k, q, txt in g]
            stat["✅ 免费可补"] += 1
            hits.append((sid, w, t, r, g, why))
        else:
            stat["✗ " + why] += 1
    f = lambda n: format(n, ",")
    print("\n■ 无中文的可见义项 %s 条" % f(len(rows)))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("   %6s  %s" % (f(v), k))
    hop = collections.Counter(h[5] for h in hits)
    print("   跳数：%s（>0 = 被引词的中文自己也是指针，继续往下走）" % dict(hop))

    random.seed(7)
    print("\n■ 抽 12 条人眼核：")
    for sid, w, t, r, g, h in random.sample(hits, min(12, len(hits))):
        print("   %-22s %-34s →%d跳→ %s"
              % (w[:22], t[:34], h, " / ".join(x[2] for x in g)[:32]))

    # 不变量：补进去的中文本身不许还是纯指针（否则等于没补）
    still = [h for h in hits if all(pure_pointer(t) for _k, _q, t in h[4])]
    print("\n   ✓ 不变量：补进去的中文里仍是纯指针的 %d（必须是 0）" % len(still))
    if still:
        return 1
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    # 🔴 `seq` 必须**在目标义项内重新编号**：`same_word` 那条路会把被引词的
    #    多个义项合并到一条义项下，两边的 `equivalent/seq=1` 会撞 PRIMARY KEY。
    ins, seen_txt = [], set()
    for sid, _w, _t, _r, rows, _h in hits:
        nxt = collections.Counter()
        for kind, _seq, txt in rows:
            if (sid, txt) in seen_txt:      # 合并后可能出现完全相同的中文，去重
                continue
            seen_txt.add((sid, txt))
            nxt[kind] += 1
            ins.append((sid, kind, nxt[kind], txt, SRC))
    with dbtool.session("fill-pt-xref-zh", expect={"#sense_gloss": len(ins)}) as s:
        s.executemany("INSERT INTO sense_gloss(sense_id, lang, kind, seq, text, src) "
                      "VALUES(?,'zh',?,?,?,?)", ins)
    print("\n✓ 免费补 %s 个义项 / %s 行中文（`src='%s'`，一条 SQL 可全撤）"
          % (f(len(hits)), f(len(ins)), SRC))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
