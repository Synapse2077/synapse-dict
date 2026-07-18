# synapse-dict / it — 意大利语划词词典（设计方案）

kaikki 骨架（免费、规则确定）+ 豆包血肉（中文/助动词/性别/搭配/IPA）+ 规则 G2P。
产物：**`synapse-dict-it.sqlite`**（**意语专属 schema**，单表交付）。

> **设计立场（本方案的地基）**
> 每种语言有自己最本质的特征，词典必须让这些特征成为一等公民。因此本方案**不套用 es 的
> 通用 `dict` 模具**，而是为意语量身设计表结构与服务类：
> 1. 表/字段按意语本质设计，不合适的通用列该改就改、该删就删。
> 2. 代码**按语种拆分、互不引用**：意语有自己的 `build/infl/ipa/translate` 脚本，web 侧有
>    自己的 `ItalianDictService`。es 的 `KaikkiDictService` 保持不动，两者零耦合、互不影响。

## 0. 意语本质特征 → 一等字段（本方案的核心）

通用词典（含 es schema）装不下、或压平进泛化 meta 的意语特征，本方案全部升为一等：

| 意语本质 | 为何独特 | 落地 |
|---|---|---|
| **助动词 essere/avere** | 复合时态的灵魂：每个动词必配其一；不及物位移/反身用 essere 且过去分词性数一致。西语无此维度 | 动词一等列 `aux` (avere/essere/both) |
| **变位规则复数 / 异性复数** | 招牌现象：`braccio(阳)→braccia(阴)`、`uovo→uova`；invariable(città/bar)、plural-only | 名词列 `plural` + `plural_gender` + `number_note` |
| **双辅音 gemination** | 音长音位对立的标志：`gatto /ˈɡat.to/` vs `gato`；意语拼写辅音须精确转写 | IPA 内精确表达（G2P 负责） |
| **开/闭元音 ɛ/e ɔ/o** | 词汇性最小对立：`pèsca 桃` ≠ `pésca 钓鱼`；拼写多不标 | IPA 内表达（规则搞不定 → 豆包） |
| **s/z 清浊、重音位置** | 词汇性不可预测（`casa` /s/~/z/；重音仅末音节才标写） | IPA 内表达（豆包兜底） |
| **动词三变位类** | -are(1) / -ere(2) / -ire(3，含 -isc- 内插 finire→finisco) 决定整个变位范式 | 动词列 `conj` (1/2/3/3isc) |
| **粘着代词动词** | procomplementari：andarsene、farcela（compound-of 3.3万） | `pronominal` 标记 + exchange 反查 |

## 1. 数据画像（真实 dump 实测）

- 总条目 **622,957** = lemma **163,156** + 纯变位 **459,801**（动词 40 万，变位比西语重）
- **IPA 覆盖仅 16.4%**（101,854）——意语相对西语最大的坑，规则 G2P + 豆包兜底是必需
- 性别：masculine 47.5k / feminine 38.8k / by-personal-gender 3.3k（→ mf）
- 变位 tag：`historic`(=远过去时 passato remoto) / imperfect / subjunctive(congiuntivo) /
  conditional(condizionale) / future / gerund / participle / imperative
- 地区 tag：Tuscany / Italy / Switzerland / Northern / Sardinia / Sicily / dialectal…
- compound-of 3.3万（粘着代词复合）；IPA 格式带音节点+重音 `/ˈka.ze/`

## 2. 字段设计（意语专属 `dict` 表）

一个拼写一行；**按意语本质设计，不受 es 列约束**：

