// ============================================================================
// 日语词典服务。2026-09-16（阶段 8）。
//
// ═══ 🔴 三处和前六门不一样，照抄会静默出错 ═══
//
// ① **搜索一律走 `word_norm`，绝不用 `COLLATE NOCASE`。**
//    SQLite 的 NOCASE / `lower()` / `upper()` / `LIKE` **只折 ASCII**，
//    对假名完全无效。照抄五门的 `WHERE word = ? COLLATE NOCASE` 不会报错、
//    也不会慢 —— 它**查不到词**（`アジア` 搜不到 `あじあ`）。
//    建库时已经有意**不建** NOCASE 索引，就是为了不留这个假索引。
//
// ② **词性名要走日语覆盖层。** `part` 在全局表是「小品词」（意语的 sì/no），
//    日语的 `particle` 是**助词**（は/が/を/に）—— 同一个码，两门语言不是一个东西。
//    还有三个六门全无的：`kanji`/`kana`/`romaji`。见 `dict-labels/src/ja.ts`。
//
// ③ **`see_also` 不是 `alt_of`。** 同音索引页（`いぬ → 犬 狗 戌 率寝 寝ぬ 去ぬ`）
//    在数据层被**有意**降级成 `see_also`，就是为了不断言它们是异体字。
//    展示层印成「异体写法」＝替数据层做一个它拒绝做的断言（`JA_PLAN` §二.5）。
//
// ═══ 声调：存核位置，不存型 ═══
// 平板/头高/中高/尾高由「重音核位置 + 拍数」唯一决定 ⇒ 库里不存型，展示层算
// （`jaPitchType`）。存一个可推导的列就是留一个会和 `pitch_pos` 打架的冗余列。
// ⚠️ `pitch_pos` 可能为 NULL 而 `pitch_mark` 有值 —— 那是**推不准就留空**，
//    不是数据缺失。展示层此时只印标记，不印型。
// ============================================================================
import { DatabaseSync } from 'node:sqlite';

export type JapaneseSearchItem = {
  id: number;
  word: string;
  kana: string | null;      // 假名读音 —— 日语搜索结果**必须带它**，同形异读靠它分
  brief: string | null;
  pos: string | null;
};

export type JapaneseSense = {
  id: number;
  etymKey: string | null;   // 词源号；断组用（词性相同且词源相同才合并）
  zh: string | null;        // 中文释义
  ja: string | null;        // 日语原文定义
  en: string | null;        // 英文对应词
  pos: string | null;
  relations: JapaneseRelationGroup[];
  altOf: JapaneseAltOf[];
};

export type JapaneseReading = {
  kana: string | null;
  kanaHist: string | null;  // 历史假名遣（月 がち 的 ぐわち）
  romaji: string | null;    // 修正ヘボン式，**存源头的不自己算**
  ipa: string | null;
  notation: string | null;
  pitchMark: string | null; // 东京式重音标记（源头原样）
  pitchPos: number | null;  // 重音核位置；**推不准时为 null**
  mora: number | null;      // 拍数（由 kana 算，用于定型）
  pos: string | null;
  src: string | null;
};

export type JapaneseExample = {
  senseId: number | null;
  text: string;
  zh: string | null;
  en: string | null;
  roman: string | null;             // 整句罗马字
  ruby: Array<[string, string]>;    // 振假名 [[汉字, 读音], …]
  ref: string | null;
  bold: Array<[number, number]>;
};

export type JapaneseInflection = {
  base: string;
  label: string | null;
  clickable: boolean;
};

export type JapaneseAltOf = { target: string; zh: string | null; clickable: boolean };
export type JapaneseRelationTarget = { word: string; clickable: boolean };
export type JapaneseRelationGroup = { kind: string; targets: JapaneseRelationTarget[] };

export type JapaneseAudio = {
  url: string; file: string; speaker: string | null; kind: string;
};

