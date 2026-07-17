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

type AnyEntry = EnEntry | KaikkiEntry;

// 'rate' = throttled by the API (429/503); 'network' = anything else went wrong.
type FetchError = 'rate' | 'network';

const EXAMPLES: Record<string, string[]> = {
  en: ['serene', 'ephemeral', 'resilience', 'curious', 'nuance', 'vivid'],
  es: ['hola', 'escalera', 'hablar', 'corazón', 'mariposa', 'rápido'],
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

function speak(word: string, locale: string) {
  const utterance = new SpeechSynthesisUtterance(word);
  utterance.lang = locale;
  utterance.rate = 0.9;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
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
  const [loading, setLoading] = useState(false);
  const [entryLoading, setEntryLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultListRef = useRef<HTMLDivElement>(null);
  const langInitDone = useRef(false);

  const activeLang = languages.find((l) => l.code === lang);
  const speakLocale = activeLang?.speak || 'en-US';

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
      return;
    }

    let cancelled = false;
    async function loadEntry() {
      try {
        setEntryLoading(true);
        setEntryError(null);
        const response = await fetch(`/api/entries/${encodeURIComponent(selectedWord!)}?lang=${lang}`);
        classifyResponse(response);
        if (!cancelled) setEntry(await response.json());
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
          <EnglishEntry entry={entry as EnEntry} onWord={goToWord} />
        )}

        {entry && entry.lang !== 'en' && (
          <KaikkiEntryView entry={entry as KaikkiEntry} speakLocale={speakLocale} onWord={goToWord} />
        )}

        {!entry && entryLoading && <div className="detail-loading">加载中…</div>}

        {!entry && !entryLoading && entryError && (
          <div className="detail-error">
            <span className="hint-emoji">{entryError === 'rate' ? '🌊' : '😕'}</span>
            <p>{entryError === 'rate' ? '请求有点频繁，稍等一下再试～' : '词条加载失败，请稍后重试'}</p>
            <button className="retry-btn" onClick={retry} type="button">重试</button>
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
    </div>
  );
}

// --- English entry detail (unchanged layout) ---

function EnglishEntry({ entry, onWord }: { entry: EnEntry; onWord: (w: string) => void }) {
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
  if (sense.gender) chips.push({ cls: 'g', text: GENDER_LABELS[sense.gender] || sense.gender });
  for (const r of sense.regions) chips.push({ cls: 'reg', text: r });
  for (const r of sense.registers) chips.push({ cls: 'lex', text: r });
  for (const n of sense.numbers) chips.push({ cls: 'num', text: n });
  if (chips.length === 0) return null;
  return (
    <span className="sense-chips">
      {chips.map((c, i) => <span className={`sense-chip ${c.cls}`} key={i}>{c.text}</span>)}
    </span>
  );
}

function KaikkiEntryView({ entry, speakLocale, onWord }: {
  entry: KaikkiEntry; speakLocale: string; onWord: (w: string) => void;
}) {
  return (
    <article className="entry-detail">
      <header className="entry-header">
        <h2 className="entry-word">{entry.word}</h2>
        <div className="entry-meta-row">
          {entry.pos && <span className="badge pos">{entry.pos}</span>}
          {entry.reflexive && <span className="badge tag">代动词 prnl.</span>}
          {!entry.isLemma && <span className="badge tag">变位形式</span>}
        </div>
      </header>

      {entry.phonetic && (
        <div className="phonetic-row">
          <button className="phonetic-btn" onClick={() => speak(entry.word, speakLocale)} title="播放发音" type="button">
            <span className="phonetic-value">{entry.phonetic}</span>
            <SpeakerIcon />
          </button>
        </div>
      )}

      {/* 真义 lemma：逐义项中文 + 英文锚点 + 性别/地区/语域 chip */}
      {entry.isLemma && entry.senses.length > 0 && (
        <section className="entry-section">
          <h3>释义</h3>
          <ol className="sense-list">
            {entry.senses.map((s, i) => (
              <li className="sense-item" key={i}>
                <div className="sense-zh">
                  {s.zh || <span className="sense-missing">（待补）</span>}
                  <SenseChips sense={s} />
                </div>
                {s.en && <div className="sense-en">{s.en}</div>}
              </li>
            ))}
          </ol>
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
                  {base?.pos && <span className="base-pos">{base.pos}</span>}
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
