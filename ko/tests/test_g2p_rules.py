#!/usr/bin/env python3
"""G2P 的**外部锚闸**：锚在 표준발음법 条文自带的例词上。2026-09-21。

═══ 为什么不锚在韩文版（我们的标尺）上 ═══
标尺（`pronunciation.hangeul_phonetic`，65,926 行）是**统计尺**，回答"大面上对不对"。
但它**自己不一致**，实测两处：
    24항   `검다[검따]` 与 `넘다[넘다]` 并存；`다듬다[다듬따]` 与 `더듬다[더듬다]` 并存
    15항   `웃옷[우돋]` 遵守，`흩어보기[흐터보기]` 不遵守
⇒ 它不能回答"这一条规则本身写对了没有"。能回答的是**표준발음법自己举的例词** ——
  那是韩国国立国语院的条文原文，是这件事的权威源，**这道闸永不过期**
  （`[[external-anchor-gates]]`：锚外部权威的闸不过期，锚自己上一版的必然过期）。

═══ 🔴 这道闸是被抽样逼出来的，不是设计出来的 ═══
规则定版、开发半/留出半两组数都绿之后，随手跑了 26 个教科书词，
当场逮到 **`읽고`→`익꼬`（应 `일꼬`）**：
`rk_verbal` 判"是不是용언"用的是「以 -다 结尾」，而 `읽고` 是**活用形**、不以 다 结尾。
⇒ 标尺里变形形只有 438 个（2.1%），这个洞它**结构性看不见**。
⭐ 本项目第五次「缺陷由抽样逮到、由闸漏掉」。所以教训写成这份文件，不写成一句话。

跑（在仓库根）：
    python3 -u ko/tests/test_g2p_rules.py
"""
import sys as _sys
import pathlib as _pl
_ROOT = _pl.Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(_ROOT))
_sys.path.insert(0, str(_ROOT / "pipeline"))

import g2p

# (词, 期望发音形, verbal, sino, 出处)
# 🔴 `verbal` / `sino` 要**显式写**：真实调用方是从库里取的（词性 / `entry.hanja`），
#    不是靠 `-다` 猜的。这里写死，闸才量得到"规则对不对"而不是"猜得准不准"。
CASES = [
    # ── 음절의 끝소리 규칙（8·9항）──
    ("닭",       "닥",        False, False, "11항 겹받침 단순화"),
    ("값",       "갑",        False, False, "10항"),
    ("옷",       "옫",        False, False, "9항"),
    ("낮",       "낟",        False, False, "9항"),
    ("부엌",     "부억",      False, False, "9항"),
    # ── 연음（13·14항）──
    ("꽃이",     "꼬치",      False, False, "13항"),
    ("닭이",     "달기",      False, False, "14항"),
    ("넋이",     "넉씨",      False, False, "14항 ㅅ은 된소리로"),
    ("값어치",   "가버치",    False, False, "15항 실질형태소 ⚠️ 已知不通过，见文件末"),
    # ── ㅎ（12항）──
    ("좋아",     "조아",      True,  False, "12항 4"),
    ("많이",     "마니",      False, False, "12항 4 ＋ 연음"),
    ("놓다",     "노타",      True,  False, "12항 1"),
    ("밝히다",   "발키다",    True,  False, "12항 1 겹받침"),
    ("앉히다",   "안치다",    True,  False, "12항 1 겹받침"),
    # ── 구개음화（17항）──
    ("굳이",     "구지",      False, False, "17항"),
    ("같이",     "가치",      False, False, "17항"),
    ("닫히다",   "다치다",    True,  False, "17항 붙임"),
    # ── 비음화（18·19항）──
    ("국물",     "궁물",      False, False, "18항"),
    ("밥물",     "밤물",      False, False, "18항"),
    ("백로",     "뱅노",      False, True,  "19항 붙임"),
    ("종로",     "종노",      False, True,  "19항"),
    # ── 유음화（20항）──
    ("신라",     "실라",      False, True,  "20항"),
    ("칼날",     "칼랄",      False, False, "20항"),
    # ── 경음화（23·25항）──
    ("학교",     "학꾜",      False, True,  "23항"),
    ("옷고름",   "옫꼬름",    False, False, "23항"),
    ("짧다",     "짤따",      True,  False, "25항 ㄼ"),
    ("핥다",     "할따",      True,  False, "25항 ㄾ"),
    ("젊지",     "점찌",      True,  False, "25항 ㄻ ⚠️ 活用形，verbal 必须显式传"),
    # ── 겹받침 ＋ 자음（11항 但서）──
    ("읽고",     "일꼬",      True,  False, "11항 但서：용언 어간 ㄺ ＋ ㄱ"),
    ("맑고",     "막꼬",      False, False, "🔴 非용언 ⇒ ㄺ 读 ㄱ（与 읽고 相反）"),
    ("닭고기",   "닥꼬기",    False, False, "同上，名词"),
    ("밟다",     "밥따",      True,  False, "10항 但서 词汇例外"),
    ("넓적다리", "넙쩍따리",  False, False, "10항 但서 词汇例外"),
    ("넓다",     "널따",      True,  False, "10항 正例（对照上面两条）"),
    # ── ㅢ（5항 다만3）／ 져·쪄·쳐（5항 다만1）──
    ("희다",     "히다",      True,  False, "5항 다만3"),
    ("가져오다", "가저오다",  True,  False, "5항 다만1"),
    ("다쳐",     "다처",      True,  False, "5항 다만1 活用形"),
]

# 🔴 **明知过不了也留在闸里的条目**。判据见 `docs/KO_PLAN.md` §四.1-c：
#    15항 被标尺否掉了（修好 3 / 弄坏 5），我们**有意不施行**。
#    ⚠️ 留着它是为了「什么会推翻这个否定结论」有个挂钩的地方 ——
#       否定结论天然没有交付物、闸管不到它（`[[record-the-negative-decision]]`）。
#       哪天 15항 施行了，这一行会自己从 KNOWN_FAIL 掉出来。
KNOWN_FAIL = {"값어치"}


def main():
    bad, unexpected_pass = [], []
    for w, want, verbal, sino, why in CASES:
        got = g2p.to_phonetic(w, verbal=verbal, sino=sino)
        if got == want:
            if w in KNOWN_FAIL:
                unexpected_pass.append((w, want, why))
        elif w not in KNOWN_FAIL:
            bad.append((w, want, got, why))

    print("■ ko G2P 外部锚闸（표준발음법 例词 %d 条，其中已知不过 %d 条）"
          % (len(CASES), len(KNOWN_FAIL)))
    for w, want, got, why in bad:
        print("   🔴 %-10s 期望 %-10s 实得 %-10s   %s" % (w, want, got, why))
    for w, want, why in unexpected_pass:
        print("   ⚠️ %-10s 现在过了，但它还挂在 KNOWN_FAIL 里 —— "
              "把它移出去，并回 KO_PLAN §四.1-c 改那条否定结论   %s" % (w, why))
    if bad or unexpected_pass:
        raise SystemExit("🔴 不符 %d 条／意外通过 %d 条"
                         % (len(bad), len(unexpected_pass)))
    print("   ✅ 全部符合")


if __name__ == "__main__":
    main()
