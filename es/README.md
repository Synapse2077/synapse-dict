# synapse-dict / es — 西班牙语划词词典

kaikki 骨架（免费、规则确定）+ 豆包血肉（中文/性别/搭配）+ 规则 IPA。
成品：**`synapse-dict-es.sqlite`**（767,293 条，单表 `dict`）。

## 数据来源与产物

| 文件 | 说明 |
|---|---|
| `kaikki.org-dictionary-Spanish.jsonl` | 源：kaikki.org Wiktextract 西语 dump（807k 条，~1GB，不进 git） |
| `synapse-dict-es.sqlite` | **成品词典**（唯一交付物） |
| `b_out.tar.gz` | 豆包原始翻译输出缓存（2120 chunk，已 merge 入库；留档以备改 schema 重跑） |

## 管线（跑的顺序）

```
1. build.py          # kaikki JSONL → sqlite 骨架层
                     #   义项/变位/exchange 反查/meta(性别·地区·语域)
                     #   真义 lemma 的 translation 留空待豆包
                     #   依赖 infl_compose.py（变位语法标签确定性组合器）

2. b_ipa_fill.py     # 规则 G2P 给 66万变位形式填 IPA（b_ipa.py 为核心）
   b_ipa_eval.py     #   （可选）拿 kaikki 真值抽验 G2P，实测 98.42%

3. b_translate.py    # 豆包 batch 翻 10.5万 lemma → zh/g(性别)/ipa/col(搭配)/flag
   python3 b_translate.py           # 翻译，结果落 b_out/（可中断续跑）
   python3 b_translate.py --merge   # b_out/ 写回 sqlite
   python3 b_translate.py --ipatodo # 外来词等规则填不了的 IPA 交豆包补
```

## 脚本职责

| 脚本 | 作用 |
|---|---|
| `build.py` | 建骨架层（确定性，无 AI） |
| `infl_compose.py` | 变位语法标签→中文措辞的确定性组合器（build.py 依赖） |
| `b_ipa.py` | 西语规则 G2P（`word_to_ipa`），Castilian 惯例，与 kaikki 对齐 |
| `b_ipa_fill.py` | 用 b_ipa 批量填变位 IPA |
| `b_ipa_eval.py` | 拿 kaikki 真值验证 G2P 准确率 |
| `b_translate.py` | 豆包翻译主脚本（AsyncArk + batch 端点 + 高并发） |

## 成品口径（截至归档）

- 总条目 767,293 = 真义 lemma 105,267 + 纯变位 662,026
- 中文译文 100% 覆盖；IPA 99.1%（缺 6,915，多为外来词/异形，规则无法转写）
- 搭配 25,804 条；flag 标记 1,323 条（豆包对 kaikki 存疑/纠错的审计留痕，词义已以豆包为准）

## 设计要点

- **一种数据一个权威**：义项/变位 = kaikki；中文/性别/搭配 = 豆包（只填不造义项）。
- **性别三源仲裁**：kaikki + 豆包 + 冲突规则（任一为 mf→mf；m↔f 冲突→豆包多者胜）。
- **搭配与例句分列**：`collocation`（豆包搭配）独立于 `example`（真例句，本期未抽）。
- 详见 memory `project_multilang_dict`。
