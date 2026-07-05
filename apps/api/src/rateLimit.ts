import type { NextFunction, Request, Response } from 'express';

/**
 * Lightweight, dependency-free rate limiter.
 *
 * Why this exists: the dictionary queries run on node:sqlite `DatabaseSync`,
 * which is *synchronous* — every request blocks the event loop while it hits
 * the shared `data/synapse-dict.sqlite`. That same file is read directly by the
 * sibling synapse-web service, so a flood here contends for the host's CPU /
 * disk / page cache and can drag web down with it. These limits cap the blast
 * radius before that happens.
 *
 * Two independent gates, both fixed-window counters:
 *  - per-IP:  stops a single client from hogging the DB.
 *  - global:  backstop for a distributed flood ("被挤爆" from many IPs) so the
 *             shared sqlite is never hammered beyond a known ceiling.
 */

type Bucket = { count: number; resetAt: number };

export interface RateLimitOptions {
  /** Window length in milliseconds. */
  windowMs: number;
  /** Max requests per window from a single IP. */
  maxPerIp: number;
  /** Max requests per window across all clients combined. */
  maxGlobal: number;
}

function numFromEnv(name: string, fallback: number): number {
  const raw = Number(process.env[name]);
  return Number.isFinite(raw) && raw > 0 ? raw : fallback;
}

export function rateLimitOptionsFromEnv(): RateLimitOptions {
  return {
    windowMs: numFromEnv('RATE_LIMIT_WINDOW_MS', 60_000),
    maxPerIp: numFromEnv('RATE_LIMIT_MAX_PER_IP', 120),
    maxGlobal: numFromEnv('RATE_LIMIT_MAX_GLOBAL', 1_200),
  };
}

export function createRateLimiter(opts: RateLimitOptions) {
  const perIp = new Map<string, Bucket>();
  let global: Bucket = { count: 0, resetAt: 0 };

  // Drop stale per-IP buckets so the Map can't grow without bound under churn.
  const sweep = setInterval(() => {
    const now = Date.now();
    for (const [ip, bucket] of perIp) {
      if (bucket.resetAt <= now) perIp.delete(ip);
    }
  }, opts.windowMs);
  sweep.unref?.();

  function hit(bucket: Bucket, max: number, now: number): { bucket: Bucket; limited: boolean } {
    if (bucket.resetAt <= now) {
      bucket = { count: 0, resetAt: now + opts.windowMs };
    }
    bucket.count += 1;
    return { bucket, limited: bucket.count > max };
  }

  return function rateLimit(req: Request, res: Response, next: NextFunction) {
    const now = Date.now();

    // Global gate first — a distributed flood shouldn't need a single hot IP.
    const g = hit(global, opts.maxGlobal, now);
    global = g.bucket;
    if (g.limited) {
      res.setHeader('Retry-After', String(Math.ceil((global.resetAt - now) / 1000)));
      res.status(503).json({ error: 'Service busy, please retry shortly' });
      return;
    }

    const ip = req.ip || req.socket.remoteAddress || 'unknown';
    const existing = perIp.get(ip) ?? { count: 0, resetAt: 0 };
    const p = hit(existing, opts.maxPerIp, now);
    perIp.set(ip, p.bucket);

    res.setHeader('X-RateLimit-Limit', String(opts.maxPerIp));
    res.setHeader('X-RateLimit-Remaining', String(Math.max(0, opts.maxPerIp - p.bucket.count)));
    res.setHeader('X-RateLimit-Reset', String(Math.ceil(p.bucket.resetAt / 1000)));

    if (p.limited) {
      res.setHeader('Retry-After', String(Math.ceil((p.bucket.resetAt - now) / 1000)));
      res.status(429).json({ error: 'Too many requests' });
      return;
    }

    next();
  };
}
