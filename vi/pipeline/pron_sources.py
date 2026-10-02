#!/usr/bin/env python3
"""**音标：三版怎么读、方言怎么归一** —— 只写一份。2026-09-28。

═══ 🔴🔴 方言归属是今天第三次「同一个概念，不同的地方」 ═══
①（早些时候）词源正文：en 版 `etymology_text` 单数 / vi·zh 版 `etymology_texts` 复数
②（早些时候）方言：en 版写 `tags:["Hà-Nội"]`，而**西贡音写在 `note:"Saigon"`**
③ 本文件：**同一个方言点有好几个名字**，而且分布在不同的版里

把三版带 `ipa` 的 sounds 上 `tags`/`note` 的**完整**值域打出来（21 个取值，不是前 8 个）：

    tags  Huế            76,338      tags  Hà-Nội         72,949
    note  Saigon         38,960   ←  en 版写 note
    tags  Saigon         38,945   ←  vi 版写 tags        **同一个点，两个字段**
    tags  Vinh           34,856      tags  Hà-Tĩnh        34,793
    tags  Thanh-Chương   34,788
    tags  General-American  274      tags  US   52    tags  China  2   ← **根本不是越南语**
    note  Quảng Nam 20 / Hội An 4 / Hoài Nhơn 3 / Phong Nha 1 / Đồng Hới 1  ← 小地点
    note  quick, colloquial speech 3 / with ngã-nặng merger 1   ← **不是方言，是语体/音变注**
    note  Wanwei, Wutou 1 / Gin 1   ← 京族（中国境内的越南族）

⇒ 三类东西混在同两个字段里：**方言点 / 非越南语 / 压根不是方言**。
  分不开的后果：`General-American` 的英语读音会挂在越南语词条上让读者照着读。

═══ 🔴 兜底一律**报错，不许静默归成 unknown** ═══
`[[residual-bucket-is-not-evidence]]` 今天第四次：如果把认不出的值默默写成 `unknown`，
那么**源头哪天加一个新方言点，我们会把它静默吞掉**，而所有闸都是绿的。
⇒ `classify()` 认不出就返回 `None` 并要求调用方计数，建库脚本**见到就红**。

═══ 外壳：存裸，但先确认剥掉的是哪一种 ═══
实测 **99.98% 是 `[…]`（音位实现）**，只有 23 条是 `/…/`（音位），
而同一 (词, 方言) 下同时出现两种外壳的**只有 1 组**。
⇒ 剥壳安全。⚠️ 这个 1 是已知残差，写在这儿；不是「没有冲突」。
"""
import re

# ── 六个方言点 ＋ 别名。**这张表就是值域**，认不出的一律报错 ─────────────
_HA_NOI = "ha-noi"
_SAI_GON = "sai-gon"
DIALECTS = {
    # 北部
    "Hà-Nội": _HA_NOI, "Hanoi": _HA_NOI, "Hanoi Vietnamese": _HA_NOI,
    # 南部 —— 🔴 en 版写在 note，vi 版写在 tags，名字还不止一个
    "Saigon": _SAI_GON, "Ho Chi Minh City": _SAI_GON,
    "Hồ-Chí-Minh-City": _SAI_GON, "TP.HCM": _SAI_GON,
    # 中部
    "Huế": "hue", "Vinh": "vinh",
    "Thanh-Chương": "thanh-chuong", "Hà-Tĩnh": "ha-tinh",
    # 小地点：量很小（≤20）但**是真的越南语方言**，给它们自己的槽，不塞进六点里
    "Quảng Nam": "quang-nam", "Hội An": "hoi-an", "Hoài Nhơn": "hoai-nhon",
    "Phong Nha": "phong-nha", "Đồng Hới": "dong-hoi",
    # 京族（中国广西的越南族）—— 是越南语的一支
    "Gin": "gin", "Wanwei, Wutou": "gin",
    # ── 阶段 6（2026-10-01）补的三个值。**它们是录音层逼出来的，不是我想起来的** ──
    # 🔴🔴 为什么音标层四道闸全绿却漏了它们：这几条 `sounds` 项**只有 `audio` 没有 `ipa`**，
    #    而音标层只处理带 `ipa` 的项 ⇒ 它们的 `tags`/`note` 从来没被 `classify()` 看过。
    #    `[[correct-steps-can-compose-a-hole]]`：每步都对，跨步的假设
    #    （「方言值域已经被音标层穷举过了」）失效 ⇒ 谁都没负责的洞。
    #    ⭐ 逮到它的机制是 `classify()` 的 `unknown-value` 兜底**要求调用方报红** ——
    #       静默归成 unknown 的话，这三个值会悄悄消失而所有闸照样绿。
    # ⚠️ 两个是**区域级**而不是六个点那样的城市级，所以给它们自己的槽，
    #    **不许折进最近的那个点**（`South Central Coast` 折成 `hue` 是替源头下结论）。
    "South Central Coast": "south-central-coast",   # 南中部沿海（Nam Trung Bộ）10 条，en 版 note
    "North": "north",                               # 北部，1 条，ko 版 tags
}

