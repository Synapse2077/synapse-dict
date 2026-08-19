// ============================================================================
// 意大利语词典服务 —— 意语专属，自包含，不引用其它语种（不复用 KaikkiDictService）。
// 读 it/build.py 产出的意语专属 dict 表：把意语本质（助动词 aux、变位类 conj、
// 性别 gender、不规则/异性复数 plural·plural_gender、number_note）作为一等字段返回。
// IPA 已是标准音标（kaikki/规则G2P/豆包三级填充），原样透传，绝不做英语式 normalize。
// ============================================================================

import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
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
  gender: string | null;    // 逐义项性别 m/f（双性名词 il radio 半径 vs la radio 收音机）
  regions: string[];        // 地区（Tuscany / dialectal …）
  registers: string[];      // 语域（literary / colloquial …）
  // 及物性等语法标签，源头原词（transitive / intransitive / impersonal …）。
  // 🔴 只在 entry.pos='verb' 时给：源头会把动词段的 transitive 串到同词形的名词义项上
  //    （`dare` 名词「借方」被标了 transitive），那 29 条数据层原样保留、这里不渲染。
  grammar: string[];
  // 该义项的助动词。单助动词词条 = 词条级的值；双助动词词条 = 逐义项确定性推导的值，
  // 推导不出来时为 'both'（展示成「avere / essere」）。
  aux: string | null;
  // 意大利语版自己写的**单语定义**（`informatica` → "disciplina scientifica e tecnica che…"）。
  // 只在能确定性 1:1 对上的义项上有值（阶段 1.5 提升了 23,523 条）；对不上的约 6 万条
  // 留在证据层 `sense_src(sense_id IS NULL)`，**不在这里露出** —— 未对齐的释义与出版义项
  // 并列展示会让用户先要理解「它不是上面那条的对应项」，认知负担大于收益。
  it: string | null;
  // 该义项是「指向另一个词」的关系条目时（异体/缩写/误拼），这里给目标词的中文释义。
  // 🔴 **跟随指针读取，不在库里复制** —— 目标词的释义改了这里自动跟着变。
  altOf: { target: string; zh: string | null }[];
  // 挂在这条义项上的例句（`example.sense_id`，14,895 条挂上了）。
  // 挂不上义项的那 23,249 条走 `ItalianEntry.examples`，摆在词条末尾，不硬塞进某条义项。
  examples: ItalianExample[];
};

export type ItalianCollocation = { text: string; zh: string | null };

// 一条读音。**来自 `pronunciation` 表，不再是 `dict.ipa` 那一列**（阶段 8 切换）。
// 一个词形可以有多条：`ancora` 名词「锚」ˈaŋkora / 副词「还」aŋˈkora 是真的两个读音，
// 全库 99,048 个词形有 ≥2 条。
export type ItalianReading = {
  ipa: string;              // 裸存，展示层统一加 /.../（六语种约定）
  notation: string;         // phonemic | narrow（严式只有 826 行，展示成 […]）
  src: string;              // 谁背书了这个读音（en/it/fr 版 · 规则派生 · unknown）
  isPrimary: boolean;       // 默认展示的那条（trust_rank 选出来的）
};

// 真人录音（Wikimedia Commons）。方针④三级兜底的**第一级**，9,404 个词形有。
// **只存 URL 不存字节**（与 es 同一判断：单条 mp3 约 24 KB，全量塞进库会让 dbtool
// 每次写库前的全文件备份跟着膨胀，而九成九的文件一辈子不会被请求）。
export type ItalianAudio = {
  file: string;             // Commons 文件名 = 这条录音的身份
  url: string;              // mp3（浏览器兼容性最好的那个）
  ogg: string | null;       // 备用格式，mp3 转码失败时用
  speaker: string | null;
  region: string | null;    // 🔴 **法语原值**（`Monopoli (Italie)`），中文映射在展示层
};

// 例句。38,144 条，**中文 100%**（阶段 5 全量翻译）。
export type ItalianExample = {
  text: string;             // 意语原句
  zh: string | null;
  en: string | null;        // 源自带的英文译文（英文版有，其余版没有）
  ref: string | null;       // 文献出处
};

// 语义关系。一个词最多 763 条（`buono`），所以**分类封顶**，并把总数一起给出去 ——
// 截断了却不说，用户会以为词典只收了这么多。
export type ItalianRelationGroup = {
  kind: string;             // synonym / antonym / hypernym / …（REL_LABELS 映射）
  total: number;
  targets: { word: string; linkable: boolean }[];   // linkable=false 的不做成链接
};

// 工具合成发音（Piper），方针④三级兜底「真人 > 工具生成 > 浏览器 TTS」的**中间那级**。
// 真人录音只覆盖 9,404 个词形（词头的 5.5%），这一级把有频次的 197,445 个词形补齐；
// 两级都没有才落到浏览器 TTS。
export type ItalianTts = {
  url: string;                 // /api/audio/it/<xx>/<sha1>.m4a
  voice: string;               // 音色名，仅用于展示与排查
};

