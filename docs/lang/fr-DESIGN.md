# synapse-dict / fr — 法语划词词典（设计方案）

kaikki 骨架（免费、规则确定）+ 豆包血肉（中文/性别/助动词/搭配/兜底IPA/难度）。
产物：**`synapse-dict-fr.sqlite`**（**法语专属 schema**，单表交付）。

> **设计立场（本方案的地基，与 it 同两条铁律）**
> 每种语言有自己最本质的特征，词典必须让这些特征成为一等公民。因此本方案**不套用 es/it 的
> 现成模具**（虽借鉴其管线思路），而是为法语量身设计表结构与服务类：
> 1. 表/字段按法语本质设计，不合适的通用列该改就改、该删就删。
> 2. 代码**按语种拆分、互不引用**：法语有自己的 `build/infl/translate` 脚本，web 侧有自己的
>    `FrenchDictService`。es 的 `SpanishDictService`、it 的 `ItalianDictService` 保持不动，
>    三者零耦合、互不影响。**语言注册表是唯一共享点**。
>
> ⚠️ 现存的老 `fr/build.py`+`translate.py` 是**从西语直接拷贝**的通用 stardict 骨架（注释里还留着
> 「西语语法术语」「casar 变位」），违反上述铁律，本方案将其**推翻重写**。

## 0. 法语本质特征 → 一等字段（本方案的核心）

通用词典装不下、或压平进泛化 meta 的法语特征，本方案全部升为一等：

| 法语本质 | 为何独特 | 落地 |
|---|---|---|
| **助动词 avoir/être** | 复合时态的灵魂：绝大多数用 avoir，位移/状态变化动词（aller/venir/devenir…）与**全部代词式**用 être 且过去分词性数一致。和意语同维度但成员不同 | 动词一等列 `aux` (avoir/être/both) |
| **过去分词 participe passé** | 复合时态 = aux + PP；être 类还需与主语性数一致（allé/allée/allés/allées）。是法语动词的招牌零件 | 动词列 `pp`（+ IPA 收录在变位行） |
| **阴阳性 genre** | 名词无标记但决定冠词/一致；法语性别不可从词形可靠推断 | 名词列 `gender` (m/f/mf) |
| **形容词阴性形** | 招牌现象：`grand→grande`、`heureux→heureuse`、`beau→belle`；阴性形常改变发音（哑辅音变读） | 形容词列 `feminine` |
| **哑音/联诵/省音 → 拼写↔发音大鸿沟** | 法语最大的坑：`livre /livʁ/`、末辅音多不发、联诵 liaison、省音 l'。拼写完全无法直读 | IPA 是刚需（kaikki 优先 + 豆包兜底） |
| **鼻元音 ɑ̃ ɛ̃ ɔ̃ œ̃** | 音位对立核心，正字法 an/en/in/on/un 多写法映射一个鼻音 | IPA 内表达 |
| **动词三组 groupes** | 1er(-er 规则) / 2e(-ir 带 -iss- finir→finissant) / 3e(其余不规则：-ir/-re/-oir、aller) 决定变位范式 | 动词列 `vgroup` (1/2/3) |
| **代词式动词** | se laver / s'en aller，一律用 être 助动词 | `pronominal` 标记 + exchange 反查 |

## 1. 数据画像（真实 dump 实测）

- 总条目 **401,593** = lemma **97,804** + 纯变位 **303,789**（动词变位量巨大，与意语同量级）
- **IPA 覆盖：lemma 76%**（kaikki sounds 自带）、**变位独立看仅 17%**——但
  **93% 的变位形 IPA 就藏在其 lemma 的 `forms` 数组里**（每个 form 带自己的 ipa），
  故用「从 lemma 收割变位形 IPA」把变位覆盖从 17%→90%+，**无需自造 G2P**
- 动词助动词：avoir 7027 / être 270（être 少，符合法语实际——仅位移状态类+代词式）
- 动词及物性 tag：transitive 3725 / intransitive 1107 / reflexive 992 / pronominal 227 / impersonal 77
- 名词性别：masculine 35.4k / feminine 28.3k（覆盖好）
- 形容词自带 feminine / masculine-plural / feminine-plural forms
- IPA 格式带音节点+鼻元音 `/a.bɔ.ʁe/`、`/a.lɑ̃/`

**为何法语不造规则 G2P（与意语相反）**：意语辅音正字法极规则，规则 G2P 自证 88% 值得造；
法语哑音末辅音、联诵、省音、一音多写，规则 G2P 极难且性价比低。法语改走
**kaikki 自带 IPA（lemma 76% + 变位收割 90%+）→ 豆包兜底缺口** 两级，不写 `b_ipa.py`。

## 2. 字段设计（法语专属 `dict` 表）

一个拼写一行；**按法语本质设计，不受 es/it 列约束**（无 conj/plural_gender/number_note；
新增 feminine/vgroup/pp）：

