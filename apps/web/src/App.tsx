import { useCallback, useEffect, useRef, useState } from 'react';

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

// Kaikki-family entry (es / fr / it / pt / no — same schema)
type KaikkiSense = {
  en: string | null;
  zh: string | null;
  pos: string | null;
  gender: string | null;
  regions: string[];
  registers: string[];
  numbers: string[];
};
type KaikkiCollocation = { text: string; zh: string | null };
type KaikkiBase = {
  word: string;
  pos: string | null;
  phonetic: string | null;
  senses: KaikkiSense[];
};
type KaikkiEntry = {
  lang: string;
  id: number;
  word: string;
  phonetic: string | null;
  pos: string | null;
  isLemma: boolean;
  reflexive: boolean;
  senses: KaikkiSense[];
  collocations: KaikkiCollocation[];
  baseForms: string[];
  bases: KaikkiBase[];
  inflNotes: string[];
  flag: string | null;
};

// Italian entry (意语专属 schema：本质字段 aux/conj/gender/plural 为一等公民)
type ItSense = {
  en: string | null;
  zh: string | null;
  pos: string | null;
  regions: string[];
  registers: string[];
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
  numberNote: string | null;
  senses: ItSense[];
  collocations: ItCollocation[];
  baseForms: string[];
  bases: ItBase[];
  inflNotes: string[];
  flag: string | null;
};

type AnyEntry = EnEntry | KaikkiEntry | ItEntry;

// 'rate' = throttled by the API (429/503); 'network' = anything else went wrong.
type FetchError = 'rate' | 'network';

const EXAMPLES: Record<string, string[]> = {
  en: ['serene', 'ephemeral', 'resilience', 'curious', 'nuance', 'vivid'],
  es: ['hola', 'escalera', 'hablar', 'corazón', 'mariposa', 'rápido'],
  it: ['ciao', 'mangiare', 'braccio', 'bello', 'andare', 'città'],
};

// --- English parsing helpers ---

function parseTranslation(raw: string | null): { pos: string; text: string }[] {
  if (!raw) return [];
  return raw.split('\\n').filter(Boolean).map((line) => {
    const match = line.match(/^([a-z]+\.)\s*(.+)$/);
    if (match) return { pos: match[1], text: match[2] };
    return { pos: '', text: line };
  });
}

function parseDefinition(raw: string | null): { pos: string; text: string }[] {
  if (!raw) return [];
  return raw.split('\\n').filter(Boolean).map((line) => {
    const match = line.match(/^([a-z]+\.)\s*(.+)$/);
    if (match) return { pos: match[1], text: match[2] };
    const match2 = line.match(/^([a-z])\s+(.+)$/);
    if (match2) return { pos: match2[1] + '.', text: match2[2] };
    return { pos: '', text: line };
  });
}

const EXCHANGE_LABELS: Record<string, string> = {
  p: '过去式', d: '过去分词', i: '现在分词', '3': '第三人称单数',
  r: '比较级', t: '最高级', s: '复数', '0': '原形',
};
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

// --- Spanish/Kaikki display helpers ---

const GENDER_LABELS: Record<string, string> = { f: '阴', m: '阳', mf: '阴/阳', n: '中' };

// 逐义项词性 → 中文标签（对应 build.py POS_MAP 的短码）。
const POS_LABELS: Record<string, string> = {
  n: '名词', name: '专名', adj: '形容词', adv: '副词', v: '动词', pron: '代词',
  prep: '介词', conj: '连词', det: '限定词', num: '数词', intj: '感叹词',
  pref: '前缀', suf: '后缀', phr: '短语', contr: '缩合', art: '冠词', prov: '谚语',
};

