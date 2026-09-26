/**
 * 闪动探针 v2 —— **只在开发期装，生产环境整个模块是空的**。2026-09-25。
 *
 * ═══ v1 跑完知道了什么 ═══
 * 用户标记三次，全保真地排除掉：整页重载（全程只有开头 2 次 load）、
 * 我的编辑触发热更新（0 条 hmr）、CSS 热替换、React 重挂、主题抖动、布局跳动
 * （4 次 layout-shift 无一靠近标记）。**我原先「Vite 整页重载」的结论被自己的探针否掉了。**
 *
 * 🔴 但 v1 没能指认元凶，原因是**它的节流恰好盖住了要看的那一段**：
 *    同名动画 1 秒去重、DOM 变更要 250ms 内超 30 条才记。
 *    `[[ko-dict-pipeline]]`：**诊断工具必须对它要诊断的病免疫** —— v1 不免疫。
 *
 * ═══ v2 的两处结构性改动 ═══
 *
 * ① **全保真环形缓冲 + 事后倒带**
 *    所有事件不节流不设阈进环（上限 900 条）；只有「值得存档的那一刻」才把
 *    前 12 秒原样倒出来。常态日志因此变**稀**（v1 五分钟写了 844 行全是悬停噪声，
 *    挂一整天没法读），而关键时刻的分辨率反而变**高**。
 *
 * ② **自动触发，不再只靠用户按键**
 *    🔴 用户实测：闪动**偶发、不可预测**，而且从「看见」到「按下 Ctrl+Shift+X」
 *    实测有 2.0–2.5 秒反应时间 —— 光靠人按，既会漏（没看着屏幕时发生）
 *    也会晚（2 秒足够让现场事件滚出窗口）。
 *
 *    判据按**用户原话的含义**写，不按我猜的机制写：
 *    用户说「**页面静止时也会发生**」⇒ **「人没动，画面却变了」就是要抓的东西**。
 *        人没动 ＝ 距上一次 pointermove/keydown/wheel/scroll/focus ≥ 1.2 秒
 *        画面变了 ＝ 过渡/动画开始、DOM 变更成簇、layout-shift、掉帧 >100ms、
 *                    <head> 换样式表、#root 换子树
 *    两个条件同时成立 → 自动倒带存档。
 *    ⚠️ 这条判据**故意比「闪动」宽** —— 宁可多存几次正常的异步渲染，
 *       也不要漏掉真的那一次。存档带着 `idleMs`，事后能分辨。
 *
 * ═══ 探针不许自己制造它要测的现象 ═══
 *   · 不进 React、不建 state、**一个 DOM 节点都不改**（改了会被自己的观察器录到）；
 *   · 自己发的 `/__flicker` 请求排除在 fetch 记录之外，否则无限自激；
 *   · window 上打单例标记 —— 它自己也会被热更新重新求值；
 *   · 自动存档限流（最快 3 秒一次、每次加载最多 120 次），挂一整天也撑不爆。
 *
 * 用法：看见闪了仍然按 **Ctrl+Shift+X**（人按的标记最可信，自动触发是兜底）。
 */

type Rec = Record<string, unknown>;

// 未被包装过的原始 fetch。**必须在 install() 之前求值** —— 它是 const，
// 写在文件末尾会落进暂时性死区，而 install() 在模块求值时就跑。
const G = (typeof window !== 'undefined' ? window : {}) as unknown as Record<string, unknown>;
if (typeof window !== 'undefined' && !G.__flickerRawFetch) {
  G.__flickerRawFetch = window.fetch.bind(window);
}
const rawFetch = G.__flickerRawFetch as typeof fetch;

const RING_MAX = 900; // 环上限
const DUMP_WINDOW_MS = 12000; // 倒带多长
const DUMP_MAX_EVENTS = 400; // 单次存档最多几条
const IDLE_MS = 1200; // 「人没动」的门槛
const DUMP_COOLDOWN_MS = 3000; // 自动存档最快多久一次
const DUMP_BUDGET = 120; // 每次页面加载最多存几次

if (import.meta.env.DEV) install();

