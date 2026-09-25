#!/usr/bin/env python3
"""§四.1-c 的「后用」那一半：给没有读音的词形补规则生成的读音。2026-09-21。

═══ 用户 2026-09-21 拍板：**全量出版 ＋ 分档标源** ═══
我给了三个选项（全量出版 / 只出安全子集 46,308 个 / 只进证据层），用户选**全量**。
两家外审在这一问上给了**相反**答案（v4pro 主张不出版、豆包主张只出子集），
而**两家的理由各自有一半不成立**，数在 `docs/KO_PLAN.md` §四.5：
  · v4pro：「你没有定义出零错子集」⇒ 定义出来了，**但它也不是零错**（99.06%）
  · 豆包：「安全子集准确率 100%」⇒ **实测不成立**，7,423 个里错 33 个
⭐ 决定性的一条两家都不知道：**it 那一门已经在线上出版了 431,859 条自己 G2P 算的音标**
  （占它音标层 73.4%），两条路径实测只有 83.9% 和 44.8%。
  ⇒ 本项目的先例不是"G2P 能不能出版"，是**按实测准确率分档**。韩语这套 98.73%。

═══ 🔴 这批行与人工读音的区别，必须**在数据里**，不能只在展示层 ═══
    src     = 'g2p'            ← 与 `en-edition` / `ko-edition` 等人工源并列，可查询可排序
    src_ref = 'g2p:<版本>'      ← 规则集改了这个字符串就变 ⇒ 哪些行是哪一版算的，可回溯
`[[aim-for-perfect-not-cheap]]`：别用展示层补丁代替把事情做进数据里。

═══ `verbal` / `sino` 从**库里取**，不在这儿猜 ═══
两条采纳的规则要知道「这是不是용언」（`rk_verbal` 的 ㄺ+ㄱ、`verbal_tense` 的 ㄻ）。
判据：**`entry.pos ∈ {v, adj}` 是正面证据；`-다` 词尾是兜底代理。**
🔴 **`pos` 说"不是用言"不作数** —— 实测源头在这批词上是错的：
   143 个 `-다` 词被标成 `pos='n'`，抽样全是用言（`가차없다`/`간사스럽다`/`가량없다`）。
   中文版 pos 99.5% 是 `unknown`，剩下 0.5% 也不可信。
⚠️ 代理的已知误伤是 `아나콘다`/`람다`/`롼다` 这类外来语名词（见 §四.5 的 24항 那张表）。
   它们在这一步**不造成差异**：采纳的两条规则只在**겹받침**（ㄺ/ㄻ）上触发，
   而外来语名词的倒数第二音节几乎不可能是겹받침 —— 这不是运气，
   是採纳线「弄坏 ≤ 修好的 5%」筛出来的结果。实测两种判据下发音形不同的有 **0 个**。

═══ 🔴 不做的事 ═══
· **不生成长音符 `(ː)`** —— 词汇性的，拼写里没有这个信息（`눈`雪 vs `눈`眼）
· **不碰已有读音的词形** —— 一个字段一个写入方；这一步只填空
· **不碰变形形**（`inflection.word_id` 里的 32 万个）—— 用户定的是那 18 万词元的口径，
  变形形要不要补是**另一个决定**，不在这一步顺手扩大（`[[es-only-scope]]` 同一条精神）

跑（在仓库根）：
    python3 -u ko/pipeline/fill_g2p_pronunciation.py
    python3 -u ko/pipeline/fill_g2p_pronunciation.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import sqlite3

import dbtool
import paths
from pipeline import g2p

SRC = "g2p"
SRC_REF = "g2p:" + g2p.fingerprint()
# 🔴 `src_ref` 里带的是 `g2p.fingerprint()` —— **规则的行为指纹，不是手写的版本号**。
#    手写版本号的问题是它**要靠人记得改**，而"忘了改"和"没变"在库里长得一模一样。
#    指纹从「一组固定探针词上的输出」算出来：凡是会改变落库内容的改动都会变，
#    改注释不会变。⇒ 账本闸 P10 拿库里的指纹与当前代码比，对不上就红。
NOTATION = "narrow"         # 标尺 98.6% 是窄式，生成的也是窄式（`ipa-bare-storage-convention`）
BATCH = 50000

VERB_POS = {"v", "adj"}

# 🔴 **这里本来有一个 `NOUNISH` 否决项（"库里说是名词就不许用 -다 代理"），2026-09-21 删掉。**
# 删的理由是两个**测量**，不是简洁：
#   ① 那个字段在这批词上**是错的**：目标里 143 个 `-다` 词被源头标成 `pos='n'`，
#      而抽样看全是用言 —— `가차없다`（毫不留情）、`간사스럽다`（奸诈）、`가량없다`。
#      中文版的 pos 99.5% 是 `unknown`，剩下那 0.5% 也不可信。
#   ② 它**买不到任何东西**：采纳的两条用到 `verbal` 的规则（`rk_verbal` 的 ㄺ＋ㄱ、
#      `verbal_tense` 的 ㄻ）都只在**겹받침**上触发，而外来语名词（`아나콘다`/`람다`/
#      `판다`）的倒数第二音节几乎不可能是겹받침。
#      实测：加与不加这个否决项，180,226 个词里**发音形不同的有 0 个**。
# ⇒ 留着它＝拿一个已证伪的字段换零收益的"看起来更严谨"。
# 🔴 什么会让它回来：若将来采纳了一条在**겹받침之外**也用 `verbal` 的规则
#    （比如翻案后的 24항），这个否决项要重新量 —— 而且**得先验证源头的 pos**。


# 🔴 口径只写一份，落库与回核**共用它** —— 但回核**不许拿它算出来的列表当期望值**，
#    见 `main()` 里那段。判据写成 SQL 是为了「写进去的」和「验出来的」出自同一句话。
# ⚠️ 条件是「没有**人工**读音」，不是「没有任何读音」：
#    后者在 `--rebuild` 时会把自己写过的行算成"已经有读音了"⇒ 候选集变空。
#    2026-09-21 就这么把 180,226 行删掉而没写回去，**而写后回核报了全绿**
#    （它拿库里的 0 与同一个坏列表的 0 比，两个 0 同源 ⇒ 恒等）。
# ⚠️ 第三个条件「整词都是谚文音节」原来只写在 Python 里，SQL 里没有 ⇒
#    **同一条判据两份、两份不一样**（SQL 说 233,142，实际填 180,226）。
#    新加的独立回核当场报红 —— 这是它第一次上岗就逮到东西。
#    🔴 `GLOB` 的否定字符类是 `[^…]`；写成 `[!…]` 不报错，只是**静默给出别的数**
#      （53,755 对 568,820）。
TARGET_SQL = """
    SELECT d.id, d.word FROM dict d
     WHERE NOT EXISTS (SELECT 1 FROM pronunciation
                        WHERE word_id = d.id AND src <> 'g2p')
       AND NOT EXISTS (SELECT 1 FROM inflection WHERE word_id = d.id)
       AND d.word <> '' AND d.word NOT GLOB '*[^가-힣]*'
