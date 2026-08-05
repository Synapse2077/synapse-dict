// ============================================================================
// 西班牙语词典服务 —— 西语专属，自包含，不引用其它语种。
// 数据源为 kaikki.org（Wiktextract），经 es/build.py 产出扁平 `dict` 表；本模块把它读成
// 西语自己的展示 shape：逐义项 中文/英文锚点/词性/性别/地区/语域/数属性，变位经 exchange 反查原形。
// IPA 入库为维基式精确源，读取时经 normalizeSpanishIpa 转 RAE 本土标准（见函数注释）。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';

export type SpanishSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

export type SpanishSense = {
  en: string | null;       // 英文 gloss 锚点
  // 西语单语定义锚点。与 `en` **互斥且互补**：英文版没有的 5.4 万个词条（西语版收进来的
  // 新词）英文释义天生为空，它们的原文证据在这一列。两列并集覆盖 98.2% 的 lemma，
  // 而在 2026-08-04 之前只有 `en` 被读取 ⇒ 三分之一的义项底下是空的。
  es: string | null;
  zh: string | null;       // 中文释义（变位形式时为语法说明）
  pos: string | null;      // 逐义项词性（n/adj/adv/v…；补充义项定不了时为 null）
  gender: string | null;   // f / m / mf / n（仅名词）
  regions: string[];       // 地区（España / México / Argentina …）
  registers: string[];     // 语域（colloquial / vulgar …）
  numbers: string[];       // 数属性（uncountable / plural-only …）
};

export type SpanishCollocation = { text: string; zh: string | null };

// Wikimedia Commons 上的真人录音。**只存 URL 不存字节**：单条 mp3 约 24 KB，
// es 全量 11,094 个文件 ≈ 260 MB，六语种合计 ≈ 36 GB —— 塞进 SQLite 会让
// `dbtool` 每次写库前的全文件备份跟着膨胀，而九成九的文件一辈子不会被请求。
export type SpanishAudio = {
  file: string;
  url: string | null;      // 优先 mp3（浏览器 <audio> 兼容性最好）
  ipa: string | null;      // 这条录音对应哪个读音
  speaker: string | null;
  region: string | null;
  regionSrc: string | null;  // tag(标注) / speaker(按录音人推) / filename
  kind: string;              // human / tts-tool / browser-tts
};

// 变位形式指向的原形（连同其词义，供变位页内联展示）。
export type SpanishBase = {
  word: string;
  pos: string | null;
  phonetic: string | null;
  senses: SpanishSense[];
};

export type SpanishEntry = {
  lang: 'es';
  id: number;
  word: string;
  phonetic: string | null;       // España 半岛标准音（distinción，含 θ）
  phoneticLatam: string | null;  // América 拉美音（seseo，θ→s 规则派生；与半岛同则为 null）
  pos: string | null;
  isLemma: boolean;
  reflexive: boolean;          // 代动词（-arse/-erse/-irse / pronominal）
  // —— 西语本质（一等字段；无 aux，西语复合时态恒用 haber）——
  gender: string | null;       // m / f / mf（el/la）
  plural: string | null;       // 不规则复数（lápiz→lápices；规则 +s 留空）
  feminine: string | null;     // 阴性形（名词 actor→actriz；形容词 rojo→roja）
  conjugation: string | null;  // 1 / 2 / 3（-ar/-er/-ir 三变位类）
  stemChange: string | null;   // 词干变化 e→ie / o→ue / e→i / u→ue（西语招牌）
  pp: string | null;           // 过去分词（不规则 roto/escrito/visto…）
  transitivity: string | null; // t / i / ti
  comparative: string | null;  // 不规则比较级（bueno→mejor）
  level: string | null;        // CEFR A1-C2（豆包）
  senses: SpanishSense[];
  collocations: SpanishCollocation[];
  audios: SpanishAudio[];
  baseForms: string[];         // 变位形式 → 原形词（来自 exchange "0:原形"）
  bases: SpanishBase[];        // 原形词连同其词义（服务端解析，供内联展示）
  inflNotes: string[];         // 该词形的语法说明（来自 infl 列，可多行）
  flag: string | null;
};

