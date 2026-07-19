# synapse-dict / pt — 葡萄牙语划词词典（设计方案）

kaikki 骨架（免费、规则确定）+ 豆包血肉（中文/性别/复数/搭配/兜底双音/难度）。
产物：**`synapse-dict-pt.sqlite`**（**葡语专属 schema**，单表交付）。

> **设计立场（两条铁律，与 it/fr 一致）**
> 1. 表/字段按葡语本质设计，不合适的通用列该改就改、该删就删。
> 2. 代码**按语种拆分、互不引用**：葡语有自己的 `build/infl/translate` 脚本 + web 侧
>    `PortugueseDictService`。es/it/fr 的服务保持不动。**语言注册表是唯一共享点**。
>
> ⚠️ 现存的老 `pt/build.py`+`translate.py` 是从西语直接拷贝的通用 stardict 骨架，违反铁律，
> 本方案**推翻重写**。

## 0. 葡语本质特征 → 一等字段（核心）

| 葡语本质 | 为何独特 | 落地 |
|---|---|---|
| **欧葡 pt-PT vs 巴葡 pt-BR 双读音** | 葡语最大特征：同一词两套标准音。livre 巴 /ˈli.vɾi/ vs 葡 /ˈli.vɾɨ/；abater 巴 /a.baˈte(ʁ)/ vs 葡 /ɐ.bɐˈteɾ/（-r 实现、非重读 a→ɐ 全不同）。kaikki 双音各覆盖 ~69% | **两列 `ipa_br` + `ipa_pt`**（不是单 ipa！） |
| **动词三变位类** | -ar(1) / -er(2) / -ir(3)，另 pôr 特例；决定整个变位范式 | 动词列 `vconj` (1/2/3/por) |
| **人称不定式 infinitivo pessoal** | 葡语独有：infinitive 随人称变位（falares/falarmos/falarem），别的罗曼语没有；kaikki 有 2.3 万 personal+infinitive 变位形 | 变位行 `infl` 标「人称不定式第X人称」 |
| **阴阳性 gênero** | 名词/形容词性数一致 | 名词/形容词列 `gender` (m/f/mf) |
| **过去分词（含双分词）** | 复合时态用；部分动词双分词 aceitar→aceitado/aceito | 动词列 `pp` |
| **鼻化元音 ã õ、开闭元音** | 音位对立核心；正字法 ã/õ/ão | 落在 IPA 双音内 |
| **不规则复数 -ão→-ões/-ãos/-ães、-l→-is** | 招牌现象：pão→pães、animal→animais | 名词列 `plural`（不规则才收） |

**明确不设 aux 列**：葡语复合时态统一用 ter/haver，无 avoir/être 式的**逐动词助动词选择**，
故不照搬 it/fr 的 `aux`（按本质「该删就删」）。government/adj_pos 本期也不做（可后续按需）。

## 1. 数据画像（真实 dump 实测）

- 总条目 **434,036** = lemma **79,157** + 纯变位 **354,879**（动词变位量巨大）
- **双音覆盖**：巴西 69% / 葡萄牙 68% / 任一 71%（kaikki sounds 按 region tag 分）
- ⚠️ **变位形 IPA 无法从 lemma forms 收割**（forms 内含 ipa = **0%**，与法语 93% 相反）——
  变位形音标只取其自身 sounds（少）或留空，**不像法语能收割**
- 名词性别：m 23.2k / f 21.9k（覆盖好）
- region tag：Brazil / Portugal 为主，另 Southern-Brazil / Rio-de-Janeiro / São-Paulo / Caipira 等
- 变位 tag：indicative/subjunctive/imperative/conditional、present/preterite/imperfect/pluperfect/future、
  **personal+infinitive（人称不定式 2.3万）**、gerund/participle

## 2. 字段设计（葡语专属 `dict` 表）

