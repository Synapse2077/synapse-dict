import { useCallback, useEffect, useRef, useState } from 'react';
import {
  GENDER_LABELS, POS_LABELS, REGISTER_LABELS, NUMBER_LABELS, TOPIC_LABELS,
  REL_LABELS, EXCHANGE_LABELS, TRANS_LABELS,
  ES_REGION_LABELS, ES_ARTICLE, ES_CONJ_LABELS,
  IT_REGION_LABELS, IT_ARTICLE, IT_AUX_LABELS, IT_CONJ_LABELS, IT_NUMBER_NOTE_LABELS,
  itAudioRegion,
  FR_AUX_LABELS, FR_VGROUP_LABELS, FR_ADJPOS_LABELS, FR_REGION_LABELS, FR_ARTICLE,
  PT_VCONJ_LABELS, PT_REGION_LABELS, PT_ARTICLE,
  DE_ARTICLE, DE_AUX_LABELS, DE_VCLASS_BASE, DE_REGION_LABELS, relTagLabel } from '@synapse-dict/dict-labels';

// ---- Shared types ----

type LanguageMeta = { code: string; label: string; name: string; speak: string };

type SearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

// English entry (legacy stardict schema)
type EnEntry = {
  lang: 'en';
  id: number;
  word: string;
  phonetic: string | null;
  phoneticUk: string | null;
  phoneticUs: string | null;
  phoneticDisplay: string | null;
  translation: string | null;
  definition: string | null;
  exchange: string | null;
  tag: string | null;
  collins: number | null;
  oxford: number | null;
  bnc: number | null;
  frq: number | null;
};

// Spanish entry (西语专属；数据源自 kaikki，经 es/build.py 产出扁平 dict 表)
type SpanishSense = {
  en: string | null;   // 英文版的英文 gloss
  es: string | null;   // 西语版的西语单语定义；与 en 互斥互补，同一行呈现
  zh: string | null;
  pos: string | null;
  gender: string | null;
  regions: string[];
  registers: string[];
  numbers: string[];
};
type SpanishCollocation = { text: string; zh: string | null };
type SpanishAudio = {
  file: string; url: string | null; ipa: string | null;
  speaker: string | null; region: string | null;
  regionSrc: string | null; kind: string;
};
// 工具合成音（Piper）。方针④三级兜底的中间那级：真人 > 工具生成 > 浏览器 TTS。
// 服务端已经 stat 过文件，出现在这个数组里就是**确实有**，前端不必再探 404。
type SpanishTts = { accent: 'spain' | 'latam'; url: string; voice: string };
// 西语版自有义项。与 SpanishSense.es 不同：那是按行号对齐的同一条义项的西语说法，
// 这是西语版自己的一套编号（hacer 我们 15 条、它 59 条），独立成块展示。
type SpanishEsSense = {
  idx: number; gloss: string; posTitle: string | null; tags: string[];
  zh: string | null;
  enI: number | null;   // 对应上面第几条义项；null = 英文版没有这个义项
};
type SpanishBase = {
  word: string;
  pos: string | null;
  phonetic: string | null;
  senses: SpanishSense[];
};
type SpanishEntry = {
  lang: string;
  id: number;
  word: string;
  phonetic: string | null;       // España 半岛（含 θ）
  phoneticLatam: string | null;  // América seseo（θ→s 派生）
  pos: string | null;
  isLemma: boolean;
  reflexive: boolean;
  gender: string | null;         // m / f / mf（el/la）
  plural: string | null;         // 不规则复数
  feminine: string | null;       // 阴性形（actor→actriz / rojo→roja）
  conjugation: string | null;    // 1 / 2 / 3（-ar/-er/-ir）
  stemChange: string | null;     // 词干变化 e→ie / o→ue / e→i / u→ue
  pp: string | null;             // 过去分词（不规则）
  transitivity: string | null;   // t / i / ti
  comparative: string | null;    // 不规则比较级
  level: string | null;          // CEFR
  senses: SpanishSense[];
  collocations: SpanishCollocation[];
  examples: SpanishExample[];
  relations: SpanishRelation[];
  audios: SpanishAudio[];
  esSenses: SpanishEsSense[];
  unifiedSenses: SpanishUnifiedSense[];
  tts: SpanishTts[];
  baseForms: string[];
  bases: SpanishBase[];
  inflNotes: string[];
  // 反查：以本词为原形的变形形（2026-08-20）。只在**补收的无释义词头**上有值 ——
  // 见 SpanishEntryView 里那段注释。服务端已按 60 条封顶。
  forms: { word: string; label: string }[];
  homographs: SpanishHomograph[];
  flag: string | null;
};

// 统一义项层（`sense`/`sense_gloss`/`sense_tag` 三张表）。2026-08-07。
// 取代 `senses` + `esSenses` 两块：那两块是**同一个词的两套义项并列**
// （`banco` 显示 4+7=11 条，「银行」出现两次），新的是归并后的一套（7 条，一条不丢）。
// `title` 是最短的那条中文、`detail` 是明显更长的那条，服务端已挑好，前端不再判断。
// 例句与词汇关系。2026-08-07 接入 —— 库里躺了很久、界面一条没显示过。
// 两者都带 `senseId`，所以挂在**对应的义项下面**，不是笼统堆在词条末尾。
type SpanishExample = {
  id: number; senseId: number | null; text: string; zh: string | null; ref: string | null;
};
type SpanishRelation = {
  senseId: number | null; kind: string; target: string; tags: string[]; linkable: boolean;
};

// 同形词：拼写只差大小写的另一个词条。同页并列显示（像纸质词典的 virgo¹ / Virgo²）。
// 🔴 西语用大小写承载词汇区别，而查询是 NOCASE —— 用户输 `sandwich` 得看得到
//    `Sandwich`（地名），否则那个词条对他不存在。
type SpanishHomograph = {
  id: number; word: string; pos: string | null; phonetic: string | null;
  senses: SpanishUnifiedSense[];
};

type SpanishUnifiedSense = {
  id: number;
  rank: number;
  pos: string | null;
  gender: string | null;
  title: string;
  detail: string | null;
  en: string | null;
  es: string | null;
  topics: string[];
  regions: string[];
  registers: string[];
  numbers: string[];
};

// Italian entry (意语专属 schema：本质字段 aux/conj/gender/plural 为一等公民)
type ItExample = { text: string; zh: string | null; en: string | null; ref: string | null };
type ItSense = {
  en: string | null;
  zh: string | null;
  it: string | null;       // 意语版原文释义（`sense_gloss.lang='it'`，89,531 条）
  pos: string | null;
  gender: string | null;   // 逐义项性别 m/f（双性名词 il radio 半径 vs la radio 收音机）
  regions: string[];
  registers: string[];
  examples: ItExample[];   // 挂在这条义项上的例句（阶段 8 接上）
  entryId: number | null;  // 这条义项属于哪个词条（同词形多词条时用来分组）
};
type ItReading = {
  ipa: string; notation: string; src: string; isPrimary: boolean;
  entryIds: number[];       // 属于哪几个词条；空 = 各词条共用（见 dict-core 的注释）
};
type ItAudio = {
  file: string; url: string; ogg: string | null;
  speaker: string | null; region: string | null;   // region 是法语原值，展示前过 itAudioRegion
};
type ItPlural = { form: string; gender: string | null };
type ItRelationGroup = {
  kind: string; total: number; targets: { word: string; linkable: boolean }[];
};
type ItCollocation = { text: string; zh: string | null };
type ItBase = {
  word: string;
  pos: string | null;
  ipa: string | null;
  aux: string | null;
  gender: string | null;
  senses: ItSense[];
};
type ItEntry = {
  lang: 'it';
  id: number;
  word: string;
  ipa: string | null;
  pos: string | null;
  isLemma: boolean;
  aux: string | null;
  conj: string | null;
  transitivity: string | null;
  pronominal: boolean;
  gender: string | null;
  plural: string | null;
  pluralGender: string | null;
  plurals: ItPlural[];          // 全部复数形（双复数 braccia/bracci）
  numberNote: string | null;
  level: string | null;
  senses: ItSense[];
  collocations: ItCollocation[];
  baseForms: string[];
  bases: ItBase[];
  // —— 阶段 8 接上展示层的四样（数据分别在阶段 4/5/6a 就落库了，界面一条没显示过）——
  readings: ItReading[];        // 全部读音；`ipa` 是其中 isPrimary 那条
  audios: ItAudio[];            // 真人录音（方针④第一级）
  examples: ItExample[];        // 挂不上具体义项的例句
  relations: ItRelationGroup[]; // 近义/反义/上下位…
  inflNotes: string[];
};

// —— 法语（fr）：法语专属 shape，与 es/it 解耦 ——
type FrSense = {
  en: string | null;
  zh: string | null;
  pos: string | null;
  gender: string | null;
  regions: string[];
  registers: string[];
};
type FrCollocation = { text: string; zh: string | null };
type FrBase = {
  word: string;
  pos: string | null;
  ipa: string | null;
  aux: string | null;
  gender: string | null;
  senses: FrSense[];
};
type FrEntry = {
  lang: 'fr';
  id: number;
  word: string;
  ipa: string | null;
  pos: string | null;
  isLemma: boolean;
  aux: string | null;
  vgroup: string | null;
  transitivity: string | null;
  pronominal: boolean;
  pp: string | null;
  gender: string | null;
  plural: string | null;
  feminine: string | null;
  invariable: boolean;
  adjPos: string | null;
  government: string | null;
  comparative: string | null;
  level: string | null;
  senses: FrSense[];
  collocations: FrCollocation[];
  baseForms: string[];
  bases: FrBase[];
  inflNotes: string[];
  flag: string | null;
};

// —— 葡萄牙语（pt）：双读音(巴西 pt-BR + 葡萄牙 pt-PT)，与 es/it/fr 解耦 ——
type PtSense = {
  en: string | null;
  zh: string | null;
  pos: string | null;
  gender: string | null;
  regions: string[];
  registers: string[];
};
type PtCollocation = { text: string; zh: string | null };
type PtBase = {
  word: string;
  pos: string | null;
  ipaBr: string | null;
  ipaPt: string | null;
  gender: string | null;
  senses: PtSense[];
};
type PtEntry = {
  lang: 'pt';
  id: number;
  word: string;
  ipaBr: string | null;
  ipaPt: string | null;
  pos: string | null;
  isLemma: boolean;
  vconj: string | null;
  transitivity: string | null;
  pronominal: boolean;
  pp: string | null;
  ppShort: string | null;
  gender: string | null;
  plural: string | null;
  feminine: string | null;
  comparative: string | null;
  adjPos: string | null;
  government: string | null;
  level: string | null;
  senses: PtSense[];
  collocations: PtCollocation[];
  baseForms: string[];
  bases: PtBase[];
  inflNotes: string[];
  flag: string | null;
};

type DeSense = {
  en: string | null;
  zh: string | null;
  pos: string | null;
  regions: string[];
  registers: string[];
};
type DeCollocation = { text: string; zh: string | null };
type DeBase = {
  word: string;
  pos: string | null;
  ipa: string | null;
  gender: string | null;
  senses: DeSense[];
};
type DeEntry = {
  lang: 'de';
  id: number;
  word: string;
  ipa: string | null;
  pos: string | null;
  isLemma: boolean;
  gender: string | null;        // m / f / n / mf（der/die/das；单性别词主性别）
  genitive: string | null;      // 属格单数
  plural: string | null;        // 复数
  nounVariants: { g: string; gen: string | null; pl: string | null }[]; // 多性别名词逐性别范式束
  aux: string | null;           // haben / sein / both
  praeteritum: string | null;   // 过去式
  partizip2: string | null;     // 过去分词
  vclass: string | null;        // weak / strong / mixed（可带 ablaut 类号）
  separable: boolean;           // 可分动词
  sepPrefix: string | null;     // 可分前缀
  reflexive: boolean;           // 反身 sich
  comparative: string | null;
  superlative: string | null;
  government: string | null;    // 支配 Rektion（helfen +Dat、warten auf +Akk）
  level: string | null;
  senses: DeSense[];
  collocations: DeCollocation[];
  baseForms: string[];
  bases: DeBase[];
  inflNotes: string[];
  flag: string | null;
};

type AnyEntry = EnEntry | SpanishEntry | ItEntry | FrEntry | PtEntry | DeEntry;

// 'rate' = throttled by the API (429/503); 'network' = anything else went wrong.
type FetchError = 'rate' | 'network';

const EXAMPLES: Record<string, string[]> = {
  en: ['serene', 'ephemeral', 'resilience', 'curious', 'nuance', 'vivid'],
  es: ['hola', 'escalera', 'hablar', 'corazón', 'mariposa', 'rápido'],
  it: ['ciao', 'mangiare', 'braccio', 'bello', 'andare', 'città'],
  fr: ['bonjour', 'manger', 'journal', 'beau', 'aller', 'heureux'],
  pt: ['olá', 'falar', 'livro', 'bonito', 'pão', 'saudade'],
  de: ['Haus', 'gehen', 'ankommen', 'gut', 'Frau', 'schön'],
};

// --- English parsing helpers ---

function parseTranslation(raw: string | null): { pos: string; text: string }[] {
  if (!raw) return [];
  return raw.split(/\\n|\r?\n/).filter((l) => l.trim()).map((line) => {
    const match = line.match(/^([a-z]+\.)\s*(.+)$/);
    if (match) return { pos: match[1], text: match[2] };
    return { pos: '', text: line };
  });
}

function parseDefinition(raw: string | null): { pos: string; text: string }[] {
  if (!raw) return [];
  return raw.split(/\\n|\r?\n/).filter((l) => l.trim()).map((line) => {
    const match = line.match(/^([a-z]+\.)\s*(.+)$/);
    if (match) return { pos: match[1], text: match[2] };
    const match2 = line.match(/^([a-z])\s+(.+)$/);
    if (match2) return { pos: match2[1] + '.', text: match2[2] };
    return { pos: '', text: line };
  });
}

const EXCHANGE_SKIP_KEYS = new Set(['1']);

