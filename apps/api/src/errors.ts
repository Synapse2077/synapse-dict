import type { NextFunction, Request, Response } from 'express';

/**
 * 统一错误出口。2026-08-11。
 *
 * ═══ 在改之前，线上真实行为是这样的 ═══
 * `GET /api/search?q=casa&limit=abc` → HTTP **500**，响应体是 Express 默认的 HTML 错误页，
 * 里面带着**完整调用栈和服务器绝对路径**：
 *     Error: datatype mismatch
 *         at SpanishDictService.search (/Users/fangyi/demo/synapse-dict/packages/dict-core/src/spanish.ts:636:35)
 * 三个问题叠在一起：
 *   ① 一个畸形的 query string 就能触发 500（`Number('abc')` = NaN，
 *      `Math.min(Math.max(NaN,1),50)` 还是 NaN，塞进 SQLite 的 LIMIT 就抛 datatype mismatch）；
 *   ② 500 泄露了部署目录结构和源码路径；
 *   ③ 返回的是 HTML —— 一个只会 `res.json()` 的客户端在这里会二次崩溃，
 *      拿到的报错是「Unexpected token '<'」，与真正的原因（limit 不合法）毫无关系。
 *
 * ⇒ 规矩定死：**API 之下只有 JSON**，客户端错误是 4xx、服务端错误是 5xx，
 *   栈只进日志不进响应。
 */

/** 已知的、可以明确告诉客户端「你哪里错了」的错误。 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export const badRequest = (code: string, msg: string, detail?: Record<string, unknown>) =>
  new ApiError(400, code, msg, detail);

export const notFound = (code: string, msg: string, detail?: Record<string, unknown>) =>
  new ApiError(404, code, msg, detail);

/** 数据层暂时不可用（库掉线 / 损坏）。是 503 不是 500：它是**可恢复**的，客户端该重试。 */
export const unavailable = (msg: string, detail?: Record<string, unknown>) =>
  new ApiError(503, 'language_unavailable', msg, detail);

/**
 * 未匹配到任何路由 —— 必须自己接管。
 * 不接管的话 Express 会回一个 HTML 404（连 `X-Powered-By: Express` 一起），
 * 与本 API 其余部分的契约不一致。
 */
export function notFoundHandler(req: Request, _res: Response, next: NextFunction) {
  next(new ApiError(404, 'no_such_route', `没有这个接口：${req.method} ${req.path}`));
}

/**
 * 兜底错误处理。**必须是最后一个 `app.use`**，且**必须带满四个形参** ——
 * Express 靠 `fn.length === 4` 认错误中间件，少写一个 `next` 它就变成普通中间件，
 * 静默失效（这个坑不报错，只是错误又回到默认 HTML 页）。
 */
export function errorHandler(exposeStack: boolean) {
  return function onError(err: unknown, req: Request, res: Response, _next: NextFunction) {
    if (res.headersSent) return;              // 静态文件流已经开始写，只能断开

    if (err instanceof ApiError) {
      // 4xx 是客户端的问题，不值得刷日志；5xx 一律记。
      if (err.status >= 500) console.error(`[${err.code}] ${req.method} ${req.originalUrl}`, err);
      res.status(err.status).json({
        error: err.code, message: err.message, ...(err.detail ? { detail: err.detail } : {}),
      });
      return;
    }

    const e = err as Error;
    console.error(`[unhandled] ${req.method} ${req.originalUrl}`, e?.stack || e);
    res.status(500).json({
      error: 'internal',
      message: '服务内部错误',
      // 只有显式打开 EXPOSE_ERRORS 才回栈（本地排错用）。生产默认关闭。
      ...(exposeStack ? { stack: String(e?.stack || e) } : {}),
    });
  };
}
