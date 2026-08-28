// ============================================================================
// 法语词典服务 —— 法语专属，自包含，不引用其它语种（不复用 es/it 服务）。
//
// ═══ 2026-08-26 阶段 8：从「老扁平 dict 列」切到 v3 表 ═══
// 切之前这个文件只有 299 行，读的全是 `dict.ipa / dict.translation / dict.definition /
// dict.infl / dict.exchange / dict.collocation` —— 阶段 1.5～5 建的
// sense / sense_gloss / pronunciation / example / inflection / collocation **一张都没接**。
// 后果（回归闸 L 组量出来的）：
//     1,423,034 个词形在音标层里有音标，而老列 `dict.ipa` 是空的 ⇒ 用户看不到
//       740,366 条例句（中文 99.9%）一条都没接进来 ⇒ 用户看不到
// 这正是回归闸文件头写的第二种「修复被绕过」：**数据全对，展示层读的是别处。**
//
// ⚠️ 老的扁平列**一列都不再读**。它们是七月流水线压平在词形上的旧值，
//    与 v3 层会打架（`dict.ipa` 有 20.2% 与音标层主读音不同 —— 那不是冲突，
//    是同一个词的两种真读音，而老列取的是英文版那一支，见 docs/FR_PLAN.md）。
//    唯一还读的是**法语本质一等字段**（aux/vgroup/pp/gender/feminine…），
//    那些还没有 v3 的家 —— fr 的 `entry` 层虽然声明了 aux/vgroup/pp/gender 四列，
//    但**一列都没填**（0 / 2,543,172，见 entryAuxQuery 处的说明）。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';

// API 列表项契约（与其它服务结构一致；结构化类型，无需跨语种 import）。
export type FrenchSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

export type FrenchSense = {
  id: number;
  en: string | null;        // 英文对应词（sense_gloss lang=en kind=equivalent）
  zh: string | null;        // 中文释义（lang=zh kind=equivalent）
  fr: string | null;        // 法语定义（lang=fr kind=definition）—— 阶段 1.5 裁决收回来的
  pos: string | null;       // 逐义项词性
  gender: string | null;    // 逐义项性别（双性名词 livre m 书 / f 斤）
  regions: string[];        // 地区（Québec / Belgique / …）← sense_tag kind=region
  registers: string[];      // 语域（littéraire / familier …）← sense_tag kind=register
  // 🔴 2026-08-27 族 C：领域（geography / botany / medicine …）← sense_tag kind=topic
  //    法文版给 243,052 条可见义项标了 topics，2026-08-27 之前**一条都没收**：
  //    下面那个 `kind === 'region' ? … : null` 直接把它们 `continue` 掉了。
  //    ⚠️ 加了列不改这里 = 白做（it 上栽过，`gatto` 的下位词照样渲染出断括号）。
  topics: string[];
};

export type FrenchCollocation = { text: string; zh: string | null };

// 一条读音。`isPrimary` 是**数据层选好的**（音位式 > 音值式；法文版 > 英文版 > 其余版），
// 展示层不许自己再挑一次 —— 那就是第二把尺子。
export type FrenchReading = {
  ipa: string;
  notation: string | null;    // phonemic（音位式 \…\）/ narrow（音值式 […]）
  // 语境变体。目前只有 'liaison'（连诵形：`les` 在元音前的 /le.z‿/）。
  // 🔴 **不能塞进 `notation`** —— 那一列的含义是**转写风格**，这一列是**语境**，
  //    两个维度压成一个，日后必然打架（`notation` 还决定 `/…/` 还是 `[…]`）。
  context: string | null;
  region: string | null;      // fr-FR / fr-CA / fr-BE / fr-CH
  src: string | null;
  isPrimary: boolean;
};

// 一条例句。`bold` 是源头给的加粗区间（字符下标对），用来高亮词形出现的位置。
export type FrenchExample = {
  senseId: number | null;
  text: string;
  zh: string | null;
  en: string | null;          // 13,181 条源头自带的英文译文（免费的交叉真值）
  ref: string | null;         // 文献出处
  bold: Array<[number, number]>;
};

// 变形关系：这个词形是谁的什么形式。
export type FrenchInflection = {
  base: string;
  label: string | null;       // 中文标签（「阴性单数」「直陈式现在时第三人称单数」）
  clickable: boolean;         // 原形在库里查得到吗
};

// alt_of 指针：这个词形是另一个词的异体/旧拼写；把目标词的中文**跟随读取**出来。
export type FrenchAltOf = { target: string; zh: string | null; clickable: boolean };

// 词元页反向看到的变位/变形形：这个词有哪些形式。
export type FrenchForm = { form: string; label: string | null };

// 语义关系（阶段 5 补做，2026-08-27）。`total` 是**全部**目标数，`targets` 只带
// 要显示的前 FR_REL_CAP 个 —— 页面上写「近义词 12 / 共 87」靠的是这个差。
export type FrenchRelationTarget = { word: string; clickable: boolean };
export type FrenchRelationGroup = {
  kind: string; total: number; targets: FrenchRelationTarget[];
};
// 展示顺序：先近义反义（查词最常要的），再上下位，再整体部分。
// ⚠️ `alt_of` **不在这里** —— 它由 altOf 那条线单独承担，不是语义关系。
const FR_REL_ORDER = ['synonym', 'antonym', 'hypernym', 'hyponym',
                      'coordinate', 'holonym', 'meronym'];