# 🔴 **不是越南语的读音**：整条丢掉，不是归到 unknown。
#    它们是外来词条目上顺带给的英语/汉语读音，印在越南语词典里会让读者照着读错。
NOT_VIETNAMESE = {"General-American", "US", "China", "UK", "Received-Pronunciation"}

# ⚠️ **不是方言，是语体或音变注**：这种行仍然有有效 IPA，
#    只是这一条注解说明不了它属于哪个点 ⇒ 方言取同条的 tags，取不到才 unknown。
NOT_A_DIALECT = {
    "quick, colloquial speech", "with ngã-nặng merger",
    "Hội An; phonetic spelling khúa",      # 带了个拼写说明，地点部分另有 Hội An 一条
    # 阶段 6（录音层）逮到的：ru 版把**语法数**写进了 sounds 的 tags。
    # 它压根不是方言，也不是语体 —— 但同样不许静默归成 unknown 而不留痕
    "singular",
}

MAIN_SIX = (_HA_NOI, "hue", _SAI_GON, "vinh", "thanh-chuong", "ha-tinh")


def classify(tags, note):
    """→ (dialect, verdict)。

    verdict ∈ {"ok", "drop-not-vietnamese", "unknown-value"}。
    🔴 `unknown-value` **必须让调用方报红** —— 静默归成 'unknown' 就等于
       源头加了新方言点我们悄悄吞掉，而所有闸照样绿。
    """
    vals = [v for v in (tags or []) if v] + ([str(note)] if note else [])
    if not vals:
        return "unknown", "ok"
    if any(v in NOT_VIETNAMESE for v in vals):
        return None, "drop-not-vietnamese"
    for v in vals:
        if v in DIALECTS:
            return DIALECTS[v], "ok"
    if all(v in NOT_A_DIALECT for v in vals):
        return "unknown", "ok"
    return None, "unknown-value"


# ── 外壳：存裸 ──────────────────────────────────────────────────────────
_SHELL = re.compile(r"^\s*[\[/]\s*(.*?)\s*[\]/]\s*$")


def strip_shell(ipa):
    """`[ʔaː˧˧]` / `/viət˨˨/` → 裸串。`[[ipa-bare-storage-convention]]`，展示层再加 `/…/`。"""
    m = _SHELL.match(ipa or "")
    return (m.group(1) if m else (ipa or "")).strip()


# ── B10：X-SAMPA 冒充 IPA ───────────────────────────────────────────────
# 🔴 判据里有方括号字符类，SQL 侧**必须用 GLOB 不能用 LIKE**
#    （LIKE 不认方括号，写成 LIKE 就是一条永远不响的闸）。
#    实测 vi 三版当下命中 **0** —— 但闸要留着：阶段 4 收词会引进新的源。
XSAMPA = re.compile(r"[0-9`\\_]")
XSAMPA_GLOB = r"*[0-9`\_]*"


def looks_like_xsampa(ipa):
    return bool(XSAMPA.search(ipa or ""))