export type JapaneseEntry = {
  lang: 'ja';
  id: number;
  word: string;
  pos: string | null;
  kanjiGrade: string | null;   // 常用/教育/人名用/表外 —— 单字条目才有
  // 活用类（五段/一段/サ変/カ変…）。🔴 **词元的属性**，不是某个形的属性 ——
  // 所以它在 `entry` 上，不在 `inflection` 的每一行上。
  vclass: string | null;
  freqZipf: number | null;
  isLemma: boolean;
  readings: JapaneseReading[];
  senses: JapaneseSense[];
  examples: JapaneseExample[];
  inflections: JapaneseInflection[];
  relations: JapaneseRelationGroup[];   // 词条级（`sense_id IS NULL` 的那些）
  altOf: JapaneseAltOf[];
  seeAlso: JapaneseAltOf[];             // 🔴 与 altOf 分开，见文件头③
  audio: JapaneseAudio[];
  // 🔴 **复数** —— 这个词形可能是好几个词的活用形。
  //    第一版写成单个 `base` 并在 SQL 里 `LIMIT 1`，`いぬ` 当场被说成
  //    「去ぬ 的变形」，而它同时是 去ぬ／鋳る／射る／寝ぬ／率寝 五个词的形
  //    （还本身是「犬」的假名写法）。**随便挑一个当原形 ＝ 在页面上断言一件假事。**
  bases: Array<{ word: string; label: string | null; clickable: boolean }>;
};

// 关系分组顺序。**词条级与义项级共用这一份** —— 两处各写一版迟早排序对不上。
const JA_REL_ORDER = ['synonym', 'antonym', 'hypernym', 'hyponym', 'coordinate',
                      'holonym', 'meronym', 'derived', 'related', 'proverb',
                      'abbreviation'];

function groupRelations(
  m: Map<string, JapaneseRelationTarget[]>,
): JapaneseRelationGroup[] {
  return JA_REL_ORDER.filter((k) => m.has(k)).map((k) => ({ kind: k, targets: m.get(k)! }));
}

/** 拍数。🔴 判据与 `ja/pipeline/build_pronunciation.py` 的 `nucleus()` 同源：
 *  拗音的小写假名**不单独成拍**，`ん`/促音**各算一拍**。 */
const SMALL = new Set(['ゃ', 'ゅ', 'ょ', 'ャ', 'ュ', 'ョ', 'ぁ', 'ぃ', 'ぅ', 'ぇ', 'ぉ',
                       'ァ', 'ィ', 'ゥ', 'ェ', 'ォ', 'ゎ', 'ヮ']);
export function moraCount(kana: string | null): number | null {
  if (!kana) return null;
  let n = 0;
  for (const c of kana) if (!SMALL.has(c)) n += 1;
  return n || null;
}

function parseJson<T>(s: string | null, fallback: T): T {
  if (!s) return fallback;
  try { return JSON.parse(s) as T; } catch { return fallback; }
}

// 搜索下拉的摘要。**两条查询（实时 / 预计算命中）共用这一份**，
// 不许各写一版 —— 那样缓存命中与否会给出不同的摘要，而两边都不会报错。
//
// 🔴 五级回退，**顺序就是信息量**：
//   ① 中文释义（第一条**有中文的**义项）
//   ②③ 日语原文 / 英文（2,362 个词元有义项但一条中文都没有）
//   ④ 跳转指针（`あいする → 愛する`）—— **32,694 个词元只有这个**，
//      占词元的 13%。第一版只查 ①，它们在下拉里是**一行光秃秃的词**，
//      读者不知道那是什么、也不知道点进去会有东西。
//   ⑤ 是别的词的活用形（`あり` ← `ある 连用形`）—— 785 个。
// ⚠️ `[[it-display-layer-stage8]]`：这一条是**起了服务、真敲进搜索框**才看见的。
//    契约闸断言的是词条页，下拉框不在它的视野里。
const BRIEF_SQL = `
  COALESCE(
    -- 🔴 是「**第一条有中文的义项**」，不是「第一条义项的中文」。
    --    「あ」的第 1 条义项只有英文、第 2 条才有中文「啊！哦！」——
    --    写成后者时它在下拉里是空的，而这个词有 9 条义项、27 条关系、13 条例句。
    (SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
       WHERE s.word_id = d.id AND g.lang = 'zh' ORDER BY s.rank LIMIT 1),
    -- 全库 2,362 个词元有义项但**一条中文都没有** ⇒ 退到日语原文，再退到英文。
    -- 印日语定义比印空白强得多（docs/FRAMEWORK.md：错比缺更伤权威，
    -- 而这里两者都不是错，是「有 vs 没有」）。
    (SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
       WHERE s.word_id = d.id AND g.lang = 'ja' ORDER BY s.rank LIMIT 1),
    (SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
       WHERE s.word_id = d.id AND g.lang = 'en' ORDER BY s.rank LIMIT 1),
    (SELECT '→ ' || r.target FROM sense_relation r
       WHERE r.word_id = d.id AND r.kind IN ('alt_of','see_also')
       ORDER BY r.kind, r.id LIMIT 1),
    (SELECT i.base || ' ' || COALESCE(i.label_zh, '的变形') FROM inflection i
       WHERE i.word_id = d.id ORDER BY i.id LIMIT 1)
  )`;