function parseExchange(raw: string | null): { label: string; words: string[] }[] {
  if (!raw) return [];
  return raw.split('/').filter(Boolean)
    .filter((part) => !EXCHANGE_SKIP_KEYS.has(part.split(':')[0]))
    .map((part) => {
      const [key, ...rest] = part.split(':');
      const words = rest.join(':').split(',').filter(Boolean);
      return { label: EXCHANGE_LABELS[key] || key, words };
    })
    .filter((item) => item.words.length > 0);
}

function parseTags(raw: string | null): string[] {
  if (!raw) return [];
  const TAG_NAMES: Record<string, string> = {
    zk: '中考', gk: '高考', ky: '考研', cet4: '四级', cet6: '六级',
    ielts: '雅思', toefl: '托福', gre: 'GRE',
  };
  return raw.split(/\s+/).filter(Boolean).map((t) => TAG_NAMES[t] || t);
}

// --- Spanish display helpers ---

// 词性短码 → 中文（支持 "n/v" 这种聚合，逐段映射后再拼），全站统一显示。
function posLabel(raw: string | null): string {
  if (!raw) return '';
  return raw.split('/').map((p) => POS_LABELS[p] || p).join('/');
}

// 真人录音行。音频托管在 Wikimedia Commons，我们只存 URL、在线播，不下载字节。
// 🔴 dump 里的 URL 实测约 **10% 已失效**（404/302），所以播放失败必须有兜底：
//    自动降到浏览器 TTS，并把这条标灰，不能让用户点了没反应。
// 🔴 2026-08-11 用户定：**页面不展示真人录音，但库里的数据不删**。
//
// 决定的依据是实测出来的三个数，不是嫌它质量差：
//   · 覆盖上几乎无损 —— 有真人录音的 9,709 个词形里 **95.5% 已经有合成音**，
//     真正「只有真人、没有合成音」的只剩 **434 个**；而合成音铺了 196,122 个词形（20 倍）。
//   · 代价却是永久的 —— 真人录音是三级兜底里**唯一有外网依赖**的一级：
//     字节在 Commons，落盘要 276 MB / 6–9 小时，且 `upload.wikimedia.org` 是面向读者的
//     媒体 CDN、**有意限流**（8 并发只涨到 0.6 条/秒，却换来 220 次重试 + 25 条 429），
//     没有整包可下（Commons 媒体不进 dump；Lingua Libre 的 Download ZIP 也是浏览器端逐条抓）。
//   · 而且降级是**静默**的 —— 死链时这个组件会悄悄换成 TTS，用户以为自己听到的是真人。
//
// ⚠️ 做成开关而不是删掉组件，是因为**前提还没验**：`gen_tts.py:338` 喂给 Piper 的是
//    **词形拼写**（`speech_text(word)`），不是我们已核过的 IPA —— 这违反 2026-08-01 定的
//    TTS 硬条件①。西语正字法规则强，多数词无妨，但外来词（`software ˈsofdw̝eɾ`、
//    `web ˈw̝eb`、`Kuwait kuˈw̝ait`）很可能被 Piper 按西语规则念错，而那正是
//    「标着 A、念出来是 B」——以音频的权威姿态给错读音，比没有音频更伤。
//    ⇒ 等 Piper 音素化 vs 库内 IPA 的逐条 diff 跑出来，再决定这个开关是删还是留。
//    数据一直在 `audio` 表里（11,203 条，仅 5.47 MB），改回 true 即可恢复。
const SHOW_HUMAN_AUDIO = false;

// 真人录音行。**语种无关**：只认「能播的一条录音」这个结构，地区文案由调用方给函数。
// 🔴 2026-08-18 从"只吃 SpanishAudio"改成结构化类型 —— 意语要用同一个组件，
//    而两边只差一个地区映射（es 是 `Bolivia` 这类标准码，it 是法语版写的 `Monopoli (Italie)`）。
//    照抄一份 it 版会让「播放/死链兜底/正在播」三段逻辑各有两个副本
//    （`refactor-mindset-code-quality`：塞第二份同类东西前先看已有那份能不能复用）。
type PlayableAudio = {
  file: string;
  url: string | null;
  speaker?: string | null;
  region?: string | null;
  regionSrc?: string | null;
  ipa?: string | null;
};

function HumanAudioRow({ audios, word, fallback, regionLabel }: {
  audios: PlayableAudio[]; word: string; fallback: () => void;
  regionLabel: (raw: string) => string;
}) {
  const [playing, setPlaying] = useState<string | null>(null);
  const [dead, setDead] = useState<Record<string, true>>({});
  const usable = audios.filter((a) => a.url);
  if (usable.length === 0) return null;

  const play = (a: PlayableAudio) => {
    if (!a.url || dead[a.file]) return;
    const el = new Audio(a.url);
    setPlaying(a.file);
    const giveUp = () => {
      setPlaying(null);
      setDead((d) => ({ ...d, [a.file]: true }));
      fallback();                       // 死链 → 立刻用 TTS 补上，别静默失败
    };
    el.onended = () => setPlaying(null);
    el.onerror = giveUp;
    el.play().catch(giveUp);
  };

  return (
    <div className="audio-row">
      <span className="audio-row-label">真人发音</span>
      {usable.map((a) => {
        const region = a.region ? regionLabel(a.region) : '未标注';
        const hint = [
          a.speaker ? `录音人 ${a.speaker}` : null,
          a.regionSrc === 'speaker' ? '地区按录音人推定' :
            a.regionSrc === 'tag' ? '地区为原始标注' :
            a.regionSrc === 'filename' ? '地区取自文件名' : null,
          a.ipa ? `对应读音 ${a.ipa}` : null,
          dead[a.file] ? '⚠️ 该录音链接已失效，已改用合成音' : null,
        ].filter(Boolean).join(' · ');
        return (
          <button
            key={a.file}
            className={'audio-chip' + (playing === a.file ? ' playing' : '') + (dead[a.file] ? ' dead' : '')}
            onClick={() => play(a)}
            title={hint || word}
            type="button"
          >
            <SpeakerIcon />
            <span className="audio-region">{region}</span>
            {a.regionSrc === 'speaker' && <span className="audio-inferred" title="地区按录音人推定">~</span>}
          </button>
        );
      })}
    </div>
  );
}

