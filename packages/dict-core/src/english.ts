// ============================================================================
// 英语词典服务 —— 英语专属，自包含，**不引用其它语种**。
//
// 2026-09-08 阶段 8：**六门里唯一从零新建的**（其余五门是从老扁平版重写）。
//
// 🔴 为什么必须有这个文件：阶段 0 把老表 `stardict` 改名成 `legacy_dict` 之后，
//    `index.ts` 的通用 `DictionaryService` 读的那套扁平列（`definition`/`translation`）
//    整个不存在了 —— 探活当场报「库里没有 stardict 表」，**en 从可用语种里被摘掉**，
//    而且是 `index.ts` 那段注释里明写警告过的同一种故障。修探活不能先于建服务：
//    先修探活会让它通过、然后在第一个请求上 500 ——**把可见的宕机变成隐蔽的**。
//
// 🔴 `[[it-display-layer-stage8]]`：**「落库成功」证明不了「到达用户」。**
//    fr 那次 `french.ts` 里 `FROM audio` 出现 0 次，39 万条录音一个用户看不见。
//    本文件接的表要与库里非空的表逐一对上（回归闸 L1 查这件事）。
//
// ══════ 六条 en 独有、**与 de/pt/fr 都不同**的约束（写之前逐条核过库） ══════
//
// ① ⭐ **读者看到的词有三类，其中六成只有 ECDICT 释义** —— 五门都没有这个形态：
//      有 v3 义项      1,385,196  34.5%
//      仅 ECDICT·出版  2,419,312  **60.3%**   ← `legacy_gloss.published=1`
//      全库            4,012,702
//    ⇒ `getEntry` **必须两条腿走路**：没有 v3 义项时回落到 `legacy_gloss`。
//    🔴🔴 **2026-09-09 起这条变了**：`build_legacy_sense.py` 把老词典层那 242 万词的
//      词条级释义**拆成了义项级**（`sense_src.src='ecdict'`，2,766,843 条），
//      于是它们和 kaikki 那批**走同一条渲染路径**了。
//      ⇒ 「`senses` 空 + `legacy` 非空」不再是六成词的常态，只剩
//        3,899 条（释义里混着别的词典条目、有意不结构化）+ 少量残渣。
//      `legacy` 兜底**保留**，判据是「没有任何一条义项带中文」而不是「没有义项」。
//
// ② 🔴 **变形走 `entry_id` 是安全的** —— 实测 `inflection.entry_id` 非空
//    **535,784/535,784 = 100.0%**。de 那边是 9.3%（收尾单 C10 要求必须走 word_id），
//    **判据不能照抄**：每门语言这个数不一样，抄错一边就查不出九成变形。
//    本文件仍按 `word_id` 查（同样正确且更直接），把这条事实记在这里备查。
//
// ③ 🔴 **`sense` 表没有 `hidden` 列** —— 别照抄 pt 的 `COALESCE(s.hidden,0)=0`，
//    那会直接 SQL 报错。`hidden` 只在 `example` 和 `sense_relation` 上。
//
// ④ 🔴 **`alt_of` 全部挂在义项级**（义项级 174,449 ／ 词条级 **0**）——
//    与 de 相同，与 pt 相反。pt 那轮把义项级的话按词条级渲染，在 `banco`（银行）
//    页顶印出「异体 → banco de dados」，**那句话本身是错的**。
//    ⇒ 本文件**不建词条级 alt_of 查询**，从结构上杜绝。
//
// ⑤ 🔴 **`example_gloss` 现在是空的**（阶段 5e 还没跑）——
//    例句**没有中文也必须显示**。用 `LEFT JOIN`，绝不能拿中文当过滤条件，
//    否则 75.8 万条例句一条都出不来，而且数据层看不出任何异常。
//
// ⑥ ⭐ **ECDICT 尺子是 en 独有的产品价值**：`collins`/`oxford`/`exam_tag`/`bnc`/
//    `freq_rank` 五门都没有。考纲标签（zk/gk/cet4/cet6/ky/toefl/ielts/gre）直接透出，
//    不在这里翻译成中文 —— 映射表的家在 `packages/dict-labels`
//    （`[[dict-labels-package]]`：`App.tsx` 里不许再新增）。
//
// ⚠️ **大小写**：`Lead`(专名) 与 `lead`(铅) 是两个词条（阶段 1a 实测 NOCASE 会多挂
//    12,834 条污染）。⇒ **精确匹配优先**，模糊匹配只作兜底且不合并两者。
//    SQLite 的 `lower()` 只处理 ASCII —— en 全是 ASCII 所以这个坑对 en 不咬，
//    但别因此把这个写法抄给别人。
//
// ⚠️ **隐藏行一律不出现在读者面前**：`example.hidden=1`、`sense_relation.hidden=1`
//    （`derived` 699,687 ／ `related` 313,989 ／ `abbreviation` 80 是有意隐藏的，
//     数据在库里、展示层默认不显示 —— 显不显示是阶段 8 的决定，不是数据层的）。
//
// IPA 全语种**存裸**，斜杠由展示层统一加（`[[ipa-bare-storage-convention]]`）。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';