export class JapaneseDictService {
  readonly databasePath: string;

  readonly lang = 'ja';

  private readonly db: DatabaseSync;

  private readonly q: Record<string, ReturnType<DatabaseSync['prepare']>>;

  /** 预计算表在不在、按多大的 TOPN 建的。**构造时探一次**，别每次查询都试。 */
  private readonly hasCache: boolean;

  private readonly cacheTopN: number;

  constructor(databasePath: string) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');

    this.q = {
      stats: this.db.prepare(`
        SELECT (SELECT COUNT(*) FROM dict)                  AS total,
               (SELECT SUM(is_lemma) FROM dict)             AS lemmas,
               (SELECT COUNT(*) FROM sense)                 AS senses,
               (SELECT COUNT(*) FROM example)               AS examples,
               (SELECT COUNT(*) FROM audio)                 AS audio
      `),

      // 🔴 前缀搜索走 `word_norm`。**不要 COLLATE NOCASE** —— 见文件头①。
      //    `word_norm` 是 Python 侧算的 NFKC + 片假名→平假名，
      //    所以 `アジア` 和 `あじあ` 归一后同键，两边都搜得到。
      search: this.db.prepare(`
        SELECT d.id, d.word, d.pos,
               (SELECT e.kana FROM entry e
                 WHERE e.word_id = d.id AND e.kana IS NOT NULL LIMIT 1) AS kana,
               -- 🔴 嵌套写，不要 JOIN。
               -- 写成 JOIN sense_gloss g ON g.sense_id = s.id WHERE ... AND g.lang='zh'
               -- 会让 SQLite 挑 idx_glosslang(lang) 当驱动 —— 那是 29 万行，
               -- 每个候选词扫一遍（EXPLAIN 里写着 SEARCH g USING INDEX idx_glosslang）。
               -- 嵌套之后驱动表变成 sense，内层才吃得到主键 sense_gloss(sense_id, lang,...)。
               -- [[query-perf-collation-traps]]：索引在那儿不等于用得上，得看谁当驱动表。
               -- 注：本段是 SQL 模板字符串内，**不许出现反引号** —— 它会把模板提前终结。
               ${BRIEF_SQL}                                           AS brief
        FROM dict d
        WHERE d.word_norm >= ? AND d.word_norm < ?
        ORDER BY d.is_lemma DESC, d.freq_zipf IS NULL, d.freq_zipf DESC, length(d.word), d.word
        LIMIT ?
      `),

      // 预计算命中：拿 `search_prefix` 里排好序的 id，再补上摘要字段。
      // 🔴 **补字段的那两个子查询与 `search` 里的逐字相同** —— 差一个字就是
      //    「命中缓存时摘要和实时查询不一样」，而两边都不会报错。
      searchCached: this.db.prepare(`
        SELECT d.id, d.word, d.pos,
               (SELECT e.kana FROM entry e
                 WHERE e.word_id = d.id AND e.kana IS NOT NULL LIMIT 1) AS kana,
               ${BRIEF_SQL}                                           AS brief
        FROM search_prefix p JOIN dict d ON d.id = p.word_id
        WHERE p.prefix = ? AND p.rank < ?
        ORDER BY p.rank
      `),

      // `vclass` 在 `entry` 上（词元属性）⇒ 取该词形第一条非空的
      vclassOf: this.db.prepare(
        'SELECT vclass FROM entry WHERE word_id=? AND vclass IS NOT NULL LIMIT 1'),

      exact: this.db.prepare(
        'SELECT id, word, pos, kanji_grade, freq_zipf, is_lemma FROM dict'
        + ' WHERE word = ? OR word_norm = ? ORDER BY word = ? DESC LIMIT 1'),

      readings: this.db.prepare(`
        SELECT e.kana, e.kana_hist, e.romaji, e.pos,
               p.ipa, p.notation, p.pitch_mark, p.pitch_pos, p.src
        FROM entry e
        LEFT JOIN pronunciation p ON p.entry_id = e.id
        WHERE e.word_id = ?
        ORDER BY e.etym_no, e.seq
      `),
      // 词条没有 entry 级读音时（阶段 3a 收的词），也可能有 word_id 级的音标
      readingsByWord: this.db.prepare(
        'SELECT ipa, notation, pitch_mark, pitch_pos, pos, src FROM pronunciation'
        + ' WHERE word_id = ? AND entry_id IS NULL'),

      senses: this.db.prepare(`
        SELECT s.id, s.pos, e.etym_no AS etymKey,
               (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='zh') AS zh,
               (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='ja') AS ja,
               (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='en') AS en
        FROM sense s LEFT JOIN entry e ON e.id = s.entry_id
        WHERE s.word_id = ? AND s.hidden = 0
        ORDER BY e.etym_no, s.rank, s.id
      `),

      // 关系：一次取全，调用方按 sense_id 分到义项级/词条级。
      // `ok` ＝ 目标在库里 ⇒ 点得动。
      relations: this.db.prepare(`
        SELECT r.sense_id, r.kind, r.target,
               EXISTS(SELECT 1 FROM dict d WHERE d.word = r.target) AS ok,
               (SELECT g.text FROM sense s2 JOIN sense_gloss g ON g.sense_id = s2.id
                 JOIN dict d2 ON d2.id = s2.word_id
                 WHERE d2.word = r.target AND g.lang='zh' ORDER BY s2.rank LIMIT 1) AS zh
        FROM sense_relation r
        WHERE r.word_id = ? AND r.hidden = 0
        ORDER BY r.kind, r.id
      `),

      examples: this.db.prepare(`
        SELECT x.sense_id, x.text, x.ref, x.bold, x.roman, x.ruby,
               (SELECT text FROM example_gloss WHERE example_id=x.id AND lang='zh') AS zh,
               (SELECT text FROM example_gloss WHERE example_id=x.id AND lang='en') AS en
        FROM example x
        WHERE x.word = ? AND x.hidden = 0
        ORDER BY x.sense_id IS NULL, x.id
      `),

      // 这个词形的变形（它是原形时）
      inflections: this.db.prepare(`
        SELECT i.base, i.label_zh AS label, d.word AS formWord,
               EXISTS(SELECT 1 FROM dict d2 WHERE d2.id = i.word_id) AS ok
        FROM inflection i JOIN dict d ON d.id = i.word_id
        WHERE i.base_id = ? ORDER BY i.id
      `),
      // 它是变形时，指回原形。🔴 **走 `word_id` 不走 `base_id`** ——
      //    `base_id` 有 988 行悬空（原形连三版都没有独立条目）。
      baseOf: this.db.prepare(`
        SELECT i.base, MIN(i.label_zh) AS label,
               EXISTS(SELECT 1 FROM dict d WHERE d.word = i.base) AS ok
        FROM inflection i WHERE i.word_id = ? GROUP BY i.base ORDER BY i.base
      `),

      audio: this.db.prepare(
        'SELECT file, COALESCE(url_ogg, url_wav, url_other, url_mp3) AS url,'
        + ' speaker, kind FROM audio WHERE word = ? ORDER BY id'),
    };

