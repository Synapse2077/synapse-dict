import { LANGUAGES, getService, probeLanguages } from '../../packages/dict-core/src/index.js';
console.log('注册:', LANGUAGES.map((l) => l.code).join(','));
for (const x of probeLanguages()) console.log('  探活', JSON.stringify(x));
const svc = getService('ja') as any;
console.log('ja 服务:', svc.constructor.name, '| lang =', svc.lang);
console.log('查 痛い:', svc.getEntry('痛い')?.senses.length, '条义项');
