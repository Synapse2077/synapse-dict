// ============================================================================
// 越南语专属映射表。2026-10-03（阶段 9）。
//
// ═══ ⚠️ 覆盖层只放**确实不一样的** ═══
// 照 `[[dict-labels-package]]`：一样的一律走全局 `POS_LABELS` / `REL_LABELS`，
// 这个包不是"把所有标签抄一遍"的地方。实测 vi 的 27 个 `entry.pos` 里
// **全局表已经给对了 22 个**，真正要写的只有下面 8 行（5 个缺失 ＋ 3 个同名异义）。
//
// ═══ 🔴🔴 键是 `entry.pos`，**不是 `dict.pos`** ═══
// 实测两列两套值域，差距比 ko 那次更大：
//     `entry.pos`  **27 种**     noun / verb / romanization / combining_form …  ← 展示层读这一列
//     `dict.pos`   **494 种**    noun/unknown、verb/noun、noun/adj …（6,749 行带斜杠）
// ko 栽过的那一跤原话：「映射表照 `pos_raw` 写、展示层读 `pos`，
// **双方一致报全绿而每个徽标都是空的**」。⇒ 覆盖闸查的那一列必须是展示层 SELECT 的那一列
// （`[[correct-steps-can-compose-a-hole]]`）。
//
// ═══ ⚠️ 每一行都回库看过实际内容才定的词，而**证据推翻了我两个猜测** ═══
// 写之前我按名字猜了三个标签，回库抽样之后两个是错的 —— 记在各行注释里。
// `[[criteria-narrower-than-you-think]]`：先读样本再定词。
// ============================================================================

/**
 * 词性覆盖层：越南语与全局 `POS_LABELS` **不同的那些**。查不到就落回全局表。
 *
 * ⚠️ 返回 `''` 与返回 `undefined` 是两件事：
 *   `''`        ＝ **有意不印** —— 调用方要把它与 undefined 分开处理
 *   `undefined` ＝ 本层没有意见 ⇒ 落回 `POS_LABELS`
 */
export const VI_POS_LABELS: Record<string, string> = {
  // ── ① 全局表**根本没有**这 5 个键（实测 `POS_LABELS[code] === undefined`）──

  // 773 条。🔴 **我先猜的是「拉丁转写」，错了。** 回证据层读原文：
  //    `Sino-Vietnamese reading of 衣`／`Âm đọc Hán-Việt của 適`／`安的漢越詞讀音`
  //    —— 三种语言写法合计 **1,193 / 1,203 = 99.2%**。它不是"转写"，
  //    是**某个汉字的汉越读音**（这个词形读作什么汉字）。剩 10 条是源头把
  //    `Northern Vietnam form of` 之类错标成了 romanization。
  romanization: '汉越读音',

  // 364 条。全局表有 `prov` 而 vi 存的是 `proverb`，**不是同一个键** ⇒ 要写。
  //    样本：`nhập gia tuỳ tục, nhập giang tuỳ khúc`（入乡随俗）
  proverb: '谚语',

  // 104 条。🔴 **我先猜的是「叠音成分」，对 30% 是错的。**
  //    162 条中文释义里只有 113 条带「叠音」；剩下 49 条是
  //    `thư` 仅用于 tiểu thư／`rọi` 仅用于 ba rọi（五花肉）／`nghễ` 与 ngạo nghễ 连用
  //    —— 本质是**只出现在某个固定组合里的黏着成分**，与是不是叠音无关。
  combining_form: '固定搭配成分',

  // 92 条。越南语的 loại từ（`con` 用于动物／`cái` 用于无生命物／`người` 用于人）。
  //    ⚠️ 与 `noun_classifier` 那张**表**不是一回事：这里是「这个词形本身是量词」，
  //      那张表是「这个名词配哪些量词」。
  classifier: '量词',
  // 1 条（`sub`，YouTube 订阅者的量词）。与 `classifier` 同义，源头用了两个名字。
  counter: '量词',

  // ── ② 全局表有、但**越南语里指的不是同一个东西**，必须覆盖 ──

  // 125 条。🔴 全局表写「小品词」—— 那是意语的 `sì`/`no`。
  //    越南语的是**句末语气词**：`ha`（是吗？对吧？）／`ta`（加强疑问、表惊讶）。
  //    它是越南语句法的核心成分，不是"小品词"。与 ja/ko 覆盖 `part` 同一个理由：
  //    改全局表会让意语跟着变。
  particle: '语气词',

  // 4 条。🔴 全局表写「词缀」，而这 4 条的中文释义是**单个汉字**：伤／洋／羊／母。
  //    `mẫu`(母) 不是词缀。⭐ **第二个独立信号同意**：4/4 的 `entry.etym_type`
  //    都是 `sino_vietnamese` ⇒ 它们是汉越语素（黏着的汉字词根）。
  //    `[[verify-before-claiming-confirmed]]`：两个独立信号一致才收。
  affix: '汉越语素',

  // ── ③ 全局表写「未标注」，vi 有意印成**什么都不印** ──
  // 21,174 条 ＝ 全部 entry 的 **27.7%**。在四分之一的页面上挂一枚「未标注」徽标
  // 是噪声，而**没有徽标本身已经传达了同一件事**。
  // ⚠️ 这是有意的，不是漏填 —— 所以写成 `''` 而不是删掉这一行，
  //   否则下一个人会落回全局表、把「未标注」印出来。
  unknown: '',
};

