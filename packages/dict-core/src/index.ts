import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';

type DictionaryRow = {
  id: number;
  word: string;
  phonetic: string | null;
  phonetic_uk: string | null;
  phonetic_us: string | null;
  definition: string | null;
  translation: string | null;
  pos: string | null;
  collins: number | null;
  oxford: number | null;
  tag: string | null;
  bnc: number | null;
  frq: number | null;
  exchange: string | null;
  detail: string | null;
  audio: string | null;
};

export type DictionaryEntry = {
  lang: 'en';
  id: number;
  word: string;
  phonetic: string | null;
  phoneticUk: string | null;
  phoneticUs: string | null;
  phoneticDisplay: string | null;
  definition: string | null;
  translation: string | null;
  pos: string | null;
  collins: number | null;
  oxford: number | null;
  tag: string | null;
  bnc: number | null;
  frq: number | null;
  exchange: string | null;
  detail: string | null;
  audio: string | null;
};

export type DictionaryStats = {
  total: number;
  translated: number;
  phoneticUk: number;
  phoneticUs: number;
  definitions: number;
};

// 跨语言统一的搜索项（列表用）；详情按语言各返回不同 shape，见 DictionaryEntry / KaikkiEntry。
export type SearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

// 英语数据用字面 "\n"、Kaikki 系用真换行——都切开取第一段。
function firstLine(s: string | null): string | null {
  if (!s) return null;
  const first = s.split(/\\n|\r?\n/).map((x) => x.trim()).filter(Boolean)[0];
  return first || null;
}

/**
 * Convert Wiktionary strict IPA → dictionary-style IPA (one function for UK & US).
 *
 * Order matters — context-sensitive rules first, then simple replacements.
 */
