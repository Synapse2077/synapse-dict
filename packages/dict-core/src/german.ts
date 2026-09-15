// ============================================================================
// 德语词典服务 —— 德语专属，自包含，**不引用其它语种**（不复用 es/it/fr/pt 服务）。
//
// 2026-09-04 阶段 8：从**老扁平版重写为 v3 多表版**。
//
// 🔴 为什么必须重写：`[[it-display-layer-stage8]]` 与 fr 2026-08-29 的复发 ——
//    数据层全绿、库里查得到，而 `french.ts` 里 `FROM audio` 出现 **0 次**
//    ⇒ 39 万条录音一个用户都看不见。**「落库成功」证明不了「到达用户」。**
//    de 重写前的状态：317 行只读 `dict` 的扁平列，v3 **十三张表一张都没接** ——
//    音标 1,009,462 行、例句中文 443,897 条、语义关系 1,305,005 条、
//    录音 1,013,733 条，阶段 0–7 做的东西用户一个字都看不到。
//    （回归闸的 L1 就是这笔债的计数器，接完才该变绿。）
//
// ══════ 五条 de 独有、别的语种没有的约束 ══════
//
// ① 🔴🔴 **查变形必须走 `inflection.word_id`，绝不能走 `entry`**（收尾单 C10）：
//    实测 `inflection.entry_id` 为空的有 **4,868,806 / 5,367,555 ＝ 90.7%** ——
//    比 pt 的 132,660 严重一个数量级。走 entry 会把九成变形查不出来。
//
// ② 🔴 **`alt_of` 只画在义项里，不画在词条级**：de 的 8,917 条 alt_of
//    **全部挂在义项上**（`sense_id IS NULL` 的是 **0 条**）。
//    pt 那轮 08-31 正是把义项级的话按词条级渲染，在 `banco`（银行）页顶上印出
//    「异体 → banco de dados」——**那句话本身是错的**。de 这里连词条级查询都不建，
//    从结构上杜绝。
//
// ③ 🔴 **构词（`kind='derivation'`，7,156 行）必须与变形分区渲染**（收尾单 C13）：
//    `Häuslein ← Haus 指小词` 与 `Häuser ← Haus 复数` 并排，读者会以为前者也是格形式。
//    外审两家一致点了这一条。⇒ `inflections` 与 `derivations` 是两个字段，不是一个。
//
// ④ **德语词头保留原大小写，精确匹配优先**：名词首字母大写是正字法，
//    `Die`（裸芯片）与 `die`（冠词）是两个词条。用 `COLLATE NOCASE` 会把它们混为一谈。
//    ⚠️ 而 SQLite 的 `lower()`/`upper()` **只处理 ASCII**（收尾单 C25），
//    所以大小写归一一律交给调用方，本文件不在 SQL 里做。
//
// ⑤ **地区码目前有两套**（收尾单 C31）：`audio.region` 是 `de-AT`/`de-CH`，
//    `pronunciation.region` 是 `at`/`ch`/`de-north`/`de`。**本文件原样透出，不映射** ——
//    在展示层把它们抹平就是用补丁盖住数据缺陷（`[[aim-for-perfect-not-cheap]]`），
//    修法在生成侧，已落账。
//
// ⚠️ 隐藏行一律不出现在读者面前：`example.hidden=1`、`sense_relation.hidden=1`。
//    （de 的 `sense` 表**没有** `hidden` 列 —— 别照抄 pt 的 `COALESCE(s.hidden,0)=0`，
//     那会直接 SQL 报错。）
//
// ⚠️ **`label_zh` 里已知有两族脏数据，本文件有意不打补丁**：
//    C15 变化类连写 122,356 行（`强变化弱变化混合变化阳性单数宾格`）、
//    C16 异体被标成「变形」56,332 行。两者都要重跑阶段 2b 在**生成侧**修。
//    展示层遮住它们只会让人以为已经修好了。
//
// IPA 全语种**存裸**，斜杠由展示层统一加（`[[ipa-bare-storage-convention]]`）。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';
// 词源号解析：与 en 共用一份（两门的 `sense` 都没有 `entry_id`）。
import { etymKeyOfSrcRef } from './etym.js';
// 词条级关系去重：义项下已经印过的，词条级不再印一遍（见 relations.ts 的实测数字）。
import { collocationParts, looseForms, type CollocationDetail } from './collocation.js';
import { dropDuplicatedAtSenseLevel } from './relations.js';

export type GermanSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
  /** 有值 ＝ 这条不是词头本身，是从别处反查到的；点击落到 `via.word` 的词条。 */
  via?: GermanSearchVia;
};

export type GermanRelationTarget = { word: string; clickable: boolean };
export type GermanRelationGroup = { kind: string; targets: GermanRelationTarget[] };
export type GermanAltOf = { target: string; zh: string | null; clickable: boolean };

export type GermanSense = {
  /** 词源号（维基词典的 Etymology 1/2/3…）。没有就 null。
   *  ⭐ 展示层据此断组：**词性相同且词源相同**才合并 —— 否则两个同形异源的词
   *  会被并进同一个词性组（用户 2026-09-12 从 en 的 `gore` 问出来的）。 */
  etymKey: string | null;
  id: number;
  zh: string | null;
  de: string | null;          // 德语原文释义（三语方针里的「本语言」那一支）
  en: string | null;
  pos: string | null;
  gender: string | null;
  regions: string[];
  registers: string[];
  relations: GermanRelationGroup[];
  altOf: GermanAltOf[];
};

