// ============================================================================
// 德语词典服务 —— 德语专属，自包含，不引用其它语种（不复用 es/it/fr/pt 服务）。
// 读 de/build.py 产出的德语专属 dict 表：把德语本质作为一等字段返回——
//   · 名词 gender(三性 der/die/das)、genitive(属格单数)、plural(复数)
//   · 动词 aux(haben/sein)、praeteritum+partizip2(三基本形式)、vclass(强/弱/混合)、
//         separable+sepPrefix(可分动词)、reflexive(sich)
//   · 形容词 comparative、superlative
// 德语 word 保留原大小写（名词首字母大写＝语义区分）；word_norm 才小写去变音供检索。
// IPA 入库为维基式精确源；读取时规范化为德语本土词典标准（去连结弧/音节点，保留 ʔ/ː/ʁ）。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';

export type GermanSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

export type GermanSense = {
  en: string | null;
  zh: string | null;
  pos: string | null;
  regions: string[];
  registers: string[];
};

export type GermanCollocation = { text: string; zh: string | null };

export type GermanBase = {
  word: string;
  pos: string | null;
  ipa: string | null;
  gender: string | null;
  senses: GermanSense[];
};

export type GermanEntry = {
  lang: 'de';
  id: number;
  word: string;
  ipa: string | null;
  pos: string | null;
  isLemma: boolean;
  // —— 德语本质（一等字段）——
  gender: string | null;        // m / f / n / mf（der/die/das）
  genitive: string | null;      // 属格单数（des Hauses）
  plural: string | null;        // 复数（die Häuser）
  aux: string | null;           // haben / sein / both（完成时助动词）
  praeteritum: string | null;   // 过去式 Präteritum（ging）
  partizip2: string | null;     // 过去分词 Partizip II（gegangen）
  vclass: string | null;        // weak / strong / mixed（可带 ablaut 类号 strong-7）
  separable: boolean;           // 可分动词 trennbar
  sepPrefix: string | null;     // 可分前缀（an/auf/mit…）
  reflexive: boolean;           // 反身 sich
  comparative: string | null;   // 比较级（gut→besser）
  superlative: string | null;   // 最高级（am besten）
  government: string | null;     // 支配 Rektion（helfen +Dat、warten auf +Akk、mit +Dat）
  level: string | null;         // CEFR A1-C2
  senses: GermanSense[];
  collocations: GermanCollocation[];
  baseForms: string[];
  bases: GermanBase[];
  inflNotes: string[];
  flag: string | null;
};

type DeRow = {
  id: number;
  word: string;
  ipa: string | null;
  pos: string | null;
  is_lemma: number;
  gender: string | null;
  genitive: string | null;
  plural: string | null;
  aux: string | null;
  praeteritum: string | null;
  partizip2: string | null;
  vclass: string | null;
  separable: number | null;
  sep_prefix: string | null;
  reflexive: number | null;
  comparative: string | null;
  superlative: string | null;
  government: string | null;
  level: string | null;
  definition: string | null;
  translation: string | null;
  meta: string | null;
  infl: string | null;
  exchange: string | null;
  collocation: string | null;
  flag: string | null;
};

