import { getService } from '../../packages/dict-core/src/index.js';
const svc = getService('ja') as any;
let tot = 0, empty = 0;
for (const q of ['あ','い','か','し','に','日','一','ア','こ','た','ま','は','く','と','さ']) {
  const rs = svc.search(q, 30); tot += rs.length;
  const e = rs.filter((r: any) => !r.brief);
  empty += e.length;
  if (e.length) console.log(`   ${q}: 空 ${e.length}  ${e.slice(0,3).map((x:any)=>x.word).join('、')}`);
}
console.log(`\n合计 ${tot} 条结果，空摘要 ${empty} 条 = ${(100*empty/tot).toFixed(1)}%`);