/**
 * 关系类型覆盖层：越南语比全局 `REL_LABELS` 多出来的 7 种。
 *
 * 🔴🔴 **`paronym` 是这里最该读的一行**（17,637 行，第四大的 kind）。
 */
export const VI_RELATION_LABELS: Record<string, string> = {
  // 17,637 行。🔴🔴 **我先想写「近音词」，那是错的。** 实测判据：
  //    去掉**全部**附加符号（声调符 ＋ 字母符 ＋ đ→d）之后同形的占 **99.9%**
  //    （17,621/17,637，16 个例外只差空格与连字符：`ban công` vs `ban-công`）。
  //    只去声调符的话只有 42% —— 剩下的是 `day → dây`（a/â）、`day → đay`（d/đ），
  //    而 **đ /ɗ/ 与 d /z/ 发音差得远**，叫「近音」是假的。
  //    ⇒ 它的真身是「**不打符号时拼写会撞上的词**」，对越南语读者是真实需求。
  // 🔴 展示层**不许把它排在语义关系里**（近义/反义/相关）：那会让读者以为
  //    `mai` 与 `mại` 意思相关。B17 在数据层治的正是这个混淆
  //    （兜底 related 被语义更具体的 kind 吞掉时，paronym **有意不参与**）。
  paronym: '仅差附加符号',

  // 29 行。越南语的 từ láy（`vuông → vuông vức`／`vòng → vòng vo`）是构词核心手段。
  reduplicative: '叠音词',
  // 13 行。`nghiêm → giới nghiêm / nghiêm cấm`：含这个词的复合词。
  compound: '复合词',
  // 12 行。`không → ko`／`Thành phố Hồ Chí Minh → TPHCM`。方向是「词 → 它的缩写」。
  abbreviation: '缩写',
  // 3 行。`lừa → ngu như lừa`（蠢得像驴）。
  //    ⚠️ 其中 1 行目标是 `đầu cực âm của ắc_qui`（带下划线的源头残渣）——
  //      与欠账 **W9** 同形（整段标签塞进 target，而现有判据只覆盖带假名/韩文的那批）。
  phraseology: '固定说法',
  // 2 行。`nước → nước chảy đá mòn`（水滴石穿）。
  phrase: '熟语',
  // 1 行。本字段在源头指**借进别的语言的后代词**；而唯一这 1 行是
  //    `môi miếng → môi miệng`（越南语内部异写）⇒ **源头标错了**。
  //    标签按字段的本义写，例外记在这里 —— 不为 1 行把名字改成错的。
  descendant: '后代词',
};

/**
 * 方言点。🔴 **13 个值，而音标层只认 6 个"方言点"** —— 其余 7 个是
 * 阶段 6 录音层才长出来的（那些 `sounds` 项有 `audio` 没有 `ipa`，音标层看不见）。
 * ⚠️ `unknown` 印成空：源头没说是哪里的音，**不许替源头猜**。
 */
export const VI_DIALECT_LABELS: Record<string, string> = {
  // ── 六个主方言点（音标层的值域，各 2.7 万–8.6 万行）──
  'ha-noi': '河内音',
  hue: '顺化音',
  'sai-gon': '西贡音',
  vinh: '荣市音',
  'ha-tinh': '河静音',
  'thanh-chuong': '清章音',
  // ── 录音层带进来的长尾（≤9 行），逐个都是地名 ──
  'quang-nam': '广南音',
  'hoi-an': '会安音',
  'hoai-nhon': '怀仁音',
  'phong-nha': '风牙音',
  'dong-hoi': '洞海音',
  gin: '京族音',       // 中国广西的京族（越南族）使用的越南语
  // ⚠️ 2,066 行。源头没标，**印空不印「未知」** ——
  //   `[[dont-say-source-lacks-what-we-skipped]]`：别把"我们不知道"写成一个值。
  unknown: '',
};