export type EnglishSearchItem = {
  id: number;
  word: string;
  pos: string | null;
  brief: string | null;
  /** 该词形有没有 v3 义项；false = 只有 ECDICT 释义（六成的词是这种） */
  v3: boolean;
};

export type EnglishRelationTarget = { word: string; clickable: boolean };
export type EnglishRelationGroup = { kind: string; targets: EnglishRelationTarget[] };
export type EnglishAltOf = { target: string; clickable: boolean };

export type EnglishExample = {
  text: string;
  /** 中文译文；阶段 5e 之前**一律为 null，但例句照样要显示** */
  zh: string | null;
  /** 文献出处（书证）。en 有 63.4 万条带出处的引文，五门里比例最高 */
  ref: string | null;
  /** 源头给的现代英语转写（古英语/方言引文才有） */
  modern: string | null;
};

export type EnglishSense = {
  id: number;
  rank: number;
  pos: string | null;
  en: string | null;
  zh: string | null;
  /** 中文的来源：model:def ／ template:form_of ／ ecdict-core ／ ecdict。
   *  展示层按它决定 `topic` 标签显不显示（两个来源的取值形状完全不同）。 */
  src: string | null;
  /** 语法/地区/语域/用法/学科 五桶标签，原样透出 */
  tags: { kind: string; value: string }[];
  relations: EnglishRelationGroup[];
  altOf: EnglishAltOf[];
  examples: EnglishExample[];
};

export type EnglishReading = {
  ipa: string;
  notation: string;
  region: string | null;
  /** en-edition = kaikki ／ en-selfgen = 本项目 2026-07 自产的 11.6 万条 */
  src: string;
};

export type EnglishAudio = {
  file: string;
  url: string | null;
  region: string | null;
  /** tag ｜ filename ｜ speaker —— 判不出时 region 与本字段同为 null，不硬填 */
  regionSrc: string | null;
  speaker: string | null;
};

/** 这个词的一个变形（在原形页上显示）：`cat` → `cats` 复数 */
export type EnglishForm = { form: string; label: string | null; kind: string };
/** 这个词是谁的变形（在变形页上显示）：`cats` → `cat` 复数 */
export type EnglishFormOf = { base: string; label: string | null; kind: string; clickable: boolean };

/** ECDICT 尺子。五门都没有 —— 考纲标签是 en 最大的产品差异点 */
export type EnglishRulers = {
  collins: number | null;
  oxford: number | null;
  examTag: string | null;
  bnc: number | null;
  freqRank: number | null;
  freqZipf: number | null;
};