```sql
CREATE TABLE dict (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  word        TEXT NOT NULL,
  word_norm   TEXT NOT NULL,   -- 去重音小写，支持无重音输入 / 前缀检索
  ipa         TEXT,            -- 音标（列名用 ipa，不沿用英语的 phonetic）
  pos         TEXT,            -- 整词聚合词性
  is_lemma    INTEGER NOT NULL,

  -- 动词本质
  aux         TEXT,            -- 'avere' | 'essere' | 'both'（复合时态助动词）
  conj        TEXT,            -- '1'|'2'|'3'|'3isc'（变位类）
  transitivity TEXT,           -- 't'|'i'|'ti'（及物/不及物/兼）
  pronominal  INTEGER,         -- 反身/代词式/procomplementare

  -- 名词本质
  gender      TEXT,            -- 'm'|'f'|'mf'（升为一等，意语核心）
  plural      TEXT,            -- 不规则复数形（规则可推者留空）
  plural_gender TEXT,          -- 异性复数标记（braccio→braccia 记 'f'）
  number_note TEXT,            -- 'invariable'|'plural-only'|'uncountable'

  -- 释义与其余
  definition  TEXT,            -- 英文 gloss 锚点（\n 分义项）
  translation TEXT,            -- 中文（\n 平行对齐 definition；纯变位=语法描述）
  meta        TEXT,            -- 逐义项 JSON：{pos, reg[], lex[]}（地区/语域，per-sense 才需要的留这）
  infl        TEXT,            -- 变位语法说明（多行）
  exchange    TEXT,            -- "0:原形"，变位反查 lemma
  collocation TEXT,            -- 豆包搭配 "frase 中文"
  example     TEXT,            -- 例句（本期留空）
  flag        TEXT             -- 豆包审计留痕（存疑/纠错）
);
CREATE INDEX idx_word ON dict(word COLLATE NOCASE);
CREATE INDEX idx_norm ON dict(word_norm);
```

**设计取舍**：性别/助动词是意语本质、且整词级绝大多数唯一 → 升为一等列（快、可筛、语义清）；
地区/语域是逐义项、低频 → 留在 `meta` JSON。**drop-ledger 保留**（全 tag 归桶，桶外建库报警，
杜绝静默丢义项）；分桶用意语维度（Tuscany/Switzerland/Sardinia/dialectal…）。

## 3. 管线（脚本按语种独立，互不 import es）

```
1. build.py            # kaikki JSONL → 意语 dict 骨架（确定性，无 AI）
                       #   依赖 it/infl_compose.py（意语变位组合器，独立文件）
                       #   动词 aux/conj/transitivity、名词 gender/plural 尽量从 kaikki
                       #   head_templates/tags 抽；抽不到的留空待豆包
2. b_ipa.py / b_ipa_fill.py / b_ipa_eval.py   # 意语规则 G2P：先自证准确率，再填变位 IPA
3. b_translate.py      # 豆包批翻 16 万 lemma → zh/aux/gender/plural/ipa/col/flag
```

### 3a. `build.py` + `it/infl_compose.py`（骨架，纯规则）
- 变位判定、base 反查、reflexive、孤儿收口等借鉴 es 思路，但**代码独立成 it 自己的文件，
  不 import es**。
- **意语变位组合器**：段序 `[非限定|语气·时态]·[人称]·[数]·[自复]`，时态映射覆盖意语专属：

  | kaikki tag | 中文 |
  |---|---|
  | historic | 远过去时（passato remoto） |
  | imperfect | 未完成过去时 |
  | present / future | 现在时 / 将来时 |
  | conditional | 条件式（condizionale） |
  | subjunctive | 虚拟式（congiuntivo） |
  | imperative | 命令式 |
  | gerund | 副动词 |
  | participle(+past) | 过去分词 |

- **措辞定稿**：抽全库真实 tag 组合（约百来种）交豆包一次性给地道术语，人工过目定稿后写进
  确定性组合器（不逐行走豆包）。
- `aux/conj/transitivity/gender/plural` 优先从 kaikki `head_templates`/conjugation 模板与 tags 抽；
  抽不到的留空，交豆包补。

### 3b. IPA（意语重点：规则 G2P + 豆包兜底，三级填充）
意语辅音正字法极规则，但 **3 个词汇性不可预测点**：重音、开/闭 `e/o`、`s/z` 清浊。
- 新写 `b_ipa.py`（意语版）：`c/g` 软化、`gl(i)/gn/sc(i)`、**双写辅音 gemination**、`qu`、
  音节切分、默认倒二重音。