/** 词源类型（`entry.etym_type`，5 种，全部来自 en 版的 `etymology_templates`）。 */
export const VI_ETYM_TYPE_LABELS: Record<string, string> = {
  sino_vietnamese: '汉越词',
  compound: '复合',
  borrowed: '借词',
  native: '固有词',
  mixed: '混合',
};

/**
 * 汉字/喃字表记的**判据可信度**（`rule_ver`）。
 *
 * 🔴🔴 **这是欠账 W6 的落点，也是这张表里最重要的一组。**
 * 实测 `codepoint-v1`（按码位区间猜汉越字还是喃字）**只有 70.8% 对**
 * —— 拿源头 10,534 对带权威标注的样本验出码位判据错 **25.66%**，
 * 而且**污染单向**（全在 han 侧）。
 * ⇒ 展示层**不许把它印成与权威来源一样的「汉越字」**。
 *
 * ⚠️ 返回的不是"表记类型"而是**这条表记凭什么**。调用方要把
 * `trusted: false` 的那档加上明确的不确定标注（契约闸有一条读者口径查这件事）。
 */
export const VI_SPELLING_RULE: Record<string, { label: string; trusted: boolean }> = {
  // 19,394 行。zh 版词源正文里直接写着的汉字 ⇒ 权威。
  'src-zh-etym-v1': { label: '据中文版词源', trusted: true },
  // 6,122 + 4,056 行。源头义项正文自标 `chữ Hán/Nôm form of` ⇒ 最强的信号。
  'src-label-v1': { label: '源头自标', trusted: true },
  // 4,835 行。en 版词源正文里的汉字。
  'src-en-etym-v1': { label: '据英文版词源', trusted: true },
  // 🔴 9,792（han）＋ 4,535（nom）行 ＝ **按 Unicode 码位区间猜的**，实测 70.8% 对。
  //    W6：它**不许印成「汉越字」**。
  'codepoint-v1': { label: '按字形推定（未经核实）', trusted: false },
};

/**
 * 音标来源。🔴 **欠账 W7 的落点**：96,267 行音标是阶段 3b 按音节**拼**出来的。
 * `src` 以 `compose:` 开头的那批**必须让读者分得出**，否则就是拿我们算的冒充源头写的。
 * （闸 R13 保证它只填空不覆盖；这里保证它在页面上有标注。）
 */
export function viPronSourceLabel(src: string): { label: string; composed: boolean } {
  if (src.startsWith('compose:')) {
    return { label: '按音节拼写', composed: true };
  }
  return { label: '源头标注', composed: false };
}

/**
 * 中文释义来源。🔴 **欠账 W13 的落点**：1,183 条模型译文与该词的汉字表记逐字相同
 * （`công nhân` → 工人）—— 那些译文**是对的**（汉越词的正确对译就等于它的汉字表记），
 * 但页面上方印着「汉字表记 工人」、释义栏再印「工人」，对读者是冗余。
 * ⇒ 调用方拿这个函数判断要不要**折叠**那一行，而**不是隐藏释义**
 *   （隐藏＝这 1,183 个词一条中文释义都没有，严格更差）。
 */
export function viGlossIsSameAsSpelling(gloss: string, spellings: readonly string[]): boolean {
  const g = gloss.trim();
  if (!g) return false;
  return spellings.some((s) => s.trim() === g);
}

/**
 * 词源正文的**来源语言版**。🔴 这不是装饰,是必需的。
 *
 * 实测有词源的 25,926 个词形里 **7,661（29.5%）** 的词源来自两三个语言版，
 * 而三版讲的常常是**同一件事的三种语言**：
 *     [英文版]   From Proto-Vietic *ʔan.
 *     [越南语版] Từ tiếng Việt-Mường nguyên thủy *ʔan.
 *     [中文版]   繼承自原始越語 *ʔan。
 * 不标来源地并印 ⇒ 读者看到三段话，**会以为这个词有三个不同的词源**
 * （`ăn` 页面上就是这样，2026-10-03 渲染出来看见的）。
 *
 * ⚠️ **一段都不丢**。只留中文那段看着更干净，但那是把「我们没印」伪装成
 *   「源头只说了这些」—— 三个版是**三个独立来源**，有时说的真不是同一件事
 *   （`[[dont-say-source-lacks-what-we-skipped]]`）。⇒ 标注来源，中文排在最前。
 */
export const VI_EDITION_LABELS: Record<string, string> = {
  'zh-edition-trad': '中文版',
  'zh-edition-simp': '中文版',
  'en-edition': '英文版',
  'vi-edition': '越南语版',
};

/** 词源段的排序权重：中文读者优先看中文，其次英文，越南语垫后。 */
export function viEditionRank(src: string): number {
  if (src.startsWith('zh-')) return 0;
  if (src === 'en-edition') return 1;
  return 2;
}
