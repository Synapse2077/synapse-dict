#!/usr/bin/env python3
"""阶段 2e：从 `character` 条目的 `eumhun` form 补汉字音训（结清欠账 K3）。2026-09-21。

═══ 🔴 K3 的推翻条件兑现了 ═══
`hanja_reading.eumhun` 当初**有意留空**，账上写的推翻条件是：

> ①找到逐字结构化的 eumhun 源；或②能写出一条**两个独立信号一致**的判据

条件①成立了 —— 结构化的 eumhun **就在英文版 `character` 条目的 forms 里**：

    {"form": "개 견", "tags": ["eumhun"]}      `犬` 训「개」(狗) 音「견」
    {"form": "말 마", "tags": ["eumhun"]}      `馬` 训「말」(马) 音「마」
    {"form": "성 마", "tags": ["eumhun"]}      `馬` 训「성」(姓) 音「마」  ← 一个字多组音训

**3,449 条，涉及 2,889 个汉字**，逐条自带汉字归属 ——
不需要当初担心的那种「从信息框里按位置推断」（那才是最容易错配的做法）。

═══ 它同时解决了另一件事：478 个空白页 ═══
阶段 2d 建完关系层后仍有 **478 个词形是空白页**，查下来
**它们唯一的内容就是 eumhun**（`㐄 → 걸을 과`、`㐅 → 다섯 오`）——
全是生僻汉字，没有义项、没有变形、没有谚文对应。
⚠️ 这说明阶段 2a 那条判据（"forms/sounds/etym/rel 四样有一样就收"）**还是太宽**：
   **有 form ≠ 收进来之后页面上有东西**，因为那个 form 可能去向别的层、
   也可能哪一层都没接。⇒ 真正的判据只能是「**落库之后**这个词形挂得到内容」，
   而那必须等内容层建完才验得了（`[[measure-landing-not-source]]`）。

═══ 判据：音取最后一段，训取其余 ═══
    개 견            → 训「개」      音「견」    3,085 条（两段）
    열째 지지 유      → 训「열째 지지」 音「유」     310 条（三段）
    조정 (朝廷) 조    → 训「조정 (朝廷)」音「조」
    닭               → 训「닭」      音 **无**     15 条（只有训）
🔴 「最后一段是**单个谚文音节**」才算音 —— 实测 3,084/3,085 条两段的符合，
   唯一的例外 `비롯`（两段但末段不是单音节）按"没有音"处理，落账。
🔴 **音提不出来的不丢训**：`eumhun` 列原样存整串，`word_id` 挂不上的那些
   单独记在 `data/work/ko/eumhun_no_syllable.tsv`，不静默丢。

═══ 写法：已有行 UPDATE，没有的 INSERT ═══
`hanja_reading` 已有 8,594 行（来自 `syllable` 条目的「音→字」对照）。
同一个 (音节, 汉字) 两边都可能有 ⇒ **先 UPDATE 已有行，再 INSERT 剩下的**，
不制造重复（`UNIQUE(src_ref)` 拦不住语义重复，它只拦同一个来源位置）。

跑（在仓库根）：
    python3 -u ko/pipeline/fill_eumhun.py
    python3 -u ko/pipeline/fill_eumhun.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths

SRC = "en-edition"


def split_eumhun(v):
    """`개 견` → (`개`, `견`)。音取不出时返回 (整串, None)。"""
    parts = (v or "").split()
    if len(parts) >= 2 and len(parts[-1]) == 1 and "가" <= parts[-1] <= "힣":
        return " ".join(parts[:-1]), parts[-1]
    return (v or "").strip(), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    inentry = {r[1]: r[0] for r in con.execute("SELECT id, src_ref FROM entry")}
    # 已有的 (word_id, hanja) → id
    existing = {(r[1], r[2]): r[0] for r in con.execute(
        "SELECT id, word_id, hanja FROM hanja_reading")}
    con.close()

    seen_entry = collections.Counter()
    upd, ins, noSyl, dropped = [], [], [], []
    seen_pair = set()
    stat = collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        praw = o.get("pos")
        if praw == "romanization":
            continue
        w = o.get("word")
        if not w or not w.strip():
            continue
        en_ = o.get("etymology_number")
        etym = str(en_) if en_ is not None else "0"
        k = (w, praw, etym)
        seq = seen_entry[k]
        seen_entry[k] += 1
        eref = "kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq)
        for i, f in enumerate(o.get("forms") or []):
            if "eumhun" not in (f.get("tags") or []):
                continue
            stat["eumhun form"] += 1
            v = (f.get("form") or "").strip()
            if not v:
                continue
            hun, eum = split_eumhun(v)
            if eum is None:
                stat["🔴 提不出音（只有训）"] += 1
                noSyl.append((w, v, "无音"))
                continue
            wid = indict.get(eum)
            if wid is None:
                stat["🔴 音节不在 dict 里"] += 1
                noSyl.append((w, v, "音节 %s 不在 dict" % eum))
                continue
            if (wid, w) in seen_pair:
                stat["同 (音节,汉字) 重复（一字多组音训取第一组）"] += 1
                dropped.append((w, eum, v))
                continue
            seen_pair.add((wid, w))
            hid = existing.get((wid, w))
            if hid:
                upd.append((v, hid))
                stat["→ UPDATE 已有行的 eumhun"] += 1
            else:
                ins.append((wid, inentry.get(eref), w, None, v, None, SRC,
                            "%s#eumhun:%d" % (eref, i)))
                stat["→ INSERT 新行（syllable 条目没覆盖到的字）"] += 1

    for k, v in stat.most_common():
        print("   %-46s %9s" % (k, format(v, ",")))
    print("   %-46s %9s" % ("涉及的不同汉字", format(len({r[2] for r in ins} |
                                                       {u[1] for u in upd}), ",")))

    if noSyl:
        print("\n🔴 挂不上音节的 %d 条（**不丢**，落账）：" % len(noSyl))
        for x in noSyl[:6]:
            print("     %s" % (x,))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    paths.WORK.mkdir(parents=True, exist_ok=True)
    p = paths.WORK / "eumhun_no_syllable.tsv"
    with open(p, "w", encoding="utf-8") as f:
        f.write("hanja\teumhun\t原因\n")
        for x in noSyl:
            f.write("\t".join(x) + "\n")
        f.write("\n# 一字多组音训、本步只取第一组的：\n")
        for x in dropped:
            f.write("\t".join(x) + "\n")
    print("■ 挂不上的 %d 条 ＋ 多组音训里被略过的 %d 条 已落账 → %s"
          % (len(noSyl), len(dropped), p))

    with dbtool.session("fill-ko-eumhun",
                        expect={"#hanja_reading": len(ins)},
                        invalidates=[]) as s:
        s.executemany("UPDATE hanja_reading SET eumhun=? WHERE id=?", upd)
        s.executemany(
            "INSERT INTO hanja_reading (word_id, entry_id, hanja, gloss_en, "
            "eumhun, mc, src, src_ref) VALUES (?,?,?,?,?,?,?,?)", ins)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("eumhun 非空的行", q("SELECT COUNT(*) FROM hanja_reading "
                              "WHERE eumhun IS NOT NULL"), len(upd) + len(ins)),
        ("没有 (音节,汉字) 重复",
         q("SELECT COUNT(*) FROM (SELECT 1 FROM hanja_reading "
           "GROUP BY word_id, hanja HAVING COUNT(*)>1)"), 0),
        ("word_id 都指得到",
         q("SELECT COUNT(*) FROM hanja_reading h LEFT JOIN dict d ON d.id=h.word_id "
           "WHERE d.id IS NULL"), 0),
        # 🔴🔴 **本步的两个理由，各一条断言**
        ("K3 结清：eumhun 不再全空",
         q("SELECT COUNT(*) FROM hanja_reading WHERE eumhun IS NOT NULL") > 0, True),
        ("空白页清零（把「作为汉字被引用」也算内容）",
         q("SELECT COUNT(*) FROM dict d "
           "WHERE NOT EXISTS(SELECT 1 FROM sense WHERE word_id=d.id) "
           "  AND NOT EXISTS(SELECT 1 FROM inflection WHERE word_id=d.id) "
           "  AND NOT EXISTS(SELECT 1 FROM hanja_reading WHERE word_id=d.id) "
           "  AND NOT EXISTS(SELECT 1 FROM hanja_reading WHERE hanja=d.word) "
           "  AND NOT EXISTS(SELECT 1 FROM sense_relation WHERE word_id=d.id)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        gs = got if isinstance(got, bool) else format(got, ",")
        ws = want if isinstance(want, bool) else format(want, ",")
        print("   %s %-34s %10s（期望 %s）" % ("✅" if good else "🔴", name, gs, ws))
    print("\n■ 抽样：几个汉字的音训")
    for r in con.execute("SELECT hanja, eumhun, (SELECT word FROM dict WHERE id=word_id) "
                         "FROM hanja_reading WHERE eumhun IS NOT NULL "
                         "AND hanja IN ('犬','馬','国','㐄','㐅')"):
        print("     %-4s %-14s 音: %s" % r)
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