- **先自证**：拿 10 万有 kaikki IPA 的词跑 `b_ipa_eval.py`，达标才用规则填变位。
- **三级填充优先级**：`kaikki > 规则 G2P > 豆包`。规则搞不定的开闭元音/清浊/外来词重音 →
  豆包逐词过 lemma 时顺带返回 `ipa`（零额外成本），merge 时仅补库中空缺。

### 3c. `b_translate.py`（豆包多合一）
- 对象：`is_lemma=1 且 translation 为空` 的 16 万 lemma。
- 输出 index-key JSON，逐词校验 `len(zh)==len(senses)`（`__misalign__` 兜底）；chunk 落盘续跑。
- 豆包除 zh 外按词性返回意语本质字段：
  - 动词：`aux`(avere/essere/both)、`transitivity`
  - 名词：`gender`(m/f/mf)、`plural`（不规则复数，规则则空）
  - 全部：`ipa`（意语约定：gemination、`gl/gn`、`ci/gi` 软化、开闭 e/o、s/z）、`col`、`flag`
- merge：性别/助动词**多源仲裁**（kaikki 有则 kaikki 优先，缺则豆包补，冲突记 flag）；
  IPA 仅补空缺；搭配/flag 入列。

## 4. 展示方案（web/api：意语自己的服务，与 es 解耦）

**不复用 es 的 `KaikkiDictService`**（那是为通用 kaikki 系设计的）。意语给自己一套：

1. `packages/dict-core/src/` 新增 `italian.ts`：`ItalianDictService` + `ItalianEntry` 类型，
   读意语专属列（aux/conj/gender/plural…），映射成意语自己的展示 shape。
2. 语言注册表加 `it` 行，指向 `ItalianDictService`；`availableLanguages()` 检测
   `it/synapse-dict-it.sqlite` 存在后自动点亮切换器。**注册表是唯一的共享点**，语种服务之间互不 import。
3. 展示新增意语专属渲染：动词卡显示 **助动词徽标**（essere/avere）、名词卡显示
   **复数形 + 异性复数提示**、IPA 高亮 gemination；变位页经 exchange 内联原形。
4. synapse-web 划词弹窗：走意语 API，划到变位自动指回原形。

## 5. 设计要点

- **本质优先**：意语独有特征（助动词、异性复数、gemination、开闭元音）升为一等，不被通用模具压平。
- **按语种解耦**：脚本层、服务层各自独立，互不引用；仅语言注册表一处汇总。
- **一种数据一个权威**：义项/变位 = kaikki；中文/助动词/性别/搭配/兜底IPA = 豆包（只填不造义项）。
- **IPA 三级填充**：kaikki > 规则 G2P > 豆包；**drop-ledger** 全 tag 归桶不静默丢。

## 6. 待办清单（实现顺序）

- [x] `build.py`：意语专属 `dict` 表（本质字段 + 意语 meta 桶 + drop-ledger）✅ 已建库验证
- [x] `it/infl_compose.py`：意语变位组合器（v1 已跑通；措辞待豆包验证定稿）
- [x] `b_ipa.py` + `b_ipa_eval.py`：意语 G2P ✅ 自证 骨架 88% / 重音路径 strict 83%
- [x] `b_ipa_fill.py`：规则填 IPA ✅ 覆盖 16.4%→**99.9%**（重音形路径 31.4 万精确）
- [x] `b_translate.py`：豆包多合一 ✅ 小样验证(义项对齐/搭配/gender补缺/仲裁 merge 均正确)；待全量跑 15 万 lemma
- [x] `dict-core/italian.ts`：`ItalianDictService` ✅ 意语专属，不复用 KaikkiDictService；typecheck+HTTP 验证通过
- [x] 注册表加 `it` 行；web `ItalianEntryView` ✅ 助动词徽标/异性复数提示条/变位页原形带 aux·gender
- [ ] 删除过时的老 `stardict` 版 `build.py`/`translate.py` 与残留 sqlite
```
