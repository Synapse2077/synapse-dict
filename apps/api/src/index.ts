import './assertNodeVersion'; // 必须放最前：抢在 dict-core 的 node:sqlite import 求值之前断言 Node 版本
import cors from 'cors';
import express from 'express';
import type { Request, RequestHandler, Response } from 'express';
import fs from 'node:fs';
import {
  closeAllServices, dataDir, getService, probeLanguages, ttsDirFor,
  type LanguageProbe,
} from '@synapse-dict/dict-core';
import { createRateLimiter, rateLimitOptionsFromEnv } from './rateLimit';
import { ApiError, errorHandler, notFound, notFoundHandler, unavailable } from './errors';
import { parseLimit, parseQuery, parseWord } from './validate';

const app = express();
const port = Number(process.env.PORT || 4000);
const corsOrigin = process.env.CORS_ORIGIN || '*';
const exposeErrors = process.env.EXPOSE_ERRORS === '1';
/** 超过这个毫秒数的请求打一条 warn。SQLite 是同步的，慢请求＝事件循环被占住那么久。 */
const SLOW_MS = Number(process.env.SLOW_REQUEST_MS || 200);

// 不广播用的是什么框架 —— 默认会回 `X-Powered-By: Express`。
app.disable('x-powered-by');

// ════════════════════════════════════════════════════════════════════════
//  启动自检 & 降级
//
//  🔴 旧版把「有没有这个语种」定义成 `fs.existsSync(db 文件)`，于是有两种故障
//     完全看不见：① 数据目录整个指错（打包后 `import.meta.url` 变了，见 dict-core
//     的 dataDir 注释）—— 现象是语言列表**空着**，前端只显示一个空下拉，没有任何报错；
//     ② 文件在但打不开（传了一半 / 权限 / schema 不对）—— 现象是第一个真实请求 500。
//  ⇒ 启动时**真开一次库**，把结果记下来当作后续请求的准入判据。
// ════════════════════════════════════════════════════════════════════════
let health: LanguageProbe[] = probeLanguages();
const okCodes = () => new Set(health.filter((l) => l.ok).map((l) => l.code));

function reportStartup() {
  console.log(`[synapse-dict] 数据目录：${dataDir()}${process.env.SYNAPSE_DATA_DIR ? '' : '（由源码位置推算，部署时请显式设 SYNAPSE_DATA_DIR）'}`);
  for (const l of health) {
    console.log(l.ok
      ? `  ✅ ${l.code} ${l.name.padEnd(6)} ${String(l.rows).padStart(9)} 条  ${l.path}`
      : `  ⛔ ${l.code} ${l.name.padEnd(6)} 不可用：${l.error}  ${l.path}`);
  }
}

reportStartup();

// 一个都开不起来 ⇒ 拒绝启动。
// 这里**必须是拒绝而不是降级**：一个语言都没有的词典服务，健康检查再漂亮也没有意义，
// 而它若能启动成功，进程管理器就会认为部署成功，故障要等用户来报。
if (health.every((l) => !l.ok)) {
  console.error(
    '\n[synapse-dict] 没有任何一个语种的词典库可用，拒绝启动。\n' +
    `  当前数据目录：${dataDir()}\n` +
    '  最常见的原因是数据目录不对 —— 用 SYNAPSE_DATA_DIR 显式指到放 db/ 的那一层，\n' +
    '  或用 DATABASE_PATH_ES / DATABASE_PATH_EN … 逐个指定。');
  process.exit(1);
}

const langs = health.filter((l) => l.ok).map(({ code, label, name, speak }) => ({ code, label, name, speak }));
const defaultLang = langs[0]?.code || 'en';

/**
 * 挑语言。`?lang=` 不合法或缺省一律回退到列表首位。
 * 🔴 与旧版的差别：旧版把「未知语种」和「已知但库坏了」都悄悄回退成英语 ——
 *    用户搜西语词、拿到英语库的结果，看不出发生了什么。现在**已知但不可用**明确回 503。
 */