const FR_REL_CAP = 12;

// 变位形式指向的原形（连同词义与本质字段，供变位页内联展示）。
export type FrenchBase = {
  word: string;
  pos: string | null;
  ipa: string | null;
  aux: string | null;
  gender: string | null;
  senses: FrenchSense[];
};

export type FrenchEntry = {
  lang: 'fr';
  id: number;
  word: string;
  ipa: string | null;           // = readings 里 isPrimary 那条，供词头单行展示
  pos: string | null;
  isLemma: boolean;
  // —— 法语本质（一等字段，仍在 dict 上，没有 v3 的家）——
  aux: string | null;           // avoir / être / both（复合时态助动词）
  vgroup: string | null;        // 1 / 2 / 3（动词组）
  transitivity: string | null;  // t / i / ti
  pronominal: boolean;          // 代词式/反身 se laver
  pp: string | null;            // 过去分词 participe passé
  gender: string | null;        // m / f / mf
  plural: string | null;        // 不规则复数形
  feminine: string | null;      // 阴性形（形容词 grand→grande；名词 acteur→actrice）
  invariable: boolean;          // 不变形
  adjPos: string | null;        // 形容词位置 pre / post / both
  government: string | null;    // 动词/形容词固定介词支配（如 "à + inf." / "de qch"）
  comparative: string | null;   // 不规则比较级（bon→meilleur）
  level: string | null;         // CEFR 难度等级 A1-C2
  // —— v3 层 ——
  senses: FrenchSense[];
  readings: FrenchReading[];    // 全部读音（含地区变体）
  examples: FrenchExample[];
  collocations: FrenchCollocation[];
  inflections: FrenchInflection[];   // 这个词形是**谁的**什么形式（正向）
  forms: FrenchForm[];               // 这个词**有哪些**形式（反向，词元页用）
  altOf: FrenchAltOf[];
  relations: FrenchRelationGroup[];   // 近义/反义/上下位…（阶段 5 补做）
  baseForms: string[];          // 变形 → 原形（去重，供旧视图用）
  bases: FrenchBase[];          // 原形词连同词义（服务端解析，供内联展示）
  inflNotes: string[];          // 该词形语法说明（= inflections 的中文标签，旧视图用）
  flag: string | null;
};

type FrRow = {
  id: number;
  word: string;
  pos: string | null;
  is_lemma: number;
  aux: string | null;
  vgroup: string | null;
  transitivity: string | null;
  pronominal: number | null;
  pp: string | null;
  gender: string | null;
  plural: string | null;
  feminine: string | null;
  invariable: number | null;
  adj_pos: string | null;
  government: string | null;
  comparative: string | null;
  level: string | null;
  flag: string | null;
};

const ENTRY_COLS = `id, word, pos, is_lemma, aux, vgroup, transitivity, pronominal,
       pp, gender, plural, feminine, invariable, adj_pos, government, comparative, level, flag`;

// 音标显示层清理。
//
// 🔴 2026-08-26 大幅缩水，**去掉了原来的 ɑ→a 折叠**。
//    老版本注释写着「Larousse 式，现代法语已合并 pâte /pɑt/→/pat/」，
//    那是**扁平列时代的补丁** —— 那时一个词形只有一条音标，折叠掉看不出损失。
//    现在音标层把 `ma.ʃa.sjɔ̃` 与 `mɑ.ʃa.sjɔ̃` 当**两条真变体**分开存着
//    （法文版自己就同时收了），再折叠会有两个后果：
//      ① 读音表出现两行一模一样的音标
//      ② 抹掉源头**有意记录**的区别
//    `[[aim-for-perfect-not-cheap]]`：别用展示层补丁代替把事情做进数据里。
//
// 音标层已经是**裸存**（`[[ipa-bare-storage-convention]]`：不带 /…/，展示层统一加），
// 且建层时已归一（去定界符/音节点/重音符）。所以这里只留两道兜底：
//   ① 万一还有定界符残留就剥掉（回归闸 A1 守着，正常应为 0）
//   ② 去连结弧 t͡ʃ→tʃ（tie bar 是排版记号，不是音位）
function normalizeFrenchIpa(ipa: string | null): string | null {
  if (!ipa) return ipa;
  let s = ipa.trim();
  if (s.startsWith('/') && s.endsWith('/')) s = s.slice(1, -1);
  if (s.startsWith('\\') && s.endsWith('\\')) s = s.slice(1, -1);
  if (s.startsWith('[') && s.endsWith(']')) s = s.slice(1, -1);
  return s.replace(/͡/g, '').trim();
}

function parseBold(raw: string | null): Array<[number, number]> {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    if (!Array.isArray(v)) return [];
    return v.filter((p) => Array.isArray(p) && p.length === 2
      && typeof p[0] === 'number' && typeof p[1] === 'number') as Array<[number, number]>;
  } catch {
    return [];
  }
}