// 地区标签 → 中文（对应 build.py REGIONS）。映射不到回退原文。
const REGION_LABELS: Record<string, string> = {
  Spain: '西班牙', 'Canary-Islands': '加那利群岛', Andalusia: '安达卢西亚',
  'Latin-America': '拉美', Mexico: '墨西哥', Chile: '智利', Colombia: '哥伦比亚',
  Peru: '秘鲁', Venezuela: '委内瑞拉', Cuba: '古巴', Bolivia: '玻利维亚',
  Ecuador: '厄瓜多尔', Guatemala: '危地马拉', Honduras: '洪都拉斯', Nicaragua: '尼加拉瓜',
  'Costa-Rica': '哥斯达黎加', Paraguay: '巴拉圭', Uruguay: '乌拉圭',
  'Dominican-Republic': '多米尼加', 'Puerto-Rico': '波多黎各', Caribbean: '加勒比',
  Rioplatense: '拉普拉塔河地区', Argentina: '阿根廷', Panama: '巴拿马',
  'El-Salvador': '萨尔瓦多', 'Central-America': '中美洲', 'South-America': '南美洲',
  'North-America': '北美洲', Philippines: '菲律宾', US: '美国', UK: '英国',
  Canada: '加拿大', Australia: '澳大利亚', Louisiana: '路易斯安那', Texas: '得州',
  California: '加州', 'New-York-City': '纽约市', Aragon: '阿拉贡', Asturias: '阿斯图里亚斯',
  Galicia: '加利西亚', Navarre: '纳瓦拉', Tenerife: '特内里费', Seville: '塞维利亚',
  Valencia: '巴伦西亚', Catalonia: '加泰罗尼亚', Mallorca: '马略卡', Belize: '伯利兹',
  Antilles: '安的列斯', Guerrero: '格雷罗', Puebla: '普埃布拉', Bogota: '波哥大',
  Manila: '马尼拉', Llanos: '亚诺斯平原', Morocco: '摩洛哥', Angola: '安哥拉',
  'Equatorial-Guinea': '赤道几内亚', Iberian: '伊比利亚', European: '欧洲',
  'European-Union': '欧盟', EU: '欧盟', Lunfardo: '隆法多黑话', 'Southern-Spain': '西班牙南部',
  Northern: '北部', Southern: '南部', Eastern: '东部', Western: '西部',
  Northeastern: '东北部', Northwestern: '西北部', Southeastern: '东南部',
  Southwestern: '西南部', Central: '中部',
};

// 语域标签 → 中文（对应 build.py REGISTERS）。
const REGISTER_LABELS: Record<string, string> = {
  colloquial: '口语', vulgar: '粗俗', slang: '俚语', derogatory: '贬义',
  offensive: '冒犯', humorous: '诙谐', literary: '文学', dated: '旧式',
  euphemistic: '委婉', informal: '非正式', formal: '正式', pejorative: '贬义',
  childish: '童语', poetic: '诗歌', familiar: '亲昵', proscribed: '非规范',
  nonstandard: '非标准', obsolete: '废弃', historical: '历史', archaic: '古语',
  rare: '罕见', uncommon: '少见', neologism: '新词', Internet: '网络',
  misspelling: '误拼', 'pronunciation-spelling': '音写', dialectal: '方言',
  regional: '地区性', jargon: '行话', slur: '蔑称', ironic: '反讽',
  sarcastic: '讽刺', endearing: '亲昵', emphatic: '强调', rhetoric: '修辞',
  bureaucratese: '官腔', Leet: 'Leet黑话', figuratively: '比喻',
};

// 数属性 → 中文（对应 build.py NUMBER）。
const NUMBER_LABELS: Record<string, string> = {
  uncountable: '不可数', 'plural-only': '仅复数', invariable: '单复同形', collective: '集合',
};

// 词性短码 → 中文（支持 "n/v" 这种聚合，逐段映射后再拼），全站统一显示。
function posLabel(raw: string | null): string {
  if (!raw) return '';
  return raw.split('/').map((p) => POS_LABELS[p] || p).join('/');
}

