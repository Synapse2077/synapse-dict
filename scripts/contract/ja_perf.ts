import { getService } from '../../packages/dict-core/src/index.js';
const svc = getService('ja') as any;
const probes = ['あ', 'い', 'か', 'し', 'に', 'にほ', '日', '日本', '一', 'アジ', 'ア', 'こ', 'こん', 'た'];
// 预热（首次要建页缓存）
for (const p of probes) svc.search(p, 30);
console.log('查询'.padEnd(8) + '条数'.padStart(6) + '  中位 ms   p90 ms   最慢 ms');
let worst = 0;
for (const p of probes) {
  const ts: number[] = [];
  let n = 0;
  for (let i = 0; i < 25; i++) {
    const t0 = performance.now();
    n = svc.search(p, 30).length;
    ts.push(performance.now() - t0);
  }
  ts.sort((a, b) => a - b);
  const med = ts[Math.floor(ts.length / 2)];
  const p90 = ts[Math.floor(ts.length * 0.9)];
  worst = Math.max(worst, ts[ts.length - 1]);
  console.log(`${p.padEnd(8)}${String(n).padStart(6)}  ${med.toFixed(2).padStart(7)}  ${p90.toFixed(2).padStart(7)}  ${ts[ts.length - 1].toFixed(2).padStart(7)}`);
}
console.log(`\n最慢一次 ${worst.toFixed(1)} ms`);
// 词条页
for (const w of ['痛い', '日本語', '青', '表現']) {
  const ts: number[] = [];
  for (let i = 0; i < 15; i++) { const t0 = performance.now(); svc.getEntry(w); ts.push(performance.now() - t0); }
  ts.sort((a, b) => a - b);
  console.log(`词条 ${w.padEnd(5)} 中位 ${ts[Math.floor(ts.length / 2)].toFixed(2)} ms  最慢 ${ts[ts.length - 1].toFixed(2)} ms`);
}