```sql
CREATE TABLE dict (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  word        TEXT NOT NULL,
  word_norm   TEXT NOT NULL,   -- 去重音小写，支持无重音输入 / 前缀检索
  ipa         TEXT,            -- 音标（kaikki 优先 + 变位收割 + 豆包兜底）
  pos         TEXT,            -- 整词聚合词性
  is_lemma    INTEGER NOT NULL,

  -- 动词本质
  aux         TEXT,            -- 'avoir' | 'être' | 'both'（复合时态助动词）
  vgroup      TEXT,            -- '1' | '2' | '3'（三组变位）
  transitivity TEXT,           -- 't' | 'i' | 'ti'（及物/不及物/兼）
  pronominal  INTEGER,         -- 代词式/反身 se laver
  pp          TEXT,            -- 过去分词 participe passé（复合时态用）

  -- 名词/形容词本质
  gender      TEXT,            -- 'm' | 'f' | 'mf'（法语核心）
  plural      TEXT,            -- 不规则复数（-al→-aux/-eau→-eaux 或整词；规则 +s、数不变留空）
  feminine    TEXT,            -- 阴性形：形容词 grand→grande；名词 acteur→actrice（生物性别配对）
  invariable  INTEGER,         -- 不变形（gratis、色彩复合形容词、缩略）
  adj_pos     TEXT,            -- 形容词位置 'pre'|'post'|'both'（BAGS前置/颜色国籍后置/变义两可，豆包）
  government  TEXT,            -- 动词/形容词固定介词支配 "à + inf."/"de qch"（学习者刚需，豆包）
  comparative TEXT,            -- 不规则比较级 bon→meilleur（硬编码 5 词：bon/mauvais/petit/bien/mal）

  -- 难度
  level       TEXT,            -- CEFR A1-C2（豆包填）

  -- 释义与其余
  definition  TEXT,            -- 英文 gloss 锚点（\n 分义项）
  translation TEXT,            -- 中文（\n 平行对齐 definition；纯变位=语法描述）
  meta        TEXT,            -- 逐义项 JSON：{pos, reg[], lex[]}（地区/语域，per-sense 才需要的留这）
  infl        TEXT,            -- 变位语法说明（多行）
  exchange    TEXT,            -- "0:原形"，变位反查 lemma
  collocation TEXT,            -- 豆包搭配 "expression 中文"
  example     TEXT,            -- 例句（本期留空）
  flag        TEXT             -- 豆包审计留痕（存疑/纠错）
);
CREATE INDEX idx_word ON dict(word COLLATE NOCASE);
CREATE INDEX idx_norm ON dict(word_norm);
```

**设计取舍**：性别/助动词/动词组/阴性形/过去分词是法语本质、整词级绝大多数唯一 → 升为一等列；
地区/语域是逐义项、低频 → 留 `meta` JSON。**drop-ledger 保留**（全 tag 归桶，桶外建库报警，
杜绝静默丢义项）。

## 3. 管线（脚本按语种独立，互不 import es/it）

```
1. build.py            # kaikki JSONL → 法语 dict 骨架（确定性，无 AI）
                       #   依赖 fr/infl_compose.py（法语变位组合器，独立文件）
                       #   动词 aux/vgroup/transitivity/pp、名词 gender/plural、
                       #   形容词 feminine 从 kaikki head_templates/forms/categories/tags 抽；
                       #   **变位形 IPA 从 lemma forms 数组收割**；抽不到的留空待豆包
2. b_translate.py      # 豆包批翻 ~10 万 lemma → zh/gender/aux/plural/feminine/ipa/col/level/flag
```

### 3a. `build.py` + `fr/infl_compose.py`（骨架，纯规则）
- 变位判定、base 反查、reflexive、孤儿收口思路借鉴 es/it，但**代码独立成 fr 自己的文件，不 import**。
- **助动词 aux**：从 lemma `forms` 里的 `"avoir + past participle"` / `"être + past participle"`
  多词构造行判定；`head_templates.args.type=auxiliary` 佐证。
- **动词组 vgroup**：不定式 -er 且非 aller → 1；副动词/现在分词以 -issant 结尾 → 2；其余 → 3。
- **过去分词 pp**：取 forms 中 tags=['participle','past'] 且非 multiword 的阳性单数形（allé）。
- **性别 gender**：名词 `head_templates.args['1']`(m/f) + `senses.tags`(masculine/feminine)。
- **形容词 feminine/复数**：从 forms tags=['feminine'] / ['masculine','plural'] 等抽。
- **变位形 IPA 收割**：建库时先扫 lemma 的 forms 数组，建 `(拼写)→ipa` 映射，
  组装变位行时回填其 IPA（覆盖 90%+）。