    // ⚠️ 表不存在是**正常状态**（这门还没跑阶段 9），不是故障 ⇒ 兜到"没有缓存"。
    const meta = (() => {
      try {
        const r = this.db.prepare(
          "SELECT v FROM search_prefix_meta WHERE k='topn'").get() as { v: string } | undefined;
        return r ? Number(r.v) : null;
      } catch { return null; }
    })();
    this.hasCache = meta !== null;
    this.cacheTopN = meta ?? 0;
  }

  // 🔴 方法名**必须与另六门一致** —— API 层是 `getService(lang).getStats()` /
  //    `.getEntry()` 泛型调用的。我第一版写成 `stats()`/`lookup()`，类型检查全绿
  //    （`getService` 返回联合类型、API 层把它当 any 用），**跑起来才 500**。
  //    这就是 `[[correct-steps-can-compose-a-hole]]`：每一步都对，跨步的约定失效。
  getStats() { return this.q.stats.get() as Record<string, number>; }

  /** 前缀搜索。`prefix` 由调用方归一（与建库侧 `norm_ja` 同口径）。
   *
   * ⭐ 热前缀走预计算表（阶段 9）。**未命中＝正确回退，不是错误** ——
   *    结果完全一样，只是慢一点。连「表存不存在」都按未命中处理，
   *    所以这份代码在还没跑过 `build_search_prefix.py` 的库上照样能用。
   */
  search(prefix: string, limit = 30): JapaneseSearchItem[] {
    const p = normJa(prefix);
    if (!p) return [];
    const shape = (r: Record<string, unknown>): JapaneseSearchItem => ({
      id: r.id as number, word: r.word as string,
      kana: (r.kana as string) ?? null,
      brief: (r.brief as string) ?? null, pos: (r.pos as string) ?? null,
    });
    if (this.hasCache && limit <= this.cacheTopN) {
      try {
        const hit = this.q.searchCached.all(p, limit) as Array<Record<string, unknown>>;
        if (hit.length) return hit.map(shape);
      } catch { /* 表被删/结构变了 ⇒ 按未命中处理 */ }
    }
    // 前缀区间：`[p, p + ￿)` —— 比 `LIKE p || '%'` 更能吃到索引
    return (this.q.search.all(p, `${p}￿`, limit) as Array<Record<string, unknown>>)
      .map(shape);
  }

  getEntry(word: string): JapaneseEntry | null {
    const n = normJa(word);
    const head = this.q.exact.get(word, n, word) as Record<string, unknown> | undefined;
    if (!head) return null;
    const id = head.id as number;

    // ── 读音 ──
    const readings: JapaneseReading[] = [];
    const seen = new Set<string>();
    for (const r of this.q.readings.all(id) as Array<Record<string, unknown>>) {
      const kana = (r.kana as string) ?? null;
      const key = `${kana}|${r.ipa ?? ''}|${r.pitch_mark ?? ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      readings.push({
        kana, kanaHist: (r.kana_hist as string) ?? null,
        romaji: (r.romaji as string) ?? null,
        ipa: (r.ipa as string) ?? null, notation: (r.notation as string) ?? null,
        pitchMark: (r.pitch_mark as string) ?? null,
        pitchPos: (r.pitch_pos as number) ?? null,
        mora: moraCount(kana), pos: (r.pos as string) ?? null,
        src: (r.src as string) ?? null,
      });
    }
    // ── 词条级读音行（`entry_id IS NULL`）──
    // 🔴 **声调几乎全在这一档**：它来自中文版（唯一可用的东京式来源），
    //    入库时挂在 `word_id` 上而不是某条 `entry` 上；而 IPA 来自英文版、挂在 entry 上。
    //    ⇒ 同一个读音被拆在两行里。第一版我把它们当两条读音并排印出来，
    //      `痛い` 于是显示成「いたい/itai [ita̠i]｜? ♪[ìtáꜜì](核2/null拍)｜? [ita̠i]」——
    //      三行，两行没有假名，读者看不懂那是什么。
    // ⚠️ **只在这个词只有一个假名读音时才合并。** 多读音词（`爺`＝じい/じじ/じじい）
    //    上无法判断这条声调属于哪一个 —— 那种情况保持独立行，宁可分开印也不猜。
    const kanaSet = new Set(readings.map((r) => r.kana).filter(Boolean));
    const onlyKana = kanaSet.size === 1 ? [...kanaSet][0]! : null;
    for (const r of this.q.readingsByWord.all(id) as Array<Record<string, unknown>>) {
      const pm = (r.pitch_mark as string) ?? null;
      const ipa = (r.ipa as string) ?? null;
      if (onlyKana) {
        const host = readings.find((x) => x.kana === onlyKana
          && (pm ? x.pitchMark === null : true));
        if (host) {
          if (pm && !host.pitchMark) {
            host.pitchMark = pm;
            host.pitchPos = (r.pitch_pos as number) ?? null;
          }
          if (ipa && !host.ipa) {
            host.ipa = ipa;
            host.notation = (r.notation as string) ?? null;
          }
          continue;
        }
      }
      const key = `|${ipa ?? ''}|${pm ?? ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      readings.push({
        kana: onlyKana, kanaHist: null, romaji: null,
        ipa, notation: (r.notation as string) ?? null,
        pitchMark: pm, pitchPos: (r.pitch_pos as number) ?? null,
        // 拍数跟着假名走 —— 有假名才算得出，没有就是 null（而不是 0）
        mora: moraCount(onlyKana), pos: (r.pos as string) ?? null,
        src: (r.src as string) ?? null,
      });
    }

    // ── 关系：义项级 / 词条级 / 指针三分 ──
    const bySense = new Map<number, Map<string, JapaneseRelationTarget[]>>();
    const wordLevel = new Map<string, JapaneseRelationTarget[]>();
    const altOf: JapaneseAltOf[] = [];
    const seeAlso: JapaneseAltOf[] = [];
    for (const r of this.q.relations.all(id) as Array<Record<string, unknown>>) {
      const kind = r.kind as string;
      const target = r.target as string;
      const clickable = Boolean(r.ok);
      if (kind === 'alt_of' || kind === 'see_also') {
        // 🔴 两者**必须分开**，见文件头③
        (kind === 'alt_of' ? altOf : seeAlso).push({
          target, zh: (r.zh as string) ?? null, clickable,
        });
        continue;
      }
      const sid = (r.sense_id as number) ?? null;
      const m = sid === null ? wordLevel
        : (bySense.get(sid) ?? bySense.set(sid, new Map()).get(sid)!);
      const arr = m.get(kind);
      if (arr) arr.push({ word: target, clickable });
      else m.set(kind, [{ word: target, clickable }]);
    }

    // ── 义项 ──
    const senses = (this.q.senses.all(id) as Array<Record<string, unknown>>).map((s) => ({
      id: s.id as number,
      etymKey: (s.etymKey as string) ?? null,
      zh: (s.zh as string) ?? null,
      ja: (s.ja as string) ?? null,
      en: (s.en as string) ?? null,
      pos: (s.pos as string) ?? null,
      relations: groupRelations(bySense.get(s.id as number) ?? new Map()),
      altOf: [] as JapaneseAltOf[],
    }));

    // ── 例句 ──
    const examples = (this.q.examples.all(head.word as string) as Array<Record<string, unknown>>)
      .map((x) => ({
        senseId: (x.sense_id as number) ?? null,
        text: x.text as string,
        zh: (x.zh as string) ?? null,
        en: (x.en as string) ?? null,
        roman: (x.roman as string) ?? null,
        ruby: parseJson<Array<[string, string]>>((x.ruby as string) ?? null, []),
        ref: (x.ref as string) ?? null,
        bold: parseJson<Array<[number, number]>>((x.bold as string) ?? null, []),
      }));

    // ── 变形 ──
    const inflections = (this.q.inflections.all(id) as Array<Record<string, unknown>>)
      .map((i) => ({
        base: i.formWord as string,
        label: (i.label as string) ?? null,
        clickable: Boolean(i.ok),
      }));
    const bases = (this.q.baseOf.all(id) as Array<Record<string, unknown>>).map((b) => ({
      word: b.base as string, label: (b.label as string) ?? null,
      clickable: Boolean(b.ok),
    }));

    const audio = (this.q.audio.all(head.word as string) as Array<Record<string, unknown>>)
      .filter((a) => a.url)
      .map((a) => ({
        url: a.url as string, file: a.file as string,
        speaker: (a.speaker as string) ?? null, kind: a.kind as string,
      }));

    return {
      lang: 'ja', id, word: head.word as string,
      pos: (head.pos as string) ?? null,
      kanjiGrade: (head.kanji_grade as string) ?? null,
      vclass: ((this.q.vclassOf.get(id) as { vclass?: string } | undefined)
        ?.vclass) ?? null,
      freqZipf: (head.freq_zipf as number) ?? null,
      isLemma: Boolean(head.is_lemma),
      readings, senses, examples, inflections,
      relations: groupRelations(wordLevel),
      altOf, seeAlso, audio, bases,
    };
  }

  close() { this.db.close(); }
}

/** 与建库侧 `ja/pipeline/build.py` 的 `norm_ja` 同口径：NFKC + 片假名→平假名。
 *
 * 🔴 **两处必须一致**，否则搜索归一键与库里的 `word_norm` 对不上，
 *    症状是「搜不到词」而不是报错。TS 侧没有 Python 的 `unicodedata`，
 *    用 `String.normalize('NFKC')` —— 两者对本项目用到的字符等价。
 */
export function normJa(s: string): string {
  let out = '';
  for (const c of s.normalize('NFKC')) {
    const cp = c.codePointAt(0)!;
    // 片假名 → 平假名（U+30A1–U+30F6 段整体下移 0x60）
    out += (cp >= 0x30a1 && cp <= 0x30f6)
      ? String.fromCodePoint(cp - 0x60) : c;
  }
  return out.trim();
}
