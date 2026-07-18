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
  zh: string | null;       // 中文释义（变位形式时为语法说明）
  pos: string | null;      // 逐义项词性（n/adj/adv/v…；补充义项定不了时为 null）
  gender: string | null;   // f / m / mf / n（仅名词）
  regions: string[];       // 地区（España / México / Argentina …）
  registers: string[];     // 语域（colloquial / vulgar …）
  numbers: string[];       // 数属性（uncountable / plural-only …）
};

export type SpanishCollocation = { text: string; zh: string | null };

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
  phonetic: string | null;
  pos: string | null;
  isLemma: boolean;
  reflexive: boolean;          // 代动词（-arse/-erse/-irse / pronominal）
  senses: SpanishSense[];
  collocations: SpanishCollocation[];
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
  translation: string | null;
  meta: string | null;
  infl: string | null;
  exchange: string | null;
  collocation: string | null;
  flag: string | null;
};

// kaikki/维基式 IPA → 西班牙 RAE 本土词典标准（显示层，DB 内仍存精确源）。
// 西语数据本已近 RAE（无音位长辅音 ː、几无音节点，θ/ʝ/ʎ/ɾ/r/x 齐全），只需：
//   去连结弧 t͡ʃ→tʃ、去音节点、去长音符、剥方括号窄式。
// 例：/ˈmut͡ʃo/→/ˈmutʃo/、/ˈɡɾaθjas/ [ˈɡɾa.θjas]→/ˈɡɾaθjas/。
function normalizeSpanishIpa(ipa: string | null): string | null {
  if (!ipa) return ipa;
  let s = ipa.trim();
  const slash = s.match(/\/[^/]*\//);              // 只留音位 /.../，丢方括号窄式
  if (slash) s = slash[0];
  else s = s.replace(/\s*\[[^\]]*\]\s*/g, '').trim();
  s = s.replace(/͡/g, '');                          // 去连结弧
  s = s.replace(/[.ː]/g, '');                        // 去音节点、长音符
  return s;
}

function splitLines(s: string | null): string[] {
  if (!s) return [];
  return s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
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
  const defs = splitLines(row.definition);
  const zhs = splitLines(row.translation);
  let metaArr: Array<Record<string, unknown>> = [];
  try {
    metaArr = row.meta ? (JSON.parse(row.meta) as Array<Record<string, unknown>>) : [];
  } catch {
    metaArr = [];
  }
  const n = Math.max(defs.length, zhs.length, metaArr.length);
  const asArr = (v: unknown) => (Array.isArray(v) ? (v as string[]) : []);
  const senses: SpanishSense[] = [];
  for (let i = 0; i < n; i++) {
    const m = metaArr[i] ?? {};
    senses.push({
      en: defs[i] ?? null,
      zh: zhs[i] ?? null,
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
  return {
    lang: 'es',
    id: row.id,
    word: row.word,
    phonetic: normalizeSpanishIpa(row.phonetic),   // 维基式 → RAE 本土标准
    pos: row.pos,
    isLemma: row.is_lemma === 1,
    reflexive: row.reflexive === 1,
    senses: buildSenses(row),
    collocations: parseCollocations(row.collocation),
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
             definition, translation, meta, infl, exchange, collocation, flag
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
    return entry;
  }

  close() {
    this.db.close();
  }
}
