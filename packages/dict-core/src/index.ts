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

  search(query: string, limit = 20): DictionaryEntry[] {
    const keyword = query.trim();
    if (!keyword) {
      return [];
    }

    const prefixPattern = `${keyword}%`;
    const rows = this.prefixQuery.all(prefixPattern, keyword, limit) as DictionaryRow[];
    return rows.map(mapEntry);
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
