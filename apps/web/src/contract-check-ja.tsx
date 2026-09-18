/** 展示层契约闸（ja）。2026-09-16（阶段 8）。
 *
 * ═══ 为什么数据层全绿之后还要这一道 ═══
 * `[[it-display-layer-stage8]]`：**接上展示层是独立一道闸。**
 * it 那轮三层数据全绿，真渲染出来立刻看见三个缺陷。
 * fr 那轮库里躺着 39 万条录音，而 `french.ts` 里 `FROM audio` 出现 0 次 ——
 * **"落库成功"证明不了"到达用户"**。
 *
 * ⇒ 本闸把 `JapaneseEntryView` 用 `react-dom/server` 渲染成静态 HTML，
 *   断言全部盯**去标签之后的可见文字**，不盯 DOM 结构。
 *
 * 🔴 **兜底越体面，缺陷越难发现。** 所以断言里有好几条是「这个词必须看得到 X」，
 *    而不是「渲染没报错」。
 *
 * 跑：npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-ja.tsx
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { JapaneseEntryView } from './App';
import { JA_RELATION_LABELS, JA_POS_LABELS, POS_LABELS, relTagLabel, REGISTER_LABELS,
         JA_REGISTER_LABELS, JA_REGION_LABELS, JA_GRAMMAR_LABELS, JA_USAGE_LABELS,
         JA_KANJI_READING_KIND, JA_KANJI_READING_SUBKIND,
         JA_KANJI_READING_ORDER } from '@synapse-dict/dict-labels';

const svc = getService('ja') as unknown as {
  getEntry(w: string): any;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;

function render(entry: unknown): string {
  return renderToStaticMarkup(createElement(JapaneseEntryView, {
    entry, speakLocale: 'ja-JP', onWord: () => {}, speak: () => {},
  } as never));
}

function visibleText(html: string): string {
  return html.replace(/<[^>]*>/g, ' ').replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ');
}

type Check = { word: string; name: string; hit: (t: string, e: any, html: string) => string | null };

const CHECKS: Check[] = [
  // ── 日语特有字段，必须真的印出来 ──
  { word: '痛い', name: '假名读音印出来了', hit: (t) => (t.includes('いたい') ? null : '看不到假名') },
  { word: '痛い', name: '罗马字印出来了', hit: (t) => (t.includes('itai') ? null : '看不到罗马字') },
  { word: '痛い', name: '声调标记印出来了', hit: (t) => (/[ꜜ]/.test(t) ? null : '看不到声调标记') },
  {
    word: '痛い',
    name: '声调型（平板/头高/中高/尾高）印出来了',
    hit: (t) => (/(平板型|头高型|中高型|尾高型)/.test(t) ? null : '看不到声调型'),
  },
  { word: '痛い', name: '例句带振假名（<ruby>）', hit: (_t, _e, html) => (html.includes('<ruby>') ? null : '例句没有振假名') },
  { word: '痛い', name: '例句译文印出来了', hit: (t) => (t.includes('头痛') ? null : '看不到例句中文') },
  { word: '痛い', name: '活用形印出来了', hit: (t) => (t.includes('活用') ? null : '看不到活用') },

  // ── 🔴 2026-09-17 版面骨架（用户看页面说"乱糟糟"那一轮）──
  //    这七条盯的都是**结构**，不是某个词有没有料。它们存在的理由是：
  //    版面这件事**数据层全绿也看不见**，而改回去同样看不见（`[[it-display-layer-stage8]]`）。
  { word: '猫', name: '有「释义」分区标题（七门统一的骨架）', hit: (t) => (t.includes('释义') ? null : '没有释义标题') },
  { word: '桜', name: '构词与语义关系分成两区', hit: (t) => (t.includes('构词') && t.includes('语义关系') ? null : '两区没分开') },
  {
    word: '猫',
    name: '🔴 派生词整页只印一次（原来三条义项各印一份）',
    hit: (t) => {
      const n = (t.match(/派生词/g) || []).length;
      return n === 1 ? null : `印了 ${n} 次`;
    },
  },
  {
    word: '猫',
    name: '🔴 读音区没有空行（汉字词条那条 entry 三样都没有）',
    hit: (_t, _e, html) => (/<div class="ja-reading"><\/div>/.test(html) ? '有空的读音行' : null),
  },
  {
    word: '猫',
    name: '🔴 声调归位到对应读音那一行（不是孤零零一行）',
    // ⚠️ 别拿 `.*?</div>` 去切一行 —— 行内还有嵌套的 `<span>`，第一个 `</div>`
    //    根本不是行尾。按行首标记切段才对（第一版就是这么报的假红）。
    hit: (_t, _e, html) => {
      const row = html.split('<div class="ja-reading">')
        .find((r) => r.includes('>ねこ</span>'));
      return row && row.includes('néꜜkò') ? null : '[néꜜkò] 没跟 ねこ 在同一行';
    },
  },
  {
    word: '猫',
    name: '🔴 同一串 IPA 不许印两遍（中文版与英文版给的是同一串）',
    hit: (t) => {
      const n = (t.match(/ne̞ko̞(?!ma)/g) || []).length;
      return n === 1 ? null : `印了 ${n} 次`;
    },
  },
  {
    word: '痛い',
    name: '🔴 活用表的汉字形与假名形并成一行',
    hit: (t) => (/痛かろ\s*／\s*いたかろ/.test(t) ? null : '没并行，各占一行'),
  },
  // ── 🔴 多读音词的义项分组要标出读音（用户 2026-09-17：「猫的三个 a cat 处理一下」）──
  //    `猫` 有三组义项（汉字 ／ 名词ねこ ／ 名词ねこま），三组的中英文几乎一样。
  //    不标读音，页面上就是「名词 猫 a cat」印三遍 —— 看起来是重复，其实是三个不同的词条。
  {
    word: '猫',
    name: '🔴 多读音词的每组义项标出它的读音',
    hit: (_t, _e, html) => {
      const labels = (html.match(/<div class="pos-group-label">[\s\S]*?<\/div>/g) || []).join('');
      return labels.includes('ねこま') && labels.includes('>ねこ<')
        ? null : '分组标题里看不到 ねこ／ねこま';
    },
  },
  {
    // 🔴 反向的一条：**单读音词不许标**。只查"多读音要标"的话，一个
    //    "保险起见全都标上"的实现同样全绿 —— 而那会给每个词条页加一串噪音。
    word: '痛い',
    name: '🔴 单读音词不许标读音（判据是事实，不是"保险起见都标"）',
    hit: (_t, _e, html) => {
      const labels = (html.match(/<div class="pos-group-label">[\s\S]*?<\/div>/g) || []).join('');
      return labels.includes('pos-group-kana') ? '单读音词也标了读音' : null;
    },
  },

  // ── 🔴 多层 gloss（用户 2026-09-17 那一轮挖出来的）──
  {
    word: '西',
    name: '🔴 伞形标题印成小标题，且兄弟义项**真的挂在同一个组里**',
    hit: (_t, _e, html) => {
      // ⚠️ 第一版只查「页面上有没有这个小标题」—— 那是个**假闸**：
      //    把分组函数改成"每条义项各成一组"之后，每条义项各自印一个小标题，
      //    断言照样绿，而页面正是要修掉的那种平铺。变异验证当场逮到它。
      //    ⇒ 判据必须问「**收进同一个组了没有**」，不是「标题在不在」。
      const groups = html.split('<li class="sense-item ja-umbrella-group">').slice(1)
        .filter((g) => /<div class="ja-umbrella">[^<]*歌舞伎/.test(g));
      if (groups.length !== 1) return `歌舞伎那个伞形组有 ${groups.length} 个（该是 1 个）`;
      const kids = (groups[0].split('</ol>')[0].match(/<li class="sense-item">/g) || []).length;
      return kids >= 2 ? null : `组里只有 ${kids} 条义项 —— 兄弟没被收进来`;
    },
  },
  {
    word: '長谷川',
    name: '🔴 伞形组里的兄弟义项，中文必须各不相同',
    hit: (_t, _e, html) => {
      // ⚠️ 第一版写的是「同一句中文不许印 ≥3 遍」，报「长谷川」印了 4 遍 ——
      //    **判据说的和它逮到的不是一回事**。那 4 条是 `a surname` /
      //    `Hasegawa (a neighborhood of …)` 这种**单层** gloss 被译文压平的，
      //    属于另一条线（JA_PLAN 欠账 14 ②「中文压平」，有意不碰）。
      //    本条闸守的是**本轮改动的交付物**：伞形组里的兄弟不许是同一句话。
      //    拿一个数量阈值当判据，等于让它替另一个缺陷背锅。
      for (const grp of html.split('<li class="sense-item ja-umbrella-group">').slice(1)) {
        const body = grp.split('</ol>')[0];
        const zh = (body.match(/<div class="sense-zh">([^<]*)<\/div>/g) || [])
          .map((x) => x.replace(/<[^>]*>/g, ''));
        if (zh.length > 1 && new Set(zh).size !== zh.length) {
          return `伞形组里有重复的中文：${zh.find((t, i) => zh.indexOf(t) !== i)}`;
        }
      }
      return null;
    },
  },
  {
    // 🔴 反向：伞形**只许当小标题**，不许同时被当成某条义项自己的释义印出来。
    //    真实故障形态是「某条义项没有自己的 definition，伞形顶上来当了它的释义」——
    //    症状与修之前一模一样（同一句话印很多遍），只是换了个来源。
    // ⚠️ **本条目前造不出变异**：全库查过，「有伞形中文、而子义项自己没有中文」的
    //    词形是 **0 个** ⇒ 没有可触发的对象，不是闸写错了。
    //    留着它是因为它守的是**将来**：`sense_gloss` 的三语子查询一旦漏掉
    //    `kind<>'umbrella'`，或者哪天有义项只有伞形没有具体释义，它就会响。
    //    `[[dont-say-source-lacks-what-we-skipped]]`：造不出变异要写明是"没有对象"，
    //    不能含糊成"验证过了"。
    word: '西',
    name: '🔴 伞形不许同时当成义项释义印一遍（当前无可触发对象，守将来）',
    hit: (_t, _e, html) => {
      for (const grp of html.split('<li class="sense-item ja-umbrella-group">').slice(1)) {
        const u = (grp.match(/<div class="ja-umbrella">([^<]*)<\/div>/) || [])[1];
        const body = grp.split('</ol>')[0];
        if (u && body.includes(`<div class="sense-zh">${u}</div>`)) {
          return `伞形「${u}」同时被当成子义项的释义印了出来`;
        }
      }
      return null;
    },
  },

  // ── 🔴 三语释义的标识与顺序（用户 2026-09-17：「前面是否和其他语言一样加一个 en 标识」）──
  {
    word: '勉強',
    name: '🔴 英文释义带 EN 标识（与 it/de 同一套 .sense-src 画法）',
    hit: (_t, _e, html) => (/<div class="sense-src" lang="en"><span class="sense-src-lang">EN<\/span>/.test(html)
      ? null : '英文释义还是裸的 .sense-en，没有 EN 徽标'),
  },
  {
    word: 'ありがとう',
    name: '🔴 顺序：中文 → EN → JA（与 it/de 一致）',
    hit: (_t, _e, html) => {
      const seg = html.split('<li class="sense-item">')[1] ?? '';
      const zh = seg.indexOf('class="sense-zh"');
      const en = seg.indexOf('lang="en"');
      const ja = seg.indexOf('lang="ja"');
      if (zh < 0 || en < 0 || ja < 0) return `这条义项三语不全（zh${zh} en${en} ja${ja}）`;
      return zh < en && en < ja ? null : `顺序不对：zh@${zh} en@${en} ja@${ja}`;
    },
  },
  {
    // 🔴 **没有中文时英文必须顶上来当主释义**（1,830 条 / 0.6%）。
    //    只查"英文有没有 EN 徽标"的话，一个"英文一律缩成带徽标的补充行"的实现照样全绿
    //    —— 而那会让这 1,830 条义项在页面上**整个没有释义**。
    //    判据要覆盖它要描述的**两半**（`[[criteria-narrower-than-you-think]]`）。
    // ⚠️ 取样词是**查出来的不是拍的**：`の` 是全库频次最高的、且确实有一条
    //    「没有中文只有英文」的义项。第一版我随手写了 `𩸽`，它根本没有这种义项 ⇒
    //    `hit` 直接 return null，**断言永远绿**。造不出触发对象的断言不是断言。
    word: 'の',
    name: '🔴 没有中文的义项，英文顶上来当主释义（不许缩成补充行）',
    hit: (_t, e: any, html) => {
      const s0 = (e.senses || []).find((x: any) => !x.zh && x.en);
      if (!s0) return '取样词已经没有「无中文」的义项了 —— 换一个词，别让这条闸空转';
      return html.includes(`<div class="sense-zh">${s0.en}</div>`)
        ? null : '没有中文的义项，英文被缩成了补充行 —— 这一条义项等于没有释义';
    },
  },

  // ── 🔴 例句块要有视觉分隔（用户 2026-09-17：「这四行应该怎样展示合理呢」）──
  {
    word: '勉強',
    name: '🔴 每条例句挂共用的 .example-item（左竖线＋缩进），不许是裸 <li>',
    hit: (_t, _e, html) => {
      const bare = (html.match(/<ul class="example-list">\s*<li>/g) || []).length
        + (html.match(/<\/li><li>(?=<div class="example-)/g) || []).length;
      return bare ? `有 ${bare} 个没挂 class 的例句 <li>` : null;
    },
  },
  {
    // 🔴 一条**层级**断言：例句的三行必须在同一个 li 里，而释义不在。
    //    只查"有没有 class"挡不住「把 class 挂错到别的元素上」。
    word: '勉強',
    name: '🔴 例句正文/罗马字/译文在同一个 .example-item 里，释义不在',
    hit: (_t, _e, html) => {
      const item = html.split('<li class="example-item">')[1]?.split('</li>')[0] ?? '';
      const has = (c: string) => item.includes(`class="${c}"`);
      if (!has('example-text') || !has('example-roman') || !has('example-zh')) {
        return '例句三行没在同一个块里';
      }
      return has('sense-zh') || has('sense-en') ? '释义被卷进了例句块' : null;
    },
  },

  // ── 🔴 朗读按钮的位置（用户 2026-09-17 指出「发音按钮在单词的右边不合适」）──
  {
    word: '勉強',
    name: '🔴 词头里不许有朗读按钮（它属于读音，不属于词形）',
    hit: (_t, _e, html) => {
      const h2 = (html.match(/<h2 class="entry-word">[\s\S]*?<\/h2>/) || [''])[0];
      return /<button|🔊/.test(h2) ? '词头里还有按钮' : null;
    },
  },
  {
    word: '猫',
    name: '🔴 每个有假名的读音行各带一个朗读按钮（多读音要能分别听）',
    hit: (_t, _e, html) => {
      const rows = html.split('<div class="ja-reading">').slice(1)
        .filter((r) => r.includes('class="ja-kana"'));
      const bad = rows.filter((r) => !r.includes('class="ja-speak"'));
      return bad.length ? `${bad.length} 行有假名却没有按钮` : null;
    },
  },
  {
    word: '猫',
    name: '朗读按钮读的是**该行的假名**不是词头',
    // ⚠️ 不去匹配提示语的**字面**（"播放发音：ねこま"）—— 那样改一个字（比如给
    //    按钮标上「合成音」）就红，而按钮读的还是对的。判据换成：**逐行**要求按钮的
    //    可访问文本里出现的是本行那个假名。
    hit: (_t, _e, html) => {
      const rows = html.split('<div class="ja-reading">').slice(1);
      const bad: string[] = [];
      let checked = 0;
      for (const r of rows) {
        const kana = (r.match(/<span class="ja-kana">([^<]+)<\/span>/) || [])[1];
        const btn = (r.match(/<button class="ja-speak"[^>]*>/) || [])[0];
        if (!kana || !btn) continue;
        checked += 1;
        if (!btn.includes(kana)) bad.push(kana);
      }
      if (checked < 2) return '猫 的读音行少于 2 行，这条断言没有对象了';
      return bad.length ? `${bad.length} 个按钮没带本行假名（${bad.join('/')}）` : null;
    },
  },
  {
    // 🔴 这一条盯的是**兜底路径**：64,487 个词元一条读音行都没有。
    //    把按钮整个挂到读音行上，等于这些页面再也读不出声 —— 而它们**没有一条
    //    断言会红**，因为上面那两条查的是"有读音行的词"。
    //    `[[criteria-narrower-than-you-think]]`：判据只覆盖了它要描述的一半。
    word: 'に対して',
    name: '🔴 没有读音行的词仍有朗读入口（兜底药丸）',
    hit: (_t, _e, html) => (/class="phonetic-btn"/.test(html) ? null
      : '既没有读音行也没有兜底按钮 —— 这一页读不出声'),
  },

  // ── 🔴 数据闸的**读者口径**复查 ──
  //    `ja/fixes/fix_relation_kind_and_targets.py` 自己的闸查的是库里还有没有残渣；
  //    这一条查的是**渲染出来的页面上**还有没有。两者不是同一个问题：
  //    `[[correct-steps-can-compose-a-hole]]` —— 闸至少要有一条是读者口径。
  {
    word: '桜',
    name: '关系目标不带振假名括号残渣（桜蔭(おういん)会(かい)）',
    hit: (t) => (/[一-鿿]\([ぁ-ゖ]+\)/.test(t) ? '关系区还有 汉字(假名) 残渣' : null),
  },
  {
    word: '猫',
    name: '🔴 ja 版「熟語」不许再印成「谚语」',
    hit: (t) => (t.includes('谚语') ? '猫 页上出现了「谚语」—— ja 版熟語又被当成谚语了' : null),
  },

  // ── 🔴 词性名必须走日语覆盖层 ──
  {
    word: '青',
    name: '词性名不许印英文码（kanji/kana/part…）',
    hit: (t) => {
      const bad = ['kanji', 'kana', 'romaji', 'adnom', 'counter', 'unknown']
        .filter((c) => new RegExp(`(^|\\s)${c}(\\s|$)`).test(t));
      return bad.length ? `印了英文码：${bad.join(', ')}` : null;
    },
  },
  { word: '青', name: '汉字词性印成「汉字」', hit: (t) => (t.includes('汉字') ? null : '没印出「汉字」') },

  // ── 活用类（欠账 4，2026-09-16 还的）──
  {
    word: '保護',
    name: '活用类印出来了（サ行变格活用）',
    hit: (t) => (t.includes('サ行变格活用') ? null : '看不到活用类'),
  },
  {
    // 🔴 原来这一条查的是 `歩く` 要印「五段活用・カ行」—— **做不到，而且不该硬做**。
    //    日语版把词条挂在**假名词头**（`あるく`）下，`歩く` 拿不到活用类。
    //    我试过按读音传播并加「读音唯一对应一个活用类」当保险，那个保险是假的：
    //    `犬[いぬ]` 会拿到动词 `去ぬ` 的 `godan-na`。⇒ 放弃传播，见 `fill_vclass` 文件头。
    //    ⇒ 断言改成查**假名词头本身**印不印得出来。
    word: 'あるく',
    name: '五段活用的行印出来了（五段活用・カ行）',
    hit: (t) => (/五段活用・カ行/.test(t) ? null : '看不到「五段活用・カ行」'),
  },
  {
    word: '保護',
    name: '🔴 活用类不许印在每一行变形上',
    hit: (t) => {
      // 它应该只出现一次（词头旁边的徽标），不是每条活用都拖一个
      const n = (t.match(/サ行变格活用/g) || []).length;
      return n === 1 ? null : `出现了 ${n} 次（词元属性印成了每个形的属性）`;
    },
  },

  // ── 🔴🔴 异体 vs 同音，措辞必须跟着判据走 ──
  {
    word: 'いぬ',
    name: '同音索引页印成「同音词」而不是「异体写法」',
    hit: (t) => {
      if (!t.includes('同音词')) return '没印出「同音词」';
      // 它没有 alt_of，所以「异体写法」这四个字一个都不该出现
      return t.includes('异体写法') ? '把同音索引页印成了异体写法（数据层拒绝做的断言）' : null;
    },
  },
  {
    word: 'いぬ',
    name: '多个原形全部印出来，不许只印一个',
    hit: (t) => {
      const have = ['去ぬ', '寝ぬ', '射る', '率寝', '鋳る'].filter((w) => t.includes(w));
      return have.length >= 5 ? null : `只印出 ${have.length}/5 个原形：${have.join('、')}`;
    },
  },
  {
    word: 'あいする',
    name: '异表记词形不是空白页（指针必须可见）',
    hit: (t) => (t.includes('愛する') ? null : '跳转页上看不到目标词 —— 读者点进来是空白'),
  },

  // ── 🔴 2026-09-18 活用形页（用户点开 `食べる` 活用表落到 `食べれます` 那一轮）──
  {
    word: '食べれます',
    name: '🔴 词头是裸词形，不带源头单元格里的 [罗马字]',
    // 英文版活用表把词形和转写写在同一个单元格里（`食べれます [taberemasu]`），
    // 阶段 2 原样收进了 `dict.word` ⇒ 词头、药丸两处都印着方括号，TTS 也跟着念。
    hit: (_t, e) => (/\[[^\]]+\]$/.test(e.word) ? `词头仍是「${e.word}」` : null),
  },
  {
    word: '食べれます',
    name: '🔴 读音行缺席时，药丸里印的不是词头的复制品',
    // 这一条盯的是**版面**：兜底药丸回答的是"它怎么念"，印成与正上方词头一字不差
    // 就等于同一个词印了两遍 —— 用户看到的正是这个。
    hit: (_t, e, html) => {
      const v = (html.match(/<span class="phonetic-value">([^<]*)<\/span>/) || [])[1];
      if (!v) return '没有兜底药丸 —— 这个词形一个朗读入口都没有';
      return v === e.word ? `药丸里又是词头本身（${v}）` : null;
    },
  },
  {
    word: '食べられます',
    name: '🔴 一个词形对同一原形的多个语法标签要全印出来',
    // `食べられます` 对 `食べる` 同时是**被动敬体**和**可能敬体**。服务层原来
    // `MIN(label_zh)` 只留一个 ⇒ 页面上断言"它只是可能敬体"。全库 9.0% 的
    // (词形, 原形) 组合有多个标签，最多的 5 个。
    hit: (t, e) => {
      const want = new Set<string>();
      for (const b of e.bases) for (const l of b.labels) want.add(l);
      if (want.size < 2) return '这个词形只有一个语法标签了 —— 这条断言没有对象，先回源看';
      const miss = [...want].filter((l) => !t.includes(l));
      return miss.length ? `漏印：${miss.join('、')}` : null;
    },
  },
  {
    word: '食べれます',
    name: '🔴 原形与语法标签之间有结构（不是黏成一串文字）',
    hit: (_t, _e, html) => (html.includes('class="ja-base-label"') ? null
      : '语法标签没有自己的元素 —— 与原形黏在一起，读者读不出断句'),
  },

  // ── 通用：不许漏出未映射的原始码 ──
  {
    word: '表現',
    name: '不许漏出未映射的关系码',
    hit: (t) => {
      const bad = ['synonym', 'antonym', 'derived', 'related', 'coordinate', 'see_also', 'alt_of']
        .filter((c) => t.includes(c));
      return bad.length ? `印了原始关系码：${bad.join(', ')}` : null;
    },
  },
  // 🔴🔴 **上面那条对「空标签」结构性失明。**
  //    `relTagLabel()` 对 `related`/`synonym`/`antonym` 返回的是**空字符串** ——
  //    页面上是个空的小标签，既不是英文码也不是中文，比印英文码更难发现。
  //    实测 13 个 kind 里，上面那条只逮到 1 个（`derived`）：
  //      8 个原样返回英文码、3 个返回空串、2 个已被 ja 覆盖层接住。
  //    ⇒ 直接去**库里取全部 kind** 逐个问有没有非空中文名 ——
  //      判据锚在数据上，源头将来多一个 kind 它会自己响（`[[external-anchor-gates]]`）。
  {
    word: '表現',
    name: '库里每个关系 kind 都有非空中文名',
    hit: () => {
      const kinds = (db.prepare('SELECT DISTINCT kind FROM sense_relation')
        .all() as Array<{ kind: string }>).map((r) => r.kind);
      const bad = kinds.filter((k) => {
        const v = JA_RELATION_LABELS[k] ?? relTagLabel(k);
        return !v || v === k;
      });
      return bad.length ? `没有中文名（空标签或原码）：${bad.join(', ')}` : null;
    },
  },
  // ── 汉字音訓読み区（阶段 4c，2026-09-18）──
  // 🔴 数据层七条回核 + 变异 8/8 全绿的东西，**渲染出来仍然是独立一道闸**
  //    （`[[it-display-layer-stage8]]`：三层数据全绿，真渲染出来立刻看见缺陷）。
  {
    word: '青',
    name: '🔴 汉字条目印出字音区（音訓読み）',
    hit: (_t, _e, html) => (html.includes('class="ja-kanji-readings"') ? null
      : '整个字音区没渲染 —— 汉字页最要紧的那一层读者看不到'),
  },
  {
    word: '青',
    name: '音读/训读分区印出来，且不是英文码',
    hit: (t) => {
      if (/\b(on|kun|nanori)\b/.test(t)) return '印出了原始 kind 码';
      const miss = ['音读', '训读'].filter((x) => !t.includes(x));
      return miss.length ? `缺分区标签：${miss.join('、')}` : null;
    },
  },
  {
    word: '青',
    name: '呉音/漢音/唐音的细分标注印出来了',
    hit: (t) => {
      const miss = ['吴音', '汉音', '唐音'].filter((x) => !t.includes(x));
      return miss.length ? `缺细分标注：${miss.join('、')}` : null;
    },
  },
  // 🔴 送假名那条是这组里最要紧的：`あお-い` 里只有 `あお` 是这个字的读音。
  //    印成一整串，读者会以为 `青` 读作 `あおい`。
  {
    word: '生',
    name: '🔴 送假名与字音分开成两个元素（い-きる 的 きる 不是字音）',
    hit: (_t, _e, html) => {
      if (!html.includes('class="ja-kr-okuri"')) {
        return '送假名没有自己的元素 —— 与字音黏成一串，读者会把送假名当成字的读音';
      }
      return html.includes('-きる') ? '连字符原样印到了页面上（应当用结构表达断点）' : null;
    },
  },
  {
    word: '生',
    name: '朗读按钮读的是字音不是整串（い-きる 读 い）',
    hit: (_t, _e, html) => (/title="播放发音（合成音）：い"/.test(html) ? null
      : '按钮没有按字音给 —— 读整串等于把送假名念成字音的一部分'),
  },
  // 🔴 与关系 kind 同一个形状：判据锚在**库里实际出现的值**上，
  //    源头将来多一个分类（比如 `so-on` 宋音）它会自己响，不用谁记得来改这里。
  {
    word: '青',
    name: '库里每个音训读 kind 都有非空中文名',
    hit: () => {
      const kinds = (db.prepare('SELECT DISTINCT kind FROM kanji_reading')
        .all() as Array<{ kind: string }>).map((r) => r.kind);
      const bad = kinds.filter((k) => {
        const v = JA_KANJI_READING_KIND[k];
        return !v || v === k;
      });
      if (bad.length) return `没有中文名（空标签或原码）：${bad.join(', ')}`;
      // 分区顺序表漏一个 ⇒ 那一档会被整个吃掉（`JaKanjiReadings` 有兜底分组，
      // 但兜底印的是原码 —— 闸要在它退到兜底之前就响）
      const off = kinds.filter((k) => !JA_KANJI_READING_ORDER.includes(k));
      return off.length ? `不在分区顺序表里：${off.join(', ')}` : null;
    },
  },
  {
    word: '青',
    name: '库里每个音训读 subkind 都有非空中文名',
    hit: () => {
      const subs = (db.prepare(
        'SELECT DISTINCT subkind FROM kanji_reading WHERE subkind IS NOT NULL')
        .all() as Array<{ subkind: string }>).map((r) => r.subkind);
      const bad = subs.filter((s) => {
        const v = JA_KANJI_READING_SUBKIND[s];
        return !v || v === s;
      });
      return bad.length ? `没有中文名：${bad.join(', ')}` : null;
    },
  },
  // ⚠️ 反向：**普通词不许印字音区**。这一层是字的属性，
  //    印在 `勉強` 这种多字词上就是在说「这个词有音读训读」，那是错的。
  {
    word: '勉強',
    name: '🔴 普通词不印字音区（这是字的属性不是词的）',
    hit: (_t, _e, html) => (html.includes('class="ja-kanji-readings"')
      ? '多字词印出了字音区 —— 音訓読み是单字的属性' : null),
  },

  // ── 义项标签 sense_tag（阶段 1d，2026-09-18）──
  // 🔴 ja 是七门里最后一个建这张表的，而 it 那门的教训是**数据进了库不等于读者看得见**
  //    （18,818 条及物性标签在库里躺了一个月，`App.tsx` 零个引用）⇒ 断言打在渲染结果上。
  {
    word: '子',
    name: '🔴 义项标签印出来了（sense_tag 接上页面）',
    hit: (_t, _e, html) => (html.includes('class="sense-chip') ? null
      : '一个标签片都没渲染 —— 60,469 条标签读者看不见'),
  },
  {
    word: '子',
    name: '标签片不许印英文码',
    // 🔴 **判据只看 chip 元素内部，不看整页可见文字。** 第一版查的是整页，
    //    报「印了原始标签码：honorific」—— 而那个 `honorific` 是**英文释义正文**
    //    里的词（`EN honorific for an adult man`），标签本身印的是「尊敬语」。
    //    判据比它要描述的东西宽（`[[criteria-narrower-than-you-think]]`），
    //    而且宽的方向恰好落在同一个语义场上，看报错信息完全像是真的。
    hit: (_t, _e, html) => {
      const chips = (html.match(/<span class="sense-chip [^"]*">([^<]*)<\/span>/g) || [])
        .map((x) => x.replace(/<[^>]*>/g, ''));
      const bad = chips.filter((c) => /^[A-Za-z][A-Za-z-]*$/.test(c));
      return bad.length ? `标签片里印了原始码：${[...new Set(bad)].join(', ')}` : null;
    },
  },
  // 🔴 与关系 kind / 音训读同一个形状：判据锚在**库里实际出现的值**上。
  //    封闭集合（register/region/grammar/usage）漏一个就是活儿没干完。
  {
    word: '子',
    name: '库里每个 register/region/grammar/usage 取值都有非空中文名',
    hit: () => {
      const T: Record<string, Record<string, string>> = {
        register: { ...REGISTER_LABELS, ...JA_REGISTER_LABELS },
        region: JA_REGION_LABELS, grammar: JA_GRAMMAR_LABELS, usage: JA_USAGE_LABELS,
      };
      const bad: string[] = [];
      for (const kind of Object.keys(T)) {
        for (const r of db.prepare(
          'SELECT DISTINCT value FROM sense_tag WHERE kind=?').all(kind) as Array<{ value: string }>) {
          const v = T[kind][r.value];
          if (!v || v === r.value) bad.push(`${kind}/${r.value}`);
        }
      }
      return bad.length ? `没有中文名：${bad.slice(0, 12).join(', ')}` : null;
    },
  },
  // 🔴 日语敬语三分：全局表把 honorific 译「敬称」、polite 译「礼貌」，
  //    对日语都不准 —— 那是语法范畴不是语气强弱。覆盖层必须真的生效。
  {
    word: '子',
    name: '🔴 敬语三分走 ja 覆盖层（尊敬语/谦让语/丁宁语，不是「敬称/礼貌」）',
    hit: () => {
      const bad: string[] = [];
      for (const [code, want] of [['honorific', '尊敬语'], ['humble', '谦让语'],
        ['polite', '丁宁语']] as const) {
        const got = { ...REGISTER_LABELS, ...JA_REGISTER_LABELS }[code];
        if (got !== want) bad.push(`${code}→${got}`);
      }
      return bad.length ? `覆盖层没生效：${bad.join(', ')}` : null;
    },
  },
  // ⚠️ 与词头徽标互补：`suru` 379 条里 295 条词头已印サ変活用类，两处说同一件事。
  {
    word: '勉強',
    name: '词头已印サ変活用类时，义项不再重复印「する动词」',
    hit: (t, e) => {
      const ja = e as { vclass: string | null };
      if (!ja.vclass || !ja.vclass.startsWith('sa-')) return null;
      return t.includes('する动词') ? '与词头的活用类徽标重复' : null;
    },
  },
  // 🔴 反向：及物性**不能**跟着一起去重 —— `vclass` 说的是「怎么活用」，
  //    不说「带不带宾语」。照抄 it 那门（意语词头直接标 t/i）会吞掉 703 条。
  {
    word: '開く',
    name: '🔴 及物性标签照印（vclass 不说及物性，不许跟着 suru 一起去重）',
    hit: (t, e) => {
      const ja = e as { senses: Array<{ grammar: string[] }> };
      const has = ja.senses.some((s) => s.grammar.includes('intransitive')
        || s.grammar.includes('transitive'));
      if (!has) return null;
      return /自动词|他动词/.test(t) ? null : '库里有及物性标签，页面上一个都没印';
    },
  },

  // 同样的形状，词性那边也查一遍：**库里每个 pos 都得有非空中文名**。
  {
    word: '表現',
    name: '库里每个词性码都有非空中文名',
    hit: () => {
      const codes = new Set<string>();
      for (const r of db.prepare('SELECT DISTINCT pos FROM entry WHERE pos IS NOT NULL')
        .all() as Array<{ pos: string }>) {
        for (const c of r.pos.split('/')) codes.add(c);
      }
      const bad = [...codes].filter((c) => {
        const v = JA_POS_LABELS[c] ?? POS_LABELS[c];
        return !v || v === c;
      });
      return bad.length ? `没有中文名：${bad.join(', ')}` : null;
    },
  },
];

let red = 0;
const cache = new Map<string, any>();
for (const c of CHECKS) {
  let e = cache.get(c.word);
  if (e === undefined) { e = svc.getEntry(c.word); cache.set(c.word, e); }
  if (!e) { console.log(`   🔴 ${c.name}  —— 词条 ${c.word} 查不到`); red += 1; continue; }
  let html: string;
  try {
    html = render(e);
  } catch (err) {
    console.log(`   🔴 ${c.name}  —— 渲染抛异常：${(err as Error).message.slice(0, 80)}`);
    red += 1;
    continue;
  }
  const why = c.hit(visibleText(html), e, html);
  if (why) red += 1;
  console.log(`   ${why ? '🔴' : '✅'} ${c.word.padEnd(5)} ${c.name}${why ? `  —— ${why}` : ''}`);
}
console.log(red ? `\n🔴 ${red} 条不合格` : '\n✅ 日语展示层契约全部通过');
process.exit(red ? 1 : 0);
