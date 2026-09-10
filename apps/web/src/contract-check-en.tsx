/**
 * 英语展示层契约闸：把真实数据喂进 React 组件、渲染成 HTML，再断言。2026-09-09（阶段 8）。
 *
 * ═══ 为什么数据层的回归闸不够 ═══
 * `en/tests/test_no_regression.py` 的 E 组一共三条，两条 grep `english.ts` 的源码
 * （「有没有写 `FROM audio`」）、一条查库。那只能证明**代码里写了**，
 * 证明不了**渲染出来有**。这两件事差着一个组件。
 *
 * 🔴🔴 **建这道闸的直接原因**：2026-09-09 用户看页面时点出
 *      「es 的释义先按名词/动词分类，英语不是这样」。查下来 en 一次带出**四个**缺陷：
 *        ① 释义不按词性分组（es/it/fr/pt/de 五门全有 `pos-group`，en 漏抄）
 *        ② 分组标题印的是原码 `n`（共用的 `posLabel()` 26 种取值一个不缺，没调用）
 *        ③ 英文定义那行没有语种徽标（fr 2026-08-29 修过同一个，en/de 没跟上）
 *        ④ 无词性的组不说话，`giffen` 的「低质商品」跟在「专名」后面被读成人名
 *      —— **当天 en 的六道闸没有一条会响**，因为它们全都读库，照不到 HTML。
 *      ⇒ 本闸存在的意义是「**下次没人会再靠肉眼看页面发现这些**」
 *        （`[[lesson-must-become-mechanism]]`：交付物是一道会自己响的闸）。
 *
 * ⇒ 本闸的每一条都断言 **HTML 里有没有**，不是数据库里有没有。
 *
 * ═══ en 独有、别的语种的闸够不到的四条 ═══
 *   ① **老词典层 242 万词已经拆成义项级**（`sense_src.src='ecdict'`，2,766,843 条），
 *      其中只有 14.95% 带词性 ⇒ **223 万条义项 `pos` 为空**，是别的语种没有的量级。
 *      「无词性的组不许无标题地跟在别的组后面」这条断言只有 en 需要（es 73 词、it 1,455 词）。
 *   ② **`topic` 桶按来源分**：kaikki 是上千种英文 slug（有意不显示），
 *      老词典层是中文短码（`计`／`医`／`化`，**必须显示**）。两个方向都要守。
 *   ③ **ECDICT 尺子是 en 独有的产品价值**（考纲/柯林斯/牛津），不渲染就白买了。
 *   ④ **书证出处必须在引文前面** —— 2026-09-09 外审三次独立读错才改的顺序，
 *      而**数据完全正确、闸永远绿**：`ref` 挂在对的那条例句上，错的只是先后。
 *
 * ═══ 用法（仓库根目录）═══
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-en.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-en.tsx --limit 420
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-en.tsx --mutate
 *
 * ⚠️ `--tsconfig` 不能省：仓库根目录没有 tsconfig.json，tsx 找不到 jsx: "react-jsx"。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { enExamLabels } from '@synapse-dict/dict-labels';
import { EnglishEntryView, capAudios } from './App';

const svc = getService('en') as unknown as {
  getEntry(w: string): unknown;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;
type Entry = Record<string, any>;
type Check = { name: string; hit: (e: Entry, html: string) => string | null };

function render(entry: Entry): string {
  return renderToStaticMarkup(createElement(EnglishEntryView, {
    entry: entry as never, speakLocale: 'en-US', onWord: () => {}, speak: () => {},
  } as never));
}

// 🔴 比对两边必须**同样归一**，否则断言在报自己的 bug（pt 那轮踩过：
//    例句中文里的 `&` 在 HTML 里是 `&amp;`、换行被压成空格 ⇒ `includes(原文)` 必然找不到）。
const norm = (x: string) => x
  .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'")
  .replace(/\s+/g, ' ').trim();
const text = (h: string) => norm(h.replace(/<[^>]*>/g, ' '));
const count = (h: string, re: RegExp) => (h.match(re) ?? []).length;

/** 页面上所有 `.badge tag` 的文字 —— 义项标签、考纲标签都走这个类名。 */
const badges = (h: string) =>
  [...h.matchAll(/<span class="badge tag">([^<]*)<\/span>/g)].map((m) => norm(m[1]));

