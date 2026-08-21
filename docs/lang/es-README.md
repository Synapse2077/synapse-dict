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

---

## 记账本 · v3 结构回补时逮到的（2026-08-20）

建 `entry` / `inflection` 两层时，**新结构让一批旧缺陷第一次变得可查询**。
下面每条都带数字、判据、以及判据的已知代价 —— 复查时**第一件事是重跑判据，不是照数字动手**
（`[[ledger-numbers-lie]]`：上次清 it 记账本，七件里四件的数字是错的）。

| # | 数字 | 判据 | 为什么这轮不动 |
|---|---|---|---|
| 1 | ✅ **已清**（见下节）｜原 934 条义项挂在小写行、词条却是大写词 | `sense.word_id <> entry.word_id`，用 **Python `casefold`** 比（SQLite 的 `lower()` 不认非 ASCII，`lower('Ángel')` 原样返回 —— 我第一版用 SQL 比，32 条重音大写词被误判成「不是大小写问题」） | `A` 的义项（字母 A / 象棋「象」）躺在 `a` 行、`FA` 在 `fa` 行、`LIBRE` 在 `libre` 行。修它要搬 `sense.word_id`，属内容改动 |
| 2 | **198** 条模型生成的西语释义标成了 `lang='en'` / `src='en-edition'` | `sense_src.src='en-edition'` 且 `text` 在英文版 dump 里找不到；`src_ref` 是 `dict:<id>#<行>:en` 而非 gap 收词器的 `kk:<w>#<i>:en` | 标签错不是内容错。`Segunda persona del singular…` 这类，来自 `fill_nogloss` 那一支 |
| 3 | ✅ **不是缺陷**（见下节）｜3,881 行有 `exchange` 却整列 `infl` 为空 | 直接查两列 | `absconder` 的 `alt_of` 指针后来被提升成正式义项（`obsolete form of esconder` 进了 `definition`），`infl` 清掉、`exchange` 留着。`Iraq→Irak`、`Qatar→Catar` 同族。**迁移前就存在**，闸②只拦涨 |
| 4 | ✅ **已清**：11,406 → **15** | 见下节 | 15 = `merer` 14 + `ethnographique` 1，`build.py:277` 有意不收 |
| 5 | ✅ 同上 | `JUNK_BASES` **只过滤了 `exchange`、没过滤 `infl` 行** | 旧列时代看不见；现在按同一份裁决表排除，不给它们建词头 |
| 6 | **14** 个词形「不同词条读音不同」 | 见 `docs/SCHEMA.md` §11.1 | 量小到能逐条读就逐条读。`pie` 脚 /pje/ vs 英语借词派 /pai/、`deal`、`Nike`、`geta`、`quiz`… 用 `pronunciation.tags` 记归属即可，不建多对多 |

### 结构现状（2026-08-20 落库后）

| 表 | 行数 | |
|---|---|---|
| `entry` | 117,667 | 词形 × 词性 × 词源号，`src_ref` 内容派生 |
| `sense.entry_id` | 147,042 条已挂锚 | = en-edition 证据的 98.85% |
| `inflection` | 1,091,106 | 从 `dict.infl` / `exchange` 迁出，逐字节可逆 |
| `pronunciation_entry` | — | **有意不建**，见 SCHEMA §11.1 |

闸：回归闸 A+B+C 三组全绿，变异 **14/14**；闸① `dict.infl` 反向重建 **0 字节差**；
读取路径 `probes/infl_read_path.ts` **4,000/4,000**，变异 3/3。


---

## 悬空原形指针：11,406 → 15（2026-08-20 当天清完）

`inflection.base_id` 建成的那一刻，10,867 条变形同时回答了「我的原形不在词典里」。
逐族回源后分成三类，判据全部锚在源头上：

