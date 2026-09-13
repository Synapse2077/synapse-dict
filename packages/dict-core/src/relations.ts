/**
 * 词条级关系去重：**已经在某条义项下印过的，词条级不许再印一遍**。2026-09-12。
 *
 * ═══ 为什么需要 ═══
 * 六门的做法都是「词条级只取 `sense_id IS NULL` 的行」。那个过滤**不够** ——
 * 库里同一条 (词, 类型, 目标) 可以**有两行**：一行带义项归属、一行不带。
 * 两条查询各取一行，页面上就印两遍。实测（排除 alt_of、只算可见行）：
 *
 *     de 24,149 组 ／ it 9,173 ／ fr 7,153 ／ en 4,050 ／ es 44 ／ pt 0
 *
 * 已验证不是理论问题：`Haus` 页上「Hausaltar」出现 2 次、
 * `-ette` 页上「-cule」出现 2 次（义项内 1 次 ＋ 词条级 1 次）。
 * ⚠️ **pt 恰好是 0，所以它那套写法一直看着是对的** —— 又一个
 * 「一门之内的闸看不见门与门之间的问题」：pt 的契约闸里有
 * 「同一条关系在词条级和义项级各印了一遍」这条断言，而 de/en 没有。
 *
 * ═══ 🔴 为什么在 JS 里去重，不在 SQL 里 ═══
 * SQL 写法要么是相关子查询 `NOT EXISTS (…同 word_id/kind/target 且 sense_id 非空…)`，
 * 要么是自连接 —— 而 `getEntry` 是**每开一个词条页就跑一次**的路径，
 * 相关子查询在这里就是嵌套扫（`[[query-perf-collation-traps]]`；
 * `de/fixes/relink_examples_to_senses.py` 那次的负控正是因为 `NOT EXISTS` 干跑超时）。
 * 两批行本来都已经在内存里，用一个 Set 过一遍是 O(n)，没有查询代价。
 *
 * ⚠️ 判据是 (类型, 目标) 而不是只看目标：`run → antonym: rise` 与
 *    `run → hypernym: rise` 是两句不同的话，去重不能把它们并掉。
 */
export function dropDuplicatedAtSenseLevel<T extends { kind: string; target: string }>(
  entryLevel: T[],
  senseLevel: ReadonlyArray<{ kind: string; target: string }>,
): T[] {
  if (senseLevel.length === 0) return entryLevel;
  const shown = new Set(senseLevel.map((r) => `${r.kind} ${r.target}`));
  return entryLevel.filter((r) => !shown.has(`${r.kind} ${r.target}`));
}
