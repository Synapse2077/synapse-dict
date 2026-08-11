import { badRequest } from './errors';

/**
 * 入参校验。2026-08-11。
 *
 * 原则：**在进 SQLite 之前把不合法的挡掉**，而不是让驱动抛异常再兜。
 * 理由不只是好看 —— `node:sqlite` 的 `DatabaseSync` 是**同步**的，
 * 每个请求都在事件循环上跑；靠抛异常兜底意味着畸形请求也要走完一次 prepare/bind，
 * 而这正是攻击者最愿意重复发的那种请求。
 */

/** 一个词形能有多长。库里最长的词条是 46 个字符，给到 128 已经很宽。 */
export const MAX_WORD_LEN = 128;
/** 检索串上限。超过这个长度的前缀查询不可能有结果，早挡早省。 */
export const MAX_QUERY_LEN = 128;

/**
 * 🔴 LIKE 通配符必须在这里挡掉，**不能靠 SQL 的 ESCAPE 子句**。
 *
 * 检索走的是 `word LIKE ? COLLATE NOCASE OR word_norm LIKE ? COLLATE NOCASE`。
 * 实测（EXPLAIN QUERY PLAN，2026-08-11）：
 *     不带 ESCAPE → MULTI-INDEX OR，两侧都是 SEARCH … USING INDEX
 *     带 ESCAPE   → **SCAN dict**，114 万行全表扫
 * SQLite 的 LIKE 优化在出现 ESCAPE 子句时直接放弃。所以「正确转义」这条路
 * 会把刚修好的检索性能（0.01 s）打回全表扫。
 *
 * 换个判据：库里**一个词头都不含** `%` `_` `\`（已核，三项均为 0）。
 * ⇒ 含这些字符的检索串在字面意义上不可能有结果，直接回空数组既正确又免了一次查询。
 * 这同时堵掉一条真实的放大通道：`q=%` 会让 LIKE 以通配符开头 ⇒ 全表扫 ⇒ 单次 0.5 s，
 * 限流放行的 120 次/分钟足够一个 IP 把一个核占满。挡掉之后是 0 s。
 */
const WILDCARD = /[%_\\]/;

export function parseQuery(raw: unknown): { keyword: string; unmatchable: boolean } {
  const s = String(raw ?? '').trim();
  if (s.length > MAX_QUERY_LEN) {
    throw badRequest('query_too_long', `检索串最长 ${MAX_QUERY_LEN} 个字符`, { length: s.length });
  }
  return { keyword: s, unmatchable: WILDCARD.test(s) };
}

export function parseWord(raw: unknown): string {
  const s = String(raw ?? '').trim();
  if (!s) throw badRequest('word_required', '词形不能为空');
  if (s.length > MAX_WORD_LEN) {
    throw badRequest('word_too_long', `词形最长 ${MAX_WORD_LEN} 个字符`, { length: s.length });
  }
  return s;
}

/**
 * 🔴 这是原来 500 的直接原因。旧写法：
 *     const limit = Math.min(Math.max(Number(req.query.limit || 20), 1), 50);
 * `Number('abc')` = NaN，而 **`Math.max(NaN, 1)` 和 `Math.min(NaN, 50)` 都是 NaN**
 * （NaN 参与比较一律 false，两个函数都直接把它传出来）—— 钳位看着做了，实际什么都没钳。
 * NaN 一路传到 `.all(..., NaN)`，node:sqlite 绑参时抛 `datatype mismatch`。
 * ⇒ 钳位之前必须先**判定它是不是一个有限数**，这一步不能省。
 */
export function parseLimit(raw: unknown, def: number, max: number): number {
  if (raw === undefined || raw === null || raw === '') return def;
  const n = Number(raw);
  if (!Number.isFinite(n)) {
    throw badRequest('limit_invalid', 'limit 必须是数字', { got: String(raw) });
  }
  return Math.min(Math.max(Math.trunc(n), 1), max);
}
