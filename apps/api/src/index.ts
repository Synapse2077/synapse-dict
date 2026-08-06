import './assertNodeVersion'; // 必须放最前：抢在 dict-core 的 node:sqlite import 求值之前断言 Node 版本
import cors from 'cors';
import express from 'express';
import type { Request } from 'express';
import fs from 'node:fs';
import { availableLanguages, closeAllServices, getService, ttsDirFor } from '@synapse-dict/dict-core';
import { createRateLimiter, rateLimitOptionsFromEnv } from './rateLimit';

const app = express();
const port = Number(process.env.PORT || 4000);
const corsOrigin = process.env.CORS_ORIGIN || '*';

// 只认 DB 文件存在的语言；?lang= 不合法或缺省一律回退到列表首位（通常 en）。
const langs = availableLanguages();
const codes = new Set(langs.map((l) => l.code));
const defaultLang = langs[0]?.code || 'en';

function pickLang(req: Request): string {
  const q = String(req.query.lang || '').trim();
  return codes.has(q) ? q : defaultLang;
}

// Honor X-Forwarded-For when running behind a reverse proxy so per-IP limits
// key on the real client, not the proxy. Enable via TRUST_PROXY (e.g. "1").
if (process.env.TRUST_PROXY) {
  app.set('trust proxy', process.env.TRUST_PROXY);
}

app.use(cors({ origin: corsOrigin }));
app.use(express.json());

// Health check stays unthrottled so monitoring keeps working under load.
app.get('/api/health', (_req, res) => {
  res.json({ ok: true, languages: langs.map((l) => l.code) });
});

// 可用语言列表 —— 前端据此渲染切换器。
app.get('/api/langs', (_req, res) => {
  res.json({ languages: langs, default: defaultLang });
});

// 合成发音的音频文件（`es/pipeline/gen_tts.py` 产物）。挂在 /api/… 之下是为了
// 复用前端已有的 vite 代理（只代理了 /api），不必再开一条转发规则。
// 放在限流**之前**：一个词条页会连着取音频，按 API 调用限流会把播放掐掉；
// 而这里是纯静态小文件（约 10 KB），交给 express.static 走 sendfile，不碰 SQLite。
// 文件名是 sha1，天然不可枚举；目录不存在的语种直接跳过。
for (const l of langs) {
  const dir = ttsDirFor(l.code);
  if (!fs.existsSync(dir)) continue;
  app.use(`/api/audio/${l.code}`, express.static(dir, {
    immutable: true,            // 内容由 sha1 定址，永不变
    maxAge: '365d',
    fallthrough: false,         // 没有就 404，别掉到后面的路由里
  }));
}

// Throttle the query endpoints — these hit the synchronous, shared SQLite that
// synapse-web also reads, so an unbounded flood here can starve web too.
app.use(createRateLimiter(rateLimitOptionsFromEnv()));

app.get('/api/stats', (req, res) => {
  const lang = pickLang(req);
  res.json({ lang, ...getService(lang).getStats() });
});

app.get('/api/search', (req, res) => {
  const lang = pickLang(req);
  const query = String(req.query.q || '').trim();
  const limit = Math.min(Math.max(Number(req.query.limit || 20), 1), 50);

  if (!query) {
    res.json({ lang, query, items: [] });
    return;
  }

  res.json({ lang, query, items: getService(lang).search(query, limit) });
});

app.get('/api/entries/:word', (req, res) => {
  const lang = pickLang(req);
  const word = String(req.params.word || '').trim();
  const entry = getService(lang).getEntry(word);

  if (!entry) {
    res.status(404).json({ message: 'Word not found' });
    return;
  }

  res.json(entry);
});

const server = app.listen(port, () => {
  console.log(`API ready at http://localhost:${port}`);
  console.log(`Languages: ${langs.map((l) => `${l.code}(${l.name})`).join(', ') || '(none)'}`);
});

function shutdown() {
  server.close(() => {
    closeAllServices();
    process.exit(0);
  });
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
