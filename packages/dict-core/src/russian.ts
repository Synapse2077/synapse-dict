// ============================================================================
// 俄语词典服务。2026-10-25（ru 阶段 9a）。
//
// ═══ 🔴 与前九门不一样的地方，照抄会静默出错 ═══
//
// ① **一页是一组 entry，不是一个词形**。ru 的数据从阶段 1 起就是 entry 中心的：
//    同一个词形 `замок` 有 за́мок（城堡）／замо́к（锁）两个 entry，重音、读音、变格表、例句、
//    词源**都挂在 entry 上**。⇒ 本服务按 entry 端出，展示层按「词性」把 entry 归组。
//
// ② **搜索键与数据层的 `norm_ru` 逐字同一条**：只剥重音符（U+0301／U+0300）＋ 小写。
//    🔴 **不做 ё→е 折叠、不做 NFD**（dbtool.norm_ru 的文件头：NFD 毁 й/ё；折叠撞 всё/все）。
//    ⚠️ 代价：搜 `все` 搜不到 `всё`。那是检索召回问题 —— 记欠账，**不许改键来解**。
//
// ③ **词形页（is_lemma=0）的内容是指针**：「воды 是 вода 的单数属格」。
//    指针在证据层（`sense_src.sense_id IS NULL AND pointer_target IS NOT NULL`），
//    出版层没有它们（义项闸 E5 守着）⇒ `pointers` 这一路专门取（vi 的 W15 同形）。
//    🔴 R22：形动词页源头没给结构目标（`pointer_target` 空）⇒ 不许从 `text` 里用正则抠。
//
// ④ **R21：词形页上不许把读音与带重音拼写配成一对印**（两者可能各属一个义项）。
//    ⇒ 端出原值，展示层据 `isLemma` 决定排法；本文件不替它配对。
//
// ④' **R29：中文一律读 `COALESCE(text_pub, text)`**（释义／例句译文／指针说明／词源）。
//    `text` 是源头或模型原话（zh-t 版是繁体），`text_pub` 是 `criteria.zh_simp` 转出的简体。
//    🔴 **不许在这里做繁→简**：整段 OpenCC 会把本来就是简体的改错（`覆上→复上`），安全的那道只有一个家。
//
// ④'' **R30：搜索与兜底查找走 ё 召回键 `word_fold`**（`foldRu` ≡ `dbtool.fold_ru`）。
//    🔴 它**不是身份键**（`все`/`всё` 在上面相同）：认词仍按 `word` → `word_norm`，只有两者都落空才用它；
//       只差 ё/е 的另一个词作 `yoVariants` 端出，展示层印成「你可能找的是」，不合并。
//
// ⑤ **词源按 entry 端、不去重**（RU_PLAN §17.1：去重归展示层，数据层藏「重复」就是 vi 的 B18）。
//
// ⑥ 变位表的 `tags` 是**源头顺序**的 `|` 串，同一组标签两种顺序都有（`nominative|singular`／
//    `plural|prepositional`）⇒ 端出拆好的数组，展示层按自己的规范顺序排。
//
// ═══ 🔴🔴 这个文件里**不许在 SQL 模板串的注释里用反引号** ═══
// SQL 串是反引号界定的模板字符串，注释里再写一个反引号就当场截断字符串（korean.ts／vietnamese.ts 各栽过）。
//
// ═══ ⚠️ 兜底越体面，缺陷越难发现 ═══
// 一律端出原值 ＋ 布尔，不在 SQL 里 COALESCE 掉语义（`[[it-display-layer-stage8]]`）。
// ============================================================================
import { DatabaseSync } from 'node:sqlite';

export type RussianSearchItem = { id: number; word: string; brief: string | null; isLemma: boolean };

export type RussianGloss = { lang: string; text: string; src: string; model: boolean };

export type RussianSense = {
  id: number;
  entryId: number;
  /** 源头义项序号（sense.rank ＝ 源头 senses[] 的下标，**是真的顺序**，与 vi 的恒 0 不同）。 */
  rank: number;
  glosses: RussianGloss[];
  tags: Array<{ bucket: string; value: string }>;
};

export type RussianExample = {
  senseId: number | null;
  entryId: number;
  text: string;
  ref: string | null;
  zh: string | null;
  /** zh 的来源：源头版／同句借用／模型 —— 展示层据此标注。 */
  zhSrc: string | null;
  en: string | null;
  src: string;
};

export type RussianRelation = {
  entryId: number;
  senseId: number | null;
  kind: string;
  subkind: string | null;
  relGroup: string | null;
  formGroup: string | null;
  target: string;
  /** 解析得到的 dict.id；null ＝ 库里没这个词形 ⇒ **不许渲染成链接**。 */
  targetId: number | null;
  src: string;
};