export class FrenchDictService {
  readonly databasePath: string;
  readonly lang = 'fr';
  private readonly db: DatabaseSync;
  private readonly statsQuery;
  private readonly exactQuery;
  private readonly normQuery;
  private readonly hasContentQuery;
  private readonly prefixQuery;
  private readonly prefixCacheQuery;
  private readonly briefQuery;
  private readonly sensesQuery;
  private readonly tagsQuery;
  private readonly entryAuxQuery;
  private readonly pronQuery;
  private readonly exampleQuery;
  private readonly colsQuery;
  private readonly inflQuery;
  private readonly formsQuery;
  private readonly altQuery;
  private readonly relationQuery;
  private readonly altTargetQuery;
  private readonly existsExactQuery;
  private readonly existsNormQuery;

  constructor(databasePath: string) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');

    // 🔴 `translated` 改成**数**义项层，不再数 `dict.translation`（那是旧扁平列，
    //    只有 385,450 行，而 v3 的中文覆盖 657,582 条义项）。
    this.statsQuery = this.db.prepare(`
      SELECT
        COUNT(*) AS total,
        SUM(is_lemma) AS lemmas,
        (SELECT COUNT(DISTINCT word_id) FROM sense WHERE COALESCE(hidden,0)=0) AS translated,
        (SELECT COUNT(DISTINCT word_id) FROM pronunciation) AS ipa
      FROM dict
    `);

    // 🔴 精确大小写是第一排序键。阶段 3a 把大小写折叠拆开之后，
    //    COLLATE NOCASE 会同时命中 `abbe` 与 `Abbé` 这类两行；不把精确匹配排前面，
    //    搜小写普通词就会命中大写专名 —— es 至今如此（搜 gracias 排第一的是洪都拉斯的城镇）。
    //    ⚠️ 这段注释里不能用反引号：它在模板字符串里会直接截断 SQL。
    // 第二键「有没有可见义项」：撇号归一/大小写拆分之后会留下空壳行（有意保留，可逆），
    //    不加这条，查那个拼写就落到空壳上、界面一片空白。
    this.exactQuery = this.db.prepare(`
      SELECT ${ENTRY_COLS} FROM dict
      WHERE word = ? COLLATE NOCASE
      ORDER BY CASE WHEN word = ? THEN 0 ELSE 1 END,
               CASE WHEN EXISTS(SELECT 1 FROM sense s
                                WHERE s.word_id = dict.id AND COALESCE(s.hidden,0)=0)
                    THEN 0 ELSE 1 END,
               is_lemma DESC
      LIMIT 1
    `);

    // 归一列回落：`word` 精确匹配落空时才用（撇号写法不同 / 没打重音符）。
    // 法语这一条比 it 更要紧：撇号在法语里是**高频构词成分**（l'eau、d'accord、qu'il），
    //    源头弯撇号 ’ 与直撇号 ' 混用，`norm_apos` 已把库里统一成直撇号，
    //    但用户从网页复制过来的往往是弯的。
    this.normQuery = this.db.prepare(`
      SELECT ${ENTRY_COLS} FROM dict
      WHERE word_norm = ?
      ORDER BY CASE WHEN EXISTS(SELECT 1 FROM sense s
                                WHERE s.word_id = dict.id AND COALESCE(s.hidden,0)=0)
                    THEN 0 ELSE 1 END,
               CASE WHEN replace(word, char(8217), '''') = ? THEN 0 ELSE 1 END,
               is_lemma DESC, LENGTH(word) ASC, word ASC
      LIMIT 1
    `);

    // 这一行是不是空壳：既没有可见义项，也不是任何词的变形。
    this.hasContentQuery = this.db.prepare(`
      SELECT (SELECT COUNT(*) FROM sense WHERE word_id = ? AND COALESCE(hidden,0)=0)
           + (SELECT COUNT(*) FROM inflection WHERE word_id = ?) AS n
    `);

    // 短前缀预计算（阶段 9，2026-08-28，`fr/pipeline/build_search_prefix.py`）。
    // `search()` 每敲一个字符跑一次，实测 1 字符前缀最慢 **264.7 ms**（fr 是六个语种里
    // 最大的库，2,086,292 行）。瓶颈是排序不是过滤：为了取 20 条把上万条候选整个排一遍，
    // 而 `LENGTH(word)` 与 `lower(word)=lower(?)` 都不可索引、`OR` 又强制 MULTI-INDEX OR。
    // 1–3 字符前缀的答案完全由前缀决定 ⇒ 预算好（26,781 个前缀 / 506,040 行）。
    // ⚠️ **查不到就回退实时查询**，结果一样只是慢一点 —— 未命中不是错误。
    //    es/it 2026-08-20 就做了这件事，**fr 漏到了阶段 9**：
    //    `[[query-perf-collation-traps]]` 性能问题要等数据长大才咬人。
    this.prefixCacheQuery = this.hasTable('search_prefix') ? this.db.prepare(`
      SELECT d.id, d.word, d.is_lemma, d.pos
      FROM search_prefix p JOIN dict d ON d.id = p.word_id
      WHERE p.prefix = ?
      ORDER BY p.rank
      LIMIT ?
    `) : null;

