import { useCallback, useEffect, useRef, useState } from 'react';

type SearchItem = {
  id: number;
  word: string;
  translation: string | null;
  definition: string | null;
  phoneticDisplay: string | null;
  pos: string | null;
};

type DictionaryEntry = SearchItem & {
  phonetic: string | null;
  phoneticUk: string | null;
  phoneticUs: string | null;
  exchange: string | null;
  detail: string | null;
  tag: string | null;
  collins: number | null;
  oxford: number | null;
  bnc: number | null;
  frq: number | null;
};

// 'rate' = throttled by the API (429/503); 'network' = anything else went wrong.
type FetchError = 'rate' | 'network';

const EXAMPLE_WORDS = ['serene', 'ephemeral', 'resilience', 'curious', 'nuance', 'vivid'];

// --- Parsing helpers ---

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
    // Match "n." "v." "a." "s." etc. at the start
    const match = line.match(/^([a-z]+\.)\s*(.+)$/);
    if (match) return { pos: match[1], text: match[2] };
    // Match single letter prefix without dot like "n " "v "
    const match2 = line.match(/^([a-z])\s+(.+)$/);
    if (match2) return { pos: match2[1] + '.', text: match2[2] };
    return { pos: '', text: line };
  });
}

const EXCHANGE_LABELS: Record<string, string> = {
  p: '过去式',
  d: '过去分词',
  i: '现在分词',
  '3': '第三人称单数',
  r: '比较级',
  t: '最高级',
  s: '复数',
  '0': '原形',
};

// "1" means "word form derived from type X" - it's metadata, not a linkable word
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

function speak(word: string, lang: 'en-GB' | 'en-US' = 'en-GB') {
  const utterance = new SpeechSynthesisUtterance(word);
  utterance.lang = lang;
  utterance.rate = 0.9;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

// Throw a typed error so the UI can distinguish "被限流了" from a real failure.
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
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchItem[]>([]);
  const [searchError, setSearchError] = useState<FetchError | null>(null);
  const [selectedWord, setSelectedWord] = useState<string | null>(null);
  const [entry, setEntry] = useState<DictionaryEntry | null>(null);
  const [entryError, setEntryError] = useState<FetchError | null>(null);
  const [loading, setLoading] = useState(false);
  const [entryLoading, setEntryLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultListRef = useRef<HTMLDivElement>(null);

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

  // Hash routing: read word from URL on mount
  useEffect(() => {
    const hash = window.location.hash.slice(1); // remove #
    if (hash) {
      const word = decodeURIComponent(hash);
      setSelectedWord(word);
      setQuery(word);
    }

    const onHashChange = () => {
      const h = window.location.hash.slice(1);
      if (h) {
        const w = decodeURIComponent(h);
        setSelectedWord(w);
      }
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // Update hash when word is selected
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
        const response = await fetch(`/api/search?q=${encodeURIComponent(keyword)}&limit=20`);
        classifyResponse(response);
        const data = await response.json();
        const items = (data.items || []) as SearchItem[];
        setResults(items);
        setActiveIndex(0);
        // Auto-select first result
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
  }, [query, selectWord, reloadKey]);

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
        const response = await fetch(`/api/entries/${encodeURIComponent(selectedWord!)}`);
        classifyResponse(response);
        if (!cancelled) setEntry(await response.json());
      } catch (e) {
        if (!cancelled) {
          setEntry(null);
          setEntryError(errorKind(e));
        }
      } finally {
        if (!cancelled) setEntryLoading(false);
      }
    }
    void loadEntry();
    return () => { cancelled = true; };
  }, [selectedWord, reloadKey]);

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

  // Scroll active result into view
  useEffect(() => {
    const container = resultListRef.current;
    if (!container) return;
    const active = container.querySelector('.result-item.active');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  const translations = entry ? parseTranslation(entry.translation) : [];
  const definitions = entry ? parseDefinition(entry.definition) : [];
  const exchanges = entry ? parseExchange(entry.exchange) : [];
  const tags = entry ? parseTags(entry.tag) : [];

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

        <div className="search-input-wrap">
          <svg className="search-icon" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
          <input
            ref={inputRef}
            className="search-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入单词查询…"
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
              <span className="result-brief">
                {item.translation?.split('\\n')[0] || item.definition?.split('\\n')[0] || ''}
              </span>
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
        {entryLoading && <div className="detail-loading">加载中…</div>}

        {!entryLoading && entryError && (
          <div className="detail-error">
            <span className="hint-emoji">{entryError === 'rate' ? '🌊' : '😕'}</span>
            <p>{entryError === 'rate' ? '请求有点频繁，稍等一下再试～' : '词条加载失败，请稍后重试'}</p>
            <button className="retry-btn" onClick={retry} type="button">重试</button>
          </div>
        )}

        {!entryLoading && !entryError && entry && (
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
                          <a
                            key={w}
                            className="exchange-link"
                            href={`#${encodeURIComponent(w)}`}
                            onClick={(e) => {
                              e.preventDefault();
                              setQuery(w);
                              selectWord(w);
                            }}
                          >
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
        )}

        {!entryLoading && !entryError && !entry && !selectedWord && (
          <div className="empty-state">
            <div className="empty-logo">突</div>
            <h1 className="empty-title">突触词典</h1>
            <p className="empty-desc">
              收录海量英文词条，含释义、音标、发音、词形变化与词频。<br />
              在左侧输入单词即可查询。
            </p>
            <div className="example-label">试试这些词</div>
            <div className="example-chips">
              {EXAMPLE_WORDS.map((w) => (
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
