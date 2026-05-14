# 词典数据说明（synapse-dict.sqlite）

## 数据库概览

| 指标 | 数值 |
|------|------|
| 总词条数 | 3,929,564 |
| 中文翻译覆盖 | 3,929,564（100%） |
| 英文释义（definition） | 703,760（17.9%） |
| 词性（pos） | 483,535（12.3%） |
| 词形变化（exchange） | 556,777（14.2%） |

## 表结构（stardict）

| 字段 | 类型 | 说明 | 覆盖率 |
|------|------|------|--------|
| id | INTEGER | 主键 | 100% |
| word | TEXT | 单词原文 | 100% |
| phonetic | TEXT | 通用音标（ECDICT 原始） | 9.2%（361,585） |
| phonetic_uk | TEXT | 英式音标（Wiktionary 补充） | 2.2%（85,973） |
| phonetic_us | TEXT | 美式音标（Wiktionary 补充） | 2.2%（85,096） |
| definition | TEXT | 英文释义 | 17.9%（703,760） |
| translation | TEXT | 中文翻译 | 100%（3,929,564） |
| pos | TEXT | 词性 | 12.3%（483,535） |
| collins | INTEGER | 柯林斯星级（1-5） | 部分 |
| oxford | INTEGER | 是否牛津核心词 | 部分 |
| tag | TEXT | 标签（考试词汇等） | 部分 |
| bnc | INTEGER | BNC 词频排名 | 部分 |
| frq | INTEGER | 美国当代语料库词频排名 | 部分 |
| exchange | TEXT | 词形变化关系 | 14.2%（556,777） |
| detail | TEXT | 详细释义 | 部分 |
| audio | TEXT | 音频路径（暂未使用） | 空 |

## 数据来源