function normalizePronunciation(ipa: string | null): string | null {
  if (!ipa) return ipa;
  return ipa
    // 1. Remove phonetic diacritics (strict IPA markers not used in teaching)
    .replace(/\u032F/g, '')   // ̯ non-syllabic mark
    .replace(/\u0329/g, '')   // ̩ syllabic mark
    .replace(/\u031F/g, '')   // ̟ advanced tongue
    .replace(/\u0325/g, '')   // ̥ voiceless/devoiced
    .replace(/\u0308/g, '')   // ̈ centralized
    .replace(/\u02B0/g, '')   // ʰ aspiration
    .replace(/\u031A/g, '')   // ̚ unreleased stop (e.g. t̚)
    .replace(/\u0303/g, '')   // ̃ nasalization
    .replace(/\u203F/g, '')   // ‿ liaison mark
    .replace(/ʔ/g, '')        // glottal stop
    .replace(/kç/g, 'k')     // palatalized k → k (but keep standalone ç for loanwords)
    // 2. Tie-bar affricates → simple affricates
    .replace(/t\u0361ʃ/g, 'tʃ')
    .replace(/d\u0361ʒ/g, 'dʒ')
    .replace(/t\u0361s/g, 'ts')
    .replace(/d\u0361z/g, 'dz')
    // 3. Diphthong variant spellings → standard
    .replace(/aj/g, 'aɪ')
    .replace(/æw/g, 'aʊ')
    // 4. ɚ + sonorant consonant → rə + consonant (e.g. ɚn→rən, ɚm→rəm, ɚl→rəl)
    .replace(/ɚ([nml])/g, 'rə$1')
    // 5. ɚ elsewhere → ər (e.g. word-final, before obstruent)
    .replace(/ɚ/g, 'ər')
    // 6. ɝ → ɜːr (stressed r-colored vowel)
    .replace(/ɝ/g, 'ɜːr')
    // 6b. Fix aʊɜːr → aʊər (Wiktionary misuses ɝ in unstressed "our" etc.)
    .replace(/aʊɜːr/g, 'aʊər')
    // 7. ɹ/ɾ → r
    .replace(/ɹ/g, 'r')
    .replace(/ɾ/g, 'r')
    // 8. Minor vowel normalizations
    .replace(/ɐ/g, 'ə')
    .replace(/ɨ/g, 'ɪ')
    .replace(/ɛ/g, 'e')
    // 9. Remove syllable dots
    .replace(/\./g, '')
    // 10. Merge duplicate r (artifact from ɚ→ər + (ɹ)→(r) overlap)
    .replace(/rr/g, 'r')
    // 11. Clean up spaces inside parentheses: (ə ) → (ə)
    .replace(/\(\s*(.+?)\s*\)/g, '($1)');
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_DB_PATH = path.resolve(__dirname, '../../../data/synapse-dict.sqlite');

function mapEntry(row: DictionaryRow): DictionaryEntry {
  return {
    lang: 'en',
    id: row.id,
    word: row.word,
    phonetic: row.phonetic,
    phoneticUk: normalizePronunciation(row.phonetic_uk),
    phoneticUs: normalizePronunciation(row.phonetic_us),
    phoneticDisplay: normalizePronunciation(row.phonetic_uk || row.phonetic_us || row.phonetic),
    definition: row.definition,
    translation: row.translation,
    pos: row.pos,
    collins: row.collins,
    oxford: row.oxford,
    tag: row.tag,
    bnc: row.bnc,
    frq: row.frq,
    exchange: row.exchange,
    detail: row.detail,
    audio: row.audio,
  };
}

export function resolveDatabasePath(customPath?: string) {
  return customPath ? path.resolve(customPath) : DEFAULT_DB_PATH;
}

export class DictionaryService {
  readonly databasePath: string;
  private readonly db: DatabaseSync;
  private readonly statsQuery;
  private readonly exactQuery;
  private readonly prefixQuery;
  private readonly fuzzyQuery;

  constructor(databasePath = DEFAULT_DB_PATH) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(this.databasePath);
    this.db.exec('PRAGMA query_only = ON');

    this.statsQuery = this.db.prepare(`
      SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN translation IS NOT NULL AND translation != '' THEN 1 ELSE 0 END) AS translated,
        SUM(CASE WHEN phonetic_uk IS NOT NULL AND phonetic_uk != '' THEN 1 ELSE 0 END) AS phoneticUk,
        SUM(CASE WHEN phonetic_us IS NOT NULL AND phonetic_us != '' THEN 1 ELSE 0 END) AS phoneticUs,
        SUM(CASE WHEN definition IS NOT NULL AND definition != '' THEN 1 ELSE 0 END) AS definitions
      FROM stardict
    `);

    this.exactQuery = this.db.prepare(`
      SELECT id, word, phonetic, phonetic_uk, phonetic_us, definition, translation, pos,
             collins, oxford, tag, bnc, frq, exchange, detail, audio
      FROM stardict
      WHERE word = ? COLLATE NOCASE
      LIMIT 1
    `);

    // Two-phase search: prefix (uses index) then fuzzy fallback
    this.prefixQuery = this.db.prepare(`
      SELECT id, word, phonetic, phonetic_uk, phonetic_us, definition, translation, pos,
             collins, oxford, tag, bnc, frq, exchange, detail, audio
      FROM stardict
      WHERE word LIKE ? COLLATE NOCASE
      ORDER BY
        CASE WHEN lower(word) = lower(?) THEN 0 ELSE 1 END,
        CASE WHEN frq IS NULL THEN 1 ELSE 0 END,
        frq ASC,
        LENGTH(word) ASC,
        word ASC
      LIMIT ?
    `);

    this.fuzzyQuery = this.db.prepare(`
      SELECT id, word, phonetic, phonetic_uk, phonetic_us, definition, translation, pos,
             collins, oxford, tag, bnc, frq, exchange, detail, audio
      FROM stardict
      WHERE word LIKE ? COLLATE NOCASE AND word NOT LIKE ? COLLATE NOCASE
      ORDER BY
        CASE WHEN frq IS NULL THEN 1 ELSE 0 END,
        frq ASC,
        LENGTH(word) ASC,
        word ASC
      LIMIT ?
    `);
  }

  getStats(): DictionaryStats {
    return this.statsQuery.get() as DictionaryStats;
  }

  search(query: string, limit = 20): SearchItem[] {
    const keyword = query.trim();
    if (!keyword) {
      return [];
    }

    const prefixPattern = `${keyword}%`;
    const rows = this.prefixQuery.all(prefixPattern, keyword, limit) as DictionaryRow[];
    return rows.map((row) => ({
      id: row.id,
      word: row.word,
      pos: row.pos,
      brief: firstLine(row.translation) || firstLine(row.definition),
    }));
  }

  getEntry(word: string): DictionaryEntry | null {
    const keyword = word.trim();
    if (!keyword) {
      return null;
    }

    const row = this.exactQuery.get(keyword) as DictionaryRow | undefined;
    return row ? mapEntry(row) : null;
  }

  close() {
    this.db.close();
  }
}