export type GermanReading = {
  ipa: string;
  notation: string | null;
  region: string | null;      // ⑤ 原样透出：at / ch / de-north / de / null
  pos: string | null;
  primary: boolean;
  src: string | null;
};

export type GermanExample = {
  senseId: number | null;
  text: string;
  zh: string | null;
  ref: string | null;
};

export type GermanInflection = { base: string; label: string | null; clickable: boolean };
export type GermanForm = { form: string; label: string | null };
// 一条搜索结果**不是词头本身**时，说明它是从哪儿反查到的。2026-09-12。
// 目前只有一种：`collocation`（搭配 / 固定短语）。
// `src` 是那条搭配的出处（`llm:doubao` / `kaikki:*`），展示层据此标「机器生成」。
export type GermanSearchVia = { word: string; kind: 'collocation'; src: string | null };

export type GermanCollocation = {
  text: string; zh: string | null; src: string | null;
  /** 本语言的原文定义。**本门恒为 null** —— 只有 it 从 kaikki 子条目搬来的 303 条有。
   *  字段留着是为了让五门共用的 `CollocationSection` 不必写分支
   *  （`[[multilang-decoupling-essence]]`：按本质设计，不为某一门的数据现状开洞）。 */
  srcText?: string | null;
};

export type GermanAudio = {
  url: string;
  region: string | null;      // ⑤ 原样透出：de-AT / de-CH / null
  regionSrc: string | null;   // 这个地区是怎么判出来的（tag / filename）
  speaker: string | null;
};

// 多性别名词的逐性别变格束（der Band(Bandes/Bände) 卷 vs die Band(–/Bands) 乐队）。
// ⚠️ **保留这个字段**：它是德语独有的一等信息，v3 重写不该让它倒退。
export type NounVariant = { g: string; gen: string | null; pl: string | null };

export type GermanBase = {
  word: string;
  pos: string | null;
  ipa: string | null;
  gender: string | null;
  senses: GermanSense[];
};

export type GermanEntry = {
  /**
   * 我们**抽过哪些维基版**的词源正文（2026-09-14）。
   * 🔴 展示层靠它分清两件完全不同的事：
   *     这一版抽过、源头确实没写  ⇒ 照实说「源头未给出」
   *     这一版**我们还没抽**      ⇒ **闭嘴**，一个字都不说
   *    把后者说成前者，就是把「我们没做」说成「源头没有」——造假，比缺更伤权威。
   * ⚠️ it/fr/pt 的义项来自 2–4 个维基版，而 `paths.KK` 只是英文版切片 ⇒
   *    这个数组现在只有一项，等别的版也抽了才会变长。
   */
  etymologyEditions: string[];
  /**
   * 词源正文（2026-09-14）。键是义项上那把**不透明** `etymKey`，值是**源头原文全文**。
   * 🔴 端全文，不端切好的第一句：用户 2026-09-14「线上只放 sqlite，我想看全部信息时能查看」
   *    ⇒ 数据层永远给全的，「只印第一句」是展示层拿 `etymologyBrief()` 自己切的。
   * ⚠️ 键 ＝ `${edition}:${etym_no}`，`edition` 入库时就按展示层会用的前缀写好了。
   * ⚠️ 只有**已抽过的版**会出现在这里。没抽过的版查不到 ⇒ 展示层必须闭嘴，
   *    不许说「源头未给出」（那是把"我们没做"说成"源头没有"）。
   */
  etymologyTexts: Record<string, string>;
  lang: 'de';
  id: number;
  word: string;
  pos: string | null;
  isLemma: boolean;
  freqZipf: number | null;
  // 便捷字段：`readings` 里的主读音。多读音仍走 `readings`，这一条只为词头那一行。
  ipa: string | null;
  level: string | null;
  // —— 德语本质（一等字段，仍从 dict 扁平列读：它们是词条属性不是义项属性）——
  gender: string | null;        // m / f / n / mf
  genitive: string | null;      // 属格单数（des Hauses）
  plural: string | null;        // 复数（die Häuser）
  nounVariants: NounVariant[];  // 多性别名词逐性别范式束（RAM der/das、SMS die/das）
  aux: string | null;           // haben / sein
  praeteritum: string | null;
  partizip2: string | null;
  vclass: string | null;        // 强 / 弱 / 混合
  separable: boolean;
  sepPrefix: string | null;
  reflexive: boolean;
  comparative: string | null;
  superlative: string | null;
  government: string | null;
  // —— v3 多表 ——
  readings: GermanReading[];
  senses: GermanSense[];
  examples: GermanExample[];
  collocations: GermanCollocation[];
  inflections: GermanInflection[];   // ③ 这个词是谁的变形
  derivations: GermanInflection[];   // ③ 构词，**单独一区**
  forms: GermanForm[];               // 词元页反过来看：它有哪些形式
  derivedForms: GermanForm[];        // 词元页反过来看：**它派生出了谁**（C38）
  relations: GermanRelationGroup[];  // 词条级（sense_id 为空的那 763,001 条）
  audio: GermanAudio[];
  bases: GermanBase[];
};

const HEAD = `id, word, pos, is_lemma, gender, genitive, plural, noun_variants, aux,
              praeteritum, partizip2, vclass, separable, sep_prefix, reflexive,
              comparative, superlative, government, level, freq_zipf`;