function install() {
  const W = G;
  // 🔴 探针自己也会被热更新重新求值 —— 不打单例标记就会叠成 N 份监听器。
  if (W.__flickerProbe) {
    (W.__flickerProbe as { rearm: () => void }).rearm();
  } else {
    W.__flickerProbe = boot();
  }
}

function boot() {
  const t0 = performance.now();
  const now = () => performance.now() - t0;
  const stamp = () => new Date().toISOString().slice(11, 23);

  let queue: Rec[] = [];
  let timer: number | undefined;
  const disposers: Array<() => void> = [];

  // ── 落盘（常态流，写得稀）────────────────────────────────────────────
  function log(kind: string, data?: Rec, urgent = false) {
    queue.push({ t: stamp(), ms: Math.round(now()), kind, ...data });
    if (urgent || queue.length >= 30) flush(urgent);
    else if (timer === undefined) timer = window.setTimeout(() => flush(false), 900);
  }

  function flush(sync: boolean) {
    window.clearTimeout(timer);
    timer = undefined;
    if (!queue.length) return;
    const body = queue.map((r) => JSON.stringify(r)).join('\n');
    queue = [];
    // 整页重载前只有 sendBeacon 送得出去（fetch 会随页面一起被掐断）
    if (sync && navigator.sendBeacon) {
      navigator.sendBeacon('/__flicker', new Blob([body], { type: 'text/plain' }));
      return;
    }
    // ⚠️ 用原始 fetch，不走被包过的那个 —— 否则探针记录自己，无限自激
    rawFetch('/__flicker', { method: 'POST', body, keepalive: true }).catch(() => {});
  }

  // ── 环形缓冲（全保真，不节流不设阈）──────────────────────────────────
  const ring: Rec[] = [];
  function push(k: string, d?: Rec) {
    ring.push({ ms: Math.round(now()), k, ...d });
    if (ring.length > RING_MAX) ring.splice(0, ring.length - RING_MAX);
  }

  let lastDumpAt = -1e9;
  let budget = DUMP_BUDGET;
  function dump(reason: string, extra?: Rec, forced = false) {
    const t = now();
    if (!forced) {
      if (budget <= 0) return;
      if (t - lastDumpAt < DUMP_COOLDOWN_MS) return;
      budget -= 1;
    }
    lastDumpAt = t;
    const from = t - DUMP_WINDOW_MS;
    const evs = ring.filter((r) => (r.ms as number) >= from).slice(-DUMP_MAX_EVENTS);
    log(
      'DUMP',
      {
        reason,
        idleMs: Math.round(t - lastInputAt), // 距上次人为输入多久 —— 「静止时也会发生」的度量
        pointerMoves1s: ptrRecent(),
        ...extra,
        n: evs.length,
        events: evs,
      },
      true,
    );
  }

  // ── 「人动了没有」────────────────────────────────────────────────────
  let lastInputAt = -1e9;
  const ptrStamps: number[] = [];
  const ptrRecent = () => {
    const t = now();
    return ptrStamps.filter((x) => x > t - 1000).length;
  };
  function onInput(e: Event) {
    const t = now();
    lastInputAt = t;
    if (e.type === 'pointermove') {
      ptrStamps.push(t);
      if (ptrStamps.length > 200) ptrStamps.splice(0, 100);
      return; // pointermove 太密，不进环
    }
    push('input', { type: e.type });
  }
  for (const ev of ['pointermove', 'pointerdown', 'keydown', 'wheel', 'scroll', 'focus']) {
    window.addEventListener(ev, onInput, true);
    disposers.push(() => window.removeEventListener(ev, onInput, true));
  }

  // 🔴 判据第一版写宽了，宽在一个**必然发生**的地方：页面刚加载时 `lastInputAt`
  //    还是初始值，「人没动」恒为真，而这时 Vite 正在注入 <style>、React 正在挂
  //    #root —— 于是**每次加载必误报一次**。实测 8 次自动存档里 5 次是这个假货。
  //    ⇒ 加载后 GRACE_MS 内不自动存档。那段时间页面本来就在变，
  //      「静止时也会发生」这条判据在那里根本不适用。
  //    ⚠️ 只挡**自动**触发；用户按 Ctrl+Shift+X 是强制存档，任何时候都记。
  const GRACE_MS = 2500;
  const idle = () => now() >= GRACE_MS && now() - lastInputAt >= IDLE_MS;

  /** 画面变了。人没动的时候变 ⇒ 这就是用户说的「静止时也会发生」。 */
  function visual(kind: string, d?: Rec) {
    push(kind, d);
    if (idle()) dump('画面变了而人没动：' + kind, { trigger: d });
  }

  // ── 节点描述 ─────────────────────────────────────────────────────────
  function desc(n: Node | null | undefined): string {
    if (!n) return '?';
    if (n.nodeType === Node.TEXT_NODE) {
      return 'text«' + (n.textContent || '').trim().slice(0, 24) + '»';
    }
    const el = n as Element;
    if (!el.tagName) return n.nodeName;
    const cls =
      typeof el.className === 'string' && el.className.trim()
        ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.')
        : '';
    return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + cls;
  }

  // ── ① 页面加载 ──────────────────────────────────────────────────────
  let loads = 0;
  let gap: number | null = null;
  try {
    loads = Number(sessionStorage.getItem('flicker.loads') || '0') + 1;
    sessionStorage.setItem('flicker.loads', String(loads));
    const prev = Number(sessionStorage.getItem('flicker.lastLoadAt') || '0');
    if (prev) gap = Math.round((Date.now() - prev) / 100) / 10;
    sessionStorage.setItem('flicker.lastLoadAt', String(Date.now()));
  } catch {
    /* 隐私模式 */
  }
  const nav = performance.getEntriesByType('navigation')[0] as
    | PerformanceNavigationTiming
    | undefined;
  log('load', {
    v: 2,
    n: loads, // 本标签页第几次加载 —— 静止时它在涨，就是整页重载
    type: nav?.type,
    sinceLastLoadSec: gap,
    url: location.href,
  });

  // ── ② Vite 热更新 ───────────────────────────────────────────────────
  if (import.meta.hot) {
    const hot = import.meta.hot;
    const on = (ev: string, fn: (p: unknown) => void) => hot.on(ev as never, fn as never);
    on('vite:beforeUpdate', (p) => {
      const u = (p as { updates?: Array<{ path: string; type: string }> })?.updates || [];
      log('hmr:update', { files: u.map((x) => x.path + '[' + x.type + ']') });
      push('hmr:update', { n: u.length });
    });
    on('vite:beforeFullReload', (p) =>
      log('hmr:FULL-RELOAD', { path: (p as { path?: string })?.path }, true),
    );
    on('vite:error', (p) =>
      log('hmr:error', { err: String((p as { err?: { message?: string } })?.err?.message) }, true),
    );
    on('vite:ws:disconnect', () => log('hmr:ws-disconnect'));
    on('vite:ws:connect', () => log('hmr:ws-connect'));
  }

  // ── ③ <head> 换样式表 / ④ #root 换子树 / ⑤ html 属性：都算结构性，常态流也记 ──
  const headObs = new MutationObserver((recs) => {
    for (const r of recs) {
      const add = Array.from(r.addedNodes).filter((n) => n.nodeName === 'STYLE' || n.nodeName === 'LINK');
      const del = Array.from(r.removedNodes).filter((n) => n.nodeName === 'STYLE' || n.nodeName === 'LINK');
      if (add.length || del.length) {
        log('head', { added: add.map(desc), removed: del.map(desc) });
        visual('head', { added: add.map(desc) });
      }
    }
  });
  headObs.observe(document.head, { childList: true });
  disposers.push(() => headObs.disconnect());

  const root = document.getElementById('root');
  if (root) {
    const rootObs = new MutationObserver((recs) => {
      for (const r of recs) {
        if (r.addedNodes.length || r.removedNodes.length) {
          const d = {
            added: Array.from(r.addedNodes).map(desc),
            removed: Array.from(r.removedNodes).map(desc),
          };
          log('root', d);
          visual('root', d);
        }
      }
    });
    rootObs.observe(root, { childList: true });
    disposers.push(() => rootObs.disconnect());
  }

  const htmlObs = new MutationObserver((recs) => {
    for (const r of recs) {
      const d = {
        attr: r.attributeName,
        from: r.oldValue,
        to: r.attributeName ? document.documentElement.getAttribute(r.attributeName) : null,
      };
      log('html-attr', d);
      visual('html-attr', d);
    }
  });
  htmlObs.observe(document.documentElement, { attributes: true, attributeOldValue: true });
  disposers.push(() => htmlObs.disconnect());

  // ── ⑥ layout-shift（带上真正位移了的节点）────────────────────────────
  try {
    const po = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        const ls = e as PerformanceEntry & {
          value: number;
          hadRecentInput: boolean;
          sources?: Array<{ node?: Node }>;
        };
        if (ls.value < 0.0005) continue;
        const d = {
          value: Math.round(ls.value * 10000) / 10000,
          hadRecentInput: ls.hadRecentInput,
          nodes: (ls.sources || []).map((s) => desc(s.node)).slice(0, 5),
        };
        log('cls', d);
        visual('cls', d);
      }
    });
    po.observe({ type: 'layout-shift', buffered: true } as PerformanceObserverInit);
    disposers.push(() => po.disconnect());
  } catch {
    /* Safari 没有 layout-shift */
  }

  // ── ⑦ 动画/过渡：**全保真进环，一条不丢**（v1 在这里节流，正是它瞎掉的地方）──
  const onAnim = (e: Event) => {
    const ev = e as AnimationEvent & TransitionEvent;
    const name = (ev as AnimationEvent).animationName || (ev as TransitionEvent).propertyName;
    visual('anim', { type: e.type, name, on: desc(e.target as Node) });
  };
  document.addEventListener('animationstart', onAnim, true);
  document.addEventListener('transitionstart', onAnim, true);
  disposers.push(() => {
    document.removeEventListener('animationstart', onAnim, true);
    document.removeEventListener('transitionstart', onAnim, true);
  });

  // ── ⑧ DOM 变更：每一条都进环（含属性旧值→新值），成簇才当「画面变了」──
  let bucket = 0;
  const bodyObs = new MutationObserver((recs) => {
    bucket += recs.length;
    for (const r of recs.slice(0, 12)) {
      const el = r.target as Element;
      push('mut', {
        ty: r.type,
        tg: desc(r.target),
        at: r.attributeName || undefined,
        ov: r.oldValue ? String(r.oldValue).slice(0, 50) : undefined,
        nv:
          r.type === 'attributes' && r.attributeName && el.getAttribute
            ? String(el.getAttribute(r.attributeName)).slice(0, 50)
            : r.type === 'characterData'
              ? String(r.target.textContent || '').slice(0, 50)
              : undefined,
      });
    }
  });
  bodyObs.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeOldValue: true,
    characterData: true,
    characterDataOldValue: true,
  });
  const tick = window.setInterval(() => {
    if (bucket >= 8) {
      push('dom', { mutations: bucket });
      if (idle()) dump('DOM 成簇变更而人没动', { mutations: bucket });
    }
    bucket = 0;
  }, 250);
  disposers.push(() => {
    bodyObs.disconnect();
    window.clearInterval(tick);
  });

  // ── ⑨ 掉帧监测：**默认关闭** ─────────────────────────────────────────
  // 🔴🔴 这是整个探针里**唯一会改变被观测对象**的部件。
  //    连续的 requestAnimationFrame 会把合成器一直钉在活跃状态，
  //    而我们要抓的恰恰是**页面静止时**的异常重绘 —— 它有可能把病压住。
  //    `[[ko-dict-pipeline]]`「诊断工具必须对它要诊断的病免疫」的另一面：
  //    **诊断工具也不许改变它要诊断的东西**。
  //    其余部件（MutationObserver / PerformanceObserver / 事件监听）全是被动的，
  //    而 v1 没有 rAF 也照样录到了三次闪动 —— 被动观测足够，这一条是可有可无的奢侈品。
  //    真要用：控制台敲 `__flickerProbe.jank(true)`。
  let frames = 0;
  let raf = 0;
  let lastFrame = performance.now();
  const onFrame = (ts: number) => {
    const dt = ts - lastFrame;
    lastFrame = ts;
    frames += 1;
    if (dt > 100) {
      push('jank', { dtMs: Math.round(dt) });
      if (idle()) dump('长掉帧而人没动', { dtMs: Math.round(dt) });
    }
    raf = requestAnimationFrame(onFrame);
  };
  function setJank(on: boolean) {
    cancelAnimationFrame(raf);
    raf = 0;
    if (on) {
      lastFrame = performance.now();
      raf = requestAnimationFrame(onFrame);
    }
    log('jank-monitor', { on });
  }
  disposers.push(() => cancelAnimationFrame(raf));

  // ── ⑩ 请求（⚠️ 排除探针自己）─────────────────────────────────────────
  if (!(window.fetch as unknown as Record<string, unknown>).__flickerWrapped) {
    window.fetch = function (input: RequestInfo | URL, init?: RequestInit) {
      const url = String(
        typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
      );
      if (url.includes('/__flicker')) return rawFetch(input, init);
      const started = now();
      push('fetch:start', { url: url.slice(0, 120) });
      return rawFetch(input, init).then(
        (r) => {
          push('fetch', { url: url.slice(0, 120), status: r.status, ms: Math.round(now() - started) });
          return r;
        },
        (e) => {
          push('fetch', { url: url.slice(0, 120), error: String(e).slice(0, 80) });
          throw e;
        },
      );
    } as typeof fetch;
    (window.fetch as unknown as Record<string, unknown>).__flickerWrapped = true;
  }

  // ── ⑪ 根本不是页面的事 ───────────────────────────────────────────────
  const onVis = () => {
    log('vis', { state: document.visibilityState });
    push('vis', { state: document.visibilityState });
  };
  const onBlur = () => {
    log('focus', { has: document.hasFocus() });
    push('focus', { has: document.hasFocus() });
  };
  const onResize = () => {
    log('resize', { w: innerWidth, h: innerHeight, dpr: devicePixelRatio });
    push('resize', { w: innerWidth, h: innerHeight, dpr: devicePixelRatio });
  };
  document.addEventListener('visibilitychange', onVis);
  window.addEventListener('blur', onBlur);
  window.addEventListener('resize', onResize);
  disposers.push(() => {
    document.removeEventListener('visibilitychange', onVis);
    window.removeEventListener('blur', onBlur);
    window.removeEventListener('resize', onResize);
  });

  // ── ⑫ 用户标记：看见闪了就按 Ctrl+Shift+X（**强制存档，不受限流/预算约束**）──
  const onKey = (e: KeyboardEvent) => {
    if (e.ctrlKey && e.shiftKey && (e.key === 'X' || e.key === 'x')) {
      e.preventDefault();
      dump('MARK 用户按键：我刚看见闪了', {}, true);
      console.log('%c[闪动探针] 已标记并倒带存档', 'color:#0a0;font-weight:bold');
    }
  };
  window.addEventListener('keydown', onKey, true);
  disposers.push(() => window.removeEventListener('keydown', onKey, true));

  // ── ⑬ 心跳：挂一整天要能看出它还活着、以及这段时间有多闲 ────────────────
  const beat = window.setInterval(() => {
    log('beat', {
      upSec: Math.round(now() / 1000),
      frames,
      fps: Math.round(frames / 120),
      ringLen: ring.length,
      dumpsLeft: budget,
      idleSec: Math.round((now() - lastInputAt) / 1000),
    });
    frames = 0;
  }, 120000);
  disposers.push(() => window.clearInterval(beat));

  const onHide = () => flush(true);
  window.addEventListener('pagehide', onHide);
  disposers.push(() => window.removeEventListener('pagehide', onHide));

  log('probe-ready', { v: 2, loads });

  return {
    jank: setJank, // 按需开掉帧监测（默认关，见 ⑨）
    rearm() {
      log('probe-rearm', { v: 2 });
    },
    dispose() {
      for (const d of disposers) {
        try {
          d();
        } catch {
          /* ignore */
        }
      }
      flush(true);
    },
  };
}

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    const p = G.__flickerProbe as { dispose: () => void } | undefined;
    p?.dispose();
    delete G.__flickerProbe;
  });
}