// kaikki/维基 IPA → 德语本土词典标准（显示层规范化）。
//   ① 去连结弧 t͡ʃ→tʃ  ② 去音节点 .  ③ 保留声门塞音 ʔ、长音 ː、小舌 ʁ、鼻化元音
//   ④ 优先取 /音位/ 式；仅有 [窄式] 时保留其内容并转斜杠
// 例：/ˈɡeː.ən/→/ˈɡeːən/、[haʊ̯s]→/haʊ̯s/
function normalizeGermanIpa(ipa: string | null): string | null {
  if (!ipa) return ipa;
  const s = ipa.trim();
  let inner: string;
  const slash = s.match(/\/[^/]*\//);
  if (slash) {
    inner = slash[0].slice(1, -1);
  } else {
    const br = s.match(/\[[^\]]*\]/);
    inner = br ? br[0].slice(1, -1) : s;
  }
  inner = inner.replace(/͡/g, '');   // ① 去连结弧
  inner = inner.replace(/\./g, '');       // ② 去音节点
  inner = inner.trim();
  if (!inner) return null;
  return '/' + inner + '/';
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

function parseCollocations(raw: string | null): GermanCollocation[] {
  return splitLines(raw).map((line) => {
    const m = line.match(/^(.+?)\s+([一-鿿　-〿＀-￯].*)$/);
    if (m) return { text: m[1].trim(), zh: m[2].trim() };
    return { text: line, zh: null };
  });
}

function parseBaseForms(raw: string | null): string[] {
  const out: string[] = [];
  for (const line of splitLines(raw)) {
    const idx = line.indexOf(':');
    const w = (idx >= 0 ? line.slice(idx + 1) : line).trim();
    if (w) out.push(w);
  }
  return [...new Set(out)];
}

function buildSenses(row: DeRow): GermanSense[] {
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
  const senses: GermanSense[] = [];
  for (let i = 0; i < n; i++) {
    const m = metaArr[i] ?? {};
    senses.push({
      en: defs[i] ?? null,
      zh: zhs[i] ?? null,
      pos: typeof m.pos === 'string' ? m.pos : null,
      regions: asArr(m.reg),
      registers: asArr(m.lex),
    });
  }
  return senses;
}

function mapEntry(row: DeRow): GermanEntry {
  return {
    lang: 'de',
    id: row.id,
    word: row.word,
    ipa: normalizeGermanIpa(row.ipa),
    pos: row.pos,
    isLemma: row.is_lemma === 1,
    gender: row.gender,
    genitive: row.genitive,
    plural: row.plural,
    aux: row.aux,
    praeteritum: row.praeteritum,
    partizip2: row.partizip2,
    vclass: row.vclass,
    separable: row.separable === 1,
    sepPrefix: row.sep_prefix,
    reflexive: row.reflexive === 1,
    comparative: row.comparative,
    superlative: row.superlative,
    government: row.government,
    level: row.level,
    senses: buildSenses(row),
    collocations: parseCollocations(row.collocation),
    baseForms: parseBaseForms(row.exchange),
    bases: [],
    inflNotes: splitLines(row.infl),
    flag: row.flag,
  };
}

export class GermanDictService {
  readonly databasePath: string;
  readonly lang = 'de';
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
        SUM(CASE WHEN ipa IS NOT NULL AND ipa != '' THEN 1 ELSE 0 END) AS ipa
      FROM dict
    `);

    this.exactQuery = this.db.prepare(`
      SELECT id, word, ipa, pos, is_lemma, gender, genitive, plural, aux,
             praeteritum, partizip2, vclass, separable, sep_prefix, reflexive,
             comparative, superlative, government, level,
             definition, translation, meta, infl, exchange, collocation, flag
      FROM dict
      WHERE word = ? COLLATE NOCASE
      ORDER BY is_lemma DESC
      LIMIT 1
    `);

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

  search(query: string, limit = 20): GermanSearchItem[] {
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

  getEntry(word: string): GermanEntry | null {
    const keyword = word.trim();
    if (!keyword) return null;
    const row = this.exactQuery.get(keyword) as DeRow | undefined;
    if (!row) return null;
    const entry = mapEntry(row);

    for (const bw of entry.baseForms) {
      if (bw === entry.word) continue;
      const br = this.exactQuery.get(bw) as DeRow | undefined;
      if (!br) continue;
      const bm = mapEntry(br);
      entry.bases.push({
        word: bm.word, pos: bm.pos, ipa: bm.ipa,
        gender: bm.gender, senses: bm.senses,
      });
    }
    return entry;
  }

  close() {
    this.db.close();
  }
}
