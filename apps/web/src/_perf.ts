import { getService } from '@synapse-dict/dict-core';
const svc = getService('de') as any;
const t = (f: () => void, n = 20) => { const a = Date.now(); for (let i=0;i<n;i++) f(); return (Date.now()-a)/n; };
console.log('── 搜索下拉（每次取 20 条）──');
for (const q of ['a','ab','abs','Haus','Ge','sch','ü','Bundes']) {
  console.log(`  ${JSON.stringify(q).padEnd(10)} ${t(() => svc.search(q, 20)).toFixed(1).padStart(7)} ms  (${svc.search(q,20).length} 条)`);
}
console.log('── 词条页 ──');
for (const w of ['Haus','gehen','Bundesverfassungsgericht','die','Reifen']) {
  console.log(`  ${w.padEnd(26)} ${t(() => svc.getEntry(w), 10).toFixed(1).padStart(6)} ms`);
}
