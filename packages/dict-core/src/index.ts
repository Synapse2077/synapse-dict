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
  qual: string | null;
};

// 译文可信度分级（英语库 stardict.qual 列，2026-07-28 建）。全库 392.9 万条按"经过了什么处理/属于哪个桶"打标，
// 供 UI 分层展示——低可信条目可加角标或折叠，而不是把数据删掉（决策可逆）。
//   core   常用核心成品（5.9 万，抽样真实 bad≈0.02%）
//   judged 逐条 LLM 判过 ok/warn（8.0 万）
//   fixed  本项目重写/回填并抽样验过（58.0 万，抽样 ok 96–99%）
//   good   抽样 bad ≤5%（81.2 万：生物学名/地名人名/领域术语，含 v4-pro 核对判 keep 的 3.5 万）
//   fair   抽样 bad 7–10%（218.8 万：无标记单词/多词短语），可用但非成品
//   low    抽样 bad≈39%（21.1 万）
//          2026-07-30 起 low 的含义收窄了：它不再是"整桶偏脏"，而是**逐条核对时模型明确
//          表示"我不认识这个词"**的那批（另 3.5 万判 keep 的已升 good、16.1 万判 fix 的已重写升 fixed）。
//          → 目前**仅作数据侧标记**，UI 不消费它：给用户看"低可信"提示而拿不出更好的译文，
//            体验比不提示更差。要不要分层展示是未决的产品决策。
export type DictQuality = 'core' | 'judged' | 'fixed' | 'good' | 'fair' | 'low';

export const LOW_CONFIDENCE_QUALITY: readonly DictQuality[] = ['low'];

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
  /** 译文可信度分级；仅英语库有，其他语种为 null。见 DictQuality。 */
  qual: DictQuality | null;
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

type Accent = 'uk' | 'us';

/**
 * Convert Wiktionary strict IPA → teaching-style IPA, **per accent**.
 *
 * 2026-07-30 重制。依据 = 2000 条真实音标送豆包 pro + DeepSeek v4-pro 双盲评审
 * （两家同码 234 条），外加两家对旧规则代码本身的独立评审。两家独立得出同一结论：
 * **英美共用一套规则修不好**，下面标 UK-only / US-only 的都是必须分列的。
 *
 * 旧版「把对的改错了」的四条（A 类 129 条归因：ɾ 95 / ɚɝ 27 / ɛ 22 / ʔ 16 / ɐ 10 / ɨ 6）：
 *   ɾ→r  citing ˈsaɪɾɪŋ 出 ˈsaɪrɪŋ「赛润」——ɾ 是 /t,d/ 的闪音变体，不是通音 r。占 A 类 73%。
 *   ʔ→''  fitty fɪʔi 出 fɪi，整个音节没了——ʔ 是英式 /t/ 的喉塞变体。
 *   ɐ→ə  现代 RP 严式用 ɐ 记 STRUT，映射成 schwa 会把重读读成弱读。
 *   ɚ→ər 用在英式列上会给非儿化音加上不该有的 r（abhorrers 英式原文就带 ɚ）。
 *
 * ⚠️ 有一份 Python 孪生体 `en/ipa_normalize.py`（19 条自检样例，全部取自真实词条）。
 *    改这里必须同步改那边，否则审计工具算出来的「用户看到的音标」是假的。
 */
