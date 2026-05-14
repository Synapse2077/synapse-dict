import cors from 'cors';
import express from 'express';
import { DictionaryService, resolveDatabasePath } from '@synapse-dict/dict-core';

const app = express();
const port = Number(process.env.PORT || 4000);
const corsOrigin = process.env.CORS_ORIGIN || '*';
const service = new DictionaryService(resolveDatabasePath(process.env.DATABASE_PATH));

app.use(cors({ origin: corsOrigin }));
app.use(express.json());

app.get('/api/health', (_req, res) => {
  res.json({ ok: true, databasePath: service.databasePath });
});

app.get('/api/stats', (_req, res) => {
  res.json(service.getStats());
});

app.get('/api/search', (req, res) => {
  const query = String(req.query.q || '').trim();
  const limit = Math.min(Math.max(Number(req.query.limit || 20), 1), 50);

  if (!query) {
    res.json({ query, items: [] });
    return;
  }

  res.json({ query, items: service.search(query, limit) });
});

app.get('/api/entries/:word', (req, res) => {
  const word = String(req.params.word || '').trim();
  const entry = service.getEntry(word);

  if (!entry) {
    res.status(404).json({ message: 'Word not found' });
    return;
  }

  res.json(entry);
});

const server = app.listen(port, () => {
  console.log(`API ready at http://localhost:${port}`);
  console.log(`Using SQLite: ${service.databasePath}`);
});

function shutdown() {
  server.close(() => {
    service.close();
    process.exit(0);
  });
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
