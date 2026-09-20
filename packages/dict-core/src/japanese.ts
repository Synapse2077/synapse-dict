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
// ═══ ⚠️ 2026-09-18：本文件 9-16 之后的未提交改动被 `git checkout` 冲掉过一次 ═══
// 起因是跑展示层变异验证时拿 `git checkout <file>` 撤销变异 —— 而这个文件当时
// **本来就是 dirty 的**，那条命令把两天的改动一起还原了，且不可逆（stash /
// IDE 本地历史 / Time Machine 全查过，无副本）。
// ⇒ 下面标着「**重建**」的几段是照契约闸 54 条断言 + `App.tsx` 的消费形状重写的，
//   行为已验到位，但**注释里的推导过程不是原文**。教训：
//   **撤销自己的改动前先确认那个文件原本干不干净**；dirty 文件只能先 `cp` 备份。
// ⭐ `accentSkeleton` 的重写拿实测复核过：多读音声调行唯一匹配
//   **1,125 / 1,189 = 94.6%**，与原注释记的 1,124 / 1,187 = 94.7% 落在同一个数上
//   （行数差 2 是库后来又动过）—— 独立重建撞上同一个测量值，才敢说行为等价。
//
// ═══ 声调：存核位置，不存型 ═══
// 平板/头高/中高/尾高由「重音核位置 + 拍数」唯一决定 ⇒ 库里不存型，展示层算
// （`jaPitchType`）。存一个可推导的列就是留一个会和 `pitch_pos` 打架的冗余列。
// ⚠️ `pitch_pos` 可能为 NULL 而 `pitch_mark` 有值 —— 那是**推不准就留空**，
//    不是数据缺失。展示层此时只印标记，不印型。
// ============================================================================
import { DatabaseSync } from 'node:sqlite';
import { etymKeyOfEntry } from './etym.js';

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
  // 这条义项属于哪个读音。🔴 多读音词（`猫`＝ねこ/ねこま）上，义项是分读音的，
  // 不标出来读者不知道哪几条属于哪个音。**单读音词不标**（那是废话不是信息）。
  kana: string | null;
  // 伞形标题（`sense_gloss.kind='umbrella'`）：`西` 的「歌舞伎中」统辖两条义项。
  // 🔴 它**不是这条义项的释义** —— SQL 里取 zh/ja/en 时必须把 kind='umbrella'
  //    排除掉，否则同一句话会既当小标题又当释义印两遍（契约闸有这条）。
  umbrella: string | null;
  zh: string | null;        // 中文释义
  ja: string | null;        // 日语原文定义
  en: string | null;        // 英文对应词
  pos: string | null;
  // ── 义项标签（`sense_tag`，阶段 1d）。五个桶分开给，展示层各有各的画法 ──
  // 🔴 **`usage` 是 ja 第一个用的桶**：拟声拟态词 633 条混进 register
  //    会被「口语」「俚语」淹掉，而那是日语的显著特征。
  topics: string[];
  registers: string[];
  regions: string[];
  grammar: string[];
  usage: string[];
  relations: JapaneseRelationGroup[];
  altOf: JapaneseAltOf[];
};

