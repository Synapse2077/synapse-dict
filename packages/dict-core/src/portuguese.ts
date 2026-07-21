// ============================================================================
// 葡萄牙语词典服务 —— 葡语专属，自包含，不引用其它语种（不复用 es/it/fr 服务）。
// 读 pt/build.py 产出的葡语专属 dict 表：把葡语本质作为一等字段返回——
//   · 双读音 ipa_br(巴西 pt-BR) + ipa_pt(欧洲 pt-PT)  ← 葡语灵魂
//   · 动词 vconj(变位类)、transitivity、pronominal、pp(过去分词)；无 aux
//   · 名词/形容词 gender、plural、feminine、comparative
// IPA 入库为维基式精确源；读取时规范化为葡语本土词典标准（去连结弧、去音节点，保留鼻化/双方言标记）。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';

export type PortugueseSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

export type PortugueseSense = {
  en: string | null;
  zh: string | null;
  pos: string | null;
  gender: string | null;    // 逐义项性别（双性名词 rádio m 收音机 / f 镭）
  regions: string[];        // 地区（Brazil / Portugal / dialectal …）
  registers: string[];
};

export type PortugueseCollocation = { text: string; zh: string | null };

export type PortugueseBase = {
  word: string;
  pos: string | null;
  ipaBr: string | null;
  ipaPt: string | null;
  gender: string | null;
  senses: PortugueseSense[];
};

export type PortugueseEntry = {
  lang: 'pt';
  id: number;
  word: string;
  ipaBr: string | null;         // 巴西标准音 pt-BR
  ipaPt: string | null;         // 欧洲标准音 pt-PT
  pos: string | null;
  isLemma: boolean;
  // —— 葡语本质（一等字段；无 aux）——
  vconj: string | null;         // 1 / 2 / 3 / por（变位类）
  transitivity: string | null;  // t / i / ti
  pronominal: boolean;          // 代词式/反身 -se
  pp: string | null;            // 过去分词（规则/长形 ganhado）
  ppShort: string | null;       // particípio duplo 不规则短形（ganho/pago/gasto）
  gender: string | null;        // m / f / mf
  plural: string | null;        // 不规则复数
  feminine: string | null;      // 阴性形（bonito→bonita；ator→atriz）
  comparative: string | null;   // 不规则比较级（bom→melhor）
  adjPos: string | null;        // 形容词位置 pre / post / both（velho amigo / amigo velho）
  government: string | null;    // 动词/形容词介词支配 regência（gostar de、assistir a）
  level: string | null;         // CEFR A1-C2
  senses: PortugueseSense[];
  collocations: PortugueseCollocation[];
  baseForms: string[];
  bases: PortugueseBase[];
  inflNotes: string[];
  flag: string | null;
};

type PtRow = {
  id: number;
  word: string;
  ipa_br: string | null;
  ipa_pt: string | null;
  pos: string | null;
  is_lemma: number;
  vconj: string | null;
  transitivity: string | null;
  pronominal: number | null;
  pp: string | null;
  pp_short: string | null;
  gender: string | null;
  plural: string | null;
  feminine: string | null;
  comparative: string | null;
  adj_pos: string | null;
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

// kaikki/维基 IPA → 葡语本土词典标准（显示层规范化，与英语 normalizePronunciation 同定位）。
// 葡语双方言音位 kaikki 已较规范；读取只做轻量清理：
//   ① 去连结弧 t͡ʃ→tʃ、d͡ʒ→dʒ  ② 去音节点 .  ③ 保留鼻化 ɐ̃/õ/ɐ̃w̃ 与双方言 (ʁ)/(ɾ) 括注
//   ④ 只保留 /音位/ 式，丢弃 [窄式]
// 例：/ˈli.vɾi/→/ˈlivɾi/、/paʁˈt͡ʃi(ʁ)/→/paʁˈtʃi(ʁ)/
function normalizePtIpa(ipa: string | null): string | null {
  if (!ipa) return ipa;
  let s = ipa.trim();
  const slash = s.match(/\/[^/]*\//);
  if (slash) s = slash[0];
  else s = s.replace(/\s*\[[^\]]*\]\s*/g, '').trim();
  let inner = s.startsWith('/') && s.endsWith('/') ? s.slice(1, -1) : s;
  inner = inner.replace(/͡/g, '');   // ① 去连结弧
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

function parseCollocations(raw: string | null): PortugueseCollocation[] {
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

function buildSenses(row: PtRow): PortugueseSense[] {
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
  const senses: PortugueseSense[] = [];
  for (let i = 0; i < n; i++) {
    const m = metaArr[i] ?? {};
    senses.push({
      en: defs[i] ?? null,
      zh: zhs[i] ?? null,
      pos: typeof m.pos === 'string' ? m.pos : null,
      gender: typeof m.g === 'string' ? m.g : null,
      regions: asArr(m.reg),
      registers: asArr(m.lex),
    });
  }
  return senses;
}

function mapEntry(row: PtRow): PortugueseEntry {
  return {
    lang: 'pt',
    id: row.id,
    word: row.word,
    ipaBr: normalizePtIpa(row.ipa_br),
    ipaPt: normalizePtIpa(row.ipa_pt),
    pos: row.pos,
    isLemma: row.is_lemma === 1,
    vconj: row.vconj,
    transitivity: row.transitivity,
    pronominal: row.pronominal === 1,
    pp: row.pp,
    ppShort: row.pp_short,
    gender: row.gender,
    plural: row.plural,
    feminine: row.feminine,
    comparative: row.comparative,
    adjPos: row.adj_pos,
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

export class PortugueseDictService {
  readonly databasePath: string;
  readonly lang = 'pt';
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
        SUM(CASE WHEN ipa_br IS NOT NULL AND ipa_br != '' THEN 1 ELSE 0 END) AS ipaBr
      FROM dict
    `);

    this.exactQuery = this.db.prepare(`
      SELECT id, word, ipa_br, ipa_pt, pos, is_lemma, vconj, transitivity, pronominal,
             pp, pp_short, gender, plural, feminine, comparative, adj_pos, government, level,
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

  search(query: string, limit = 20): PortugueseSearchItem[] {
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

  getEntry(word: string): PortugueseEntry | null {
    const keyword = word.trim();
    if (!keyword) return null;
    const row = this.exactQuery.get(keyword) as PtRow | undefined;
    if (!row) return null;
    const entry = mapEntry(row);

    for (const bw of entry.baseForms) {
      if (bw === entry.word) continue;
      const br = this.exactQuery.get(bw) as PtRow | undefined;
      if (!br) continue;
      const bm = mapEntry(br);
      entry.bases.push({
        word: bm.word, pos: bm.pos, ipaBr: bm.ipaBr, ipaPt: bm.ipaPt,
        gender: bm.gender, senses: bm.senses,
      });
    }
    return entry;
  }

  close() {
    this.db.close();
  }
}
