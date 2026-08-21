// ============================================================================
// 西班牙语词典服务 —— 西语专属，自包含，不引用其它语种。
// 数据源为 kaikki.org（Wiktextract），经 es/build.py 产出扁平 `dict` 表；本模块把它读成
// 西语自己的展示 shape：逐义项 中文/英文锚点/词性/性别/地区/语域/数属性，变位经 exchange 反查原形。
// IPA 入库为维基式精确源，读取时经 normalizeSpanishIpa 转 RAE 本土标准（见函数注释）。
// ============================================================================

import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
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

// 例句。2026-08-07 接入 —— 库里 50,766 条原文躺了很久，界面一条没显示过。
// `senseId` 已由 `example.src_gloss` × `sense_src.text` 精确匹配挂好（79.0%），
// 所以例句能跟着义项走，而不是笼统堆在词条末尾。
export type SpanishExample = {
  id: number;
  senseId: number | null;
  text: string;                // 西语原句
  zh: string | null;
  ref: string | null;          // 出处（书名/作者/年份）
};

// 词汇关系。源头一直有，2026-08-07 才收进库（`sense_relation` 121,647 条）。
// `target` 是词形原样，**不解析成外键** —— 源头给的可能是短语（`a cuatro pies`）
// 或库里没有的词。`linkable` 告诉前端这个词点得动（实测 90.6% 点得动）。
export type SpanishRelation = {
  senseId: number | null;
  kind: string;                // synonym / antonym / hypernym / hyponym / derived / related …
  target: string;
  tags: string[];
  linkable: boolean;
};

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

// 西语版（es.wiktionary）自己那套单语义项，`sense_es` 表。2026-08-05 补收。
//
// 🔴 **它和 `SpanishSense.es` 不是一回事，别混。**
//   · `SpanishSense.es` 走 `dict.definition_es`，与英文/中文**按行号对齐**，是同一条义项的西语说法；
//   · 这里是西语版**自己的一套义项编号**，与我们的义项切分无关（`hacer` 我们 15 条、它 59 条）。
//   按行号塞进前者会造成系统性错配（放大版的 `novia`），所以另立门户。
// 两者互斥：`definition_es` 有值的词，西语义项已经内联显示了，这里就返回空数组，不重复推给前端。
export type SpanishEsSense = {
  idx: number;
  gloss: string;               // 西语单语定义原文
  posTitle: string | null;     // 西语版语法口径（Sustantivo ambiguo / Verbo transitivo…），比我们的短码细
  tags: string[];
  zh: string | null;           // 中文；补收时留空，翻译那步再填
  // 这条西语义项对应上面 `senses` 的第几条；null = 英文版没有这个义项。
  // 2026-08-06 与翻译同一次调用产出（输入本来就要喂英文义项消歧，只多吐一个下标）。
  // 全库 22.7% 为 null，且分布自洽：「西语义项更多」的词 33.0%、「两边条数相同」仅 5.5%。
  enI: number | null;
};

// 统一义项：`sense` / `sense_gloss` / `sense_tag` 三张表的读出结果。2026-08-07。
//
// 🔴 **它是 `senses` 与 `esSenses` 两者的替代**，不是第三种东西：
//    那两者分别读 `dict` 的行号对齐列和 `sense_es` 表，同一个「锁孔」义在 `ojo` 下
//    出现两次（英文版一次、西语版一次）。新表已按 `en_i` 对齐结果归并（`ojo` 29 → 25），
//    每条义项自带主键，例句/搭配将来可直接挂上去。
//    过渡期两套并存，展示层切过去、验证无误后再删旧的。
//
// ⭐ **`title` 取「最短的那条中文」，与 `kind` 无关。**
//    `kind` 记的是**来源**（从英文对应词翻来 = equivalent、从西语定义翻来 = definition），
//    溯源上自洽，但**不能直接拿来选标题行**：2026-08-07 实测，被判成 definition 的
//    17.2 万条里 56% 本来就 ≤10 字（`妓女` / `污水排水管` / `兰科植物属`），
//    它们就是合格的标题。按 kind 选会漏掉这批，还会误判出「需要再翻译 17 万条」
//    这种三倍于实际的工作量。按长度选是零成本的正确做法。
export type SpanishUnifiedSense = {
  id: number;
  rank: number;
  pos: string | null;
  gender: string | null;
  title: string;               // 标题行：最短的那条中文
  detail: string | null;       // 副行：明显更长的那条中文（没有则 null）
  en: string | null;           // 英文对应词（溯源用）
  es: string | null;           // 西语单语定义（溯源用）
  topics: string[];
  regions: string[];
  registers: string[];
  numbers: string[];
};

