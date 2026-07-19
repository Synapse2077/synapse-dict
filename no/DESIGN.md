# synapse-dict / no — 挪威语（书面语 Bokmål）划词词典（设计方案）

kaikki 骨架（免费、规则确定）+ 豆包血肉（中文/难度/搭配/兜底 IPA）。
产物：**`synapse-dict-no.sqlite`**（**挪威语专属 schema**，单表交付）。
数据源为 **Bokmål（书面语，lang_code=nb）** dump；Nynorsk 是另一套书面标准，本期不含。

> **设计立场（两条铁律，与 es/it/fr/pt/de 一致）**
> 1. 表/字段按**挪威语本质**设计，不合适的通用列该改就改、该删就删。
> 2. 代码**按语种拆分、互不引用**：挪语有自己的 `build/infl/translate` 脚本 + web 侧
>    `NorwegianDictService`。其它语种服务保持不动。**语言注册表是唯一共享点**。

## 0. 挪威语本质特征 → 一等字段（核心）

| 挪语本质 | 为何独特 | 落地 |
|---|---|---|
| **后置定冠词（suffiks bestemt artikkel）** | 挪语灵魂：定冠词是**词尾后缀**不是独立词——bil→bil**en**、bok→bok**a**、hus→hus**et**。学挪语＝掌握名词四格变化 | 名词四件套列 `def_sg`(定单数) + `indef_pl`(不定复数) + `def_pl`(定复数)；不定单数=lemma |
| **三性 en/ei/et（Bokmål 可两性）** | 阳/阴/中；Bokmål 保守派把阴性并入阳性（**共性 common**：bok「f or m」），故有 m/f/n/mf 四值 | 名词列 `gender` (m/f/n/mf) |
| **动词无人称变位** | 挪语动词不随人称变（像英语）；核心是时态形：现在-r / 过去 / 完成分词 | 动词列 `present`(kommer) + `preterite`(kom) + `pp`(kommet) |
| **弱动词四类 + 强动词 ablaut** | 弱动词按过去式词尾分 4 类（-et/-a、-te、-de、-dde），强动词换干元音（komme→kom） | 动词列 `vclass`（weak1-4/strong，由过去式词尾派生） |
| **形容词性数定式一致** | 中性 -t（fin→fint）、定/复数 -e（fine）、比较级 -ere / 最高级 -est | 形容词列 `neuter` + `definite` + `comparative` + `superlative` |
| **被动态 -s** | snakke→snakkes（综合被动，与助动词被动并存） | 落在变位行（passiv） |
| **声调 tonelag（toneme 1/2）** | 音高重音辨义（bønder/bønner），但 kaikki 几乎不标 | IPA 内偶见，不专列；不造 G2P |

**明确不设**：德语式 aux（挪语完成时统一用 ha，无 haben/sein 逐动词选择）；德语式四格变格
（挪语名词无格变化，只有定/不定 × 单/复，已由四件套表达）。IPA 覆盖仅 10%，**不造 G2P**，豆包兜底单音。

## 1. 数据画像（真实 dump 实测）

- 总条目 **76,274**（lang_code 全 nb）：noun 49,289 / verb 15,394 / adj 8,667 / name 1,220
- **IPA 覆盖仅 10%**（挪语 kaikki 音标极稀，且声调不标）→ 豆包兜底为主
- 名词 head 模板：`nb-noun-m1/m2/m3`(阳) / `nb-noun-n1/n2/n3`(中) / `nb-noun-c/cu`(共性 f-or-m) /
  `nb-noun-f/f1`(阴) / `nb-noun-mu/nu`(不可数) / `nb-noun-irreg`；另 ~3.7 万走通用 `head` 模板
  （expansion 同样带性别与四件套）
- 动词全走通用 `head` 模板，expansion 极规整：
  "komme (imperative kom, present tense kommer, simple past kom, past participle kommet, present participle kommende)"
- 形容词 expansion："fin (neuter singular fint, definite singular and plural fine, comparative finere,
  indefinite superlative finest, definite superlative fineste)"
- 变形 tag：definite/indefinite × singular/plural（名词）、past/participle/present/imperative/
  passive/supine（动词）、neuter/comparative/superlative（形容词）