type DeRow = {
  id: number; word: string; pos: string | null; is_lemma: number;
  gender: string | null; genitive: string | null; plural: string | null;
  noun_variants: string | null;
  aux: string | null; praeteritum: string | null; partizip2: string | null;
  vclass: string | null; separable: number | null; sep_prefix: string | null;
  reflexive: number | null; comparative: string | null; superlative: string | null;
  government: string | null; level: string | null; freq_zipf: number | null;
};

function groupRelations(m: Map<string, GermanRelationTarget[]>): GermanRelationGroup[] {
  return [...m.entries()].map(([kind, targets]) => ({ kind, targets }));
}

export class GermanDictService {
  readonly lang = 'de';
  readonly databasePath: string;
  private readonly db: DatabaseSync;
  private readonly q: Record<string, ReturnType<DatabaseSync['prepare']>>;
  // 🔴 短前缀的**预计算表是阶段 9 才建的**，现在库里根本没有这张表。
  //    第一版无条件 `prepare` 它 ⇒ 构造函数当场抛 `no such table: search_prefix`，
  //    整个服务起不来。**「未命中回退实时查询」这条设计本来就该覆盖「表还不存在」**
  //    —— 它和「这个前缀没算过」是同一件事，不该是两种处理。
  private readonly cached: ReturnType<DatabaseSync['prepare']> | null;

  private readonly collocDetailQuery;

  private readonly collocWordQuery;

  private readonly etymologyQuery;

  private readonly etymEditions: string[];

