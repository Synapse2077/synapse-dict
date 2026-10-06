// ============================================================================
// 越南语词典服务。2026-10-03（阶段 9）。
//
// ═══ 🔴 六处和前八门不一样，照抄会静默出错 ═══
//
// ① **搜索走 `word_norm`，而 `word_norm` 保留声调。**
//    越南语的声调是**辨义**的（ma 鬼／má 妈／mà 而／mả 坟／mã 马／mạ 秧苗 —— 六个词）。
//    归一若剥掉声调，这六个会折成一个词条。`criteria.norm_vi` 只做
//    NFC ＋ 小写，**不动声调**，回归闸 R4 逐行核「库里的 word_norm 与判据一致」。
//    ⚠️ 所以查询侧要 `normalize('NFC')`：越南语输入法常产出 NFD。
//
// ② **词性读 `entry.pos`（27 种），绝不读 `dict.pos`（494 种）。**
//    `dict.pos` 是**词形级**的斜杠合并串（`noun/unknown`、`verb/noun`，6,749 行带斜杠）。
//    ko 在这件事上栽过：映射表照一列写、展示层读另一列，**双方一致报全绿而徽标全空**。
//
// ③ **音标必须让读者分得出「拼的」和「源头写的」**（欠账 W7）。
//    96,267 行是阶段 3b 按音节拼的（`src` 以 `compose:` 开头）。
//    闸 R13 保证它只填空不覆盖；本文件把 `composed` 端出去，展示层据此加标注。
//    ⚠️ 音标**裸存**（八语种统一约定），加 `/…/` 是展示层的事。
//
// ④ **汉字/喃字表记要带"凭什么"**（欠账 W6）。
//    `rule_ver='codepoint-v1'`（14,327 行）是**按 Unicode 码位区间猜**的，
//    实测只有 **70.8%** 对，且污染单向全在 han 侧。
//    ⇒ 端出 `trusted` 标志，展示层**不许把它印成与权威来源一样的「汉越字」**。
//
// ⑤ **例句的 `ref` 不是译文**（欠账 W10）。
//    vi 版 709 条 `example.translation` 里一条真译文都没有（214 条整串是 `.`，
//    290 条是 `(tục ngữ)`/作者名）⇒ 那批进了 `example.ref`。
//    本文件把 `ref` 端成独立字段，**它的语义是「出处」**，不许排在译文位置。
//
// ⑥ **16,305 个词形唯一的"释义"是一条指针**（欠账 W15）——
//    `UBND = Ủy ban Nhân dân`／`Tobago → alternative form of Tô-ba-gô`。
//    阶段 5a 把指针义项放在证据层（`sense_src.sense_id IS NULL`，闸 E7 守着），
//    出版层因此没有它们。🔴 **源头明明给了内容，而那正是读者要看的那句话。**
//    ⇒ `pointers` 这一路专门取它们；没有可出版义项时展示层印指针。
//    ⚠️ 其中 222 个词形连音标都没有 ＝ 真·空白页，而**它们也全部有指针**
//      （回归闸 R1b：「源头也没给」的是 **0** 个）。
//
// ═══ 🔴🔴 这个文件里**不许在 SQL 模板串的注释里用反引号** ═══
// SQL 串是用反引号界定的模板字符串，注释里再写一个反引号就当场**截断字符串** ——
// tsc 吐一串 TS1005。`korean.ts` 的文件头把这条写了两遍，我照样踩了一次
// （2026-10-03，9 个 TS1005）。⇒ SQL 注释里的标识符一律不加反引号。
//
// ═══ ⚠️ 兜底越体面，缺陷越难发现 ═══
// `[[it-display-layer-stage8]]`：`|| g.kind` 这种兜底会把"缺失的中文名"伪装成英文内容。
// 本文件一律**端出原值 ＋ 一个布尔**，让展示层决定，不在 SQL 里 COALESCE 掉语义。
// ============================================================================
import { DatabaseSync } from 'node:sqlite';
import { dropDuplicatedAtSenseLevel } from './relations.js';

