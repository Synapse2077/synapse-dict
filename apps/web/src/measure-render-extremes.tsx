/**
 * 渲染层极端页度量：**按用户真正看到的样子**量十门最重的页。2026-11-23。
 *
 * ═══ 为什么需要它 ═══
 * `docs/DISPLAY_EXTREMES.md` §1 那张总账（de `Tag` 171 KB / 4,142 个关系）没有可复现脚本，
 * 只有一句「用 renderToStaticMarkup 渲染，数 .rel-item」——2026-11-23 复现时发现：
 *   · 旧 §1 的关系数是**双倍计数**（每个目标被数了两次），与同文档 §2.1 的数据层数字对不上；
 *   · en `G.O.S.` 那条 752 义项是 2026-10-29 已修的老词典层缺陷，文档没跟着改。
 * ⇒ 数字写进文档却算不出来，下一次动界面又会拿一张过期表当依据
 *   （`[[lesson-must-become-mechanism]]`、`[[external-anchor-gates]]`）。
 *
 * ═══ 量什么、不量什么 ═══
 * 与 `layout-probe.tsx` 分工：那个量「排版事故的结构性成因」（超长不可断词、单行块数），
 * 本脚本量**渲染成品的体量与块数**，给文档 §1 用。两者都是 node 端渲染，
 * 与 `contract-check-*.tsx` 同一条代码路径（不是读接口 JSON 猜）。
 *
 * ⚠️ 折叠默认**展开**（`__EXPAND_ALL__ = true`）——要量最坏情况；
 *    页面默认只露前几条，首屏比这里的数字小。
 *
 * 用法（仓库根）：
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/measure-render-extremes.tsx
 *     ... --lang de          # 只量一门
 * 只读，不写库。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
(globalThis as { __EXPAND_ALL__?: boolean }).__EXPAND_ALL__ = true;
import { getService } from '@synapse-dict/dict-core';
import { VIEWS, assertViewsRegistered } from './views';

const argv = process.argv.slice(2);
const ONLY = argv.includes('--lang') ? argv[argv.indexOf('--lang') + 1] : undefined;

try { assertViewsRegistered(); } catch (e) {
  console.error(String(e instanceof Error ? e.message : e));
  process.exit(1);
}
if (ONLY && !VIEWS[ONLY]) {
  console.error(`🔴 认不出语种 ${JSON.stringify(ONLY)}；登记了的：${Object.keys(VIEWS).join(' ')}`);
  process.exit(1);
}

type Row = {
  lang: string; arm: string; word: string;
  bytes: number; nodes: number; ms: number; dataN: number;
  sense: number; rel: number; etym: number;
  example: number; form: number;
};

const n = (h: string, re: RegExp) => (h.match(re) ?? []).length;

// 🔴 类名判据必须**覆盖十门**。第一版只写了 en/de 那套（sense-zh／rel-item／
//    example-item／form-cell），vi 和 ru 的每个块都数成 0 —— 而两门页面的字节数
//    最高到 344 KB。**假 0 比不量更坏**：它看起来像「这门没有该块」。
//    下面是各门真正的单元类名，并集使用：
//      义项   sense-zh（八门）／vi-sense／ru-sense
//      关系   rel-item（八门）／vi-link／ru-link（⚠️ 近似：vi/ru 的链接类名不只用于关系）
//      例句   sense-example（多门）／vi-example／ru-example
//      变形   de-form-cell／de-infl（de）／form-item（通用列表）／infl-form（ja/ko）／ru-infl-table（ru 变格表）
//      词源   etym-label（多门）／vi-etym-text／ru-etym-text
const SEL = {
  sense: /class="sense-zh"|class="vi-sense"|class="ru-sense"/g,
  rel: /class="rel-item"|class="vi-link"|class="ru-link"/g,
  example: /class="sense-example"|class="vi-example"|class="ru-example"/g,
  form: /class="de-form-cell"|class="de-infl"|class="form-item"|class="infl-form"|class="ru-infl-table"/g,
  etym: /class="etym-label"|class="vi-etym-text"|class="ru-etym-text"/g,
} as const;

for (const [lang, [View, locale]] of Object.entries(VIEWS)) {
  if (ONLY && lang !== ONLY) continue;
  const svc = getService(lang) as unknown as { getEntry(w: string): any; db: any };
  const has = (tbl: string, col: string) => {
    try { return svc.db.prepare(`PRAGMA table_info(${tbl})`).all().some((r: any) => r.name === col); }
    catch { return false; }
  };

  // ── 取样：每类只取最狠的一个。分布见 scripts/measure_display_extremes.py（数据层）。
  const senseHide = has('sense', 'hidden') ? ' AND COALESCE(s.hidden,0)=0' : '';
  const example = has('example', 'word_id')
    ? 'SELECT d.word w, COUNT(*) n FROM example e JOIN dict d ON d.id=e.word_id GROUP BY e.word_id ORDER BY n DESC LIMIT 1'
    : 'SELECT word w, COUNT(*) n FROM example GROUP BY word ORDER BY n DESC LIMIT 1';
  // 🔴 变形块挂在 `base_id`（这一堆变形属于哪个词元），不是 `word_id`（这一行自己是谁）。
  //    第一版按 word_id 分组，de 取到 `haben`（34 KB）而漏掉真正的 `überlegen`（531 个变形）
  //    —— 取样错了，量出来的「最狠」就不是最狠。
  const inflection = has('inflection', 'base_id')
    ? 'SELECT d.word w, COUNT(*) n FROM inflection i JOIN dict d ON d.id=i.base_id GROUP BY i.base_id ORDER BY n DESC LIMIT 1'
    : (has('inflection', 'entry_id')
        ? 'SELECT d.word w, COUNT(*) n FROM inflection i JOIN entry en ON en.id=i.entry_id JOIN dict d ON d.id=en.word_id GROUP BY en.word_id ORDER BY n DESC LIMIT 1'
        : null);

  const arms: Array<[string, string | null]> = [
    ['义项最多', `SELECT d.word w, COUNT(*) n FROM sense s JOIN dict d ON d.id=s.word_id WHERE 1=1${senseHide} GROUP BY s.word_id ORDER BY n DESC LIMIT 1`],
    ['关系最多', 'SELECT d.word w, COUNT(*) n FROM sense_relation r JOIN dict d ON d.id=r.word_id GROUP BY r.word_id ORDER BY n DESC LIMIT 1'],
    ['例句最多', example],
    ['变形最多', inflection],
    ['读音最多', 'SELECT d.word w, COUNT(*) n FROM pronunciation p JOIN dict d ON d.id=p.word_id GROUP BY p.word_id ORDER BY n DESC LIMIT 1'],
    ['词源最多', has('etymology', 'edition')
      ? "SELECT d.word w, COUNT(DISTINCT e.edition||':'||e.etym_no) n FROM etymology e JOIN dict d ON d.id=e.word_id GROUP BY e.word_id ORDER BY n DESC LIMIT 1"
      : 'SELECT d.word w, COUNT(*) n FROM etymology e JOIN dict d ON d.id=e.word_id GROUP BY e.word_id ORDER BY n DESC LIMIT 1'],
    ['词形最长', 'SELECT word w, LENGTH(word) n FROM dict ORDER BY n DESC LIMIT 1'],
  ];

  const rows: Row[] = [];
  for (const [arm, sql] of arms) {
    if (!sql) continue;
    let got: Array<{ w: string; n: number }> = [];
    try { got = svc.db.prepare(sql).all() as Array<{ w: string; n: number }>; }
    catch { continue; }                       // 该门没有这张表／列 —— 跳过，不冒充 0
    for (const { w } of got.slice(0, 1)) {
      const entry = svc.getEntry(w);
      if (!entry) continue;
      let html = '';
      let ms = -1;
      try {
        const t0 = performance.now();
        html = renderToStaticMarkup(createElement(View as never, {
          entry, speakLocale: locale, onWord: () => {}, speak: () => {},
        } as never));
        ms = performance.now() - t0;
      } catch (e) {
        console.error(`🔴 ${lang} ${arm} ${w} 渲染抛异常：${String(e).slice(0, 160)}`);
        continue;
      }
      rows.push({
        lang, arm, word: w, bytes: Buffer.byteLength(html),
        nodes: n(html, /<[a-z][a-z0-9]*[\s>]/g),
        ms: Math.round(ms * 10) / 10,
        dataN: got[0]?.n ?? -1,
        sense: n(html, SEL.sense),
        rel: n(html, SEL.rel),
        etym: n(html, SEL.etym),
        example: n(html, SEL.example),
        form: n(html, SEL.form),
      });
    }
  }
  if (!rows.length) { console.log(`── ${lang}：没取到可渲染的样本`); continue; }
  rows.sort((a, b) => b.bytes - a.bytes);
  console.log(`\n── ${lang} ──`);
  console.log('| 类型 | 词 | 字节 | 节点 | 渲染毫秒 | 数据层条数 | 义项 | 关系 | 词源 | 例句 | 变形 |');
  console.log('|---|---|---|---|---|---|---|---|---|---|---|');
  for (const r of rows) {
    console.log(`| ${r.arm} | ${r.word} | ${r.bytes.toLocaleString('en-US')} | ${r.nodes} | ${r.ms} | ${r.dataN} | ${r.sense} | ${r.rel} | ${r.etym} | ${r.example} | ${r.form} |`);
  }
}