  constructor(databasePath: string) {

    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');

    // ══ 搭配详情页（2026-09-14）════════════════════════════════════════════
    // 🔴 `COLLATE NOCASE` 走 `idx_col_text_nocase`；**别写成 BINARY 比较**
    //    —— NOCASE 索引上做 BINARY 比较是静默全表扫（`[[query-perf-collation-traps]]`）。
    // 🔴 一条短语可能挂在多个词条下 ⇒ 这里**不加 LIMIT 1**，由调用方合并。
    this.collocDetailQuery = this.db.prepare(`
      SELECT c.text AS text, d.word AS owner,
             (SELECT text FROM collocation_gloss
               WHERE collocation_id = c.id AND lang = 'zh') AS zh,
             -- 本语言原文释义：只有 it 那 303 条有，其余四门这一列恒 null。
             -- ⚠️ 照查不误 —— 少查一列的代价是「唯一有人写过释义的那批永远看不到」，
             --    2026-09-12 已经因为服务层没 SELECT 它而漏过一次。
             (SELECT text FROM collocation_gloss
               WHERE collocation_id = c.id AND lang = 'de') AS srcText
      FROM collocation c JOIN dict d ON d.id = c.word_id
      WHERE c.text = ? COLLATE NOCASE
      ORDER BY d.word
    `);

    // 词形存在性：判「短语本身是不是词头」与「组成词点不点得动」共用这一条。
    // 🔴 **两个占位符就要传两个参数。** it 那边同形状的 `existsQuery` 声明了两个、
    //    调用处只传了一个，node:sqlite 不报错、缺的按 NULL 绑定 ⇒
    //    `word_norm = NULL` 恒不成立，归一列回退**从来没跑过**（2026-09-13 才发现）。
    this.collocWordQuery = this.db.prepare(`
      SELECT word FROM dict WHERE word = ? OR word_norm = ? LIMIT 1
    `);

    // 词源正文（2026-09-14）。`edition` 入库时就按展示层的 etymKey 前缀写好，
    // 这里直接拼键，不再从义项里推前缀（多一处判据就多一处会漂开的地方）。
    this.etymologyQuery = this.db.prepare(`
      SELECT edition, etym_no, text FROM etymology WHERE word_id = ? ORDER BY etym_no
    `);

    // 抽过哪些版 —— **构造时算一次**（六门共 4–6 行的小表，不必每开一个词条页查一遍）。
    // ⚠️ 表可能还不存在（这门还没跑 `scripts/ingest_etymology.py`）⇒ 兜到空数组，
    //    空数组的意思是「一版都没抽」，展示层对所有词源块一律闭嘴 —— 那是对的。
    this.etymEditions = (() => {
      try {
        return (this.db.prepare('SELECT DISTINCT edition FROM etymology').all() as Array<{
          edition: string }>).map((x) => x.edition);
      } catch { return []; }
    })();
    const hasPrefix = (this.db.prepare(
      "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name='search_prefix'"
    ).get() as { n: number }).n > 0;
    this.cached = hasPrefix ? this.db.prepare(`
        SELECT d.id, d.word, d.pos, d.is_lemma
          FROM search_prefix p JOIN dict d ON d.id = p.word_id
         WHERE p.prefix = ? ORDER BY p.rank LIMIT ?`) : null;

    this.q = {
      stats: this.db.prepare(`
        SELECT (SELECT COUNT(*) FROM dict)                               AS total,
               (SELECT SUM(is_lemma) FROM dict)                          AS lemmas,
               (SELECT COUNT(DISTINCT word_id) FROM sense)               AS translated,
               (SELECT COUNT(DISTINCT word_id) FROM pronunciation)       AS ipa,
               (SELECT COUNT(DISTINCT word) FROM audio)                  AS audio,
               (SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0) AS examples`),

      // ④ 精确大小写优先；查不到再退回不区分大小写。
      head: this.db.prepare(
        `SELECT ${HEAD} FROM dict WHERE word = ? ORDER BY is_lemma DESC LIMIT 1`),
      headCI: this.db.prepare(
        `SELECT ${HEAD} FROM dict WHERE word = ? COLLATE NOCASE
          ORDER BY CASE WHEN word = ? THEN 0 ELSE 1 END, is_lemma DESC LIMIT 1`),

      // 🔴 **中文摘要必须查在 LIMIT 之后**（`[[query-perf-collation-traps]]`）。
      //    pt 那轮把它写成候选行上的相关子查询，实测 5,891ms → 拆开后 28ms。
      //    根因：相关子查询从选择性最差那头入手（`lang='zh'` 有几十万行），
      //    而且对**每个候选**都跑一次，不是只对留下的 20 条。
      prefix: this.db.prepare(`
        SELECT d.id, d.word, d.pos, d.is_lemma
          FROM dict d
         WHERE d.word LIKE ? COLLATE NOCASE OR d.word_norm LIKE ? COLLATE NOCASE
         ORDER BY CASE WHEN d.word = ? THEN 0 ELSE 1 END,
                  d.is_lemma DESC, LENGTH(d.word) ASC, d.word ASC
         LIMIT ?`),


      brief: this.db.prepare(`
        SELECT g.text FROM sense s
          JOIN sense_gloss g ON g.sense_id = s.id AND g.lang = 'zh'
         WHERE s.word_id = ? ORDER BY s.rank LIMIT 1`),

      // ⚠️ de 的 `sense` **没有 hidden 列**，别照抄 pt 的过滤条件。
      senses: this.db.prepare(`
        SELECT s.id, s.pos, s.gender,
               (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' LIMIT 1) AS zh,
               -- 🔴🔴 原来是 LIMIT 1 且没有 ORDER BY —— 一条义项可以挂多条德语释义
               -- （C29 裁决的设计：德语版常把我们的一条拆得更细，Kastanie 的「树」与「果」都该挂），
               -- 而那个查询**随机取一条**。外审当场逮到：stehen「合适，好看，合身」
               -- 挂着 seq=0 nicht funktionieren（错的）和 seq=1 gut passen（对的），
               -- 页面显示的正是**错的那条**。
               -- ⇒ 按 seq 排序并全部取出（换行连接，组件逐行渲染）。
               (SELECT GROUP_CONCAT(text, char(10)) FROM
                  (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='de'
                    ORDER BY seq)) AS de,
               (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='en' LIMIT 1) AS en,
               -- 🔴 词源号（2026-09-12）。de 的 sense **没有 entry_id**（it/fr/pt 有），
               --    只能看 sense_src.src_ref 的形状：
               --        kk-en:A:noun:1:0#0        4 个冒号 + # ⇒ 倒数第二段是词源号
               --        kk-de:'n Abend:intj:0#0   3 个冒号    ⇒ 倒数第一段是 seq（见下）
               --        kk-de-adj2:A#0            1 个冒号    ⇒ 不带号，拿不到键
               --    ⚠️ de 一条 sense 可以挂**多条** sense_src（en 是 1:1），
               --       所以这里用 LIKE 先筛出带号的那一条；
               --       权威的拆解仍然交给 etymKeyOfSrcRef()，LIKE 只是把范围缩小。
               --    ⚠️ 这一段里一个反引号都不能有：整条 SQL 在 TS 模板字符串里。
               --
               -- 🔴 2026-09-15：原来这里写死 3 个冒号的一律不要，注释理由是
               --    德语版不带词源号。**那句话当天是对的，现在不是** —— 德语版的
               --    第 4 段是 seq（该 (词,pos) 在 dump 里的第几个条目），
               --    scripts/ingest_etymology.py 已按它灌了 105,266 条词源。
               --    这是同一个 5 段假设写在两处，只改 etymKeyOfSrcRef 那一处不够
               --    （端到端闸当场逮到：数据层有 kk-de:0，义项侧却只给 kk-en:0）。
               -- ⇒ LIKE 放宽到 3 个冒号，**ORDER BY 让 5 段式优先** ——
               --    现有拿得到 5 段式的义项一个不变（零回归），
               --    原本拿不到键的 135,192 个义项才落到德语版那一支。
               (SELECT src_ref FROM sense_src
                 WHERE sense_id = s.id AND src_ref LIKE '%:%:%:%#%'
                 ORDER BY (src_ref LIKE '%:%:%:%:%#%') DESC LIMIT 1) AS srcRef
          FROM sense s WHERE s.word_id = ? ORDER BY s.rank`),

      tags: this.db.prepare(
        `SELECT sense_id, kind, value FROM sense_tag WHERE sense_id IN
           (SELECT id FROM sense WHERE word_id = ?)`),

      // `is_primary` 先排；notation 目前全库只有 phonemic，留着排序键是为了以后加音位/音值两支。
      readings: this.db.prepare(`
        SELECT ipa, notation, region, pos, is_primary, src FROM pronunciation
         WHERE word_id = ?
         ORDER BY is_primary DESC,
                  CASE notation WHEN 'phonemic' THEN 0 ELSE 1 END,
                  CASE WHEN region IS NULL THEN 0 ELSE 1 END, id`),

      examples: this.db.prepare(`
        SELECT e.sense_id, e.text, e.ref,
               (SELECT text FROM example_gloss WHERE example_id=e.id AND lang='zh') AS zh
          FROM example e
         WHERE e.word = ? AND COALESCE(e.hidden,0)=0
         ORDER BY CASE WHEN e.sense_id IS NULL THEN 1 ELSE 0 END, e.id
         LIMIT 40`),


        // ══ 搭配反查（2026-09-12）════════════════════════════════════════════
      // 起因：用户在词条页上看到「搭配 / 固定短语 · habitante quiteño 基多居民」，
      // 回到搜索框把这一整条抄进去 —— **什么都没有**。
      // `search()` 只查 `dict.word` / `word_norm`，`collocation` 根本不在检索范围里。
      // **页面上印出来的字符串，读者搜一下总该有反应**（与「下位词点不动」同一族）。
      //
      // 🔴 两列都查：从页面抄下来的是带重音的原文（命中 `text`），
      //    自己敲的多半不带重音（命中 `text_norm` —— 归一口径与 `dict.word_norm`
      //    逐字一致，由 `scripts/build_collocation_search.py` 的尺子闸守着）。
      // 🔴 两条索引**都必须是 `COLLATE NOCASE`**：SQLite 默认的大小写不敏感 `LIKE`
      //    不认 BINARY 索引。第一版建成 BINARY，执行计划写着
      //    `SCAN collocation USING COVERING INDEX idx_col_norm` —— 索引名在、干的是
      //    全表扫，it 实测 234.7 ms，而这是**每敲一个字符跑一次**的路径。
    // 🔴🔴 **拆成两条单列查询，不写 `WHERE text LIKE ? OR text_norm LIKE ?`。**
    //    `OR` 那版两条索引确实都走 SEARCH，但 `MULTI-INDEX OR` **产不出有序结果**
    //    ⇒ 计划末尾挂着 `USE TEMP B-TREE FOR ORDER BY`，把命中的全部行排一遍才取 20 条。
    //    实测最坏：it `c%` **923.8 ms**、fr `p%` 285.9 ms —— 而这是每敲一键跑一次的路径。
    //    拆开之后各自沿索引顺序扫、够 20 条就停，热态 0.28～0.49 ms。
    //    ⚠️ 代价是排序从"短的在前"变成字母序；读者抄一整条短语来搜时命中唯一，看不见。
      collocSearchByText: this.db.prepare(`
        SELECT c.text AS phrase, c.src AS colSrc, c.word_id AS wordId, d.word AS owner,
               (SELECT text FROM collocation_gloss
                 WHERE collocation_id = c.id AND lang = 'zh') AS zh
          FROM collocation c JOIN dict d ON d.id = c.word_id
         WHERE c.text LIKE ? COLLATE NOCASE
         ORDER BY c.text COLLATE NOCASE
         LIMIT ?
      `),

      collocSearchByNorm: this.db.prepare(`
        SELECT c.text AS phrase, c.src AS colSrc, c.word_id AS wordId, d.word AS owner,
               (SELECT text FROM collocation_gloss
                 WHERE collocation_id = c.id AND lang = 'zh') AS zh
          FROM collocation c JOIN dict d ON d.id = c.word_id
         WHERE c.text_norm LIKE ? COLLATE NOCASE
         ORDER BY c.text_norm COLLATE NOCASE
         LIMIT ?
      `),

      colloc: this.db.prepare(`
        SELECT c.text, c.src,
               (SELECT text FROM collocation_gloss WHERE collocation_id=c.id AND lang='zh') AS zh
          FROM collocation c WHERE c.word_id = ? ORDER BY c.rank`),

      // ① 走 word_id，**不走 entry**（90.7% 的 entry_id 为空）。
      // ③ 变形与构词分开查，不是同一个列表。
      // ⚠️ 下面两条**保留 LIMIT 60**。它们喂的是「词形还原」与「构词（这个词是谁派生来的）」，
      //    不是用户 2026-09-12 点名的「词形变化」「构词（它派生出了谁）」那两处。
      // 🔴 而且不能去：实测 haben 有 **24,354 条**「是谁的变形」
      //    （德语完成时都以 haben 为助动词，每个动词的完成式都指回来），sein 4,593 条。
      //    全铺出来会当场卡死页面 —— 那反而让人**看不成**，与「先全部展示好做判断」相反。
      //    要放开得先给个数字。
      // ⚠️⚠️ **注释一律写在模板串外面**：这一段第一版插在 SQL 里，里面的反引号
      //    当场把 TS 模板字符串截断。今天第三次栽在这上面（PITFALLS 81）。
      inflOf: this.db.prepare(`
        SELECT DISTINCT i.base, i.label_zh,
               (SELECT 1 FROM dict d WHERE d.word = i.base) AS ok
          FROM inflection i WHERE i.word_id = ? AND i.kind <> 'derivation'
         ORDER BY i.base, i.label_zh LIMIT 60`),
      derivOf: this.db.prepare(`
        SELECT DISTINCT i.base, i.label_zh,
               (SELECT 1 FROM dict d WHERE d.word = i.base) AS ok
          FROM inflection i WHERE i.word_id = ? AND i.kind = 'derivation'
         ORDER BY i.base, i.label_zh LIMIT 60`),

      // 🔴 2026-09-05：这条**漏了 `kind` 过滤**（收尾单 C38）。
      //    `inflectionsOf` 与 `derivOf` 都按 `kind` 分了区（C13 那轮加的），
      //    而反方向的 `forms` 没有 ⇒ 我把 `stellen ← stehen` 改成 `derivation`
      //    之后，另外两条查询都躲开了它，**这一条照样把它印在「词形变化」里**。
      //    ⇒ 「同一个字段有几个读取路径，分区就得做几遍」——
      //      与 `[[fix-regression-and-gate]]` 第二种机制（换了读取路径）同源，
      //      只是这次是**同一次改动里的另一条路径**，不是隔天。
      // ⚠️ **2026-09-12 临时去掉 LIMIT**（用户：「数字都不要，先全部展示，不做 limit，
      //    我看了过后才好做判断」）。这是**观察态**，不是终态 ——
      //    看完之后要重新定上限，届时**有截断就必须说总数**，不然读者以为就这么多。
      //    实测上限：词形变化最多 790（`überlegen` 530、`am` 518），构词最多 40。
      // ⚠️⚠️ **注释一律写在模板串外面。** 这一段第一版插在 SQL 里，`//` SQLite 不认，
      //    `tsc` 全绿、一跑就 `SQL logic error`。今天第三次栽在这上面（PITFALLS 81）。
      forms: this.db.prepare(`
        SELECT DISTINCT d.word AS form, i.label_zh AS label
          FROM inflection i JOIN dict d ON d.id = i.word_id
         WHERE i.base_id = ? AND i.kind <> 'derivation'
         ORDER BY i.label_zh, d.word`),
      // 反方向的构词：**谁是这个词派生出来的**（`stehen` → `stellen 使役派生`）。
      // 这是真信息，不该被上面那条一并挡掉 —— 它该去「构词」那一区。
      derivedForms: this.db.prepare(`
        SELECT DISTINCT d.word AS form, i.label_zh AS label
          FROM inflection i JOIN dict d ON d.id = i.word_id
         WHERE i.base_id = ? AND i.kind = 'derivation'
         ORDER BY i.label_zh, d.word`),

      // ⚠️ 词条级只取**没有义项归属**的（763,001 条）。有归属的走 `relBySense`，
      //    否则同一条会在词条级和义项级各印一遍。
      rel: this.db.prepare(`
        SELECT kind, target,
               (SELECT 1 FROM dict d WHERE d.word = sense_relation.target) AS ok
          FROM sense_relation
         WHERE word_id = ? AND sense_id IS NULL AND COALESCE(hidden,0) = 0
         LIMIT 200`),

      relBySense: this.db.prepare(`
        SELECT r.sense_id, r.kind, r.target,
               (SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
          FROM sense_relation r
         WHERE r.sense_id IN (SELECT id FROM sense WHERE word_id = ?)
           AND r.kind <> 'alt_of' AND COALESCE(r.hidden,0) = 0`),

      // ② **只有义项级**。de 的 alt_of 一条都不挂在词条上，所以不建词条级查询。
      altOfBySense: this.db.prepare(`
        SELECT r.sense_id, r.target,
               (SELECT g.text FROM sense s
                  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh'
                 WHERE s.word_id = (SELECT id FROM dict WHERE word = r.target)
                 ORDER BY s.rank LIMIT 1) AS zh,
               (SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
          FROM sense_relation r
         WHERE r.sense_id IN (SELECT id FROM sense WHERE word_id = ?)
           AND r.kind = 'alt_of' AND COALESCE(r.hidden,0) = 0`),

      audio: this.db.prepare(`
        SELECT COALESCE(url_ogg, url_mp3, url_wav, url_other) AS url,
               region, region_src, speaker
          FROM audio WHERE word = ?
         ORDER BY CASE WHEN region IS NULL THEN 0 ELSE 1 END, id
         LIMIT 8`),
    };
  }

