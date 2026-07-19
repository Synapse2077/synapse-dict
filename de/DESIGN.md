# synapse-dict / de — 德语划词词典（设计方案）

kaikki 骨架（免费、规则确定）+ 豆包血肉（中文/难度/搭配/兜底）。
产物：**`synapse-dict-de.sqlite`**（**德语专属 schema**，单表交付）。

> **设计立场（两条铁律，与 es/it/fr/pt 一致）**
> 1. 表/字段按**德语本质**设计，不合适的通用列该改就改、该删就删。
> 2. 代码**按语种拆分、互不引用**：德语有自己的 `build/infl/translate` 脚本 + web 侧
>    `GermanDictService`。es/it/fr/pt 的服务保持不动。**语言注册表是唯一共享点**。

## 0. 德语本质特征 → 一等字段（核心）

| 德语本质 | 为何独特 | 落地 |
|---|---|---|
| **三性 der/die/das** | 名词分阳/阴/中三性（法/意/葡只有两性），决定冠词、形容词变格、代词回指 | 名词列 `gender` (m/f/n/mf) |
| **名词两大著录形：属格单数 + 复数** | 德语词典标准著录法 `das Haus, des Hauses, die Häuser`；复数**不可预测**（-e/-er/-en/-s/变音/零），属格 -s/-es/-en | 名词列 `genitive` + `plural`（全收，不省规则） |
| **动词三基本形式 Stammformen** | 学德语动词＝背 `gehen–ging–gegangen`（不定式-过去式-过去分词），强动词靠 ablaut 换元音 | 动词列 `praeteritum` + `partizip2` |
| **完成时助动词 haben/sein** | 复合时态选 haben 或 sein（位移/状态变化用 sein：gehen→ist gegangen） | 动词列 `aux` (haben/sein/both) |
| **强/弱/混合变化 + ablaut 类** | 强动词换干元音(1-7 类)、弱动词加 -te、混合动词兼具；决定整个变位范式 | 动词列 `vclass`（strong/weak/mixed[-类号]） |
| **可分动词 trennbare Verben** | `ankommen`→"ich komme **an**"（前缀分离后置）、"an**ge**kommen"（ge 中缀）；德语灵魂之一 | 动词列 `separable` + `sep_prefix`（an/auf/mit…） |
| **名词首字母大写** | 正字法硬规则：所有名词大写（Haus/Liebe/Gehen），区分 `sie`(她) vs `Sie`(您) | **`word` 保留原大小写**（不 lowercase），`word_norm` 才小写去变音 |
| **形容词比较级/最高级** | gut→besser→am besten（不规则）、schön→schöner→am schönsten | 形容词列 `comparative` + `superlative` |
| **四格 Kasus（主/属/与/宾）** | 名词/形容词/冠词按 4 格 × 单复数 × 强弱变格；范式庞大 | **落在变位行**（infl 说明「属格单数/强变化阳性单数宾格」等），非 lemma 列 |
| **ä ö ü ß** | 变音字母 + eszett；用户常用 ae/oe/ue/ss 输入 | `word_norm`：ä→ae ö→oe ü→ue ß→ss，支持无变音检索 |

**明确不设**：`vgroup`（法语三组变位，德语无对应；德语用强/弱/混合，已由 `vclass` 表达）、
`government/adj_pos`（本期不做，可后续按需）、`feminine` 列（德语职业阴性靠 -in 派生 Lehrer→Lehrerin，
规则性强，作为独立词条收录即可，不设专列）。

## 1. 数据画像（真实 dump 实测）

- 总条目 **368,352**：noun 136,591 / adj 126,542 / verb 87,343 / name 11,915 / adv 2,421 …
  其中 lemma：名词 65,183 / 动词 10,530；余为变位/变格形（独立词条，senses 全 form_of）
- **IPA 覆盖 23%**（基础音标偏少）；⚠️ **变位形 IPA 无法从 forms 收割**（含 ipa=0%，同葡语、不同法语）
  → 德语单一标准音，豆包兜底**单音**（不像葡语双音）
- 名词性别（de-noun expansion 抽）：f 25,136 / m 22,712 / n 16,336
- 动词助动词（de-verb expansion 抽）：haben 9,507 / sein 971 / both 47
- 动词强弱：strong 2,826 / weak 8,366（弱为主，强动词是高频核心词）
- 形容词比较级：5,911
- 变位/变格 tag：case(nominative/genitive/dative/accusative) × number × 冠词(definite/indefinite/
  without-article) × 强弱(strong/weak/mixed)；动词 person/number/present/preterite/
  subjunctive-i/subjunctive-ii/imperative/participle