## 2. 字段设计（挪语专属 `dict` 表）

```sql
CREATE TABLE dict (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  word        TEXT NOT NULL,
  word_norm   TEXT NOT NULL,   -- 小写 + æ→ae ø→o å→a，支持 ASCII 检索/前缀
  ipa         TEXT,
  pos         TEXT,
  is_lemma    INTEGER NOT NULL,

  -- 名词本质（性 + 后置定冠词四件套；不定单数=lemma 不另存）
  gender      TEXT,            -- 'm'|'f'|'n'|'mf'（en/ei/et；mf=共性）
  def_sg      TEXT,            -- 定单数（bilen / boka / huset）← 后置定冠词
  indef_pl    TEXT,            -- 不定复数（biler / bøker）
  def_pl      TEXT,            -- 定复数（bilene / husa）

  -- 动词本质（无人称变位；时态三形 + 弱/强类）
  present     TEXT,            -- 现在时（kommer，-r）
  preterite   TEXT,            -- 过去式 simple past（kom）
  pp          TEXT,            -- 过去分词（kommet）
  vclass      TEXT,            -- 'weak1'|'weak2'|'weak3'|'weak4'|'strong'（由过去式词尾派生）

  -- 形容词本质
  neuter      TEXT,            -- 中性单数（-t：fint）
  definite    TEXT,            -- 定式/复数（-e：fine）
  comparative TEXT,            -- 比较级（finere）
  superlative TEXT,            -- 最高级（finest）

  level       TEXT,            -- CEFR A1-C2（豆包）

  definition  TEXT, translation TEXT, meta TEXT,
  infl        TEXT, exchange TEXT, collocation TEXT, example TEXT, flag TEXT
);
CREATE INDEX idx_word ON dict(word COLLATE NOCASE);
CREATE INDEX idx_norm ON dict(word_norm);
```

## 3. 管线（脚本按语种独立，互不 import）

```
1. build.py + no/infl_compose.py   # kaikki JSONL → 挪语 dict 骨架（确定性）
   · 名词：expansion 抽 gender；forms 抽 def_sg/indef_pl/def_pl（后置定冠词四件套）
   · 动词：expansion 抽 present/preterite/pp；由过去式词尾派生 vclass（weak1-4/strong）
   · 形容词：expansion 抽 neuter/definite/comparative/superlative
   · 变形（senses 全 form_of）→ 独立词条，infl 存中文语法说明，exchange 反查原形
2. b_translate.py                  # 豆包批翻 lemma → zh + 缺口 gender/四件套/动词三形
                                   #   + 兜底单音 ipa（覆盖仅 10%，豆包为主）+ col + level + flag
```

- **IPA 不造 G2P**：挪语声调复杂、kaikki 覆盖仅 10%，豆包兜底单音（不强求声调 toneme）。
- merge 仲裁：kaikki 有则优先，缺口豆包补。

## 4. 展示（web/api：挪语自己的服务，与其它语种解耦）

1. `packages/dict-core/src/norwegian.ts`：`NorwegianDictService` + `NorwegianEntry`。
   **名词**：en/ei/et 冠词徽标 + 四件套著录行（bil · bilen · biler · bilene，后置定冠词高亮）。
   **动词**：时态三形行（komme · kommer · kom · kommet）+ 弱/强类徽标。
   **形容词**：中性/定式/比较级/最高级行。
2. 注册表加 `no`（speak locale nb-NO）；`App.tsx` 的 `NorwegianEntryView`；变形页经 exchange 内联原形。

## 5. 待办清单

- [ ] `build.py` + `no/infl_compose.py`：kaikki → 挪语骨架
- [ ] `dict-core/norwegian.ts`：`NorwegianDictService`（三性冠词、四件套、动词三形展示）
- [ ] 注册表加 `no`；web `NorwegianEntryView`
- [ ] **全量豆包翻译（用户自己跑）**：`cd no && python3 b_translate.py --mode batch --concurrency 50` 后 `--merge`
- [ ] 跑前小样验证：`--mode online --words "bil,bok,hus,komme,snakke,fin,stor"` 确认三性/四件套/动词三形/CEFR
