// ============================================================================
// 真人发音按钮的标签 —— **八门共用**。2026-09-26（K23）
//
// ═══ 为什么这段逻辑要从 `HumanAudioRow` 里搬出来 ═══
// 「同一个词的几个按钮写着一样的字，读者分不清点哪个」这个缺陷，
// 在四门上各发作过一次，每次都是**用户在页面上看见的**：
//
//     2026-08-31  fr `chien`   八个按钮全写「法国」   → 加 `capAudios`（每地区≤2、总≤6）
//     2026-08-31  es `banco`   两个都写「未标注」     → region 空时退到录音人
//     2026-08-31  pt `a`       四个都写「巴西」       → 标签重复时把录音人带上
//     2026-09-25  ko `한국`     两个又都写「未标注」   → **录音人也是空的，兜底到此为止**
//
// 🔴 前三次都是「修好手边那一个形状」，第四次换个形状又发作。
//    2026-09-26 全量实测：**八门全中，3,563 个词**（en 218／es 171／it 116／fr 1,090／
//    pt 403／de 1,559／ja 3／ko 39，按「录音行签名」全覆盖）。
//    ⇒ 要的不是第四个补丁，是一条**不变式**：
//
//        **同一个词的所有按钮标签，两两不同。**
//
//    这个不变式由 `apps/web/src/contract-check-audio.tsx` 盯着（读渲染出来的字）。
//
// ═══ 判据：加信息的顺序是「源头给的事实」优先，编号垫底 ═══
// 重复时逐级往上加，每一级都必须是**源头真给了的东西**；
// 到最后实在没有任何事实能把它们分开，才加序号 ——
// 序号**不假装知道差别在哪**，它只保证读者知道「这是两条不同的录音」。
// `[[dont-recast-deliverables-as-junk]]`：不许把缺口伪装成内容；
// 反过来也不许因为说不清就藏起来（`DISPLAY_EXTREMES` §四.1「折叠可以，死胡同不行」）。
//
// ⚠️ **序号会掩盖数据缺陷**：两行其实是同一条录音存了两次时，
//    页面上会印出「录音 1 / 录音 2」，读者以为有两条。
//    所以数据层那笔账必须**另外记、另外盯**（`docs/BACKLOG.md` B12），
//    不许拿这个展示层兜底当成事情做完了（`[[aim-for-perfect-not-cheap]]`）。
// ============================================================================

export type AudioChipLike = {
  region?: string | null;
  speaker?: string | null;
  ipa?: string | null;
  /** Commons 文件名。有的门的服务层不查这一列（pt/de），所以是可选的。 */
  file?: string | null;
};

const clean = (s: string) => s.replace(/_/g, ' ').replace(/\s+/g, ' ').trim();

/**
 * 文件名里括号注的那部分 —— 上传者用它区分同一个词的不同录音。
 *
 * ⭐ ko `밤` 就是这么两条：`Ko-밤(단음).ogg` / `Ko-밤(장음).ogg`
 *    —— **短元音 vs 长元音**，韩语里 `밤`（夜）短、`밤`（栗）长，那是真区别。
 *    序号垫底会把它盖成「录音 1 / 录音 2」，**真信息就没了**
 *    （`KO_PLAN` K23 原文记着「有一族信息就藏在文件名里」）。
 *
 * ⚠️ 不做白名单（不写 `단음|장음`）—— 那是形式代理，换个词就漏。
 *    这里只负责把括号里的字取出来，**要不要用它由「这一级分不分得开」决定**：
 *    Lingua Libre 的 `LL-Q9176 (kor)-…` 里那个 `(kor)` 是命名结构、
 *    组内人人相同 ⇒ 自动被跳过，不用特判。
 */
function parenNote(fn: string | null | undefined): string | null {
  // 🔴 取**最后一个**括号，不是第一个。Lingua Libre 的命名是
  //      `LL-Q150 (fra)-WikiLucas00-Agni (dieu).wav`
  //    第一个括号是**语言码**（人人相同、毫无区分力），真正的注在后面 ——
  //    第一版取第一个，`fr Agni` 的「神(dieu) / 民族(peuple)」因此被判成
  //    「组内取值全相同」而跳过，退回了序号。又是**判据取错了位置**。
  const all = [...(fn || '').matchAll(/[（(]([^）)]{1,16})[）)]/g)];
  return all.length ? clean(all[all.length - 1][1]) : null;
}

/** 出现了不止一次的标签。 */
function repeated(labels: string[]): Set<string> {
  const n = new Map<string, number>();
  for (const l of labels) n.set(l, (n.get(l) ?? 0) + 1);
  return new Set([...n.entries()].filter(([, c]) => c > 1).map(([l]) => l));
}

/**
 * 一个词的几条录音 → 几个按钮标签，**保证两两不同**。
 *
 * @param audios     已经过 `capAudios` 限量的那几条，顺序即渲染顺序
 * @param regionLabel 各门自己的「原始地区码 → 中文」（ja/ko 传恒等）
 * @param unlabeled  什么都没有时印什么
 */
export function audioChipLabels<T extends AudioChipLike>(
  audios: T[],
  regionLabel: (raw: string) => string,
  unlabeled = '未标注',
): string[] {
  // 第一级：地区 → 录音人 → 未标注（原有行为，不动）
  let out = audios.map((a) =>
    a.region ? regionLabel(a.region) : a.speaker ? clean(a.speaker) : unlabeled,
  );

  // 第二、三级：还重复的，逐级补一条**源头给的事实**
  const steps: Array<(a: T) => string | null> = [
    // 地区相同时把录音人带上（`a` 的四个「巴西」就是这么分开的）。
    // ⚠️ 只在标签来自**地区**时加 —— 否则会印出「HappyMidnight · HappyMidnight」。
    (a) => (a.region && a.speaker ? clean(a.speaker) : null),
    // 地区与录音人都一样，但读音不同（同一人录了两个读法）。
    (a) => (a.ipa ? a.ipa : null),
    // 文件名的括号注（`밤(단음)` / `밤(장음)`）—— 上传者标的真区别，比序号强。
    (a) => parenNote(a.file),
  ];
  for (const step of steps) {
    const dup = repeated(out);
    if (dup.size === 0) return out;
    // 🔴 **某一级只有在它真能把这组分开时才许加。**
    //    第一版漏了这一条，`es Argentina` 印成
    //        「未标注 · [aɾxẽn̪ˈt̪ina] · 录音 1」「未标注 · [aɾxẽn̪ˈt̪ina] · 录音 2」
    //    —— 两条录音的 IPA 本来就一样，加上去是纯噪声，加完还是得靠序号。
    //    ⇒ 组内取值全相同的那一级，跳过。
    //    闸当时报的是绿（标签确实两两不同）—— **是把渲染结果打出来读才看见的**。
    const next = out.slice();
    for (const label of dup) {
      const idx = out.map((l, i) => (l === label ? i : -1)).filter((i) => i >= 0);
      const vals = idx.map((i) => step(audios[i]) ?? '');
      if (new Set(vals).size < 2) continue; // 这一级分不开这一组
      idx.forEach((i, k) => {
        if (vals[k] && vals[k] !== label) next[i] = `${label} · ${vals[k]}`;
      });
    }
    out = next;
  }

  // 垫底：没有任何事实能分开它们 ⇒ 加序号。
  const dup = repeated(out);
  if (dup.size) {
    const seen = new Map<string, number>();
    out = out.map((l) => {
      if (!dup.has(l)) return l;
      const n = (seen.get(l) ?? 0) + 1;
      seen.set(l, n);
      return `${l} · 录音 ${n}`;
    });
  }
  return out;
}
