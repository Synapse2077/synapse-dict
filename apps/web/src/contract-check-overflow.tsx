/**
 * 版式溢出闸（B26）：手机宽度下**整页不许出现横向滚动**。十门共用。2026-10-27。
 *
 * ═══ 为什么要渲染 ═══
 * 其余契约闸读的是 HTML 文本 ——「有没有」看得见，「撑不撑破」看不见。
 * de 收尾时就记下：`styles.css` 一条断词规则都没有，最长不可断片段 it 227 字、de/fr 107 字。
 * ⇒ 这里真用排版引擎量：本机的 Google Chrome 无头模式，**不装任何新依赖**。
 *
 * ═══ 怎么量 ═══
 * 每页一个 375px 宽的 iframe（它有自己的视口 ⇒ `@media (max-width: 820px)` 的手机版样式照常生效；
 * 塞进宽视口里一个 375px 的 div 是量不准的 —— 媒体查询看视口不看容器）。
 * iframe 里的脚本量完 `postMessage` 给顶层，顶层写进 DOM，`--dump-dom` 读回来。**一次只起一个 Chrome。**
 *
 * ═══ 判据 ═══
 *   O1 `scrollWidth > clientWidth`（整页横向滚动）⇒ 红。读者看得见的就是这件事。
 *      设计成可横滑的容器（`overflow-x: auto/hidden/scroll`）里面的东西不算 —— 那是有意的。
 *      顺带报最宽的那个元素（类名＋文字），方便定位。
 *   O2 一个关系词排成了不止一个行框（被从中间劈开）⇒ 红。
 *      🔴 只有 O1 时，拿掉 `.rel-item { display: inline-block }` **照样全绿** —— `overflow-wrap: anywhere`
 *      会把那一长串关系词从词中间硬劈开（`Affen|kasten`），不溢出了而读者读到的是半截词。
 *      「不溢出」分不出「在词与词之间换行」和「把词劈开」。
 *   O0 一页的结果都没回来（Chrome 起不来／脚本没跑）⇒ 红，**不许当成绿**。
 * 取样**每次从库里现查**：最长的无空格词头 2 ／ 最长的无空格关系目标所在页 2 ／ 关系最多的页 2 ／ 一个常用词。
 *
 * 用法（仓库根）：
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-overflow.tsx [--mutate]
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { getService } from '@synapse-dict/dict-core';
import {
  EnglishEntryView, SpanishEntryView, ItalianEntryView,
  FrenchEntryView, PortugueseEntryView, GermanEntryView, JapaneseEntryView,
  KoreanEntryView, VietnameseEntryView, RussianEntryView,
} from './App';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '../../..');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const WIDTH = 375;
type Lang = 'en' | 'es' | 'it' | 'fr' | 'pt' | 'de' | 'ja' | 'ko' | 'vi' | 'ru';
const VIEW: Record<Lang, unknown> = {
  en: EnglishEntryView, es: SpanishEntryView, it: ItalianEntryView,
  fr: FrenchEntryView, pt: PortugueseEntryView, de: GermanEntryView,
  ja: JapaneseEntryView, ko: KoreanEntryView,
  vi: VietnameseEntryView, ru: RussianEntryView,
};
const COMMON: Record<Lang, string> = {
  en: 'water', es: 'agua', it: 'acqua', fr: 'eau', pt: 'água', de: 'Wasser',
  ja: '水', ko: '물', vi: 'nước', ru: 'вода',
};

function samples(lang: Lang): string[] {
  const db = new DatabaseSync(join(ROOT, `data/db/synapse-dict-${lang}.sqlite`), { readOnly: true });
  const col = (sql: string) => (db.prepare(sql).all() as Array<{ w: string }>).map((r) => r.w);
  const out = [
    ...col(`SELECT word AS w FROM dict WHERE instr(word,' ')=0 ORDER BY length(word) DESC LIMIT 2`),
    ...col(`SELECT d.word AS w FROM (SELECT word_id, MAX(length(target)) m FROM sense_relation
              WHERE instr(target,' ')=0 GROUP BY word_id ORDER BY m DESC LIMIT 2) x JOIN dict d ON d.id=x.word_id`),
    ...col(`SELECT d.word AS w FROM (SELECT word_id, COUNT(*) c FROM sense_relation GROUP BY 1 ORDER BY c DESC LIMIT 2) x
              JOIN dict d ON d.id=x.word_id`),
    COMMON[lang],
  ];
  db.close();
  return [...new Set(out)];
}

// iframe 里跑的量具。只在**不在可横滑容器里**的元素中找最宽的那个。
// iframe 里跑的量具。🔴 **视口是 `.detail-column`，不是整个文档**：它设了 `overflow-y: auto`，
//    按 CSS 规范另一个方向的 `visible` 随之算成 `auto` ⇒ 超长内容不撑宽整页，而是让**这一栏**出横向滚动条。
//    第一版量 `documentElement.scrollWidth`，又把 `.detail-column` 当「有意横滑的容器」排除 ⇒ 400 字的长词都量不到。
//    排除只算栏**内部**的可横滑容器（变格表这类有意设计成可滑的）。
const MEASURE = `<script>
addEventListener('load', () => {
  const col = document.querySelector('.detail-column'), W = col.clientWidth, L = col.getBoundingClientRect().left;
  const scrollable = (el) => { for (let p = el.parentElement; p && p !== col; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
  let worst = null;
  for (const el of col.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.right - L > W + 1 && !scrollable(el) && (!worst || r.right > worst.right))
      worst = { right: Math.round(r.right - L), cls: el.className || el.tagName, text: (el.textContent || '').slice(0, 60) };
  }
  // O2：关系词被从中间劈开（一个 .rel-item 排成了不止一个行框）。⚠️ 这里在模板字符串里，注释不许用反引号
  let split = 0, splitEx = '';
  for (const el of col.querySelectorAll('.rel-item')) {
    if (el.getClientRects().length > 1) { split++; if (!splitEx) splitEx = (el.textContent || '').slice(0, 30); }
  }
  parent.postMessage({ id: window.name, sw: col.scrollWidth, cw: W, worst, split, splitEx }, '*');
});
</script>`;

function esc(s: string): string { return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;'); }

type Page = { lang: string; word: string; html: string };
type Result = { id: string; sw: number; cw: number; worst: { right: number; cls: string; text: string } | null;
  split: number; splitEx: string };

function measure(pages: Page[], css: string): Map<string, Result> {
  const frames = pages.map((p, i) => {
    const doc = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">`
      + `<style>${css}</style></head><body><div class="detail-column">${p.html}</div>${MEASURE}</body></html>`;
    return `<iframe name="p${i}" width="${WIDTH}" height="600" srcdoc="${esc(doc)}"></iframe>`;
  }).join('\n');
  // 🔴 监听必须在 `<head>` 里、早于任何 iframe：第一版写在 body 末尾，**先加载完的 iframe 先发消息、
  //    那时还没人在听** ⇒ 最前面 23 页的结果整批丢了（O0 当场报出来，没有混成绿）。
  const top = `<!doctype html><html><head><meta charset="utf-8"><script>
const got = [];
addEventListener('message', (e) => { got.push(e.data);
  const o = document.getElementById('out'); if (o) { const p = document.createElement('pre');
  p.textContent = JSON.stringify(e.data); o.appendChild(p); } });
addEventListener('DOMContentLoaded', () => { const o = document.getElementById('out');
  for (const d of got) { const p = document.createElement('pre'); p.textContent = JSON.stringify(d); o.appendChild(p); } });
</script></head><body><div id="out"></div>${frames}</body></html>`;
  const dir = mkdtempSync(join(tmpdir(), 'overflow-'));
  const file = join(dir, 'index.html');
  writeFileSync(file, top);
  const dom = execFileSync(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run',
    '--virtual-time-budget=20000', '--dump-dom', `file://${file}`],
    { encoding: 'utf8', maxBuffer: 512 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'] });
  const got = new Map<string, Result>();
  for (const m of dom.matchAll(/<pre>([\s\S]*?)<\/pre>/g)) {
    const r = JSON.parse(m[1].replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')) as Result;
    got.set(r.id, r);
  }
  return got;
}

function judge(pages: Page[], got: Map<string, Result>): string[] {
  const bad: string[] = [];
  pages.forEach((p, i) => {
    const r = got.get(`p${i}`);
    if (!r) { bad.push(`O0 ${p.lang} ${p.word}：结果没回来（Chrome 没跑起来或脚本没执行）`); return; }
    if (r.sw > r.cw) {
      bad.push(`O1 ${p.lang} ${p.word.slice(0, 30)}：整页宽 ${r.sw}px > ${r.cw}px`
        + (r.worst ? `　最宽的是 .${String(r.worst.cls).split(' ')[0]}「${r.worst.text.slice(0, 40)}」` : ''));
    }
    if (r.split > 0) bad.push(`O2 ${p.lang} ${p.word.slice(0, 30)}：${r.split} 个关系词被从中间劈开（如「${r.splitEx}」）`);
  });
  return bad;
}

const css = readFileSync(join(HERE, 'styles.css'), 'utf8');
const pages: Page[] = [];
for (const lang of Object.keys(VIEW) as Lang[]) {
  const svc = getService(lang) as unknown as { getEntry: (w: string) => unknown };
  for (const w of samples(lang)) {
    const entry = svc.getEntry(w);
    if (!entry) continue;
    const html = renderToStaticMarkup(createElement(VIEW[lang] as never, {
      entry, speakLocale: 'x', onWord: () => {}, speak: () => {}, onSelect: () => {},
    } as never));
    pages.push({ lang, word: w, html });
  }
}
const got = measure(pages, css);
const bad = judge(pages, got);
console.log(`■ 版式溢出闸：${pages.length} 页（十门，${WIDTH}px 视口）`);
for (const b of bad) console.log('  🔴 ' + b);
console.log(bad.length ? `🔴 ${bad.length} 页横向溢出` : '✅ 全绿');

if (process.argv.includes('--mutate')) {
  console.log('\n■ 变异');
  const long = 'x'.repeat(400);
  const probe: Page[] = [
    // ⚠️ 写成 nowrap：B26 修好之后，普通的长词会被 `overflow-wrap: anywhere` 正常断开（那是对的），
    //    人造探针得是样式规则救不回来的形状 —— 某个组件写死了不许换行。
    { lang: 'mut', word: '一个写了 nowrap 的 400 字长串', html: `<p style="white-space:nowrap">${long}</p>` },
    { lang: 'mut', word: '（反控）同样的词在可横滑容器里', html: `<div style="overflow-x:auto"><p style="white-space:nowrap">${long}</p></div>` },
  ];
  const g2 = measure(probe, css);
  const caught = judge([probe[0]], g2).length > 0;
  const ctrl = judge([probe[1]], new Map([...g2].map(([k, v]) => [k === 'p1' ? 'p0' : 'x' + k, v]))).length === 0;
  const lost = judge([probe[0]], new Map()).some((b) => b.startsWith('O0'));
  // B26 的两条样式规则各拿掉一条（在内存里改样式表文本，不碰文件），真页面必须红
  const real = pages.filter((p) => ['Haus', 'por', 'agua'].includes(p.word) || p.word.startsWith('Tetaumata'));
  const without = (a: string, b: string) => {
    if (!css.includes(a)) throw new Error('变异前提不成立：样式表里找不到 ' + a);
    return judge(real, measure(real, css.replace(a, b)));
  };
  const noWrap = without('  overflow-wrap: anywhere;\n', '').some((x) => x.startsWith('O1'));
  const noIB = without('.rel-item { display: inline-block; margin-right: 8px; }', '.rel-item { margin-right: 8px; }')
    .some((x) => x.startsWith('O2'));
  console.log(`  ${caught ? '✅' : '🔴 没逮到'} 写了 nowrap 的长串撑破版面`);
  console.log(`  ${ctrl ? '✅' : '🔴 误报'} （反控）可横滑容器里的不算`);
  console.log(`  ${lost ? '✅' : '🔴 没逮到'} 结果没回来不许当成绿`);
  console.log(`  ${noWrap ? '✅' : '🔴 没逮到'} 拿掉 .detail-column 的 overflow-wrap ⇒ 长词撑破`);
  console.log(`  ${noIB ? '✅' : '🔴 没逮到'} 拿掉 .rel-item 的 inline-block ⇒ 关系词被劈开`);
  const dead = [caught, ctrl, lost, noWrap, noIB].filter((x) => !x).length;
  console.log(`  变异 ${5 - dead}/5`);
  process.exit(dead || bad.length ? 1 : 0);
}
process.exit(bad.length ? 1 : 0);
