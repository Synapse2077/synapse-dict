import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';

// 每门语言走自己的一套服务（注册表是唯一汇合点；语种服务之间互不引用）。
import { ItalianDictService } from './italian.js';
import { SpanishDictService } from './spanish.js';
import { FrenchDictService } from './french.js';
import { PortugueseDictService } from './portuguese.js';
import { GermanDictService } from './german.js';
export * from './italian.js';
export * from './spanish.js';
export * from './french.js';
export * from './portuguese.js';
export * from './german.js';

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

// 跨语言统一的搜索项（列表用）；详情按语言各返回不同 shape（DictionaryEntry / SpanishEntry / ItalianEntry）。
export type SearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

// 英语数据用字面 "\n"、其余语种用真换行——都切开取第一段。
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
// 语言注册表 —— 唯一汇合点。每门语言一套自己的服务，互不引用；加一门新语言：
// 写一个 <lang>.ts（可照 spanish.ts / italian.ts）+ 在此 LANGUAGES 与 getService 各加一行。
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
  { code: 'it', label: 'Italiano', name: '意大利语', speak: 'it-IT' },
  { code: 'fr', label: 'Français', name: '法语', speak: 'fr-FR' },
  { code: 'pt', label: 'Português', name: '葡萄牙语', speak: 'pt-BR' },
  { code: 'de', label: 'Deutsch', name: '德语', speak: 'de-DE' },
  // 后续：no(Norsk/nb-NO)
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

type AnyService = DictionaryService | SpanishDictService | ItalianDictService
  | FrenchDictService | PortugueseDictService | GermanDictService;
const serviceCache = new Map<string, AnyService>();

export function getService(code: string): AnyService {
  const meta = LANGUAGES.find((l) => l.code === code);
  const lang = meta ? code : 'en';
  let svc = serviceCache.get(lang);
  if (!svc) {
    if (lang === 'es') svc = new SpanishDictService(dbPathFor('es'));       // 西语专属服务
    else if (lang === 'it') svc = new ItalianDictService(dbPathFor('it'));  // 意语专属服务
    else if (lang === 'fr') svc = new FrenchDictService(dbPathFor('fr'));   // 法语专属服务
    else if (lang === 'pt') svc = new PortugueseDictService(dbPathFor('pt')); // 葡语专属服务
    else if (lang === 'de') svc = new GermanDictService(dbPathFor('de'));   // 德语专属服务
    else svc = new DictionaryService(dbPathFor('en'));                      // 英语（含未知回退）
    serviceCache.set(lang, svc);
  }
  return svc;
}

export function closeAllServices() {
  for (const svc of serviceCache.values()) svc.close();
  serviceCache.clear();
}