"""


def load_targets(con):
    """要补读音的词形。**口径写死在 `TARGET_SQL` 里，这儿不再加过滤。**"""
    return con.execute(TARGET_SQL).fetchall()


def load_signals(con):
    """→ (verbal:set, sino:set)。两个信号都来自库，不来自词形的样子。"""
    pos = collections.defaultdict(set)
    for w, p in con.execute(
            "SELECT d.word, e.pos FROM entry e JOIN dict d ON d.id = e.word_id"):
        pos[w].add(p)
    sino = {r[0] for r in con.execute(
        "SELECT DISTINCT d.word FROM entry e JOIN dict d ON d.id = e.word_id "
        "WHERE e.hanja IS NOT NULL")}
    return pos, sino


def is_verbal(w, pos):
    """库里的 `pos` 说是 v/adj 就信；说别的不作数（见上面那段）；其余用 `-다` 代理。"""
    return bool(pos.get(w, set()) & VERB_POS) or w.endswith("다")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rebuild", action="store_true",
                    help="删掉已有的 g2p 行**重算**。⚠️ 规则改了就该走这条路 —— "
                         "**不许只改 src_ref 的盖章**，那是拿新版本号给旧内容背书")
    a = ap.parse_args()

    print("■ 规则集行为指纹 %s（落进每一行的 src_ref）" % g2p.fingerprint())
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = con.execute("SELECT COUNT(*) FROM pronunciation WHERE src = ?",
                       (SRC,)).fetchone()[0]
    if have and not a.rebuild:
        old = [r[0] for r in con.execute(
            "SELECT DISTINCT src_ref FROM pronunciation WHERE src=?", (SRC,))]
        raise SystemExit("🔴 已有 %d 行 src='g2p'（指纹 %s）—— **一个字段一个写入方**。\n"
                         "   规则变了就 --rebuild 重算，别在旧行上盖新章。"
                         % (have, "、".join(old)))
    tgt = load_targets(con)
    pos, sino = load_signals(con)
    con.close()
    # 🔴 **空候选集必须当场炸，不许静默走完。** `--rebuild` 那次就是候选集悄悄变空，
    #    删掉 18 万行、写回 0 行，而每一条写后回核都绿（期望值来自同一个空列表）。
    if have and not tgt:
        raise SystemExit("🔴 库里有 %d 行 g2p 却算出 0 个候选 —— 口径自己把自己排除了。"
                         "**不许继续**，否则就是删了不写回。" % have)

    rows, stat = [], collections.Counter()
    for wid, w in tgt:
        verbal = is_verbal(w, pos)
        ph = g2p.to_phonetic(w, verbal=verbal, sino=(w in sino))
        ipa = g2p.to_ipa(ph)
        if not ipa.strip():
            stat["🔴 算不出 IPA（已跳过）"] += 1
            continue
        stat["要写的行"] += 1
        stat["发音形 == 拼写形"] += (ph == w)
        stat["用言（按库里 pos）"] += (w in pos and bool(pos[w] & VERB_POS))
        stat["用言（只能靠 -다 代理）"] += (verbal and not (pos.get(w, set()) & VERB_POS))
        stat["🔴 源头 pos 说是 n 但以 -다 结尾"] += (
            w.endswith("다") and "n" in pos.get(w, set()))
        rows.append((wid, None, ipa, NOTATION, ph, None, None, None, 0, SRC, SRC_REF))

    print("■ 口径：无读音 ＋ 不是变形形 ＋ 整词纯谚文")
    print("   %-30s %9s" % ("命中词形", format(len(tgt), ",")))
    for k, v in stat.most_common():
        print("   %-30s %9s" % (k, format(v, ",")))
    print("\n■ 抽样（人眼看一遍 —— 本项目五次缺陷都是抽样逮到的，不是闸）")
    for wid, _, ipa, _, ph, *_ in rows[:4] + rows[len(rows) // 2:len(rows) // 2 + 4] \
            + rows[-4:]:
        w = dict(tgt)[wid]
        print("     %-14s → %-14s  %s" % (w, ph, ipa))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session(
            "fill-ko-g2p-pronunciation",
            expect={"#pronunciation": len(rows) - have},
            invalidates=[
                "🔴 **读音覆盖率从此是两个数**：`人工读音覆盖` 与 `含规则生成的覆盖`。"
                "验收与任何对外报数**必须分开报** —— 合成一个数就等于把 98.73% 的"
                "规则结果说成了人工源的品质",
                "展示层（阶段 9）：必须按 `src` 分档，`g2p` 不许与四版人工源混成一样",
                "阶段 8 的回归闸：要新增一条「src='g2p' 的行数与 `g2p:` 版本号对得上」，"
                "否则规则集改了而旧行还躺着，没人会发现",
            ]) as s:
        if have:
            s.execute("DELETE FROM pronunciation WHERE src=?", (SRC,))
            s.written += have
        for i in range(0, len(rows), BATCH):
            s.executemany(
                "INSERT INTO pronunciation (word_id, entry_id, ipa, notation, "
                "hangeul_phonetic, region, tags, pos, is_primary, src, src_ref) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows[i:i + BATCH])
            print("   …已写 %s 行" % format(min(i + BATCH, len(rows)), ","))

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    # 🔴 期望值**从库里重新算一遍口径**，不用 `len(rows)`。
    #    用 `len(rows)` 时，生成侧坏了会让期望值跟着坏 ⇒ 两个坏数相等 ⇒ 恒绿。
    want_n = len(con.execute(TARGET_SQL).fetchall())
    checks = [
        ("g2p 行数（期望＝按口径重算）",
         q("SELECT COUNT(*) FROM pronunciation WHERE src='g2p'"), want_n),
        # 🔴 读者口径：符合口径的词形**一个都不许没有** g2p 行
        ("符合口径却没拿到 g2p 行的词形",
          q("SELECT COUNT(*) FROM (%s) t WHERE NOT EXISTS("
           "SELECT 1 FROM pronunciation p WHERE p.word_id=t.id AND p.src='g2p')"
           % TARGET_SQL.replace("d.id, d.word", "d.id AS id, d.word AS word")), 0),
        ("src_ref 都是当前指纹",
         q("SELECT COUNT(*) FROM pronunciation WHERE src='g2p' AND src_ref<>'%s'"
           % SRC_REF), 0),
        # 🔴 **裸存自证**：展示层会自己加 `[ ]`，库里再带一层就是双括号
        ("ipa 里没有定界符残留",
         q("SELECT COUNT(*) FROM pronunciation WHERE src='g2p' "
           "AND (ipa LIKE '[%' OR ipa LIKE '/%')"), 0),
        # 🔴 我们有意不生成长音 ⇒ 生成行里出现 ː 就是串源了
        ("g2p 行不带长音符",
         q("SELECT COUNT(*) FROM pronunciation WHERE src='g2p' AND ipa LIKE '%ː%'"), 0),
        # 🔴 发音形必须是谚文；IPA 里不许有谚文
        ("发音形里没有拉丁字母",
         q("SELECT COUNT(*) FROM pronunciation WHERE src='g2p' "
           "AND hangeul_phonetic GLOB '*[a-zA-Z]*'"), 0),
        ("ipa 里没有谚文",
         q("SELECT COUNT(*) FROM pronunciation WHERE src='g2p' "
           "AND ipa GLOB '*[가-힣]*'"), 0),
        # 🔴 **只填空，不覆盖**：有人工读音的词形不许出现 g2p 行
        ("没有覆盖到已有人工读音的词形",
         q("SELECT COUNT(*) FROM pronunciation p WHERE p.src='g2p' AND EXISTS("
           "SELECT 1 FROM pronunciation q WHERE q.word_id=p.word_id AND q.src<>'g2p')"), 0),
        ("word_id 都指得到",
         q("SELECT COUNT(*) FROM pronunciation p LEFT JOIN dict d ON d.id=p.word_id "
           "WHERE p.src='g2p' AND d.id IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-32s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    # ⭐ 覆盖率**分两个数报**，这是 `invalidates` 里那条声明的兑现
    lem = q("SELECT COUNT(*) FROM dict d WHERE NOT EXISTS("
            "SELECT 1 FROM inflection WHERE word_id=d.id)")
    man = q("SELECT COUNT(DISTINCT p.word_id) FROM pronunciation p JOIN dict d "
            "ON d.id=p.word_id WHERE p.src<>'g2p' AND NOT EXISTS("
            "SELECT 1 FROM inflection WHERE word_id=d.id)")
    allc = q("SELECT COUNT(DISTINCT p.word_id) FROM pronunciation p JOIN dict d "
             "ON d.id=p.word_id WHERE NOT EXISTS("
             "SELECT 1 FROM inflection WHERE word_id=d.id)")
    print("\n   词元 %s" % format(lem, ","))
    print("   ├ **人工读音**覆盖      %9s  %5.1f%%   ← 这个数没有因为本步变大"
          % (format(man, ","), 100 * man / lem))
    print("   └ 含规则生成的覆盖      %9s  %5.1f%%" % (format(allc, ","), 100 * allc / lem))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