// 🔴 与 `it/pipeline/gen_tts.py` 的 `digest()` **逐字节一致**：sha1(`词|音色`)。
//    差一个字节，前端就永远 existsSync 失败、**静默**全部降级到浏览器 TTS ——
//    不报错、不 404，只是所有词突然都"没有合成音"。
//    ⇒ `it/probes/tts_contract.ts` 拿清单逐条比对两端，别靠"看着一样"。
// ⚠️ 意语只有一个音色：不像 es 要分半岛/拉美（那是 θ 与 s 的真差别），
//    意语的地区差是零散方言（Milan/Romanesco，全库约 600 条），不做地区分叉（A58）。
const TTS_VOICES: Array<{ tag: string; voice: string }> = [
  { tag: 'it', voice: 'it_IT-paola-medium' },   // 换音色要同步改这里与 gen_tts.py 的 VOICES
];

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
  // 默认展示的读音（= `readings` 里 isPrimary 那条）。
  // 🔴 2026-08-18 阶段 8：来源从 `dict.ipa` 列换成 `pronunciation` 表。
  //    影响面实测：**513,775 个词形从「没有音标」变成有**（列只填过 588,280 个，
  //    表覆盖 1,102,055 个），另有 22,908 个词形显示的读音会变
  //    （`Gabon` ˈɡa.bon → ɡaˈbɔn，绝大多数是修对了 —— 列里 73.4% 是我们自己 G2P 算的，
  //     表里按 en > it > fr > 规则 的可信度重选了默认值）。
  ipa: string | null;
  readings: ItalianReading[];   // 全部读音，含 ipa 那条
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
  audios: ItalianAudio[];       // 真人录音（方针④第一级）
  examples: ItalianExample[];   // 挂不上具体义项的例句（挂得上的在 sense.examples 里）
  relations: ItalianRelationGroup[];   // 近义/反义/上下位…
  tts: ItalianTts[];            // 工具合成音（没有就空数组，前端落到浏览器 TTS）
  inflNotes: string[];          // 该词形语法说明（infl 列）
};

// 2026-08-12 v2 结构迁移（docs/SCHEMA.md）：`definition` / `translation` / `meta` /
// `collocation` 四列已从 dict 迁出到 sense / sense_gloss / sense_tag / collocation 表，
// `example` / `flag` 两列（0 行死数据）已删。本类型只留 dict 上仍在的词级列。
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
  infl: string | null;
  exchange: string | null;
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
  return inner;   // 裸输出——斜杠由展示层(App.tsx)统一加，全语种存裸
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

// ⚠️ 2026-08-12 删掉了 parseCollocations：搭配曾经把意语短语和中文粘在一个字符串里，
//    靠正则**在每次渲染时**切开（切错不留痕，且越南语这类拉丁字母语言直接崩，
//    见 docs/SCHEMA.md §7.1）。现在 collocation / collocation_gloss 两张表已经切好落库。

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

// 关系分类的展示上限。`buono` 有 763 条，全铺出来就不是词典是词表了。
// 截断必须连总数一起给（见 ItalianRelationGroup 的注释）。
const REL_CAP = 12;
// 关系分类的展示顺序：先给「换个词说」（近义/反义），再给分类学（上下位/同类/整体部分）。
const REL_ORDER = ['synonym', 'antonym', 'hypernym', 'hyponym', 'coordinate', 'holonym', 'meronym'];
// 词级例句的上限。挂上义项的那批不截断（本来就分散在各义项下，最多的也才几条）。
const EX_CAP = 8;

type SenseRow = { id: number; pos: string | null; gender: string | null;
                  en: string | null; zh: string | null; it: string | null;
                  sense_aux: string | null; entry_aux: string | null;
                  entry_pos: string | null };
type TagRow = { sense_id: number; kind: string; value: string };
type InflRow = { base: string; label_zh: string };
type AltRow = { sense_id: number; target: string };
type ColRow = { text: string; zh: string | null };
type AudioRow = { file: string; url_mp3: string | null; url_ogg: string | null;
                  url_wav: string | null; speaker: string | null; region: string | null };

/**
 * 检索归一：小写 + 去重音符 + 撇号折成 ASCII `'`。
 *
 * 🔴 **必须与 Python 侧 `it/fixes/split_case_forms.norm` 逐字节一致** ——
 *    `dict.word_norm` 是那边写的，这边查。同一个契约写两遍是老坑
 *    （音标哈希那次两边差一字节，全库静默降级）。
 *    ⇒ `it/probes/norm_contract.py` **逐行**核对两边实现，不抽样。
 *
 * 为什么要折撇号：意语撇号是词形的一部分（`all'alba` `sant'Antonio` `d'accordo`），
 * 网页正文用弯撇号 `’`、用户手打用直撇号 `'`，库里两种都有但**只有 267 个词两种都收了**。
 * 不归一的话，划词选中 `all'alba` 查不到（库里是 `all’alba`）。
 */