- **法语变位组合器** `infl_compose.py`：段序 `[非限定|语气·时态]·[人称]·[数]·[性]`：

  | kaikki tag | 中文 |
  |---|---|
  | present / imperfect / future | 现在时 / 未完成过去时 / 简单将来时 |
  | past + historic | 简单过去时（passé simple） |
  | conditional | 条件式 |
  | subjunctive | 虚拟式（subjonctif） |
  | imperative | 命令式 |
  | infinitive / gerund(participle+present) | 不定式 / 现在分词·副动词 |
  | participle + past | 过去分词（+性数一致） |

### 3b. `b_translate.py`（豆包多合一）
- 对象：`is_lemma=1 且 translation 为空` 的 ~10 万 lemma。
- 输出 index-key JSON，逐词校验 `len(zh)==len(senses)`（`__misalign__` 兜底）；chunk 落盘续跑。
- 豆包除 zh 外按词性返回法语本质字段：
  - 动词：`aux`(avoir/être/both)、`transitivity`
  - 名词：`gender`(m/f/mf)、`plural`（不规则复数）
  - 形容词：`feminine`（阴性形）
  - 全部：`ipa`（法语约定：鼻元音、末哑辅音、联诵不标；仅补库中空缺）、`col`、`level`(CEFR)、`flag`
- merge：性别/助动词/组**多源仲裁**（kaikki 有则优先，缺则豆包补，冲突记 flag）；
  IPA 仅补空缺；搭配/flag/level 入列。

## 4. 展示方案（web/api：法语自己的服务，与 es/it 解耦）

**不复用 es/it 的服务**。法语给自己一套：

1. `packages/dict-core/src/` 新增 `french.ts`：`FrenchDictService` + `FrenchEntry` 类型，
   读法语专属列（aux/vgroup/gender/feminine/pp…），映射成法语自己的展示 shape。
2. 语言注册表加 `fr` 行，指向 `FrenchDictService`；`availableLanguages()` 检测
   `fr/synapse-dict-fr.sqlite` 存在后自动点亮切换器。
3. 展示新增法语专属渲染：动词卡显示 **助动词徽标**（avoir/être）+ 动词组 + 过去分词、
   名词卡显示 **性别 + 不规则复数**、形容词卡显示 **阴性形**、IPA 高亮鼻元音；变位页经 exchange 内联原形。
4. synapse-web 划词弹窗：走法语 API，划到变位自动指回原形。

## 5. 设计要点

- **本质优先**：法语独有特征（avoir/être 助动词、过去分词、阴性形、动词三组、鼻元音）升为一等。
- **按语种解耦**：脚本层、服务层各自独立，互不引用；仅语言注册表一处汇总。
- **一种数据一个权威**：义项/变位 = kaikki；中文/性别/助动词/搭配/兜底IPA/难度 = 豆包（只填不造义项）。
- **IPA 两阶段**：①**入库=维基式精确源**（kaikki lemma 76% + 变位收割 90%+ + 豆包兜底）；
  ②**读取=本土词典标准**（`french.ts` 的 `normalizeFrenchIpa` 显示层规范化：去连结弧、去音节点、
  保留鼻元音/长音，和英语 `normalizePronunciation`、意语 `normalizeItalianIpa` 同一定位）。
- **不造 G2P**：法语正字法↔发音鸿沟太大，规则 G2P 性价比低；靠 kaikki 收割 + 豆包兜底达标。
- **drop-ledger** 全 tag 归桶不静默丢。

## 6. 待办清单（实现顺序）

- [x] `build.py`：法语专属 `dict` 表 ✅ 385,216 词条（lemma 90,688 + 变位 294,528）；
  IPA **77%**（其中从 lemma forms **收割回填 178,287** 条变位 IPA）；aux 7208/gender 92,532/
  阴性形 9120/过去分词 7318；drop-ledger 全 tag 已归桶
- [x] `fr/infl_compose.py`：法语变位组合器 ✅ 184 种真实组合验证（passé simple/subjonctif/
  形容词阴阳性数皆正确）
- [x] `b_translate.py`：豆包多合一 ✅ 小样验证（10 词覆盖各词性；aller/rester→être、manger→avoir、
  chien→chienne、beau→belle、eau→eaux、义项对齐无 misalign、CEFR/搭配/IPA 均正确、仲裁 merge 正确）
- [x] `dict-core/french.ts`：`FrenchDictService` ✅ 法语专属，不复用 es/it；typecheck 通过；
  `normalizeFrenchIpa` 去连结弧/音节点（/mɑ̃.ʒe/→/mɑ̃ʒe/）
- [x] 注册表加 `fr` 行；web `FrenchEntryView`（助动词/组/阴性形/过去分词/不变形徽标）✅ typecheck +
  API（`/api/langs` 含 fr、`/api/entries/manger?lang=fr` 返回全字段）均通过
- [ ] **全量豆包翻译 ~9 万 lemma（用户自己跑）**：`python3 b_translate.py --mode batch --concurrency 50`
  后 `--merge`（付费+耗时，可续跑）；跑完中文才齐，建议浏览器视觉验证
- [x] 老 stardict 版 `build.py`/`translate.py` 已被本方案覆盖重写
