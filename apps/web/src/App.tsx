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
    const match = line.match(/^([a-z]+\.)\s*(.+)$/);
    if (match) return { pos: match[1], text: match[2] };
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
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchItem[]>([]);
  const [selectedWord, setSelectedWord] = useState<string | null>(null);
  const [entry, setEntry] = useState<DictionaryEntry | null>(null);
  const [loading, setLoading] = useState(false);
  const [entryLoading, setEntryLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultListRef = useRef<HTMLDivElement>(null);

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

  // Search
  useEffect(() => {
    const keyword = query.trim();
    if (!keyword) {
      setResults([]);
      return;
    }

    const timer = window.setTimeout(async () => {
      try {
        setLoading(true);
        const response = await fetch(`/api/search?q=${encodeURIComponent(keyword)}&limit=20`);
        if (!response.ok) throw new Error('查询失败');
        const data = await response.json();
        const items = (data.items || []) as SearchItem[];
        setResults(items);
        setActiveIndex(0);
        // Auto-select first result
        if (items.length > 0) {
          selectWord(items[0].word);
        }
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 200);

    return () => window.clearTimeout(timer);
  }, [query, selectWord]);

  // Load entry
  useEffect(() => {
    if (!selectedWord) {
      setEntry(null);
      return;
    }

    let cancelled = false;
    async function loadEntry() {
      try {
        setEntryLoading(true);
        const response = await fetch(`/api/entries/${encodeURIComponent(selectedWord!)}`);
        if (!response.ok) throw new Error('词条加载失败');
        if (!cancelled) setEntry(await response.json());
      } catch {
        if (!cancelled) setEntry(null);
      } finally {
        if (!cancelled) setEntryLoading(false);
      }
    }
    void loadEntry();
    return () => { cancelled = true; };
  }, [selectedWord]);

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
        <div className="search-header">
          <h1>突触词典</h1>
        </div>
        <div className="search-input-wrap">
          <input
            ref={inputRef}
            className="search-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入单词查询..."
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
          {!loading && query.trim() && results.length === 0 && (
            <p className="no-results">没有找到匹配词条</p>
          )}
        </div>
      </div>

      <div className="detail-column">
        {entryLoading && <div className="detail-loading">加载中...</div>}
        {!entryLoading && entry && (
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
                <button
                  className="phonetic-item phonetic-btn"
                  onClick={() => speak(entry.word, 'en-GB')}
                  title="播放英式发音"
                  type="button"
                >
                  <span className="phonetic-label">UK</span>
                  <span className="phonetic-value">/{entry.phoneticUk}/</span>
                  <svg className="phonetic-speaker" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
                </button>
              )}
              {entry.phoneticUs && (
                <button
                  className="phonetic-item phonetic-btn"
                  onClick={() => speak(entry.word, 'en-US')}
                  title="播放美式发音"
                  type="button"
                >
                  <span className="phonetic-label">US</span>
                  <span className="phonetic-value">/{entry.phoneticUs}/</span>
                  <svg className="phonetic-speaker" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
                </button>
              )}
              {!entry.phoneticUk && !entry.phoneticUs && (
                <button
                  className="phonetic-item phonetic-btn"
                  onClick={() => speak(entry.word, 'en-US')}
                  title="播放发音"
                  type="button"
                >
                  {entry.phonetic && <span className="phonetic-value">/{entry.phonetic}/</span>}
                  <svg className="phonetic-speaker" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
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
        {!entryLoading && !entry && !selectedWord && (
          <div className="empty-state">
            <p>输入单词开始查询</p>
          </div>
        )}
      </div>
    </div>
  );
}
