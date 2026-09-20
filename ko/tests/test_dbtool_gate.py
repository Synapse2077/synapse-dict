#!/usr/bin/env python3
"""ko 写库闸门自身的**变异验证** —— `PLAYBOOK` 7.3：一条永远通过的检查等于没检查。

═══ 为什么这份文件在库还不存在的时候就有 ═══
`PLAYBOOK` 1.4 说闸门不能推后。但"闸门存在"和"闸门拦得住"是两回事 ——
ja 的 TRACK 列了 23 个字段而实际只守住 4 个，整整一个项目没人发现，
**因为从来没有人问过它「你现在拦得住什么」**。
⇒ 这份文件问的就是这个，而且它在**空库**上就能跑（M1/M2 靠的正是空库那条路径）。

跑：`python3 ko/tests/test_dbtool_gate.py`（退出码非零＝有闸没拦住）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dbtool


def check_brief():
    """→ [(编号, 说明), ...]，空列表＝全绿。给 `dbtool` 挂闸用的简报接口。"""
    red = []

    def want(cid, name, cond, detail=""):
        if not cond:
            red.append((cid, "%s %s" % (name, detail)))

    def want_lazy(cid, name, fn, detail=""):
        """条件**延迟求值**，并且求值时抛异常也算红。

        🔴🔴 这个函数是变异验证自己逼出来的（2026-09-20）：
        原来十七条检查全部写成 `want(cid, name, <直接求值的表达式>)`，于是我把
        `_ZH_SRC` 变异成「漏掉繁体片」时，`is_chinese_text` 在**参数求值阶段**
        抛了 `ValueError` —— `check_brief()` 整个崩掉，
        **后面的 M4e / M4f / M5 / M6 一条都没跑**。

        也就是说：一条判据坏掉，闸不是报「1 条红」，而是**丢掉剩下的 70% 覆盖面**，
        且对外表现成「闸自己坏了」而不是「闸逮到东西了」。
        （`[[criteria-narrower-than-you-think]]` 的又一个形状：
        清单上有 17 条，真正跑得到的只有前 12 条。）
        ⇒ 凡是**可能抛异常**的判据一律走这里。
        """
        try:
            cond = fn()
        except Exception as e:
            red.append((cid, "%s —— 求值时抛异常：%s: %s" % (name, type(e).__name__, e)))
            return
        want(cid, name, cond, detail)

    # ── M1/M2：两条**结构性**的拦截，它们是空库上唯一跑得到的写库路径 ──
    # 🔴 M1 的意义：库被误删 / paths.DB 写错时，静默从零开始写比报错危险得多
    #    （`[[backup-retention]]` 咬过六次的都是「删数据的默认值不够保守」这个形状）。
    try:
        with dbtool.session("fix-something", expect={}):
            pass
        want("M1", "空库上的非建库写入", False, "**没拦住**")
    except SystemExit as e:
        want("M1", "空库上的非建库写入", "不是建库步骤" in str(e), str(e)[:60])

    # 🔴 M2 的意义：同一个形状发生过三次（pt 变形层 46.2% 空白页／ja 读音层
    #    99.90%→39.8%／ja 中文覆盖 98.66%→70.77%），三次都写了教训、三次都没拦住下一次。
    #    ⚠️ ko 的收词预计是七门里最大的一次 ⇒ 这条尤其要真的拦得住。
    try:
        with dbtool.session("ingest-edition", expect={"__rows__": 150000}):
            pass
        want("M2", "插 15 万行却不声明 invalidates", False, "**没拦住**")
    except SystemExit as e:
        want("M2", "插 15 万行却不声明 invalidates", "invalidates" in str(e), str(e)[:60])

    # ── M3：`has_hangul` 按**内容**判，不按整块码位判 ──
    #    ja 在这条上栽过（`・` 落在片假名区 ⇒ 纯汉字日语被判成"带假名"）。
    # 🔴🔴 每条只许测**一段区间**，测试串里不许混进别段的字符。
    #    2026-09-20 变异验证当场逮到：M3b 原来写的是 `"ㄷ 불규칙"` ——
    #    把 `_HANGUL_RANGES` 砍成只剩音节区（兼容字母区整个删掉），
    #    **十七条检查一条都不红**，因为 `불규칙` 三个字自己就在音节区里，
    #    它替被测的那段区间**背了书**（`[[criteria-narrower-than-you-think]]`
    #    的反面：判据比它要描述的东西更宽）。
    #    ⇒ 兼容字母那条改成**孤立的单字**，它红不红只取决于那一段在不在。
    want("M3a", "谚文音节区 사람", dbtool.has_hangul("사람"))
    want("M3b", "兼容谚文字母区 —— **孤立的** `ㄷ`（`ㄷ 불규칙` 这类活用类标签的字头）",
         dbtool.has_hangul("ㄷ"))
    want("M3b2", "谚文字母区（조합형）—— 孤立的初声 `ᄀ`", dbtool.has_hangul("ᄀ"))
    want("M3b3", "半角谚文区 —— 孤立的 `ﾡ`", dbtool.has_hangul("ﾡ"))
    want("M3c", "纯汉字韩语词 符號 不算带谚文", not dbtool.has_hangul("符號"))
    want("M3d", "中文不算带谚文", not dbtool.has_hangul("中文释义"))
    want("M3e", "带括号谚文 ㈀ **有意排除**（符号不是字母）", not dbtool.has_hangul("㈀"))
    want("M3f", "带圆圈谚文 ㉠ **有意排除**", not dbtool.has_hangul("㉠"))

    # ── M4：`is_chinese_text` 三步，纯汉字必须拿到 src 才肯答 ──
    # ⚠️ 以下全部走 `want_lazy`：`is_chinese_text` **有意**会抛异常，
    #    直接求值会在参数阶段炸掉整个 check_brief（见 `want_lazy` 的文件注释）。
    want_lazy("M4a", "带谚文 ⇒ 不是中文", lambda: dbtool.is_chinese_text("사람") is False)
    want_lazy("M4b", "罗马字串 ⇒ 不是中文", lambda: dbtool.is_chinese_text("gyoga") is False)
    # 🔴 中文版**两片都要认**：少写一个名字，那一片的译文会被判成"没翻译"
    want_lazy("M4c", "纯汉字 + 简体片源 ⇒ 是中文",
              lambda: dbtool.is_chinese_text("符號", "zh-edition-simp") is True)
    want_lazy("M4d", "纯汉字 + 繁体片源 ⇒ 是中文",
              lambda: dbtool.is_chinese_text("符號", "zh-edition-trad") is True)
    want_lazy("M4e", "纯汉字 + 韩语源 ⇒ 不是中文",
              lambda: dbtool.is_chinese_text("符號", "ko-edition") is False)
    try:
        dbtool.is_chinese_text("符號")
        want("M4f", "纯汉字无 src 时**拒绝猜**", False, "**没抛异常** —— 它猜了")
    except ValueError as e:
        want("M4f", "纯汉字无 src 时**拒绝猜**", "分不出中韩" in str(e))

    # ── M5：汉字判据不许只查基本区（元素字/鸟名/鱼名在扩展区，词典里大量出现）──
    want("M5a", "扩展 F 区 𬭊（化学元素字）", dbtool.has_han_char("𬭊"))
    want("M5b", "扩展 A 区 䴙（鸟名）", dbtool.has_han_char("䴙"))

    # ── M6：`has_han` 这个名字必须**不存在** ──
    # 🔴 从另外七门拷来的脚本必然写着 `dbtool.has_han(...)`。留着它＝静默给错答案；
    #    删掉它＝`AttributeError` 当场炸。`[[prefer-reversible-designs]]`
    want("M6", "`has_han` 这个名字不存在", not hasattr(dbtool, "has_han"),
         "**它存在了** —— 拷过来的脚本会静默拿到错答案")

    return red


if __name__ == "__main__":
    red = check_brief()
    if red:
        print("🔴 闸的变异验证未通过：%d 条" % len(red))
        for cid, why in red:
            print("   %-5s %s" % (cid, why))
        sys.exit(1)
    print("■ ko 写库闸门变异验证通过 ✓（每一条都验的是「它拦得住什么」，不是「它存在」）")