// ============================================================================
// Kaikki 系词典（es / fr / it / pt / no —— 同一 `dict` schema，build.py 产出）
// 与英语的差异：音标已是标准 IPA，原样透传（绝不套 normalizePronunciation）；
// 释义为逐义项平行数组 definition↔translation↔meta[i]；变位形式经 exchange 指回原形。
// ============================================================================

type KaikkiRow = {
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

export type KaikkiSense = {
  en: string | null;       // 英文 gloss 锚点
  zh: string | null;       // 中文释义（变位形式时为语法说明）
  gender: string | null;   // f / m / mf / n（仅名词）
  regions: string[];       // kaikki 原始地区名
  registers: string[];     // 语域（colloquial / vulgar …）
  numbers: string[];       // 数属性（uncountable / plural-only …）
};

export type KaikkiCollocation = { text: string; zh: string | null };

// 变位形式指向的原形（连同其词义，供变位页内联展示）。
export type KaikkiBase = {
  word: string;
  pos: string | null;
  phonetic: string | null;
  senses: KaikkiSense[];
};

export type KaikkiEntry = {
  lang: string;
  id: number;
  word: string;
  phonetic: string | null;
  pos: string | null;
  isLemma: boolean;
  reflexive: boolean;
  senses: KaikkiSense[];
  collocations: KaikkiCollocation[];
  baseForms: string[];     // 变位形式 → 原形词（来自 exchange "0:原形"）
  bases: KaikkiBase[];     // 原形词连同其词义（服务端解析，供内联展示）
  inflNotes: string[];     // 该词形的语法说明（来自 infl 列，可多行）
  flag: string | null;
};

function splitLines(s: string | null): string[] {
  if (!s) return [];
  return s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
}

// 搭配存储为 "西语短语 中文"；从首个 CJK 字符处切分（西语部分含空格，无法按空格切）。
function parseCollocations(raw: string | null): KaikkiCollocation[] {
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

function mapKaikki(row: KaikkiRow, lang: string): KaikkiEntry {
  const defs = splitLines(row.definition);
  const zhs = splitLines(row.translation);
  let metaArr: Array<Record<string, unknown>> = [];
  try {
    metaArr = row.meta ? (JSON.parse(row.meta) as Array<Record<string, unknown>>) : [];
  } catch {
    metaArr = [];
  }
  const n = Math.max(defs.length, zhs.length, metaArr.length);
  const senses: KaikkiSense[] = [];
  for (let i = 0; i < n; i++) {
    const m = metaArr[i] ?? {};
    const asArr = (v: unknown) => (Array.isArray(v) ? (v as string[]) : []);
    senses.push({
      en: defs[i] ?? null,
      zh: zhs[i] ?? null,
      gender: typeof m.g === 'string' ? m.g : null,
      regions: asArr(m.reg),
      registers: asArr(m.lex),
      numbers: asArr(m.num),
    });
  }
  return {
    lang,
    id: row.id,
    word: row.word,
    phonetic: row.phonetic,               // 原样，不 normalize
    pos: row.pos,
    isLemma: row.is_lemma === 1,
    reflexive: row.reflexive === 1,
    senses,
    collocations: parseCollocations(row.collocation),
    baseForms: parseBaseForms(row.exchange),
    bases: [],   // 由 getEntry 解析填充（mapKaikki 只做单行映射，避免递归）
    inflNotes: splitLines(row.infl),
    flag: row.flag,
  };
}

export class KaikkiDictService {
  readonly databasePath: string;
  readonly lang: string;
  private readonly db: DatabaseSync;
  private readonly statsQuery;
  private readonly exactQuery;
  private readonly prefixQuery;

  constructor(databasePath: string, lang: string) {
    this.databasePath = databasePath;
    this.lang = lang;
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

  search(query: string, limit = 20): SearchItem[] {
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

  getEntry(word: string): KaikkiEntry | null {
    const keyword = word.trim();
    if (!keyword) return null;
    const row = this.exactQuery.get(keyword) as KaikkiRow | undefined;
    if (!row) return null;
    const entry = mapKaikki(row, this.lang);

    // 解析每个原形的词义（单层，供变位页内联展示各原形分别是什么意思）。
    for (const bw of entry.baseForms) {
      if (bw === entry.word) continue;
      const br = this.exactQuery.get(bw) as KaikkiRow | undefined;
      if (!br) continue;
      const bm = mapKaikki(br, this.lang);
      entry.bases.push({ word: bm.word, pos: bm.pos, phonetic: bm.phonetic, senses: bm.senses });
    }
    return entry;
  }

  close() {
    this.db.close();
  }
}

// ============================================================================
// 语言注册表 —— 加一门新语言只需在此加一行（Kaikki 系共用 KaikkiDictService）。
// ============================================================================

export type LanguageMeta = {
  code: string;
  label: string;   // 该语言自称
  name: string;    // 中文名
  speak: string;   // Web Speech 发音 locale
};

export const LANGUAGES: LanguageMeta[] = [
  { code: 'en', label: 'English', name: '英语', speak: 'en-US' },
  { code: 'es', label: 'Español', name: '西班牙语', speak: 'es-ES' },
  // 后续：fr(Français/fr-FR)、it(Italiano/it-IT)、pt(Português/pt-PT)、no(Norsk/nb-NO)
];

const REPO_ROOT = path.resolve(__dirname, '../../..');

// 大文件不进 git，路径可用 DATABASE_PATH_<CODE> 覆盖（线上 scp 到别处时用）。
function dbPathFor(code: string): string {
  const override = process.env[`DATABASE_PATH_${code.toUpperCase()}`];
  if (override) return path.resolve(override);
  if (code === 'en') return DEFAULT_DB_PATH;
  return path.resolve(REPO_ROOT, `${code}/synapse-dict-${code}.sqlite`);
}

// 只暴露 DB 文件确实存在的语言（前端据此渲染切换器）。
export function availableLanguages(): LanguageMeta[] {
  return LANGUAGES.filter((l) => fs.existsSync(dbPathFor(l.code)));
}

const serviceCache = new Map<string, DictionaryService | KaikkiDictService>();

export function getService(code: string): DictionaryService | KaikkiDictService {
  const meta = LANGUAGES.find((l) => l.code === code);
  const lang = meta ? code : 'en';
  let svc = serviceCache.get(lang);
  if (!svc) {
    svc = lang === 'en'
      ? new DictionaryService(dbPathFor('en'))
      : new KaikkiDictService(dbPathFor(lang), lang);
    serviceCache.set(lang, svc);
  }
  return svc;
}

export function closeAllServices() {
  for (const svc of serviceCache.values()) svc.close();
  serviceCache.clear();
}
