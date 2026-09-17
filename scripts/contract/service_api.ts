/** 闸：**每门注册的语言，服务层都得暴露 API 层真正调用的那几个方法。** 2026-09-16。
 *
 * 🔴 起因：`JapaneseDictService` 第一版把方法写成 `stats()` / `lookup()`，
 *    而 `apps/api/src/index.ts` 调的是 `getStats()` / `getEntry()` / `search()`。
 *    **TypeScript 全绿** —— `getService()` 返回联合类型，API 层把它当 `any` 用，
 *    于是这个不匹配一路躺到运行时才变成 500。
 *
 * ⚠️ 这是 `[[correct-steps-can-compose-a-hole]]` 的标准形状：
 *    服务层写对了、API 层写对了、类型也对，**跨步的那个约定没人负责**。
 *    ⇒ 闸要有一条是**读者口径**：不是「类型对不对」，是「API 真的调得动吗」。
 *
 * 🔴 判据从 **API 源码里读**，不在这儿手抄一份方法名 ——
 *    手抄的那份会和 API 漂开，然后闸报自己的 bug。
 *
 * 跑：npx tsx scripts/contract/service_api.ts
 */
import { readFileSync } from 'node:fs';
import { LANGUAGES, getService } from '../../packages/dict-core/src/index.js';

const API = new URL('../../apps/api/src/index.ts', import.meta.url).pathname;
const src = readFileSync(API, 'utf8');

// `getService(lang).xxx(` / `getService(lang) as {...}` 里出现的方法名
const called = new Set<string>();
for (const m of src.matchAll(/getService\([^)]*\)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(/g)) {
  called.add(m[1]);
}
// `const svc = getService(lang) as {...}; svc.foo(` 这种两步写法。
// 🔴 只取**顶层属性名**：`{ getCollocation?: (t: string) => unknown }` 里的 `t`
//    是参数名不是方法名。第一版没锚定位置，把 `t` 当成了必须实现的方法，
//    七门全报红 —— **判据比它要描述的东西宽**，闸第一次跑就在报自己的 bug。
for (const m of src.matchAll(/getService\([^)]*\)\s+as\s*\{([^}]*)\}/g)) {
  for (const f of m[1].matchAll(/(?:^|[{;,])\s*([A-Za-z_][A-Za-z0-9_]*)\??\s*:/g)) {
    called.add(f[1]);
  }
}
called.add('close');   // `closeAllServices` 走的

console.log('■ API 层实际调用的方法：', [...called].sort().join(', '));

let red = 0;
for (const { code } of LANGUAGES) {
  let svc: Record<string, unknown>;
  try {
    svc = getService(code) as unknown as Record<string, unknown>;
  } catch (e) {
    console.log(`   🔴 ${code}  服务建不起来：${(e as Error).message.slice(0, 70)}`);
    red += 1;
    continue;
  }
  // ⚠️ `getCollocation` 是**可选**的：API 里就是 `{ getCollocation?: … }`，
  //    没有搭配层的语言不该因此红。判据跟着 API 的可选性走。
  const optional = new Set(['getCollocation']);
  const miss = [...called].filter((m) => typeof svc[m] !== 'function' && !optional.has(m));
  const opt = [...called].filter((m) => typeof svc[m] !== 'function' && optional.has(m));
  if (miss.length) red += 1;
  console.log(`   ${miss.length ? '🔴' : '✅'} ${code.padEnd(3)}`
    + `${svc.constructor.name.padEnd(24)}`
    + (miss.length ? `缺 ${miss.join(', ')}` : '齐')
    + (opt.length ? `  （可选未实现：${opt.join(', ')}）` : ''));
}
console.log(red ? `\n🔴 ${red} 门服务接不上 API` : '\n✅ 每门服务都接得上 API');
process.exit(red ? 1 : 0);
