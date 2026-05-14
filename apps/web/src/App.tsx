import { useEffect, useMemo, useState } from 'react';

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

type DictionaryStats = {
  total: number;
  translated: number;
  phoneticUk: number;
  phoneticUs: number;
  definitions: number;
};

function formatNumber(value: number | null | undefined) {
  if (value == null) {
    return '-';
  }

  return new Intl.NumberFormat('zh-CN').format(value);
}

export default function App() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchItem[]>([]);
  const [selectedWord, setSelectedWord] = useState<string | null>(null);
  const [entry, setEntry] = useState<DictionaryEntry | null>(null);
  const [stats, setStats] = useState<DictionaryStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [entryLoading, setEntryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/stats')
      .then((response) => response.json())
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  useEffect(() => {
    const keyword = query.trim();
    if (!keyword) {
      setResults([]);
      setSelectedWord(null);
      setEntry(null);
      setError(null);
      return;
    }

    const timer = window.setTimeout(async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await fetch(`/api/search?q=${encodeURIComponent(keyword)}&limit=20`);
        if (!response.ok) {
          throw new Error('查询失败');
        }

        const data = await response.json();
        const nextItems = (data.items || []) as SearchItem[];
        setResults(nextItems);
        setSelectedWord(nextItems[0]?.word ?? null);
      } catch (fetchError) {
        setResults([]);
        setSelectedWord(null);
        setEntry(null);
        setError(fetchError instanceof Error ? fetchError.message : '查询失败');
      } finally {
        setLoading(false);
      }
    }, 250);

    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!selectedWord) {
      setEntry(null);
      return;
    }

    const activeWord = selectedWord;

    async function loadEntry() {
      try {
        setEntryLoading(true);
        const response = await fetch(`/api/entries/${encodeURIComponent(activeWord)}`);
        if (!response.ok) {
          throw new Error('词条加载失败');
        }

        setEntry((await response.json()) as DictionaryEntry);
      } catch (fetchError) {
        setEntry(null);
        setError(fetchError instanceof Error ? fetchError.message : '词条加载失败');
      } finally {
        setEntryLoading(false);
      }
    }

    void loadEntry();
  }, [selectedWord]);

  const headerStats = useMemo(() => {
    if (!stats) {
      return [];
    }

    return [
      { label: '总词条', value: formatNumber(stats.total) },
      { label: '中文翻译', value: formatNumber(stats.translated) },
      { label: '英式音标', value: formatNumber(stats.phoneticUk) },
      { label: '英文释义', value: formatNumber(stats.definitions) },
    ];
  }, [stats]);

  return (
    <div className="page-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Synapse Dict</p>
          <h1>基于 SQLite 的可复用词典工程</h1>
          <p className="hero-copy">
            页面查询和项目复用都围绕同一个 `synapse-dict.sqlite`，前端只负责检索体验，数据资产保持独立。
          </p>
        </div>
        <div className="stats-grid">
          {headerStats.map((item) => (
            <section className="stat-card" key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </section>
          ))}
        </div>
      </header>

      <main className="workspace">
        <section className="panel search-panel">
          <div className="panel-header">
            <h2>查询</h2>
            <p>支持精确匹配、前缀匹配和模糊检索。</p>
          </div>
          <label className="search-box">
            <span>输入英文单词</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="例如 apple / democracy / jagoffs"
            />
          </label>
          {loading ? <p className="status">正在查询...</p> : null}
          {error ? <p className="status error">{error}</p> : null}
          {!loading && query.trim() && results.length === 0 && !error ? (
            <p className="status">没有找到匹配词条。</p>
          ) : null}
          <div className="result-list">
            {results.map((item) => (
              <button
                className={item.word === selectedWord ? 'result-item active' : 'result-item'}
                key={item.id}
                onClick={() => setSelectedWord(item.word)}
                type="button"
              >
                <div>
                  <strong>{item.word}</strong>
                  <span>{item.phoneticDisplay ? `/${item.phoneticDisplay}/` : '无音标'}</span>
                </div>
                <p>{item.translation || item.definition || '暂无释义'}</p>
              </button>
            ))}
          </div>
        </section>

        <section className="panel detail-panel">
          <div className="panel-header">
            <h2>词条详情</h2>
            <p>优先展示英美音标和中文释义，同时保留原始频次与标签字段。</p>
          </div>
          {entryLoading ? <p className="status">正在加载词条...</p> : null}
          {!entryLoading && entry ? (
            <article className="entry-card">
              <div className="entry-title">
                <div>
                  <h3>{entry.word}</h3>
                  <p>{entry.pos || '未标注词性'}</p>
                </div>
                <div className="phonetics">
                  <span>UK: {entry.phoneticUk || entry.phonetic || '-'}</span>
                  <span>US: {entry.phoneticUs || entry.phonetic || '-'}</span>
                </div>
              </div>

              <section>
                <h4>中文翻译</h4>
                <pre>{entry.translation || '暂无中文翻译'}</pre>
              </section>

              <section>
                <h4>英文释义</h4>
                <pre>{entry.definition || '暂无英文释义'}</pre>
              </section>

              <section className="meta-grid">
                <div>
                  <span>Collins</span>
                  <strong>{formatNumber(entry.collins)}</strong>
                </div>
                <div>
                  <span>Oxford</span>
                  <strong>{formatNumber(entry.oxford)}</strong>
                </div>
                <div>
                  <span>BNC</span>
                  <strong>{formatNumber(entry.bnc)}</strong>
                </div>
                <div>
                  <span>FRQ</span>
                  <strong>{formatNumber(entry.frq)}</strong>
                </div>
              </section>

              <section>
                <h4>附加字段</h4>
                <pre>{entry.exchange || entry.detail || entry.tag || '暂无附加信息'}</pre>
              </section>
            </article>
          ) : null}
          {!entryLoading && !entry ? (
            <div className="empty-state">
              <h3>选择左侧结果查看详情</h3>
              <p>如果你准备给别的项目直接用词库，目标文件位于 `data/synapse-dict.sqlite`。</p>
            </div>
          ) : null}
        </section>
      </main>
    </div>
  );
}