| 族 | 规模 | 判据 | 处置 |
|---|---|---|---|
| **A 源头真缺词头** | 10,867 行 / **8,077** 个词 | 两版 dump 都只有它的**变形页**、没有词头页（`sublimatorio` 有 `sublimatorios/-a/-as` 三个变形页，词头页不存在） | 补 **8,075** 个词头（扣掉 2 个 JUNK） |
| **B wiktextract 粘出的伪词** | 518 行 | `base == 同条第一个 form_of + "se"` **且**词尾是分词+se | 503 行重指、15 行藏 |
| **C 多词 junk** | 15 行 | 在 `build.py` 的 `MW_DROP`/`MW_REPOINT` 裁决表里 | 11 行重指、4 行藏 |

### 🔴 C 族是本轮唯一「用户看得见的错」，而我一开始判反了

```
lo   zipf 6.89   变位形式：él and usted 的 宾格
te   zipf 6.52   变位形式：tú and vos 的 与格
les  zipf 5.88   变位形式：ellos and ellas 的 与格
```

`lo`/`te`/`les` 是西语最常用的词之一。我先查了「有没有死链」，答案是 0，
就据此判定「用户看不见」—— **判「看不看得见」不能只看链接，要看这些行落在什么词上。**
处置也不该是藏：`te` 确实是 `tú`/`vos` 的与格，事实是对的，
坏的只是 base 被英文粘住 ⇒ 重指到第一个代词（都在库里），保住这条真语法信息。

### A 族：补词头，**不补释义**

补：词形 / 去重音形 / 词性（从变形形的 `dict.pos` 确定性反推）/ 规则音标（`b_ipa`，`src='rule'`）。
不补释义 —— 这批全是生僻古旧单词，模型盲推这一族的错误率实测卡在 **24–25%**。
**宁可留诚实空白，不要四分之一是错的。**

⚠️ **代价**：这第一次打破了「每个词头都有中文」这个曾经 100% 成立的性质，
现在 177,837 个 lemma 里有 8,075 个（4.5%）没有释义。
换来的是这批词从「搜不到」变成「搜得到、知道词性、知道怎么读、知道有哪些变形形」——
`spanish.ts` 加了反查 `formsQuery`，前端只在**无义项**时显示这一块。

### 三个把我自己的判据打回去的地方

1. **`base == 第一个原形 + "se"` 会误伤 84 行真数据。** `acoparse`（= `acopar`+`se`）
   是真实的自复动词，源头写着「Participio de ahuchar **o de ahucharse**」。
   区分点是第一个原形是**分词**（`desemejado` ⇒ 分词+se 不成词）还是**不定式**。
2. **基线必须实测，不能猜。** C7 我猜 15+1=16，结果「少补一个词头」造成的 16
   恰好等于基线、被当正常吞掉，变异该红没红。猜高一条的代价不是宽松一点，
   是让整整一类回归对这道闸隐形。
3. **「悬空」的本质是指不到东西，不是某一列为 NULL。** C7 第一版只查 `base_id IS NULL`，
   删掉词头之后 `base_id` 仍非空、只是指向不存在的行 —— 变异当场暴露。

### 一个性能坑（与 [[query-perf-collation-traps]] 反方向）

`UPDATE inflection SET base_id=(SELECT d.id FROM dict d WHERE d.word=inflection.base)`
跑十分钟没跑完：`idx_word` 建的是 `word COLLATE NOCASE`，而这里要**精确**匹配，
索引用不上 ⇒ 109 万行每行一次全表扫。不是漏写 NOCASE，是**索引带了 NOCASE 而查询要精确**。
改成 Python 建映射 + `executemany`，20 秒。

### 闸

回归闸 C 组 **9 条**（C7 悬空 / C8 补收词头缩水 / C9 伪原形复活），
变异 **17/17**；闸① `dict.infl` 反向重建仍 **0 字节差**；
读取路径 2 万个词形 0 不符。


---

## 大小写折叠残留：934 → 0（2026-08-20）

判据一句话：**义项应该待在 `word` 等于 `entry.spelling` 的那一行。**
`entry.spelling` 记着 dump 的原拼写，是建 entry 层的副产品 ——
2026-08-07 那轮（`split_case_homographs`）没有这个凭据，6,083 条只能送模型判。

