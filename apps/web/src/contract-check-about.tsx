/**
 * B33「关于」页契约闸。2026-11-23。
 *
 * ═══ 为什么需要它 ═══
 * 「关于」页是 **CC BY-SA 4.0 的署名交付物**：整个词典的数据都受该许可约束
 * （不只某一列，见 `docs/BACKLOG.md` B33）。对外公布时，署名方式走「链接到稳定的
 * 在线副本」—— 也就是本页列出的 11 个语言版 Wiktionary 主页。
 * 这一页的内容如果被删掉一行、链接被改坏，**没有任何东西会响** —— 而它恰是
 * 许可义务本身（`[[lesson-must-be-come-mechanism]]` 的形状：决定没有替它站岗的东西）。
 *
 * ═══ 判据（读者口径）═══
 * 真渲染 `AboutPanel`（与线上同一个组件、同一条渲染路径），断言：
 *   ① 11 个语言版 Wiktionary 主页链接一个不少（en/de/fr/it/es/pt/ja/ko/vi/ru/zh）
 *   ② CC BY-SA 4.0 许可链接
 *   ③ 署名：Wikimedia 贡献者、kaikki.org、ECDICT
 *   ④ 加工方式说清：清洗／重组／机器翻译
 *   ⑤ 不许出现「版权所有」这类含糊话（许可要求的是署名＋相同方式共享）
 *
 * 用法（仓库根）：
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-about.tsx
 *     ... --selftest   # 判据自检：拿一份缺链接的 HTML，必须报红
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AboutPanel } from './App';

const EDITIONS = ['en', 'de', 'fr', 'it', 'es', 'pt', 'ja', 'ko', 'vi', 'ru', 'zh'];

function checks(html: string): Array<[string, boolean]> {
  const text = html.replace(/<[^>]*>/g, ' ');
  return [
    ['11 个语言版 Wiktionary 主页链接',
      EDITIONS.every((l) => html.includes(`https://${l}.wiktionary.org/`))],
    ['CC BY-SA 4.0 许可链接',
      html.includes('creativecommons.org/licenses/by-sa/4.0/')],
    ['kaikki.org 署名', text.includes('kaikki.org')],
    ['ECDICT 署名', text.includes('ECDICT')],
    ['Wikimedia 贡献者署名', text.includes('Wikimedia')],
    ['机器翻译说明', text.includes('机器翻译')],
    ['清洗／重组说明', text.includes('清洗') && text.includes('重新组织')],
    ['不出现「版权所有」这类含糊话', !text.includes('版权所有')],
  ];
}

function run(html: string, label: string): number {
  const bad = checks(html).filter(([, ok]) => !ok);
  for (const [name, ok] of checks(html)) console.log(`   ${ok ? '✅' : '🔴'} ${name}`);
  if (bad.length) console.log(`\n🔴 ${label}：${bad.length} 处不符（${bad.map(([n]) => n).join('、')}）`);
  return bad.length;
}

if (process.argv.includes('--selftest')) {
  // 判据自检：缺一个语言版链接 + 缺许可链接 ⇒ 必须报出 2 条。
  const broken = '<p>词典数据按 <a href="https://example.org/">某许可</a> 提供。kaikki.org ECDICT Wikimedia</p>';
  const n = run(broken, '自检（残缺 HTML）');
  const ok = n >= 2;
  console.log(ok ? '\n✅ 自检通过：残缺内容会被报出' : '\n🔴 自检失败：判据没逮到残缺内容');
  process.exit(ok ? 0 : 1);
}

const html = renderToStaticMarkup(createElement(AboutPanel, { onClose: () => {} }));
console.log('■ 「关于」页契约闸（B33：CC BY-SA 4.0 署名义务）');
const bad = run(html, '关于页');
console.log(bad ? `\n🔴 共 ${bad} 处不符` : '\n✅ 全部通过');
process.exit(bad ? 1 : 0);
