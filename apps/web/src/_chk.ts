import { getService } from '@synapse-dict/dict-core';
const svc = getService('de') as any;
for (const w of ['Reifen','Lehrer','Aasen']) {
  const e = svc.getEntry(w);
  console.log('══', w);
  console.log('  变形 inflections:', JSON.stringify(e.inflections));
  console.log('  构词 derivations:', JSON.stringify(e.derivations));
}
