import { getService } from '@synapse-dict/dict-core';
const svc = getService('de') as any;
for (const w of ['stehen','Kastanie','wegen']) {
  const e = svc.getEntry(w);
  console.log('══', w);
  for (const s of e.senses.slice(0, 6)) {
    if (!s.de) continue;
    console.log(`  「${(s.zh||'-').slice(0,20)}」`);
    for (const line of s.de.split('\n')) console.log('     ·', line.slice(0, 62));
  }
}