    // 前缀检索：命中 word 或 word_norm（去重音，便于无重音输入）；lemma 优先、短词优先。
    this.prefixQuery = this.db.prepare(`
      SELECT id, word, is_lemma, pos
      FROM dict
      WHERE word LIKE ? COLLATE NOCASE OR word_norm LIKE ? COLLATE NOCASE
      ORDER BY
        CASE WHEN lower(word) = lower(?) THEN 0 ELSE 1 END,
        is_lemma DESC,
        LENGTH(word) ASC,
        word ASC
      LIMIT ?
    `);

    // 列表项的一行摘要 = 第一条义项的中文。
    // 🔴 单独一条按 word_id 的查询，**不做成前缀查询里的相关子查询** ——
    //    那样 SQLite 会从选择性最差的一头入手（`[[query-perf-collation-traps]]`，
    //    es 的 `mano` 词条页曾因此跑了 6.3 秒）。先 LIMIT 出候选，再对这 ≤20 个 id 各查一次。
    this.briefQuery = this.db.prepare(`
      SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
      WHERE s.word_id = ? AND COALESCE(s.hidden, 0) = 0
        AND g.lang = 'zh' AND g.kind = 'equivalent' AND g.seq = 0
      ORDER BY s.rank LIMIT 1
    `);

    // 一个词的义项：出版层 `sense` 定顺序，各语言说法从 `sense_gloss` 取。
    // fr 的三种 gloss（实测取值，不是猜的）：
    //     zh equivalent 657,582 ｜ fr definition 648,506 ｜ en equivalent 124,908
    this.sensesQuery = this.db.prepare(`
      SELECT s.id, s.pos, s.gender,
             (SELECT text FROM sense_gloss
               WHERE sense_id = s.id AND lang = 'en' AND kind = 'equivalent' AND seq = 0) AS en,
             (SELECT text FROM sense_gloss
               WHERE sense_id = s.id AND lang = 'zh' AND kind = 'equivalent' AND seq = 0) AS zh,
             (SELECT text FROM sense_gloss
               WHERE sense_id = s.id AND lang = 'fr' AND kind = 'definition' AND seq = 0) AS fr
      FROM sense s
      WHERE s.word_id = ? AND COALESCE(s.hidden, 0) = 0
      ORDER BY s.rank
    `);

    // 逐义项标签。fr 只有两类（实测）：register 15,101 / region 2,759。
    this.tagsQuery = this.db.prepare(`
      SELECT t.sense_id, t.kind, t.value
      FROM sense_tag t JOIN sense s ON s.id = t.sense_id
      WHERE s.word_id = ? AND COALESCE(s.hidden, 0) = 0
    `);

    // 🔴🔴 这里原本抄了 it 的「助动词从 entry 层聚合」——**两个错，都来自盲抄**：
    //    ① fr 的 `entry.aux` **整列是空的**（0 / 2,543,172）。
    //       `entry` 建表时声明了 aux/vgroup/pp/gender 四列，阶段 2 一列都没填。
    //    ② 抄来的 WHERE 写着 `pos = 'verb'`，而 fr 的 `entry.pos` 取值是 `v`
    //       —— 就算 aux 有值也永远匹配不上。
    //    ⇒ `[[es-v3-structure-backfill]]`：**照搬别的语言结构前，先量这门语言有没有那个数据。**
    //    现状：fr 的助动词真值只有 `dict.aux`（12,969 行），两边**没有打架**
    //    （实测同时有值且不同的词形 = 0，因为 entry 侧压根没值）。
    //    📋 记账：把 aux/vgroup/pp/gender 填进 entry 层是数据侧的事，不在阶段 8 做。
    this.entryAuxQuery = this.db.prepare(`
      SELECT DISTINCT aux FROM entry
      WHERE word_id = ? AND aux IS NOT NULL AND aux <> ''
    `);

    // 读音：`pronunciation` 表（阶段 4 建，阶段 8 才接上展示层）。
    // 🔴 `is_primary DESC` 是第一排序键 —— 默认展示的那条必须稳定排第一，
    //    它是数据层按「音位式 > 音值式；法文版 > 英文版 > 其余版」选出来的，
    //    展示层不许自己再挑一次（那就是第二把尺子）。
    // ⚠️ fr 的 `pronunciation` **没有 hidden 列**（it 有）—— 不能照抄 it 的 WHERE。
    //    该藏的在阶段 7 已经**删行**处理了（150 条 X-SAMPA），不是藏。
    this.pronQuery = this.db.prepare(`
      SELECT ipa, notation, region, src, is_primary, pos, context
      FROM pronunciation
      WHERE word_id = ?
      ORDER BY is_primary DESC, CASE WHEN notation = 'phonemic' THEN 0 ELSE 1 END,
               LENGTH(ipa) ASC, ipa ASC
    `);

