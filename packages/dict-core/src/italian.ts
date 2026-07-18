// ============================================================================
// 意大利语词典服务 —— 意语专属，自包含，不引用其它语种（不复用 KaikkiDictService）。
// 读 it/build.py 产出的意语专属 dict 表：把意语本质（助动词 aux、变位类 conj、
// 性别 gender、不规则/异性复数 plural·plural_gender、number_note）作为一等字段返回。
// IPA 已是标准音标（kaikki/规则G2P/豆包三级填充），原样透传，绝不做英语式 normalize。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';

// API 列表项契约（与其它服务结构一致；结构化类型，无需跨语种 import）。
export type ItalianSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

export type ItalianSense = {
  en: string | null;        // 英文 gloss 锚点
  zh: string | null;        // 中文释义
  pos: string | null;       // 逐义项词性
  regions: string[];        // 地区（Tuscany / dialectal …）
  registers: string[];      // 语域（literary / colloquial …）
};

export type ItalianCollocation = { text: string; zh: string | null };

// 变位形式指向的原形（连同词义与本质字段，供变位页内联展示）。
export type ItalianBase = {
  word: string;
  pos: string | null;
  ipa: string | null;
  aux: string | null;
  gender: string | null;
  senses: ItalianSense[];
};

export type ItalianEntry = {
  lang: 'it';
  id: number;
  word: string;
  ipa: string | null;
  pos: string | null;
  isLemma: boolean;
  // —— 意语本质（一等字段）——
  aux: string | null;           // avere / essere / both（复合时态助动词）
  conj: string | null;          // 1 / 2 / 3 / 3isc（变位类）
  transitivity: string | null;  // t / i / ti
  pronominal: boolean;          // 反身/代词式/procomplementare
  gender: string | null;        // m / f / mf
  plural: string | null;        // 不规则复数形
  pluralGender: string | null;  // 异性复数（braccio→braccia 记 f）
  numberNote: string | null;    // invariable / plural-only / uncountable
  level: string | null;         // CEFR 难度等级 A1-C2（豆包填）
  // —— 释义与关联 ——
  senses: ItalianSense[];
  collocations: ItalianCollocation[];
  baseForms: string[];          // 变位 → 原形（exchange "0:原形"）
  bases: ItalianBase[];         // 原形词连同词义（服务端解析，供内联展示）
  inflNotes: string[];          // 该词形语法说明（infl 列）
  flag: string | null;
};

type ItRow = {
  id: number;
  word: string;
  ipa: string | null;
  pos: string | null;
  is_lemma: number;
  aux: string | null;
  conj: string | null;
  transitivity: string | null;
  pronominal: number | null;
  gender: string | null;
  plural: string | null;
  plural_gender: string | null;
  number_note: string | null;
  level: string | null;
  definition: string | null;
  translation: string | null;
  meta: string | null;
  infl: string | null;
  exchange: string | null;
  collocation: string | null;
  flag: string | null;
};