export type VietnameseSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

export type VietnamesePronunciation = {
  ipa: string;
  dialect: string;
  src: string;
  /** 🔴 W7：true ＝ 这条是我们按音节拼的，不是源头写的。 */
  composed: boolean;
};

export type VietnameseSpelling = {
  /** 汉字串本身。 */
  text: string;
  /** 'han' ＝ 汉越字（通用区）／'nom' ＝ 喃字（扩展区）。 */
  script: 'han' | 'nom';
  ruleVer: string;
  /** 🔴 W6：false ＝ 按码位推定，实测只有 70.8% 对，不许印成权威表记。 */
  trusted: boolean;
};

export type VietnameseRelation = {
  senseId: number | null;
  kind: string;
  target: string;
  /** 解析得到的 `dict.id`；null ＝ 库里没这个词形 ⇒ **不许渲染成链接**。 */
  targetId: number | null;
  zh: string | null;
};

export type VietnameseSense = {
  id: number;
  rank: number;
  etymNo: number | null;
  pos: string | null;
  zh: string | null;
  zhSrc: string | null;
  en: string | null;
  vi: string | null;
  /** 🔴 W13：中文释义与本词的汉字表记逐字相同 ⇒ 展示层折叠，**不是隐藏**。 */
  zhSameAsSpelling: boolean;
};

export type VietnameseExample = {
  senseId: number | null;
  text: string;
  /** 🔴 W10：**出处**，不是译文。不许排在译文位置。 */
  ref: string | null;
  zh: string | null;
  en: string | null;
};

/** 🔴 W15：证据层的指针义项（源头给了而出版层没有）。 */
export type VietnamesePointer = {
  lang: string;
  text: string;
  src: string;
  /** 源头 `form_of`/`alt_of` 给的目标词形；源头没给结构字段时是 null。
   *  🔴 **不许在展示层从 `text` 里用正则抠** —— `text` 是自由文本
   *  （`initialism of Hoa Kỳ (= United States): a country in North America: US`）。 */
  target: string | null;
  /** 目标在 `dict` 里才可点。🔴 这是关系层 `targetId` 为 NULL 时的既有约定：
   *  点下去是空白页比不能点更坏（W9 那 2,238 行死链）。 */
  targetId: number | null;
};

export type VietnameseEntryView = {
  pos: string | null;
  etymNo: number | null;
  etymType: string | null;
  src: string;
};

export type VietnameseEntry = {
  id: number;
  word: string;
  isLemma: boolean;
  syllables: number;
  entries: VietnameseEntryView[];
  senses: VietnameseSense[];
  pronunciations: VietnamesePronunciation[];
  spellings: VietnameseSpelling[];
  /** 本词配的量词（`con` 用于动物…）。 */
  classifiers: Array<{ classifier: string; classifierId: number | null; note: string | null }>;
  senseRelations: VietnameseRelation[];
  entryRelations: VietnameseRelation[];
  examples: VietnameseExample[];
  etymologies: Array<{ etymNo: number; text: string; src: string }>;
  audios: Array<{ url: string; dialect: string; commonsKey: string }>;
  /** 🔴 W15：只有在**没有可出版义项**时才该印 —— 展示层据 `senses.length` 判断。 */
  pointers: VietnamesePointer[];
  /** 同一个 `word_norm` 的别的词形（`bắc cực` vs `Bắc Cực`）。1,263 组。 */
  homographs: Array<{ id: number; word: string }>;
};

/** 🔴 NFC：越南语输入法常产出 NFD，长得一样、字节不同、`=` 匹配不上。
 *  ⚠️ **不许在这里剥声调** —— 见文件头①。 */
function normVi(s: string): string {
  return s.normalize('NFC').toLowerCase();
}