export function normalizePronunciation(ipa: string | null, accent: Accent = 'uk'): string | null {
  if (!ipa) return ipa;
  let s = ipa
    // 1. Tie-bar affricates（U+0361 上置连弧、U+035C 下置连弧都要管）
    .replace(/t[͜͡]ʃ/g, 'tʃ')
    .replace(/d[͜͡]ʒ/g, 'dʒ')
    .replace(/t[͜͡]s/g, 'ts')
    .replace(/d[͜͡]z/g, 'dz')
    // 2. 上标括号 ⁽ʲ⁾ 与腭化符 ʲ（Kamin-Kashyrskyi 那类外来专名）
    .replace(/⁽[^⁾]*⁾/g, '')
    .replace(/ʲ/g, '')   // ʲ palatalization
    // 3. 去严式变音符
    .replace(/̯/g, '')   // ̯ non-syllabic
    .replace(/̟/g, '')   // ̟ advanced tongue
    .replace(/̥/g, '')   // ̥ devoiced
    .replace(/̈/g, '')   // ̈ centralized
    .replace(/ʰ/g, '')   // ʰ aspiration
    .replace(/̚/g, '')   // ̚ unreleased stop
    .replace(/̃/g, '')   // ̃ nasalization
    .replace(/‿/g, '')   // ‿ liaison
    // 4. 音位级还原：喉塞与闪音都是 /t/ 的变体，不是「无音」、也不是 r
    .replace(/ʔ/g, 't')
    .replace(/ɾ/g, 't')
    .replace(/kç/g, 'k')
    // 5. 双元音异写 → 标准
    .replace(/aj/g, 'aɪ')
    .replace(/æw/g, 'aʊ')
    .replace(/æʊ/g, 'aʊ')
    .replace(/ʌɪ/g, 'aɪ')
    // 6. 非教学用严式符号
    .replace(/ɹ/g, 'r')
    .replace(/ɫ/g, 'l')       // dark l
    .replace(/ɐ/g, 'ʌ')       // 现代 RP 的 STRUT，不是 schwa
    .replace(/ɨ/g, 'ɪ')
    // 7. 成节辅音补 schwa——光删标记会读不出（dirndl ˈdɜːndl̩ → ˈdɜːndl）。
    //    ⚠️ (ə)C̩ 必须先合并，否则 ˈæb.s(ə)n̩s 会出双 schwa。
    .replace(/\(ə\)([lnmr])̩/g, 'ə$1')
    .replace(/([lnmr])̩/g, 'ə$1')
    .replace(/̩/g, '');

  if (accent === 'uk') {
    s = s
      .replace(/ɚ/g, 'ə')            // UK-only 非儿化：不加 r
      .replace(/ɝ/g, 'ɜː')
      .replace(/ɛ/g, 'e')            // UK-only 英式 DJ 记法 DRESS 写 /e/（牛津/朗文英式如此）
      .replace(/a(?![ɪʊ])/g, 'æ')    // UK-only TRAP；⚠️ 排除 aɪ/aʊ，否则劈坏双元音
      // 括号：英式连诵 r 单说不读 → 整个删；保留 yod；保留长音
      .replace(/\([rɹ]\)/g, '')
      .replace(/\(j\)/g, 'j')
      .replace(/\(ː\)/g, 'ː');
  } else {
    s = s
      .replace(/ɚ/g, 'ər')           // US-only 儿化：带 r
      .replace(/ɝ/g, 'ɜr')           //           且不补长音符
      // 括号：美式 r 必读；GA 在 t/d/n/l 后丢 yod；GA 无可选长音
      .replace(/\([rɹ]\)/g, 'r')
      .replace(/\(j\)/g, '')
      .replace(/\(ː\)/g, '');
    // ⚠️ 不动 uː/iː/ɑː：剑桥/朗文的美式 IPA 本来就写 /uː/，
    //    「美式无长短对立」只适用于可选长音 (ː) 那一类。
  }

  return s
    // 8. 其余括号一律拆掉留内容（(ə)(t)(h)…）——取全读形式，对学习者最稳。
    //    严式可选音括号不该透给用户：全库 9,796 条里常用核心就占 4,676。
    .replace(/\(\s*\)/g, '')
    .replace(/\(\s*(.+?)\s*\)/g, '$1')
    .replace(/\./g, '')
    .replace(/ː{2,}/g, 'ː')   // ɝ→ɜː 撞上已有 ː
    // 兜底：源数据里有**括号没闭合**的（academic quarter 的 ˈkwɔːtə(r、unmetamorphized 的 ˈmɔː(r.fə），
    // 上面按 (x) 配对的规则匹配不到，会把裸括号透给用户。这两条应当修数据，
    // 但展示层仍要有兜底——畸形输入不该变成用户看到的乱字符。
    .replace(/[()]/g, '')
    // 9. 合并重复 r。⚠️ 必须在括号拆完之后：旧版放在前面，ˈnʌmbɚ(r) 出 ˈnʌmbər(r)，
    //    注释说这条就是为修重复 r 写的，却因为顺序错而从未生效。
    .replace(/r{2,}/g, 'r')
    .trim();
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// 2026-08-01：数据全部迁到仓库根 `data/`，代码目录下不再存放任何数据字节。
// 位置只在这里和各语种的 paths.py 声明；清单见 data/MANIFEST.md。
//
// 🔴 2026-08-11：`SYNAPSE_DATA_DIR` 不是「可选的方便」，是**打包后唯一可靠的锚**。
//    下面的默认值是从**本源文件的位置**往上数三层推出来的（src → dict-core → packages → 根）。
//    这个推法只在「源码原地跑」时成立：一旦 `npm run build:server` 把整个服务
//    打成 `dist/server.js`，`import.meta.url` 就变成 `<部署目录>/dist/server.js`，
//    往上三层指到一个根本不存在的地方，而症状是「所有语言都不可用」——
//    一条 SQLite 报错都不会有，因为 `availableLanguages()` 用的是 `fs.existsSync`，
//    文件不存在就静默地从列表里消失。
//    ⇒ 部署时**必须**显式给 `SYNAPSE_DATA_DIR`（14 GB 数据本来也不该跟代码放一起）。
//       启动自检 `assertDataDir()` 会在 0 个语种可用时直接拒绝启动并把推算路径打出来。
export function dataDir(): string {
  const override = process.env.SYNAPSE_DATA_DIR;
  return override ? path.resolve(override) : path.resolve(__dirname, '../../../data');
}

const DEFAULT_DB_PATH = path.resolve(dataDir(), 'db/synapse-dict-en.sqlite');

function mapEntry(row: DictionaryRow): DictionaryEntry {
  return {
    lang: 'en',
    id: row.id,
    word: row.word,
    phonetic: row.phonetic,
    phoneticUk: normalizePronunciation(row.phonetic_uk, 'uk'),
    phoneticUs: normalizePronunciation(row.phonetic_us, 'us'),
    // 兜底显示：按取到的是哪一列决定口音，别用同一套规则套两种音
    phoneticDisplay: row.phonetic_uk
      ? normalizePronunciation(row.phonetic_uk, 'uk')
      : normalizePronunciation(row.phonetic_us || row.phonetic, 'us'),
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
    qual: (row.qual as DictQuality | null) ?? null,
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
             collins, oxford, tag, bnc, frq, exchange, detail, audio, qual
      FROM stardict
      WHERE word = ? COLLATE NOCASE
      LIMIT 1
    `);

    // Two-phase search: prefix (uses index) then fuzzy fallback
    this.prefixQuery = this.db.prepare(`
      SELECT id, word, phonetic, phonetic_uk, phonetic_us, definition, translation, pos,
             collins, oxford, tag, bnc, frq, exchange, detail, audio, qual
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
             collins, oxford, tag, bnc, frq, exchange, detail, audio, qual
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

// 大文件不进 git，路径可用 DATABASE_PATH_<CODE> 覆盖（线上 scp 到别处时用）。
export function dbPathFor(code: string): string {
  const override = process.env[`DATABASE_PATH_${code.toUpperCase()}`];
  if (override) return path.resolve(override);
  if (code === 'en') return DEFAULT_DB_PATH;
  return path.resolve(dataDir(), `db/synapse-dict-${code}.sqlite`);
}

// 只暴露 DB 文件确实存在的语言（前端据此渲染切换器）。
// ⚠️ 这里只看**文件在不在**，不看**打不打得开**。文件存在但损坏 / 权限不足 / 是个空文件时，
//    它照样出现在列表里，然后在第一个真实请求上抛异常。要判「能不能真的服务」用 `probeLanguages()`。
export function availableLanguages(): LanguageMeta[] {
  return LANGUAGES.filter((l) => fs.existsSync(dbPathFor(l.code)));
}

export type LanguageProbe = LanguageMeta & {
  ok: boolean;
  /** 该语种词条总数（探活顺带取到，健康检查直接用，不必再查一次）。 */
  rows: number | null;
  /** ok=false 时的原因，给运维看的一句话。 */
  error: string | null;
  path: string;
};

/**
 * 逐语种**真开一次库并跑一条查询**，返回谁能服务、谁不能。启动自检与 /health 共用。
 *
 * 🔴 为什么不能只用 `availableLanguages()`：那是 `fs.existsSync`，
 *    「文件在」和「库能用」是两件事。真实故障形态是——scp 传了一半、
 *    挂载盘掉线后留下 0 字节占位、跑数据脚本时把库锁住、备份还原成了别的 schema。
 *    这几种 `existsSync` 全部返回 true，然后用户在第一个请求上收到 500。
 * ⚠️ 查的是 `sqlite_master` 而不是 `SELECT count(*) FROM <主表>` ——
 *    后者在 114 万行的库上要几十毫秒且随数据长大，探活不该随数据变慢。
 *    行数改用 `max(rowid)` 近似（只读索引末端，O(log n)）。
 *
 * 🔴 主表名**不是每门语言都一样**：英语库是 ECDICT 底座、主表叫 `stardict`，
 *    其余五门是本项目自建的 `dict`。第一版探活把 `dict` 写死，结果启动自检
 *    把好端端的英语库判成「schema 不对」并从可用列表里摘掉 —— 连带把默认语种
 *    从 en 换成了 es。**探活写错造成的假故障，和真故障一样会停服**，
 *    所以这张表跟着 LANGUAGES 走，加语言时必须一起填。
 */
const MAIN_TABLE: Record<string, string> = {
  en: 'stardict',   // ECDICT 底座（见 en/ 目录），与其余语种不同构
  es: 'dict', it: 'dict', fr: 'dict', pt: 'dict', de: 'dict',
};

export function probeLanguages(): LanguageProbe[] {
  return LANGUAGES.map((l) => {
    const p = dbPathFor(l.code);
    const tbl = MAIN_TABLE[l.code] ?? 'dict';
    if (!fs.existsSync(p)) {
      return { ...l, ok: false, rows: null, error: 'DB 文件不存在', path: p };
    }
    let db: DatabaseSync | null = null;
    try {
      db = new DatabaseSync(p, { readOnly: true });
      const t = db.prepare(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?").get(tbl) as
        { name?: string } | undefined;
      if (!t?.name) throw new Error(`库里没有 ${tbl} 表（schema 不对）`);
      const r = db.prepare(`SELECT max(rowid) AS n FROM ${tbl}`).get() as { n: number | null };
      return { ...l, ok: true, rows: r?.n ?? 0, error: null, path: p };
    } catch (e) {
      return { ...l, ok: false, rows: null, error: (e as Error).message.slice(0, 200), path: p };
    } finally {
      try { db?.close(); } catch { /* 探活失败时 close 也可能抛，忽略 */ }
    }
  });
}

// 合成发音的音频目录（`es/pipeline/gen_tts.py` 的产物，与 es/paths.py 的 TTS_OUT 同址）。
// 音频**不进 SQLite**、也不进 git；API 把这个目录静态挂在 /api/audio/<code> 下。
// 目前只有 es 有；其余语种目录不存在 ⇒ 静态挂载会跳过，前端自动落到浏览器 TTS。
export function ttsDirFor(code: string): string {
  const override = process.env[`TTS_PATH_${code.toUpperCase()}`];
  if (override) return path.resolve(override);
  return path.resolve(dataDir(), `tts/${code}`);
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