// 义项按相邻相同词性分组（definition 本就按词性成段，相邻聚合即可）。
function groupSensesByPos(senses: KaikkiSense[]): { pos: string | null; senses: KaikkiSense[] }[] {
  const groups: { pos: string | null; senses: KaikkiSense[] }[] = [];
  for (const s of senses) {
    const last = groups[groups.length - 1];
    if (last && last.pos === s.pos) last.senses.push(s);
    else groups.push({ pos: s.pos, senses: [s] });
  }
  return groups;
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

// 按 locale 找语音：先精确匹配（es-ES），再退到同语言（任意 es-*）。找不到返回 null。
function findVoice(locale: string): SpeechSynthesisVoice | null {
  if (voiceCache.length === 0) refreshVoices();
  const lc = locale.toLowerCase();
  const base = lc.split('-')[0];
  return (
    voiceCache.find((v) => v.lang.toLowerCase() === lc) ||
    voiceCache.find((v) => v.lang.toLowerCase().startsWith(base)) ||
    null
  );
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

function getInitialLang(): string {
  try {
    const saved = localStorage.getItem('dict-lang');
    if (saved) return saved;
  } catch {
    // ignore
  }
  return 'en';
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
        setActiveIndex(0);
        if (items.length > 0) {
          selectWord(items[0].word);
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

        {entry && entry.lang !== 'en' && entry.lang !== 'it' && (
          <KaikkiEntryView entry={entry as KaikkiEntry} speakLocale={speakLocale} onWord={goToWord} speak={speakWord} />
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
            <span className="phonetic-label">UK</span>
            <span className="phonetic-value">/{entry.phoneticUk}/</span>
            <SpeakerIcon />
          </button>
        )}
        {entry.phoneticUs && (
          <button className="phonetic-btn" onClick={() => speak(entry.word, 'en-US')} title="播放美式发音" type="button">
            <span className="phonetic-label">US</span>
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

// --- Spanish / Kaikki entry detail ---

function SenseChips({ sense }: { sense: KaikkiSense }) {
  const chips: { cls: string; text: string }[] = [];
  if (sense.gender) chips.push({ cls: `g g-${sense.gender}`, text: GENDER_LABELS[sense.gender] || sense.gender });
  for (const r of sense.regions) chips.push({ cls: 'reg', text: REGION_LABELS[r] || r });
  for (const r of sense.registers) chips.push({ cls: 'lex', text: REGISTER_LABELS[r] || r });
  for (const n of sense.numbers) chips.push({ cls: 'num', text: NUMBER_LABELS[n] || n });
  if (chips.length === 0) return null;
  return (
    <span className="sense-chips">
      {chips.map((c, i) => <span className={`sense-chip ${c.cls}`} key={i}>{c.text}</span>)}
    </span>
  );
}

function KaikkiEntryView({ entry, speakLocale, onWord, speak }: {
  entry: KaikkiEntry; speakLocale: string; onWord: (w: string) => void;
  speak: (word: string, locale: string) => void;
}) {
  // 空壳 lemma（有释义但义项无 pos）才显示聚合词性 badge。变位形式不挂标签——
  // 下方「变位形式」区块已含语法说明+原形，头部再标一个纯属重复。
  const showStubPos = entry.isLemma && !!entry.pos && !entry.senses.some((s) => s.pos);
  const hasBadges = showStubPos || entry.reflexive;
  return (
    <article className="entry-detail">
      {/* 音标紧跟单词；标签（变位形式/代动词/空壳词性）移到音标下方 */}
      <header className="entry-header">
        <h2 className="entry-word">{entry.word}</h2>
      </header>

      {entry.phonetic && (
        <div className="phonetic-row">
          <button className="phonetic-btn" onClick={() => speak(entry.word, speakLocale)} title="播放发音" type="button">
            <span className="phonetic-value">{entry.phonetic}</span>
            <SpeakerIcon />
          </button>
        </div>
      )}

      {hasBadges && (
        <div className="entry-meta-row entry-badges">
          {showStubPos && <span className="badge pos">{posLabel(entry.pos)}</span>}
          {entry.reflexive && <span className="badge tag">代动词 prnl.</span>}
        </div>
      )}

      {/* 真义 lemma：按词性分组，组内逐义项中文 + 英文锚点 + 性别/地区/语域 chip */}
      {entry.isLemma && entry.senses.length > 0 && (
        <section className="entry-section">
          <h3>释义</h3>
          {groupSensesByPos(entry.senses).map((grp, gi) => (
            <div className="pos-group" key={gi}>
              {grp.pos && (
                <div className="pos-group-label">{posLabel(grp.pos)}</div>
              )}
              <ol className="sense-list">
                {grp.senses.map((s, i) => (
                  <li className="sense-item" key={i}>
                    <div className="sense-zh">
                      {s.zh || <span className="sense-missing">（待补）</span>}
                      <SenseChips sense={s} />
                    </div>
                    {s.en && <div className="sense-en">{s.en}</div>}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </section>
      )}

      {/* 变位形式：指回原形 + 各原形的词义 + 语法说明 */}
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
// 自包含，不复用西语的 KaikkiEntryView。
// ============================================================================

const AUX_LABELS: Record<string, string> = {
  avere: '助动词 avere', essere: '助动词 essere', both: '助动词 avere/essere',
};
const CONJ_LABELS: Record<string, string> = {
  '1': '第一变位 -are', '2': '第二变位 -ere', '3': '第三变位 -ire', '3isc': '第三变位 -ire (-isc-)',
};
const TRANS_LABELS: Record<string, string> = { t: '及物', i: '不及物', ti: '及物/不及物' };
const NUMBER_NOTE_LABELS: Record<string, string> = {
  invariable: '单复同形', 'plural-only': '仅复数', 'singular-only': '仅单数',
  uncountable: '不可数', collective: '集合名词',
};
// 意语地区标签（意语专属，不复用西语 REGION_LABELS）。映射不到回退原文。
const IT_REGION_LABELS: Record<string, string> = {
  Italy: '意大利', Tuscany: '托斯卡纳', Switzerland: '瑞士意语区', Sardinia: '撒丁岛',
  Sicily: '西西里', Naples: '那不勒斯', Rome: '罗马', Florence: '佛罗伦萨', Milan: '米兰',
  Venice: '威尼斯', Turin: '都灵', Genoa: '热那亚', Bologna: '博洛尼亚', Lombardy: '伦巴第',
  Piedmont: '皮埃蒙特', Veneto: '威尼托', Campania: '坎帕尼亚', Calabria: '卡拉布里亚',
  Apulia: '普利亚', Abruzzo: '阿布鲁佐', Lazio: '拉齐奥', Liguria: '利古里亚',
  Umbria: '翁布里亚', Marche: '马尔凯', Molise: '莫利塞', Basilicata: '巴西利卡塔',
  Friuli: '弗留利', Trentino: '特伦蒂诺', 'Northern-Italy': '意大利北部',
  'Southern-Italy': '意大利南部', 'Central-Italy': '意大利中部', Northern: '北部',
  Southern: '南部', Eastern: '东部', Western: '西部', Central: '中部',
  regional: '地区性', dialectal: '方言', 'Ancient-Rome': '古罗马', Roman: '罗马',
};

// 显示用：去掉连结弧 U+0361（t͡ʃ→tʃ）。它是最脆弱的组合字符，多数字体不渲染而显示为空，
// 去掉后 tʃ/dʒ/ts/dz 读音等价、任何字体都能正常显示；DB 内仍保留精确的 t͡ʃ。
function displayIpa(ipa: string | null): string | null {
  return ipa ? ipa.replace(/͡/g, '') : ipa;
}

function ItSenseChips({ sense }: { sense: ItSense }) {
  const chips: { cls: string; text: string }[] = [];
  for (const r of sense.regions) chips.push({ cls: 'reg', text: IT_REGION_LABELS[r] || r });
  for (const r of sense.registers) chips.push({ cls: 'lex', text: REGISTER_LABELS[r] || r });
  if (chips.length === 0) return null;
  return (
    <span className="sense-chips">
      {chips.map((c, i) => <span className={`sense-chip ${c.cls}`} key={i}>{c.text}</span>)}
    </span>
  );
}

function groupItSenses(senses: ItSense[]): { pos: string | null; senses: ItSense[] }[] {
  const groups: { pos: string | null; senses: ItSense[] }[] = [];
  for (const s of senses) {
    const last = groups[groups.length - 1];
    if (last && last.pos === s.pos) last.senses.push(s);
    else groups.push({ pos: s.pos, senses: [s] });
  }
  return groups;
}

function ItalianEntryView({ entry, speakLocale, onWord, speak }: {
  entry: ItEntry; speakLocale: string; onWord: (w: string) => void;
  speak: (word: string, locale: string) => void;
}) {
  const isVerb = !!entry.pos && entry.pos.split('/').includes('v');
  const isNoun = !!entry.pos && entry.pos.split('/').some((p) => p === 'n' || p === 'name');
  const showStubPos = entry.isLemma && !!entry.pos && !entry.senses.some((s) => s.pos);
  return (
    <article className="entry-detail">
      <header className="entry-header">
        <h2 className="entry-word">{entry.word}</h2>
      </header>

      {entry.ipa && (
        <div className="phonetic-row">
          <button className="phonetic-btn" onClick={() => speak(entry.word, speakLocale)} title="播放发音" type="button">
            <span className="phonetic-value">{displayIpa(entry.ipa)}</span>
            <SpeakerIcon />
          </button>
        </div>
      )}

      {/* 意语本质徽标：动词看助动词/变位类/及物性，名词看性别/复数 */}
      <div className="entry-meta-row entry-badges">
        {isNoun && entry.gender && (
          <span className={`badge g g-${entry.gender}`}>{GENDER_LABELS[entry.gender] || entry.gender}性</span>
        )}
        {isNoun && entry.plural && (
          <span className="badge plural">
            复数 {entry.plural}
            {entry.pluralGender && <span className="plural-shift">〈{GENDER_LABELS[entry.pluralGender]}〉</span>}
          </span>
        )}
        {isNoun && entry.numberNote && (
          <span className="badge num">{NUMBER_NOTE_LABELS[entry.numberNote] || entry.numberNote}</span>
        )}
        {isVerb && entry.aux && (
          <span className={`badge aux aux-${entry.aux}`}>{AUX_LABELS[entry.aux]}</span>
        )}
        {isVerb && entry.conj && (
          <span className="badge conj">{CONJ_LABELS[entry.conj] || entry.conj}</span>
        )}
        {isVerb && entry.transitivity && (
          <span className="badge tag">{TRANS_LABELS[entry.transitivity] || entry.transitivity}</span>
        )}
        {entry.pronominal && <span className="badge tag">代动词 prnl.</span>}
        {showStubPos && <span className="badge pos">{posLabel(entry.pos)}</span>}
      </div>

      {/* 异性复数（metaplasmic）提示：意语招牌，braccio(阳)→braccia(阴) */}
      {isNoun && entry.pluralGender && entry.plural && (
        <div className="it-note">
          异性复数：单数 <b>{entry.word}</b>（{GENDER_LABELS[entry.gender || 'm']}）→ 复数{' '}
          <b>{entry.plural}</b>（{GENDER_LABELS[entry.pluralGender]}）
        </div>
      )}

      {entry.isLemma && entry.senses.length > 0 && (
        <section className="entry-section">
          <h3>释义</h3>
          {groupItSenses(entry.senses).map((grp, gi) => (
            <div className="pos-group" key={gi}>
              {grp.pos && <div className="pos-group-label">{posLabel(grp.pos)}</div>}
              <ol className="sense-list">
                {grp.senses.map((s, i) => (
                  <li className="sense-item" key={i}>
                    <div className="sense-zh">
                      {s.zh || <span className="sense-missing">（待补）</span>}
                      <ItSenseChips sense={s} />
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
                  {base?.aux && <span className="base-pos">{AUX_LABELS[base.aux]}</span>}
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