export type RussianInflection = {
  entryId: number;
  form: string;
  stressed: string | null;
  /** 拆好的标签（源头顺序），展示层自己排。 */
  tags: string[];
  tableTag: string | null;
  src: string;
};

export type RussianPointer = {
  entryId: number | null;
  lang: string;
  text: string;
  src: string;
  /** 源头 form_of/alt_of 的目标词形；没有结构字段时是 null（R22）。 */
  target: string | null;
  targetId: number | null;
};

export type RussianEntryPart = {
  id: number;
  pos: string;
  etymNo: number;
  etymSub: number;
  aspect: string | null;
  gender: string | null;
  animacy: string | null;
  /** 默认展示的带重音拼写（派生自 stress 表 is_primary）；null ＝ 没有。 */
  stressed: string | null;
  /** 全部重音候选（R14：主行挑法是弱信号，候选都给出去）。 */
  stressVariants: string[];
  src: string;
};

export type RussianEntry = {
  /** 🔴 vi 漏过这一行，后果是视图一次都没被渲染（dispatch-audit 的起因）。 */
  lang: 'ru';
  id: number;
  word: string;
  isLemma: boolean;
  entries: RussianEntryPart[];
  senses: RussianSense[];
  pronunciations: Array<{ entryId: number | null; ipa: string; dialect: string; notation: string; src: string }>;
  inflections: RussianInflection[];
  examples: RussianExample[];
  relations: RussianRelation[];
  etymologies: Array<{ entryId: number; etymNo: number; text: string; etymType: string | null; src: string }>;
  audios: Array<{ entryId: number | null; url: string; commonsKey: string; src: string }>;
  pointers: RussianPointer[];
  /** 同一个 word_norm 的别的词形（R12：`Аален`/`аален`）。 */
  homographs: Array<{ id: number; word: string }>;
  /** R30：只差在 ё/е 上的**另一个词**（`все` ↔ `всё`）。不是同一个词，是「你可能找的是它」。 */
  yoVariants: Array<{ id: number; word: string }>;
  /** R30：用户没打 ё 而按召回键找到的（`елка` → `ёлка`）—— 展示层据此说明「按 ё 写法找到」。 */
  foldedFrom: string | null;
};

/** 与 `ru/dbtool.norm_ru` 逐字同一条：剥 U+0301／U+0300 ＋ 小写。**不 NFD、不折 ё**。 */
export function normRu(s: string): string {
  return s.replace(/[́̀]/g, '').toLowerCase();
}

/** R30 ё 召回键：与 `ru/dbtool.fold_ru` 逐字同一条（`normRu` 再折 ё→е）。**不是身份键**。 */
export function foldRu(s: string): string {
  return normRu(s).replace(/ё/g, 'е');
}

export class RussianDictService {
  readonly databasePath: string;

  readonly lang = 'ru';

  private readonly db: DatabaseSync;

  private readonly q: Record<string, ReturnType<DatabaseSync['prepare']>>;

