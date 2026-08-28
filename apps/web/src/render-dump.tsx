/**
 * 把指定词条**按用户真正看到的样子**导出成文本，供人工点测与外部评审。2026-08-21。
 *
 * ═══ 为什么不直接导库 ═══
 * 用户 2026-08-21：「把点测的结果（也就是我们在前端页面展示给用户的结果）发给 pro、v4-pro」。
 * 「展示给用户的结果」这句是判据本身 —— 我们已经吃过三次亏，缺陷**只在渲染之后才存在**：
 * `TVTB` 那条的接口返回完全正确，错只在组件里一行 `entry.isLemma &&`，查库查接口都看不见。
 * ⇒ 评审材料必须来自 `renderToStaticMarkup`，与 `contract-check.tsx` 同一条渲染路径。
 *
 * ═══ 与 contract-check 的分工 ═══
 * `contract-check.tsx` 断言**已知**的缺陷形状（写死判据、可变异验证）；
 * 本脚本不做任何判断，只**如实导出**，用来发现判据还没覆盖到的形状。
 *
 * 用法（仓库根目录）：
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/render-dump.tsx --lang it dei dio una
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/render-dump.tsx --lang it --file words.txt --out x.md
 *
 * ⚠️ `--tsconfig` 不能省，理由同 contract-check.tsx 文件头。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { ItalianEntryView, SpanishEntryView, FrenchEntryView } from './App';
import { readFileSync, writeFileSync } from 'node:fs';

const argv = process.argv.slice(2);
// 🔴 布尔开关必须与带值选项分开登记：第一版把 `--html` 也当成带值的，
//    于是 `--html dei` 里的 `dei` 被当作它的值吃掉，词表变空、输出 1 字节。
const VALUED = new Set(['--lang', '--out', '--file']);
function opt(name: string): string | undefined {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : undefined;
}
const lang = opt('--lang') ?? 'it';
const outPath = opt('--out');
const fileArg = opt('--file');
const words = fileArg
  ? readFileSync(fileArg, 'utf8').split('\n').map((s) => s.trim()).filter((s) => s && !s.startsWith('#'))
  : argv.filter((a, i) => !a.startsWith('--') && !VALUED.has(argv[i - 1] ?? ''));

// 🔴 2026-08-26 加 fr（阶段 8）。导出器只支持 it/es 时，fr 的展示层缺陷
//    就只能靠我读服务端 JSON 猜 —— 而缺陷**只在渲染之后才存在**。
const View = lang === 'es' ? SpanishEntryView
  : lang === 'fr' ? FrenchEntryView : ItalianEntryView;
const locale = lang === 'es' ? 'es-MX' : lang === 'fr' ? 'fr-FR' : 'it-IT';
const svc = getService(lang) as unknown as { getEntry(w: string): unknown };

/**
 * 去标签取可见文字。
 * 🔴 块级元素必须换成换行**再**去标签 —— 否则整页文字挤成一坨，
 *    "两支中文并排像重复"这类版面缺陷会被自己的导出器抹平，评审就看不见了。
 */
function visibleText(html: string): string {
  return html
    .replace(/<(br|hr)\s*\/?>/g, '\n')
    .replace(/<\/(div|p|li|ul|ol|section|h[1-6]|tr|table)>/g, '\n')
    .replace(/<\/(td|th|span)>/g, ' ')
    // 🔴 行内 span 的**开**标签也要换成空格。第一版只换闭标签，
    //    `<div class="pos-group-label">缩合<span class="pos-group-ipa">/ˈdej/</span></div>`
    //    被导出成 `缩合/ˈdej/`，看着像"标签和音标挤在一起"——而 CSS 里
    //    `.pos-group-ipa { margin-left: 8px }`，页面上本来是分开的灰字。
    //    这种由导出器自己造出来的假象会骗走评审意见，比漏掉真缺陷更坏。
    .replace(/<span[^>]*>/g, ' ')
    .replace(/<[^>]*>/g, '')
    .replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ')
    .split('\n').map((l) => l.replace(/[ \t]+/g, ' ').trim()).filter(Boolean)
    .join('\n');
}

const out: string[] = [];
for (const w of words) {
  const entry = svc.getEntry(w) as Record<string, unknown> | null;
  if (!entry) { out.push(`## ${w}\n\n（getEntry 返回空 —— 页面上查无此词）\n`); continue; }
  const html = renderToStaticMarkup(
    createElement(View as never, { entry, speakLocale: locale, onWord: () => {}, speak: () => {} } as never),
  );
  // `--html` 用来判断某处「挤在一起」是页面真这样，还是本导出器去标签时造成的假象。
  out.push(argv.includes('--html')
    ? `## ${w}\n\n\`\`\`html\n${html}\n\`\`\`\n`
    : `## ${w}\n\n\`\`\`\n${visibleText(html)}\n\`\`\`\n`);
}

const text = out.join('\n');
if (outPath) { writeFileSync(outPath, text, 'utf8'); console.error(`✓ ${words.length} 词 → ${outPath}`); }
else console.log(text);