  getStats() {
    return this.q.stats.get() as Record<string, number>;
  }

  search(query: string, limit = 20): GermanSearchItem[] {
    const kw = query.trim();
    if (!kw) return [];
    const like = `${kw}%`;
    type Row = { id: number; word: string; pos: string | null };
    let rows = (this.cached?.all(kw, limit) ?? []) as Row[];
    if (rows.length === 0) rows = this.q.prefix.all(like, like, kw, limit) as Row[];
    const items: GermanSearchItem[] = rows.map((r) => ({
      id: r.id, word: r.word, pos: r.pos,
      brief: (this.q.brief.get(r.id) as { text: string } | undefined)?.text ?? null,
    }));
    // 词头没填满时，用剩下的名额反查搭配。
    // 🔴 **词头永远优先，搭配只补位** —— `quiteño` 既是词头又出现在一堆搭配里，
    //    让搭配挤掉词头就是把主词条藏起来。
    // 🔴 落点是**拥有这条搭配的词条**（`via.word`），不是短语本身（短语不是词头，
    //    拿它去 `getEntry` 一定查不到）。展示层据 `via` 渲染来源标记与跳转目标。
    if (items.length < limit) {
      const seen = new Set(items.map((x) => x.word.toLowerCase()));
      type ColHit = { phrase: string; colSrc: string | null; wordId: number;
        owner: string; zh: string | null };
      const hits = [
        ...(this.q.collocSearchByText.all(like, limit) as ColHit[]),
        ...(this.q.collocSearchByNorm.all(like, limit) as ColHit[]),
      ];
      for (const c of hits) {
        if (items.length >= limit) break;
        const k = c.phrase.toLowerCase();
        if (seen.has(k)) continue;
        seen.add(k);
        items.push({
          id: c.wordId, word: c.phrase, pos: null, brief: c.zh,
          via: { word: c.owner, kind: 'collocation', src: c.colSrc },
        });
      }
    }
    return items;
  }