export type EnglishEntry = {
  /** App.tsx 按这个字段分派视图；缺了它前端会落到西语视图上 */
  lang: 'en';
  id: number;
  word: string;
  pos: string | null;
  isLemma: boolean;
  rulers: EnglishRulers;
  readings: EnglishReading[];
  audio: EnglishAudio[];
  senses: EnglishSense[];
  /** 这个词有哪些变形（查 `inflection.base`）*/
  forms: EnglishForm[];
  /** 这个词是谁的变形（查 `inflection.word_id`）；`saw` 两者都非空是**合法**的 */
  formOf: EnglishFormOf[];
  /** 词条级关系（不属于任何单条义项）—— 12.1% 的可见关系在这里 */
  relations: EnglishRelationGroup[];
  /**
   * ECDICT 词条级释义。**六成的词只有这个**（见头部约束①）。
   * `senses` 为空而本字段非空是**正常形态**，不是缺陷。
   */
  legacy: { text: string; qual: string } | null;
};

const HEAD = `id, word, pos, is_lemma, collins, oxford, exam_tag, bnc, freq_rank, freq_zipf`;

type EnRow = {
  id: number; word: string; pos: string | null; is_lemma: number;
  collins: number | null; oxford: number | null; exam_tag: string | null;
  bnc: number | null; freq_rank: number | null; freq_zipf: number | null;
};

export class EnglishDictService {
  readonly lang = 'en';
  private readonly db: DatabaseSync;
  private readonly q: Record<string, ReturnType<DatabaseSync['prepare']>>;
  /** 阶段 9 预计算缓存；表不存在时为 null ⇒ 全部走实时查询 */
  private readonly cached: ReturnType<DatabaseSync['prepare']> | null;