搬了 **904 + 103** 条，改的只有 `sense.word_id` / `sense.rank` / `entry.word_id` 三个整数。
`dict` 一列不动。效果：

```
搜 gracias  →  以前：谢谢 / 格拉西亚斯（洪都拉斯城镇）   现在：只有「谢谢」三条
搜 libre    →  以前：自由的 … / 革新自由主义（政党）    现在：只有形容词义项
搜 Gracias  →  以前：无                              现在：两条地名义项
搜 y        →  以前：字母 Y 的释义出现两遍             现在：一条
```

### 🔴 我在这一步犯的最重的一个错：机械判据盖过了人工裁决

第一版只用 `entry.spelling`，把 **103 条搬到了与 2026-08-07 裁决相反的行**上 ——
`Chad`（乍得）被搬去 `chad`（打孔屑）那行，`Trinidad` / `Palermo` / `Sábado` / `D` 同。
`sense_owner`（4,501 条，`split_case+recheck_lowercase@2026-08-07`）就是那轮的裁决表，
而我的脚本根本没读它。这正是 [[replay-scripts-undo-fixes]]：
**重放式脚本会静默撤销已完成的修复。判据没错，错在它不知道自己不是唯一的判据。**

⇒ 定成两级权威，`plan` 与闸 **共用同一个 `target_of` 函数**：

```
① sense_owner —— 2026-08-07 裁决过的，它说了算
② entry.spelling —— 裁决没覆盖到的才用它
```

⚠️ 共用判据有代价：`target_of` 自己错了这道闸看不出来 ⇒ **必须变异验证**（已做，18/18）。

### 顺带修的两处

* `build_entry_layer.build_rows` 把精确表与小写回退表写成了同一张
  （`Ángel` 的 id 比 `ángel` 小 ⇒ 占了 `'ángel'` 这个键），**17 个 entry 的 word_id 指错行**。
  源头已修，落库的那 17 行也已改正。
* C5 断言的**含义变了**：934 → 111，而这 111 条是**预期行为**
  （裁决把「复活节岛」判给大写行、dump 原拼写是小写，两者本就该不同）。
  真正管事的是新加的 C10。**基线改数字时必须同时改描述，否则下次有人照旧读。**

---

## 「有 exchange 无 infl」那 3,881 行：不是缺陷，是标题写错了

逐条看下来，这批全是**拼写变体**（`aqui`→`aquí` 常见误拼、`sólo`→`solo` 旧拼写、
`vídeo`→`video` 地区变体、`EEUU`→`EE. UU.` 缩写形），数据形状是对的：
释义写着「aquí 的常见误拼」、`exchange` 给出可点链接、没有语法说明所以 `infl` 为空。

**错的是页面上那个块的标题**：叫「变位形式」。而 `sólo`(zipf 5.79) / `asi`(5.21) /
`tambien`(4.98) 全是高频词。判据现成且确定性 —— **有语法说明才是变位，没有就只是指向另一个拼写**：

```tsx
<h3>{entry.inflNotes.length > 0 ? '变位形式' : '参见'}</h3>
```

⚠️ **es 没有契约闸**（`contract-check.tsx` 只覆盖意语），渲染层的规则只能在
回归闸 C11 从数据侧盯着（拼写变体词形不许冒出变形行）。**这是已知缺口。**


---

## 查询优化：搜索下拉 354ms → 1ms（2026-08-20）

`search()` 是**每敲一个字符跑一次**的路径。优化前：

    es  P50 1.9ms  P95 26ms  P99 210ms  max 295ms
    it  P50 5.2ms  P95 44ms  P99 184ms  max 490ms   ← it 更慢

### 瓶颈是排序，实测出来的

| 做什么 | 耗时 |
|---|---|
| 只过滤，不排序不 LIMIT（候选 2–3 万条） | 7–16 ms |
| 过滤 + LIMIT 20，**不排序** | **0 ms** |
| 过滤 + 排序 + LIMIT 20 | **35–59 ms** |

