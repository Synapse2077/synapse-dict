# `es/fixes/` —— 一次性修复脚本（**已全部应用**）

28 个脚本 / 4,253 行。每一个都是**针对 es 库某一族具体缺陷的一次性订正**，
已经跑过、结果已经落进 `data/db/synapse-dict-es.sqlite`。

**它们不是可复用组件，也不是流水线的一部分。** 打开这个目录之前先读完下面三条。

---

## 🔴 一、不能删

`tests/test_no_regression.py` 的 23 条断言，**SQL 条件是直接抄自本目录里各脚本的**
（例如 A2–A7 抄自 `fix_ipa_residue.FAMS`、A1 抄自 `fix_x_gs.convert` 的拒绝判据）。

判据是对「缺陷长什么样」的定义，属于数据的性质。删掉脚本，闸就失去了依据——
下一次有人重建某张表、把修复静默抹掉时，没有任何东西会报警。

被闸直接引用的（核实于 2026-08-11，全部在位）：

| 脚本 | 断言 | 它当初修的缺陷 |
|---|---|---|
| `fix_x_gs.py` | A1 | 字母 x 写成 `ɡs`（应为 `ks`） |
| `fix_ipa_residue.py` | A2–A7 | 正字法 c/q/v 残留、`ʎ`、`w̝`、双颤音符、词首 `ɾ`、定界符残留 |
| `fix_ipa_nonspanish.py` | A8–A13 | `th`/`z`/`ʒ`/非西语元音/严式附加符/拉丁 g |
| `normalize_notation.py` | A14 | 音标含正字法 `y` |
| `drop_bad_labels.py` | B1–B2 | 短标签是纯领域标记、组内重复 |
| `fix_altof_lemma.py` | B3 | 异体拼写被编造成变形标签（`Méjico 的 阳性`） |

另有两条断言引用的脚本在**仓库别处**，不在本目录：
`scripts/fix_inflected_gloss.py`、`scripts/fix_pointer_gloss.py`（B4，跨语种共用），
以及 `pipeline/split_case_homographs.py`（B5）、`pipeline/build_example_layer.py`（B7）、
`pipeline/build_relation_layer.py`（B8）。

## 🔴 二、不要照抄到下一门语言

这些脚本修的是 **es 特有**的缺陷，判据里写死了西语的音系与 kaikki 的西语约定。
换语种时要带走的是 `docs/PITFALLS.md`（「什么时候会咬人」）和 `docs/PLAYBOOK.md`
（做事顺序），**不是这 4,253 行**。

⚠️ 尤其别照抄音标族：`fix_ipa_nonspanish` 里「`z` 一律是缺陷」只在西语成立
（西语无 /z/ 音位），葡语、意语、法语都有 /z/，照抄会把对的数据改坏。

## 🔴 三、新增修复脚本时，必须同时加断言

没有断言的修复 ＝ 下一次静默回归。加在 `tests/test_no_regression.py` 的
`IPA_CHECKS` / `SENSE_CHECKS` 里，并且**判据要落在 App 实际读取的那一列**上，
不能只查修复写入的列（`docs/PITFALLS.md` G1：修复会被「绕过」）。

---

## 按族索引

**音标（9 个）** —— 2026-07-31 ~ 08-03 那三轮
`fix_ipa_residue` `fix_ipa_nonspanish` `fix_ipa_stress_accented` `clean_ipa_residue`
`fix_x_gs` `fix_pron_x_gs` `fix_coda_unblocked_by_x` `normalize_notation` `compose_multiword_ipa`

> ⭐ 这一族里最值钱的经验是**被推翻的那两条**：`coda 浊化 31,890 条`与`多词次重音 7,889 条`
> 一度被两家模型共同判为缺陷，回源逐字核对后证明是 **kaikki 的记法约定**（99.9% / 96.8% 一致），
> 没有修。见 `docs/PITFALLS.md` 与 `probes/review_coda_rule.py`。

**义项与释义（7 个）**
`fix_altof_lemma` `drop_bad_labels` `append_zh_senses` `manual_nogloss`
`fix_misalign` `resolve_misalign59` `reorder_feminine_senses`

**跨版对齐（3 个）**
`fix_en_i_criterion` `clear_invalid_en_i` `apply_dup_verdicts`

> ⚠️ `fix_en_i_criterion` 记着一条硬教训：`en_i` 是**义项行号**，不是「第几条英文释义」
> （`mona` 给出铁证）。用错键就是义项错配。

**残渣清理（5 个）**
`clean_sense_es_residue` `fix_sense_es_residue2` `fix_sense_es_case`
`drop_resurrected_residue` `recheck_emptied_lowercase`

> ⚠️ `drop_resurrected_residue` 的存在本身就是教训：重放式脚本会把已删的行**填回来**。
> `UNIQUE` 保证不重复，**不保证不倒退**。

**其他（4 个）**
`fix_dualgender` `patch_pos_meta` `fix_flagged` `reconstruct_conflicts`

---

## 一句话

**这 4,253 行是「证据」，`docs/PITFALLS.md` 那 520 行是「结论」。**
带走结论，把证据留在原地。
