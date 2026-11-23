/**
 * 十门语言入口视图的**唯一登记表**。2026-11-23。
 *
 * ═══ 为什么抽出来 ═══
 * `render-dump.tsx` 和 `layout-probe.tsx` 各有一张同样的表，而两张表都犯过
 * 「少登记一门」的账（render-dump 漏 ja/ko/ru 各一次，layout-probe 六门时漏 en）。
 * 再给新的渲染度量脚本抄一张，就是第三个实例（`[[refactor-mindset-code-quality]]`）。
 *
 * 自检与 `css-audit.ts`／`contract-check-layout.tsx` 同一条：
 * 读 `App.tsx` 的 `export function XxxEntryView`，与登记表逐名对账。
 * 🔴 认不出任何视图 ⇒ 判据坏了，不是「全登记了」。
 *
 * ⚠️ 本模块只在 node 端被工具脚本 import（用了 node:fs）；`App.tsx` 不 import 它，
 *    所以不会进浏览器包。
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  EnglishEntryView, SpanishEntryView, ItalianEntryView, FrenchEntryView,
  PortugueseEntryView, GermanEntryView, JapaneseEntryView, KoreanEntryView,
  VietnameseEntryView, RussianEntryView,
} from './App';

/** 语种 → [视图组件, 朗读 locale]。渲染参数统一传 `{ entry, speakLocale, onWord, speak }`。 */
export const VIEWS: Record<string, [unknown, string]> = {
  en: [EnglishEntryView, 'en-US'],
  es: [SpanishEntryView, 'es-MX'],
  it: [ItalianEntryView, 'it-IT'],
  fr: [FrenchEntryView, 'fr-FR'],
  pt: [PortugueseEntryView, 'pt-BR'],
  de: [GermanEntryView, 'de-DE'],
  ja: [JapaneseEntryView, 'ja-JP'],
  ko: [KoreanEntryView, 'ko-KR'],
  vi: [VietnameseEntryView, 'vi-VN'],
  ru: [RussianEntryView, 'ru-RU'],
};

/** 登记表 ↔ `App.tsx` 源码对账。不一致时抛，调用方直接退出。 */
export function assertViewsRegistered(): void {
  const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'App.tsx'), 'utf8');
  const inSource = [...app.matchAll(/export function (\w+EntryView)\b/g)].map((m) => m[1]);
  const declared = new Set(Object.values(VIEWS).map(([f]) => (f as { name: string }).name));
  const unlisted = inSource.filter((fn) => !declared.has(fn));
  if (inSource.length === 0 || unlisted.length) {
    throw new Error(inSource.length === 0
      ? '🔴 判据坏了：App.tsx 里一个 `export function XxxEntryView` 都没认出来'
      : `🔴 App.tsx 里有没登记进 VIEWS 的视图：${unlisted.join(', ')}`);
  }
}