```sql
CREATE TABLE dict (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  word        TEXT NOT NULL,
  word_norm   TEXT NOT NULL,   -- 去重音小写，支持无重音输入 / 前缀检索
  ipa_br      TEXT,            -- 巴西标准音（pt-BR）
  ipa_pt      TEXT,            -- 欧洲标准音（pt-PT）
  pos         TEXT,
  is_lemma    INTEGER NOT NULL,

  -- 动词本质（无 aux！）
  vconj       TEXT,            -- '1'|'2'|'3'|'por'（三变位类 + pôr）
  transitivity TEXT,           -- 't'|'i'|'ti'
  pronominal  INTEGER,         -- 代词式/反身 -se
  pp          TEXT,            -- 过去分词（复合时态）

  -- 名词/形容词本质
  gender      TEXT,            -- 'm'|'f'|'mf'
  plural      TEXT,            -- 不规则复数（-ão→-ões、-l→-is；规则留空）
  feminine    TEXT,            -- 阴性形（形容词 bonito→bonita；名词 ator→atriz）
  comparative TEXT,            -- 不规则比较级 bom→melhor（硬编码少数）

  level       TEXT,            -- CEFR A1-C2（豆包）

  definition  TEXT, translation TEXT, meta TEXT,
  infl        TEXT, exchange TEXT, collocation TEXT, example TEXT, flag TEXT
);
CREATE INDEX idx_word ON dict(word COLLATE NOCASE);
CREATE INDEX idx_norm ON dict(word_norm);
```

## 3. 管线（脚本按语种独立，互不 import）

```
1. build.py + pt/infl_compose.py   # kaikki JSONL → 葡语 dict 骨架（确定性）
                                   #   双音 ipa_br/ipa_pt 按 region tag 抽；vconj/gender/plural/pp/feminine
2. b_translate.py                  # 豆包批翻 ~8 万 lemma → zh + 缺口 gender/plural/feminine
                                   #   + 兜底双音 ipa_br/ipa_pt + col + level(CEFR) + flag
```

- **IPA 不造 G2P**：双方言 + 鼻化太复杂，kaikki 双音（71%）+ 豆包兜底两套音即可。
- 豆包 IPA 兜底须**同时返回 br 与 pt 两套**（prompt 明确）。
- merge 仲裁：kaikki 有则优先，缺口豆包补；双音各自独立补。

## 4. 展示（web/api：葡语自己的服务，与 es/it/fr 解耦）

1. `packages/dict-core/src/portuguese.ts`：`PortugueseDictService` + `PortugueseEntry`。
   **双音展示**：🇧🇷 BR / 🇵🇹 PT 两行音标（或并排），各自可发音（speak locale pt-BR / pt-PT）。
2. 注册表加 `pt` 行；`App.tsx` 的 `PortugueseEntryView`：变位类/过去分词/性别/复数/阴性形徽标 + CEFR；
   变位页经 exchange 内联原形；**人称不定式**在变位说明里点明。

## 5. 待办清单

- [x] `build.py` + `pt/infl_compose.py` ✅ 411,802 词条（lemma 71,440 + 变位 340,362）；
  双音 lemma 层巴西 67%/葡萄牙 66%；vconj 6277/gender 58,416/阴性形(名+形) 10,357/pp 6936；
  人称不定式/简单过去时/虚拟式将来时组合正确；drop-ledger 全归桶
- [x] `b_translate.py` ✅ 豆包多合一（zh + 缺口 gender/plural/feminine + 兜底双音 ipa_br/ipa_pt +
  col + level + flag）；结构承已验证的 fr 版；**豆包小样测试待意语跑完再做**（不并发调用）
- [x] `dict-core/portuguese.ts`：`PortugueseDictService` ✅ 双音、解耦、typecheck 过；
  `normalizePtIpa` 去连结弧/音节点（/ˈli.vɾi/→/ˈlivɾi/），保留鼻化/双方言括注
- [x] 注册表加 `pt`；web `PortugueseEntryView` ✅ 双读音行(🇧🇷pt-BR/🇵🇹pt-PT 各自发音) +
  变位类/过去分词/性别/复数/阴性形/比较级徽标；API `/api/langs` 含 pt、`falar?lang=pt` 返回双音
- [ ] **全量豆包翻译 ~7 万 lemma（用户自己跑）**
- [x] 老 stardict 版 `build.py`/`translate.py` 已删/重写
```