  constructor(databasePath: string) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');
    this.q = {
      stats: this.db.prepare(`
        SELECT (SELECT COUNT(*) FROM dict)                       AS total,
               (SELECT SUM(is_lemma) FROM dict)                  AS lemmas,
               (SELECT COUNT(*) FROM sense WHERE hidden = 0)     AS senses,
               (SELECT COUNT(*) FROM example WHERE hidden = 0)   AS examples,
               (SELECT COUNT(*) FROM audio WHERE hidden = 0)     AS audio
      `),
      // 词元优先、短的优先；brief 取第一条可出版义项的中文
      search: this.db.prepare(`
        SELECT d.id, d.word, d.is_lemma AS isLemma,
               (SELECT COALESCE(g.text_pub, g.text) FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
                 WHERE s.word_id = d.id AND s.hidden = 0 AND g.lang = 'zh'
                 ORDER BY s.id LIMIT 1) AS brief
        FROM dict d
        WHERE d.word_fold >= ? AND d.word_fold < ?
        ORDER BY (d.word_norm >= ? AND d.word_norm < ?) DESC, d.is_lemma DESC, LENGTH(d.word), d.word
        LIMIT ?
      `),
      exactWord: this.db.prepare('SELECT id, word, is_lemma AS isLemma FROM dict WHERE word = ?'),
      exactNorm: this.db.prepare(
        'SELECT id, word, is_lemma AS isLemma FROM dict WHERE word_norm = ? ORDER BY is_lemma DESC, id'),
      homographs: this.db.prepare('SELECT id, word FROM dict WHERE word_norm = ? AND id <> ? ORDER BY id'),
      // R30：省写 ё 的兜底（精确、归一都找不到时）与「只差 ё/е 的另一个词」
      exactFold: this.db.prepare(
        'SELECT id, word, is_lemma AS isLemma FROM dict WHERE word_fold = ? ORDER BY is_lemma DESC, id'),
      yoVariants: this.db.prepare(
        'SELECT id, word FROM dict WHERE word_fold = ? AND word_norm <> ? ORDER BY is_lemma DESC, id'),
      entries: this.db.prepare(`
        SELECT id, pos, etym_no AS etymNo, etym_sub AS etymSub, aspect, gender, animacy,
               stressed, src
        FROM entry WHERE word_id = ? ORDER BY id
      `),
      stress: this.db.prepare(`
        SELECT entry_id AS entryId, stressed FROM stress WHERE word_id = ?
        ORDER BY entry_id, variant_seq
      `),
      senses: this.db.prepare(`
        SELECT id, entry_id AS entryId, rank FROM sense
        WHERE word_id = ? AND hidden = 0 ORDER BY entry_id, rank, id
      `),
      glosses: this.db.prepare(`
        SELECT g.sense_id AS senseId, g.lang, COALESCE(g.text_pub, g.text) AS text, g.src FROM sense_gloss g
        JOIN sense s ON s.id = g.sense_id
        WHERE s.word_id = ? AND s.hidden = 0 ORDER BY g.sense_id, g.id
      `),
      tags: this.db.prepare(`
        SELECT t.sense_id AS senseId, t.bucket, t.value FROM sense_tag t
        JOIN sense s ON s.id = t.sense_id
        WHERE s.word_id = ? AND s.hidden = 0 ORDER BY t.sense_id, t.id
      `),
      pronunciations: this.db.prepare(`
        SELECT entry_id AS entryId, ipa, dialect, notation, src FROM pronunciation
        WHERE word_id = ? AND hidden = 0 ORDER BY entry_id, id
      `),
      inflections: this.db.prepare(`
        SELECT i.entry_id AS entryId, i.form, i.stressed, i.tags, i.table_tag AS tableTag, i.src
        FROM inflection i JOIN entry e ON e.id = i.entry_id
        WHERE e.word_id = ? ORDER BY i.entry_id, i.id
      `),
      examples: this.db.prepare(`
        SELECT x.sense_id AS senseId, x.entry_id AS entryId, COALESCE(x.text_pub, x.text) AS text, x.ref, x.src,
               (SELECT COALESCE(text_pub, text) FROM example_gloss WHERE example_id = x.id AND lang = 'zh') AS zh,
               (SELECT src FROM example_gloss WHERE example_id = x.id AND lang = 'zh') AS zhSrc,
               (SELECT text FROM example_gloss WHERE example_id = x.id AND lang = 'en') AS en
        FROM example x
        WHERE x.word_id = ? AND x.hidden = 0
        ORDER BY x.entry_id, x.sense_id IS NULL, x.id
      `),
      relations: this.db.prepare(`
        SELECT entry_id AS entryId, sense_id AS senseId, kind, subkind, rel_group AS relGroup,
               form_group AS formGroup, target, target_id AS targetId, src
        FROM sense_relation WHERE word_id = ? AND hidden = 0
        -- 只按 id 排：视图自己按 entry／kind 分组。原先 ORDER BY entry_id, kind, id 在最重的页
        -- （5,640 条关系）上要临时 B 树排序 15.6 ms，而那个顺序视图根本不用（查询计划闸逮到的）
        ORDER BY id
      `),
      etymologies: this.db.prepare(`
        SELECT entry_id AS entryId, etym_no AS etymNo, COALESCE(text_pub, text) AS text,
               etym_type AS etymType, src
        FROM etymology WHERE word_id = ? AND hidden = 0 ORDER BY entry_id, id
      `),
      audios: this.db.prepare(`
        SELECT entry_id AS entryId, url, commons_key AS commonsKey, src FROM audio
        WHERE word_id = ? AND hidden = 0 ORDER BY id
      `),
      // 指针：证据层的指针义项（源头给了、出版层有意不收）。目标解析到 dict 才可点
      pointers: this.db.prepare(`
        SELECT x.entry_id AS entryId, x.lang, COALESCE(x.text_pub, x.text) AS text, x.src, x.pointer_target AS target,
               -- 源头的目标带重音符（воды 页上的目标是 вода́），dict.word 不带 ⇒ 先剥再解析（与关系层同一条规矩）
               (SELECT d.id FROM dict d
                 WHERE d.word = replace(replace(x.pointer_target, char(769), ''), char(768), '')
                 ORDER BY d.id LIMIT 1) AS targetId
        FROM sense_src x
        WHERE x.word_id = ? AND x.sense_id IS NULL AND x.pointer_target IS NOT NULL
        ORDER BY x.id
      `),
    };
  }

  close(): void { this.db.close(); }

  getStats() { return this.q.stats.get() as Record<string, number>; }

  search(prefix: string, limit = 30): RussianSearchItem[] {
    // R30：区间走 ё 召回键（省写 ё 也找得到），与输入**逐字**对上 ё 的排前面（打了 `всё` 先给 всё）
    const n = normRu(prefix.trim());
    const p = foldRu(prefix.trim());
    if (!p) return [];
    const rows = this.q.search.all(p, `${p}￿`, n, `${n}￿`, Math.max(1, Math.min(limit, 100))) as
      unknown as Array<{ id: number; word: string; isLemma: number; brief: string | null }>;
    return rows.map((r) => ({ ...r, isLemma: !!r.isLemma }));
  }

  getEntry(word: string): RussianEntry | null {
    const raw = word.trim();
    type Hit = { id: number; word: string; isLemma: number };
    // 🔴 R12：精确大小写优先；`word_norm` 一对多时**端出全部**作 homographs（vi 的 `.get()` 只取第一行那一跤）
    let hit = this.q.exactWord.get(raw) as Hit | undefined;
    let foldedFrom: string | null = null;
    if (!hit) {
      const cands = this.q.exactNorm.all(normRu(raw)) as unknown as Hit[];
      if (cands.length) [hit] = cands;
    }
    if (!hit) {
      // R30：省写了 ё（`елка`）—— 归一键找不到才走召回键；找到几个都端出来（yoVariants），这里只取词元优先的第一个
      const cands = this.q.exactFold.all(foldRu(raw)) as unknown as Hit[];
      if (!cands.length) return null;
      [hit] = cands;
      foldedFrom = raw;
    }
    const id = hit.id;
    const stressRows = this.q.stress.all(id) as unknown as Array<{ entryId: number; stressed: string }>;
    const variants = new Map<number, string[]>();
    for (const r of stressRows) {
      const a = variants.get(r.entryId);
      if (a) a.push(r.stressed); else variants.set(r.entryId, [r.stressed]);
    }
    const entries = (this.q.entries.all(id) as unknown as Array<Omit<RussianEntryPart, 'stressVariants'>>)
      .map((e) => ({ ...e, stressVariants: variants.get(e.id) ?? [] }));

    const glossRows = this.q.glosses.all(id) as unknown as Array<{ senseId: number } & Omit<RussianGloss, 'model'>>;
    const tagRows = this.q.tags.all(id) as unknown as Array<{ senseId: number; bucket: string; value: string }>;
    const gBy = new Map<number, RussianGloss[]>();
    for (const g of glossRows) {
      const v = { lang: g.lang, text: g.text, src: g.src, model: g.src.startsWith('model:') };
      const a = gBy.get(g.senseId);
      if (a) a.push(v); else gBy.set(g.senseId, [v]);
    }
    const tBy = new Map<number, Array<{ bucket: string; value: string }>>();
    for (const t of tagRows) {
      const a = tBy.get(t.senseId);
      if (a) a.push({ bucket: t.bucket, value: t.value }); else tBy.set(t.senseId, [{ bucket: t.bucket, value: t.value }]);
    }
    const senses = (this.q.senses.all(id) as unknown as Array<{ id: number; entryId: number; rank: number }>)
      .map((s) => ({ ...s, glosses: gBy.get(s.id) ?? [], tags: tBy.get(s.id) ?? [] }));

    const infl = (this.q.inflections.all(id) as unknown as Array<Omit<RussianInflection, 'tags'> & { tags: string | null }>)
      .map((r) => ({ ...r, tags: (r.tags ?? '').split('|').filter(Boolean) }));

    return {
      lang: 'ru',
      id,
      word: hit.word,
      isLemma: !!hit.isLemma,
      entries,
      senses,
      pronunciations: this.q.pronunciations.all(id) as unknown as RussianEntry['pronunciations'],
      inflections: infl,
      examples: this.q.examples.all(id) as unknown as RussianExample[],
      relations: this.q.relations.all(id) as unknown as RussianRelation[],
      etymologies: this.q.etymologies.all(id) as unknown as RussianEntry['etymologies'],
      audios: this.q.audios.all(id) as unknown as RussianEntry['audios'],
      pointers: this.q.pointers.all(id) as unknown as RussianPointer[],
      homographs: this.q.homographs.all(normRu(hit.word), id) as unknown as Array<{ id: number; word: string }>,
      yoVariants: this.q.yoVariants.all(foldRu(hit.word), normRu(hit.word)) as unknown as Array<{ id: number; word: string }>,
      foldedFrom,
    };
  }
}