## 2. 字段设计（德语专属 `dict` 表）

```sql
CREATE TABLE dict (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  word        TEXT NOT NULL,   -- 保留原大小写（名词首字母大写＝德语本质）
  word_norm   TEXT NOT NULL,   -- 小写 + ä→ae ö→oe ü→ue ß→ss，无变音检索/前缀匹配
  ipa         TEXT,
  pos         TEXT,
  is_lemma    INTEGER NOT NULL,

  -- 名词本质（三性 + 两大著录形）
  gender      TEXT,            -- 'm'|'f'|'n'|'mf'
  genitive    TEXT,            -- 属格单数（des Hauses）
  plural      TEXT,            -- 复数（die Häuser；不可预测，全收）

  -- 动词本质（三基本形式 + 助动词 + 强弱 + 可分）
  aux         TEXT,            -- 'haben'|'sein'|'both'（完成时助动词）
  praeteritum TEXT,            -- 过去式 Präteritum（ging）
  partizip2   TEXT,            -- 过去分词 Partizip II（gegangen）
  vclass      TEXT,            -- 'weak'|'strong'|'mixed'（可带 ablaut 类号 strong-7）
  separable   INTEGER,         -- 可分动词 trennbar
  sep_prefix  TEXT,            -- 可分前缀（an/auf/mit/vor/zu…）
  reflexive   INTEGER,         -- 反身 sich

  -- 形容词本质
  comparative TEXT,            -- 比较级（gut→besser、schön→schöner）
  superlative TEXT,            -- 最高级（am besten、am schönsten）

  level       TEXT,            -- CEFR A1-C2（豆包）

  definition  TEXT, translation TEXT, meta TEXT,
  infl        TEXT, exchange TEXT, collocation TEXT, example TEXT, flag TEXT
);
CREATE INDEX idx_word ON dict(word COLLATE NOCASE);
CREATE INDEX idx_norm ON dict(word_norm);
```

## 3. 管线（脚本按语种独立，互不 import）

```
1. build.py + de/infl_compose.py   # kaikki JSONL → 德语 dict 骨架（确定性）
   · 名词：de-noun expansion 抽 gender/genitive/plural
   · 动词：de-verb expansion 抽 aux/praeteritum/partizip2/vclass；forms 抽 separable+prefix
   · 形容词：de-adj expansion 抽 comparative/superlative
   · 变位/变格形（senses 全 form_of）→ 独立词条，infl 存中文语法说明，exchange 反查原形
2. b_translate.py                  # 豆包批翻 lemma → zh + 缺口 gender/genitive/plural/aux
                                   #   + 兜底单音 ipa + col + level(CEFR) + flag
```

- **IPA 不造 G2P**：德语正字法虽较规则，但变音/长短元音/词重音/外来词例外多；kaikki 23% + 豆包兜底。
- merge 仲裁：kaikki 有则优先，缺口豆包补。

## 4. 展示（web/api：德语自己的服务，与 es/it/fr/pt 解耦）

1. `packages/dict-core/src/german.ts`：`GermanDictService` + `GermanEntry`。
   **名词**：der/die/das 冠词彩色徽标 + 属格/复数著录行（das Haus · des Hauses · die Häuser）。
   **动词**：三基本形式行（gehen–ging–gegangen）+ 助动词 haben/sein 徽标 + 强/弱/可分徽标。
   **形容词**：比较级/最高级行。
2. 注册表加 `de`（speak locale de-DE）；`App.tsx` 的 `GermanEntryView`；变位页经 exchange 内联原形。

## 5. 待办清单

- [ ] `build.py` + `de/infl_compose.py`：kaikki → 德语骨架（gender/genitive/plural/aux/三基本形式/vclass/separable）
- [ ] `dict-core/german.ts`：`GermanDictService`（三性冠词、三基本形式、可分动词展示）
- [ ] 注册表加 `de`；web `GermanEntryView`
- [ ] **全量豆包翻译（用户自己跑）**：`cd de && python3 b_translate.py --mode batch --concurrency 50` 后 `--merge`
- [ ] 跑前小样验证：`--mode online --words "Haus,gehen,ankommen,gut,Frau,schön"` 确认三性/三基本形式/可分/CEFR