function pickLang(req: Request): string {
  const q = String(req.query.lang || '').trim();
  if (!q) return defaultLang;
  const known = health.find((l) => l.code === q);
  if (!known) return defaultLang;                 // 压根不是我们支持的语种 → 回退
  if (!known.ok) throw unavailable(`${known.name}词典当前不可用`, { lang: q, reason: known.error });
  return q;
}

/**
 * 运行期掉线的补救：任何一次非 ApiError 的失败之后，重新探一次该语种。
 * 探到坏了，后续请求就直接 503 快失败，而不是每个请求都去撞一次同步 SQLite。
 */
function reprobe(code: string) {
  const fresh = probeLanguages().find((l) => l.code === code);
  if (!fresh) return;
  const i = health.findIndex((l) => l.code === code);
  if (i >= 0 && health[i].ok !== fresh.ok) {
    console.warn(`[synapse-dict] ${code} 可用性变化：${health[i].ok} → ${fresh.ok}（${fresh.error ?? 'ok'}）`);
  }
  if (i >= 0) health[i] = fresh;
}

/** 包一层：把同步路由里抛出的东西交给统一错误出口，顺带做掉线重探。 */
const route = (fn: (req: Request, res: Response) => void): RequestHandler =>
  (req, res, next) => {
    try {
      fn(req, res);
    } catch (e) {
      if (!(e instanceof ApiError)) {
        const lang = String(req.query.lang || defaultLang);
        if (okCodes().has(lang)) reprobe(lang);
      }
      next(e);
    }
  };

app.use(cors({ origin: corsOrigin }));
// 本服务没有任何写接口，请求体一律不需要 —— 收窄到 4 KB，别给一个只读 API 留下大 body 通道。
app.use(express.json({ limit: '4kb' }));

// 访问日志。默认只记非 2xx 与慢请求，正常流量不刷屏；LOG_ALL=1 记全部。
const logAll = process.env.LOG_ALL === '1';
app.use((req, res, next) => {
  const t0 = process.hrtime.bigint();
  res.on('finish', () => {
    const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    if (logAll || res.statusCode >= 400 || ms >= SLOW_MS) {
      const mark = ms >= SLOW_MS ? ' ⏱' : '';
      console.log(`${res.statusCode} ${ms.toFixed(1)}ms${mark} ${req.method} ${req.originalUrl}`);
    }
  });
  next();
});

// Honor X-Forwarded-For when running behind a reverse proxy so per-IP limits
// key on the real client, not the proxy. Enable via TRUST_PROXY (e.g. "1").
if (process.env.TRUST_PROXY) {
  app.set('trust proxy', process.env.TRUST_PROXY);
}

// ════════════════════════════════════════════════════════════════════════
//  路由
//  版本前缀 `/api/v1`。旧的无版本 `/api/*` 保留为别名（前端还在用），
//  但**新客户端一律用 v1** —— 无版本路径此后只做兼容，不再增加接口。
// ════════════════════════════════════════════════════════════════════════
const api = express.Router();

/**
 * 健康检查。不限流（监控要在过载时仍然能读到）。
 * 🔴 旧版是 `res.json({ ok: true })` —— 一个**永远为真**的健康检查，
 *    库掉了它照样绿。现在它反映真实探活结果：全坏 503、部分坏 degraded。
 */
api.get('/health', (_req, res) => {
  const good = health.filter((l) => l.ok);
  const status = good.length === 0 ? 'down' : good.length === health.filter((l) => l.error !== 'DB 文件不存在').length ? 'ok' : 'degraded';
  res.status(good.length === 0 ? 503 : 200).json({
    status,
    languages: health.map((l) => ({ code: l.code, ok: l.ok, rows: l.rows, error: l.error })),
    uptimeSec: Math.round(process.uptime()),
  });
});

api.get('/langs', (_req, res) => {
  res.json({ languages: langs, default: defaultLang });
});

