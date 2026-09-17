import { getService } from '../../packages/dict-core/src/index.js';
const svc = getService('ja') as any;
for (const q of ['あ', 'あい', 'いぬ', 'あいす']) {
  console.log(`── 搜「${q}」──`);
  for (const r of svc.search(q, 6)) {
    console.log(`   ${r.word.padEnd(10)} ${String(r.kana ?? '').padEnd(10)} ${r.brief ?? '🔴 空'}`);
  }
}
// 空摘要还剩多少
const n = svc.search('あ', 30).filter((r: any) => !r.brief).length;
console.log(`\n「あ」前 30 条里空摘要 ${n} 条`);
