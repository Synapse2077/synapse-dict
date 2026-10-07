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

  // ══ 🔴🔴 阶段 6e 的产物：**花了 19–21 元买的 75,970 条例句中文译文** ══
  //    `[[aim-for-perfect-not-cheap]]` 的反面风险：钱花了而读者看不见。
  //    这三条是它唯一的读者口径断言 —— 回归闸 P14/P15 只能证明「库里有」。
  { word: 'ăn', name: '🔴🔴 6e：例句的中文译文印出来了',
    hit: (t, e) => {
      const withZh = [...e.examples].filter((x: any) => x.zh);
      if (withZh.length === 0) return '这个词一条带中文译文的例句都没有（6e 没落到它身上？）';
      // 判据**读数据再去页面上找**，不写死字面量 —— 字面量会随源头变而这条断言不该
      const miss = withZh.filter((x: any) => !t.includes(x.zh.split('\n')[0]));
      return miss.length === 0 ? null
        : `${miss.length}/${withZh.length} 条例句的中文译文没印出来，例如 ${miss[0].zh.slice(0, 20)}`;
    } },
  // 🔴 多行例句（诗、歌词、法条）**每一条都必须有中文译文**。
  //    ⚠️ 这一条查的是**数据**而不是像素 —— 多行能不能在页面上**排成多行**由
  //      `.vi-example-zh { white-space: pre-line }` 管，而契约闸读的是
  //      `renderToStaticMarkup` 的纯文本、看不见样式（这正是 55 个 `vi-*` 类名
  //      零规则却一路全绿的原因）⇒ 两边各管一半，都不许缺。
  //
  // 🔴🔴 **这一条原本断言的是「译文行数＝原文行数」，已经换掉了。** 换的理由不是
  //    「它判红了」，而是**它断言的东西在一部分行上不成立**：
  //    实测全库 625 条多行例句里 17 条行数对不上，逐条读下来三类混在一起 ——
  //      · 行数少是**对的**：`Bàn Cổ` 的原文两行是「汉越音转写」＋「同一句的越南语」，
  //        模型给出汉文原文 `史臣吳士連曰…` 一行，正是读者要的
  //      · 真的丢了内容：`uất hận` 9 行→8 行，丢的那行**正含词头**
  //      · 我的清洗判据还漏：`cò` 的首行是**不以年份开头的出处**（`Tú Xương, "Ông Cò…"`）、
  //        末行是**带越南语人名的英译**（`Hà Nam's most honoured…` 里的 `Hà` 带声调符
  //        ⇒ 我的「无越南语标记」判据放过了它）
  //    重译一轮**不收敛**（17 条里 14 条仍对不上）⇒ 根因在数据层不在译文。
  //    ⇒ 行数那笔账锁进回归闸 **P16**（数字＋读法一起锁），记欠账 **W21**；
  //      此处只断言「有没有」—— 这是契约闸能干净断言的那一半。
  { word: 'thối', name: '🔴 6e：多行例句都有中文译文',
    hit: (_t, e) => {
      const multi = [...e.examples].filter((x: any) => x.text.includes('\n'));
      // 🔴 **这条检查自己的闸**：样本词没有多行例句的话它恒绿 ——
      //    第一版挂在 `mai` 上，而六个样本词一条多行例句都没有，于是它永远绿
      //    （`[[permanently-red-gate-masks-real-reds]]` 的镜像）。
      if (multi.length === 0) return '这个词没有多行例句 ⇒ 这条检查空过了，换一个样本词';
      const miss = multi.filter((x: any) => !x.zh);
      return miss.length === 0 ? null
        : `${miss.length}/${multi.length} 条多行例句没有中文译文：${miss[0].text.slice(0, 24)}`;
    } },
  // ── 🔴🔴 W16（2026-10-05）：**本版自己的释义语言不许印在页面上** ──
  //    fr 版维基词典是一部**越→法双语词典**，它的例句一格里装着
  //        `Nắng to : il fait grand soleil.`
  //    法语是**那一版的释义语言**（不是越南语里的法语借词 —— 那些在词源层，
  //    1,115 个词形，早就收齐了）。三语方针说页面上不该有它。
  //    ⇒ 展示层读 `example.text_pub`（出版正文），`example.text` 原样留在证据层。
  //
  // 🔴 **样本词必须选中真的有这一族的词。** `to` 有 7 条（fr 版），`ke` 有 2 条。
  //    昨天刚吃过这个教训：多行例句那条检查挂在 `mai` 上而六个样本词
  //    一条多行例句都没有 ⇒ 它永远绿。⭐ **样本词表决定哪些代码路径被走到。**
  { word: 'to', name: '🔴🔴 W16：页面上的例句正文不许带本版的法语释义',
    hit: (_t, e) => {
      // 这条检查自己的闸：样本词没有这一族 ⇒ 它空过了，当场说出来
      const cut = [...e.examples].filter((x: any) => /\bil fait\b|\bun grand\b|\bjouer\b/.test(x.text));
      if (cut.length > 0) {
        return `${cut.length} 条例句正文里还印着法语释义：${cut[0].text.slice(0, 40)}`;
      }
      // 反向：`to` 这个词**必须**真的有 W16 那一族的例句（否则本条恒绿）
      const heads = [...e.examples].filter((x: any) => /^(Cây|Nắng|Kêu|Quan) to/.test(x.text));
      return heads.length > 0 ? null
        : '`to` 的例句里找不到 W16 那一族（`Cây to`/`Nắng to`…）⇒ 这条检查空过了，换样本词';
    } },
  // 🔴 另一个方向：切完之后**越南语正文一个字都不许少**。
  //    只断言「法语没了」的话，「整条例句都不印」也能满足它 —— 而那正是
  //    W9 刚清掉的那种「为了去掉坏东西把好东西一起删了」。
  { word: 'to', name: '🔴 W16：切掉法语之后越南语正文还在',
    hit: (t, e) => {
      const heads = [...e.examples].filter((x: any) => /^(Cây|Nắng|Kêu|Quan) to/.test(x.text));
      if (heads.length === 0) return '找不到 W16 那一族 ⇒ 这条检查空过了';
      const gone = heads.filter((x: any) => !t.includes(x.text));
      return gone.length === 0 ? null
        : `${gone.length}/${heads.length} 条越南语正文根本没印出来：${gone[0].text}`;
    } },
  // 🔴 中文列也不许粘着法语（6e 是按整格买的译文 ⇒ 它把法语也译了／或原样抄了）
  { word: 'ban', name: '🔴 W16：中文译文里不许漏出法语',
    hit: (_t, e) => {
      const withZh = [...e.examples].filter((x: any) => x.zh);
      if (withZh.length === 0) return '这个词一条带中文译文的例句都没有 ⇒ 空过了';
      const leak = withZh.filter((x: any) => /balle de|jouer au|grossière|deuil/.test(x.zh));
      return leak.length === 0 ? null
        : `${leak.length} 条中文译文里漏着法语：${leak[0].zh.slice(0, 30)}`;
    } },

  // ── 🔴🔴 W24（2026-10-05）：**同一格里不许把同一句例句印两遍** ──
  //    两个版都收了同一句（`to` 页上 `Cây to 大树` 印两遍：fr 版切完 ＋ ko 版本来就是它）。
  // 🔴🔴🔴 **这笔账我第一次报给用户的数错了 3.8 倍，而且量的是另一件事**：
  //    按词形分组得 1,569 组，而展示层把带义项的例句印在**各自的义项下面**、
  //    `sense_id IS NULL` 的印在末尾「例句」区 ⇒ 读者口径只有 417 组。
  //    ⭐ 所以这条契约检查按**页面上真正相邻的那一格**查，而不是按词形 ——
  //      它和数据层 X15、回归闸 P22 用的是同一个口径（三道闸、一个口径）。
  //
  // 🔴 样本词 `bay`（13 条被判重复，全库最多）—— 不是随手挑的「好看的词」：
  //    挑的就是这个缺陷最密集的那个，否则这条检查是白捡的绿
  //    （昨天多行例句那条挂在 `mai` 上而六个样本词一条多行例句都没有）。
  { word: 'bay', name: '🔴🔴 W24：同一格里不许把同一句例句印两遍',
    hit: (_t, e) => {
      // 归一与数据层一致：压空白、去首尾标点、小写
      const nz = (s: string) => s.replace(/\s+/g, ' ').trim()
        .replace(/^[\s.。!！?？:：;；,，、…]+|[\s.。!！?？:：;；,，、…]+$/g, '').toLowerCase();
      const seen = new Map<string, number>();
      for (const x of e.examples as any[]) {
        const k = `${x.senseId ?? 'T'}\u0000${nz(x.text)}`;
        seen.set(k, (seen.get(k) ?? 0) + 1);
      }
      const dup = [...seen.entries()].filter(([, n]) => n > 1);
      if (dup.length > 0) {
        return `${dup.length} 处同一格里印了两遍：${dup[0][0].split('\u0000')[1].slice(0, 30)}`;
      }
      // 这条检查自己的闸：`bay` 必须真的有过重复（否则它恒绿）
      return (e.examples as any[]).length >= 10 ? null
        : '`bay` 的可出版例句不足 10 条 ⇒ 这条检查多半空过了，换样本词';
    } },

  // ── 🔴🔴 W25（2026-10-05）：**同一页上不许印两条中文一模一样的义项** ──
  //    `qua` 页上曾经并排印着「幸存」[en 版] 和「脱离死亡」[vi 版] —— 同一个义项，
  //    两版各描述了一遍。实测 1,252 组 / 1,631 条。
  // 🔴 样本词 `Hòa Bình`（67 条被折，全库最多）—— 又一次：挑**缺陷最密**的那个，
  //    不是挑好看的词。它是个地名，源头在十几个版里重复登记「X 省的一个社/坊」。
  { word: 'Hòa Bình', name: '🔴🔴 W25：同一页上不许印两条中文一模一样的义项',
    hit: (_t, e) => {
      const seen = new Map<string, number>();
      for (const s of e.senses as any[]) {
        if (!s.zh) continue;
        // ⚠️ 分组键要带**词性** —— 同一个中文出现在两个词性下是正当的
        //    （`qua` 当动词和介词都译作「经过」，读者在两个标题下各看一次）。
        //    这与数据层 E17「同一个 entry 内」是同一个口径的两种表达。
        const k = `${s.pos ?? ''}\u0000${s.zh.trim()}`;
        seen.set(k, (seen.get(k) ?? 0) + 1);
      }
      const dup = [...seen.entries()].filter(([, n]) => n > 1);
      if (dup.length > 0) {
        return `${dup.length} 处同词性下印了两条一样的义项：${dup[0][0].split('\u0000')[1].slice(0, 26)}`;
      }
      // 这条检查自己的闸：这个词必须真的有过一堆义项（否则它恒绿）
      return (e.senses as any[]).length >= 5 ? null
        : '`Hòa Bình` 的可出版义项不足 5 条 ⇒ 这条检查多半空过了，换样本词';
    } },
  // 🔴 另一个方向：折叠**不许把例句弄没**。744 条可出版例句挂在被折的义项上，
  //    展示层 `bySense` 只遍历可见义项 ⇒ 不重新指向就在页面上无声消失。
  //    ⚠️ 只断言「没有重复义项」的话，「把带例句的义项整条折掉」也能满足它。
  { word: 'em', name: '🔴 W25：折叠之后例句还在页面上（不许随义项一起消失）',
    hit: (t, e) => {
      const withSense = (e.examples as any[]).filter((x) => x.senseId !== null);
      if (withSense.length === 0) return '`em` 没有挂在义项上的例句 ⇒ 这条检查空过了';
      const gone = withSense.filter((x: any) => !t.includes(x.text.split('\n')[0]));
      return gone.length === 0 ? null
        : `${gone.length}/${withSense.length} 条挂在义项上的例句一个字都没印出来：${gone[0].text.slice(0, 30)}`;
    } },

  // ── 🔴🔴 W29（2026-10-06）：**按方言的播放按钮必须名副其实** ──
  //    用户 2026-10-06：「为什么音标有这么多方框」—— 指的是读音区 5 个带边框的 `▶`。
  //    而真正的缺陷不是「框多」：那 5 个按钮**行为完全一样**（全是
  //    `speak(entry.word, speakLocale)`，而 `speakLocale` 整页一个值 `vi-VN`），
  //    越南语的 Web Speech **做不出方言差异** ⇒ 承诺「听河静音」而播的是通用音。
  //    ⭐ `[[dict-framework-doc]]`：**错比缺更伤权威**。
  //    ⇒ 去掉按方言的 TTS；该方言**真有真人录音**时才给播放器（4,177 组对得上）。
  //
  // 🔴 这一条断言的是「页面上没有按方言的 TTS 按钮」。样本词 `công nhân` 有 **5 个方言行、
  //    0 条录音** —— 正是最该不出现按钮的那种。
  { word: 'công nhân', name: '🔴🔴 W29：没有录音的方言行不许有播放按钮',
    hit: (t, e) => {
      const dialects = new Set((e.pronunciations as any[]).map((p) => p.dialect));
      if (dialects.size < 2) return '`công nhân` 的方言行少于 2 ⇒ 这条检查空过了，换样本词';
      if ((e.audios as any[]).length > 0) return '`công nhân` 现在有录音了 ⇒ 换一个没录音的样本词';
      // `▶` 是那个按方言 TTS 按钮的字面量。它一回来，这条就红。
      const n = (t.match(/▶/g) ?? []).length;
      return n === 0 ? null
        : `读音区有 ${n} 个 ▶ 按钮，而这个词一条录音都没有 —— 它们读的是同一个通用 TTS`;
    } },
  // 🔴 另一个方向：**有录音的方言行必须给得出播放器**。
  //    只断言「没录音时没按钮」的话，「永远不给按钮」也能满足它 —— 那就把 4,177 组
  //    真人录音藏起来了（`[[dont-recast-deliverables-as-junk]]`：录音是珍贵资产）。
  // 🔴🔴 **这一条的第一版判据是错的，而它当场判红把我揪回来了。**
  //    我写的是「在渲染文本里找 `upload.wikimedia.org`」—— 可 `<audio src="…">` 的 URL
  //    在**属性**里，而契约闸给 `hit` 的第一个参数是**去掉标签的可见文本**，
  //    属性当然不在里面 ⇒ 它报「一个播放器都没有」而页面上其实有两个。
  //    ⭐ 与 `css-audit` 文件头记的是同一条：**文本导出器在原理上看不见属性和样式**。
  //    ⇒ 用第三个参数 `html`（原始 HTML）—— 播放器是**元素**不是文字。
  { word: 'và', name: '🔴 W29：有录音的方言行给得出播放器（别把录音藏起来）',
    hit: (_t, e, html) => {
      const matched = (e.audios as any[]).filter(
        (a) => (e.pronunciations as any[]).some((p) => p.dialect === a.dialect));
      if (matched.length === 0) return '`và` 没有方言对得上的录音 ⇒ 这条检查空过了，换样本词';
      // 🔴 **挂在方言行上**才算（`vi-audio-inline`）；落到下面「没标方言」那一区不算，
      //    否则「全部塞进那一区」也能满足这条断言。
      const inline = (html.match(/class="vi-audio vi-audio-inline"/g) ?? []).length;
      const missing = matched.filter((a: any) => !html.includes(a.url));
      if (inline === 0) return `${matched.length} 条方言对得上的录音，方言行上一个播放器都没有`;
      return missing.length === 0 ? null
        : `${missing.length}/${matched.length} 条录音的 url 没出现在页面上：${missing[0].url.slice(0, 50)}`;
    } },

  // 📋 **有意不写**「中文译文不许排进『出处：』那一格」这一条：我写了一版，
  //    **两个分支都 `return null`** —— 一条永远不会红的检查，信号量是零
  //    （恒绿和恒红一样没用：`[[permanently-red-gate-masks-real-reds]]` 的镜像）。
  //    写不出判据的原因是**出处本身就可能含中文书名**（`《翘传》`），
  //    而「这段中文是出处还是译文」在渲染出来的纯文本里分不开。
  //    ⇒ 真正管这件事的是数据层：`example.ref` 与 `example_gloss` 是**两列**，
  //      回归闸 P7 锁带 `ref` 的条数、P15 锁带中文的条数。此处不补假断言。

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
  // ══ 🔴🔴 W15 的后一半（2026-10-05）：指针做成可点链接 ══
  //    ⚠️ **两个方向都要断言**。只断言「可跳的印成了链接」的话，
  //      「把所有指针都印成链接」也能满足它 —— 而那正是 W9 刚清掉的死链
  //      （`nhà` 的「相关」里印着波兰语 `kościół`，`target_id` 解析得上的 0 行）。
  { word: 'UBND', name: '🔴🔴 W15：目标在 `dict` 里的指针印成了可点链接',
    hit: (_x, e, html) => {
      const ok = [...e.pointers].filter((p: any) => p.targetId !== null && p.target);
      if (ok.length === 0) return '这个词没有可跳转的指针 ⇒ 这条检查空过了，换一个样本词';
      const miss = ok.filter((p: any) =>
        !html.includes(`class="vi-link vi-pointer-go"`) || !html.includes(p.target));
      return miss.length === 0 ? null
        : `${miss.length}/${ok.length} 条可跳转的指针没印成链接：${ok[0].target}`;
    } },
  { word: 'ngư', name: '🔴 W15 反面：目标不在 `dict` 里的指针**不许**印成链接',
    hit: (_x, e, html) => {
      const dead = [...e.pointers].filter((p: any) => p.targetId === null);
      if (dead.length === 0) return '这个词没有「跳不动」的指针 ⇒ 这条检查空过了，换一个样本词';
      // 跳不动的那些，它们的目标不许出现在 `vi-pointer-go` 按钮里
      const btn = html.match(/class="vi-link vi-pointer-go"[^>]*>([^<]*)</g) ?? [];
      const bad = dead.filter((p: any) => p.target && btn.some((b) => b.includes(p.target)));
      return bad.length === 0 ? null
        : `${bad.length} 条跳不动的指针被印成了链接（死链）：${bad[0].target}`;
    } },
  // 🔴🔴 **指针区不许印「只是这个词自己的汉字表记」那一类。**
  //    实测修之前读者看到的 17,418 行里 **79.7% 是它** —— 而同一页上方已经有
  //    「汉字表记」区印着同一串字。判据 `criteria.pointer_class()`，派生列 `ptr_class`。
  { word: 'nhất vị', name: '🔴🔴 W15：指针区不许印「只是汉字表记」的行',
    hit: (text, e) => {
      if (e.pointers.length > 0) return null;   // 服务层已经过滤掉了 ⇒ 这一页没有指针区
      return text.includes('这个词形指向') ? '指针区印出来了，而这一页只有汉字表记' : null;
    } },

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