    // 例句 + 中文。⚠️ `idx_ex_word` 是 BINARY 索引，**不能写 COLLATE NOCASE** ——
    //    加了就用不上索引、退化成扫 74 万行。传进来的是 DB 里的词形（getEntry 已归一）。
    // 🔴 `hidden` 必须过滤：加了列不改这里 = 白做（it 上栽过，
    //    `gatto` 的下位词照样渲染出断括号，而那个脚本的 --verify 还报了绿）。
    this.exampleQuery = this.db.prepare(`
      SELECT e.sense_id, e.text, e.ref, e.bold,
             (SELECT text FROM example_gloss WHERE example_id = e.id AND lang = 'zh') AS zh,
             (SELECT text FROM example_gloss WHERE example_id = e.id AND lang = 'en') AS en
      FROM example e
      WHERE e.word = ? AND COALESCE(e.hidden, 0) = 0
      ORDER BY CASE WHEN e.sense_id IS NULL THEN 1 ELSE 0 END, e.sense_id, e.id
    `);

    this.colsQuery = this.db.prepare(`
      SELECT c.text,
             (SELECT text FROM collocation_gloss
               WHERE collocation_id = c.id AND lang = 'zh') AS zh
      FROM collocation c WHERE c.word_id = ? ORDER BY c.rank
    `);

    // 变形关系：读 `inflection` 表（阶段 2 从 dict.infl/exchange 两列字符串迁来）。
    // 🔴 不再读那两列 —— 它们把一个词形的多条关系拼在一个字符串里，且**含 alt_of**
    //    （阶段 2a 已把 alt_of 移回词条层，见 sense_relation）。
    this.inflQuery = this.db.prepare(`
      SELECT base, label_zh FROM inflection WHERE word_id = ? ORDER BY id
    `);

    // 反向：这个词**有哪些**形式（词元页看自己的变位表）。走 `base_id`（有 idx_infl_base）；
    //    **不走 `base` 字符串** —— 那一列没有索引，按它查就是扫 227 万行。
    // 🔴 必须 DISTINCT。同一个词形+标签会重复多次，因为同一个词的**多个词条**
    //    （不同词源/词性）各产生一条：`chat` 的「复数 chats」有 3 行、
    //    `grand` 的每个标签 2 行。不判重，页面上就是一串一模一样的条目。
    //    ⚠️ 这是 it 记过的形状：读取侧按**投影后的两列**判重，与写入侧的全列判重
    //       天生不同，那不是「被绕过」。
    this.formsQuery = this.db.prepare(`
      SELECT DISTINCT d.word AS form, i.label_zh AS label
      FROM inflection i JOIN dict d ON d.id = i.word_id
      WHERE i.base_id = ?
      ORDER BY i.label_zh IS NULL, i.label_zh, d.word
    `);

    // alt_of 指针。
    // ⚠️ fr 的 sense_relation **没有 hidden 列**，不能照抄 it 的 WHERE。
    this.altQuery = this.db.prepare(`
      SELECT DISTINCT target FROM sense_relation WHERE word_id = ? AND kind = 'alt_of'
    `);

    // 语义关系（近义/反义/上下位/整体部分/同级）。
    // 🔴 这段代码上一版写着「fr 的 sense_relation 只有 alt_of 一种，所以不做相关词
    //    分组」—— 那句话当时是**诚实的现状记录**，但 2026-08-27 阶段 5 补做了关系层
    //    （+300,611 行）之后它就成了错的。`[[it-display-layer-stage8]]`：
    //    **数据层补完不接展示层，等于没做**（it 那轮"关系例句录音三张表从没人看"）。
    // ⚠️ 排除 `alt_of` —— 它是变形/异体指针，由上面 altQuery 那条线单独承担，
    //    混进「近义词」里就是把"这是同一个词的另一种拼法"说成"这是个近义词"。
    this.relationQuery = this.db.prepare(`
      SELECT kind, target FROM sense_relation
      WHERE word_id = ? AND kind <> 'alt_of'
    `);

    // 把目标词的中文**跟随读取**出来（不复制数据）。
    // 🔴 写成「先用标量子查询定位到唯一 word_id，再顺着索引取」——
    //    直接 JOIN 会让 SQLite 从选择性最差那头入手（先扫遍 65 万条 lang='zh'），
    //    it 上实测 386 ms → 0.0 ms。
    this.altTargetQuery = this.db.prepare(`
      SELECT (SELECT text FROM sense_gloss
               WHERE sense_id = s.id AND lang = 'zh' AND seq = 0) AS text
      FROM sense s
      WHERE s.word_id = (SELECT id FROM dict WHERE word = ? COLLATE NOCASE LIMIT 1)
        AND COALESCE(s.hidden, 0) = 0
      ORDER BY s.rank LIMIT 1
    `);