const CHECKS: Check[] = [
  // ───────────────── A. 释义区 ─────────────────
  {
    // ⚠️ 条件问的是「**有没有中文**」不是「有没有义项」—— en 有 3,360 条指针义项
    //    本来就没有中文（`oneself` 那批），拿「有义项」当前提会造出一批假红。
    name: '🔴 A1 有中文的义项，整块释义却不渲染（is_lemma 挡住 12 万词形那个形状）',
    hit: (e, h) => (e.senses.some((s: Entry) => s.zh) && !/class="sense-zh"/.test(h))
      ? `${e.senses.length} 条义项里有中文，HTML 里一条 .sense-zh 都没有` : null,
  },
  {
    // ⭐ 上一条只问「有没有」，这一条问「**几条就该有几条**」——
    //    少一条（被某个 filter 悄悄吃掉）也红。
    // ⚠️ `.sense-zh` 现在也承载「只有标签没有中文」的那一行（徽标要跟中文同行），
    //    所以 got 只能 **≥** want，不能相等断言。
    name: '🔴 A2 有中文的义项条数与渲染出来的对不上',
    hit: (e, h) => {
      const want = e.senses.filter((s: Entry) => s.zh).length;
      const got = count(h, /class="sense-zh"/g);
      return want > 0 && got < want ? `有中文的义项 ${want}，渲染 ${got}` : null;
    },
  },
  {
    // it 2026-08-16 那个形状：意语原文导了 89,531 条、接口一直在返回，
    // **组件那一行漏了写**，用户问了才发现。
    name: '🔴 A3 英文定义条数与渲染出来的对不上（it 漏 89,531 条那个形状）',
    hit: (e, h) => {
      const want = e.senses.filter((s: Entry) => s.en).length;
      const got = count(h, /<div class="sense-src" lang="en">/g);
      return want > 0 && got < want ? `有英文定义的义项 ${want}，渲染 ${got}` : null;
    },
  },
  {
    // 🔴 A3 只问「渲染出来没有」，答案一直是"有"，所以它**在构造上看不见这个缺陷**。
    //    这一条问的是不同的问题：**渲染出来的那行，认不认得出是哪种语言**。
    //    fr 2026-08-29 已有同条；en 是第三次同形状。
    name: '🔴 A4 源语言行必须带认得出的语种徽标（EN）',
    hit: (_e, h) => {
      const rows = [...h.matchAll(
        /<div class="sense-src" lang="(\w+)">(?:<span class="sense-src-lang">(\w+)<\/span>)?/g)];
      const bare = rows.filter((m) => !m[2]);
      if (bare.length) return `${bare.length} 行源语言没有语种徽标（lang=${bare[0][1]}）`;
      const wrong = rows.filter((m) => m[2] !== m[1].toUpperCase());
      return wrong.length
        ? `语种徽标与 lang 不符：lang=${wrong[0][1]} 徽标=${wrong[0][2]}` : null;
    },
  },
  {
    // 🔴 缺陷①：整块不分组。`butterfly` 曾连印 8 个 `n`。
    name: '🔴 A5 有词性的义项，页面却一个词性分组标题都没有',
    hit: (e, h) => {
      const posed = new Set(e.senses.map((s: Entry) => s.pos).filter(Boolean));
      return posed.size > 0 && !/class="pos-group-label/.test(h)
        ? `${posed.size} 种词性，HTML 里一个 .pos-group-label 都没有` : null;
    },
  },
  {
    // 🔴 缺陷②：标题印原码。共用的 `posLabel()`（`dict-labels` 的 `POS_LABELS`）
    //    对 en 的 26 种 pos 取值**一个不缺**，所以任何全小写 ASCII 的标题都是没调用它。
    name: '🔴 A6 词性分组标题印的是原码，不是中文',
    hit: (_e, h) => {
      const raw = [...h.matchAll(/<div class="pos-group-label[^"]*">([^<]*)<\/div>/g)]
        .map((m) => m[1]).filter((l) => /^[a-z_/]+$/.test(l));
      return raw.length ? `${raw.length} 个分组标题是原码，例：${raw[0]}` : null;
    },
  },
  {
    // 🔴🔴 缺陷④，**en 独有的量级**：223 万条义项 `pos` 为空。
    //    `giffen` = 「专名 ─ 吉芬」+ 无标题的「低质商品」，读者顺着上一个标题读，
    //    「低质商品」（经济学的吉芬商品）就成了人名。
    //    ⚠️ 这正是同一天在**数据层**修掉的「专名标记传播」（EN_PLAN §15.3）——
    //       展示层不说话就会把它原样重造一遍。
    //    ⚠️ 唯一一组时不要标题：老词典层绝大多数词是这样，
    //       给两百多万条统一印「未标注词性」是加噪声不是加信息 ⇒ 前提里排除。
    name: '🔴 A7 无词性的组无标题地跟在别的组后面（词性会被读成蔓延的）',
    hit: (_e, h) => {
      const groups = [...h.matchAll(
        /<div class="pos-group">(?:<div class="pos-group-label[^"]*">([^<]*)<\/div>)?/g)];
      if (groups.length <= 1) return null;
      const bare = groups.filter((m) => m[1] === undefined);
      return bare.length
        ? `${groups.length} 组里有 ${bare.length} 组没有标题，读者会顺着上一组的词性读下去`
        : null;
    },
  },

  // ───────────────── B. 老词典层兜底 ─────────────────
  {
    // 🔴🔴 `oneself`（freq_rank 7,598）那个形状：三个各自正确的决定合成一个洞 ——
    //    有 1 条义项、但那是没有中文的指针义项 ⇒ 旧判据「有没有义项」把它挡在兜底之外，
    //    而 ECDICT 的「pron. 自己, 亲自」在库里 `published=1`、回归闸 F1 报 0。
    //    **库里查得到、页面上一个中文都没有。**
    name: '🔴 B1 一个中文都没有的词，老词典层的中文没到达读者（oneself 那个形状）',
    hit: (e, h) => {
      if (e.senses.some((s: Entry) => s.zh)) return null;
      if (!e.legacy) return null;
      const first = norm(e.legacy.text.split('\n')[0]).slice(0, 20);
      return first && !text(h).includes(first)
        ? `义项无中文、legacy 有「${first}…」，页面上找不到` : null;
    },
  },
  {
    // ⭐ 反方向：义项已经有中文了就不该再整块印一遍老词典层原文，
    //    否则同一个词两块中文并排，读者读成重复（es 2026-08-07 就是这么并起来的）。
    name: '🔴 B2 义项已有中文，却又整块印了一遍老词典层原文',
    hit: (e, h) => {
      if (!e.senses.some((s: Entry) => s.zh)) return null;
      return /<h3>中文释义<\/h3>|class="sense-detail"/.test(h)
        ? '义项已带中文，页面上还印了老词典层兜底区' : null;
    },
  },

  // ───────────────── C. 尺子（en 独有资产）─────────────────
  {
    // ⚠️ 断言的是**每一个考纲标签都到了页面上**，不是「有没有印过标签」——
    //    后者拿 `.badge tag` 存不存在当判据，而那个类名义项标签也在用，
    //    于是「考纲全丢、义项标签还在」会被判成绿。**判据要指名道姓。**
    name: '🔴 C1 考纲标签有值却没渲染（en 独有，五门都没有）',
    hit: (e, h) => {
      const want = enExamLabels(e.rulers.examTag);
      if (!want.length) return null;
      const t = text(h);
      const miss = want.filter((x) => !t.includes(x));
      return miss.length ? `考纲 ${want.join('/')}，页面上缺 ${miss.join('/')}` : null;
    },
  },
  {
    name: '🔴 C2 柯林斯星级有值却没渲染',
    hit: (e, h) => (e.rulers.collins && !/★/.test(text(h)))
      ? `collins=${e.rulers.collins}，页面上没有星级` : null,
  },

  // ───────────────── D. 音标 / 录音 ─────────────────
  {
    name: '🔴 D1 音标没渲染',
    hit: (e, h) => (e.readings.length > 0 && !text(h).includes(e.readings[0].ipa))
      ? `主读音 /${e.readings[0].ipa}/ 不在页面上` : null,
  },
  {
    // fr 那次 39 万条录音一个用户看不见（`french.ts` 里 `FROM audio` 出现 0 次）。
    // 🔴 2026-09-10 判据跟着组件换：en 从页尾裸 `<audio controls>` 换成共用的
    //    `HumanAudioRow`（内联按钮 `.audio-chip`，播放走 JS `new Audio()`，
    //    **HTML 里根本没有 `<audio>` 标签**）⇒ 旧判据当场恒红。
    //    ⚠️ 期望条数用共用件自己的 `capAudios`（每地区 ≤2、总数 ≤6），
    //       **不在这里另写一份限量规则** —— 两边各写一版，闸迟早与实现漂开。
    name: '🔴 D2 有录音却没渲染',
    hit: (e, h) => {
      const want = capAudios(e.audio as Array<{ url: string | null; region?: string | null }>).length;
      const got = count(h, /class="audio-chip"/g);
      return want > 0 && got < want ? `可渲染录音 ${want} 条，页面只有 ${got} 个` : null;
    },
  },
  {
    // ⭐ 「英美同拼不同读」是 en 的核心价值之一，只印一个等于抹掉一半。
    name: '🔴 D3 多读音只渲染了一个（读者看不到另一读）',
    hit: (e, h) => {
      const uniq = [...new Set(e.readings.map((r: Entry) => r.ipa))] as string[];
      if (uniq.length < 2) return null;
      const t = text(h);
      // 折叠成 `+N` 的算渲染到了（组件有意折叠），但一个 `+N` 都没有就是真丢了
      if (/\+\d/.test(t)) return null;
      const miss = uniq.filter((x) => !t.includes(x));
      return miss.length ? `${uniq.length} 个读音，页面缺 ${miss.length} 个（如 /${miss[0]}/）` : null;
    },
  },

  // ───────────────── E. 例句 ─────────────────
  {
    name: '🔴 E1 例句没渲染',
    hit: (e, h) => {
      const want = e.senses.reduce((n: number, s: Entry) => n + s.examples.length, 0);
      return want > 0 && !/class="example-chip"/.test(h)
        ? `${want} 条例句，HTML 里一条 .example-chip 都没有` : null;
    },
  },
  {
    name: '🔴 E2 例句有中文却没渲染出来',
    hit: (e, h) => {
      const t = text(h);
      for (const s of e.senses) {
        for (const x of s.examples.slice(0, 4)) {
          if (x.zh && !t.includes(norm(x.zh).slice(0, 12))) {
            return `例句「${norm(x.text).slice(0, 24)}…」的中文没渲染`;
          }
        }
      }
      return null;
    },
  },
  {
    // 🔴🔴 **出处在前、引文在后**（2026-09-09 外审改）。外审**三次独立读错**，
    //    都判成「出处混在例句前/顺序混乱/张冠李戴」，因为读者无从判断
    //    那行出处属于上一条还是下一条。维基词典自己的体例也是出处引出引文。
    //    ⭐ 这是**只有渲染成品才发现得了**的缺陷：数据完全正确、`ref` 挂在对的那条上，
    //      任何数据层的闸都永远是绿的 —— 它错的只是**先后**。
    name: '🔴 E3 书证出处落在引文后面（外审三次读错的那个顺序）',
    hit: (_e, h) => {
      for (const li of h.matchAll(/<li>((?:(?!<\/li>)[\s\S])*)<\/li>/g)) {
        const s = li[1];
        const iRef = s.indexOf('<div class="rel-plain">');
        const iEx = s.indexOf('<div class="example-chip">');
        if (iRef >= 0 && iEx >= 0 && iRef > iEx) {
          return `出处排在引文后面：${norm(s.slice(iEx, iEx + 60).replace(/<[^>]*>/g, ' '))}…`;
        }
      }
      return null;
    },
  },
  {
    // `hide_non_examples.py` 藏起来的三族（维护提示 / 占位符 / 关系数据错放）
    // 一条都不许回到页面上。服务层 `WHERE e.hidden = 0` 一旦被改坏，这条会红。
    name: '🔴 E4 藏起来的例句漏到了页面上',
    hit: (e, h) => {
      const rows = db.prepare(
        `SELECT e.text FROM example e JOIN sense s ON s.id=e.sense_id
          WHERE s.word_id = ? AND e.hidden = 1 LIMIT 20`).all(e.id) as Array<{ text: string }>;
      const t = text(h);
      const leak = rows.find((r) => r.text.length > 15 && t.includes(norm(r.text).slice(0, 24)));
      return leak ? `隐藏例句出现在页面上：${norm(leak.text).slice(0, 40)}…` : null;
    },
  },

  // ───────────────── F. 关系 / 变形 / 标签 ─────────────────
  {
    // 🔴 **12.1% 的可见关系挂在词条级**（`sense_id IS NULL`，109,195 条）。
    //    只渲染义项级会让它们一条都到不了读者。
    name: '🔴 F1 词条级关系没渲染（12.1% 的可见关系在这里）',
    hit: (e, h) => (e.relations.length > 0 && !/class="rel-row"/.test(h))
      ? `${e.relations.length} 组词条级关系，HTML 里没有 .rel-row` : null,
  },
  {
    // de C37 那个形状：把英文 kind（`synonym`）直接印给中文读者。
    name: '🔴 F2 关系分组名没有中文（把英文 kind 直接印给读者）',
    hit: (_e, h) => {
      const bad = [...h.matchAll(/class="rel-kind">([^<]*)</g)]
        .map((m) => m[1]).filter((x) => /^[a-z_]+$/.test(x));
      return bad.length ? `${bad.length} 个分组名是英文 kind，例：${bad[0]}` : null;
    },
  },
  {
    name: '🔴 F3 有变形却没有「词形变化」区',
    hit: (e, h) => (e.forms.length > 0 && !/class="exchange-item"/.test(h))
      ? `${e.forms.length} 个变形，HTML 里没有 .exchange-item` : null,
  },
  {
    // 🔴🔴 **两个方向都要守**，这是 en 独有的一条：
    //    · 老词典层的 `topic` 是中文短码（`计`／`医`／`化`），**自解释、正是读者要的**
    //      —— 藏掉它等于把 68 万条已经有的学科信息扔了；
    //    · kaikki 的 `topic` 是上千种英文 slug（`natural-sciences`），没有映射表
    //      ⇒ 有意不显示，印出来就是给中文读者看英文分类名。
    //    ⚠️ 判据用**来源**不用「是不是中文」：后者是形式代理，
    //       源头哪天给了中文 slug 就会误判。
    name: '🔴 F4 topic 标签没按来源分（中文短码被藏 / 英文 slug 被印）',
    hit: (e, h) => {
      const bs = new Set(badges(h));
      for (const s of e.senses) {
        for (const t of s.tags as Array<{ kind: string; value: string }>) {
          if (t.kind !== 'topic') continue;
          if (s.src === 'ecdict' && !bs.has(norm(t.value))) {
            return `老词典层的学科标签「${t.value}」没印给读者`;
          }
          if (s.src !== 'ecdict' && bs.has(norm(t.value))) {
            return `kaikki 的英文 slug「${t.value}」印到了页面上`;
          }
        }
      }
      return null;
    },
  },
];

// ── 取样：**按形状取，不是随机抽** ──
// 随机抽 400 个词，抽到的绝大多数是老词典层的单义项词 —— 那样闸里大半条断言从不触发，
// 「全部通过」就成了假绿。⇒ 每一类形状各取一批，保证每条断言都有活可干。
// ⚠️ SQLite 的 `UNION ALL` 分支里不许带 LIMIT，各查各的。
const LIMIT = Number(process.argv[process.argv.indexOf('--limit') + 1]) || 420;
const PER = Math.ceil(LIMIT / 14);
const arms: Array<[string, string]> = [
  // 🔴 第一支就是 A7 那批：**词性有缺有全**（34,762 个词，0.91%）。
  //    没有这一支，「无词性的组无标题」那条断言一次都不会触发。
  ['词性有缺有全（34,762 那批）',
    `SELECT d.word FROM dict d WHERE d.id IN (
       SELECT word_id FROM sense GROUP BY word_id
        HAVING SUM(pos IS NULL)>0 AND SUM(pos IS NOT NULL)>0) LIMIT ${PER}`],
  ['多词性词（A5/A6 的活）',
    `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      GROUP BY d.id HAVING COUNT(DISTINCT s.pos)>2 LIMIT ${PER}`],
  ['多义项词', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      GROUP BY d.id ORDER BY COUNT(*) DESC LIMIT ${PER}`],
  ['只有老词典层义项（242 万那批）',
    `SELECT d.word FROM dict d JOIN sense_src ss ON ss.word_id=d.id
      WHERE ss.src='ecdict' GROUP BY d.id LIMIT ${PER}`],
  // 🔴 B1 那批：有 legacy、但一条义项中文都没有（`oneself` 的形状）
  ['无义项中文但有 legacy（oneself 那批）',
    `SELECT d.word FROM dict d JOIN legacy_gloss lg ON lg.word_id=d.id AND lg.published=1
      WHERE NOT EXISTS(SELECT 1 FROM sense s JOIN sense_gloss g
                        ON g.sense_id=s.id AND g.lang='zh' WHERE s.word_id=d.id)
      LIMIT ${PER}`],
  ['有英文定义', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' GROUP BY d.id LIMIT ${PER}`],
  ['考纲/柯林斯尺子',
    `SELECT word FROM dict WHERE exam_tag IS NOT NULL AND collins IS NOT NULL LIMIT ${PER}`],
  ['多读音', `SELECT d.word FROM dict d JOIN pronunciation p ON p.word_id=d.id
      GROUP BY d.id HAVING COUNT(DISTINCT p.ipa)>1 LIMIT ${PER}`],
  ['有录音', `SELECT word FROM audio GROUP BY word LIMIT ${PER}`],
  ['例句有中文', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      JOIN example e ON e.sense_id=s.id JOIN example_gloss g ON g.example_id=e.id
      WHERE e.hidden=0 GROUP BY d.id LIMIT ${PER}`],
  // E3 那批：没有这一支，「出处排在引文后面」那条断言就是恒真的
  ['例句有出处 ref', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      JOIN example e ON e.sense_id=s.id
      WHERE e.hidden=0 AND e.ref IS NOT NULL GROUP BY d.id LIMIT ${PER}`],
  ['有隐藏例句', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      JOIN example e ON e.sense_id=s.id WHERE e.hidden=1 GROUP BY d.id LIMIT ${PER}`],
  ['词条级关系', `SELECT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
      WHERE r.sense_id IS NULL AND r.hidden=0 AND r.kind<>'alt_of' GROUP BY d.id LIMIT ${PER}`],
  // F4 两个方向各一支
  ['老词典层学科标签', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      JOIN sense_tag t ON t.sense_id=s.id JOIN sense_src ss ON ss.sense_id=s.id
      WHERE t.kind='topic' AND ss.src='ecdict' GROUP BY d.id LIMIT ${PER}`],
  ['kaikki 学科标签', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      JOIN sense_tag t ON t.sense_id=s.id JOIN sense_src ss ON ss.sense_id=s.id
      WHERE t.kind='topic' AND ss.src<>'ecdict' GROUP BY d.id LIMIT ${PER}`],
];
const words: string[] = [];
const bucket = new Map<string, number>();
for (const [name, sql] of arms) {
  const got = (db.prepare(sql).all() as Array<{ word: string }>).map((r) => r.word);
  bucket.set(name, got.length);
  for (const w of got) if (!words.includes(w)) words.push(w);
}

// 已接受基线：`断言名 → [上限, 理由]`。**超了红。**
// 🔴 与回归闸同一条规矩：锁的是**数字**不是名字（`[[fix-regression-and-gate]]` 第四种机制：
//    pt 那轮 ACCEPT 按名字豁免，基线从 539 涨到 643 一声没吭）。
const ACCEPT: Record<string, [number, string]> = {};

// ── 变异：**一次只造一个缺陷** ──
// 🔴🔴 de/fr 那两个闸把十几种变异**一次性全抹掉**，这有两个坑，我第一版全踩了：
//   ① **互相遮盖**：先把 `<div class="sense-src" lang="en">` 抹成 `class="x"`（造 A3 的缺陷），
//      A4「这行有没有语种徽标」就再也找不到任何一行可查 ⇒ **A4 恒绿，看起来却像合格**。
//   ② **数不出哪条断言没人管**：一起跑只能看到"总共红了几条"，
//      而我要问的是「**每一条断言，是不是都存在一个能打红它的缺陷**」。
// ⇒ 逐个变异单独跑，每个必须至少打红一条；**一条都打不红的变异，和一条谁都打不红的
//   断言，是同一个病**（`[[fix-regression-and-gate]]`：一条永远通过的检查等于没检查）。
// 🔴 每个变异都造一个**真实发生过**的缺陷形状，不许依赖「现在恰好没有」
//   （PITFALLS 一句话版 35：变异会随着项目做完而空转）。
type Mut = [string, (h: string, e: Entry) => string];
const MUTS: Mut[] = [
  ['A1/A2 抹掉中文释义行', (h) => h.replace(/class="sense-zh"/g, 'class="x"')],
  ['A3 整行漏写英文定义（it 89,531 那个形状）',
    (h) => h.replace(/<div class="sense-src" lang="en">[\s\S]*?<\/div>/g, '')],
  ['A4 源语言行没有语种徽标（改前的 .sense-en 裸行）',
    (h) => h.replace(/<span class="sense-src-lang">\w+<\/span>/g, '')],
  ['A5 整块不分组（改前的 entry.senses.map）',
    (h) => h.replace(/<div class="pos-group-label[^"]*">[^<]*<\/div>/g, '')],
  ['A6 分组标题印原码（改前不调 posLabel）',
    (h) => h.replace(/<div class="pos-group-label">[^<]*<\/div>/,
                     '<div class="pos-group-label">n</div>')],
  ['A7 无词性的组不说话（giffen 那个形状）',
    (h) => h.replace(/<div class="pos-group-label pos-group-unset">[^<]*<\/div>/g, '')],
  ['B1 老词典层兜底整块不渲染（oneself 那个形状）',
    (h) => h.replace(/<div class="sense-detail">[\s\S]*?<\/div><\/section>/g, '</section>')],
  ['B2 义项已有中文还再印一遍老词典层（两块中文并排）',
    (h, e) => (e.legacy
      ? h.replace('</article>', `<div class="sense-detail">${e.legacy.text}</div></article>`)
      : h)],
  ['C1 考纲标签没渲染', (h) => h.replace(/<span class="badge tag">[^<]*<\/span>/g, '')],
  ['C2 柯林斯星级没渲染', (h) => h.replace(/★/g, '')],
  ['D1 音标没渲染',
    (h) => h.replace(/class="phonetic-value">[^<]*</g, 'class="phonetic-value">/xx/<')],
  ['D2 录音没渲染', (h) => h.replace(/class="audio-chip"/g, 'class="x"')],
  // 只留第一个读音按钮，并抹掉 `+N` 折叠标记 —— 模拟组件只读 readings[0]
  ['D3 多读音只渲染了一个',
    (h) => h.replace(/<span class="rel-more">\+\d+<\/span>/g, '')
      .replace(/(<button class="phonetic-btn"[\s\S]*?<\/button>)[\s\S]*?(<\/div>)/,
               (_m, first, tail) => first + tail)],
  ['E1 例句没渲染', (h) => h.replace(/class="example-chip"/g, 'class="x"')],
  ['E2 例句中文没渲染', (h) => h.replace(/<div class="example-label">[^<]*<\/div>/g, '')],
  ['E3 出处排在引文后面（改前的顺序）',
    (h) => h.replace(/(<div class="rel-plain">[^<]*<\/div>)(<div class="example-chip">[^<]*<\/div>)/g,
                     '$2$1')],
  ['E4 隐藏的例句漏到页面上（服务层 hidden=0 被改坏）',
    (h, e) => {
      const r = db.prepare(
        `SELECT e.text FROM example e JOIN sense s ON s.id=e.sense_id
          WHERE s.word_id = ? AND e.hidden = 1 AND LENGTH(e.text) > 15 LIMIT 1`)
        .all(e.id) as Array<{ text: string }>;
      return r.length ? h.replace('</article>', `<div>${r[0].text}</div></article>`) : h;
    }],
  ['F1 词条级关系没渲染（12.1% 到不了读者）',
    (h) => h.replace(/class="rel-row"/g, 'class="x"')],
  ['F2 关系分组名印英文 kind（de C37 那个形状）',
    (h) => h.replace(/class="rel-kind">[^<]*</, 'class="rel-kind">synonym<')],
  ['F3 词形变化区没渲染', (h) => h.replace(/class="exchange-item"/g, 'class="x"')],
  ['F4a 老词典层的中文学科标签被藏起来',
    (h, e) => {
      const vs = new Set<string>();
      for (const s of e.senses) {
        if (s.src !== 'ecdict') continue;
        for (const t of s.tags as Array<{ kind: string; value: string }>) {
          if (t.kind === 'topic') vs.add(t.value);
        }
      }
      return [...vs].reduce(
        (acc, v) => acc.replace(new RegExp(`<span class="badge tag">${v}</span>`, 'g'), ''), h);
    }],
  ['F4b kaikki 的英文 slug 印给了读者',
    (h, e) => {
      for (const s of e.senses) {
        if (s.src === 'ecdict') continue;
        for (const t of s.tags as Array<{ kind: string; value: string }>) {
          if (t.kind === 'topic') {
            return h.replace('</article>', `<span class="badge tag">${t.value}</span></article>`);
          }
        }
      }
      return h;
    }],
];

const mutate = process.argv.includes('--mutate');
const fails = new Map<string, string[]>();
const counts = new Map<string, number>();
const pages: Array<[string, Entry, string]> = [];
for (const w of words) {
  const e = svc.getEntry(w) as Entry | null;
  if (!e) continue;
  pages.push([w, e, render(e)]);
}
const n = pages.length;
for (const [w, e, html] of pages) {
  for (const c of CHECKS) {
    const why = c.hit(e, html);
    if (why) {
      const arr = fails.get(c.name) ?? [];
      if (arr.length < 4) arr.push(`${w}：${why}`);
      fails.set(c.name, arr);
      counts.set(c.name, (counts.get(c.name) ?? 0) + 1);
    }
  }
}

console.log('═══ 契约闸（en）：渲染出来的 HTML 对不对 ═══\n');
console.log(`  取样 ${n} 个词（按形状取，不是随机）：\n` +
  [...bucket].map(([k, v]) => `    ${k} ${v}`).join('\n') + '\n');
let red = 0;
for (const c of CHECKS) {
  const arr = fails.get(c.name);
  const cn = counts.get(c.name) ?? 0;
  const acc = ACCEPT[c.name];
  if (!arr) { console.log(`   ✅ ${c.name}`); continue; }
  if (acc && cn <= acc[0]) {
    console.log(`   🟡 ${c.name}  ${cn} 条  ← 已接受（上限 ${acc[0]}）`);
    console.log(`        理由：${acc[1]}`);
    for (const x of arr.slice(0, 2)) console.log(`        ${x}`);
    continue;
  }
  red++;
  console.log(`   🔴 ${c.name}  ${cn} 条${acc ? `  ← 超出已接受上限 ${acc[0]}` : ''}`);
  for (const x of arr) console.log(`        ${x}`);
}
console.log(red ? `\n🔴 ${red} 条红` : `\n✅ 全部通过（${CHECKS.length} 条断言）`);

if (mutate) {
  console.log(`\n═══ 变异：${MUTS.length} 种缺陷各造一次，每种必须至少打红一条 ═══\n`);
  const covered = new Set<string>();
  let dead = 0;
  for (const [mname, f] of MUTS) {
    const got = new Set<string>();
    let hits = 0;
    for (const [, e, html] of pages) {
      let bad: string;
      try { bad = f(html, e); } catch { continue; }
      if (bad === html) continue;           // 这个词身上造不出这种缺陷，跳过
      for (const c of CHECKS) if (c.hit(e, bad)) { got.add(c.name); hits++; }
    }
    if (got.size === 0) { dead++; console.log(`   🔴 ${mname}  —— 没有任何断言逮到它`); }
    else {
      for (const g of got) covered.add(g);
      const tag = [...got].map((x) => x.replace(/^🔴 /, '').split(' ')[0]).join(' ');
      console.log(`   ✅ ${mname}  → ${tag}（${hits} 次命中）`);
    }
  }
  const naked = CHECKS.map((c) => c.name).filter((x) => !covered.has(x));
  console.log(`\n   变异 ${MUTS.length - dead}/${MUTS.length} 有效`
    + ` ｜ 断言 ${CHECKS.length - naked.length}/${CHECKS.length} 有变异守着`);
  // 🔴 「一条谁都打不红的断言」与「一个谁都逮不到的变异」是同一个病，两边都要报。
  for (const x of naked) console.log(`   🔴 没有变异能打红：${x}`);
  process.exit(dead || naked.length ? 1 : 0);
}
process.exit(red ? 1 : 0);