// 关系组：同一 kind 的目标词并成一行，可点的给锚点链接。
function RelationRow({ rels, onWord }: {
  rels: SpanishRelation[]; onWord: (w: string) => void;
}) {
  if (rels.length === 0) return null;
  const byKind = new Map<string, SpanishRelation[]>();
  for (const r of rels) {
    const a = byKind.get(r.kind);
    if (a) a.push(r); else byKind.set(r.kind, [r]);
  }
  return (
    <div className="rel-groups">
      {[...byKind].map(([kind, list]) => (
        <div className="rel-group" key={kind}>
          <span className="rel-kind">{REL_LABELS[kind] || kind}</span>
          {list.map((r, i) => (
            <span key={i} className="rel-item">
              {r.linkable
                ? <a className="rel-link" href={`#${encodeURIComponent(r.target)}`}
                     onClick={(ev) => { ev.preventDefault(); onWord(r.target); }}>{r.target}</a>
                : <span className="rel-plain">{r.target}</span>}
              {/* 🔴 2026-08-21：原来是 `r.tags.join('·')` —— 把原始英文标签直接印出来
                  （`casilla diminutive`、`近义 diñar slang`）。映射表的家在
                  `@synapse-dict/dict-labels`，不在这里新增。空串＝有意不显示
                  （`synonym` 这类关系类型自身作标签是冗余的）。 */}
              {(() => {
                const zh = r.tags.map(relTagLabel).filter(Boolean);
                return zh.length > 0 && <span className="rel-tag">{zh.join('·')}</span>;
              })()}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

// 统一义项按相邻相同词性分组。**相邻聚合而非按 pos 归类** ——
// 义项顺序本身有意义（`rank`），按 pos 重排会打乱它。
function groupUnifiedByPos(
  senses: SpanishUnifiedSense[],
): { pos: string | null; senses: SpanishUnifiedSense[] }[] {
  const out: { pos: string | null; senses: SpanishUnifiedSense[] }[] = [];
  for (const s of senses) {
    const last = out[out.length - 1];
    if (last && last.pos === s.pos) last.senses.push(s);
    else out.push({ pos: s.pos, senses: [s] });
  }
  return out;
}

// 语音列表是异步加载的，首帧 getVoices() 常为空 → 缓存 + onvoiceschanged 兜底。
let voiceCache: SpeechSynthesisVoice[] = [];
function refreshVoices() {
  if (typeof window === 'undefined' || !window.speechSynthesis) return;
  const v = window.speechSynthesis.getVoices();
  if (v.length) voiceCache = v;
}
if (typeof window !== 'undefined' && window.speechSynthesis) {
  refreshVoices();
  window.speechSynthesis.addEventListener('voiceschanged', refreshVoices);
}

// 🔴 macOS 附带一批**搞笑音**（Ventura 起还给它们配了各语言版本）。实测这台机器上
// 西语语音共 18 个，其中 16 个是 Eddy / Flo / Grandma / Grandpa / Reed / Rocko /
// Sandy / Shelley（每个 ×es_ES/es_MX），**真发音人只有 Mónica 和 Paulina 两个**。
// 原来的 `find(第一个语言匹配)` 按字母序会先撞上 Eddy ⇒ 用户听到的是滑稽音，
// 还会以为"这词典发音真难听"。词典的发音是**权威性的一部分**，不能交给运气。
const NOVELTY_VOICES = new Set([
  'eddy', 'flo', 'grandma', 'grandpa', 'reed', 'rocko', 'sandy', 'shelley',
  'albert', 'bad news', 'bahh', 'bells', 'boing', 'bubbles', 'cellos',
  'deranged', 'good news', 'hysterical', 'jester', 'junior', 'kathy', 'organ',
  'superstar', 'trinoids', 'whisper', 'wobble', 'zarvox', 'bruce', 'fred',
  'ralph', 'agnes', 'princess', 'victoria', 'zuzana',
]);

// 搞笑音的名字形如 `Eddy (西班牙语（西班牙）)` —— 取括号前那截来判定。
function isNovelty(v: SpeechSynthesisVoice): boolean {
  const base = v.name.split(/[(（]/)[0].trim().toLowerCase();
  return NOVELTY_VOICES.has(base);
}

// 按 locale 找语音：先剔搞笑音，再精确匹配（es-ES），再退到同语言（任意 es-*）。
// 全被剔光时才回到未过滤的列表 —— 宁可用搞笑音，也好过完全没声音。
function findVoice(locale: string): SpeechSynthesisVoice | null {
  if (voiceCache.length === 0) refreshVoices();
  const lc = locale.toLowerCase();
  const base = lc.split('-')[0];
  const pick = (pool: SpeechSynthesisVoice[]) =>
    pool.find((v) => v.lang.toLowerCase() === lc) ||
    pool.find((v) => v.lang.toLowerCase().replace('_', '-') === lc) ||
    pool.find((v) => v.lang.toLowerCase().startsWith(base)) ||
    null;
  const real = voiceCache.filter((v) => !isNovelty(v));
  return pick(real) || pick(voiceCache);
}

// 读词。挑到匹配语音就用它并返回 true；一个都没有 → 返回 false（调用方给提示，
// 不 return 前的 speak 仍会执行：浏览器可能用默认音兜底，但那多半读不准）。
function speak(word: string, locale: string): boolean {
  if (typeof window === 'undefined' || !window.speechSynthesis) return false;
  const voice = findVoice(locale);
  const utterance = new SpeechSynthesisUtterance(word);
  if (voice) utterance.voice = voice;
  utterance.lang = locale;
  utterance.rate = 0.9;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
  return !!voice;
}

function classifyResponse(res: Response) {
  if (res.status === 429 || res.status === 503) {
    const err = new Error('rate') as Error & { kind: FetchError };
    err.kind = 'rate';
    throw err;
  }
  if (!res.ok) {
    const err = new Error('network') as Error & { kind: FetchError };
    err.kind = 'network';
    throw err;
  }
}

function errorKind(e: unknown): FetchError {
  return (e as { kind?: FetchError })?.kind === 'rate' ? 'rate' : 'network';
}

// --- Theme ---

type Theme = 'light' | 'dark';

function getInitialTheme(): Theme {
  try {
    const saved = localStorage.getItem('dict-theme');
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // localStorage may be unavailable (private mode) — fall through
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

// 用上次缓存的语言列表初始化，让语言栏首帧就在位、不再加载后弹入（避免布局跳动）。
function getInitialLanguages(): LanguageMeta[] {
  try {
    const saved = localStorage.getItem('dict-langs');
    if (saved) return JSON.parse(saved) as LanguageMeta[];
  } catch {
    // ignore
  }
  return [];
}

// 存下来的语种码在这里就核一次，别等 /api/langs 回来。
//
// 🔴 `/api/langs` 回来之后确实会核对（见下面那个 effect 里的 setLang），但那是
//    **一个网络往返之后**的事。在那之前，首帧和首批 /api/search 用的都是这个值 ——
//    存了个已下线/拼错的码（改过 localStorage、或某个语种下线了），就会先打出一批
//    落到后端回退分支的请求。后端那条回退是对的（响应里如实标 lang），
//    但那意味着**用户看到的是另一门语言的结果，而语言栏高亮的是他选的那个**。
//
// 判据用的就是上一次缓存下来的语言表 —— 同步可读、零成本、不多发一个请求。
// 缓存为空（首次访问/清过缓存）时不拦：那时没有可信的判据，拦了等于永远回退到 en。
export function getInitialLang(): string {
  try {
    const saved = localStorage.getItem('dict-lang');
    if (!saved) return 'en';
    const known = getInitialLanguages();
    if (known.length === 0 || known.some((l) => l.code === saved)) return saved;
  } catch {
    // ignore
  }
  return 'en';
}

const SpeakerIcon = () => (
  <svg className="phonetic-speaker" viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
    <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z" />
  </svg>
);

function CollinsStars({ rating }: { rating: number | null }) {
  if (!rating) return null;
  return (
    <span className="collins-stars" title={`Collins ${rating} 星`}>
      {'★'.repeat(rating)}{'☆'.repeat(5 - rating)}
    </span>
  );
}

// --- App ---

export default function App() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [languages, setLanguages] = useState<LanguageMeta[]>(getInitialLanguages);
  const [lang, setLang] = useState<string>(getInitialLang);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchItem[]>([]);
  const [searchError, setSearchError] = useState<FetchError | null>(null);
  const [selectedWord, setSelectedWord] = useState<string | null>(null);
  const [entry, setEntry] = useState<AnyEntry | null>(null);
  const [entryError, setEntryError] = useState<FetchError | null>(null);
  const [entryNotFound, setEntryNotFound] = useState(false);
  const [loading, setLoading] = useState(false);
  const [entryLoading, setEntryLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultListRef = useRef<HTMLDivElement>(null);
  const langInitDone = useRef(false);
  const toastTimer = useRef<number | undefined>(undefined);

  const activeLang = languages.find((l) => l.code === lang);
  const speakLocale = activeLang?.speak || 'en-US';

  // 读词入口：设备缺该语言语音时弹一条非阻塞提示（浏览器会用默认音兜底，多半读不准）。
  const speakWord = useCallback((word: string, locale: string) => {
    if (speak(word, locale)) return;
    const base = locale.split('-')[0];
    const label = languages.find((l) => l.speak.split('-')[0] === base)?.name || '该语言';
    setToast(`当前设备未安装${label}语音，发音可能不准确`);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4000);
  }, [languages]);

  // Apply + persist theme
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem('dict-theme', theme);
    } catch {
      // ignore persistence failures
    }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'));
  }, []);

  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  // Load available languages once; reconcile the persisted choice.
  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch('/api/langs');
        const data = await res.json();
        const langs = (data.languages || []) as LanguageMeta[];
        setLanguages(langs);
        try { localStorage.setItem('dict-langs', JSON.stringify(langs)); } catch { /* ignore */ }
        setLang((cur) => (langs.some((l) => l.code === cur) ? cur : data.default || langs[0]?.code || 'en'));
      } catch {
        // API down — leave selector empty, English default still works
      }
    })();
  }, []);

  // Persist language + reset the view when it actually changes (skip first settle).
  useEffect(() => {
    try {
      localStorage.setItem('dict-lang', lang);
    } catch {
      // ignore
    }
    if (!langInitDone.current) {
      langInitDone.current = true;
      return;
    }
    // 切换语言不清空详情：由 search 效应重新选词，旧词条保留到新词条就绪，
    // 避免详情区先回弹欢迎页再显示新词（那个来回就是偶发的“闪一下”）。
    setEntryError(null);
  }, [lang]);

  // Hash routing: read word from URL on mount
  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (hash) {
      const word = decodeURIComponent(hash);
      setSelectedWord(word);
      setQuery(word);
    }
    const onHashChange = () => {
      const h = window.location.hash.slice(1);
      if (h) setSelectedWord(decodeURIComponent(h));
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const selectWord = useCallback((word: string) => {
    setSelectedWord(word);
    window.location.hash = encodeURIComponent(word);
  }, []);

  const pickExample = useCallback((word: string) => {
    setQuery(word);
    selectWord(word);
    inputRef.current?.focus();
  }, [selectWord]);

  // Search
  useEffect(() => {
    const keyword = query.trim();
    if (!keyword) {
      setResults([]);
      setSearchError(null);
      return;
    }

    const timer = window.setTimeout(async () => {
      try {
        setLoading(true);
        setSearchError(null);
        const response = await fetch(`/api/search?q=${encodeURIComponent(keyword)}&limit=20&lang=${lang}`);
        classifyResponse(response);
        const data = await response.json();
        const items = (data.items || []) as SearchItem[];
        setResults(items);
        // 🔴 2026-08-12 修闪动：这里原本无条件 `selectWord(items[0].word)`，
        //    会把**用户已经点中的词**在 200ms 后踢掉换成搜索首条 ——
        //    点词条内链接走 `goToWord`，它同时 setQuery(触发本效应) 和 selectWord(立即加载)，
        //    本效应回来后就覆盖了后者。实测 200 个高频词有 19 个(9.5%)会自己变：
        //    `a`→`A`、`como`→`Como`、`ser`→`SER`、`vida`→`Vida`（小写词被大写专名顶掉，
        //    根因是 /api/search 没把精确大小写当第一排序键）。用户体感即"页面无端闪一下"。
        // ⇒ 查询词精确出现在结果里就选它；只有前缀搜索（`cas` 尚未匹配到词）才退回首条，
        //    这样"边搜边预览"的行为不变。同时让高亮跟着实际选中的那条走。
        if (items.length > 0) {
          const exactIndex = items.findIndex((i) => i.word === keyword);
          const pick = exactIndex >= 0 ? exactIndex : 0;
          setActiveIndex(pick);
          selectWord(items[pick].word);
        } else {
          setActiveIndex(0);
        }
      } catch (e) {
        setResults([]);
        setSearchError(errorKind(e));
      } finally {
        setLoading(false);
      }
    }, 200);

    return () => window.clearTimeout(timer);
  }, [query, lang, selectWord, reloadKey]);

  // Load entry
  useEffect(() => {
    if (!selectedWord) {
      setEntry(null);
      setEntryError(null);
      setEntryNotFound(false);
      return;
    }

    let cancelled = false;
    async function loadEntry() {
      try {
        setEntryLoading(true);
        setEntryError(null);
        const response = await fetch(`/api/entries/${encodeURIComponent(selectedWord!)}?lang=${lang}`);
        // 404 = 词典里没这个词（正常情形，非故障）→ 标记查无此词，别当网络错误报错。
        // 不清旧 entry：沿用 SWR，保住上一个词条不闪；查无此词只在无词条可显时才露出，
        // 这样切语言/失效链接触发的瞬时 404 不会把当前词条闪没。
        if (response.status === 404) {
          if (!cancelled) setEntryNotFound(true);
          return;
        }
        classifyResponse(response);
        if (!cancelled) { setEntry(await response.json()); setEntryNotFound(false); }
      } catch (e) {
        if (!cancelled) setEntryError(errorKind(e));  // 保留旧词条，不闪空
      } finally {
        if (!cancelled) setEntryLoading(false);
      }
    }
    void loadEntry();
    return () => { cancelled = true; };
  }, [selectedWord, lang, reloadKey]);

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = Math.min(activeIndex + 1, results.length - 1);
      setActiveIndex(next);
      if (results[next]) selectWord(results[next].word);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = Math.max(activeIndex - 1, 0);
      setActiveIndex(prev);
      if (results[prev]) selectWord(results[prev].word);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (results[activeIndex]) selectWord(results[activeIndex].word);
    }
  };

  useEffect(() => {
    const container = resultListRef.current;
    if (!container) return;
    const active = container.querySelector('.result-item.active');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  const goToWord = useCallback((word: string) => {
    setQuery(word);
    selectWord(word);
  }, [selectWord]);

  return (
    <div className="dict-app">
      <div className="search-column">
        <div className="brand-bar">
          <div className="brand">
            <div className="brand-mark">突</div>
            <div>
              <div className="brand-name">突触词典</div>
              <div className="brand-sub">Synapse Dict</div>
            </div>
          </div>
          <button
            className="theme-toggle"
            onClick={toggleTheme}
            title={theme === 'dark' ? '切换到浅色' : '切换到深色'}
            aria-label="切换主题"
            type="button"
          >
            {theme === 'dark' ? (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M6.76 4.84l-1.8-1.79-1.41 1.41 1.79 1.79 1.42-1.41zM4 10.5H1v2h3v-2zm9-9.95h-2V3.5h2V.55zm7.45 3.91l-1.41-1.41-1.79 1.79 1.41 1.41 1.79-1.79zm-3.21 13.7l1.79 1.8 1.41-1.41-1.8-1.79-1.4 1.4zM20 10.5v2h3v-2h-3zm-8-5c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm-1 16.95h2V19.5h-2v2.95zm-7.45-3.91l1.41 1.41 1.79-1.8-1.41-1.41-1.79 1.8z" /></svg>
            ) : (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.389 5.389 0 0 1-4.4 2.26 5.403 5.403 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z" /></svg>
            )}
          </button>
        </div>

        {languages.length > 1 && (
          <div className="lang-switch" role="tablist" aria-label="词典语言">
            {languages.map((l) => (
              <button
                key={l.code}
                className={l.code === lang ? 'lang-pill active' : 'lang-pill'}
                onClick={() => setLang(l.code)}
                type="button"
                role="tab"
                aria-selected={l.code === lang}
                title={l.label}
              >
                {l.name}
              </button>
            ))}
          </div>
        )}

        <div className="search-input-wrap">
          <svg className="search-icon" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
          <input
            ref={inputRef}
            className="search-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={activeLang ? `查询${activeLang.name}…` : '输入单词查询…'}
            autoFocus
          />
          {loading && <span className="search-spinner" />}
        </div>

        <div className="result-list" ref={resultListRef}>
          {results.map((item, i) => (
            <button
              className={i === activeIndex ? 'result-item active' : 'result-item'}
              key={item.id}
              onClick={() => { setActiveIndex(i); selectWord(item.word); }}
              type="button"
            >
              <span className="result-word">{item.word}</span>
              <span className="result-brief">{item.brief || ''}</span>
            </button>
          ))}

          {!loading && searchError === 'rate' && (
            <div className="list-hint error">
              <span className="hint-emoji">🌊</span>
              查询有点频繁，稍等一下再试～
              <br />
              <button className="retry-btn" onClick={retry} type="button">重新查询</button>
            </div>
          )}
          {!loading && searchError === 'network' && (
            <div className="list-hint error">
              <span className="hint-emoji">😕</span>
              查询没能完成，请检查网络后重试
              <br />
              <button className="retry-btn" onClick={retry} type="button">重新查询</button>
            </div>
          )}
          {!loading && !searchError && query.trim() && results.length === 0 && (
            <div className="list-hint">
              <span className="hint-emoji">🔍</span>
              没有找到匹配词条
            </div>
          )}
        </div>
      </div>

      <div className="detail-column">
        {/* SWR：有词条就一直显示（含切换/加载中），避免闪空或回弹欢迎页 */}
        {entry && entry.lang === 'en' && (
          <EnglishEntry entry={entry as EnEntry} onWord={goToWord} speak={speakWord} />
        )}

        {entry && entry.lang === 'it' && (
          <ItalianEntryView entry={entry as ItEntry} speakLocale={speakLocale} onWord={goToWord} speak={speakWord} />
        )}

        {entry && entry.lang === 'fr' && (
          <FrenchEntryView entry={entry as FrEntry} speakLocale={speakLocale} onWord={goToWord} speak={speakWord} />
        )}

        {entry && entry.lang === 'pt' && (
          <PortugueseEntryView entry={entry as PtEntry} onWord={goToWord} speak={speakWord} />
        )}

        {entry && entry.lang === 'de' && (
          <GermanEntryView entry={entry as DeEntry} speakLocale={speakLocale} onWord={goToWord} speak={speakWord} />
        )}

        {entry && entry.lang !== 'en' && entry.lang !== 'it' && entry.lang !== 'fr' && entry.lang !== 'pt' && entry.lang !== 'de' && (
          <SpanishEntryView entry={entry as SpanishEntry} speakLocale={speakLocale} onWord={goToWord} speak={speakWord} />
        )}

        {!entry && entryLoading && <div className="detail-loading">加载中…</div>}

        {!entry && !entryLoading && entryError && (
          <div className="detail-error">
            <span className="hint-emoji">{entryError === 'rate' ? '🌊' : '😕'}</span>
            <p>{entryError === 'rate' ? '请求有点频繁，稍等一下再试～' : '词条加载失败，请稍后重试'}</p>
            <button className="retry-btn" onClick={retry} type="button">重试</button>
          </div>
        )}

        {!entry && !entryLoading && !entryError && entryNotFound && selectedWord && (
          <div className="detail-error">
            <span className="hint-emoji">🔍</span>
            <p>词典中没有「{selectedWord}」这个词条</p>
          </div>
        )}

        {!entry && !entryLoading && !entryError && !selectedWord && (
          <div className="empty-state">
            <div className="empty-logo">突</div>
            <h1 className="empty-title">突触词典</h1>
            <p className="empty-desc">
              {activeLang ? `${activeLang.name}词典` : '多语言词典'}
              ，含释义、音标、发音与词形变化。<br />
              在左侧输入即可查询{languages.length > 1 ? '，上方可切换语言' : ''}。
            </p>
            <div className="example-label">试试这些词</div>
            <div className="example-chips">
              {(EXAMPLES[lang] || EXAMPLES.en).map((w) => (
                <button className="example-chip" key={w} onClick={() => pickExample(w)} type="button">
                  {w}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {toast && <div className="speak-toast" role="status">{toast}</div>}
    </div>
  );
}

// --- English entry detail (unchanged layout) ---

function EnglishEntry({ entry, onWord, speak }: {
  entry: EnEntry; onWord: (w: string) => void; speak: (word: string, locale: string) => void;
}) {
  const translations = parseTranslation(entry.translation);
  const definitions = parseDefinition(entry.definition);
  const exchanges = parseExchange(entry.exchange);
  const tags = parseTags(entry.tag);

  return (
    <article className="entry-detail">
      <header className="entry-header">
        <h2 className="entry-word">{entry.word}</h2>
        <div className="entry-meta-row">
          <CollinsStars rating={entry.collins} />
          {entry.oxford === 1 && <span className="badge oxford">Oxford 3000</span>}
          {tags.map((t) => <span className="badge tag" key={t}>{t}</span>)}
        </div>
      </header>

      <div className="phonetic-row">
        {entry.phoneticUk && (
          <button className="phonetic-btn" onClick={() => speak(entry.word, 'en-GB')} title="播放英式发音" type="button">
            <span className="phonetic-label">英</span>
            <span className="phonetic-value">/{entry.phoneticUk}/</span>
            <SpeakerIcon />
          </button>
        )}
        {entry.phoneticUs && (
          <button className="phonetic-btn" onClick={() => speak(entry.word, 'en-US')} title="播放美式发音" type="button">
            <span className="phonetic-label">美</span>
            <span className="phonetic-value">/{entry.phoneticUs}/</span>
            <SpeakerIcon />
          </button>
        )}
        {!entry.phoneticUk && !entry.phoneticUs && (
          <button className="phonetic-btn" onClick={() => speak(entry.word, 'en-US')} title="播放发音" type="button">
            {entry.phonetic && <span className="phonetic-value">/{entry.phonetic}/</span>}
            <SpeakerIcon />
          </button>
        )}
      </div>

      {translations.length > 0 && (
        <section className="entry-section">
          <h3>释义</h3>
          <dl className="definition-list">
            {translations.map((item, i) => (
              <div className="def-item" key={i}>
                {item.pos && <dt>{item.pos}</dt>}
                <dd>{item.text}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {definitions.length > 0 && (
        <section className="entry-section">
          <h3>English</h3>
          <dl className="definition-list en">
            {definitions.map((item, i) => (
              <div className="def-item" key={i}>
                {item.pos && <dt>{item.pos}</dt>}
                <dd>{item.text}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {exchanges.length > 0 && (
        <section className="entry-section">
          <h3>词形变化</h3>
          <div className="exchange-list">
            {exchanges.map((ex) => (
              <div className="exchange-item" key={ex.label}>
                <span className="exchange-label">{ex.label}</span>
                <span className="exchange-words">
                  {ex.words.map((w) => (
                    <a key={w} className="exchange-link" href={`#${encodeURIComponent(w)}`}
                      onClick={(e) => { e.preventDefault(); onWord(w); }}>
                      {w}
                    </a>
                  ))}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {(entry.bnc != null && entry.bnc > 0 || entry.frq != null && entry.frq > 0) && (
        <section className="entry-section">
          <h3>词频</h3>
          <div className="freq-row">
            {entry.bnc != null && entry.bnc > 0 && <span className="freq-item">BNC: <strong>{entry.bnc}</strong></span>}
            {entry.frq != null && entry.frq > 0 && <span className="freq-item">COCA: <strong>{entry.frq}</strong></span>}
          </div>
        </section>
      )}
    </article>
  );
}

// --- Spanish entry detail ---

// 两种 sense shape 共用（旧的 SpanishSense 与新的 SpanishUnifiedSense），
// 后者多一个 topics（主题标签，`escalera` 的"顺子"义带 poker）。
function SenseChips({ sense }: { sense: SpanishSense | SpanishUnifiedSense }) {
  const chips: { cls: string; text: string }[] = [];
  if (sense.gender) chips.push({ cls: `g g-${sense.gender}`, text: GENDER_LABELS[sense.gender] || sense.gender });
  for (const t of ('topics' in sense ? sense.topics : [])) chips.push({ cls: 'top', text: TOPIC_LABELS[t] || t });
  for (const r of sense.regions) chips.push({ cls: 'reg', text: ES_REGION_LABELS[r] || r });
  for (const r of sense.registers) chips.push({ cls: 'lex', text: REGISTER_LABELS[r] || r });
  for (const n of sense.numbers) chips.push({ cls: 'num', text: NUMBER_LABELS[n] || n });
  if (chips.length === 0) return null;
  return (
    <span className="sense-chips">
      {chips.map((c, i) => <span className={`sense-chip ${c.cls}`} key={i}>{c.text}</span>)}
    </span>
  );
}

// 导出供 `contract-check-es.tsx` 渲染 —— 契约闸必须用**组件本身**，
// 不能自己复刻一份渲染逻辑（那样验的是复刻件，不是用户看到的东西）。
// 义项折叠阈值。**导出**供契约闸使用 —— 闸要断言「首屏那一段必须渲染」，
// 自己复制一个 8 就等于两处各写一份，改一处另一处静默失效。
export const SENSE_FOLD_AT_ES = 8;

export function SpanishEntryView({ entry, speakLocale, onWord, speak }: {
  entry: SpanishEntry; speakLocale: string; onWord: (w: string) => void;
  speak: (word: string, locale: string) => void;
}) {
  // 义项折叠（2026-08-11）。产品是**划词弹窗**，"字段轻快够用"是既定范围，
  // 而 `mano` 有 26 条义项、一屏铺不下，冷僻义（一令纸的二十分之一 / 狩猎围猎的每一次）
  // 会把「手」淹掉。
  // ⚠️ 只折叠**显示**，不删数据 —— 冷僻义仍然可检索、展开即见。
  // 🔴 阈值取固定条数而不是「只展开两版都收录的那些」：后者虽然更"聪明"
  //    （`mano` 恰好在第 8 条断开：1–8 两版都有，9–26 只有西语版），
  //    但对用户是**不可预测**的 —— 这个词展开 3 条、那个展开 12 条，说不出理由。
  //    固定条数至少是可解释的。
  const [showAllSenses, setShowAllSenses] = useState(false);
  const SENSE_FOLD_AT = SENSE_FOLD_AT_ES;
  useEffect(() => { setShowAllSenses(false); }, [entry.id]);   // 换词回到折叠态

  // 方针④三级兜底在音标行上的落法：有成品合成音就播文件，没有才降到浏览器 TTS。
  // 🔴 **不能拿拉美那份去顶半岛按钮**：用户看着 /θeɾˈbeθa/ 却听到 serˈbesa，
  //    比听浏览器音更糟——错的音比没有音更伤。缺哪个口音就用哪个 locale 交给浏览器。
  const ttsOf = (accent: 'spain' | 'latam') =>
    entry.tts.find((t) => t.accent === accent) || null;

  const playAccent = (accent: 'spain' | 'latam', locale: string) => {
    const t = ttsOf(accent);
    if (!t) { speak(entry.word, locale); return; }
    const el = new Audio(t.url);
    // 文件可能被挪走/清掉（音频不进 git，换台机器就没有）⇒ 播不出照样要有声音
    el.onerror = () => speak(entry.word, locale);
    el.play().catch(() => speak(entry.word, locale));
  };

  const tierHint = (accent: 'spain' | 'latam') =>
    ttsOf(accent) ? '合成音（工具生成）' : '合成音（浏览器）';
  const showStubPos = entry.isLemma && !!entry.pos && !entry.senses.some((s) => s.pos);
  const posParts = entry.pos ? entry.pos.split('/') : [];

  // 🔴 2026-08-11 用户实测 `mano` 逮到的两个标注错误，根因是同一个：
  //    词头徽标读的是 `dict` 上的**跨义项折叠列**（v1 遗留），而逐义项的真值就在
  //    `unifiedSenses` 里躺着没被用。
  //
  //    ① 及物/不及物：`mano` 的 `pos` 是 `n/v` —— 因为它同时是 `manar` 的
  //       第一人称变位（“我流出”）。及物性来自那个**动词读法**，却显示在名词义项旁边。
  //       kaikki 里 mano 的 verb 块只有一条 `form-of`，没有任何及物性语义。
  //       同病 **3,670 个词形**：peso(pesar)、amigo(amigar)、llama(llamar)…
  //       ⇒ 判据换成「**有没有 pos='v' 的义项**」，光靠词形能当动词读不算。
  //
  //    ② 性别 el/la：`mano` 25 条义项是阴性，只有第 8 条（墨西哥俚语「兄弟」）是阳性
  //       —— 那在 kaikki 里是**另一个词条** `mano m`（DRAE 记作 mano²）。
  //       ⚠️ 这里原本的结论是「词头只显示主义项性别」，**2026-08-12 已被推翻**，
  //       改为词头做粗分、义项做细分 —— 见下面 `headGender` 处的判据。
  //
  //    ⚠️ 都要保留回退：变形形、无义项的词条在 `unifiedSenses` 里是空的，
  //       那时仍用词级列，否则这些词的徽标会整片消失。
  const senseHasPos = entry.unifiedSenses.some((s) => !!s.pos);
  const isVerb = senseHasPos
    ? entry.unifiedSenses.some((s) => s.pos === 'v')
    : posParts.includes('v');
  const isNoun = senseHasPos
    ? entry.unifiedSenses.some((s) => s.pos === 'n' || s.pos === 'name')
    : posParts.some((p) => p === 'n' || p === 'name');
  const isAdj = senseHasPos
    ? entry.unifiedSenses.some((s) => s.pos === 'adj' || s.pos === 'adv')
    : posParts.some((p) => p === 'adj' || p === 'adv');

  // 🔴 2026-08-21 词头徽标的**归属守卫**（与 it 的 A97 同一条判据，见 it-CONVENTIONS）。
  //    `isNoun` 只问「有没有一条名词义项」——`la` 有名词义（音名「拉」）就为真，
  //    于是词头给阴性定冠词标上了 `el · 阳`。全库 **64,393 个词形**这样。
  //    ⇒ 性/复数/阴性形只在**有义项的词性全是名词性**（n/name/adj，它们共享性数系统）
  //      时才显示；变位类/词干变化/过去分词/及物性只可能属于动词，有动词义项就显示。
  //    ⚠️ 变量名特意与意语段不同：App.tsx 五个语种共用一个文件，同名的话
  //      批量替换串到别的语种会**静默生效**（2026-08-21 已经这样搞崩过 es 一次）。
  //    ⚠️ 判据第一版写成「义项词性全是名词性才显示」，被外审逮到误伤：`banco` 有
  //       6 条名词义项 + 1 条**感叹词**义项（`¡banco!` 表强烈赞同），于是明确的
  //       `el · 阳` 被藏掉了。真正会冲突的不是「任何非名词词性」，而是**另一种也带性的
  //       词类** —— 冠词/代词/限定词有性且可能与名词的性相反（`la` ＝ art 阴 + n 阳）；
  //       感叹词/介词/动词/副词根本没有性，不影响名词那一支。
  const ES_NOMINAL = new Set(['n', 'name', 'adj']);
  const ES_GENDERED = new Set(['art', 'pron', 'det', 'contr']);   // 这些也带性 ⇒ 会打架
  const esPosScope = [...new Set(entry.unifiedSenses.map((s) => s.pos).filter(Boolean))];
  const esNounBadge = esPosScope.length === 0
    ? isNoun
    : esPosScope.some((p) => ES_NOMINAL.has(p!)) && !esPosScope.some((p) => ES_GENDERED.has(p!));
  const esVerbBadge = esPosScope.length === 0 ? isVerb : esPosScope.includes('v');

  // 词头性别 = **粗分**：这个词会不会碰到两种性别。细分（每条义项到底是哪个性别）
  // 由义项自己的小圆片承担，词头不重复也不替它回答。
  //
  // 🔴 2026-08-12 定的判据：只要该词的义项**合起来**同时涉及阴与阳，词头就标双性 ——
  //    不区分这两性来自不同义项（`radio`：la radio 收音机 / el radio 半径）还是
  //    来自同一义项内部（`fiscal` 第 5 义 `mf`：el/la fiscal，跟着人的性别走）。
  //    两者对读者的意思是同一句话：「这个词你会遇到两种冠词，往下看哪条是哪个」。
  //
  //    ⚠️ 这条**取代**了上面第②条「词头只显示主义项性别」的旧决定。旧决定是为了避免
  //    `mano` 词头印出 `el` 而被读成「手也能说 el mano」，代价是词头多了一个
  //    `*` 号 / 「另有阳性义项」这类要额外解释的符号 —— 用户实测两者都看不懂。
  //    现在把这份精度交还给义项圆片，词头只做粗分。
  //
  // `mf` 展开成阴阳两支再取并集：它自己就已经把两性都说了。
  const senseGenders = entry.unifiedSenses.map((s) => s.gender).filter(Boolean) as string[];
  const expandG = (g: string) => (g === 'mf' ? ['m', 'f'] : [g]);
  const genderSet = new Set(
    (senseGenders.length ? senseGenders : (entry.gender ? [entry.gender] : []))
      .flatMap(expandG),
  );
  const headGender = genderSet.has('m') && genderSet.has('f')
    ? 'mf'
    : (senseGenders[0] || entry.gender);
  const g0 = headGender ? headGender.split('/')[0] : null;
  return (
    <article className="entry-detail">
      <header className="entry-header">
        <h2 className="entry-word">{entry.word}</h2>
      </header>

      {/* 双音：ES 半岛(distinción θ) / LA 拉美(seseo s)，格式同英语 UK/US——字母标签+音标同在一标签内。
          分两个按钮的前提就是这个词含 θ、两地读法不同，所以两边各取各的音色。 */}
      {entry.phonetic && entry.phoneticLatam ? (
        <div className="phonetic-row">
          <button
            className={'phonetic-btn' + (ttsOf('spain') ? ' has-tts' : '')}
            onClick={() => playAccent('spain', 'es-ES')}
            title={`播放 西班牙(半岛) 发音 · ${tierHint('spain')}`} type="button"
          >
            <span className="phonetic-label">西</span>
            <span className="phonetic-value">/{entry.phonetic}/</span>
            <SpeakerIcon />
          </button>
          <button
            className={'phonetic-btn' + (ttsOf('latam') ? ' has-tts' : '')}
            onClick={() => playAccent('latam', 'es-MX')}
            title={`播放 拉美 发音 · ${tierHint('latam')}`} type="button"
          >
            <span className="phonetic-label">拉美</span>
            <span className="phonetic-value">/{entry.phoneticLatam}/</span>
            <SpeakerIcon />
          </button>
        </div>
      ) : entry.phonetic ? (
        /* 单按钮 = 音标无 θ = 两地读法本来就相同 ⇒ 拉美那份音色通用，直接拿来播。 */
        <div className="phonetic-row">
          <button
            className={'phonetic-btn' + (ttsOf('latam') ? ' has-tts' : '')}
            onClick={() => playAccent('latam', speakLocale)}
            title={`播放发音 · ${tierHint('latam')}`} type="button"
          >
            <span className="phonetic-value">/{entry.phonetic}/</span>
            <SpeakerIcon />
          </button>
        </div>
      ) : null}

      {/* 上面那排是合成音（TTS）。真人录音这一排 2026-08-11 起不展示，见 SHOW_HUMAN_AUDIO。 */}
      {SHOW_HUMAN_AUDIO && (
        <HumanAudioRow
          audios={entry.audios}
          word={entry.word}
          fallback={() => speak(entry.word, speakLocale)}
          regionLabel={(r) => ES_REGION_LABELS[r] || r}
        />
      )}


      {/* 西语本质徽标：CEFR 贯穿；名词性别 el/la/复数/阴性，动词变位类/词干变化/过去分词/及物性 */}
      <div className="entry-meta-row entry-badges">
        {entry.level && <span className={`badge cefr cefr-${entry.level[0]}`}>{entry.level}</span>}
        {esNounBadge && headGender && (
          <span className={`badge g g-${g0}`}>
            {ES_ARTICLE[headGender] || ''} · {GENDER_LABELS[headGender] || headGender}
          </span>
        )}
        {esNounBadge && entry.plural && <span className="badge plural">复数 {entry.plural}</span>}
        {esNounBadge && entry.feminine && <span className="badge fem">阴性形 {entry.feminine}</span>}
        {(isAdj || isVerb) && entry.comparative && <span className="badge cmp">比较级 {entry.comparative}</span>}
        {esVerbBadge && entry.conjugation && (
          <span className="badge conj">{ES_CONJ_LABELS[entry.conjugation] || entry.conjugation}</span>
        )}
        {esVerbBadge && entry.stemChange && <span className="badge sep">词干 {entry.stemChange}</span>}
        {esVerbBadge && entry.pp && <span className="badge pp">过去分词 {entry.pp}</span>}
        {esVerbBadge && entry.transitivity && (
          <span className="badge tag">{TRANS_LABELS[entry.transitivity] || entry.transitivity}</span>
        )}
        {entry.reflexive && <span className="badge tag">代动词</span>}
        {showStubPos && <span className="badge pos">{posLabel(entry.pos)}</span>}
      </div>

      {/* 释义。数据来自统一义项层（`sense`/`sense_gloss`/`sense_tag`）。
          🔴 2026-08-07 之前这里是**两个并列区块**：上面「释义」读 `dict` 的行号对齐列，
             下面「西语版释义」读 `sense_es` 表 —— 同一个词的两套义项摆在一起，
             `banco` 显示 4+7=11 条、「银行」出现两次。现在按 `en_i` 对齐结果归并成一套
             （`banco` 7 条、`ojo` 29→25），一条不丢，每条自带主键。
          标题行取最短的那条中文、副行取明显更长的那条 —— 服务端已挑好（见
          `spanish.ts` 的 `buildUnified`），前端不再判断。 */}
      {entry.unifiedSenses.length > 0 && (
        <section className="entry-section">
          <h3>释义</h3>
          {groupUnifiedByPos(
            showAllSenses ? entry.unifiedSenses : entry.unifiedSenses.slice(0, SENSE_FOLD_AT),
          ).map((grp, gi) => (
            <div className="pos-group" key={gi}>
              {grp.pos && (
                <div className="pos-group-label">{posLabel(grp.pos)}</div>
              )}
              <ol className="sense-list">
                {grp.senses.map((s) => (
                  <li className="sense-item" key={s.id}>
                    <div className="sense-zh">
                      {s.title}
                      <SenseChips sense={s} />
                    </div>
                    {s.detail && <div className="sense-detail">{s.detail}</div>}
                    <RelationRow rels={entry.relations.filter((r) => r.senseId === s.id)}
                                 onWord={onWord} />
                    {entry.examples.filter((x) => x.senseId === s.id).slice(0, 3).map((x) => (
                      <div className="sense-example" key={x.id}>
                        <div className="ex-es" lang="es">{x.text}</div>
                        {x.zh && <div className="ex-zh">{x.zh}</div>}
                      </div>
                    ))}
                    {/* 源语言锚点：英文对应词与西语单语定义。归并之后**同一条义项
                        可能两者都有**（旧结构下它们分属两条），所以不再是二选一。 */}
                    {s.en && (
                      <div className="sense-src" lang="en">
                        <span className="sense-src-lang">EN</span>{s.en}
                      </div>
                    )}
                    {s.es && (
                      <div className="sense-src" lang="es">
                        <span className="sense-src-lang">ES</span>{s.es}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          ))}
          {entry.unifiedSenses.length > SENSE_FOLD_AT && (
            <button type="button" className="sense-more"
                    onClick={() => setShowAllSenses((v) => !v)}>
              {showAllSenses
                ? '收起'
                : `展开其余 ${entry.unifiedSenses.length - SENSE_FOLD_AT} 条义项`}
            </button>
          )}
        </section>
      )}

      {/* 同形词：拼写只差大小写的另一个词条，同页并列。
          放在本词条释义之后、其余区块之前 —— 它是"另一个词"，不是本词的补充。 */}
      {entry.homographs.map((h) => (
        <section className="entry-section homograph" key={h.id}>
          <div className="homograph-head">
            <span className="homograph-word">{h.word}</span>
            {h.pos && <span className="badge pos">{posLabel(h.pos)}</span>}
            {h.phonetic && <span className="homograph-ipa">/{h.phonetic}/</span>}
          </div>
          {h.senses.length > 0 ? (
            <ol className="sense-list">
              {h.senses.map((s) => (
                <li className="sense-item" key={s.id}>
                  <div className="sense-zh">
                    {s.title}
                    <SenseChips sense={s} />
                  </div>
                  {s.detail && <div className="sense-detail">{s.detail}</div>}
                </li>
              ))}
            </ol>
          ) : <div className="sense-missing">（无释义）</div>}
        </section>
      ))}

      {/* 词级关系：`derived`（派生词/习语）没有义项归属，单独成块。
          义项级的已经跟着各自的义项显示了。 */}
      {entry.relations.some((r) => !r.senseId) && (
        <section className="entry-section">
          <h3>相关词</h3>
          <RelationRow rels={entry.relations.filter((r) => !r.senseId)} onWord={onWord} />
        </section>
      )}

      {/* 没挂上义项的例句（src_gloss 匹配不上那 21%）：仍要显示，只是归不到某条义项下 */}
      {entry.examples.some((x) => !x.senseId) && (
        <section className="entry-section">
          <h3>例句</h3>
          {entry.examples.filter((x) => !x.senseId).slice(0, 6).map((x) => (
            <div className="sense-example" key={x.id}>
              <div className="ex-es" lang="es">{x.text}</div>
              {x.zh && <div className="ex-zh">{x.zh}</div>}
            </div>
          ))}
        </section>
      )}

      {/* 补收的词头（2026-08-20，8,075 个）：源头只有变形页、没有词头页，
          我们按证据补了词形/词性/规则音标，但**没有释义** ——
          模型盲推这批生僻词的错误率实测卡在 24–25%，宁可留诚实空白。
          这一块让页面至少能回答「它有哪些变形形」，而不是一片空白。
          🔴 条件带 `unifiedSenses.length === 0`：有释义的词条页不显示这块。
             `acoparse` 有 58 个变位形，挂在正常词条页上只会挤掉真正要看的东西 ——
             「超长内容撑版面」是 es 展示层已知的三条线索之一。 */}
      {entry.forms.length > 0 && entry.unifiedSenses.length === 0 && (
        <section className="entry-section">
          <h3>变形形</h3>
          <p className="it-note">源头未收录本词的词条页，暂无释义；以下是库中指向它的变形形。</p>
          <ul className="infl-notes">
            {entry.forms.slice(0, 24).map((f, i) => (
              <li key={i}>
                <a href={`#${encodeURIComponent(f.word)}`}
                  onClick={(e) => { e.preventDefault(); onWord(f.word); }}>{f.word}</a>
                {' — '}{f.label}
              </li>
            ))}
            {entry.forms.length > 24 && (
              <li className="base-more">… 共 {entry.forms.length} 个变形形</li>
            )}
          </ul>
        </section>
      )}

      {/* 变位形式：指回原形 + 各原形的词义 + 语法说明
          🔴 标题按**数据**分，不写死（2026-08-20）：3,881 个词形有 `baseForms`
             但没有任何 `inflNotes` —— 它们是**拼写变体**不是变位形式
             （`aqui`→`aquí` 常见误拼、`sólo`→`solo` 旧拼写、`EEUU`→`EE. UU.` 缩写形，
             `sólo` zipf 5.79 / `asi` 5.21 / `tambien` 4.98，全是高频词）。
             这些词的释义已经写着「aquí 的常见误拼」，下面却顶着「变位形式」的标题。
             判据是确定性的：有语法说明才是变位，没有就只是指向另一个拼写。

          🔴 条件是 `baseForms || inflNotes`，**不是只看 baseForms**
             （2026-08-20 契约闸第一次跑就逮到）：`baseForms` 来自 `dict.exchange`，
             而 `exchange` 为空、变位说明非空的词形有 **10,894 个** ——
             头两个是 `lo`(zipf 6.89) 和 `te`(6.52)，全库最常用的词。
             原条件把整块（含语法说明）一起跳过：数据里明明写着「él 的 宾格」，
             页面上一个字都没有。当天我刚把 `él and usted` 重指成 `él`，
             数据侧的闸全绿、**用户看到的页面没有任何变化** —— 典型的「被绕过」。 */}
      {(entry.baseForms.length > 0 || entry.inflNotes.length > 0) && (
        <section className="entry-section">
          <h3>{entry.inflNotes.length > 0 ? '变位形式' : '参见'}</h3>
          {entry.inflNotes.length > 0 && (
            <ul className="infl-notes">
              {entry.inflNotes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
          <div className="base-list">
            {entry.baseForms.map((bw) => {
              const base = entry.bases.find((b) => b.word === bw);
              return (
                <div className="base-item" key={bw}>
                  <a className="base-word" href={`#${encodeURIComponent(bw)}`}
                    onClick={(e) => { e.preventDefault(); onWord(bw); }}>
                    {bw}
                  </a>
                  {base?.pos && <span className="base-pos">{posLabel(base.pos)}</span>}
                  {base && base.senses.length > 0 && (() => {
                    const zhs = base.senses.map((s) => s.zh).filter(Boolean) as string[];
                    const CAP = 4;
                    const shown = zhs.slice(0, CAP).join('；');
                    const more = zhs.length > CAP;
                    return (
                      <span className="base-senses">
                        {shown}
                        {more && <span className="base-more">… 共 {zhs.length} 义，点词查看</span>}
                      </span>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {entry.collocations.length > 0 && (
        <section className="entry-section">
          <h3>搭配 / 固定短语</h3>
          <ul className="colloc-list">
            {entry.collocations.map((c, i) => (
              <li className="colloc-item" key={i}>
                <span className="colloc-text">{c.text}</span>
                {c.zh && <span className="colloc-zh">{c.zh}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

// ============================================================================
// 意大利语词条视图 —— 意语专属，把本质特征做成一等展示：
// 助动词 essere/avere 徽标、变位类、异性复数（braccio→braccia 阴）、gemination 已在 IPA 内。
// 自包含，不复用西语的 SpanishEntryView。
// ============================================================================

function ItSenseChips({ sense, dualGender }: { sense: ItSense; dualGender?: boolean }) {
  const chips: { cls: string; text: string }[] = [];
  // 仅双性名词逐义项标性别（il 半径 / la 收音机），单性词与词头徽标重复故略
  if (dualGender && sense.gender)
    chips.push({ cls: `g g-${sense.gender}`, text: `${IT_ARTICLE[sense.gender] || ''} ${GENDER_LABELS[sense.gender] || ''}` });
  for (const r of sense.regions) chips.push({ cls: 'reg', text: IT_REGION_LABELS[r] || r });
  for (const r of sense.registers) chips.push({ cls: 'lex', text: REGISTER_LABELS[r] || r });
  if (chips.length === 0) return null;
  return (
    <span className="sense-chips">
      {chips.map((c, i) => <span className={`sense-chip ${c.cls}`} key={i}>{c.text}</span>)}
    </span>
  );
}

/**
 * 义项分组。**相邻聚合**（不是按 pos 归类）—— 义项顺序本身有意义（`sense.rank`），重排会打乱它。
 *
 * 🔴 2026-08-19：分组键从「词性」改成「**词条 + 词性**」。同一个词形常常是好几个词条：
 *    `ancora` = 副词「还」/ 名词「锚」/ 动词，`subito` = 副词「立刻」/ 动词「遭受了」。
 *    只按词性分，两个**同词性不同词源**的词条会被并成一组（`pesca` 的两个名词：
 *    桃子 etym1 / 捕鱼 etym2），而它们的读音是不同的 —— 分不开就没法把读音挂对地方。
 */
/**
 * 这条读音该不该标在这一组义项的组头上。
 *
 * 🔴 判据是「**专属**」不是「属于」：一条读音若挂在这个词形的**每一个**词条上，
 *    它就是共用读音 —— 词头那行已经显示过，再往每个组头铺一遍只是把同一个东西印 N 遍。
 *    回答的是「这一组有没有自己的读音」，不是「这一组该读什么」。
 *
 * 🔴 导出是为了**一处实现**：组件渲染和 `contract-check` 都调它。
 *    `it-display-layer-stage8` 的教训：第一版我在闸里自己按义项的 entryId 算了一遍，
 *    报了 67 条假红 —— 判据分两份写，迟早漂。
 *
 * ⚠️ 它住在 App.tsx 而不是 dict-core：dict-core 依赖 `node:sqlite`，浏览器端引不了
 *    （`dict-labels` 存在的理由就是这个）。而这条判据不是"映射表"，也不该塞进 dict-labels。
 */
export function readingBelongsTo(
  r: ItReading, entryId: number | null, allEntryIds: (number | null)[],
): boolean {
  if (entryId === null || r.entryIds.length === 0) return false;
  if (!r.entryIds.includes(entryId)) return false;
  const known = allEntryIds.filter((x): x is number => x !== null);
  return !(known.length > 1 && known.every((x) => r.entryIds.includes(x)));
}

export function groupItSenses(senses: ItSense[]): {
  pos: string | null; entryId: number | null; senses: ItSense[];
}[] {
  const groups: { pos: string | null; entryId: number | null; senses: ItSense[] }[] = [];
  for (const s of senses) {
    const last = groups[groups.length - 1];
    if (last && last.pos === s.pos && last.entryId === s.entryId) last.senses.push(s);
    else groups.push({ pos: s.pos, entryId: s.entryId, senses: [s] });
  }
  return groups;
}

// 🔴 导出供 `contract-check.tsx` 用：那道闸把真实数据喂进这个组件、渲染成 HTML 再断言。
//    2026-08-16 之前我所有的闸都在数据库里自查，而用户从界面上挑出三个我完全看不见的缺陷
//    （词性标题显示成英文原始串 / 专名被归到「短语」/ 有义项却整块不渲染）——
//    那三个的共同点是**只在渲染之后才存在**，查库和查接口都查不到。
// 一条例句。原文 + 中文 + 出处，三层都可能缺（出处只有 6.7% 有）。
function ItExampleView({ ex }: { ex: ItExample }) {
  return (
    <div className="sense-example">
      <div className="ex-it" lang="it">{ex.text}</div>
      {ex.zh && <div className="ex-zh">{ex.zh}</div>}
      {ex.ref && <div className="ex-ref">{ex.ref}</div>}
    </div>
  );
}

// 语义关系。分类封顶 12 条（`buono` 有 763 条），**截断了要把总数说出来** ——
// 不说的话用户会以为词典只收了这么多。
function ItRelationGroups({ groups, onWord }: {
  groups: ItRelationGroup[]; onWord: (w: string) => void;
}) {
  if (groups.length === 0) return null;
  return (
    <div className="rel-groups">
      {groups.map((g) => (
        <div className="rel-group" key={g.kind}>
          <span className="rel-kind">{REL_LABELS[g.kind] || g.kind}</span>
          {g.targets.map((t) => (
            <span className="rel-item" key={t.word}>
              {t.linkable
                ? <a className="rel-link" href={`#${encodeURIComponent(t.word)}`}
                     onClick={(ev) => { ev.preventDefault(); onWord(t.word); }}>{t.word}</a>
                : <span className="rel-plain">{t.word}</span>}
            </span>
          ))}
          {g.total > g.targets.length && (
            <span className="rel-more">共 {g.total} 个</span>
          )}
        </div>
      ))}
    </div>
  );
}

export function ItalianEntryView({ entry, speakLocale, onWord, speak }: {
  entry: ItEntry; speakLocale: string; onWord: (w: string) => void;
  speak: (word: string, locale: string) => void;
}) {
  const isVerb = !!entry.pos && entry.pos.split('/').includes('v');
  const isNoun = !!entry.pos && entry.pos.split('/').some((p) => p === 'n' || p === 'name');
  const showStubPos = entry.isLemma && !!entry.pos && !entry.senses.some((s) => s.pos);
  // 🔴 2026-08-21 词头徽标的**归属守卫**。
  //    `isNoun`/`isVerb` 读的是 `dict.pos`（`contr/n/v` 这样的**词形级**斜杠串），
  //    只要这个拼写有一种名词用法就为真；而 `entry.gender`/`plural`/`aux` 同样是
  //    词形级汇总 —— 两个词形级的东西凑在一起，就把只对某一个词条成立的属性
  //    顶到了整词头上：`la` 显示「阳性」（那是名词「音名拉」的性，冠词/代词是阴性）、
  //    `di` 显示「阴性 单复同形」、`anche`（也）显示「阴性」、`fare` 显示「复数 fari」
  //    （`fari` 是 `faro` 灯塔的复数）。全库 7,527 个词形，**几乎全是最高频词**。
  //    ⇒ 归属不明就不显示。错比缺更伤权威。
  //    ⚠️ 判据用 `posWithSenses`（**有可见义项**的词条词性），不是 `dict.pos`：
  //       `acqua` 的 `pos='n/v'` 里那个 v 是 `acquare` 的变位形、一条义项都没有，
  //       它的「阴性 复数 acque」完全正确，不能跟着一起藏。
  //    ⏳ 这是止血。把徽标下沉到各个词性分组是正解，要先给 entry 层补性/复数，已记账。
  //    ⚠️ 判据第一版写成「≥2 种词性就算归属不明」，被契约闸逮到造成 92 处回归：
  //       `cecchino`(noun+name 姓氏)、`sagro`(adj+noun)、`100enne`(adj) 的复数形全没了。
  //       意语里**名词/专名/形容词共享性数系统**（`sagri` 对形容词和名词都适用），
  //       它们之间根本不冲突 —— 冲突只发生在**混进了没有性数的词类**时（冠词/代词/介词/动词）。
  //    ⚠️ 助动词/变位类/及物性更简单：它们**只可能属于动词**，不存在归属歧义 ⇒
  //       有动词义项就显示（`fare` 的 aux=avere 是对的；`acqua` 没有动词义项，
  //       它那个 aux 来自同形的 `acquare`，所以不显示）。
  const NOMINAL = new Set(['noun', 'name', 'adj']);
  const posScope = entry.posWithSenses ?? [];
  // posScope 为空 = 该词形没有自己的义项（纯变形形如 `piante`）⇒ 没有证据说明有冲突，
  // 保持原行为，别把「不知道」当成「有歧义」。
  const nounBadge = posScope.length === 0 ? isNoun : posScope.every((p) => NOMINAL.has(p));
  const verbBadge = posScope.length === 0 ? isVerb : posScope.includes('verb');
  return (
    <article className="entry-detail">
      <header className="entry-header">
        <h2 className="entry-word">{entry.word}</h2>
      </header>

      {/* 音标行。🔴 2026-08-18 阶段 8：`entry.ipa` 现在来自 `pronunciation` 表
          （原来是 `dict.ipa` 列）—— 513,775 个词形因此**第一次有音标可显示**。
          多读音的词（99,048 个）把其余读音并排列出：`ancora` 名词「锚」ˈaŋkora
          与副词「还」aŋˈkora 是真的两个读音，只显示一个等于告诉用户另一个是错的。
          ⚠️ 严式转写用方括号，音位式用斜杠 —— 定界符的差别本身是信息（六语种存裸约定）。*/}
      {entry.ipa && (
        <div className="phonetic-row">
          <button className="phonetic-btn" onClick={() => speak(entry.word, speakLocale)} title="播放发音" type="button">
            <span className="phonetic-value">/{entry.ipa}/</span>
            <SpeakerIcon />
          </button>
          {entry.readings.filter((r) => !r.isPrimary).slice(0, 2).map((r) => (
            <span className="phonetic-btn phonetic-alt" key={r.ipa}
                  title={`另一读音 · 来源 ${r.src}`}>
              <span className="phonetic-value">
                {r.notation === 'narrow' ? `[${r.ipa}]` : `/${r.ipa}/`}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* 真人录音（阶段 6a 收的 12,188 条 URL）。放在合成音之前 ——
          方针④的三级兜底是「真人 > 工具生成 > 浏览器 TTS」，顺序就是权威顺序。 */}
      <HumanAudioRow
        audios={entry.audios}
        word={entry.word}
        fallback={() => speak(entry.word, speakLocale)}
        regionLabel={itAudioRegion as (r: string) => string}
      />

      {/* 意语本质徽标：动词看助动词/变位类/及物性，名词看性别/复数；CEFR 难度贯穿所有词性 */}
      <div className="entry-meta-row entry-badges">
        {entry.level && <span className={`badge cefr cefr-${entry.level[0]}`}>{entry.level}</span>}
        {nounBadge && entry.gender && (
          <span className={`badge g g-${entry.gender}`}>{GENDER_LABELS[entry.gender] || entry.gender}性</span>
        )}
        {/* 🔴 2026-08-19：意语的双复数装不进单列 —— `braccio` 有 braccia（阴，人的手臂）
            与 bracci（阳，器物的臂）两个，全库 1,833 个词这样。现在铺全部。 */}
        {nounBadge && entry.plurals.map((p) => (
          <span className="badge plural" key={p.form}>
            复数 {p.form}
            {p.gender && <span className="plural-shift">〈{GENDER_LABELS[p.gender]}〉</span>}
          </span>
        ))}
        {nounBadge && entry.numberNote && (
          <span className="badge num">{IT_NUMBER_NOTE_LABELS[entry.numberNote] || entry.numberNote}</span>
        )}
        {verbBadge && entry.aux && (
          <span className={`badge aux aux-${entry.aux}`}>{IT_AUX_LABELS[entry.aux]}</span>
        )}
        {verbBadge && entry.conj && (
          <span className="badge conj">{IT_CONJ_LABELS[entry.conj] || entry.conj}</span>
        )}
        {verbBadge && entry.transitivity && (
          <span className="badge tag">{TRANS_LABELS[entry.transitivity] || entry.transitivity}</span>
        )}
        {entry.pronominal && <span className="badge tag">代动词</span>}
        {showStubPos && <span className="badge pos">{posLabel(entry.pos)}</span>}
      </div>

      {/* 异性复数（metaplasmic）提示：意语招牌，braccio(阳)→braccia(阴)。
          🔴 同时给出另一个「规则复数」——这类词的两个复数**意思不同**
          （braccia 是人的手臂、bracci 是器物的臂），只显示一个等于告诉用户另一个不存在。 */}
      {nounBadge && entry.plurals.some((p) => p.gender) && (() => {
        const shifted = entry.plurals.find((p) => p.gender)!;
        const others = entry.plurals.filter((p) => p !== shifted);
        return (
          <div className="it-note">
            异性复数：单数 <b>{entry.word}</b>（{GENDER_LABELS[entry.gender || 'm']}）→ 复数{' '}
            <b>{shifted.form}</b>（{GENDER_LABELS[shifted.gender!]}）
            {others.length > 0 && (
              <>；另有 <b>{others.map((p) => p.form).join('、')}</b>
              （{GENDER_LABELS[entry.gender || 'm']}）</>
            )}
          </div>
        );
      })()}

      {/* 🔴 2026-08-16 去掉 `entry.isLemma &&`（用户查 `TVTB` 时发现的）。
          `is_lemma` 是七月压平结构时打的标，那会儿还没有 entry/sense 分层，
          它被当成了「值不值得显示释义」的代理 —— 而**「不是变形」和「是词元」不是一回事**：
          `TVTB`（缩写）、`e pur si muove`（伽利略名言）、`colibri`（蜂鸟）都被标 0，
          于是有义项也整块不渲染。实测 **8,552 个词形**（有义项词形的 2.5%）中招。
          现在判据就是事实本身：有可见义项就显示。es 早已是这个写法（它做过义项分层重构）；
          fr/pt/de 三个渲染器仍留着老条件，记在 `it-CONVENTIONS` 待办，本轮不越界。 */}
      {entry.senses.length > 0 && (
        <section className="entry-section">
          <h3>释义</h3>
          {groupItSenses(entry.senses).map((grp, gi, all) => (
            <div className="pos-group" key={gi}>
              {grp.pos && (
                <div className="pos-group-label">
                  {posLabel(grp.pos)}
                  {/* 🔴 2026-08-19：把**这一组专属的读音**标在组头上。
                      `ancora` 名词「锚」是 ˈankora、副词「还」是 anˈkora —— 以前两条读音
                      并排堆在词头，用户没法知道哪条配哪组义项（1,944 个同形异读词形）。
                      ⚠️ 判据是「这条读音**专属**于本词条」——共用读音已经在词头那行
                      显示过，再铺一遍只是重复。这里回答的是「这一组有没有自己的读音」，
                      与「这一组该读什么」是两个问题。
                      🔴 2026-08-19：判据搬进 `readingBelongsTo`（dict-core），
                      组件与契约闸**共用同一份实现** —— 判据分两份写就会像上次那样
                      在闸里报 67 条假红。 */}
                  {/* ⚠️ 只在**分了多组**时标：单组页面上，词头那行已经把读音显示过了，
                      再在组头重复一遍是噪声（`braccio` 只有一个名词组）。 */}
                  {(all.length > 1 ? entry.readings.filter(
                    (r) => readingBelongsTo(r, grp.entryId, all.map((g) => g.entryId))) : [])
                    .slice(0, 1).map((r) => (
                      <span className="pos-group-ipa" key={r.ipa}>
                        {r.notation === 'narrow' ? `[${r.ipa}]` : `/${r.ipa}/`}
                      </span>
                    ))}
                </div>
              )}
              <ol className="sense-list">
                {grp.senses.map((s, i) => (
                  <li className="sense-item" key={i}>
                    <div className="sense-zh">
                      {s.zh || <span className="sense-missing">（待补）</span>}
                      <ItSenseChips sense={s} dualGender={entry.gender === 'mf'} />
                    </div>
                    {/* 🔴 2026-08-16 补上 `s.it`（用户问「怎么没见过 en 和 it 同时出现」时发现的）。
                        阶段 1.5–3 往库里导了 89,531 条**意语原文释义**，接口也一直在返回，
                        但这里只渲染了 `s.en` —— 于是那批全部看不见。
                        实测 52,909 条义项 en+it 都有、36,245 条**只有 it**（英文版没收的义项）。
                        样式复用 es 那套 `.sense-src`，EN / IT 两个语言标记并排。 */}
                    {s.en && (
                      <div className="sense-src" lang="en">
                        <span className="sense-src-lang">EN</span>{s.en}
                      </div>
                    )}
                    {s.it && (
                      <div className="sense-src" lang="it">
                        <span className="sense-src-lang">IT</span>{s.it}
                      </div>
                    )}
                    {/* 挂在这条义项上的例句。中文 100%（阶段 5 全量翻译），
                        所以这里不做「有没有中文」的分支 —— 有就一定有。 */}
                    {s.examples.slice(0, 3).map((x, xi) => (
                      <ItExampleView ex={x} key={xi} />
                    ))}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </section>
      )}

      {/* 变位形式：指回原形；原形连带助动词/性别一起显示 */}
      {entry.baseForms.length > 0 && (
        <section className="entry-section">
          <h3>变位形式</h3>
          {/* 🔴 2026-08-19：`braccio` 既是名词「手臂」，又是动词 `bracciare` 的变位形
              （源头就是两个词源）。这一块直接摆在名词释义下面，看起来像是名词的变位 ——
              有人看这一页时正是这么误读的，还建议把整块删掉。**删掉会丢真信息**：
              用户在文章里划到 `io braccio` 需要知道它是动词形。⇒ 不删，说清楚它是另一个词。 */}
          {/* 🔴 2026-08-21：这句开场白原来是无条件的，对 `sentirsi` 说反了 ——
              `sentirsi` **就是** `sentire` 的自反形式（`inflection.tags` 里明写着
              form-of/reflexive），不是「碰巧同形的另一个词」。全库 1,418 行这样。
              ⇒ 全部原形都是自反关系时换一句话说；混合时按同形处理（更保守）。 */}
          {entry.senses.length > 0 && (() => {
            const refl = entry.reflexiveOf ?? [];
            const allRefl = refl.length > 0 && entry.baseForms.every((b) => refl.includes(b));
            return (
              <div className="it-note it-homograph">
                {allRefl ? (
                  <>下面是 <b>{entry.word}</b> 作为{' '}
                    {entry.baseForms.map((b, i) => (
                      <span key={b}>{i > 0 && '、'}<b>{b}</b></span>
                    ))}{' '}自反形式的变位。</>
                ) : (
                  <>下面这些与上面的释义不是同一个词 —— <b>{entry.word}</b> 这个拼写同时还是{' '}
                    {entry.baseForms.map((b, i) => (
                      <span key={b}>{i > 0 && '、'}<b>{b}</b></span>
                    ))}{' '}的变位形式。</>
                )}
              </div>
            );
          })()}
          {entry.inflNotes.length > 0 && (
            <ul className="infl-notes">
              {entry.inflNotes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
          <div className="base-list">
            {entry.baseForms.map((bw) => {
              const base = entry.bases.find((b) => b.word === bw);
              return (
                <div className="base-item" key={bw}>
                  <a className="base-word" href={`#${encodeURIComponent(bw)}`}
                    onClick={(e) => { e.preventDefault(); onWord(bw); }}>
                    {bw}
                  </a>
                  {base?.pos && <span className="base-pos">{posLabel(base.pos)}</span>}
                  {base?.aux && <span className="base-pos">{IT_AUX_LABELS[base.aux]}</span>}
                  {base?.gender && <span className="base-pos">{GENDER_LABELS[base.gender]}性</span>}
                  {base && base.senses.length > 0 && (() => {
                    const zhs = base.senses.map((s) => s.zh).filter(Boolean) as string[];
                    const CAP = 4;
                    const shown = zhs.slice(0, CAP).join('；');
                    return (
                      <span className="base-senses">
                        {shown}
                        {zhs.length > CAP && <span className="base-more">… 共 {zhs.length} 义，点词查看</span>}
                      </span>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {entry.collocations.length > 0 && (
        <section className="entry-section">
          <h3>搭配 / 固定短语</h3>
          <ul className="colloc-list">
            {entry.collocations.map((c, i) => (
              <li className="colloc-item" key={i}>
                <span className="colloc-text">{c.text}</span>
                {c.zh && <span className="colloc-zh">{c.zh}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 挂不上具体义项的例句（39.0% 挂上了，其余在这里成块）。
          🔴 不硬塞进第一条义项 —— 那等于替源头做了一个它没做的判断，
          而例句挂错义项正是「用户会看到错的内容」那一类。 */}
      {entry.examples.length > 0 && (
        <section className="entry-section">
          <h3>例句</h3>
          {entry.examples.map((x, i) => <ItExampleView ex={x} key={i} />)}
        </section>
      )}

      {entry.relations.length > 0 && (
        <section className="entry-section">
          <h3>相关词</h3>
          <ItRelationGroups groups={entry.relations} onWord={onWord} />
        </section>
      )}
    </article>
  );
}

// ============================================================================
// 法语词条视图 —— 法语专属，把本质特征做成一等展示：
// 助动词 avoir/être 徽标、动词三组、过去分词、形容词阴性形、名词不规则复数、不变形。
// 自包含，不复用 es/it 的视图。
// ============================================================================

function FrSenseChips({ sense, dualGender }: { sense: FrSense; dualGender?: boolean }) {
  const chips: { cls: string; text: string }[] = [];
  // 仅双性名词逐义项标性别（le 书 / la 斤），单性词与词头徽标重复故略
  if (dualGender && sense.gender)
    chips.push({ cls: `g g-${sense.gender}`, text: `${FR_ARTICLE[sense.gender] || ''} ${GENDER_LABELS[sense.gender] || ''}` });
  for (const r of sense.regions) chips.push({ cls: 'reg', text: FR_REGION_LABELS[r] || r });
  for (const r of sense.registers) chips.push({ cls: 'lex', text: REGISTER_LABELS[r] || r });
  if (chips.length === 0) return null;
  return (
    <span className="sense-chips">
      {chips.map((c, i) => <span className={`sense-chip ${c.cls}`} key={i}>{c.text}</span>)}
    </span>
  );
}

function groupFrSenses(senses: FrSense[]): { pos: string | null; senses: FrSense[] }[] {
  const groups: { pos: string | null; senses: FrSense[] }[] = [];
  for (const s of senses) {
    const last = groups[groups.length - 1];
    if (last && last.pos === s.pos) last.senses.push(s);
    else groups.push({ pos: s.pos, senses: [s] });
  }
  return groups;
}

function FrenchEntryView({ entry, speakLocale, onWord, speak }: {
  entry: FrEntry; speakLocale: string; onWord: (w: string) => void;
  speak: (word: string, locale: string) => void;
}) {
  const posParts = entry.pos ? entry.pos.split('/') : [];
  const isVerb = posParts.includes('v');
  const isNoun = posParts.some((p) => p === 'n' || p === 'name');
  const isAdj = posParts.includes('adj');
  const showStubPos = entry.isLemma && !!entry.pos && !entry.senses.some((s) => s.pos);
  return (
    <article className="entry-detail">
      <header className="entry-header">
        <h2 className="entry-word">{entry.word}</h2>
      </header>

      {entry.ipa && (
        <div className="phonetic-row">
          <button className="phonetic-btn" onClick={() => speak(entry.word, speakLocale)} title="播放发音" type="button">
            <span className="phonetic-value">/{entry.ipa}/</span>
            <SpeakerIcon />
          </button>
        </div>
      )}

      {/* 法语本质徽标：动词看助动词/组/过去分词/及物性，名词看性别/复数，形容词看阴性形；CEFR 贯穿 */}
      <div className="entry-meta-row entry-badges">
        {entry.level && <span className={`badge cefr cefr-${entry.level[0]}`}>{entry.level}</span>}
        {isNoun && entry.gender && (
          <span className={`badge g g-${entry.gender}`}>{GENDER_LABELS[entry.gender] || entry.gender}性</span>
        )}
        {isNoun && entry.plural && (
          <span className="badge plural">复数 {entry.plural}</span>
        )}
        {(isNoun || isAdj) && entry.invariable && <span className="badge num">不变形 inv.</span>}
        {/* 阴性形：形容词 grand→grande；名词 acteur→actrice */}
        {(isAdj || isNoun) && entry.feminine && (
          <span className="badge fem">阴性形 {entry.feminine}</span>
        )}
        {isAdj && entry.adjPos && (
          <span className="badge apos">{FR_ADJPOS_LABELS[entry.adjPos] || entry.adjPos}</span>
        )}
        {(isAdj || isVerb) && entry.comparative && (
          <span className="badge cmp">比较级 {entry.comparative}</span>
        )}
        {isVerb && entry.aux && (
          <span className={`badge aux aux-${entry.aux}`}>{FR_AUX_LABELS[entry.aux]}</span>
        )}
        {isVerb && entry.vgroup && (
          <span className="badge conj">{FR_VGROUP_LABELS[entry.vgroup] || entry.vgroup}</span>
        )}
        {isVerb && entry.pp && <span className="badge pp">过去分词 {entry.pp}</span>}
        {/* 固定介词支配（动词/形容词）：commencer à、dépendre de——学习者刚需 */}
        {(isVerb || isAdj) && entry.government && (
          <span className="badge gov">＋{entry.government}</span>
        )}
        {isVerb && entry.transitivity && (
          <span className="badge tag">{TRANS_LABELS[entry.transitivity] || entry.transitivity}</span>
        )}
        {entry.pronominal && <span className="badge tag">代动词 pron.</span>}
        {showStubPos && <span className="badge pos">{posLabel(entry.pos)}</span>}
      </div>

      {entry.isLemma && entry.senses.length > 0 && (
        <section className="entry-section">
          <h3>释义</h3>
          {groupFrSenses(entry.senses).map((grp, gi) => (
            <div className="pos-group" key={gi}>
              {grp.pos && <div className="pos-group-label">{posLabel(grp.pos)}</div>}
              <ol className="sense-list">
                {grp.senses.map((s, i) => (
                  <li className="sense-item" key={i}>
                    <div className="sense-zh">
                      {s.zh || <span className="sense-missing">（待补）</span>}
                      <FrSenseChips sense={s} dualGender={entry.gender === 'mf'} />
                    </div>
                    {s.en && <div className="sense-en">{s.en}</div>}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </section>
      )}

      {/* 变位形式：指回原形；原形连带助动词/性别一起显示 */}
      {entry.baseForms.length > 0 && (
        <section className="entry-section">
          <h3>变位形式</h3>
          {entry.inflNotes.length > 0 && (
            <ul className="infl-notes">
              {entry.inflNotes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
          <div className="base-list">
            {entry.baseForms.map((bw) => {
              const base = entry.bases.find((b) => b.word === bw);
              return (
                <div className="base-item" key={bw}>
                  <a className="base-word" href={`#${encodeURIComponent(bw)}`}
                    onClick={(e) => { e.preventDefault(); onWord(bw); }}>
                    {bw}
                  </a>
                  {base?.pos && <span className="base-pos">{posLabel(base.pos)}</span>}
                  {base?.aux && <span className="base-pos">{FR_AUX_LABELS[base.aux]}</span>}
                  {base?.gender && <span className="base-pos">{GENDER_LABELS[base.gender]}性</span>}
                  {base && base.senses.length > 0 && (() => {
                    const zhs = base.senses.map((s) => s.zh).filter(Boolean) as string[];
                    const CAP = 4;
                    const shown = zhs.slice(0, CAP).join('；');
                    return (
                      <span className="base-senses">
                        {shown}
                        {zhs.length > CAP && <span className="base-more">… 共 {zhs.length} 义，点词查看</span>}
                      </span>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {entry.collocations.length > 0 && (
        <section className="entry-section">
          <h3>搭配 / 固定短语</h3>
          <ul className="colloc-list">
            {entry.collocations.map((c, i) => (
              <li className="colloc-item" key={i}>
                <span className="colloc-text">{c.text}</span>
                {c.zh && <span className="colloc-zh">{c.zh}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

// ============================================================================
// 葡萄牙语词条视图 —— 葡语专属，把本质特征做成一等展示：
// 双读音 🇧🇷 巴西 pt-BR / 🇵🇹 葡萄牙 pt-PT（各自可发音）、变位类、过去分词、性别、复数、阴性形。
// 自包含，不复用 es/it/fr 的视图。
// ============================================================================

function PtSenseChips({ sense, dualGender }: { sense: PtSense; dualGender?: boolean }) {
  const chips: { cls: string; text: string }[] = [];
  // 仅双性名词逐义项标性别（o 收音机 / a 镭），单性词与词头徽标重复故略
  if (dualGender && sense.gender)
    chips.push({ cls: `g g-${sense.gender}`, text: `${PT_ARTICLE[sense.gender] || ''} ${GENDER_LABELS[sense.gender] || ''}` });
  for (const r of sense.regions) chips.push({ cls: 'reg', text: PT_REGION_LABELS[r] || r });
  for (const r of sense.registers) chips.push({ cls: 'lex', text: REGISTER_LABELS[r] || r });
  if (chips.length === 0) return null;
  return (
    <span className="sense-chips">
      {chips.map((c, i) => <span className={`sense-chip ${c.cls}`} key={i}>{c.text}</span>)}
    </span>
  );
}

function groupPtSenses(senses: PtSense[]): { pos: string | null; senses: PtSense[] }[] {
  const groups: { pos: string | null; senses: PtSense[] }[] = [];
  for (const s of senses) {
    const last = groups[groups.length - 1];
    if (last && last.pos === s.pos) last.senses.push(s);
    else groups.push({ pos: s.pos, senses: [s] });
  }
  return groups;
}

// 双读音行：区旗 + 音标 + 发音按钮（巴西 pt-BR / 葡萄牙 pt-PT 各一套 locale）。
function PtPhonetics({ word, ipaBr, ipaPt, speak }: {
  word: string; ipaBr: string | null; ipaPt: string | null;
  speak: (word: string, locale: string) => void;
}) {
  if (!ipaBr && !ipaPt) return null;
  const same = ipaBr && ipaPt && ipaBr === ipaPt;
  // 格式同英语 英/美、西语 西/拉美——单字标签 + 音标同在一个 .phonetic-btn 标签内，同一排。
  // label 短(巴/葡)供显示，name 全称供 hover；两地同音时不带标签只显示一个音标（同英语单音）。
  const rows: { label: string; name: string; ipa: string; locale: string }[] = [];
  if (same) {
    rows.push({ label: '', name: '', ipa: ipaBr as string, locale: 'pt-BR' });
  } else {
    if (ipaBr) rows.push({ label: '巴', name: '巴西', ipa: ipaBr, locale: 'pt-BR' });
    if (ipaPt) rows.push({ label: '葡', name: '葡萄牙', ipa: ipaPt, locale: 'pt-PT' });
  }
  return (
    <div className="phonetic-row">
      {rows.map((r, i) => (
        <button className="phonetic-btn" key={i} onClick={() => speak(word, r.locale)} title={r.name ? `播放 ${r.name} 发音` : '播放发音'} type="button">
          {r.label && <span className="phonetic-label">{r.label}</span>}
          <span className="phonetic-value">/{r.ipa}/</span>
          <SpeakerIcon />
        </button>
      ))}
    </div>
  );
}

function PortugueseEntryView({ entry, onWord, speak }: {
  entry: PtEntry; onWord: (w: string) => void;
  speak: (word: string, locale: string) => void;
}) {
  const posParts = entry.pos ? entry.pos.split('/') : [];
  const isVerb = posParts.includes('v');
  const isNoun = posParts.some((p) => p === 'n' || p === 'name');
  const isAdj = posParts.includes('adj');
  const showStubPos = entry.isLemma && !!entry.pos && !entry.senses.some((s) => s.pos);
  return (
    <article className="entry-detail">
      <header className="entry-header">
        <h2 className="entry-word">{entry.word}</h2>
      </header>

      <PtPhonetics word={entry.word} ipaBr={entry.ipaBr} ipaPt={entry.ipaPt} speak={speak} />

      {/* 葡语本质徽标：动词看变位类/过去分词/及物性，名词看性别/复数，形容词看阴性形；CEFR 贯穿 */}
      <div className="entry-meta-row entry-badges">
        {entry.level && <span className={`badge cefr cefr-${entry.level[0]}`}>{entry.level}</span>}
        {isNoun && entry.gender && (
          <span className={`badge g g-${entry.gender}`}>{GENDER_LABELS[entry.gender] || entry.gender}性</span>
        )}
        {isNoun && entry.plural && <span className="badge plural">复数 {entry.plural}</span>}
        {(isAdj || isNoun) && entry.feminine && <span className="badge fem">阴性形 {entry.feminine}</span>}
        {(isAdj || isVerb) && entry.comparative && <span className="badge cmp">比较级 {entry.comparative}</span>}
        {isAdj && entry.adjPos && (
          <span className="badge apos">{FR_ADJPOS_LABELS[entry.adjPos] || entry.adjPos}</span>
        )}
        {isVerb && entry.vconj && (
          <span className="badge conj">{PT_VCONJ_LABELS[entry.vconj] || entry.vconj}</span>
        )}
        {isVerb && entry.pp && <span className="badge pp">过去分词 {entry.pp}</span>}
        {isVerb && entry.ppShort && <span className="badge pp">短分词 {entry.ppShort}</span>}
        {(isVerb || isAdj) && entry.government && (
          <span className="badge gov">＋{entry.government}</span>
        )}
        {isVerb && entry.transitivity && (
          <span className="badge tag">{TRANS_LABELS[entry.transitivity] || entry.transitivity}</span>
        )}
        {entry.pronominal && <span className="badge tag">代动词 pron.</span>}
        {showStubPos && <span className="badge pos">{posLabel(entry.pos)}</span>}
      </div>

      {entry.isLemma && entry.senses.length > 0 && (
        <section className="entry-section">
          <h3>释义</h3>
          {groupPtSenses(entry.senses).map((grp, gi) => (
            <div className="pos-group" key={gi}>
              {grp.pos && <div className="pos-group-label">{posLabel(grp.pos)}</div>}
              <ol className="sense-list">
                {grp.senses.map((s, i) => (
                  <li className="sense-item" key={i}>
                    <div className="sense-zh">
                      {s.zh || <span className="sense-missing">（待补）</span>}
                      <PtSenseChips sense={s} dualGender={entry.gender === 'mf'} />
                    </div>
                    {s.en && <div className="sense-en">{s.en}</div>}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </section>
      )}

      {/* 变位形式：指回原形（含人称不定式等葡语专属变位）；原形连带性别显示 */}
      {entry.baseForms.length > 0 && (
        <section className="entry-section">
          <h3>变位形式</h3>
          {entry.inflNotes.length > 0 && (
            <ul className="infl-notes">
              {entry.inflNotes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
          <div className="base-list">
            {entry.baseForms.map((bw) => {
              const base = entry.bases.find((b) => b.word === bw);
              return (
                <div className="base-item" key={bw}>
                  <a className="base-word" href={`#${encodeURIComponent(bw)}`}
                    onClick={(e) => { e.preventDefault(); onWord(bw); }}>
                    {bw}
                  </a>
                  {base?.pos && <span className="base-pos">{posLabel(base.pos)}</span>}
                  {base?.gender && <span className="base-pos">{GENDER_LABELS[base.gender]}性</span>}
                  {base && base.senses.length > 0 && (() => {
                    const zhs = base.senses.map((s) => s.zh).filter(Boolean) as string[];
                    const CAP = 4;
                    const shown = zhs.slice(0, CAP).join('；');
                    return (
                      <span className="base-senses">
                        {shown}
                        {zhs.length > CAP && <span className="base-more">… 共 {zhs.length} 义，点词查看</span>}
                      </span>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {entry.collocations.length > 0 && (
        <section className="entry-section">
          <h3>搭配 / 固定短语</h3>
          <ul className="colloc-list">
            {entry.collocations.map((c, i) => (
              <li className="colloc-item" key={i}>
                <span className="colloc-text">{c.text}</span>
                {c.zh && <span className="colloc-zh">{c.zh}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

// ============================================================================
// 德语词条视图 —— 德语专属，把本质特征做成一等展示：
// 名词 der/die/das 冠词 + 属格/复数著录；动词三基本形式（Infinitiv–Präteritum–
// Partizip II）+ 完成时助动词 haben/sein + 强弱/可分；形容词比较级/最高级。
// 自包含，不复用 es/it/fr/pt 的视图。
// ============================================================================

function deVclassLabel(v: string): string {
  const [base, cls] = v.split('-');
  const b = DE_VCLASS_BASE[base] || base;
  return cls ? `${b}·第${cls}类` : b;
}

function isNounPos(pos: string | null): boolean {
  if (!pos) return false;
  return pos.split('/').some((p) => p === 'n' || p === 'name');
}

function DeSenseChips({ sense }: { sense: DeSense }) {
  const chips: { cls: string; text: string }[] = [];
  for (const r of sense.regions) chips.push({ cls: 'reg', text: DE_REGION_LABELS[r] || r });
  for (const r of sense.registers) chips.push({ cls: 'lex', text: REGISTER_LABELS[r] || r });
  if (chips.length === 0) return null;
  return (
    <span className="sense-chips">
      {chips.map((c, i) => <span className={`sense-chip ${c.cls}`} key={i}>{c.text}</span>)}
    </span>
  );
}

function groupDeSenses(senses: DeSense[]): { pos: string | null; senses: DeSense[] }[] {
  const groups: { pos: string | null; senses: DeSense[] }[] = [];
  for (const s of senses) {
    const last = groups[groups.length - 1];
    if (last && last.pos === s.pos) last.senses.push(s);
    else groups.push({ pos: s.pos, senses: [s] });
  }
  return groups;
}

function GermanEntryView({ entry, speakLocale, onWord, speak }: {
  entry: DeEntry; speakLocale: string; onWord: (w: string) => void;
  speak: (word: string, locale: string) => void;
}) {
  const posParts = entry.pos ? entry.pos.split('/') : [];
  const isVerb = posParts.includes('v');
  const isNoun = posParts.some((p) => p === 'n' || p === 'name');
  const isAdj = posParts.some((p) => p === 'adj' || p === 'adv');
  const showStubPos = entry.isLemma && !!entry.pos && !entry.senses.some((s) => s.pos);
  const g0 = entry.gender ? entry.gender.split('/')[0] : null;
  const article = entry.gender ? (DE_ARTICLE[entry.gender] || DE_ARTICLE[g0 || ''] || '') : '';
  // 多性别名词（Band der/die/das 各自变格）：词头不塞单一冠词，改下方逐性别范式束展示
  const multiGender = isNoun && entry.isLemma && entry.nounVariants.length > 1;
  return (
    <article className="entry-detail">
      <header className="entry-header">
        <h2 className="entry-word">
          {isNoun && article && !multiGender && <span className={`de-article g-${g0}`}>{article} </span>}
          {entry.word}
        </h2>
      </header>

      {entry.ipa && (
        <div className="phonetic-row">
          <button className="phonetic-btn" onClick={() => speak(entry.word, speakLocale)} title="播放发音" type="button">
            <span className="phonetic-value">/{entry.ipa}/</span>
            <SpeakerIcon />
          </button>
        </div>
      )}

      {multiGender ? (
        <div className="de-noun-variants">
          {entry.nounVariants.map((v) => (
            <div className="de-nv-row" key={v.g}>
              <span className={`de-article g-${v.g}`}>{DE_ARTICLE[v.g] || ''}</span>
              {' '}<span className="de-nv-word">{entry.word}</span>
              {(v.gen || v.pl) && (
                <span className="de-nv-forms">
                  {v.gen && <>{' '}<span className="de-form-k">属格</span> {v.gen}</>}
                  {v.pl && <>{' '}<span className="de-form-k">复数</span> die {v.pl}</>}
                </span>
              )}
            </div>
          ))}
        </div>
      ) : (
        isNoun && entry.isLemma && (entry.genitive || entry.plural) && (
          <div className="de-forms">
            {entry.genitive && <span className="de-form"><span className="de-form-k">属格</span> {entry.genitive}</span>}
            {entry.plural && <span className="de-form"><span className="de-form-k">复数</span> die {entry.plural}</span>}
          </div>
        )
      )}

      {isVerb && entry.isLemma && (entry.praeteritum || entry.partizip2) && (
        <div className="de-forms de-stammformen">
          <span className="de-form"><span className="de-form-k">原形</span> {entry.word}</span>
          {entry.praeteritum && <span className="de-form"><span className="de-form-k">过去式</span> {entry.praeteritum}</span>}
          {entry.partizip2 && (
            <span className="de-form">
              <span className="de-form-k">过去分词</span>{' '}
              {entry.aux === 'sein' ? 'ist ' : entry.aux === 'haben' ? 'hat ' : ''}{entry.partizip2}
            </span>
          )}
        </div>
      )}

      {isAdj && !isVerb && entry.isLemma && (entry.comparative || entry.superlative) && (
        <div className="de-forms">
          <span className="de-form"><span className="de-form-k">原级</span> {entry.word}</span>
          {entry.comparative && <span className="de-form"><span className="de-form-k">比较级</span> {entry.comparative}</span>}
          {entry.superlative && <span className="de-form"><span className="de-form-k">最高级</span> {entry.superlative}</span>}
        </div>
      )}

      <div className="entry-meta-row entry-badges">
        {entry.level && <span className={`badge cefr cefr-${entry.level[0]}`}>{entry.level}</span>}
        {isNoun && multiGender ? (
          <span className="badge g g-mf">
            {entry.nounVariants.map((v) => GENDER_LABELS[v.g] || v.g).join('/')}性
          </span>
        ) : isNoun && entry.gender && (
          <span className={`badge g g-${g0}`}>{GENDER_LABELS[entry.gender] || entry.gender}性</span>
        )}
        {isVerb && entry.aux && (
          <span className={`badge aux aux-${entry.aux === 'sein' ? 'être' : 'avoir'}`}>{DE_AUX_LABELS[entry.aux]}</span>
        )}
        {isVerb && entry.vclass && (
          <span className="badge conj">{deVclassLabel(entry.vclass)}</span>
        )}
        {isVerb && entry.separable && (
          <span className="badge sep">可分 · {entry.sepPrefix}-</span>
        )}
        {isVerb && entry.reflexive && <span className="badge tag">反身 sich</span>}
        {entry.government && <span className="badge gov">支配 {entry.government}</span>}
        {showStubPos && <span className="badge pos">{posLabel(entry.pos)}</span>}
      </div>

      {entry.isLemma && entry.senses.length > 0 && (
        <section className="entry-section">
          <h3>释义</h3>
          {groupDeSenses(entry.senses).map((grp, gi) => (
            <div className="pos-group" key={gi}>
              {grp.pos && <div className="pos-group-label">{posLabel(grp.pos)}</div>}
              <ol className="sense-list">
                {grp.senses.map((s, i) => (
                  <li className="sense-item" key={i}>
                    <div className="sense-zh">
                      {s.zh || <span className="sense-missing">（待补）</span>}
                      <DeSenseChips sense={s} />
                    </div>
                    {s.en && <div className="sense-en">{s.en}</div>}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </section>
      )}

      {entry.baseForms.length > 0 && (
        <section className="entry-section">
          <h3>词形还原</h3>
          {entry.inflNotes.length > 0 && (
            <ul className="infl-notes">
              {entry.inflNotes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
          <div className="base-list">
            {entry.baseForms.map((bw) => {
              const base = entry.bases.find((b) => b.word === bw);
              const bg0 = base?.gender ? base.gender.split('/')[0] : null;
              const bArticle = base?.gender && isNounPos(base.pos)
                ? (DE_ARTICLE[base.gender] || DE_ARTICLE[bg0 || ''] || '') : '';
              return (
                <div className="base-item" key={bw}>
                  <a className="base-word" href={`#${encodeURIComponent(bw)}`}
                    onClick={(e) => { e.preventDefault(); onWord(bw); }}>
                    {bArticle ? `${bArticle} ` : ''}{bw}
                  </a>
                  {base?.pos && <span className="base-pos">{posLabel(base.pos)}</span>}
                  {base && base.senses.length > 0 && (() => {
                    const zhs = base.senses.map((s) => s.zh).filter(Boolean) as string[];
                    const CAP = 4;
                    const shown = zhs.slice(0, CAP).join('；');
                    return (
                      <span className="base-senses">
                        {shown}
                        {zhs.length > CAP && <span className="base-more">… 共 {zhs.length} 义，点词查看</span>}
                      </span>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {entry.collocations.length > 0 && (
        <section className="entry-section">
          <h3>搭配 / 固定短语</h3>
          <ul className="colloc-list">
            {entry.collocations.map((c, i) => (
              <li className="colloc-item" key={i}>
                <span className="colloc-text">{c.text}</span>
                {c.zh && <span className="colloc-zh">{c.zh}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