export function itSearchNorm(w: string): string {
  return w
    .replace(/[’‘ʼ´`＇]/g, "'")
    .toLowerCase()
    .normalize('NFD')
    .replace(/\p{Mn}/gu, '');
}

export class ItalianDictService {
  readonly databasePath: string;
  readonly lang = 'it';
  private readonly db: DatabaseSync;
  private readonly statsQuery;
  private readonly exactQuery;
  private readonly normQuery;
  private readonly hasContentQuery;
  private readonly prefixQuery;
  private readonly sensesQuery;
  private readonly entryAuxQuery;
  private readonly inflQuery;
  private readonly altQuery;
  private readonly altTargetQuery;
  private readonly tagsQuery;
  private readonly colsQuery;
  private readonly briefQuery;
  private readonly pronQuery;
  private readonly audioQuery;
  private readonly exampleQuery;
  private readonly relationQuery;
  private readonly existsQuery;
  private readonly ttsDir: string;

  constructor(databasePath: string, ttsDir?: string) {
    this.databasePath = databasePath;
    // 默认由 DB 路径推出：data/db/synapse-dict-it.sqlite → data/tts/it
    this.ttsDir = ttsDir ?? path.resolve(path.dirname(databasePath), '../tts/it');
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');

    this.statsQuery = this.db.prepare(`
      SELECT
        COUNT(*) AS total,
        SUM(is_lemma) AS lemmas,
        (SELECT COUNT(DISTINCT word_id) FROM sense) AS translated,
        SUM(CASE WHEN ipa IS NOT NULL AND ipa != '' THEN 1 ELSE 0 END) AS ipa
      FROM dict
    `);

    this.exactQuery = this.db.prepare(`
      SELECT id, word, ipa, pos, is_lemma, aux, conj, transitivity, pronominal,
             gender, plural, plural_gender, number_note, level, infl, exchange
      FROM dict
      WHERE word = ? COLLATE NOCASE
      -- 🔴 精确大小写是第一排序键（阶段 3a）。abate（男修道院院长）与 Abate（姓氏）
      --    拆成两行后 COLLATE NOCASE 会同时命中两行；不把精确匹配排前面，搜小写词就会
      --    命中大写专名 —— es 至今如此（搜 gracias 排第一的是洪都拉斯的城镇 Gracias）。
      --    ⚠️ 这段注释里不能用反引号：它在模板字符串里会直接截断 SQL。
      -- 🔴 2026-08-17 加第二排序键「有没有可见义项」。fixes/merge_apostrophe_variants.py
      --    把撇号异写的两行合并成一行后，另一行成了空壳（有意保留，可逆）。
      --    不加这一条，查那个拼写就落到空壳上、界面一片空白 ——
      --    合并反而让用户看到的更少。空壳没有义项，所以这条判据同时也是合并的兜底。
      ORDER BY CASE WHEN word = ? THEN 0 ELSE 1 END,
               CASE WHEN EXISTS(SELECT 1 FROM sense s
                                WHERE s.word_id = dict.id AND COALESCE(s.hidden,0)=0)
                    THEN 0 ELSE 1 END,
               is_lemma DESC
      LIMIT 1
    `);

    // 归一列回落：`word` 精确匹配落空时才用（撇号写法不同 / 没打重音符）。
    //    排序与 exactQuery 同构：lemma 优先，其次词形短的 —— 归一后可能命中多行
    //    （`Valle d'Aosta` / `Valle d’Aosta`），得有确定的挑选顺序。
    this.normQuery = this.db.prepare(`
      SELECT id, word, ipa, pos, is_lemma, aux, conj, transitivity, pronominal,
             gender, plural, plural_gender, number_note, level, infl, exchange
      FROM dict
      WHERE word_norm = ?
      -- 排序三层，顺序都是踩出来的：
      -- ① 有可见义项的优先 —— 不加这层，'r 的空壳（is_lemma=1）会压过真词条（is_lemma=0）
      -- ② 折掉撇号后与输入**大小写一致**的优先 —— 不加这层，查 ’ndrangheta（小写）
      --    会落到 'Ndrangheta（大写，指那个组织），而用户要的是同名普通名词
      -- ③ 其余按 lemma 优先、词形短优先，保证结果确定
      ORDER BY CASE WHEN EXISTS(SELECT 1 FROM sense s
                                WHERE s.word_id = dict.id AND COALESCE(s.hidden,0)=0)
                    THEN 0 ELSE 1 END,
               CASE WHEN replace(word, char(8217), '''') = ? THEN 0 ELSE 1 END,
               is_lemma DESC, LENGTH(word) ASC, word ASC
      LIMIT 1
    `);

    // 这一行是不是空壳：既没有可见义项，也不是任何词的变形。
    // 用于 getEntry 的回落判据 —— 合并撇号异写之后留下的行就是这种。
    this.hasContentQuery = this.db.prepare(`
      SELECT
        (SELECT COUNT(*) FROM sense WHERE word_id = ? AND COALESCE(hidden,0)=0)
      + (SELECT COUNT(*) FROM inflection WHERE word_id = ?) AS n
    `);

    // 一个词的义项：出版层 sense 定顺序，各语言说法从 sense_gloss 取。
    this.sensesQuery = this.db.prepare(`
      SELECT s.id, s.pos, s.gender,
             s.aux AS sense_aux, e.aux AS entry_aux, e.pos AS entry_pos,
             (SELECT text FROM sense_gloss
               WHERE sense_id = s.id AND lang = 'en' AND kind = 'equivalent' AND seq = 0) AS en,
             (SELECT text FROM sense_gloss
               WHERE sense_id = s.id AND lang = 'zh' AND kind = 'equivalent' AND seq = 0) AS zh,
             (SELECT text FROM sense_gloss
               WHERE sense_id = s.id AND lang = 'it' AND kind = 'definition' AND seq = 0) AS it
      FROM sense s
      LEFT JOIN entry e ON e.id = s.entry_id
      WHERE s.word_id = ? AND COALESCE(s.hidden, 0) = 0
      ORDER BY s.rank
    `);

    // 词头的助动词：**从 entry 层聚合**，不读 `dict.aux`。
    // 🔴 `dict.aux` 是七月流水线压平到词形上的旧值，与 entry 层会打架 ——
    //    `rallentare` 旧值 avere，而源头给的是 avére[及物]+èssere[不及物]（=both），
    //    于是词头写 avere、义项写 essere，同一页两个真值。
    //    真值在 entry.aux；`dict.aux` 只在**变形词形**上还有用（阶段 2 变形层建好后
    //    改成由 lemma 聚合下来的派生值，届时这一列就能退休）。
    this.entryAuxQuery = this.db.prepare(`
      SELECT DISTINCT aux FROM entry
      WHERE word_id = ? AND pos = 'verb' AND aux IS NOT NULL
    `);

    // 变形关系：读 `inflection` 表（阶段 2b 从 dict.infl/exchange 两列字符串迁来）。
    // 🔴 不再读那两列 —— 它们把一个词形的多条关系拼在一个字符串里，且**含 alt_of**
    //    （`a` 的 "alfiere 的 变位形式" 其实是缩写，不是变位形式，阶段 2a 已移回词条层）。
    this.inflQuery = this.db.prepare(`
      SELECT base, label_zh FROM inflection WHERE word_id = ? ORDER BY id
    `);

    // alt_of 指针：把目标词的中文释义**跟随读取**出来（不复制数据）。
    // 两位顾问一致：用户查到 `abaca` 时最想要的就是 `abacà` 的词义，只给裸指针没用。
    // 🔴 2026-08-16 重写：原来那版**实测 386 ms**（`TVTB` 整页 0.43 秒，比同类词慢十倍）。
    //    执行计划是 `SEARCH g USING INDEX idx_glosslang (lang=?)` —— SQLite 从**选择性最差
    //    那头**入手，先扫遍 41 万条 lang='zh' 的释义，再逐条回连 sense、再连 dict 判词形。
    //    `query-perf-collation-traps` 记的就是这个形状（es 上是「扫遍 34 万条中文 gloss」），
    //    it 上今天中文从 63 万涨到 70 万才咬得这么明显 —— **性能问题要等数据长大才咬人**。
    //    改法：把 dict 的定位**逼成标量子查询**，先拿到唯一的 word_id，再顺着索引取。
    //    实测 386 ms → 0.0 ms。
    this.altTargetQuery = this.db.prepare(`
      SELECT (SELECT text FROM sense_gloss
               WHERE sense_id = s.id AND lang = 'zh' AND seq = 0) AS text
      FROM sense s
      WHERE s.word_id = (SELECT id FROM dict WHERE word = ? COLLATE NOCASE LIMIT 1)
        AND COALESCE(s.hidden, 0) = 0
      ORDER BY s.rank LIMIT 1
    `);

    this.altQuery = this.db.prepare(`
      SELECT sense_id, target FROM sense_relation WHERE word_id = ? AND kind = 'alt_of'
    `);

    this.tagsQuery = this.db.prepare(`
      SELECT t.sense_id, t.kind, t.value
      FROM sense_tag t JOIN sense s ON s.id = t.sense_id
      WHERE s.word_id = ?
    `);

    this.colsQuery = this.db.prepare(`
      SELECT c.text,
             (SELECT text FROM collocation_gloss
               WHERE collocation_id = c.id AND lang = 'zh') AS zh
      FROM collocation c
      WHERE c.word_id = ?
      ORDER BY c.rank
    `);

    // 列表项的一行摘要 = 第一条义项的中文。
    // 🔴 单独一条按 word_id 的查询，**不做成前缀查询里的相关子查询** ——
    //    那样 SQLite 会从选择性最差的一头入手，es 的 `mano` 词条页曾因此跑了 6.3 秒。
    //    先 LIMIT 出候选，再对这 ≤20 个 id 各查一次（走 idx_sense_word，微秒级）。
    this.briefQuery = this.db.prepare(`
      SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
      WHERE s.word_id = ? AND COALESCE(s.hidden, 0) = 0
        AND g.lang = 'zh' AND g.kind = 'equivalent' AND g.seq = 0
      ORDER BY s.rank LIMIT 1
    `);

    // 读音：`pronunciation` 表（阶段 4 建，阶段 8 接上展示层）。
    // 🔴 排序里 `is_primary DESC` 是第一键 —— 默认展示的那条必须稳定排第一，
    //    它是 `trust_rank` 选出来的，展示层不许自己再挑一次（那就是第二把尺子）。
    //    其余按「音位式优先、短的优先、字符串定序」，保证同一个词两次打开顺序一致。
    this.pronQuery = this.db.prepare(`
      SELECT ipa, notation, src, is_primary FROM pronunciation
      WHERE word_id = ?
      ORDER BY is_primary DESC, CASE WHEN notation='phonemic' THEN 0 ELSE 1 END,
               LENGTH(ipa) ASC, ipa ASC
    `);

    // 真人录音。⚠️ 这里**不能写 COLLATE NOCASE** —— `idx_audio_word` 是 BINARY 索引，
    //    加了 NOCASE 就用不上索引、退化成扫 12,188 行（es 的 `mano` 词条页 6.3 秒同一个坑）。
    //    传进来的是 **DB 里的词形**（getEntry 已经归一过），大小写本来就是对的。
    this.audioQuery = this.db.prepare(`
      SELECT file, url_mp3, url_ogg, url_wav, speaker, region
      FROM audio WHERE word = ? AND kind = 'human'
      ORDER BY CASE WHEN speaker IS NULL THEN 1 ELSE 0 END, file
    `);

    // 例句 + 中文。同上，`idx_ex_word` 也是 BINARY 索引，不加 COLLATE。
    this.exampleQuery = this.db.prepare(`
      SELECT e.sense_id, e.text, e.ref,
             (SELECT text FROM example_gloss WHERE example_id = e.id AND lang = 'zh') AS zh,
             (SELECT text FROM example_gloss WHERE example_id = e.id AND lang = 'en') AS en
      FROM example e WHERE e.word = ? ORDER BY e.id
    `);

    // 语义关系。`alt_of` 由 altQuery 单独处理（它是「指向另一个词」，不是「语义相邻」）。
    this.relationQuery = this.db.prepare(`
      SELECT kind, target FROM sense_relation
      WHERE word_id = ? AND kind <> 'alt_of' ORDER BY id
    `);

    // 关系目标点不点得动。🔴 判据必须与 `getEntry` 的解析路径一致：那边落空会走
    //    **归一列**再查一次（撇号写法/重音符/大小写）。只查 `word` 会把
    //    `amico dell’uomo`（源头弯撇号、库里直撇号）标成点不动，而它其实查得到 ——
    //    「说点不动、实际点得动」和反过来一样是骗人。
    this.existsQuery = this.db.prepare(`
      SELECT 1 AS n FROM dict WHERE word = ? OR word_norm = ? LIMIT 1
    `);

    // 前缀检索：命中 word 或 word_norm（去重音，便于无重音输入）；lemma 优先、短词优先。
    this.prefixQuery = this.db.prepare(`
      SELECT id, word, is_lemma, pos, infl
      FROM dict
      WHERE word LIKE ? COLLATE NOCASE OR word_norm LIKE ? COLLATE NOCASE
      ORDER BY
        CASE WHEN word = ? THEN 0 WHEN lower(word) = lower(?) THEN 1 ELSE 2 END,
        is_lemma DESC,
        LENGTH(word) ASC,
        word ASC
      LIMIT ?
    `);
  }

  /**
   * 同一个读音的两种写法 → 同一个键。**只用于去重，不用于展示**（展示保留源头写法）。
   *
   * 只折**两件音位变体**，两件都是「意语里不可能靠它区别词义」的：
   *   ① 长音符 `ː` —— 重音开音节的元音自动拉长，`ˈka.ne`（英文版）与 `ˈkaːne`（意语版）
   *      是同一个读音的两种记法
   *   ② 软腭前的 `ŋ` —— /n/ 在 k/ɡ 前必然读成 [ŋ]，`anˈkora`（英文版）与 `aŋˈkora`（意语版）
   *      同上。**只在 k/ɡ 之前折**，别处的 ŋ 一概不动
   *
   * 不折就会有大量假变体：`ancora` 原来并排显示 4 条，其中两两成对只差记法，
   * 用户看到的是「这个词有四个读音」。折完剩 2 条，正是真的那两个
   * （anˈkora「还」/ ˈankora「锚」）。
   *
   * ⚠️ **重音符不折**，那是真区别（`subito` ˈsubito「立刻」/ suˈbito「遭受了」）。
   * ⚠️ 也**不折 s/z** —— 清浊在意语里南北有别，是真变体不是记法差。
   */
  private static readingKey(ipa: string): string {
    // ⚠️ 前瞻里必须放过中间的重音符：`aŋˈkora` 的 ŋ 后面隔着一个 `ˈ` 才是 k。
    //    第一版写成 `/ŋ(?=[kɡ])/` —— 一条都没折到，而 `ancora` 照旧并排显示三条读音。
    //    **是渲染出来读了一遍才发现的**，单元层面看不出来（函数没报错、也确实折了别的词）。
    return ipa.normalize('NFC').replace(/ː/g, '').replace(/ŋ(?=[ˈˌ]?[kɡ])/g, 'n');
  }

  private buildReadings(wordId: number): ItalianReading[] {
    const rows = this.pronQuery.all(wordId) as unknown as
      { ipa: string; notation: string; src: string; is_primary: number }[];
    const out: ItalianReading[] = [];
    const seen = new Set<string>();
    for (const r of rows) {
      const ipa = normalizeItalianIpa(r.ipa);
      if (!ipa) continue;
      // 🔴 去重**不带 notation**：`pesca` 的四行是 en 版两条音位式 + fr 版同样两条严式
      //    （fr 版用 `[…]`），文字一模一样 ⇒ 带上 notation 去重，页面就变成
      //    `/ˈpɛska/ /ˈpeska/ [ˈpɛska] [ˈpeska]` —— 同样两个读音显示两遍。
      //    排序已把音位式排在严式前面，所以留下的是音位式那条。
      //    ⚠️ 严式**只在文字确实不同时**才留（真正的窄式转写会带更多细节）。
      const key = ItalianDictService.readingKey(ipa);
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ ipa, notation: r.notation, src: r.src, isPrimary: r.is_primary === 1 });
    }
    return out;
  }

  /** 例句按义项分桶。挂不上义项的进 `null` 桶，摆在词条末尾。 */
  private examplesOf(word: string): Map<number | null, ItalianExample[]> {
    const rows = this.exampleQuery.all(word) as unknown as
      { sense_id: number | null; text: string; ref: string | null;
        zh: string | null; en: string | null }[];
    const out = new Map<number | null, ItalianExample[]>();
    for (const r of rows) {
      const list = out.get(r.sense_id) ?? [];
      list.push({ text: r.text, zh: r.zh ?? null, en: r.en ?? null, ref: r.ref ?? null });
      out.set(r.sense_id, list);
    }
    return out;
  }

  private relationsOf(wordId: number): ItalianRelationGroup[] {
    const rows = this.relationQuery.all(wordId) as unknown as { kind: string; target: string }[];
    const byKind = new Map<string, string[]>();
    for (const r of rows) {
      const list = byKind.get(r.kind) ?? [];
      if (!list.includes(r.target)) list.push(r.target);
      byKind.set(r.kind, list);
    }
    const out: ItalianRelationGroup[] = [];
    // 认识的分类按 REL_ORDER 排，不认识的排在最后（不丢，也不假装知道该排哪）
    const rank = (k: string) => (REL_ORDER.indexOf(k) < 0 ? REL_ORDER.length : REL_ORDER.indexOf(k));
    for (const kind of [...byKind.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))) {
      const all = byKind.get(kind)!;
      out.push({
        kind,
        total: all.length,
        // 🔴 存在性只查**要显示的那几个**（≤12），不是全部 763 个 ——
        //    每个查询是微秒级，但 763 × 每次打开词条就不是了。
        targets: all.slice(0, REL_CAP).map((w) => ({
          word: w, linkable: this.existsQuery.get(w) !== undefined,
        })),
      });
    }
    return out;
  }

  private buildSenses(wordId: number, ex?: Map<number | null, ItalianExample[]>): ItalianSense[] {
    const rows = this.sensesQuery.all(wordId) as unknown as SenseRow[];
    const tags = this.tagsQuery.all(wordId) as unknown as TagRow[];
    const byId = new Map<number, { regions: string[]; registers: string[]; grammar: string[] }>();
    for (const t of tags) {
      let e = byId.get(t.sense_id);
      if (!e) { e = { regions: [], registers: [], grammar: [] }; byId.set(t.sense_id, e); }
      if (t.kind === 'region') e.regions.push(t.value);
      else if (t.kind === 'register') e.registers.push(t.value);
      else if (t.kind === 'grammar') e.grammar.push(t.value);
    }
    const alts = new Map<number, { target: string; zh: string | null }[]>();
    for (const a of this.altQuery.all(wordId) as unknown as AltRow[]) {
      const hit = this.altTargetQuery.get(a.target) as { text?: string } | undefined;
      const list = alts.get(a.sense_id) ?? [];
      list.push({ target: a.target, zh: hit?.text ?? null });
      alts.set(a.sense_id, list);
    }
    return rows.map((r) => ({
      en: r.en ?? null,
      zh: r.zh ?? null,
      it: r.it ?? null,
      pos: r.pos,
      gender: r.gender,
      regions: byId.get(r.id)?.regions ?? [],
      registers: byId.get(r.id)?.registers ?? [],
      // 见 ItalianSense.grammar 的说明：非动词词条不渲染及物性
      grammar: r.entry_pos === 'verb' ? (byId.get(r.id)?.grammar ?? []) : [],
      // 逐义项的值优先；没有就用词条级的值（**不是**在库里复制一份，见 SCHEMA §10.4）
      aux: r.sense_aux ?? r.entry_aux ?? null,
      altOf: alts.get(r.id) ?? [],
      examples: ex?.get(r.id) ?? [],
    }));
  }

  /** 词条级助动词 = 该词形所有动词 entry 的取值聚合；两个值以上就是 both。
   *  返回 null 表示 entry 层没有值（多半是变形词形），由调用方回落到 `dict.aux`。 */
  private rollupAux(wordId: number): string | null {
    const vals = (this.entryAuxQuery.all(wordId) as unknown as { aux: string }[])
      .map((r) => r.aux);
    if (vals.length === 0) return null;
    const set = new Set(vals.flatMap((v) => (v === 'both' ? ['avere', 'essere'] : [v])));
    return set.size === 1 ? [...set][0] : 'both';
  }

  /**
   * @param full false = 只要词头字段与义项（供 `bases` 内联展示）。
   *   原形词不需要例句/关系/录音 —— 它们在原形自己的页面上，内联块里铺开只是噪声，
   *   而每条都要查库。变位形页面上常有 3～5 个原形，省下的是 3～5 倍的查询。
   */
  private mapEntry(row: ItRow, full = true): ItalianEntry {
    const infl = this.inflQuery.all(row.id) as unknown as InflRow[];
    const readings = this.buildReadings(row.id);
    const ex = full ? this.examplesOf(row.word) : undefined;
    return {
      lang: 'it',
      id: row.id,
      word: row.word,
      // 🔴 阶段 8：读 `pronunciation` 表，不再读 `dict.ipa` 列（见 ItalianEntry.ipa 的注释）。
      //    `normalizeItalianIpa` 仍然要走 —— 它做的是「维基式源 IPA → 本土词典标准」，
      //    与"从哪张表取"无关。
      ipa: readings.find((r) => r.isPrimary)?.ipa ?? readings[0]?.ipa ?? null,
      readings,
      pos: row.pos,
      isLemma: row.is_lemma === 1,
      aux: this.rollupAux(row.id) ?? row.aux,
      conj: row.conj,
      transitivity: row.transitivity,
      pronominal: row.pronominal === 1,
      gender: row.gender,
      plural: row.plural,
      pluralGender: row.plural_gender,
      numberNote: row.number_note,
      level: row.level,
      senses: this.buildSenses(row.id, ex),
      collocations: (this.colsQuery.all(row.id) as unknown as ColRow[])
        .map((c) => ({ text: c.text, zh: c.zh ?? null })),
      baseForms: [...new Set(infl.map((x) => x.base))],
      bases: [],
      audios: full ? (this.audioQuery.all(row.word) as unknown as AudioRow[]).map((a) => ({
        file: a.file,
        // mp3 优先（浏览器兼容性最好）；12,188 条全都有 mp3，ogg/wav 只是备用
        url: a.url_mp3 ?? a.url_ogg ?? a.url_wav ?? '',
        ogg: a.url_ogg ?? null,
        speaker: a.speaker ?? null,
        // 🔴 **原样透传法语原值**（`Monopoli (Italie)`），不在这里翻译 ——
        //    映射表的家是 `@synapse-dict/dict-labels`（`itAudioRegion`），
        //    数据层翻译会让同一份数据出现两套中文（es 就是在展示层映射的）。
        region: a.region ?? null,
      })).filter((a) => a.url) : [],
      examples: full ? (ex!.get(null) ?? []).slice(0, EX_CAP) : [],
      relations: full ? this.relationsOf(row.id) : [],
      tts: [],                          // 文件系统，由 getEntry 填
      inflNotes: infl.map((x) => `${x.base} 的 ${x.label_zh}`),
      // ⚠️ 2026-08-18 阶段 8 删掉了 `flag` 字段：`dict.flag` 列在 v2 迁移时就删了
      //    （全库 0 行），这里一直返回 null 只是为了不动展示层。现在一起清掉 ——
      //    永远为 null 的字段和永远为真的健康检查是同一类东西。
    };
  }

  getStats() {
    return this.statsQuery.get() as Record<string, number>;
  }

  search(query: string, limit = 20): ItalianSearchItem[] {
    const keyword = query.trim();
    if (!keyword) return [];
    const like = `${keyword}%`;
    const rows = this.prefixQuery.all(like, like, keyword, keyword, limit) as Array<{
      id: number; word: string; pos: string | null; infl: string | null;
    }>;
    return rows.map((r) => {
      const g = this.briefQuery.get(r.id) as { text: string } | undefined;
      return {
        id: r.id,
        word: r.word,
        pos: r.pos,
        // 变形形没有义项，摘要退回它的语法说明（"gatto 的 复数"）——
        // 与迁移前一致：那时 translation 存的就是这句话。
        brief: g?.text ?? firstLine(r.infl),
      };
    });
  }

  getEntry(word: string): ItalianEntry | null {
    const keyword = word.trim();
    if (!keyword) return null;
    let row = this.exactQuery.get(keyword, keyword) as ItRow | undefined;
    // 🔴 两种情况要按归一列再查一次（撇号写法不同 / 输入没打重音符）：
    //    ① 精确匹配落空 —— 2026-08-17 之前这里只查 word 列，划词选中 all'alba（直撇号）
    //       查不到，库里存的是 all’alba（弯撇号）。约 2,000 个词形只有其中一种写法。
    //    ② 精确命中了一个空壳 —— fixes/merge_apostrophe_variants.py 把撇号异写的两行
    //       合并后，另一行内容全搬走了（行本身有意保留，可逆）。不回落就显示空白，
    //       合并反而让用户看到的更少。
    //    ⚠️ 空壳判据是「没有可见义项**且**不是任何词的变形」——
    //       只判"没有义项"会把变形形（accintolarlo 这类，本来就没有独立义项）
    //       一起踢去回落，落到别的词上。
    if (row && (this.hasContentQuery.get(row.id, row.id) as { n: number }).n === 0) {
      row = undefined;
    }
    if (!row) {
      const folded = keyword.replace(/[’‘ʼ´`＇]/g, "'");   // 保大小写，只折撇号
      row = (this.normQuery.get(itSearchNorm(keyword), folded) as ItRow | undefined)
        ?? (this.exactQuery.get(keyword, keyword) as ItRow | undefined);
    }
    if (!row) return null;
    const entry = this.mapEntry(row);
    // ⚠️ 用 **DB 里的词形**算哈希，不是用户输入的 —— 查询会走归一列（撇号/重音符/大小写）
    entry.tts = this.ttsFor(entry.word);

    // 解析每个原形词义（单层，供变位页内联展示各原形是什么意思）。
    for (const bw of entry.baseForms) {
      if (bw === entry.word) continue;
      const br = this.exactQuery.get(bw, bw) as ItRow | undefined;
      if (!br) continue;
      const bm = this.mapEntry(br, false);   // 内联块只要词头字段＋义项，见 mapEntry 的 full
      entry.bases.push({
        word: bm.word, pos: bm.pos, ipa: bm.ipa, aux: bm.aux,
        gender: bm.gender, senses: bm.senses,
      });
    }
    return entry;
  }

  // 合成音查找。**路径是算出来的，不查表**（见 TTS_VOICES 上方的契约说明）。
  //
  // 🔴 为什么还要 existsSync：路径算得出来 ≠ 文件一定在。
  //    只给**有频次**的 197,445 个词形生成（另外 130 万个在 wordfreq 里查不到，
  //    按方针④落到浏览器 TTS）；标点/符号条目也合成不出音频。
  //    让前端拿路径去试、靠 404 兜底要多一个来回，而 getEntry 本来就是一次请求
  //    ⇒ 在服务端 stat 一下（微秒级），把"有没有"直接写进返回的 JSON。
  //
  // ⚠️ 必须用 **DB 里的词形**算哈希，不能用用户输入的：查询会走归一列
  //    （撇号写法、重音符、大小写都可能不同），而音频是按 DB 词形生成的。
  ttsFor(word: string): ItalianTts[] {
    const out: ItalianTts[] = [];
    for (const v of TTS_VOICES) {
      const h = createHash('sha1').update(`${word}|${v.tag}`).digest('hex');
      const rel = `${h.slice(0, 2)}/${h}.m4a`;
      if (fs.existsSync(path.join(this.ttsDir, rel))) {
        out.push({ url: `/api/audio/it/${rel}`, voice: v.voice });
      }
    }
    return out;
  }

  close() {
    this.db.close();
  }
}