type EsRow = {
  id: number;
  word: string;
  phonetic: string | null;
  pos: string | null;
  is_lemma: number;
  reflexive: number | null;
  definition: string | null;
  definition_es: string | null;
  translation: string | null;
  meta: string | null;
  infl: string | null;
  exchange: string | null;
  collocation: string | null;
  flag: string | null;
  gender: string | null;
  plural: string | null;
  feminine: string | null;
  conjugation: string | null;
  stem_change: string | null;
  pp: string | null;
  transitivity: string | null;
  comparative: string | null;
  level: string | null;
};

// América 拉美音（seseo）由半岛音规则派生：所有 θ→s（gracias /ˈɡɾaθjas/→/ˈɡɾasjas/）。
// seseo 是完全规则的音变，无例外，故不入库、显示层派生即可。返回与半岛不同时才有意义。
function seseoLatam(spainIpa: string | null): string | null {
  if (!spainIpa || !spainIpa.includes('θ')) return null;   // 无 θ = 两地同音，不另示
  return spainIpa.replace(/θ/g, 's');
}

// kaikki/维基式 IPA → 西班牙 RAE 本土词典标准（显示层，DB 内仍存精确源）。
// 西语数据本已近 RAE（无音位长辅音 ː、几无音节点，θ/ʝ/ʎ/ɾ/r/x 齐全），只需：
//   去连结弧 t͡ʃ→tʃ、去音节点、去长音符、剥方括号窄式、去升降符 ̝ ̞。
// 例：/ˈmut͡ʃo/→/ˈmutʃo/、/ˈɡɾaθjas/ [ˈɡɾa.θjas]→/ˈɡɾaθjas/、/ˈw̝eb/→/ˈweb/。
// ⭐ ̝(U+031D) 是 kaikki 对西语 /w/ 的约定（hu- 词与字母 w 外来词都写 w̝，库内 1,092 条忠实照存），
//   但对划词用户是噪声 → 只在这层剥，DB 保持与 kaikki 逐字一致。别去库里剥（2026-07-31 试过，踩坑）。
function normalizeSpanishIpa(ipa: string | null): string | null {
  if (!ipa) return ipa;
  let s = ipa.trim();
  const slash = s.match(/\/[^/]*\//);              // 只留音位 /.../，丢方括号窄式
  if (slash) s = slash[0];
  else s = s.replace(/\s*\[[^\]]*\]\s*/g, '').trim();
  s = s.replace(/͡/g, '');                          // 去连结弧
  s = s.replace(/[.ː]/g, '');                        // 去音节点、长音符
  s = s.replace(/[\u031D\u031E]/g, '');              // 去升符 ̝ / 降符 ̞（w̝→w、β̞→β）
  // ⭐ 擦音变体 → 音位（ð→d、β→b、ɣ→ɡ、ŋ→n）。库内约 12,300 行把 [β ð ɣ ŋ] 这些
  //   **同位异音**写进了音位式格子（ˈliβɾo / ˈxuɣo / iŋkonfoɾ…），而同类词的另一批写的
  //   是塞音 —— 纯属内部不一致。2026-07-31 v4-pro 盲测的逐条任务与规则评审**各自独立
  //   指出同一处不一致**（主张的方向相反：一个要删、一个要补），故方向不由判官定，
  //   由本函数既定目标定：RAE 教学式音标写 /b d ɡ n/，不写变体。
  //   同 w̝ 的处理：**只在展示层换，DB 保持与 kaikki 逐字一致**，零风险可回退。
  s = s.replace(/ð/g, 'd').replace(/β/g, 'b')
       .replace(/ɣ/g, 'ɡ').replace(/ŋ/g, 'n');
  return s;
}

// 列表型的列（infl / collocation …）：丢空行没关系。
function splitLines(s: string | null): string[] {
  if (!s) return [];
  return s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
}