### 1. ECDICT 基础数据（约 340 万词）
- 来源：[ECDICT 开源词典](https://github.com/skywind3000/ECDICT)
- 包含：单词、通用音标（phonetic）、英文释义、中文翻译、词频、词形变化等
- 中文翻译覆盖：约 80%（原始状态）

### 2. Wiktionary 新词导入（约 53 万词）
- 来源：[kaikki.org](https://kaikki.org/dictionary/English/) 的 Wiktextract 数据
- 原始文件：`data/raw/kaikki.org-dictionary-English.jsonl`（约 145 万词条，20GB）
- 导入脚本：`scripts/import-wiktionary-newwords.py`
- 导入内容：word、definition、pos（仅导入 ECDICT 中不存在的新词）

### 3. Wiktionary 音标补充
- 导入脚本：`scripts/import-wiktionary-phonetics.py`
- 补充内容：phonetic_uk、phonetic_us
- 覆盖情况：约 8.6 万词获得了英式/美式音标

## 已完成的数据处理

### ✅ 中文翻译（100% 覆盖）

**处理流程：**
1. ECDICT 原始翻译覆盖约 80% 词条
2. 使用豆包大模型（Volcengine Ark SDK）批量翻译剩余约 53 万词
   - 脚本：`scripts/fetch-translation-batch.py`
   - 模型：豆包（doubao），40 词/批，100 并发
   - 输出：`data/intermediate/doubao-translation.jsonl`（中间结果，可删除）
3. JSONL 结果合并入 SQLite
   - 脚本：`scripts/merge-translation.ts`
4. API 无法处理的 287 个特殊词手动翻译
   - 文件：`data/intermediate/manual-translation.jsonl`（已合并，可删除）
5. 最终结果：3,929,564 词全部有中文翻译

### ✅ 词形描述追加（9.3 万词）

**处理流程：**
- 脚本：`scripts/patch-exchange-translation.py`
- 逻辑：根据 exchange 字段中的 `0:基础词` 关系，在翻译前追加词形描述
- 示例：`destroyed` → `(destroy 的过去式和过去分词) vt. 破坏, 毁坏...`
- 映射规则（确定性，非 AI）：
  - `s` → 复数, `p` → 过去式, `d` → 过去分词
  - `dp/pd` → 过去式和过去分词, `i` → 现在分词
  - `3` → 第三人称单数, `r` → 比较级, `t` → 最高级

### ✅ Wiktionary 新词导入（约 53 万词）

- 脚本：`scripts/import-wiktionary-newwords.py`
- 仅导入 ECDICT 中不存在的词
- 导入字段：word、definition、pos

### ✅ Wiktionary 音标补充（约 8.6 万词）

- 脚本：`scripts/import-wiktionary-phonetics.py`
- 仅补充 phonetic_uk 和 phonetic_us
- 不覆盖已有数据

## 未完成 / 可优化项

### 🔲 音标覆盖率提升
- 当前有任一音标的词：391,771（10.0%），其余 90% 无音标
- phonetic（通用）有 36.2 万词，但 phonetic_uk/us 各只有 ~8.6 万
- **程序兜底方案**：展示时优先 phonetic_uk → phonetic → 空；派生词通过 exchange 的 `0:` 回溯基础词取音标
- Wiktionary 也仅 9.2%（13.4 万词条）有 IPA 音标，补充空间有限
- 旧 phonetic 字段未迁移到 uk/us（格式不统一，难以判断属于哪种口音）

### 🔲 发音音频
- audio 字段当前为空，暂未接入发音数据
- Wiktionary 音频包（20GB）中英语部分约 8.8 万独立单词，覆盖率仅 2.3%
- 且 Wikimedia Commons 链接在中国大陆访问不稳定
- **候选方案**：
  - 方案 A：TTS 生成（pyttsx3 离线免费 / 火山引擎 TTS 付费高质量）
  - 方案 B：Wiktionary 音频文件下载后自托管
  - 方案 C：混合方案 — 常用词预生成 + 长尾词实时 TTS 缓存
- TTS 不区分美英，需用不同音色分别生成两份
- 派生词可直接用 TTS 发音，不依赖音标数据

### 🔲 Wiktionary 其他字段
- Wiktextract 数据中还有未入库的字段：
  - `translations`：多语言翻译（含中文释义，可与现有翻译交叉验证）
  - `etymology_text`：词源说明
  - `synonyms` / `antonyms`：同义词 / 反义词
  - `categories`：分类标签
  - `derived` / `related`：派生词 / 相关词
- 这些字段可按需后续导入

### 🔲 phonetic 字段格式统一
- ECDICT 原始 phonetic 格式不统一（部分带 `/`，部分不带；部分用 ASCII 近似）
- Wiktionary 的 phonetic_uk/us 统一为标准 IPA
- 如需统一，需要清洗 ECDICT 的旧音标数据

## 脚本说明

| 脚本 | 用途 | 运行方式 |
|------|------|----------|
| `scripts/fetch-translation-batch.py` | 批量调用豆包 API 翻译缺失中文释义 | `python3 scripts/fetch-translation-batch.py` |
| `scripts/merge-translation.ts` | 将 JSONL 翻译结果合并到 SQLite | `npx tsx scripts/merge-translation.ts` |
| `scripts/import-wiktionary-newwords.py` | 从 Wiktionary 导入新词 | `python3 scripts/import-wiktionary-newwords.py` |
| `scripts/import-wiktionary-phonetics.py` | 从 Wiktionary 补充英美音标 | `python3 scripts/import-wiktionary-phonetics.py` |
| `scripts/patch-exchange-translation.py` | 根据 exchange 追加词形描述 | `python3 scripts/patch-exchange-translation.py` |
| `scripts/test-doubao-format.ts` | 测试豆包翻译格式效果 | `npx tsx scripts/test-doubao-format.ts` |

## data/ 目录文件说明

| 文件 | 说明 | 是否可删 |
|------|------|----------|
| `synapse-dict.sqlite` | 主词典数据库 | ❌ 核心文件 |
| `intermediate/doubao-translation.jsonl` | 豆包翻译中间结果 | ✅ 已合并入库 |
| `intermediate/manual-translation.jsonl` | 手动翻译的 287 个特殊词 | ✅ 已合并入库 |
| `raw/kaikki.org-dictionary-English.jsonl` | Wiktionary 原始辅助源 | ❌ 构建输入 |