  constructor(databasePath: string) {
    this.db = new DatabaseSync(databasePath, { readOnly: true });
    this.q = {
      stats: this.db.prepare(
        `SELECT (SELECT COUNT(*) FROM dict) AS words,
                (SELECT COUNT(*) FROM sense) AS senses,
                (SELECT COUNT(*) FROM example) AS examples,
                (SELECT COUNT(*) FROM pronunciation) AS readings,
                (SELECT COUNT(*) FROM audio) AS audio`),
      // 🔴 精确匹配优先：`Lead` 与 `lead` 是两个词条，不合并
      exact: this.db.prepare(`SELECT ${HEAD} FROM dict WHERE word = ?`),
      // ⭐ 阶段 9 的预计算缓存（1–3 字符前缀）。**未命中 = 正确回退到实时查询，不是错误** ——
      //    表不存在也按未命中处理，所以 `cached` 是可空的。
      //    实测：`a` 105 ms → 缓存命中后 <1 ms；4 字符起实时查询本来就在 1 ms 内。
      // 前缀搜索：常用词优先（ECDICT 词频升序，NULL 排最后），再按词形长度
      prefix: this.db.prepare(
        `SELECT id, word, pos,
                EXISTS(SELECT 1 FROM sense s WHERE s.word_id = dict.id) AS v3
           FROM dict WHERE word LIKE ? ESCAPE '\\'
          ORDER BY (word = ?) DESC,
                   CASE WHEN freq_rank IS NULL THEN 1 ELSE 0 END,
                   freq_rank ASC, length(word) ASC, word ASC
          LIMIT ?`),
      // 摘要：v3 中文优先，没有就用 ECDICT 词条级中文（六成的词走这条）
      briefZh: this.db.prepare(
        `SELECT g.text FROM sense s JOIN sense_gloss g
                ON g.sense_id = s.id AND g.lang = 'zh'
          WHERE s.word_id = ? ORDER BY s.rank LIMIT 1`),
      briefLegacy: this.db.prepare(
        `SELECT text FROM legacy_gloss WHERE word_id = ? AND published = 1`),
      senses: this.db.prepare(
        // 🔴 `src` 必须带出去：`topic` 桶的取值**两个来源形状完全不同** ——
        //    kaikki 是上千种英文 slug（`natural-sciences`），有意不显示；
        //    老词典层是中文短码（`计`／`医`／`化`），**自解释、正是读者要的**。
        //    ⇒ 让视图按来源决定显不显示，而不是拿"是不是中文"当判据。
        `SELECT s.id, s.rank, s.pos,
                (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='en'
                  ORDER BY seq LIMIT 1) AS en,
                (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='zh'
                  ORDER BY seq LIMIT 1) AS zh,
                (SELECT src FROM sense_gloss WHERE sense_id = s.id AND lang='zh'
                  ORDER BY seq LIMIT 1) AS src
           FROM sense s WHERE s.word_id = ? ORDER BY s.rank`),
      tags: this.db.prepare(
        `SELECT t.sense_id, t.kind, t.value FROM sense_tag t
           JOIN sense s ON s.id = t.sense_id WHERE s.word_id = ?`),
      // ⚠️ hidden=1 的（derived/related）不给读者看
      relBySense: this.db.prepare(
        `SELECT r.sense_id, r.kind, r.target,
                EXISTS(SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
           FROM sense_relation r JOIN sense s ON s.id = r.sense_id
          WHERE s.word_id = ? AND r.kind <> 'alt_of' AND r.hidden = 0`),
      // 🔴 **词条级关系也要出** —— 实测 109,195 条可见关系（**12.1%**）挂在词条级
      //    （`sense_id IS NULL`），只渲染义项级会让它们一条都到不了读者：
      //    `run → antonym: rise ／ hypernym: move ／ hyponym: bolt, flee` 都是正经内容。
      //    ⚠️ 这与下面 alt_of 那条**不冲突**：alt_of 在 en 是义项级 174,449、词条级 0，
      //       所以那一路有意不建；关系不是。**逐条量过再定，不按印象统一处理。**
      relByEntry: this.db.prepare(
        `SELECT r.kind, r.target,
                EXISTS(SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
           FROM sense_relation r
          WHERE r.word_id = ? AND r.sense_id IS NULL
            AND r.kind <> 'alt_of' AND r.hidden = 0`),
      // ④ alt_of 只在义项级 —— 不建词条级查询
      altBySense: this.db.prepare(
        `SELECT r.sense_id, r.target,
                EXISTS(SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
           FROM sense_relation r JOIN sense s ON s.id = r.sense_id
          WHERE s.word_id = ? AND r.kind = 'alt_of' AND r.hidden = 0`),
      // ⑤ LEFT JOIN —— 中文还没买，例句照样要出来
      examples: this.db.prepare(
        `SELECT e.sense_id, e.text, e.ref, e.src_translation AS modern,
                (SELECT text FROM example_gloss WHERE example_id = e.id AND lang='zh') AS zh
           FROM example e JOIN sense s ON s.id = e.sense_id
          WHERE s.word_id = ? AND e.hidden = 0
          ORDER BY e.id`),
      // 🔴 **必须 DISTINCT**：`pronunciation` 是**按 entry 存的**，`cat` 有十几个
      //    entry（adj/noun/verb × 多个词源），同一个读音会重复十几遍。
      //    实测 `cat` 56 条 → 按 (ipa,notation,region) 去重后 **9 条**。
      //    ⚠️ 数据没错（每个 entry 确实有那个读音），**错的是照搬 de 的查询**：
      //       de 的 `pronunciation` 也带 entry_id，但德语一词多 entry 的情况少得多，
      //       它没去重也看不出来。判据要按**这门语言的形状**定。
      //    ⇒ `pos` 有意不出现在去重键里：同一读音跨词性重复，读者不需要看十遍。
      //    ⚠️ `src` **不能进 DISTINCT** —— 同一读音在 `en-edition` 和 `en-selfgen`
      //       各有一行，带上 src 又变成两行（`cat` 的 `/ˈkæt/·uk` 出现两次）。
      //       读者不需要看来源；来源在库里，回归闸查得到。
      readings: this.db.prepare(
        `SELECT ipa, notation, region, MIN(src) AS src FROM pronunciation
          WHERE word_id = ? GROUP BY ipa, notation, region
          ORDER BY (region IS NULL), region, notation, ipa`),
      audio: this.db.prepare(
        `SELECT file, COALESCE(url_ogg, url_mp3, url_wav, url_other) AS url,
                region, region_src, speaker
           FROM audio WHERE word = ? ORDER BY (region IS NULL), region, id`),
      // 🔴🔴 **`inflection` 的方向：`word_id` 是变形本身，`base` 是原形。**
      //    我第一版查 `WHERE word_id = ?`，问的是「这个词是谁的变形」——
      //    在 `cat` 页上返回 **0 条**，而 `cat` 明明有 cats / catted / catting。
      //    渲染出来才看见（`[[it-display-layer-stage8]]`：数据全绿≠到达用户）。
      //    ⇒ **两个方向都要，是两件事**：
      //      `forms`  = 这个词有哪些变形（查 base）—— 在 `cat` 页上显示
      //      `formOf` = 这个词是谁的变形（查 word_id）—— 在 `cats` 页上显示
      //    ⚠️ 查 **`base_id`（整数外键）不查 `base`（文本）**：表上本来就有
      //       `idx_infl_base ON inflection(base_id)`。我第一版按文本查，撞上
      //       **全表扫 53.5 万行 ＝ 单个词条页 197 ms**，然后又给 `base` 建了一个
      //       冗余索引 —— **加索引之前先看表上有什么**
      //       （`[[refactor-mindset-code-quality]]`）。实测 `base_id` 99.8% 非空、
      //       与 `base` 文本零不一致；空的那 960 条是阶段 2 的悬空 base，
      //       本来就查不到对应词条。整数比较还顺带避开了文本 collation 的坑。
      forms: this.db.prepare(
        `SELECT DISTINCT d.word AS form, i.label_zh AS label, i.kind
           FROM inflection i JOIN dict d ON d.id = i.word_id
          WHERE i.base_id = ? ORDER BY i.id`),
      formOf: this.db.prepare(
        `SELECT i.base, i.label_zh AS label, i.kind,
                EXISTS(SELECT 1 FROM dict d WHERE d.word = i.base) AS ok
           FROM inflection i WHERE i.word_id = ? ORDER BY i.id`),
      legacy: this.db.prepare(
        `SELECT text, qual FROM legacy_gloss WHERE word_id = ? AND published = 1`),
    };
    // 🔴 缓存表可能不存在（阶段 9 未跑 / 旧库）⇒ 准备语句要容错，**不是致命错**
    let cached: ReturnType<DatabaseSync['prepare']> | null = null;
    try {
      cached = this.db.prepare(
        `SELECT d.id, d.word, d.pos,
                EXISTS(SELECT 1 FROM sense s WHERE s.word_id = d.id) AS v3
           FROM search_prefix p JOIN dict d ON d.id = p.word_id
          WHERE p.prefix = ? ORDER BY p.rank LIMIT ?`);
    } catch { cached = null; }
    this.cached = cached;
  }

