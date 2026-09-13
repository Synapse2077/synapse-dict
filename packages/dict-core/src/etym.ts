/**
 * 词源键：从 `sense_src.src_ref` 里拆出来。2026-09-12。
 *
 * ═══ 为什么单独一个文件 ═══
 * en 与 de 的 `sense` 表**没有 `entry_id`**（it/fr/pt 有 99.5–100%，es 有 54.7%），
 * 拿不到词源的唯一线索就是 `src_ref` 的形状。两门都要用同一条判据，
 * 而语种模块之间**互不引用**（`[[multilang-decoupling-essence]]`）——
 * 所以放这里：**它是个纯字符串函数，不含任何语种知识**。
 * ⚠️ 不要放进 `index.ts`：那里 `export * from './german.js'`，反过来 import 会成环。
 *
 * ═══ 🔴🔴 返回的是「来源:编号」，不是裸编号 ═══
 * `che`（it）同时有两个来源的义项：
 *     kk-en:che:pron:1:0#0    英文版 Etymology 1
 *     kk-it:che:adj:0:0#0     意语版 Etymology 0
 * **两套编号各自从头数，不是同一个命名空间。** 拿裸数字当分组键，
 * 「英文版的 1」与「意语版的 1」会被当成同一个词源合并 —— 那是把两个不同的词
 * 并成一个，比不分组更糟。
 * ⇒ 键**带上来源、且不透明**：调用方只许拿它做相等比较，不许解析、不许显示。
 *   页面上的「词源 ①②③」由展示层**按出场顺序重新编号**（见 App.tsx 的 etymLabel）。
 *
 * ═══ 判据按结构，不按来源名 ═══
 *     en-edition:gore:noun:1:0#0     带 `#`、`:` ≥ 4  ⇒ 倒数第二段是编号
 *     kk-en:A:noun:1:0#0             同上（de 的英文版那批）
 *     kk-de:'n Abend:intj:0#0        `:` = 3         ⇒ 德语版不带编号 ⇒ null
 *     kk-de-adj2:A#0                 `:` = 1         ⇒ null
 *     ecdict:942:0                   没有 `#`        ⇒ 老词典层，没有词源概念
 *
 * 🔴 **不写 `startsWith('en-edition')`**：来源名会随时间长出新层 ——
 *    de 那次桥只认 `src='de-edition'`，后来多出 `-adjudicated` / `-backfill`
 *    两层 8.4 万条，桥一条都不长还一声不吭（`[[criteria-narrower-than-you-think]]`）。
 * 🔴 **从右往左取**：词形本身可能带 `:`（`kk-de:'n Abend:intj:0#0` 的词形含空格），
 *    从左数会错位。
 */
export function etymKeyOfSrcRef(ref: string | null | undefined): string | null {
  if (!ref) return null;
  const hash = ref.indexOf('#');
  if (hash < 0) return null;               // 没有 `#` ⇒ 不是 kaikki 那一族
  const parts = ref.slice(0, hash).split(':');
  if (parts.length < 5) return null;       // 少于 5 段 ⇒ 这一族不带编号
  const n = parts[parts.length - 2];
  if (!/^\d+$/.test(n)) return null;
  return `${parts[0]}:${n}`;               // 来源 + 编号，**不透明**
}

/** it/fr/pt/es 走 `entry` 表：同样把来源拼进去，口径与上面那条一致。 */
export function etymKeyOfEntry(
  src: string | null | undefined, etymNo: string | null | undefined,
): string | null {
  if (etymNo === null || etymNo === undefined || etymNo === '') return null;
  return `${src ?? '?'}:${etymNo}`;
}
