/** 展示层契约闸（vi）。2026-10-03（阶段 9b）。
 *
 * ═══ 为什么数据层十一道闸全绿之后还要这一道 ═══
 * `[[it-display-layer-stage8]]`：**接上展示层是独立一道闸。**
 * vi 这一轮它当天就兑现了 8 次，全是数据闸报绿时逮到的，其中四件最狠：
 *   · 查 `mai`（清晨/梅）显示的是 `Mai`（姓氏）—— `word_norm` 冲突 1,263 组，
 *     `.get()` 只取第一行 ⇒ **1,291 行的页面永远打不开而且内容是错的**
 *   · 例句里印着韩语 `나는 개를 두마리 기르고 있다.` —— 1,655 条内嵌译文
 *   · 关系里印着波兰语 `kościół` —— 2,238 行非国语字目标，全是死链
 *   · 关系目标印成 `hoahòahọahỏahoahòahọahỏahoahòahọahỏa` —— 缺分隔符 ＋ 缺去重
 * 共同点：**所有形式判据都满足**，只有读者看到的东西是错的。
 *
 * ⇒ 本闸把 `VietnameseEntryView` 用 `react-dom/server` 渲染成静态 HTML，
 *   断言全部盯**去标签之后的可见文字**，不盯 DOM 结构。
 *
 * 跑：npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-vi.tsx
 *     加 `--dump ăn nhà` 把渲染结果打出来读（找缺陷用的，不是闸）
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { VietnameseEntryView, EXAMPLES } from './App';
import { POS_LABELS, REL_LABELS, VI_POS_LABELS, VI_RELATION_LABELS,
         VI_DIALECT_LABELS, VI_ETYM_TYPE_LABELS, VI_SPELLING_RULE,
         VI_EDITION_LABELS } from '@synapse-dict/dict-labels';

const svc = getService('vi') as unknown as {
  getEntry(w: string): any;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;

function render(entry: unknown): string {
  return renderToStaticMarkup(createElement(VietnameseEntryView, {
    entry, speakLocale: 'vi-VN', onWord: () => {}, speak: () => {},
  } as never));
}

function visibleText(html: string): string {
  return html.replace(/<[^>]*>/g, ' ').replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ');
}

/** 只看**可见文字**，不看 `title=` 这种提示属性 —— 提示不是内容。 */
function bodyText(html: string): string {
  return visibleText(html.replace(/\stitle="[^"]*"/g, ''));
}

const HANGUL = /[가-힣ᄀ-ᇿ]/;
const KANA = /[぀-ヿ]/;

type Check = { word: string; name: string; hit: (t: string, e: any, html: string) => string | null };

const CHECKS: Check[] = [
  // ══ ① 越南语特有的字段必须真的印出来 ══
  { word: 'nhà', name: '汉字/喃字表记印出来了',
    hit: (t) => (t.includes('家') ? null : '看不到喃字表记 家') },
  { word: 'ăn', name: '六个方言点的音标印出来了（至少四个）',
    hit: (t) => ((t.match(/音/g) ?? []).length >= 4 ? null : '方言点标注少于四个') },
  { word: 'con', name: '量词区印出来了',
    hit: (t) => (t.includes('量词') ? null : '看不到量词区') },
  { word: 'ăn', name: '例句与英文译文印出来了',
    hit: (t) => (t.includes('ăn thịt') && t.includes('eat meat') ? null : '看不到例句或译文') },

  // ══ ② 🔴 五条欠账的**读者口径**。每条都是「页面上必须/不许看到 X」 ══

  // W6：按码位推定的表记（14,327 行，实测只有 70.8% 对）不许印成权威表记。
  { word: 'nhà', name: '🔴 W6：按码位推定的表记标了「未经核实」',
    hit: (t) => (t.includes('按字形推定（未经核实）') ? null
      : 'codepoint-v1 的表记没有标注 —— 它只有 70.8% 对') },
  { word: 'nhà', name: '🔴 W6：按码位推定的表记旁边不许印「汉越字」三个字',
    hit: (t) => (/按字形推定（未经核实）\s*汉越字/.test(t)
      ? '把按码位猜的表记印成了「汉越字」' : null) },

  // W7：拼出来的音标（96,267 行）必须让读者分得出。
  { word: 'hóa', name: '🔴 W7：拼出来的音标标了「按音节拼写」',
    hit: (t) => (t.includes('按音节拼写') ? null : 'compose: 的音标没有标注') },

  // W10：`example.ref` 是出处，不是译文。
  { word: 'ăn', name: '🔴 W10：`ref` 印成「出处：」',
    hit: (t, e) => {
      const withRef = [...e.examples].some((x: any) => x.ref);
      if (!withRef) return null;           // 这个词没有带 ref 的例句，跳过
      return t.includes('出处：') ? null : '带 ref 的例句没有印「出处：」标签';
    } },

  // W13：中文释义与同页汉字表记逐字相同（1,183 条）⇒ 折叠，**不隐藏**。
  { word: 'công nhân', name: '🔴 W13：中文释义＝汉字表记时折叠成「同汉字表记」',
    hit: (t) => (t.includes('同汉字表记') ? null : '没有折叠 —— 工人会印两遍') },
  { word: 'công nhân', name: '🔴 W13：折叠**不是隐藏** —— 这一页仍然有中文释义',
    hit: (t) => (t.includes('蓝领工人') ? null
      : '把 W13 那一行连带把别的中文释义也藏了 —— 隐藏比重复严格更差') },

  // W15：16,305 个词形唯一的释义信息是一条指针。
  { word: 'UBND', name: '🔴🔴 W15：没有可出版义项时印指针',
    hit: (t) => (t.includes('uỷ ban nhân dân') ? null
      : '只有指针的词形印成了空页 —— 源头给了而我们没印') },
  { word: 'UBND', name: '🔴 W15：指针页诚实说明为什么没有释义',
    hit: (t) => (t.includes('异写或缩写') ? null : '没有说明，读者只看到一串越南语') },

  // ══ ③ 🔴 这几条钉的是**本轮真实逮到的缺陷**，别让它们回来 ══

  // 🔴🔴 最狠的那个：`word_norm` 冲突（1,263 组）。
  { word: 'mai', name: '🔴🔴 查 `mai` 得到的是 `mai` 不是 `Mai`（大小写冲突）',
    hit: (t, e) => {
      if (e.word !== 'mai') return `词条页返回的是 \`${e.word}\` —— 原样大小写优先失效了`;
      return t.includes('清晨') ? null : '看不到 mai（清晨）的释义';
    } },
  { word: 'mai', name: '同形词给了出口（`Mai` 可点）',
    hit: (t) => (t.includes('同形词') ? null : '同一 word_norm 的别的词形没有入口') },

  // 🔴 例句**正文**里不许出现韩文（三语方针：中＋英＋越）。
  // 🔴🔴 **判据收窄过一次**：第一版查的是**整页文字**，当场报红 ——
  //    而那段韩文在 `ref`（出处）里：`출处：창세기 2장 9절`（创世记 2 章 9 节）。
  //    数据侧已经把**完全不可读**的 679 条 ref 判掉了，但剩下 7 条是
  //    **以拉丁为主、夹着原文人名**的正当引文（`2021, Han Kang, …, 한강`）——
  //    那里的韩文是作者名的原文，是**信息不是噪声**。
  //    ⇒ 判据只盯 `vi-example-text` 那一格。`[[criteria-narrower-than-you-think]]`：
  //      判据说的是「例句正文里混进了别的语言」，不是「页面上出现过韩文字符」。
  { word: 'ăn', name: '🔴 例句正文里没有韩文（1,655 条内嵌译文已切）',
    hit: (_t, _e, html) => {
      const texts = [...html.matchAll(/<span class="vi-example-text">([^<]*)<\/span>/g)]
        .map((m) => m[1]);
      const bad = texts.filter((x) => HANGUL.test(x));
      return bad.length ? `例句正文里有韩文：${bad[0].slice(0, 40)}` : null;
    } },
  { word: 'nhà', name: '🔴 页面上没有假名',
    hit: (t) => (KANA.test(t) ? '页面上出现了假名' : null) },

  // 🔴 关系目标之间必须有分隔符（否则十二个词粘成一串）。
  { word: 'hóa', name: '🔴 关系目标之间有分隔符',
    hit: (t) => (/hoa\s*、\s*hòa/.test(t) ? null
      : '关系目标粘成一串（`hoahòahọahỏa`）—— 缺分隔符') },
  { word: 'hóa', name: '🔴 同一组关系目标不许重复印',
    hit: (t) => {
      const m = t.match(/hoa/g) ?? [];
      return m.length <= 4 ? null : `「hoa」在页面上出现 ${m.length} 次 —— 渲染期没去重`;
    } },

  // 🔴 同一方言的音标归一行（`ăn` 原先排出 11 个播放按钮、`/ʔan˧˧/ 河内音` 两次）。
  { word: 'ăn', name: '🔴 同一方言的音标归一行、组内去重',
    hit: (t) => {
      const m = t.match(/河内音/g) ?? [];
      return m.length <= 1 ? null : `「河内音」出现 ${m.length} 次 —— 没按方言归组`;
    } },

  // 🔴 词源三版并印必须标来源（7,661 个词形会看到两三段）。
  { word: 'ăn', name: '🔴 词源段标了来源语言版',
    hit: (t) => (/(中文版|英文版|越南语版)\s*\S/.test(t) ? null
      : '词源段没标来源 —— 三段同义的话读者会以为是三个词源') },
  { word: 'ăn', name: '🔴 词源的中文那段排在最前',
    hit: (t) => {
      const zh = t.indexOf('中文版'); const en = t.indexOf('英文版');
      if (zh < 0 || en < 0) return null;
      return zh < en ? null : '英文版排在中文版前面';
    } },

  // 🔴🔴 B18 的 vi 版：有词源就必须印出来，哪怕它挂不上任何义项组。
  //    实测 **407 个词形**（有词源的 1.6%）的词源号与义项组对不上 ⇒ 第一版一个字都不印。
  //    `biên phòng` 是其中之一（56 个「所有可出版义项都挂不上词条」那一类）。
  { word: 'biên phòng', name: '🔴🔴 B18：词源号对不上时词源仍然印出来',
    hit: (t) => (t.includes('漢越詞') || t.includes('Sino-Vietnamese')
      ? null : '有词源而页面上一个字都没有 —— B18 的形状换个条件复发了') },

  // 🔴 `paronym`（17,637 行）不许混在语义关系里。
  { word: 'mai', name: '🔴 `paronym` 单开一区，不混在「语义关系」下',
    hit: (t) => {
      if (!t.includes('仅差附加符号')) return null;      // 这个词没有 paronym
      const sem = t.indexOf('语义关系'); const ortho = t.indexOf('不打符号时会撞上的词');
      if (ortho < 0) return 'paronym 区的标题不见了';
      return sem < 0 || ortho > sem ? null : 'paronym 排进了语义关系区';
    } },
];

/** 全量扫描：对每个抽样词渲染一遍，盯**跨词的结构性契约**。 */
function sweep(words: string[]) {
  let bad = 0;
  let rawKind = 0; let rawPos = 0; let rawDialect = 0; let rawRule = 0;
  let links = 0; let deadLinks = 0;
  let hangul = 0; let kana = 0;
  const kinds = new Set<string>();
  for (const w of words) {
    const e = svc.getEntry(w);
    if (!e) continue;
    const html = render(e);
    const t = bodyText(html);
    // ① 关系徽标不许印英文原码。
    // 🔴🔴 **判据只看 `vi-rel-kind` 那一格，不看整页文字** —— ko 那份第一版扫整页，
    //    报出的 14 处全在**英文释义里**（`related to …`）。
    //    `[[criteria-narrower-than-you-think]]`：它说的是"徽标印了原码"，
    //    不是"页面上出现过这个英文单词"。
    for (const m of html.matchAll(/<span class="vi-rel-kind">([^<]*)<\/span>/g)) {
      if (/^[a-z_]+$/.test(m[1])) {
        console.log(`   🔴 ${w} 的关系徽标印的是英文原码 \`${m[1]}\``);
        rawKind += 1;
      }
    }
    for (const r of [...e.senseRelations, ...e.entryRelations]) {
      kinds.add(r.kind);
      if (r.targetId) links += 1; else deadLinks += 1;
    }
    // ② 词性：两张表都查不到 ⇒ 徽标会是空的（而**空的徽标看起来像"这个词没有词性"**）
    for (const en of e.entries) {
      if (!en.pos) continue;
      const over = VI_POS_LABELS[en.pos];
      if (over === undefined && POS_LABELS[en.pos] === undefined) {
        console.log(`   🔴 ${w} 的词性 \`${en.pos}\` 两张表都没有`);
        rawPos += 1;
      }
    }
    // ③ 方言值：表里没有就不印，而**不印和"源头没说"在页面上长得一样**
    for (const p of e.pronunciations) {
      if (VI_DIALECT_LABELS[p.dialect] === undefined) {
        console.log(`   🔴 ${w} 的方言值 \`${p.dialect}\` 不在表里`);
        rawDialect += 1;
      }
    }
    // ④ `rule_ver`：不在表里 ⇒ 原样印出 `codepoint-v1` 这种内部串
    for (const sp of e.spellings) {
      if (VI_SPELLING_RULE[sp.ruleVer] === undefined) {
        console.log(`   🔴 ${w} 的 rule_ver \`${sp.ruleVer}\` 不在表里 —— 会印内部串`);
        rawRule += 1;
      }
    }
    // ⑤ 三语方针：**例句正文**里不许有韩文/假名（`ref` 里的原文人名是正当的，见上）
    const exTexts = [...html.matchAll(/<span class="vi-example-text">([^<]*)<\/span>/g)]
      .map((m) => m[1]).join(' ');
    if (HANGUL.test(exTexts)) { console.log(`   🔴 ${w} 例句正文里有韩文`); hangul += 1; }
    if (KANA.test(exTexts)) { console.log(`   🔴 ${w} 例句正文里有假名`); kana += 1; }
  }
  // 🔴 **值域要跨全库查，不只查抽样词**：抽样扫不到的值一样会印给读者。
  const allKinds = (db.prepare(
    'SELECT DISTINCT kind FROM sense_relation WHERE hidden = 0').all() as Array<{ kind: string }>)
    .map((r) => r.kind);
  const missKind = allKinds.filter(
    (k) => VI_RELATION_LABELS[k] === undefined && REL_LABELS[k] === undefined);
  const allDialects = (db.prepare(
    'SELECT DISTINCT dialect FROM pronunciation').all() as Array<{ dialect: string }>)
    .map((r) => r.dialect);
  const missDialect = allDialects.filter((d) => VI_DIALECT_LABELS[d] === undefined);
  const allPos = (db.prepare(
    "SELECT DISTINCT pos FROM entry WHERE pos IS NOT NULL").all() as Array<{ pos: string }>)
    .map((r) => r.pos);
  const missPos = allPos.filter(
    (p) => VI_POS_LABELS[p] === undefined && POS_LABELS[p] === undefined);
  const allEtym = (db.prepare(
    'SELECT DISTINCT etym_type FROM entry WHERE etym_type IS NOT NULL').all() as
    Array<{ etym_type: string }>).map((r) => r.etym_type);
  const missEtym = allEtym.filter((x) => VI_ETYM_TYPE_LABELS[x] === undefined);
  const allEditions = (db.prepare(
    'SELECT DISTINCT src FROM etymology').all() as Array<{ src: string }>).map((r) => r.src);
  const missEdition = allEditions.filter((x) => VI_EDITION_LABELS[x] === undefined);

  const dom: Array<[string, string[], number]> = [
    ['关系类别', missKind, allKinds.length],
    ['方言点', missDialect, allDialects.length],
    ['词性', missPos, allPos.length],
    ['词源类型', missEtym, allEtym.length],
    ['词源来源版', missEdition, allEditions.length],
  ];
  console.log('\n── 值域覆盖（**跨全库**，不只抽样词）');
  for (const [name, miss, tot] of dom) {
    console.log(`   ${miss.length === 0 ? '✅' : '🔴'} ${name.padEnd(10)} ${tot} 种，缺名字 ${miss.length} 种${miss.length ? `：${miss.join(' ')}` : ''}`);
    bad += miss.length;
  }
  console.log('\n── 渲染扫描');
  console.log(`   ${rawKind === 0 ? '✅' : '🔴'} 关系徽标印中文名        原码漏出 ${rawKind} 处`);
  console.log(`   ${hangul === 0 ? '✅' : '🔴'} 例句正文无韩文        ${hangul} 个词`);
  console.log(`   ${kana === 0 ? '✅' : '🔴'} 例句正文无假名        ${kana} 个词`);
  console.log(`   ℹ️  关系链接 ${links} 条可点、${deadLinks} 条源头引用了我们没收的词（如实印成纯文本）`);
  console.log(`   ℹ️  抽样扫到 ${kinds.size} 种关系类别`);
  bad += rawKind + rawPos + rawDialect + rawRule + hangul + kana;
  return bad;
}

function main() {
  const argv = process.argv.slice(2);
  const di = argv.indexOf('--dump');
  if (di >= 0) {
    for (const w of argv.slice(di + 1)) {
      const e = svc.getEntry(w);
      console.log(`\n═══ ${w} ═══\n${e ? bodyText(render(e)) : '（查不到）'}`);
    }
    return;
  }
  console.log('■ 展示层契约闸（vi）：把 `VietnameseEntryView` 渲染出来，断言可见文字');
  let bad = 0;
  for (const c of CHECKS) {
    const e = svc.getEntry(c.word);
    if (!e) { console.log(`   🔴 ${c.word} 查不到 —— 抽样词必须在库里`); bad += 1; continue; }
    const html = render(e);
    const why = c.hit(bodyText(html), e, html);
    console.log(`   ${why ? '🔴' : '✅'} ${c.word.padEnd(11)} ${c.name}${why ? ` —— ${why}` : ''}`);
    if (why) bad += 1;
  }
  bad += sweep(EXAMPLES.vi ?? []);
  console.log(`\n${bad === 0 ? '■ ✅ 全绿' : `■ 🔴 红 ${bad} 条`}`);
  process.exit(bad === 0 ? 0 : 1);
}

main();