  getStats() {
    return this.q.stats.get() as Record<string, number>;
  }

  search(query: string, limit = 20): EnglishSearchItem[] {
    const kw = query.trim();
    if (!kw) return [];
    type Row = { id: number; word: string; pos: string | null; v3: number };
    let rows = (this.cached?.all(kw, limit) ?? []) as Row[];
    if (rows.length === 0) {
      const esc = kw.replace(/[\\%_]/g, (m) => `\\${m}`);
      rows = this.q.prefix.all(`${esc}%`, kw, limit) as Row[];
    }
    return rows.map((r) => ({
      id: r.id,
      word: r.word,
      pos: r.pos,
      v3: !!r.v3,
      brief: this.briefOf(r.id),
    }));
  }

  /** 摘要：v3 中文 → ECDICT 中文。**没有 v3 义项不等于没有内容**（约束①） */
  private briefOf(wordId: number): string | null {
    const a = this.q.briefZh.get(wordId) as { text: string } | undefined;
    if (a?.text) return a.text;
    const b = this.q.briefLegacy.get(wordId) as { text: string } | undefined;
    return b?.text ? b.text.split('\n')[0] : null;
  }

  private sensesOf(wordId: number): EnglishSense[] {
    const rows = this.q.senses.all(wordId) as Array<{
      id: number; rank: number; pos: string | null; en: string | null; zh: string | null;
      src: string | null;
    }>;
    if (rows.length === 0) return [];
    const tagBy = new Map<number, { kind: string; value: string }[]>();
    for (const t of this.q.tags.all(wordId) as Array<{
      sense_id: number; kind: string; value: string }>) {
      const arr = tagBy.get(t.sense_id) ?? [];
      arr.push({ kind: t.kind, value: t.value });
      tagBy.set(t.sense_id, arr);
    }
    const relBy = new Map<number, Map<string, EnglishRelationTarget[]>>();
    for (const r of this.q.relBySense.all(wordId) as Array<{
      sense_id: number; kind: string; target: string; ok: number }>) {
      const m = relBy.get(r.sense_id) ?? new Map<string, EnglishRelationTarget[]>();
      const arr = m.get(r.kind) ?? [];
      arr.push({ word: r.target, clickable: !!r.ok });
      m.set(r.kind, arr);
      relBy.set(r.sense_id, m);
    }
    const altBy = new Map<number, EnglishAltOf[]>();
    for (const r of this.q.altBySense.all(wordId) as Array<{
      sense_id: number; target: string; ok: number }>) {
      const arr = altBy.get(r.sense_id) ?? [];
      arr.push({ target: r.target, clickable: !!r.ok });
      altBy.set(r.sense_id, arr);
    }
    const exBy = new Map<number, EnglishExample[]>();
    for (const e of this.q.examples.all(wordId) as Array<{
      sense_id: number; text: string; ref: string | null;
      modern: string | null; zh: string | null }>) {
      const arr = exBy.get(e.sense_id) ?? [];
      arr.push({ text: e.text, zh: e.zh, ref: e.ref, modern: e.modern });
      exBy.set(e.sense_id, arr);
    }
    return rows.map((r) => ({
      id: r.id, rank: r.rank, pos: r.pos, en: r.en, zh: r.zh, src: r.src,
      tags: tagBy.get(r.id) ?? [],
      relations: [...(relBy.get(r.id) ?? new Map())].map(([kind, targets]) => ({ kind, targets })),
      altOf: altBy.get(r.id) ?? [],
      examples: exBy.get(r.id) ?? [],
    }));
  }