// 工具合成发音（Piper），方针④三级兜底「真人 > 工具生成 > 浏览器 TTS」的**中间那级**。
// 真人录音只覆盖 5.5% 的 lemma，这一级把常用词补齐；两级都没有才落到浏览器 TTS。
export type SpanishTts = {
  accent: 'spain' | 'latam';   // 与音标行的「西 / 拉美」两个标签一一对应
  url: string;                 // /api/audio/es/<xx>/<sha1>.m4a
  voice: string;               // 音色标识，换音色后排查用
};

// 音色 → 口音。半岛音只给音标含 θ 的词生成（其余两地读法相同，拉美那份通用）。
const TTS_VOICES: Array<{ tag: string; accent: 'spain' | 'latam'; voice: string }> = [
  { tag: 'mx', accent: 'latam', voice: 'es_MX-claude-high' },
  { tag: 'es', accent: 'spain', voice: 'es_ES-sharvard-medium#0' },
];

// 同形词：拼写只差大小写的另一个词条。2026-08-07 接入。
//
// 🔴 **西语用大小写承载词汇区别**，而查询入口是 `COLLATE NOCASE`（用户不会记得
//    要大写）。库里已有 573 组同形对（`sandwich`/`Sandwich`、`aves`/`Aves`），
//    做完「小写专名与普通名词压成一行」的拆分后会到 ~3,000 组。
//    此前 `exactQuery` 是 `LIMIT 1` —— 输 `sandwich` 只看到「sándwich 的常见误拼」，
//    `Sandwich`（三明治群岛）**完全不可见**。
//
// ⇒ 同页并列显示，像纸质词典的 virgo¹ / Virgo²。左侧结果列表本来就两个都列，
//   问题只在点进详情之后那一页。
export type SpanishHomograph = {
  id: number;
  word: string;
  pos: string | null;
  phonetic: string | null;
  senses: SpanishUnifiedSense[];
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
  examples: SpanishExample[];
  relations: SpanishRelation[];
  audios: SpanishAudio[];
  esSenses: SpanishEsSense[];  // 西语版自有义项组（与 senses 不对齐，独立成块展示）
  unifiedSenses: SpanishUnifiedSense[];  // 新义项层（sense/sense_gloss/sense_tag），取代上面两者
  tts: SpanishTts[];           // 工具合成音（有哪个口音就给哪个，缺的由前端落到浏览器 TTS）
  baseForms: string[];         // 变位形式 → 原形词（来自 exchange "0:原形"）
  bases: SpanishBase[];        // 原形词连同其词义（服务端解析，供内联展示）
  inflNotes: string[];         // 该词形的语法说明（来自 inflection 表，可多行）
  // 反查：以本词为原形的变形形。2026-08-20 加，`inflection.base_id` 建成之后才可能。
  // 主要给 8,075 个**补收的词头**用 —— 源头只有变形页、没有词头页，
  // 我们按证据补了词头但**没有释义**（模型盲推这批生僻词错误率 24–25%，宁可留空白）。
  // 有了这一块，页面至少能回答「这个词长什么样、怎么读、有哪些变形」。
  forms: { word: string; label: string }[];
  homographs: SpanishHomograph[];  // 拼写只差大小写的其他词条（同页并列显示）
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

// 自复不定式的指针文本：`levantar 的 不定式·自复`。**只认这一种**。
// 别扩大到所有指针（`^.+ 的 \S+$`）—— 那样会命中 4,515 条，其中 2,141 条换掉是倒退：
//   han  指针「haber 的 陈述式·现在时·第三人称·复数」，义项中文是「中国的汉族」
//   lean 指针「leer 的 虚拟式…」，义项中文是「一种娱乐性毒品饮料」
//   pula 指针「pulir 的 虚拟式…」，义项中文是「博茨瓦纳的货币单位」
// 这些词**主要就是那个变形**，另一个义项是罕见外来词，指针才是有用的摘要。
// 自复不定式不一样：用户搜 levantarse 要的就是「站起来」，不是「levantar 的 不定式·自复」。
const REFLEXIVE_PTR = /^.+ 的 不定式·自复$/;

// 搜索下拉的摘要。v1 的 `dict.translation` 优先（既有摘要零回归），两种情况例外：
//   ① 该列为空 ⇒ 落到义项层（3,130 条，全是补收的词头和姓氏，原先一片空白）
//   ② 该列首行是**自复不定式指针** ⇒ 用义项中文（2,374 条）
function briefOf(r: { translation: string | null; definition: string | null;
                      sense_zh: string | null }): string {
  const t = firstLine(r.translation);
  if (t && !(REFLEXIVE_PTR.test(t) && r.sense_zh)) return t;
  return r.sense_zh || t || firstLine(r.definition) || '';
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
    collocations: [],                 // 另表，由 getEntry 填
    examples: [],                     // 另表，由 getEntry 填
    relations: [],                    // 另表，由 getEntry 填
    audios: [],                       // 另表，由 getEntry 填
    esSenses: [],                     // 另表，由 getEntry 填
    unifiedSenses: [],                // 另表，由 getEntry 填
    tts: [],                          // 文件系统，由 getEntry 填

    // 🔴 `baseForms` **继续读 `exchange`，不读 `inflection.base`**（2026-08-20）。
    //    这两列不是同一份东西：`build.py:305-330` 对 `exchange` 里的原形做过**人工裁决**
    //    （`fertil`→`fértil` 重指、`azud m`→`azud` 剥英文泄漏、`tú and vos` 当垃圾删掉），
    //    `infl` 行里留的是**未裁决的原字符串**。实测换过去 15,499 个词形会变：
    //    `absconder` 丢掉指向 `esconder` 的链接、`te` 冒出一个点不开的 `tú and vos`。
    //    ⇒ 裁决过的那份才是真值。变形层给的是**结构**（tags / 原文 / base_id），不是原形裁决。
    baseForms: parseBaseForms(row.exchange),
    bases: [],
    inflNotes: [],                    // 另表 `inflection`，由 getEntry 填
    forms: [],                        // 另表 `inflection` 反查，由 getEntry 填
    homographs: [],                   // 另表，由 getEntry 填
    flag: row.flag,
  };
}

