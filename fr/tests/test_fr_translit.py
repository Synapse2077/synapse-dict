#!/usr/bin/env python3
"""`pipeline/fr_translit.py` 自己的准确率测试。2026-08-24。

═══ 🔴 为什么必须有这个 ═══
我拿这个译写器去核 26,470 个模型音译，第一次跑出「62.2% 不一致」。
**那个数不能用** —— 我修了 7 个 bug，它才挪到 60.4%，
说明我**分不清「剩下的是我的 bug」还是「模型真错」**。
拿一个自己没验过的判据去判别人，是 `[[criteria-narrower-than-you-think]]` 那族错误。

⇒ 先给校验器做真值。下面这批是我有把握的法国知名地名。

═══ ⚠️ 这份真值的局限，先说清楚 ═══
知名地名多是**约定译名**，而标准正文明写它**只管尚未被词典收录的地名**。
所以：
  · 通过 = 实现至少能复现已知答案，是**下界**
  · 不通过 ≠ 实现错，可能只是该名有约定译法（`Paris`→巴黎 谁也推不出来）
⇒ 真值分两组：**REGULAR**（按规则可推的）与 **EXONYM**（约定译名，只记录不计分）。

🔴 **我对那 26,470 个冷僻市镇没有任何独立真值** —— 模型和译写器在那批上**都没被验过**。
   所以两者的关系是「第二意见」，不是「判官与被判者」。

跑：python3 tests/test_fr_translit.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.fr_translit import translit   # noqa: E402

# 按规则可推的（多数与新华社译名一致）
REGULAR = {
    "Rouen": "鲁昂", "Caen": "卡昂", "Grenoble": "格勒诺布尔",
    "Bordeaux": "博尔多", "Conteville": "孔特维尔", "Elbeuf": "埃尔伯夫",
    "Bannes": "巴讷", "Mazerolles": "马泽罗勒", "Beaulieu": "博略",
    "Caumont": "科蒙", "Jonquières": "容基耶尔", "Aigues-Vives": "艾格维沃",
    "Saint-Christophe": "圣克里斯托夫", "Francheville": "夫朗什维尔",
    "Thil": "蒂尔", "Andilly": "昂迪伊",
}

# 约定译名：标准管不着，**只记录不计分**
EXONYM = {
    "Paris": "巴黎", "Lyon": "里昂", "Marseille": "马赛", "Versailles": "凡尔赛",
    "Nice": "尼斯", "Reims": "兰斯", "Metz": "梅斯", "Nancy": "南锡",
    "Dijon": "第戎", "Amiens": "亚眠", "Saint-Denis": "圣但尼",
    "Toulouse": "图卢兹", "Nantes": "南特", "Orléans": "奥尔良",
}


def run(pairs, label, score=True):
    ok, bad, none = 0, [], 0
    for fr, want in sorted(pairs.items()):
        got = translit(fr)
        if got is None:
            none += 1
            bad.append((fr, want, "—拆不出"))
        elif got == want:
            ok += 1
        else:
            bad.append((fr, want, got))
    n = len(pairs)
    print("\n── %s（%d 条）%s ──" % (label, n, "" if score else "  ※ 不计分"))
    if score:
        print("   命中 %d/%d = **%.0f%%**（拆不出 %d）" % (ok, n, 100.0 * ok / n, none))
    else:
        print("   与约定译名一致 %d/%d（其余是标准与约定的正常分歧）" % (ok, n))
    for fr, want, got in bad:
        print("     %-22s 期望 %-12s 实得 %s" % (fr, want, got))
    return ok, n


def main():
    ok, n = run(REGULAR, "按规则可推")
    run(EXONYM, "约定译名", score=False)
    print("\n%s" % ("✓ 可作为第二意见使用" if ok / n >= 0.8 else
                    "🔴 准确率不足，**不要拿它去判模型**"))
    return 0 if ok / n >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
