import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// ═══ 闪动探针的落盘端（2026-09-25，只在 dev 服务器上存在）═══
// 浏览器里的 `src/flicker-probe.ts` 把事件 POST 到 /__flicker，这里追加成 JSONL。
// 走 dev 服务器而不是 API（:4000）：这是**开发期诊断**，不该碰生产服务；
// 生产构建里这个中间件根本不存在（`apply: 'serve'`）。
const FLICKER_LOG =
  process.env.FLICKER_LOG ||
  path.join(path.dirname(fileURLToPath(import.meta.url)), '.flicker.jsonl');

function flickerLog(): Plugin {
  return {
    name: 'flicker-log',
    apply: 'serve',
    configureServer(server) {
      server.config.logger.info('[闪动探针] 日志 → ' + FLICKER_LOG);
      server.middlewares.use('/__flicker', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405;
          res.end();
          return;
        }
        const chunks: Buffer[] = [];
        req.on('data', (c: Buffer) => chunks.push(c));
        req.on('end', () => {
          try {
            const body = Buffer.concat(chunks).toString('utf8').trim();
            if (body) fs.appendFileSync(FLICKER_LOG, body + '\n');
          } catch {
            /* 诊断工具不许把被诊断的东西搞挂 */
          }
          res.statusCode = 204;
          res.end();
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), flickerLog()],
  server: {
    host: '0.0.0.0',
    port: 5181,
    hmr: {
      host: 'localhost',
    },
    proxy: {
      '/api': {
        target: 'http://localhost:4000',
        changeOrigin: true,
      },
    },
  },
});