// kaikki/维基 IPA → 意大利本土词典标准（显示层规范化，与英语 normalizePronunciation 同一定位）。
// DB 内存的是精确的维基式源 IPA（含连结弧/音节点/双写长辅音）；对外读取时统一转本土写法：
//   ① 去连结弧 t͡ʃ→tʃ  ② 固有长辅音 ʎ/ɲ/ʃ 元音间恒长 → 单写（不双写不加 ː）
//   ③ 真双辅音(双写字母)→ 长音符 ː（gatto ˈɡatːo；塞擦音 braccio ˈbratːtʃo=闭塞tː+释放tʃ）
//   ④ 去音节点  ⑤ 开/闭元音 ɛ/ɔ 保留
// 例：/ˈbrat.t͡ʃo/→/ˈbratːtʃo/、/ˈfiʎ.ʎo/→/ˈfiʎo/、/adˈd͡zɔ.to/→/aˈdːdzɔto/
function normalizeItalianIpa(ipa: string | null): string | null {
  if (!ipa) return ipa;
  const s = ipa.trim();
  let inner = s.startsWith('/') && s.endsWith('/') ? s.slice(1, -1) : s;
  inner = inner.replace(/͡/g, '');                     // ① 去连结弧
  // ② 固有长 ʎ ɲ ʃ（先处理，免得被当普通双辅音加 ː）
  inner = inner.replace(/([ʎɲʃ])ˈ\1/gu, 'ˈ$1');            // 跨重音
  inner = inner.replace(/([ʎɲʃ])[.ˌ]\1/gu, '$1');          // 跨点/次重音
  // ③a 塞擦音长音：塞音 + 边界 + 塞擦音 → 塞音ː + 塞擦音（跨重音时重音移到长辅音前）
  inner = inner.replace(/([td])ˈ(t[ʃs]|d[ʒz])/gu, 'ˈ$1ː$2');
  inner = inner.replace(/([td])[.ˌ](t[ʃs]|d[ʒz])/gu, '$1ː$2');
  // ③b 普通双辅音：C + 边界 + 同 C → Cː
  inner = inner.replace(/([bdfɡklmnprstv])ˈ\1/gu, 'ˈ$1ː');
  inner = inner.replace(/([bdfɡklmnprstv])[.ˌ]\1/gu, '$1ː');
  inner = inner.replace(/\./g, '');                          // ④ 去剩余音节点
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

// 搭配存 "意语短语 中文"；从首个 CJK 字符处切分（意语部分可含空格）。
function parseCollocations(raw: string | null): ItalianCollocation[] {
  return splitLines(raw).map((line) => {
    const m = line.match(/^(.+?)\s+([一-鿿　-〿＀-￯].*)$/);
    if (m) return { text: m[1].trim(), zh: m[2].trim() };
    return { text: line, zh: null };
  });
}

// exchange 每行 "0:原形"，收集去重原形词。
function parseBaseForms(raw: string | null): string[] {
  const out: string[] = [];
  for (const line of splitLines(raw)) {
    const idx = line.indexOf(':');
    const w = (idx >= 0 ? line.slice(idx + 1) : line).trim();
    if (w) out.push(w);
  }
  return [...new Set(out)];
}

function buildSenses(row: ItRow): ItalianSense[] {
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
  const senses: ItalianSense[] = [];
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

function mapEntry(row: ItRow): ItalianEntry {
  return {
    lang: 'it',
    id: row.id,
    word: row.word,
    ipa: normalizeItalianIpa(row.ipa),  // 维基式源 IPA → 本土词典标准（见函数注释）
    pos: row.pos,
    isLemma: row.is_lemma === 1,
    aux: row.aux,
    conj: row.conj,
    transitivity: row.transitivity,
    pronominal: row.pronominal === 1,
    gender: row.gender,
    plural: row.plural,
    pluralGender: row.plural_gender,
    numberNote: row.number_note,
    level: row.level,
    senses: buildSenses(row),
    collocations: parseCollocations(row.collocation),
    baseForms: parseBaseForms(row.exchange),
    bases: [],
    inflNotes: splitLines(row.infl),
    flag: row.flag,
  };
}

export class ItalianDictService {
  readonly databasePath: string;
  readonly lang = 'it';
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
      SELECT id, word, ipa, pos, is_lemma, aux, conj, transitivity, pronominal,
             gender, plural, plural_gender, number_note, level,
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

  search(query: string, limit = 20): ItalianSearchItem[] {
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

  getEntry(word: string): ItalianEntry | null {
    const keyword = word.trim();
    if (!keyword) return null;
    const row = this.exactQuery.get(keyword) as ItRow | undefined;
    if (!row) return null;
    const entry = mapEntry(row);

    // 解析每个原形词义（单层，供变位页内联展示各原形是什么意思）。
    for (const bw of entry.baseForms) {
      if (bw === entry.word) continue;
      const br = this.exactQuery.get(bw) as ItRow | undefined;
      if (!br) continue;
      const bm = mapEntry(br);
      entry.bases.push({
        word: bm.word, pos: bm.pos, ipa: bm.ipa, aux: bm.aux,
        gender: bm.gender, senses: bm.senses,
      });
    }
    return entry;
  }

  close() {
    this.db.close();
  }
}