// 🔴 义项三列（definition / translation / meta）是**按行号一一对应**的：第 i 行
// 是同一个义项的英文与中文。空行不是噪声，是「这个义项没有英文」的**占位**，
// 丢掉就会让后面所有行整体上移、张冠李戴。
// 2026-08-04 实例：`novia` 的 definition 是 `\n\n\na type of sweet roll`
// （前三条阴性义无英文，第四条才是甜面包卷）。`filter(Boolean)` 把它塌成 1 行后，
// 按下标 zip 的结果是「女朋友 / a type of sweet roll」—— 中英完全对不上。
// 库里是对的、错的是这里，所以修在这一层，不许回头去改数据迁就它。
function splitAligned(s: string | null): string[] {
  if (!s) return [];
  return s.split(/\r?\n/).map((x) => x.trim());
}

function firstLine(s: string | null): string | null {
  if (!s) return null;
  const first = s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)[0];
  return first || null;
}

// 搭配存 "西语短语 中文"；从首个 CJK 字符处切分（西语部分含空格）。
function parseCollocations(raw: string | null): SpanishCollocation[] {
  return splitLines(raw).map((line) => {
    const m = line.match(/^(.+?)\s+([一-鿿　-〿＀-￯].*)$/);
    if (m) return { text: m[1].trim(), zh: m[2].trim() };
    return { text: line, zh: null };
  });
}

// exchange 每行 "0:原形"，收集去重后的原形词。
function parseBaseForms(raw: string | null): string[] {
  const out: string[] = [];
  for (const line of splitLines(raw)) {
    const idx = line.indexOf(':');
    const w = (idx >= 0 ? line.slice(idx + 1) : line).trim();
    if (w) out.push(w);
  }
  return [...new Set(out)];
}

function buildSenses(row: EsRow): SpanishSense[] {
  const defs = splitAligned(row.definition);
  const defsEs = splitAligned(row.definition_es);
  const zhs = splitAligned(row.translation);
  let metaArr: Array<Record<string, unknown>> = [];
  try {
    metaArr = row.meta ? (JSON.parse(row.meta) as Array<Record<string, unknown>>) : [];
  } catch {
    metaArr = [];
  }
  const n = Math.max(defs.length, defsEs.length, zhs.length, metaArr.length);
  const asArr = (v: unknown) => (Array.isArray(v) ? (v as string[]) : []);
  const senses: SpanishSense[] = [];
  for (let i = 0; i < n; i++) {
    const m = metaArr[i] ?? {};
    senses.push({
      // 占位空串要还原成 null，否则会渲染出一行空的英文锚点
      en: defs[i] || null,
      es: defsEs[i] || null,
      zh: zhs[i] || null,
      pos: typeof m.pos === 'string' ? m.pos : null,
      gender: typeof m.g === 'string' ? m.g : null,
      regions: asArr(m.reg),
      registers: asArr(m.lex),
      numbers: asArr(m.num),
    });
  }
  return senses;
}

function mapEntry(row: EsRow): SpanishEntry {
  const phonetic = normalizeSpanishIpa(row.phonetic);   // España 半岛（含 θ）
  return {
    lang: 'es',
    id: row.id,
    word: row.word,
    phonetic,
    phoneticLatam: seseoLatam(phonetic),               // América seseo（θ→s 派生）
    pos: row.pos,
    isLemma: row.is_lemma === 1,
    reflexive: row.reflexive === 1,
    gender: row.gender,
    plural: row.plural,
    feminine: row.feminine,
    conjugation: row.conjugation,
    stemChange: row.stem_change,
    pp: row.pp,
    transitivity: row.transitivity,
    comparative: row.comparative,
    level: row.level,
    senses: buildSenses(row),
    collocations: parseCollocations(row.collocation),
    audios: [],                       // 另表，由 getEntry 填

    baseForms: parseBaseForms(row.exchange),
    bases: [],
    inflNotes: splitLines(row.infl),
    flag: row.flag,
  };
}

export class SpanishDictService {
  readonly databasePath: string;
  readonly lang = 'es';
  private readonly db: DatabaseSync;
  private readonly statsQuery;
  private readonly exactQuery;
  private readonly prefixQuery;
  private readonly audioQuery;

  constructor(databasePath: string) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');

    this.statsQuery = this.db.prepare(`
      SELECT
        COUNT(*) AS total,
        SUM(is_lemma) AS lemmas,
        SUM(CASE WHEN translation IS NOT NULL AND translation != '' THEN 1 ELSE 0 END) AS translated,
        SUM(CASE WHEN phonetic IS NOT NULL AND phonetic != '' THEN 1 ELSE 0 END) AS phonetic
      FROM dict
    `);