    // 目标点不点得动。🔴 判据必须与 getEntry 的解析路径一致：那边落空会走归一列再查一次。
    //    只查 `word` 会把 `l’eau`（源头弯撇号、库里直撇号）标成点不动，而它其实查得到 ——
    //    「说点不动、实际点得动」和反过来一样是骗人。
    // 🔴🔴 2026-08-27 拆成两条：原来是 `WHERE word = ? OR word_norm = ?`，
    //    查询计划是 **`SCAN dict`** —— `OR` 让 SQLite 一个索引都用不上
    //    （`[[search-prefix-precompute]]`：`OR` 强制 MULTI-INDEX OR）。
    //    命中时 `LIMIT 1` 立刻停所以看不出来，**未命中要扫完 208 万行：334 ms 一次**。
    //    这个缺陷一直潜伏着：以前每个词只查 1–2 次（异体指针，且目标基本都在库里）；
    //    阶段 5 补做关系层之后一个词最多查 84 次、目标多半是不在库里的多词短语
    //    ⇒ 契约检查从 5 分钟变成跑 20 分钟还没完。
    //    `[[query-perf-collation-traps]]`：**性能问题要等数据长大才咬人。**
    //
    // 🔴 顺带修掉一个**正确性** bug：`getEntry` 的解析路径第一步是
    //    `word = ? COLLATE NOCASE`，而这里原来是 BINARY ⇒ `Chien` 会被说成
    //    "点不动"，而它其实点得动。**判据只许一份**（`[[fix-regression-and-gate]]`）。
    //    下面两条与 `row()` 的两步一一对应：① exactQuery ② normQuery。
    this.existsExactQuery = this.db.prepare(`
      SELECT 1 AS n FROM dict WHERE word = ? COLLATE NOCASE LIMIT 1
    `);
    this.existsNormQuery = this.db.prepare(`
      SELECT 1 AS n FROM dict WHERE word_norm = ? LIMIT 1
    `);
  }

  getStats() {
    return this.statsQuery.get() as Record<string, number>;
  }

  /** 这个库里有没有这张表。⚠️ 预计算表是**可选**的：指向旧备份时也必须能起得来。 */
  private hasTable(name: string): boolean {
    return !!this.db.prepare(
      "SELECT 1 AS n FROM sqlite_master WHERE type='table' AND name = ?").get(name);
  }

  search(query: string, limit = 20): FrenchSearchItem[] {
    const keyword = query.trim();
    if (!keyword) return [];
    // 先查预计算表；**未命中一律回退实时查询**（键严格等于原串，猜不中不是错误）。
    let rows = (this.prefixCacheQuery?.all(keyword, limit) ?? []) as Array<{
      id: number; word: string; pos: string | null;
    }>;
    if (rows.length === 0) {
      const like = `${keyword}%`;
      rows = this.prefixQuery.all(like, like, keyword, limit) as Array<{
        id: number; word: string; pos: string | null;
      }>;
    }
    return rows.map((r) => ({
      id: r.id,
      word: r.word,
      pos: r.pos,
      brief: (this.briefQuery.get(r.id) as { text: string } | undefined)?.text ?? null,
    }));
  }

  private senses(wordId: number): FrenchSense[] {
    const rows = this.sensesQuery.all(wordId) as Array<{
      id: number; pos: string | null; gender: string | null;
      en: string | null; zh: string | null; fr: string | null;
    }>;
    const reg = new Map<number, string[]>();
    const top = new Map<number, string[]>();
    const lex = new Map<number, string[]>();
    for (const t of this.tagsQuery.all(wordId) as Array<{
      sense_id: number; kind: string; value: string;
    }>) {
      const m = t.kind === 'region' ? reg
        : t.kind === 'register' ? lex
          : t.kind === 'topic' ? top : null;
      if (!m) continue;
      const arr = m.get(t.sense_id) ?? [];
      arr.push(t.value);
      m.set(t.sense_id, arr);
    }
    return rows.map((r) => ({
      id: r.id,
      en: r.en,
      zh: r.zh,
      fr: r.fr,
      pos: r.pos,
      gender: r.gender,
      regions: reg.get(r.id) ?? [],
      registers: lex.get(r.id) ?? [],
      topics: top.get(r.id) ?? [],
    }));
  }

  // 目标点不点得动。🔴 判据必须与 `row()` 的解析路径**逐步一致**：
  //    ① `word = ? COLLATE NOCASE`  ② 归一撇号后 `word_norm = ?`
  //    只查 ① 会把 `l’eau`（源头弯撇号、库里直撇号）标成点不动，而它其实查得到 ——
  //    「说点不动、实际点得动」和反过来一样是骗人。
  private clickable(w: string): boolean {
    if (this.existsExactQuery.get(w)) return true;
    return !!this.existsNormQuery.get(w.replace(/’/g, "'"));
  }

  private relationsOf(wordId: number): FrenchRelationGroup[] {
    const rows = this.relationQuery.all(wordId) as Array<{ kind: string; target: string }>;
    // 🔴 2026-08-28 第二轮外审：`fillâtre` 的 `beau-fils` 同时出现在「近义」和「下位」，
    //    `dictionnaire` 的 `glossaire` 同时是「近义」和「上位」，
    //    `Afghanistan` 的 `Kaboul` 同时是「近义」和「下位」（近义那条源头就是错的）。
    //    全库 1,035 对 / 833 个词形。
    //    ⇒ **同一个目标只留最具体的那一组**：上下位/整体部分/同类/反义 都比
    //      `synonym` 具体 —— 源头把「相关词」一股脑塞进 synonymes 是常态，
    //      而它同时又出现在某个精确关系里时，那个精确关系才是它真正的身份。
    //    ⚠️ 只在**展示层**去重，`sense_relation` 里两行都留着 —— 源头怎么说的
    //      是证据，不能因为我们的展示偏好就抹掉（`[[two-layer-sense-model]]`）。
    //    ⚠️ **只盖住 616 对**（含 synonym 的那些）。剩下 419 对不含 synonym
    //      （`antonym`+`coordinate` 311 对、`hypernym`+`hyponym` 35 对…）这里
    //      **有意不动**：`dénotation` 之于 `connotation` 确实既是反义又是同类，
    //      而 `hypernym`+`hyponym` 同时成立是源头自相矛盾，我判不了谁对。
    //      记在收尾单里，别让「规则覆盖了一部分」被读成「这一族清完了」。
    const specific = new Set<string>();
    for (const r of rows) if (r.kind !== 'synonym') specific.add(r.target);
    const byKind = new Map<string, string[]>();
    for (const r of rows) {
      if (r.kind === 'synonym' && specific.has(r.target)) continue;
      const list = byKind.get(r.kind) ?? [];
      if (!list.includes(r.target)) list.push(r.target);   // 同一目标可能来自两版
      byKind.set(r.kind, list);
    }
    // 认识的按 FR_REL_ORDER 排，不认识的排最后 —— **不丢，也不假装知道该排哪**
    const rank = (k: string) =>
      FR_REL_ORDER.indexOf(k) < 0 ? FR_REL_ORDER.length : FR_REL_ORDER.indexOf(k);
    const kinds = [...byKind.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
    return kinds.map((kind) => {
      const all = byKind.get(kind)!;
      return {
        kind,
        total: all.length,
        // 🔴 存在性只查**要显示的那几个**（≤ FR_REL_CAP）。
        //    每次查是微秒级，但 `chien` 的下位词有几百个，乘起来就不是了
        //    （`[[query-perf-collation-traps]]`：性能问题要等数据长大才咬人）。
        targets: all.slice(0, FR_REL_CAP).map((w) => ({
          word: w, clickable: this.clickable(w),
        })),
      };
    });
  }

  private row(word: string): FrRow | null {
    const exact = this.exactQuery.get(word, word) as FrRow | undefined;
    if (exact) {
      const n = (this.hasContentQuery.get(exact.id, exact.id) as { n: number }).n;
      if (n > 0) return exact;
    }
    // 精确命中落空、或命中的是空壳 ⇒ 走归一列再试一次（撇号写法 / 没打重音符）
    const norm = word.replace(/’/g, "'");
    const alt = this.normQuery.get(norm, norm) as FrRow | undefined;
    return alt ?? exact ?? null;
  }

  private mapEntry(row: FrRow, deep: boolean): FrenchEntry {
    // 🔴 按**归一后的音标字符串**判重。同一个词形的多条读音字符串完全相同、
    //    只是 notation/src 不同的，全库有 25,520 组 —— `chat` 的 `/tʃat/` 出现两次
    //    （fr 版一条、el 版一条）、`passer` 的 `pa.se` 既有音位式又有音值式。
    //    读者看到的是那串音标，「同一串出现两次」就是噪声；
    //    而「音位式与音值式一致」这个信息对查词的人没有价值。
    //    ⚠️ 判重发生在**读取侧、按投影后的一列**，与写入侧的
    //       `UNIQUE(word_id, ipa, notation)` 天生不同 —— 那不是「被绕过」。
    //    保留顺序里的第一条（已按 is_primary → 音位式优先 排好），所以主读音必然留下。
    const seenIpa = new Set<string>();
    const readings = (this.pronQuery.all(row.id) as Array<{
      ipa: string; notation: string | null; region: string | null;
      src: string | null; is_primary: number; pos: string | null;
      context: string | null;
    }>).map((p) => ({
      ipa: normalizeFrenchIpa(p.ipa) ?? p.ipa,
      notation: p.notation,
      region: p.region,
      src: p.src,
      isPrimary: p.is_primary === 1,
      // 🔴 **读音归属**（2026-08-27，族 D）：这条读音属于哪个词性的词条。
      //    法文版把每个词条的音标各写各的，我们以前全堆在词头 ——
      //    `en` 的 A1 介词旁边摆着名词义的 /ɑ̃.ky.le/、`bon` 旁边摆着 /ba.ta.jɔ̃/
      //    （bataillon 的缩写）。3,674 个词形跨词性读音不同。
      //    NULL = `legacy` 那 9,295 行（七月老流水线，没有词性坐标）。
      //    ⚠️ 该显示在哪儿由 `frReadingSlot`（App.tsx）判定，**判据只许一份**。
      pos: p.pos,
      // 语境变体（收尾单 A1，2026-08-27）。目前只有 'liaison'：119 条
      //    「拿连诵形冒充这个词自己的读音」的行 —— `les` 的 /le.z‿/ 是它在元音前
      //    的读法，不是 `les` 本身（/le/）。**不删**（那是真信息），标出来。
      context: p.context,
    })).filter((r) => {
      // 🔴 判重键只用**音标字符串本身**，不带地区。
      //    第一版把地区并进键里，于是 `passer` 的 /pa.se/（无地区）与
      //    [pa.se] fr-FR 仍并排显示 —— 而那两行读者看到的是同一串音。
      //    「法国读作 [pa.se]」在已经写了 /pa.se/ 之后不构成新信息；
      //    真正有信息的是**字符串不同**的地区变体（mɑ̃.ʒe vs 魁北克 mã.ʒe），
      //    那种本来就不会被这条判重挡掉。
      if (seenIpa.has(r.ipa)) return false;
      seenIpa.add(r.ipa);
      return true;
    });

    // 🔴 2026-08-28 第二轮外审：`quelles` 的「阴性复数」在页面上印了**四次**。
    //    `inflection` 里确实是四行 —— 英语版的 adj 与 pron 各一条、法文版
    //    `kk-fr:quelles:adj#0.0` 与 `#1.0` 各一条，**同一个语法事实的四份跨版证言**。
    //    全库同 (词形, 原形, 标签) 重复 175,074 组 / 多余 177,302 行。
    //    ⇒ 展示层按 (base,label) 去重；`inflection` 表**一行不删** —— 那是证据层，
    //      `src_ref` 各不相同，删了就再也说不清哪一版给的（`[[two-layer-sense-model]]`）。
    const seenInfl = new Set<string>();
    const infl = (this.inflQuery.all(row.id) as Array<{
      base: string; label_zh: string | null;
    }>).filter((i) => {
      const k = `${i.base}${i.label_zh ?? ''}`;
      if (seenInfl.has(k)) return false;
      seenInfl.add(k);
      return true;
    }).map((i) => ({
      base: i.base,
      label: i.label_zh,
      clickable: this.clickable(i.base),
    }));

    const altOf = (this.altQuery.all(row.id) as Array<{ target: string }>).map((a) => ({
      target: a.target,
      zh: (this.altTargetQuery.get(a.target) as { text: string | null } | undefined)?.text ?? null,
      clickable: this.clickable(a.target),
    }));

    // 🔴 动词助动词从 entry 层聚合。多个词条给出不同值时合成 both ——
    //    法语的 `passer` 就是这种：及物用 avoir、不及物用 être，两个都对。
    const auxes = (this.entryAuxQuery.all(row.id) as Array<{ aux: string }>)
      .map((a) => a.aux).filter(Boolean);
    const aux = auxes.length === 0 ? row.aux
      : auxes.length === 1 ? auxes[0]
        : auxes.includes('both') ? 'both' : 'both';

    const entry: FrenchEntry = {
      lang: 'fr',
      id: row.id,
      word: row.word,
      ipa: readings.find((r) => r.isPrimary)?.ipa ?? readings[0]?.ipa ?? null,
      pos: row.pos,
      isLemma: row.is_lemma === 1,
      aux,
      vgroup: row.vgroup,
      transitivity: row.transitivity,
      pronominal: row.pronominal === 1,
      pp: row.pp,
      gender: row.gender,
      plural: row.plural,
      feminine: row.feminine,
      invariable: row.invariable === 1,
      adjPos: row.adj_pos,
      government: row.government,
      comparative: row.comparative,
      level: row.level,
      senses: this.senses(row.id),
      readings,
      examples: deep ? (this.exampleQuery.all(row.word) as Array<{
        sense_id: number | null; text: string; ref: string | null; bold: string | null;
        zh: string | null; en: string | null;
      }>).map((e) => ({
        senseId: e.sense_id, text: e.text, zh: e.zh, en: e.en,
        ref: e.ref, bold: parseBold(e.bold),
      })) : [],
      collocations: (this.colsQuery.all(row.id) as Array<{
        text: string; zh: string | null;
      }>).map((c) => ({ text: c.text, zh: c.zh })),
      inflections: infl,
      // 反向变形只在 deep（词条主页）取 —— 原形内联展示不需要，取了白花时间
      forms: deep ? (this.formsQuery.all(row.id) as Array<{
        form: string; label: string | null;
      }>).map((f) => ({ form: f.form, label: f.label })) : [],
      altOf,
      relations: this.relationsOf(row.id),
      baseForms: [...new Set(infl.map((i) => i.base))],
      bases: [],
      inflNotes: infl.map((i) => i.label).filter(Boolean) as string[],
      flag: row.flag,
    };
    return entry;
  }

  getEntry(word: string): FrenchEntry | null {
    const keyword = word.trim();
    if (!keyword) return null;
    const row = this.row(keyword);
    if (!row) return null;
    const entry = this.mapEntry(row, true);

    // 解析每个原形词义（单层，供变形页内联展示各原形是什么意思）。
    // ⚠️ `deep=false` —— 原形的例句不取，那是另一页的事，取了白花时间。
    for (const bw of entry.baseForms) {
      if (bw === entry.word) continue;
      const br = this.row(bw);
      if (!br) continue;
      const bm = this.mapEntry(br, false);
      entry.bases.push({
        word: bm.word, pos: bm.pos, ipa: bm.ipa, aux: bm.aux,
        gender: bm.gender, senses: bm.senses,
      });
    }
    return entry;
  }

  close() {
    this.db.close();
  }
}
