// 搜索路径：**结果一致性 + 延迟**。2026-08-20。
//
// `search()` 每敲一个字符跑一次。1 字符前缀原本最慢 354ms（为取 20 条把 2–3 万条
// 候选整个排一遍）。`pipeline/build_search_prefix.py` 把 1–2 字符前缀预算好，
// 本探针盯两件事：
//   ① **预计算路径与实时路径的结果逐位相同** —— 快了但答案变了就是灾难
//   ② 延迟分位
//
// 用法（仓库根）：node --experimental-strip-types es/probes/search_perf.ts
import { DatabaseSync } from 'node:sqlite';
import { SpanishDictService } from '../../packages/dict-core/src/spanish.ts';

const ROOT = new URL('../../', import.meta.url).pathname;
const DB = `${ROOT}data/db/synapse-dict-es.sqlite`;
const d = new SpanishDictService(DB, `${ROOT}data/tts/es`);
const raw = new DatabaseSync(DB, { readOnly: true });

// 实时查询（与 spanish.ts:prefixQuery 内层同一份 SQL）
const live = raw.prepare(`
  SELECT id FROM dict
  WHERE word LIKE ? COLLATE NOCASE OR word_norm LIKE ? COLLATE NOCASE
  ORDER BY CASE WHEN lower(word)=lower(?) THEN 0 ELSE 1 END,
           is_lemma DESC, LENGTH(word) ASC, word ASC
  LIMIT ?`);

const prefixes = (raw.prepare(
  `SELECT DISTINCT prefix FROM search_prefix ORDER BY prefix`).all() as
  Array<{ prefix: string }>).map((r) => r.prefix);

let same = 0; let diff = 0; const bad: string[] = [];
for (const p of prefixes) {
  // ⚠️ `search()` 先 `trim()`。比之前必须**同样 trim**，否则比的是两个不同的查询 ——
  //    第一版没 trim，19 个带尾空格的键（`"1 "` 来自 `1 de enero` 这类多词条目）
  //    报成「缓存 20 vs 实时 9」的假不一致。
  const k = p.trim();
  if (!k) continue;
  const got = d.search(p, 20).map((x) => x.id);
  const want = (live.all(`${k}%`, `${k}%`, k, 20) as Array<{ id: number }>).map((r) => r.id);
  if (JSON.stringify(got) === JSON.stringify(want)) same++;
  else { diff++; if (bad.length < 3) bad.push(`${JSON.stringify(p)} 缓存 ${got.length} vs 实时 ${want.length}`); }
}
console.log(`① 结果一致性：${prefixes.length} 个前缀，逐位相同 ${same} / 🔴 不同 ${diff}`);
for (const b of bad) console.log('   🔴 ' + b);

const words = (raw.prepare(
  `SELECT word FROM dict ORDER BY COALESCE(freq_zipf,0) DESC LIMIT 400`).all() as
  Array<{ word: string }>).map((r) => r.word);
for (const L of [1, 2, 3, 4]) {
  const ps = [...new Set(words.filter((w) => w.length >= L).map((w) => w.slice(0, L)))].slice(0, 60);
  for (const p of ps.slice(0, 10)) d.search(p, 20);          // 预热
  const t: number[] = [];
  for (const p of ps) { const a = performance.now(); d.search(p, 20); t.push(performance.now() - a); }
  t.sort((a, b) => a - b);
  const q = (x: number) => t[Math.floor(t.length * x)].toFixed(1);
  console.log(`② ${L} 字符前缀（${ps.length} 个）：P50 ${q(0.5)}  P95 ${q(0.95)}  max ${t[t.length - 1].toFixed(0)}ms`);
  if (L >= 3 && t[t.length - 1] > 50) {
    // 最慢的那个是谁 —— 离群值要点名，别只报分位数
    let worst = ps[0]; let wt = -1;
    for (const p of ps) { const a = performance.now(); d.search(p, 20); const e = performance.now() - a; if (e > wt) { wt = e; worst = p; } }
    console.log(`     ⚠️ 最慢前缀 ${JSON.stringify(worst)}  ${wt.toFixed(0)}ms`);
  }
}
process.exit(diff ? 1 : 0);