export class SpanishDictService {
  readonly databasePath: string;
  readonly lang = 'es';
  private readonly db: DatabaseSync;
  private readonly ttsDir: string;
  private readonly statsQuery;
  private readonly exactQuery;
  private readonly prefixQuery;
  private readonly audioQuery;
  private readonly esSenseQuery;
  private readonly unifiedSenseQuery;
  private readonly unifiedTagQuery;
  private readonly collocationQuery;
  private readonly exampleQuery;
  private readonly relationQuery;
  private readonly homographQuery;
  private readonly inflectionQuery;
  private readonly formsQuery;
  private readonly prefixCacheQuery;

  constructor(databasePath: string, ttsDir?: string) {
    this.databasePath = databasePath;
    // 默认由 DB 路径推出：data/db/synapse-dict-es.sqlite → data/tts/es
    this.ttsDir = ttsDir ?? path.resolve(path.dirname(databasePath), '../tts/es');
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

    // 🔴 排序第一键是**精确大小写命中**，不是 is_lemma。2026-08-06 补收 573 个
    //    大写专名词头之后必须如此：西语靠大小写区分词汇，而这里是 COLLATE NOCASE。
    //
    //      cefalópodo    Adjetivo/Sustantivo    属于头足纲的        （lemma）
    //      cefalópodos   ← 上一条的阳性复数变形                      is_lemma=0
    //      Cefalópodos   Sustantivo propio      头足纲（Cephalopoda） is_lemma=1  ← 新收
    //
    //    只按 `is_lemma DESC` 排，用户查 `cefalópodos`（正文里的复数形）会拿到
    //    **分类单元**那条 —— 569 个词都会这样翻转。同族还有 virgo/Virgo、be/Be、chile/Chile。
    //    先按大小写完全一致排，再按 is_lemma，两条都在时各归各位。
    this.exactQuery = this.db.prepare(`
      SELECT id, word, phonetic, pos, is_lemma, reflexive,
             definition, definition_es, translation, meta, infl, exchange, collocation, flag,
             gender, plural, feminine, conjugation, stem_change, pp,
             transitivity, comparative, level
      FROM dict
      WHERE word = ? COLLATE NOCASE
      ORDER BY
        -- 🔴 第一排序键：**既没有义项、又不是变形形**的行排到最后（2026-08-10）。
        --    大小写拆分（split_case_homographs）把义项挪给了大写专名，留下 858 个
        --    空壳小写行。其中 847 个是**变形形**（cefalópodos 是复数、
        --    estonia 是 estonio 的阴性），空着是对的 —— 界面走 infl/exchange
        --    指针跳原形，绝不能让它们排后面，否则搜 cefalópodos 会返回
        --    分类单元 Cefalópodos，正是下面那条精确大小写规则要防的 bug。
        --    真空壳只有 11 个：arca de la alianza / Imperio romano /
        --    islas Turcas y Caicos 这类多词专名的另一种拼法，没有义项也没有指针，
        --    点进去是一页空的。判据 = 无 sense 且 infl/exchange 皆空。
        CASE WHEN infl IS NULL AND exchange IS NULL
                  AND NOT EXISTS (SELECT 1 FROM sense s WHERE s.word_id = dict.id)
             THEN 1 ELSE 0 END,
        -- 精确大小写命中优先（2026-08-06 为 Cefalópodos/cefalópodos 加）
        CASE WHEN word = ? THEN 0 ELSE 1 END,
        is_lemma DESC
      LIMIT 1
    `);

    // 前缀检索：命中 word 或 word_norm（去重音，便于无重音输入）；lemma 优先、短词优先。
    //
    // 🔴 摘要 `zh` 取自 `sense_gloss`，不再只靠 `dict.translation`（2026-08-10）。
    //    `translation` 是 v1 遗留列，v2 已把释义搬进 `sense_gloss`，词条页早就切过去了，
    //    **只有这里的搜索摘要还在读老列** ⇒ 3,130 个词在下拉列表里是一片空白
    //    （`A`、`AVE`、`API`、几百个姓氏，以及 2026-08-10 补收新建的 872 个词头）。
    //    这 3,130 条 100% 都有义项中文可用，一条都不用重新翻译。
    // ⭐ 不走「把义项中文抄一份回 `dict.translation`」那条路：那是 v2 特意废掉的
    //    按行号对齐的列，抄回去等于数据存两份、再造一次已经咬过三次的契约。
    // ⚠️ 摘要取 **rank 最靠前**那条义项的中文，**不是最短的那条**。
    //    词条页 buildUnified 取最短当 title 是对的 —— 它把最长的一并当 detail 显示，
    //    两条都在。但搜索下拉只显示一条，取最短会挑出边角义项：
    //    搜 A 摘要成了「主教」（国际象棋 alfil），而不是「西班牙语字母表的第一个字母」。
    //    同一条数据、两个场景，判据不能照抄。
    // 🔴 摘要的子查询必须写在**外层**，套在已经 LIMIT 过的结果上（2026-08-10）。
    //    第一版把它放进内层 SELECT ⇒ 前缀 AVE% 匹配上千行，每行都跑一次
    //    sense/sense_gloss 关联，而 LIMIT 20 是最后才截的 ⇒ 搜索 10.4 秒。
    //    挪到外层后只对最终 20 行求值 ⇒ 0.01 秒。
    //    ⚠️ 同一个教训在同一天出现两次（另一次是 relationQuery 用不上 NOCASE 索引）：
    //    O(n) 的子查询乘上"还没截断的行数"，就是 O(n²)。
    this.prefixQuery = this.db.prepare(`
      -- 🔴 写法必须是「**先定位第 1 条义项，再取它的中文**」，不能写成
      --    sense JOIN sense_gloss ... WHERE s.word_id=? AND g.lang='zh'。
      --    后者规划器会从 idx_gloss_lang (lang='zh') 那一头入手，
      --    **扫遍 34 万条中文 gloss**，20 行就是 680 万次 ⇒ 搜索 3–4 秒。
      --    改成先取 sense.id 再按 sense_gloss 主键 (sense_id, lang) 命中 ⇒ 0.028 秒。
      --    EXPLAIN QUERY PLAN 里看 g 那一行走的是哪个索引，是唯一可靠的判据。
      SELECT h.*,
             (SELECT g.text FROM sense_gloss g
              WHERE g.sense_id = (SELECT s.id FROM sense s
                                  WHERE s.word_id = h.id ORDER BY s.rank LIMIT 1)
                AND g.lang = 'zh'
              ORDER BY LENGTH(g.text) LIMIT 1) AS sense_zh
      FROM (
        SELECT id, word, is_lemma, pos, translation, definition
        FROM dict
        WHERE word LIKE ? COLLATE NOCASE OR word_norm LIKE ? COLLATE NOCASE
        ORDER BY
          CASE WHEN lower(word) = lower(?) THEN 0 ELSE 1 END,
          is_lemma DESC,
          LENGTH(word) ASC,
          word ASC
        LIMIT ?
      ) h
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

    // 西语版自有义项。`sense_es.word` 是从 `dict.word` 原样带过来的，用精确匹配即可
    // （查询入口的大小写归一已由 exactQuery 的 COLLATE NOCASE 做过，这里拿到的是库内词形）。
    this.esSenseQuery = this.db.prepare(`
      SELECT idx, gloss, pos_title, tags, zh, en_i
      FROM sense_es
      WHERE word = ?
      ORDER BY idx
    `);

    // 统一义项层。两条查询而非一条 JOIN：义项与释义是 1:N、义项与标签也是 1:N，
    // 一条 JOIN 会把两个 N 乘起来（`ojo` 25 条义项 × 释义 × 标签），
    // 分开取再在内存里拼，行数是加法而不是乘法。
    this.unifiedSenseQuery = this.db.prepare(`
      SELECT s.id, s.rank, s.pos, s.gender, g.lang, g.kind, g.text
      FROM sense s
      JOIN sense_gloss g ON g.sense_id = s.id
      WHERE s.word_id = ?
      ORDER BY s.rank, g.seq
    `);
    // 搭配。2026-08-07 从 `dict.collocation` 那一列拆出来 —— 那一列把西语短语与中文
    // 粘在同一个字符串里，展示层靠「从第一个汉字处切开」的正则分离：
    //   · 实测 **95 条切不开**（`rayos X X射线`：第一个汉字前面是字母不是空格），
    //     用户看到的是整串当西语、中文为空，而且**切分发生在每次渲染时，不留痕迹**
    //   · 🔴 越南语用拉丁字母，找不到「第一个汉字」⇒ 这一列不改就做不了多语言
    this.pronQuery = this.db.prepare(`
      SELECT ipa, region FROM pronunciation
      WHERE word_id = ? AND notation = 'phonemic' AND is_primary = 1
    `);

    // 🔴 2026-08-21 加 hidden 过滤，与 sense_relation 同批：
    //    `hide_relation_colloc_residue` 藏了 6 组重复搭配（en el aire 出现 3 次）
    //    与 11 条关系残渣（barril 的度量衡换算表被切成 cuarto (1 + 1008 barriles)）。
    //    加列不改这里 = 白做 —— it 那轮就是这么栽的，而且脚本的 --verify 还报了绿。
    this.collocationQuery = this.db.prepare(`
      SELECT c.id, c.text, g.text AS zh
      FROM collocation c
      LEFT JOIN collocation_gloss g ON g.collocation_id = c.id AND g.lang = 'zh'
      WHERE c.word_id = ? AND COALESCE(c.hidden, 0) = 0
      ORDER BY c.rank
    `);

    // 例句：`bold`（关键词位置）与 `src_gloss`（源头义项）不推给前端 ——
    // 前者前端还没用上，后者是溯源信息不是展示内容。
    this.exampleQuery = this.db.prepare(`
      SELECT e.id, e.sense_id, e.text, g.text AS zh, e.ref
      FROM example e
      LEFT JOIN example_gloss g ON g.example_id = e.id AND g.lang = 'zh'
      WHERE e.word = ?
      ORDER BY (e.sense_id IS NULL), e.sense_id, e.id
    `);

    // 词汇关系。`linkable` 在 SQL 里判，省得前端为每个 target 再发一次查询。
    this.relationQuery = this.db.prepare(`
      -- 🔴 COLLATE NOCASE 不是放宽判据，是**为了走上索引**（2026-08-10）。
      --    dict 上唯一的词形索引是 idx_word ON dict(word COLLATE NOCASE)；
      --    写成二进制比较 d2.word = r.target 用不上它 ⇒ 每条关系全表扫 113 万行。
      --    mano 有 135 条关系 ⇒ 这一句查询 6.3 秒，整个词条页转圈 5–6 秒。
      --    加上 COLLATE NOCASE 后 0.009 秒（快 850 倍）。
      --    口径也因此与 exactQuery 一致（那里一直是 NOCASE：搜 gracias 命中 Gracias），
      --    可链接数 115 → 116，多出来的正是只差大小写的那一个，点得开。
      -- ⚠️ 这个坑是今天补齐 derived（关系 121,585 → 142,602）之后才暴露的：
      --    以前 mano 只有几条关系，全表扫几次看不出来。O(n²) 要等数据长大才咬人。
      -- ⚠️ 本文件的 SQL 写在模板字符串里，注释中**绝不能出现反引号**（会提前闭合字符串）。
      SELECT r.sense_id, r.kind, r.target, r.tags,
             EXISTS(SELECT 1 FROM dict d2
                    WHERE d2.word = r.target COLLATE NOCASE) AS linkable
      FROM sense_relation r
      WHERE r.word_id = ? AND COALESCE(r.hidden, 0) = 0
      ORDER BY r.kind, r.id
    `);

    // 同形词：拼写 NOCASE 相同、但**不是同一行**的其他词条。
    // 排除自己用 id 而非 word —— 大小写完全相同的两行不存在（word 唯一）。
    this.homographQuery = this.db.prepare(`
      SELECT id, word, pos, phonetic FROM dict
      WHERE word = ? COLLATE NOCASE AND id <> ?
      ORDER BY is_lemma DESC, word
    `);

    this.unifiedTagQuery = this.db.prepare(`
      SELECT t.sense_id, t.kind, t.value
      FROM sense_tag t JOIN sense s ON s.id = t.sense_id
      WHERE s.word_id = ?
    `);

    // 变形层（2026-08-20 建，取代 `dict.infl` 那个多行字符串）。
    // `seq` 就是旧列的行序 —— 排序键换成别的，页面上变形的先后就会变。
    // `base_fixed` 优先于 `base`，`hidden=1` 不渲染 —— 见 fixes/fix_glued_reflexive_base.py。
    // 🔴 修的是**用户看得见的错**：`lo`(zipf 6.89) 的变位形式曾显示
    //    「él and usted 的 宾格」—— wiktextract 把英文粘进了原形，
    //    而这几个词是全词典频次最高的。`base` 列本身不改（它是闸①的参照物）。
    this.inflectionQuery = this.db.prepare(`
      SELECT i.seq, COALESCE(i.base_fixed, i.base) AS base, i.base_id,
             i.label_zh, i.kind, d.word AS base_word
      FROM inflection i LEFT JOIN dict d ON d.id = i.base_id
      WHERE i.word_id = ? AND COALESCE(i.hidden, 0) = 0
      ORDER BY i.seq
    `);

    // 短前缀预计算（2026-08-20，`pipeline/build_search_prefix.py`）。
    // 🔴 `search()` 是**每敲一个字符跑一次**的路径，而 1 字符前缀实测最慢 354ms ——
    //    瓶颈是为了取 20 条把 2–3 万条候选整个排一遍（`LENGTH(word)` 与
    //    `lower(word)=lower(?)` 都不可索引，`OR` 又强制走 MULTI-INDEX OR）。
    //    1–3 字符前缀全库约 1.1 万种（含大小写变体），答案完全由前缀决定 ⇒ 预算好。
    //    做到 2 不够：1–2 降到 1ms 之后最慢的变成 3 字符的 `des`（114ms）。
    // ⚠️ **查不到就回退实时查询**，结果一样只是慢一点 —— 缓存未命中不是错误。
    //    这条性质是有意的：SQLite 的 `lower()` 不认非 ASCII，与其猜大小写归一规则，
    //    不如让键严格等于原串。
    this.prefixCacheQuery = this.db.prepare(`
      SELECT d.id, d.word, d.is_lemma, d.pos, d.translation, d.definition,
             (SELECT g.text FROM sense_gloss g
              WHERE g.sense_id = (SELECT s.id FROM sense s
                                  WHERE s.word_id = d.id ORDER BY s.rank LIMIT 1)
                AND g.lang = 'zh'
              ORDER BY LENGTH(g.text) LIMIT 1) AS sense_zh
      FROM search_prefix p JOIN dict d ON d.id = p.word_id
      WHERE p.prefix = ?
      ORDER BY p.rank
      LIMIT ?
    `);

    // 反查：以本词为原形的变形形。走 `idx_infl_base`（base_id）。
    // 🔴 上限 60：`hablar` 这类动词有几百个变位形，全塞给前端会把页面撑爆
    //    （超长内容撑版面是 es 展示层已知的三条线索之一）。
    this.formsQuery = this.db.prepare(`
      SELECT d.word AS word, i.label_zh AS label
      FROM inflection i JOIN dict d ON d.id = i.word_id
      WHERE i.base_id = ? AND COALESCE(i.hidden, 0) = 0
      ORDER BY d.word, i.seq
      LIMIT 60
    `);
  }

  getStats() {
    return this.statsQuery.get() as Record<string, number>;
  }

  // 合成音查找。**路径是算出来的，不查表**：文件名就是 sha1(`词|音色`)，
  // 与 `es/pipeline/gen_tts.py` 里的 `digest()` 必须逐字一致，否则全库对不上。
  //
  // 🔴 为什么还要 existsSync：路径算得出来 ≠ 文件一定在。
  //    ① 半岛音只给音标含 θ 的词生成（其余 83.5% 根本没有这个文件）；
  //    ② 标点条目（`¿ ?`、`« »` 等 6 个）合成不出音频，一份都没有；
  //    ③ 音频按层铺开，没铺到的层就是没有。
  //    让前端拿路径去试、靠 404 兜底要多一个来回，而 `getEntry` 本来就是一次请求
  //    ⇒ 在服务端 stat 一下（微秒级），把"有没有"直接写进返回的 JSON。
  //
  // ⚠️ 必须用 **DB 里的词形** 算哈希，不能用用户输入的：`exactQuery` 是 COLLATE NOCASE，
  //    用户搜 "GRACIAS" 也能命中 `gracias`，但音频是按 DB 词形生成的。
  //
  // 🔴 **没有 θ 的词，拉美那份就是半岛音**（2026-08-10 补）。
  //    `TTS_VOICES` 的注释早就写了"其余两地读法相同，拉美那份通用"，但代码没落实：
  //    半岛音文件不存在时直接不给 `spain`，前端于是把「西」这个按钮降到浏览器 TTS。
  //    结果同一个词 —— 比如 `hola`，两地读法一模一样 —— 点「拉美」是 Piper、
  //    点「西」是系统音，音色突然换人，听着像我们有两份录音而其中一份很差。
  //    孤立单词上半岛↔拉美的实际差别只有 `z`/`ce`/`ci` 读 /θ/ 还是 /s/（同 `gen_tts.py`），
  //    ⇒ 音标里没有 θ 就把主力音同时挂到 `spain`。有 θ 而又没生成半岛音的，
  //    才继续落到浏览器 TTS —— 那种词拿拉美音冒充半岛音是真的读错了。
  private ttsFor(word: string, ipaSpain: string | null): SpanishTts[] {
    const out: SpanishTts[] = [];
    const url = (tag: string): string | null => {
      const h = createHash('sha1').update(`${word}|${tag}`).digest('hex');
      const rel = `${h.slice(0, 2)}/${h}.m4a`;
      return fs.existsSync(path.join(this.ttsDir, rel)) ? `/api/audio/es/${rel}` : null;
    };
    const mx = TTS_VOICES.find((v) => v.tag === 'mx')!;
    const es = TTS_VOICES.find((v) => v.tag === 'es')!;
    const uMx = url(mx.tag);
    const uEs = url(es.tag);
    if (uMx) out.push({ accent: mx.accent, url: uMx, voice: mx.voice });
    if (uEs) out.push({ accent: es.accent, url: uEs, voice: es.voice });
    else if (uMx && !(ipaSpain ?? '').includes('θ')) {
      out.push({ accent: es.accent, url: uMx, voice: mx.voice });
    }
    return out;
  }

  search(query: string, limit = 20): SpanishSearchItem[] {
    const keyword = query.trim();
    if (!keyword) return [];
    const like = `${keyword}%`;
    // 短前缀走预计算表；未命中（或长前缀）落回实时查询，结果一致。
    let rows = (keyword.length <= 3
      ? this.prefixCacheQuery.all(keyword, limit)
      : []) as Array<{
      id: number; word: string; pos: string | null;
      translation: string | null; definition: string | null; sense_zh: string | null;
    }>;
    if (rows.length === 0) rows = this.prefixQuery.all(like, like, keyword, limit) as Array<{
      id: number; word: string; pos: string | null;
      translation: string | null; definition: string | null; sense_zh: string | null;
    }>;
    return rows.map((r) => ({
      id: r.id,
      word: r.word,
      pos: r.pos,
      brief: briefOf(r),
    }));
  }

  // 读音。2026-08-07 从 `dict.phonetic` 那一列升级到 `pronunciation` 表。
  //
  // 🔴 **`phoneticLatam` 原先是用规则 θ→s 从半岛音派生的，而源头本来就直接给了。**
  //    实测含 θ 的 29,134 个词头里，源头给了 seseo 形的 29,118 个，
  //    其中 **630 个与规则派生不一致** —— 规则错得有规律：
  //      irascible  半岛 iɾasˈθible  规则 iɾasˈsible ❌  源头 iɾaˈsible ✅（sc 在拉美是单个 s）
  //      Madrid     半岛 maˈdɾiθ     规则 maˈdɾis   ❌  源头 maˈdɾid  ✅（词尾 -d）
  //    ⇒ 有权威源就用权威源；只有源头没给（16 个）才派生，且这一层只取源头。
  //
  // 只取 `notation='phonemic'` 的 primary：严式（`[ˈɡɾa.t̪is]`）也在库里，
  // **存不存与展不展示是两个独立开关**，这里选择不展示。
  private readonly pronQuery;

  // 统一义项层的读取与拼装。
  //
  // ⭐ `title` = **最短的那条中文**（理由见 SpanishUnifiedSense 的注释）。
  //    `detail` 只在「明显更长」时才给：长度差 ≤4 个字的两条中文（`平局；打平` vs
  //    `平局，打平`）是同一句话的两次翻译，并排显示只会让用户以为是两个意思。
  private buildUnified(wordId: number): SpanishUnifiedSense[] {
    const rows = this.unifiedSenseQuery.all(wordId) as Array<{
      id: number; rank: number; pos: string | null; gender: string | null;
      lang: string; kind: string; text: string;
    }>;
    const tags = this.unifiedTagQuery.all(wordId) as Array<{
      sense_id: number; kind: string; value: string;
    }>;
    const byTag = new Map<number, Record<string, string[]>>();
    for (const t of tags) {
      let m = byTag.get(t.sense_id);
      if (!m) byTag.set(t.sense_id, (m = {}));
      (m[t.kind] ||= []).push(t.value);
    }

    const order: number[] = [];
    const acc = new Map<number, {
      rank: number; pos: string | null; gender: string | null;
      zh: string[]; en: string[]; es: string[];
    }>();
    for (const r of rows) {
      let a = acc.get(r.id);
      if (!a) {
        acc.set(r.id, (a = { rank: r.rank, pos: r.pos, gender: r.gender,
                             zh: [], en: [], es: [] }));
        order.push(r.id);
      }
      if (r.lang === 'zh') a.zh.push(r.text);
      else if (r.lang === 'en') a.en.push(r.text);
      else if (r.lang === 'es') a.es.push(r.text);
    }

    const out: SpanishUnifiedSense[] = [];
    for (const id of order) {
      const a = acc.get(id)!;
      if (a.zh.length === 0) continue;      // 断言保证不会发生，防御性跳过
      const sorted = [...a.zh].sort((x, y) => x.length - y.length);
      const title = sorted[0];
      const longest = sorted[sorted.length - 1];
      const t = byTag.get(id) || {};
      out.push({
        id, rank: a.rank, pos: a.pos, gender: a.gender,
        title,
        detail: longest.length > title.length + 4 ? longest : null,
        en: a.en[0] ?? null,
        es: a.es[0] ?? null,
        topics: t.topic || [], regions: t.region || [],
        registers: t.register || [], numbers: t.number || [],
      });
    }
    return out;
  }

  getEntry(word: string): SpanishEntry | null {
    const keyword = word.trim();
    if (!keyword) return null;
    const row = this.exactQuery.get(keyword, keyword) as EsRow | undefined;
    if (!row) return null;
    const entry = mapEntry(row);

    // 变形层：语法说明改从 `inflection` 表读（2026-08-20），不再劈 `dict.infl` 字符串。
    // 🔴 迁移时逐词形核过：这里拼出来的 `inflNotes` 与旧列 `splitLines(row.infl)`
    //    在**全部 1,139,997 个词形上逐字节相同**（差异只出在 baseForms，见 mapEntry 处的注释）。
    //    契约闸另有一条断言盯着这件事，别改了排序或拼法就以为没人看得见。
    const infl = this.inflectionQuery.all(row.id) as Array<{
      seq: number; base: string; base_id: number | null;
      label_zh: string; kind: string | null; base_word: string | null;
    }>;
    entry.inflNotes = infl.map((r) => (r.base ? `${r.base} 的 ${r.label_zh}` : r.label_zh));

    // 反查变形形。**只在本词没有义项时查** —— 有释义的词条页信息已经够多，
    // 再挂一串变位形只会挤掉真正要看的东西；而补收的词头正好没有义项。
    if (row.definition === null && row.translation === null) {
      entry.forms = this.formsQuery.all(row.id) as { word: string; label: string }[];
    }

    // 解析每个原形的词义（单层，供变位页内联展示各原形分别是什么意思）。
    for (const bw of entry.baseForms) {
      if (bw === entry.word) continue;
      const br = this.exactQuery.get(bw, bw) as EsRow | undefined;
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
    // 读音：源头给了半岛/拉美两条就各用各的；只有一条通用形就两边都显示它。
    const pr = this.pronQuery.all(row.id) as Array<{ ipa: string; region: string | null }>;
    if (pr.length) {
      const es = pr.find((p) => p.region === 'es-ES');
      const la = pr.find((p) => p.region === 'es-419');
      const gen = pr.find((p) => p.region === null);
      entry.phonetic = normalizeSpanishIpa((es || gen || pr[0]).ipa);
      // 拉美音与半岛音相同时不另示（沿用既有约定，避免重复显示同一串）
      const l = la ? normalizeSpanishIpa(la.ipa) : null;
      entry.phoneticLatam = l && l !== entry.phonetic ? l : null;
    }

    entry.unifiedSenses = this.buildUnified(row.id);
    entry.homographs = (this.homographQuery.all(entry.word, row.id) as Array<{
      id: number; word: string; pos: string | null; phonetic: string | null;
    }>).map((h) => ({
      id: h.id, word: h.word, pos: h.pos,
      phonetic: normalizeSpanishIpa(h.phonetic),
      senses: this.buildUnified(h.id),
    }));

    entry.examples = (this.exampleQuery.all(entry.word) as Array<{
      id: number; sense_id: number | null; text: string; zh: string | null; ref: string | null;
    }>).map((r) => ({ id: r.id, senseId: r.sense_id, text: r.text, zh: r.zh, ref: r.ref }));
    entry.relations = (this.relationQuery.all(row.id) as Array<{
      sense_id: number | null; kind: string; target: string;
      tags: string | null; linkable: number;
    }>).map((r) => {
      let tags: string[] = [];
      try {
        const p = r.tags ? JSON.parse(r.tags) : [];
        if (Array.isArray(p)) tags = p as string[];
      } catch { tags = []; }
      return { senseId: r.sense_id, kind: r.kind, target: r.target,
               tags, linkable: r.linkable === 1 };
    });
    entry.collocations = (this.collocationQuery.all(row.id) as Array<{
      id: number; text: string; zh: string | null;
    }>).map((r) => ({ text: r.text, zh: r.zh }));

    // 西语版自有义项。`definition_es` 有值 = 西语义项已按行号内联在 senses 里，
    // 这里再给一份就是同样内容显示两遍 ⇒ 返回空。两者由构造保证互斥
    // （实测 54,206 个有 definition_es 的词，英文释义非空的恰好 0 个）。
    if (!row.definition_es) {
      const es = this.esSenseQuery.all(entry.word) as Array<{
        idx: number; gloss: string; pos_title: string | null;
        tags: string | null; zh: string | null; en_i: number | null;
      }>;
      entry.esSenses = es.map((r) => {
        let tags: string[] = [];
        try {
          const p = r.tags ? JSON.parse(r.tags) : [];
          if (Array.isArray(p)) tags = p as string[];
        } catch {
          tags = [];
        }
        return {
          idx: r.idx, gloss: r.gloss, posTitle: r.pos_title, tags, zh: r.zh,
          enI: typeof r.en_i === 'number' ? r.en_i : null,
        };
      });
    }

    entry.tts = this.ttsFor(entry.word, entry.phonetic);
    return entry;
  }

  close() {
    this.db.close();
  }
}
