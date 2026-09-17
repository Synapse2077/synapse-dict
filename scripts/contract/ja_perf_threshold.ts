import { DatabaseSync } from 'node:sqlite';
const db = new DatabaseSync('/Users/fangyi/demo/synapse-dict/data/db/synapse-dict-ja.sqlite', { readOnly: true });
const SQL = `SELECT d.id FROM dict d WHERE d.word_norm >= ? AND d.word_norm < ?
  ORDER BY d.is_lemma DESC, d.freq_zipf IS NULL, d.freq_zipf DESC, length(d.word), d.word LIMIT 30`;
const st = db.prepare(SQL);
// 每个候选数量级抽几个前缀，量真实耗时
const buckets = [[100, 300], [300, 700], [700, 1500], [1500, 4000], [4000, 12000], [12000, 999999]];
console.log('候选数区间'.padEnd(16) + '样本'.padStart(4) + '  中位 ms   最慢 ms');
for (const [lo, hi] of buckets) {
  const ks = (db.prepare(
    `WITH p AS (SELECT substr(word_norm,1,1) k, COUNT(*) n FROM dict GROUP BY 1
                UNION ALL SELECT substr(word_norm,1,2), COUNT(*) FROM dict WHERE length(word_norm)>=2 GROUP BY 1)
     SELECT k FROM p WHERE n >= ? AND n < ? ORDER BY RANDOM() LIMIT 8`).all(lo, hi) as Array<{k:string}>).map((r)=>r.k);
  if (!ks.length) continue;
  const ts: number[] = [];
  for (const k of ks) for (let i = 0; i < 8; i++) {
    const t0 = performance.now(); st.all(k, `${k}￿`); ts.push(performance.now() - t0);
  }
  ts.sort((a,b)=>a-b);
  console.log(`${String(lo)+'–'+String(hi === 999999 ? '∞' : hi)}`.padEnd(16)
    + String(ks.length).padStart(4)
    + `  ${ts[Math.floor(ts.length/2)].toFixed(2).padStart(7)}  ${ts[ts.length-1].toFixed(2).padStart(7)}`);
}
db.close();