  getEntry(word: string): EnglishEntry | null {
    const row = this.q.exact.get(word) as EnRow | undefined;
    if (!row) return null;
    const legacy = this.q.legacy.get(row.id) as { text: string; qual: string } | undefined;
    return {
      lang: 'en',
      id: row.id,
      word: row.word,
      pos: row.pos,
      isLemma: !!row.is_lemma,
      rulers: {
        collins: row.collins, oxford: row.oxford, examTag: row.exam_tag,
        bnc: row.bnc, freqRank: row.freq_rank, freqZipf: row.freq_zipf,
      },
      readings: this.q.readings.all(row.id) as EnglishReading[],
      audio: (this.q.audio.all(row.word) as Array<{
        file: string; url: string | null; region: string | null;
        region_src: string | null; speaker: string | null }>).map((a) => ({
          file: a.file, url: a.url, region: a.region,
          regionSrc: a.region_src, speaker: a.speaker,
        })),
      senses: this.sensesOf(row.id),
      relations: (() => {
        const m = new Map<string, EnglishRelationTarget[]>();
        for (const rr of this.q.relByEntry.all(row.id) as Array<{
          kind: string; target: string; ok: number }>) {
          const a = m.get(rr.kind) ?? [];
          a.push({ word: rr.target, clickable: !!rr.ok });
          m.set(rr.kind, a);
        }
        return [...m].map(([kind, targets]) => ({ kind, targets }));
      })(),
      forms: this.q.forms.all(row.id) as EnglishForm[],
      formOf: (this.q.formOf.all(row.id) as Array<{
        base: string; label: string | null; kind: string; ok: number }>).map((i) => ({
          base: i.base, label: i.label, kind: i.kind, clickable: !!i.ok,
        })),
      legacy: legacy ?? null,
    };
  }

  close() { this.db.close(); }
}