  private sensesOf(wordId: number): GermanSense[] {
    const rows = this.q.senses.all(wordId) as Array<{
      id: number; pos: string | null; gender: string | null;
      zh: string | null; de: string | null; en: string | null;
    }>;
    const tagRows = this.q.tags.all(wordId) as Array<{
      sense_id: number; kind: string; value: string;
    }>;
    const tagBy = new Map<number, { regions: string[]; registers: string[] }>();
    for (const t of tagRows) {
      const e = tagBy.get(t.sense_id) ?? { regions: [], registers: [] };
      if (t.kind === 'region') e.regions.push(t.value);
      else if (t.kind === 'register') e.registers.push(t.value);
      tagBy.set(t.sense_id, e);
    }
    const relBy = new Map<number, Map<string, GermanRelationTarget[]>>();
    for (const r of this.q.relBySense.all(wordId) as Array<{
      sense_id: number; kind: string; target: string; ok: number | null;
    }>) {
      const m = relBy.get(r.sense_id) ?? new Map<string, GermanRelationTarget[]>();
      const arr = m.get(r.kind) ?? [];
      arr.push({ word: r.target, clickable: !!r.ok });
      m.set(r.kind, arr);
      relBy.set(r.sense_id, m);
    }
    const altBy = new Map<number, GermanAltOf[]>();
    for (const r of this.q.altOfBySense.all(wordId) as Array<{
      sense_id: number; target: string; zh: string | null; ok: number | null;
    }>) {
      const arr = altBy.get(r.sense_id) ?? [];
      arr.push({ target: r.target, zh: r.zh, clickable: !!r.ok });
      altBy.set(r.sense_id, arr);
    }
    return rows.map((r) => ({
      id: r.id, zh: r.zh, de: r.de, en: r.en, pos: r.pos, gender: r.gender,
      etymKey: etymKeyOfSrcRef((r as { srcRef?: string | null }).srcRef),
      ...(tagBy.get(r.id) ?? { regions: [], registers: [] }),
      relations: groupRelations(relBy.get(r.id) ?? new Map()),
      altOf: altBy.get(r.id) ?? [],
    }));
  }