为了取 20 条，把 2–3 万条候选整个排了一遍。`ORDER BY` 里的 `LENGTH(word)` 和
`CASE WHEN lower(word)=lower(?)` 都不可索引，而 `word LIKE ? OR word_norm LIKE ?`
的 **OR 强制走 MULTI-INDEX OR** —— 实测建 `(is_lemma, LENGTH(word), word)` 索引后
`EXPLAIN QUERY PLAN` 里 `USE TEMP B-TREE FOR ORDER BY` 原样还在，耗时几乎没变。

### 判据：问题只在短前缀，而短前缀的答案完全由前缀决定

```
1 字符：中位 57ms  最慢 354ms      ← 全库只有 65 种
2 字符：中位 14ms  最慢  40ms      ← 977 种
3 字符：中位  1ms  最慢 114ms      ← `des` 这类高频前缀；9,436 种
4 字符：中位  0ms  最慢  12ms      ← 不预计算
```

⇒ `search_prefix(prefix, rank, word_id)` 预计算 1–3 字符的 top-50。
es 12,427 个前缀 / it 13,442 个（含大小写变体）。

**闸①**：每个前缀重跑实时查询，id 序列**逐位比**，100% 非抽样 ——
es 12,427/12,427、it 13,442/13,442 全部相同。
**闸②陈旧性**：记下建表时 `dict` 的行数与 max(id)。派生表的头号风险不是算错，
是**算对了然后数据变了没人重算**。es 挂在回归闸 C12、it 挂在 F1，
两条都做过变异验证（`it/tests/test_search_prefix_gate.py` 5/5）。

结果：**两个语种 1–3 字符前缀 max 都降到 1ms。**

### 三条可复用的

1. **缓存未命中 = 正确回退，不是错误。** 键就是调用方传的原字符串，查不到走实时查询。
   这条性质是有意的：SQLite 的 `lower()` 不认非 ASCII（`lower('Á')`='Á'），
   与其猜大小写归一规则，不如让键严格等于原串。
2. **做到 2 不够。** 1–2 字符降到 1ms 之后，最慢的变成 3 字符的 `des`（114ms）。
   ⚠️ 而且它在第一次取样里根本没出现 —— **换一组取样就看不见的尖峰，要点名不要只报分位数**。
3. **两个语种必须各写一份。** it 的 `ORDER BY` 是**两级**精确匹配
   （先 `word = ?` 再 `lower(word) = lower(?)`），抄西语那份会静默改掉排序。


---

## 话题②「页面展示排版」已结（2026-08-20，用户实看确认）

8-11 封版时留的三个话题里的第二个，三条线索逐条了结：

| 线索 | 结论 |
|---|---|
| 两支中文并排像重复（原记 62,059 条） | ✅ **已被 8-07 的 title/detail 设计化解**。`banco` 现在显示「银行」+ 副行「提供货币服务的企业」，读得通 |
| 徽标 `el · 阳` 被当正文 | ✅ 已修（8-12 前） |
| 超长定义撑版面 | ✅ **不是缺陷**。用户实看全库最长的一批（`crucero` 247 字、`banana` 232 字、`corzuela` 副行 255 字）后确认「还好，没问题」 |

### 🔴 我在这条上犯的错，值得单独记

我一度报「超长定义撑版面 1,649 条（>80 字）」当作待办。**这个结论是错的，而且错法很典型**：

1. 记忆笔记里有「超长定义撑版面」一句，我**当成既有结论继承了**；
2. 然后我去「验证」它 —— 查 `LENGTH(text) > 80` 得到 1,649 条，就说「确实还在」。

**字符长度根本不能区分「话啰嗦」和「破版」。** 真判据是 CSS 有没有阻止换行 ——
`.sense-zh` 是 `flex-wrap: wrap`、`.sense-detail` 是普通块级文本，全份 `styles.css`
只有两处 `white-space: nowrap`（搜索摘要行，还带 `text-overflow: ellipsis`，正是该有的处理）。
**一查就完了，我压根没查。**

