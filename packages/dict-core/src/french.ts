// ============================================================================
// 法语词典服务 —— 法语专属，自包含，不引用其它语种（不复用 es/it 服务）。
// 读 fr/build.py 产出的法语专属 dict 表：把法语本质（助动词 aux avoir/être、动词组 vgroup、
// 过去分词 pp、及物性、代词式、性别 gender、不规则复数 plural、形容词阴性形 feminine、
// 不变形 invariable）作为一等字段返回。
// IPA 入库为维基式精确源（kaikki 76% + 从 lemma forms 收割 + 豆包兜底）；读取时规范化为
// 法语本土词典标准（normalizeFrenchIpa：去连结弧、去音节点，保留鼻元音/小舌音 ʁ）。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';

// API 列表项契约（与其它服务结构一致；结构化类型，无需跨语种 import）。
export type FrenchSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

export type FrenchSense = {
  en: string | null;        // 英文 gloss 锚点
  zh: string | null;        // 中文释义
  pos: string | null;       // 逐义项词性
  regions: string[];        // 地区（Quebec / Belgium / dialectal …）
  registers: string[];      // 语域（literary / colloquial …）
};

export type FrenchCollocation = { text: string; zh: string | null };

// 变位形式指向的原形（连同词义与本质字段，供变位页内联展示）。
export type FrenchBase = {
  word: string;
  pos: string | null;
  ipa: string | null;
  aux: string | null;
  gender: string | null;
  senses: FrenchSense[];
};

export type FrenchEntry = {
  lang: 'fr';
  id: number;
  word: string;
  ipa: string | null;
  pos: string | null;
  isLemma: boolean;
  // —— 法语本质（一等字段）——
  aux: string | null;           // avoir / être / both（复合时态助动词）
  vgroup: string | null;        // 1 / 2 / 3（动词组）
  transitivity: string | null;  // t / i / ti
  pronominal: boolean;          // 代词式/反身 se laver
  pp: string | null;            // 过去分词 participe passé
  gender: string | null;        // m / f / mf
  plural: string | null;        // 不规则复数形
  feminine: string | null;      // 形容词阴性形（grand→grande）
  invariable: boolean;          // 不变形
  level: string | null;         // CEFR 难度等级 A1-C2（豆包填）
  // —— 释义与关联 ——
  senses: FrenchSense[];
  collocations: FrenchCollocation[];
  baseForms: string[];          // 变位 → 原形（exchange "0:原形"）
  bases: FrenchBase[];          // 原形词连同词义（服务端解析，供内联展示）
  inflNotes: string[];          // 该词形语法说明（infl 列）
  flag: string | null;
};

type FrRow = {
  id: number;
  word: string;
  ipa: string | null;
  pos: string | null;
  is_lemma: number;
  aux: string | null;
  vgroup: string | null;
  transitivity: string | null;
  pronominal: number | null;
  pp: string | null;
  gender: string | null;
  plural: string | null;
  feminine: string | null;
  invariable: number | null;
  level: string | null;
  definition: string | null;
  translation: string | null;
  meta: string | null;
  infl: string | null;
  exchange: string | null;
  collocation: string | null;
  flag: string | null;
};

// kaikki/维基 IPA → 法语本土词典标准（显示层规范化，与英语 normalizePronunciation 同定位）。
// 法语正字法↔发音鸿沟大，音位本身 kaikki 已较规范；对外读取只做轻量清理：
//   ① 去连结弧 t͡ʃ→tʃ、d͡ʒ→dʒ  ② 去音节点 .  ③ 去联诵/次要修饰  ④ 保留鼻元音 ɑ̃ɛ̃ɔ̃œ̃ 与小舌音 ʁ
//   ⑤ 只保留 /音位/ 式，丢弃 [窄式] 变体
// 例：/a.bɔ.ʁe/→/abɔʁe/、/ˈɡʁɑ̃/→/ɡʁɑ̃/、/mɑ̃.ʒe/→/mɑ̃ʒe/
function normalizeFrenchIpa(ipa: string | null): string | null {
  if (!ipa) return ipa;
  let s = ipa.trim();
  // 优先取 /.../ 音位式；无斜杠时去掉 [窄式] 方括号
  const slash = s.match(/\/[^/]*\//);
  if (slash) s = slash[0];
  else s = s.replace(/\s*\[[^\]]*\]\s*/g, '').trim();
  let inner = s.startsWith('/') && s.endsWith('/') ? s.slice(1, -1) : s;
  inner = inner.replace(/͡/g, '');   // ① 去连结弧（tie bar）
  inner = inner.replace(/‿/g, '');   // ③ 去联诵标记 ‿
  inner = inner.replace(/\./g, '');       // ② 去音节点
  inner = inner.trim();
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

// 搭配存 "法语短语 中文"；从首个 CJK 字符处切分（法语部分可含空格）。
function parseCollocations(raw: string | null): FrenchCollocation[] {
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

function buildSenses(row: FrRow): FrenchSense[] {
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
  const senses: FrenchSense[] = [];
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

function mapEntry(row: FrRow): FrenchEntry {
  return {
    lang: 'fr',
    id: row.id,
    word: row.word,
    ipa: normalizeFrenchIpa(row.ipa),   // 维基式源 IPA → 本土词典标准（见函数注释）
    pos: row.pos,
    isLemma: row.is_lemma === 1,
    aux: row.aux,
    vgroup: row.vgroup,
    transitivity: row.transitivity,
    pronominal: row.pronominal === 1,
    pp: row.pp,
    gender: row.gender,
    plural: row.plural,
    feminine: row.feminine,
    invariable: row.invariable === 1,
    level: row.level,
    senses: buildSenses(row),
    collocations: parseCollocations(row.collocation),
    baseForms: parseBaseForms(row.exchange),
    bases: [],
    inflNotes: splitLines(row.infl),
    flag: row.flag,
  };
}

export class FrenchDictService {
  readonly databasePath: string;
  readonly lang = 'fr';
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
      SELECT id, word, ipa, pos, is_lemma, aux, vgroup, transitivity, pronominal,
             pp, gender, plural, feminine, invariable, level,
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

  search(query: string, limit = 20): FrenchSearchItem[] {
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

  getEntry(word: string): FrenchEntry | null {
    const keyword = word.trim();
    if (!keyword) return null;
    const row = this.exactQuery.get(keyword) as FrRow | undefined;
    if (!row) return null;
    const entry = mapEntry(row);

    // 解析每个原形词义（单层，供变位页内联展示各原形是什么意思）。
    for (const bw of entry.baseForms) {
      if (bw === entry.word) continue;
      const br = this.exactQuery.get(bw) as FrRow | undefined;
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