// 合成发音的音频文件（`es/pipeline/gen_tts.py` 产物）。挂在 /api/… 之下是为了
// 复用前端已有的 vite 代理（只代理了 /api），不必再开一条转发规则。
// 放在限流**之前**：一个词条页会连着取音频，按 API 调用限流会把播放掐掉；
// 而这里是纯静态小文件（约 10 KB），交给 express.static 走 sendfile，不碰 SQLite。
// 文件名是 sha1，天然不可枚举；目录不存在的语种直接跳过。
for (const l of langs) {
  const dir = ttsDirFor(l.code);
  if (!fs.existsSync(dir)) {
    console.log(`  ♪ ${l.code} 无合成音目录，前端将回落到浏览器 TTS（${dir}）`);
    continue;
  }
  api.use(`/audio/${l.code}`, express.static(dir, {
    immutable: true,            // 内容由 sha1 定址，永不变
    maxAge: '365d',
    fallthrough: false,         // 没有就 404，别掉到后面的路由里
  }));
}

// Throttle the query endpoints — these hit the synchronous, shared SQLite that
// synapse-web also reads, so an unbounded flood here can starve web too.
api.use(createRateLimiter(rateLimitOptionsFromEnv()));

api.get('/stats', route((req, res) => {
  const lang = pickLang(req);
  res.json({ lang, ...getService(lang).getStats() });
}));

api.get('/search', route((req, res) => {
  const lang = pickLang(req);
  const { keyword, unmatchable } = parseQuery(req.query.q);
  const limit = parseLimit(req.query.limit, 20, 50);

  // 空串、或含 LIKE 通配符（库里没有任何词头含 % _ \，见 validate.ts）⇒ 字面上不可能有结果。
  if (!keyword || unmatchable) {
    res.json({ lang, query: keyword, items: [] });
    return;
  }
  res.json({ lang, query: keyword, items: getService(lang).search(keyword, limit) });
}));

api.get('/entries/:word', route((req, res) => {
  const lang = pickLang(req);
  const word = parseWord(req.params.word);
  const entry = getService(lang).getEntry(word);
  if (!entry) throw notFound('word_not_found', `没有收录「${word}」`, { lang, word });
  res.json(entry);
}));

app.use('/api/v1', api);
app.use('/api', api);          // 兼容旧客户端；新接口只加在 v1 上

app.use(notFoundHandler);
app.use(errorHandler(exposeErrors));

// ════════════════════════════════════════════════════════════════════════
const server = app.listen(port, () => {
  console.log(`\n[synapse-dict] API ready at http://localhost:${port}  (canonical: /api/v1)`);
  console.log(`  可用语种：${langs.map((l) => `${l.code}(${l.name})`).join('、') || '(无)'}`);
});

/**
 * 优雅关闭。
 * ⚠️ 一定要有强杀兜底：`server.close()` 只是停止接受新连接，
 *    keep-alive 上还挂着的空闲连接会让回调迟迟不触发，进程卡在「正在关闭」，
 *    进程管理器等到超时再 SIGKILL —— 中间那段时间流量已经切走但旧实例还占着端口。
 */
let closing = false;
function shutdown(sig: string) {
  if (closing) return;
  closing = true;
  console.log(`\n[synapse-dict] 收到 ${sig}，开始关闭…`);
  const force = setTimeout(() => {
    console.error('[synapse-dict] 关闭超时，强制退出');
    process.exit(1);
  }, Number(process.env.SHUTDOWN_TIMEOUT_MS || 10_000));
  force.unref();
  server.close(() => {
    closeAllServices();
    console.log('[synapse-dict] 已关闭');
    process.exit(0);
  });
  server.closeIdleConnections?.();
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

// 未捕获异常不静默 —— 记下来再退出，交给进程管理器重启。
// （不 try 着继续跑：node:sqlite 是同步的，抛到这里通常意味着状态已经不可信。）
process.on('uncaughtException', (e) => {
  console.error('[synapse-dict] uncaughtException', e);
  shutdown('uncaughtException');
});
process.on('unhandledRejection', (e) => {
  console.error('[synapse-dict] unhandledRejection', e);
});