  private mapEntry(row: DeRow): GermanEntry {
    const inf = (rows: unknown): GermanInflection[] =>
      (rows as Array<{ base: string; label_zh: string | null; ok: number | null }>)
        .map((x) => ({ base: x.base, label: x.label_zh, clickable: !!x.ok }));
    const readings = (this.q.readings.all(row.id) as Array<{
      ipa: string; notation: string | null; region: string | null;
      pos: string | null; is_primary: number | null; src: string | null;
    }>).map((r) => ({
      ipa: r.ipa, notation: r.notation, region: r.region,
      pos: r.pos, primary: !!r.is_primary, src: r.src,
    }));
    let nounVariants: NounVariant[] = [];
    if (row.noun_variants) {
      // 坏 JSON 不该让整个词条页崩掉 —— 宁可少一个范式束，也不给读者一片白。
      try { nounVariants = JSON.parse(row.noun_variants) as NounVariant[]; } catch { /* 忽略 */ }
    }
    // 🔴 `sense_id IS NULL` 这个过滤**不够**：同一条 (词, 类型, 目标) 在库里可以有两行
    //    （一行带归属、一行不带），两级各取一行就印两遍。**de 是六门里最严重的一门**：
    //    24,149 组，`Haus` 页上「Hausaltar」实测出现 2 次。见 relations.ts。
    const relAtSense = this.q.relBySense.all(row.id) as Array<{
      kind: string; target: string }>;
    const relMap = new Map<string, GermanRelationTarget[]>();
    for (const r of dropDuplicatedAtSenseLevel(this.q.rel.all(row.id) as Array<{
      kind: string; target: string; ok: number | null;
    }>, relAtSense)) {
      const arr = relMap.get(r.kind) ?? [];
      arr.push({ word: r.target, clickable: !!r.ok });
      relMap.set(r.kind, arr);
    }
    return {
      lang: 'de',
      etymologyEditions: this.etymEditions,
      // 键 ＝ `${edition}:${etym_no}`，与 `etymKeyOfEntry()` 拼出来的那把逐字一致。
      etymologyTexts: Object.fromEntries(
        (this.etymologyQuery.all(row.id) as Array<{
          edition: string; etym_no: string; text: string }>)
          .map((x) => [`${x.edition}:${x.etym_no}`, x.text])),
      id: row.id,
      word: row.word,
      pos: row.pos,
      isLemma: !!row.is_lemma,
      freqZipf: row.freq_zipf,
      level: row.level,
      gender: row.gender,
      genitive: row.genitive,
      plural: row.plural,
      aux: row.aux,
      praeteritum: row.praeteritum,
      partizip2: row.partizip2,
      vclass: row.vclass,
      separable: !!row.separable,
      sepPrefix: row.sep_prefix,
      reflexive: !!row.reflexive,
      comparative: row.comparative,
      superlative: row.superlative,
      government: row.government,
      ipa: readings[0]?.ipa ?? null,
      nounVariants,
      readings,
      senses: this.sensesOf(row.id),
      examples: (this.q.examples.all(row.word) as Array<{
        sense_id: number | null; text: string; ref: string | null; zh: string | null;
      }>).map((e) => ({ senseId: e.sense_id, text: e.text, zh: e.zh, ref: e.ref })),
      collocations: this.q.colloc.all(row.id) as GermanCollocation[],
      inflections: inf(this.q.inflOf.all(row.id)),
      derivations: inf(this.q.derivOf.all(row.id)),
      forms: this.q.forms.all(row.id) as GermanForm[],
      derivedForms: this.q.derivedForms.all(row.id) as GermanForm[],
      relations: groupRelations(relMap),
      audio: (this.q.audio.all(row.word) as Array<{
        url: string; region: string | null; region_src: string | null; speaker: string | null;
      }>).map((a) => ({
        url: a.url, region: a.region, regionSrc: a.region_src, speaker: a.speaker,
      })),
      bases: [],
    };
  }