// 汉字的音訓読み（`kanji_reading`，阶段 4c）。**字的属性，不是词的属性** ——
// 所以它与 `readings`（词的读音）分开：`青` 作为词读 あお，作为**字**读
// ショウ(呉音)／セイ(漢音)／チン・シイ(唐音)／あお・あお-い(訓)／あをし(古訓)。
// 🔴 `kanaStem`/`okurigana` 是拆开的两段：`い-きる` 里只有 `い` 是这个字的读音，
//    `きる` 是送假名。合成一串印出来就把「字读什么」和「词读什么」混回去了。
export type JapaneseKanjiReading = {
  kana: string;             // 原样，含连字符（あお-い）
  kanaStem: string;         // 字本身的读音（あお）
  okurigana: string | null; // 送假名（い）
  kind: string;             // on / kun / nanori
  subkind: string | null;   // go-on / kan-on / to-on / kan-yo-on / ko-kun
  isJoyo: boolean;          // 该读音在常用汉字表内
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
  /** 词源正文全文，键＝`${edition}:${etym_no}`。**服务层端全文**，
   *  页面只印 `etymologyBrief()` 切的第一句 —— 改「印几句」不该回头重抽数据。 */
  etymologyTexts: Record<string, string>;
  /** 抽过哪些维基版。**没抽过的版，组件必须闭嘴**：把「我们没抽」
   *  说成「源头没写」是造假，比缺更伤权威。 */
  etymologyEditions: string[];
  readings: JapaneseReading[];
  // 🔴 与 `readings` 分开的理由见 `JapaneseKanjiReading`：一个是**词**怎么念，
  //    一个是**字**怎么念。只有汉字条目有，普通词恒为空数组。
  kanjiReadings: JapaneseKanjiReading[];
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
  // ⚠️ `labels` 是**复数**：`食べられます` 对 `食べる` 同时是被动敬体和可能敬体。
  //    服务层原来 `MIN(label_zh)` 只留一个，9.0% 的组合被静默压掉了。
  //    `romaji` 是这个**词形**的转写（源头把它和词形写在同一个单元格里，
  //    阶段 2 拆开存进 `inflection.romaji`），活用形页的读音药丸靠它。
  bases: Array<{ word: string; labels: string[]; romaji: string | null;
                 clickable: boolean }>;
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

/** 声调标记 / 罗马字 → 可比对的骨架。**重建（2026-09-18），见文件头。**
 *
 * 🔴 用途是**声调归位**：声调来自中文版、挂在 `word_id` 上；IPA 来自英文版、
 *    挂在 `entry` 上 ⇒ 同一个读音被拆在两行。要把声调行并回它属于的那一行。
 * ⭐ **证据在数据里，不是猜**：声调标记 `[néꜜkò]` 本身就是**带调号的罗马字**，
 *    而 `entry.romaji` 是同一套罗马字 ⇒ 去掉调号比对骨架就能定归属。
 * ⚠️ **折长音是为了消除写法差异，不是还原音长**（`bèńkyóó` vs `benkyō`）。
 *    只要两边**对称施加**就安全：`紅色` 的 `kurenaiiro` 两边都折成 `kurenairo`，
 *    照样匹配得上；我们比的是两个骨架相不相等，不是真实发音。
 * ⭐ 实测（重写后复核）：多读音的声调行 1,189 条，**唯一匹配 1,125 ＝ 94.6%**，
 *    零匹配 11、多匹配 53。原注释记的是 1,124 / 1,187 ＝ 94.7%。
 * 🔴 **只有唯一匹配才归位**；零匹配或多匹配一律保持独立行 ——
 *    多读音词上挑一个当宿主＝在页面上断言一件没有证据的事。
 */
export function accentSkeleton(s: string | null): string | null {
  if (!s) return null;
  let t = s.normalize('NFD')
    // 组合调号（grave / acute / macron …）。`ō` 在 NFD 下是 o + U+0304，
    // 剥掉组合记号顺带就把长音符折平了。
    .replace(/[̀-ͯ]/g, '')
    // ꜜ 降位符、重音符、定界符
    .replace(/[ꜜˈˌ'’ʼ[\]\s]/g, '')
    .normalize('NFC')
    .toLowerCase()
    .replace(/[ー-]/g, '');
  t = t.replace(/ou/g, 'o').replace(/ei/g, 'e')
    .replace(/([aiueo])\1+/g, '$1');
  return t || null;
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
  /** 抽过哪些维基版的词源正文。**没抽过的版，展示层必须闭嘴** ——
   *  把「我们没抽」说成「源头没写」就是造假（见 `ingest_etymology.py` 文件头）。 */
  private readonly etymEditions: string[];

  private readonly hasCache: boolean;

  private readonly cacheTopN: number;

  constructor(databasePath: string) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');

    this.q = {
      // ══ 词源正文（2026-09-20）══════════════════════════════════════════
      // 🔴 这一层在 ja 上**整个缺席过**：`scripts/ingest_etymology.py` 2026-09-14
      //    就有，而 ja 09-15 开建却没被加进它的语种名单 —— 库里没有 `etymology` 表，
      //    而「阶段表全 ✅」对**没列进阶段表的层**结构性失明。
      // 🔴 服务层端**全文**，页面只印 `etymologyBrief()` 切出来的第一句：
      //    改「印几句」是展示层的事，不该回头重抽数据。
      etymology: this.db.prepare(`
        SELECT edition, etym_no, text FROM etymology WHERE word_id = ? ORDER BY etym_no
      `),

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

      // 🔴 **`kind <> 'umbrella'` 这三个过滤不能少。** 伞形标题（`西` 的「歌舞伎中」）
      //    和释义住在同一张表、同一个 lang 下，只差 `kind` ——
      //    不过滤就会被当成这条义项的中文释义取出来，于是同一句话
      //    既当小标题印一遍、又当释义印一遍（契约闸「伞形不许同时当成义项释义印一遍」）。
      // ⚠️ 子查询不写 ORDER BY，跟的是主键 `(sense_id, lang, kind, seq)` 的顺序 ⇒
      //    `definition` 排在 `equivalent` 前面。这是 9-16 版就有的行为，别动。
      senses: this.db.prepare(`
        SELECT s.id, s.pos, e.src AS etymSrc, e.etym_no AS etymNo, e.kana AS kana,
               (SELECT text FROM sense_gloss
                 WHERE sense_id = s.id AND lang='zh' AND kind <> 'umbrella') AS zh,
               (SELECT text FROM sense_gloss
                 WHERE sense_id = s.id AND lang='ja' AND kind <> 'umbrella') AS ja,
               (SELECT text FROM sense_gloss
                 WHERE sense_id = s.id AND lang='en' AND kind <> 'umbrella') AS en,
               -- 伞形标题：优先中文，没有才退英文（zh 1,739 条 / en 1,810 条）
               COALESCE(
                 (SELECT text FROM sense_gloss
                   WHERE sense_id = s.id AND lang='zh' AND kind = 'umbrella'),
                 (SELECT text FROM sense_gloss
                   WHERE sense_id = s.id AND lang='en' AND kind = 'umbrella')
               ) AS umbrella
        FROM sense s LEFT JOIN entry e ON e.id = s.entry_id
        WHERE s.word_id = ? AND s.hidden = 0
        ORDER BY e.etym_no, s.rank, s.id
      `),

      // 义项标签（阶段 1d）。一次取全，调用方按 sense_id 分。
      // ⚠️ 走子查询而不是 JOIN entry —— 这张表只按 sense_id 取，别把 entry 乘进来
      //    （量重叠时我就是这么把 379 条数成 586 条的）。
      tags: this.db.prepare(
        'SELECT sense_id, kind, value FROM sense_tag WHERE sense_id IN'
        + ' (SELECT id FROM sense WHERE word_id = ?) ORDER BY kind, value'),

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
      // 🔴 **逐行取回来，不在 SQL 里 `GROUP BY` 压掉标签。**
      //    原来是 `MIN(label_zh)`：`食べられます` 对 `食べる` 同时是**被动敬体**和
      //    **可能敬体**，`MIN` 只留一个 —— 9.0% 的组合被静默压掉，而页面上
      //    看起来完全正常（印出来的那一个是真的，只是不全）。
      //    归并改到 JS 侧做，顺序由这里的 `ORDER BY` 定死，不靠 Map 的插入序碰运气。
      baseOf: this.db.prepare(`
        SELECT i.base, i.label_zh AS label, i.romaji,
               EXISTS(SELECT 1 FROM dict d WHERE d.word = i.base) AS ok
        FROM inflection i WHERE i.word_id = ? ORDER BY i.base, i.id
      `),

      // 汉字音訓読み（阶段 4c）。🔴 **按 `seq` 排，不按 kind 排** —— `seq` 是
      //   源头顺序（音读在前、训读在后），重排等于把辞书的编排意图丢掉；
      //   分区由展示层按 `JA_KANJI_READING_ORDER` 做，两件事。
      kanjiReadings: this.db.prepare(
        'SELECT kana, kana_stem, okurigana, kind, subkind, is_joyo'
        + ' FROM kanji_reading WHERE word_id = ? ORDER BY seq, id'),

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
    // 抽过哪些版 —— **构造时算一次**（小表，不必每开一个词条页查一遍）。
    // ⚠️ 表可能还不存在（这门还没跑 `scripts/ingest_etymology.py`）⇒ 兜到空数组；
    //    空数组的意思是「一版都没抽」，展示层对所有词源块一律闭嘴 —— 那是对的。
    this.etymEditions = (() => {
      try {
        return (this.db.prepare('SELECT DISTINCT edition FROM etymology')
          .all() as Array<{ edition: string }>).map((x) => x.edition);
      } catch { return []; }
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
      const ipa = (r.ipa as string) ?? null;
      const pm = (r.pitch_mark as string) ?? null;
      // 🔴 跳过**三样都没有**的行。`entry` 与 `pronunciation` 是 LEFT JOIN，
      //    汉字词条（`猫`/`桜` 的 `pos='kanji'` 那条）既没有假名也没有音标 ⇒
      //    原来会推进来一条全 null 的读音，渲染成页面顶上**一个空行**。
      //    用户说"乱糟糟"时，页面最上面那道空白就是它。
      if (!kana && !ipa && !pm) continue;
      const key = `${kana}|${ipa ?? ''}|${pm ?? ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      readings.push({
        kana, kanaHist: (r.kana_hist as string) ?? null,
        romaji: (r.romaji as string) ?? null,
        ipa, notation: (r.notation as string) ?? null,
        pitchMark: pm,
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
    // 🔴🔴 **归位规则：先按骨架配，配不上再退回「只有一个读音就并过去」。**
    //    原来只有后半条，多读音词（`猫`＝ねこ/ねこま）上直接放弃，页面变成：
    //        ねこ neko /ne̞ko̞/ ／ ねこま nekoma /ne̞ko̞ma̠/
    //        [néꜜkò] 头高型          ← 孤零零一行，读者不知道它属于哪个读音
    //        /ne̞ko̞/ ／ /ne̞ko̞ma̠/   ← 上面印过一遍的 IPA 又印了一遍
    //    ⭐ 而**证据其实在数据里**：声调标记本身是带调号的罗马字，
    //      与 `entry.romaji` 同一套 ⇒ 去调号比骨架就能定归属（`accentSkeleton`）。
    //    🔴 **只有唯一匹配才归位**：多匹配 53 条、零匹配 11 条一律保持独立行。
    const kanaSet = new Set(readings.map((r) => r.kana).filter(Boolean));
    const onlyKana = kanaSet.size === 1 ? [...kanaSet][0]! : null;
    for (const r of this.q.readingsByWord.all(id) as Array<Record<string, unknown>>) {
      const pm = (r.pitch_mark as string) ?? null;
      const ipa = (r.ipa as string) ?? null;
      // ① 骨架归位：拿声调标记的骨架去找 romaji 骨架相同的读音行。
      //    候选按**读音行**去重 —— `三` 的 romaji 里 `mi`/`mī` 是同一个读音的两种写法，
      //    按字符串去重会把它算成两个候选、白白退化成「多匹配」。
      let host: JapaneseReading | undefined;
      const want = accentSkeleton(pm);
      if (want) {
        const hit = new Map<string, JapaneseReading>();
        for (const x of readings) {
          if (x.kana && accentSkeleton(x.romaji) === want) hit.set(x.kana, x);
        }
        if (hit.size === 1) [host] = [...hit.values()];
      }
      // ② 退回原规则：整个词只有一个假名读音时，声调只可能属于它。
      if (!host && onlyKana) {
        host = readings.find((x) => x.kana === onlyKana
          && (pm ? x.pitchMark === null : true));
      }
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
      // 🔴 同一串 IPA 不许印两遍：中文版与英文版给的常常是同一串，
      //    而它们一个挂 word_id、一个挂 entry_id，`seen` 的键里假名那格不同 ⇒
      //    单靠上面那个 key 挡不住。这里再按「IPA 是否已出现过」查一次。
      if (ipa && readings.some((x) => x.ipa === ipa)) {
        if (!pm) continue;
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

    // ── 义项标签：先按 (sense_id, kind) 归堆 ──
    const tagBy = new Map<number, Record<string, string[]>>();
    for (const t of this.q.tags.all(id) as Array<Record<string, unknown>>) {
      const sid = t.sense_id as number;
      const m = tagBy.get(sid) ?? {};
      (m[t.kind as string] ??= []).push(t.value as string);
      tagBy.set(sid, m);
    }

    // ── 义项 ──
    const senses = (this.q.senses.all(id) as Array<Record<string, unknown>>).map((s) => ({
      id: s.id as number,
      // 🔴 键必须与 `etymology.edition` 逐字一致：ja 走 `has_entry` 那一支，
      //    `ingest_etymology.db_keys()` 取的是 **`entry.src`** ⇒ 这里也取 `e.src`。
      //    ⚠️ 原来只取裸词源号（`'1'`），而 texts 的键是 `'en-edition:1'` ——
      //    **两边各自自洽、拼起来对不上**，页面上一条词源都印不出来而且一声不吭
      //    （`[[correct-steps-can-compose-a-hole]]`）。
      //    ⭐ 实测改前改后**分组数零变化**（214,105 个词条逐个比过），只是键更完整了。
      etymKey: etymKeyOfEntry(s.etymSrc as string | null, s.etymNo as string | null),
      kana: (s.kana as string) ?? null,
      umbrella: (s.umbrella as string) ?? null,
      zh: (s.zh as string) ?? null,
      ja: (s.ja as string) ?? null,
      en: (s.en as string) ?? null,
      pos: (s.pos as string) ?? null,
      topics: tagBy.get(s.id as number)?.topic ?? [],
      registers: tagBy.get(s.id as number)?.register ?? [],
      regions: tagBy.get(s.id as number)?.region ?? [],
      grammar: tagBy.get(s.id as number)?.grammar ?? [],
      usage: tagBy.get(s.id as number)?.usage ?? [],
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
    // 逐行取回来在这里按原形归并 —— 顺序由 SQL 的 ORDER BY 定死，不靠 Map 的插入序碰运气。
    const baseMap = new Map<string, { word: string; labels: string[];
                                      romaji: string | null; clickable: boolean }>();
    for (const b of this.q.baseOf.all(id) as Array<Record<string, unknown>>) {
      const w = b.base as string;
      const cur = baseMap.get(w)
        ?? { word: w, labels: [], romaji: null, clickable: Boolean(b.ok) };
      const lab = (b.label as string) ?? null;
      if (lab && !cur.labels.includes(lab)) cur.labels.push(lab);
      // 转写是**这个词形**的属性，同一个词形的几行给的是同一串 ⇒ 取第一个非空即可
      if (!cur.romaji && b.romaji) cur.romaji = b.romaji as string;
      baseMap.set(w, cur);
    }
    const bases = [...baseMap.values()];

    const audio = (this.q.audio.all(head.word as string) as Array<Record<string, unknown>>)
      .filter((a) => a.url)
      .map((a) => ({
        url: a.url as string, file: a.file as string,
        speaker: (a.speaker as string) ?? null, kind: a.kind as string,
      }));

    return {
      lang: 'ja', id, word: head.word as string,
      etymologyEditions: this.etymEditions,
      // 键＝`${edition}:${etym_no}`，与展示层 `etymKeyOfEntry()` 拼出来的逐字一致
      etymologyTexts: Object.fromEntries(
        (this.q.etymology.all(id) as Array<{ edition: string; etym_no: string; text: string }>)
          .map((x) => [`${x.edition}:${x.etym_no}`, x.text])),
      pos: (head.pos as string) ?? null,
      kanjiGrade: (head.kanji_grade as string) ?? null,
      vclass: ((this.q.vclassOf.get(id) as { vclass?: string } | undefined)
        ?.vclass) ?? null,
      freqZipf: (head.freq_zipf as number) ?? null,
      isLemma: Boolean(head.is_lemma),
      readings,
      kanjiReadings: (this.q.kanjiReadings.all(id) as Array<Record<string, unknown>>)
        .map((k) => ({
          kana: k.kana as string,
          kanaStem: k.kana_stem as string,
          okurigana: (k.okurigana as string) ?? null,
          kind: k.kind as string,
          subkind: (k.subkind as string) ?? null,
          isJoyo: Boolean(k.is_joyo),
        })),
      senses, examples, inflections,
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