    this.exactQuery = this.db.prepare(`
      SELECT id, word, phonetic, pos, is_lemma, reflexive,
             definition, definition_es, translation, meta, infl, exchange, collocation, flag,
             gender, plural, feminine, conjugation, stem_change, pp,
             transitivity, comparative, level
      FROM dict
      WHERE word = ? COLLATE NOCASE
      ORDER BY is_lemma DESC
      LIMIT 1
    `);

    // 前缀检索：命中 word 或 word_norm（去重音，便于无重音输入）；lemma 优先、短词优先。
    this.prefixQuery = this.db.prepare(`
      SELECT id, word, is_lemma, pos, translation, definition
      FROM dict
      WHERE word LIKE ? COLLATE NOCASE OR word_norm LIKE ? COLLATE NOCASE
      ORDER BY
        CASE WHEN lower(word) = lower(?) THEN 0 ELSE 1 END,
        is_lemma DESC,
        LENGTH(word) ASC,
        word ASC
      LIMIT ?
    `);

    // 真人录音。排序即"该先播哪条"：
    //   ① 地区是**标注**的排在**按录音人推**的前面（region_src='tag' 更可信）；
    //   ② 西班牙本土优先 —— 我们的音标展示层默认是半岛音（含 θ），
    //      录音得跟音标对得上，否则用户看着 /θ/ 却听到 /s/；
    //   ③ 其余按地区名稳定排序，保证同一个词每次播的是同一条。
    // ⚠️ 录音实际分布严重偏拉美（委内瑞拉 4,598 + 哥伦比亚 2,769 = 65%，
    //    西班牙仅 1,411），全因 Marreromarco 一人录了 4,597 条。不排序就会默认播拉美音。
    this.audioQuery = this.db.prepare(`
      SELECT file, url_mp3, url_ogg, ipa, speaker, region, region_src, kind
      FROM audio
      WHERE word = ? COLLATE NOCASE
      ORDER BY
        CASE WHEN region = 'Spain' THEN 0 ELSE 1 END,
        CASE WHEN region_src = 'tag' THEN 0 WHEN region_src IS NULL THEN 2 ELSE 1 END,
        region, file
    `);
  }

  getStats() {
    return this.statsQuery.get() as Record<string, number>;
  }

  search(query: string, limit = 20): SpanishSearchItem[] {
    const keyword = query.trim();
    if (!keyword) return [];
    const like = `${keyword}%`;
    const rows = this.prefixQuery.all(like, like, keyword, limit) as Array<{
      id: number; word: string; pos: string | null;
      translation: string | null; definition: string | null;
    }>;
    return rows.map((r) => ({
      id: r.id,
      word: r.word,
      pos: r.pos,
      brief: firstLine(r.translation) || firstLine(r.definition),
    }));
  }

  getEntry(word: string): SpanishEntry | null {
    const keyword = word.trim();
    if (!keyword) return null;
    const row = this.exactQuery.get(keyword) as EsRow | undefined;
    if (!row) return null;
    const entry = mapEntry(row);

    // 解析每个原形的词义（单层，供变位页内联展示各原形分别是什么意思）。
    for (const bw of entry.baseForms) {
      if (bw === entry.word) continue;
      const br = this.exactQuery.get(bw) as EsRow | undefined;
      if (!br) continue;
      const bm = mapEntry(br);
      entry.bases.push({ word: bm.word, pos: bm.pos, phonetic: bm.phonetic, senses: bm.senses });
    }

    const au = this.audioQuery.all(entry.word) as Array<{
      file: string; url_mp3: string | null; url_ogg: string | null;
      ipa: string | null; speaker: string | null; region: string | null;
      region_src: string | null; kind: string;
    }>;
    entry.audios = au.map((r) => ({
      file: r.file,
      url: r.url_mp3 || r.url_ogg,   // mp3 优先：<audio> 对它的兼容性最好
      ipa: r.ipa,
      speaker: r.speaker,
      region: r.region,
      regionSrc: r.region_src,
      kind: r.kind,
    }));
    return entry;
  }

  close() {
    this.db.close();
  }
}