  getEntry(word: string): GermanEntry | null {
    const kw = word.trim();
    if (!kw) return null;
    // ④ 精确大小写优先（`Die` 裸芯片 ≠ `die` 冠词）
    const row = (this.q.head.get(kw) ?? this.q.headCI.get(kw, kw)) as DeRow | undefined;
    if (!row) return null;
    const entry = this.mapEntry(row);

    // 变形页：把它指向的原形内联进来，读者不必再点一次。
    //
    // 🔴🔴 **只在这一页自己没有义项时才内联** —— 判据按含义：
    //    「这一页有没有自己的内容」。第一版对所有词条都内联，渲染出来当场看见：
    //    `Haus`（房屋，4 条义项、词元）页上内联出 **`Hau` 猛击** ——
    //    因为 `Haus` 同时是 `Hau` 的单数属格，**语言学上没错**，
    //    但把「猛击」摆进「房屋」的页面里就是噪声。
    //    ⇒ 有自己的义项 = 有自己的内容 = 不需要借别人的。
    //    （`[[it-display-layer-stage8]]`：库里查不出异常，渲染出来一眼看见。）
    if (entry.senses.length > 0) return entry;

    // 🔴 **异体链要多跟一跳**：2d 补的那批是「异体 → 异体 → 词元」
    //    （`Fussschmerze → Fußschmerze → Fußschmerz`）。只跟一跳会内联出一页空白 ——
    //    第一版实测 `Fußschmerze` 自己也没有义项，内联结果是 `undefined`。
    const seen = new Set<string>([entry.word]);
    const push = (w: string, depth: number): boolean => {
      if (seen.has(w) || depth > 2) return false;
      seen.add(w);
      const br = this.q.head.get(w) as DeRow | undefined;
      if (!br) return false;
      const senses = this.sensesOf(br.id);
      if (senses.length === 0) {
        // 这一跳也是空的：继续往它的原形走，别把空页摆给读者。
        for (const nx of this.q.inflOf.all(br.id) as Array<{ base: string; ok: number | null }>) {
          if (nx.ok && push(nx.base, depth + 1)) return true;
        }
        return false;
      }
      entry.bases.push({
        word: br.word, pos: br.pos, gender: br.gender,
        ipa: (this.q.readings.all(br.id) as Array<{ ipa: string }>)[0]?.ipa ?? null,
        senses,
      });
      return true;
    };
    for (const i of entry.inflections) {
      if (!i.clickable) continue;
      push(i.base, 0);
      if (entry.bases.length >= 3) break;
    }
    return entry;
  }

  /**
   * 搭配详情页（2026-09-14）。用户：「搭配我希望也有详情页，请按照现有格式配置」。
   *
   * 在此之前搭配只是词条页上一行死文字：2026-09-12 补了反查**搜得到**，但点不开，
   * 而搜索结果那一行点下去跳的是**所属词条**（`item.via.word`），不是短语自己。
   *
   * 🔴 `text` 用 `COLLATE NOCASE` 找、然后**一律改用库里那一版的写法**往下走：
   *    读者可能从地址栏敲进来大小写不同的一版，后面 `owners` / `parts` / 词头判断
   *    全是精确匹配，拿读者那一版去查会零零散散地落空。
   * 🔴 同一条短语可能挂在**多个词条**下（本门实测有几百条），所以 `owners` 是数组
   *    不是单值 —— 取第一条的老写法会让读者以为这个短语只跟一个词有关。
   */
  getCollocation(text: string): CollocationDetail | null {
    const rows = this.collocDetailQuery.all(text) as Array<{
      text: string; owner: string; zh: string | null; srcText: string | null;
    }>;
    if (rows.length === 0) return null;
    const canonical = rows[0].text;
    // 词头判断：短语本身就是词条时，前端直接跳真词条页（用户 2026-09-14 定）。
    const head = this.collocWordQuery.get(canonical, canonical) as { word: string } | undefined;
    return {
      lang: 'de',
      text: canonical,
      headword: head ? head.word : null,
      // 多条行里挑第一条有值的：同一短语挂在两个词条下时，两行的译文是同一份，
      // 但**不保证两边都填了**（译文是按 collocation.id 落的，不是按 text）。
      zh: rows.map((r) => r.zh).find((x) => x) ?? null,
      srcText: rows.map((r) => r.srcText).find((x) => x) ?? null,
      owners: [...new Set(rows.map((r) => r.owner))],
      // 🔴 逐个候选写法去查，**第一个查得到的就用它**（`looseForms`：先原样、
      //    再剥首尾标点）。查得到的一律回填**库里那一版的写法** ——
      //    源头短语里 `Chile.` 带句点，词条是 `Chile`，链接文字得是后者。
      parts: collocationParts(canonical).map((w) => {
        for (const cand of looseForms(w)) {
          const hit = this.collocWordQuery.get(cand, cand) as { word: string } | undefined;
          if (hit) return { word: hit.word, clickable: true };
        }
        return { word: w, clickable: false };
      }),
    };
  }

  close() {
    this.db.close();
  }
}