⇒ 两条：
* **「撑版面」这类关于渲染的断言，只能靠渲染或 CSS 判定**，数据侧的任何代理量都不作数。
* **别把记忆笔记里的措辞当既有结论**。笔记记的是当时的判断，不是事实；
  复查时要重跑判据，而不是找一个数字去印证那句话。

⚠️ 同一批里「义项近重复 62,297」我也没渲染过就报了 —— 实际渲染出来是 title+detail 两行，
没有并排重复。**这两条是同一个错误的两个实例。**


---

## 展示层契约闸（2026-08-20 建，`apps/web/src/contract-check-es.tsx`）

意语那道闸 8-16 就有（17 条），西语一直没有 —— 而 8-20 这天西语改了**三处渲染**
（`inflNotes` 改读 `inflection` 表 / 「变位形式 vs 参见」按数据分标题 / 新增「变形形」区块），
三处都只有数据侧的闸盯着。**数据对不等于页面对。**

12 条断言，变异 **11/11**（数据类 3 + 渲染类 8）。
渲染类变异是「先正常渲染、再把渲染结果打坏」—— 只改数据的话组件照样忠实渲染，
那种变异**在构造上不可能红**（意语那份 8-18 重写时的教训）。

### 🔴 第一次跑就逮到 4 个真缺陷，其中最重的一个是我当天刚"修好"的

| 缺陷 | 规模 | 说明 |
|---|---|---|
| **变位说明整块不渲染** | **10,894 个词形** | 组件条件是 `entry.baseForms.length > 0 &&`，而 `baseForms` 来自 `dict.exchange`。`exchange` 为空、`infl` 非空的词形有 10,894 个 —— 头两个是 `lo`(zipf 6.89)、`te`(6.52)。**我当天刚把 `él and usted` 重指成 `él`，数据侧全绿，页面上一个字没变。** 改成 `baseForms \|\| inflNotes` |
| 词性标题显示英文原始串 | 97 处 | `POS_LABELS` 里是**意语的短码**（`sym`/`char`/`abbr`），而 es 的 `POS_MAP` 不映射这几个、原样透传 `symbol`/`character`/`abbrev`/`prep_phrase`… 一次补全 8 个 |
| 伪原形 `empelotadose` 印在页面上 | 1 | 见下 |
| 凭空多出的伪词头 | 1 | 同上，已删 |

### 🔴 `empelotadose`：我的修复被我自己后一步的产物挡住了

1. `fix_glued_reflexive_base` 的判据是「`base` == 该词形**第一个**可解析 base + `se`」——
   而 `empelotadas` 的第一个是 `empelotada`，粘接产物派生自第二个 `empelotado` ⇒ **漏网**。
2. 紧接着 `ingest_missing_bases` 给它**建了个词头** ⇒ `base_id` 变成非空。
3. 再跑第一步时，它的 `WHERE base_id IS NULL` **再也看不见这一行**。

两步各自都过了自己的闸。只有渲染出来才看得见。
⇒ 判据改成两处：「等于**任意一个**可解析 base + se」＋「**还没被处理过的行**」
（不是「`base_id` 为空的行」——后者会被后续步骤的产物遮住）。

### ⚠️ 同一次跑里，我自己写的判据错了三条

| 我第一版写的 | 假红 | 真相 |
|---|---|---|
| 「每条义项的中文都必须渲染」 | 535 | 组件默认折叠，只铺 `slice(0, SENSE_FOLD_AT)`。**折叠是有意的产品设计** |
| 「每条例句都必须渲染」 | 225 | 每义项 `slice(0,3)`、未挂靠 `slice(0,6)`，有意截断 |
| 「页面上不许出现 undefined」 | 1 | `espacio` 的英文原文里就写着 "an **undefined** period of time" —— 真内容 |

⇒ 三条的共同点：**拿我的期望当判据，而不是组件自己的规则**。
修法一律是「判据与实现共用同一份规则」——`SENSE_FOLD_AT_ES` 现在从 `App.tsx` **导出**给闸用，
两处各写一个 8 就等于改一处另一处静默失效。