export class VietnameseDictService {
  readonly databasePath: string;

  readonly lang = 'vi';

  private readonly db: DatabaseSync;

  private readonly q: Record<string, ReturnType<DatabaseSync['prepare']>>;

  constructor(databasePath: string) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');

    this.q = {
      stats: this.db.prepare(`
        SELECT (SELECT COUNT(*) FROM dict)                             AS total,
               (SELECT SUM(is_lemma) FROM dict)                        AS lemmas,
               (SELECT COUNT(*) FROM sense WHERE hidden = 0)           AS senses,
               (SELECT COUNT(*) FROM example WHERE hidden = 0)         AS examples,
               (SELECT COUNT(*) FROM pronunciation)                    AS pronunciations,
               (SELECT COUNT(*) FROM audio WHERE hidden = 0)           AS audio,
               (SELECT COUNT(*) FROM etymology)                        AS etymologies
      `),

      // 前缀搜索。🔴 **范围查询**不用 LIKE：后者要挡通配符，而加 ESCAPE 会从
      //    索引搜索退化成全表扫（PLAYBOOK 九）。范围查询天然不认通配符。
      // 🔴 pos 取 `entry.pos`（见文件头②）。
      search: this.db.prepare(`
        SELECT d.id, d.word,
               (SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
                 WHERE s.word_id = d.id AND s.hidden = 0 AND g.lang = 'zh'
                 ORDER BY s.rank, s.id LIMIT 1) AS brief,
               (SELECT e.pos FROM entry e WHERE e.word_id = d.id
                 AND e.pos IS NOT NULL AND e.pos <> 'unknown' LIMIT 1) AS pos
        FROM dict d
        WHERE d.word_norm >= ? AND d.word_norm < ?
        ORDER BY d.is_lemma DESC, d.syllables, LENGTH(d.word), d.word
        LIMIT ?
      `),

      // 🔴🔴 **两条，不是一条。** 实测 `word_norm` 有 **1,263 组 / 2,554 行**冲突
      //    （`bắc cực` 北极 ／ `Bắc Cực` 专名 ／ `Bắc cực`；`ca` ／ `Ca` ／ `CA`），
      //    因为 `criteria.norm_vi` 要小写（`[[case-folding-contaminates-columns]]`）。
      //    第一版只有归一那一条 ＋ `.get()`（只取第一行）⇒ 查 `mai`（清晨/梅）
      //    返回的是 `Mai`（姓氏）的内容 —— **1,291 行的页面永远打不开，
      //    而且显示的是别的词的内容**。`[[dict-framework-doc]]`：**错比缺更伤权威。**
      //    ⇒ 原样大小写优先；取不到才落回归一。
      exactWord: this.db.prepare(
        'SELECT id, word, is_lemma AS isLemma, syllables FROM dict WHERE word = ?'),
      exactNorm: this.db.prepare(
        'SELECT id, word, is_lemma AS isLemma, syllables FROM dict WHERE word_norm = ?'
        + ' ORDER BY is_lemma DESC, id'),
      // 同形词（同一个 `word_norm` 的别的行）—— 展示层据此给读者一个出口。
      homographs: this.db.prepare(
        'SELECT id, word FROM dict WHERE word_norm = ? AND id <> ? ORDER BY id'),

      entries: this.db.prepare(`
        -- 🔴 entry.etym_no 存的是 **TEXT**（全库 76,371 行 typeof='text'）⇒
        --    ORDER BY etym_no 是字典序，'10' 会排在 '2' 前面。最大词源号是 13，
        --    有 ≥10 个词源的词形只有 2 个 —— **影响小，但顺序是真的错**。
        SELECT pos, CAST(etym_no AS INTEGER) AS etymNo, etym_type AS etymType, src
        FROM entry WHERE word_id = ? ORDER BY CAST(etym_no AS INTEGER), seq
      `),

      // 🔴 W7：端出 src 让展示层知道哪条是拼的。
      // ⚠️ 排序把**源头写的排在拼的前面**（`src LIKE 'compose:%'` 为真时排后）。
      pronunciations: this.db.prepare(`
        SELECT ipa, dialect, src FROM pronunciation
        WHERE word_id = ? ORDER BY (src LIKE 'compose:%'), dialect, id
      `),

      // 汉越字与喃字**一次取全**，`script` 由来源表决定（不靠码位再猜一遍）。
      spellings: this.db.prepare(`
        SELECT han AS text, 'han' AS script, rule_ver AS ruleVer FROM han_spelling
          WHERE word_id = ?
        UNION ALL
        SELECT nom AS text, 'nom' AS script, rule_ver AS ruleVer FROM nom_spelling
          WHERE word_id = ?
      `),

      // 出版层义项。🔴 `hidden = 0`：186 条被 W12 判掉的（纯标点／词典标记缩写）不出版。
      senses: this.db.prepare(`
        -- 🔴 **这里原来写的是 COALESCE(e.pos,'')，那正是本文件头警告的"体面兜底"。**
        --    实测 102,487 条可出版义项里 **9,116（8.9%）** 的 entry_id IS NULL
        --    （zh 版 4,835 ／ vi 版 4,281）—— 它们真的取不到词性。
        --    折成 '' 之后，「没有 entry」和「entry 说 unknown」在调用方眼里一模一样。
        --    ⇒ 留 NULL，让展示层分得开（[[it-display-layer-stage8]]：
        --      兜底越体面，缺陷越难发现）。
        SELECT s.id, s.rank, CAST(e.etym_no AS INTEGER) AS etymNo, e.pos AS pos,
               (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='zh'
                 ORDER BY id LIMIT 1) AS zh,
               (SELECT src  FROM sense_gloss WHERE sense_id = s.id AND lang='zh'
                 ORDER BY id LIMIT 1) AS zhSrc,
               (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='en'
                 ORDER BY id LIMIT 1) AS en,
               (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='vi'
                 ORDER BY id LIMIT 1) AS vi
        FROM sense s LEFT JOIN entry e ON e.id = s.entry_id
        WHERE s.word_id = ? AND s.hidden = 0
        ORDER BY CAST(e.etym_no AS INTEGER), s.rank, s.id
      `),

      // 关系。一次取全，调用方按 senseId 分义项级/词级。
      // 🔴 链接走 `target_id`（建库时解析好的），不在这里拿 target 去比 word_norm。
      relations: this.db.prepare(`
        SELECT r.sense_id AS senseId, r.kind, r.target, r.target_id AS targetId,
               (SELECT g.text FROM sense s2 JOIN sense_gloss g ON g.sense_id = s2.id
                 WHERE s2.word_id = r.target_id AND g.lang='zh' AND s2.hidden = 0
                 ORDER BY s2.rank LIMIT 1) AS zh
        FROM sense_relation r
        WHERE r.word_id = ? AND r.hidden = 0
        ORDER BY r.kind, r.id
      `),

      classifiers: this.db.prepare(`
        SELECT classifier, classifier_id AS classifierId, note
        FROM noun_classifier WHERE word_id = ? ORDER BY id
      `),

      // 🔴 W10：`ref` 是**出处**。端成独立字段，与译文分开。
      // 🔴🔴 W16：读的是 `text_pub`（**出版正文**），不是 `text`（证据层）。
      //    fr 版是一部越→法双语词典，它的例句一格里装着「越南语搭配 : 法语释义」：
      //        Nắng to : il fait grand soleil.
      //    法语是**那一版的释义语言**，三语方针（中＋英＋越）说页面上不该有它，
      //    而它在 `example_gloss` 里没有家（那张表只收三语）⇒ 只能留在 `text` 里。
      //    用户 2026-10-05 定的口径：**页面不印、证据层原样保留**。52 条。
      // ⚠️ **不许写 `COALESCE(x.text_pub, x.text)`。** 那是本仓库反复栽的「体面兜底」
      //    （`[[it-display-layer-stage8]]`：`|| g.kind` 把缺失的中文名伪装成英文内容）——
      //    重建时忘填这一列，兜底会让页面看起来完全正常，而我们永远发现不了。
      //    回归闸 **P17** 查「可出版行的 `text_pub` 全部非空」，忘填就判红。
      examples: this.db.prepare(`
        SELECT x.sense_id AS senseId, x.text_pub AS text, x.ref,
               (SELECT text FROM example_gloss WHERE example_id = x.id AND lang='zh') AS zh,
               (SELECT text FROM example_gloss WHERE example_id = x.id AND lang='en') AS en
        FROM example x
        WHERE x.word_id = ? AND x.hidden = 0
        ORDER BY x.sense_id IS NULL, x.id
      `),

      etymologies: this.db.prepare(`
        SELECT CAST(etym_no AS INTEGER) AS etymNo, text, src FROM etymology
        WHERE word_id = ? ORDER BY CAST(etym_no AS INTEGER), id
      `),

      audios: this.db.prepare(`
        SELECT url, dialect, commons_key AS commonsKey FROM audio
        WHERE word_id = ? AND hidden = 0 ORDER BY id
      `),

      // 🔴 W15：证据层的指针义项。**只在没有可出版义项时才印**（调用方判断）。
      // 🔴🔴 **`ptr_class = 'pointer'` 这一条是 W15 的真修复。**
      //    第一版没有它 ⇒ 读者在「这个词形指向」标题下看到的 17,418 行里
      //    **13,887 条（79.7%）整段只是这个词自己的汉字表记**（`nhất vị` → `一味`），
      //    而同一页上方已经有「汉字表记」区印着同一串字。
      //    ⭐ 那是 W2 的病在第三个地方复发（义项释义 / 词源正文 / 指针区），
      //      判据 `criteria.pointer_class()`，派生列 `sense_src.ptr_class`。
      // 🔴 `LEFT JOIN` 不是 `JOIN`：目标不在 `dict` 里时**仍然要印这一行**
      //    （照原文印成纯文本），只是不可点 —— 丢掉它等于把源头说过的话吞掉。
      pointers: this.db.prepare(`
        SELECT s.lang, s.text, s.src, s.pointer_target AS target, d.id AS targetId
        FROM sense_src s
        LEFT JOIN dict d ON d.word = s.pointer_target
        WHERE s.word_id = ? AND s.sense_id IS NULL AND s.ptr_class = 'pointer'
        ORDER BY s.id
      `),
    };
  }

  /** 🔴 `closeAllServices()` 会调它 —— 没有这个方法会在**运行时**炸，
   *  而 TS 的联合类型只在把本类加进 `DictService` 之后才查得出来。 */
  close(): void { this.db.close(); }

  getStats() { return this.q.stats.get() as Record<string, number>; }

  search(prefix: string, limit = 30): VietnameseSearchItem[] {
    const p = normVi(prefix.trim());
    if (!p) return [];
    return this.q.search.all(p, `${p}￿`, Math.max(1, Math.min(limit, 100))) as
      unknown as VietnameseSearchItem[];
  }

  getEntry(word: string): VietnameseEntry | null {
    const raw = word.trim();
    type Hit = { id: number; word: string; isLemma: number; syllables: number };
    // 🔴 原样大小写优先 —— 见 `exactWord` 的注释（1,263 组同形冲突）。
    let hit = this.q.exactWord.get(raw) as Hit | undefined;
    if (!hit) {
      const cands = this.q.exactNorm.all(normVi(raw)) as unknown as Hit[];
      if (!cands.length) return null;
      [hit] = cands;
    }
    const id = hit.id;

    const spellRows = this.q.spellings.all(id, id) as unknown as
      Array<{ text: string; script: 'han' | 'nom'; ruleVer: string }>;
    // 🔴 W6：`trusted` 在这里算一次，判据**只有 `dict-labels` 一个家** ——
    //    不在本文件再抄一份码位规则（`[[refactor-mindset-code-quality]]`）。
    const spellings: VietnameseSpelling[] = spellRows.map((r) => ({
      ...r,
      trusted: r.ruleVer !== 'codepoint-v1',
    }));
    const spellTexts = spellings.map((s) => s.text);

    const senseRows = this.q.senses.all(id) as unknown as
      Array<Omit<VietnameseSense, 'zhSameAsSpelling'>>;
    // 🔴 W13：中文释义与汉字表记逐字相同的 1,183 条 —— 标出来让展示层折叠。
    //    ⚠️ **不是隐藏**：隐藏＝这些词一条中文释义都没有，严格更差。
    const senses: VietnameseSense[] = senseRows.map((s) => ({
      ...s,
      zhSameAsSpelling: !!s.zh && spellTexts.some((t) => t.trim() === s.zh!.trim()),
    }));

    const relRows = this.q.relations.all(id) as unknown as VietnameseRelation[];
    const atSense = relRows.filter((r) => r.senseId !== null);
    const atEntry = relRows.filter((r) => r.senseId === null);

    const pronRows = this.q.pronunciations.all(id) as unknown as
      Array<{ ipa: string; dialect: string; src: string }>;

    return {
      id,
      word: hit.word,
      isLemma: !!hit.isLemma,
      syllables: hit.syllables,
      entries: this.q.entries.all(id) as unknown as VietnameseEntryView[],
      senses,
      pronunciations: pronRows.map((r) => ({ ...r, composed: r.src.startsWith('compose:') })),
      spellings,
      classifiers: this.q.classifiers.all(id) as unknown as
        Array<{ classifier: string; classifierId: number | null; note: string | null }>,
      senseRelations: atSense,
      // 🔴🔴 **词条级必须去掉义项级已经印过的**。实测 vi 有 **5,168 组**
      //    同一条 (词, 类型, 目标) 在两边各有一行 ⇒ 不去重，`A Lịch Sơn` 页上
      //    「Alexanđê」会印两遍（`relations.ts` 记的实测：de 24,149／it 9,173／
      //    fr 7,153／en 4,050／es 44／**pt 恰好 0**）。
      //    ⚠️ `[[decision-not-propagated-across-editions]]`：pt 是 0，所以它那套
      //      没去重的写法一直看着是对的 —— 而 ko 那份也没用这个函数。
      //      **照抄 ko 会让 vi 直接中这 5,168 组。**
      entryRelations: dropDuplicatedAtSenseLevel(atEntry, atSense),
      examples: this.q.examples.all(id) as unknown as VietnameseExample[],
      etymologies: this.q.etymologies.all(id) as unknown as
        Array<{ etymNo: number; text: string; src: string }>,
      audios: this.q.audios.all(id) as unknown as
        Array<{ url: string; dialect: string; commonsKey: string }>,
      // 🔴 W15：**一律取回**，由展示层按「有没有可出版义项」决定印不印 ——
      //    在这里按 senses.length 过滤掉的话，调用方就再也不知道它存在
      //    （`[[dont-recast-deliverables-as-junk]]` 的反面：别替调用方把信息丢掉）。
      pointers: this.q.pointers.all(id) as unknown as VietnamesePointer[],
      // 🔴 同形词：`Bắc Cực`（专名）与 `bắc cực`（北极）是**两个词**，
      //    而归一之后它们撞在一起。端出去让展示层给读者一个出口，
      //    否则另外那 1,291 行就只能靠运气被看到。
      homographs: this.q.homographs.all(normVi(hit.word), id) as unknown as
        Array<{ id: number; word: string }>,
    };
  }
}
