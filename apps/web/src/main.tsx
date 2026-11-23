import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.tsx';
import './flicker-probe.ts'; // 闪动探针：模块内部自带 import.meta.env.DEV 开关，生产环境为空
import './styles.css';
// B29：罕用汉字（扩展 B 及以后）兜底字体，按需切片；由 scripts/rare_han_font.py --build 生成
import './rare-han.css';

// 标签页切回时，浏览器会把处于 :focus/:hover 的过渡**整组重播**。
// 探针（`flicker-probe.ts`）记录的 8 次切回，8 次都是同一形状：
//   `vis visible → input focus ×2 → 6 个 transitionstart`（搜索框边框 4 边 + 背景 + 光晕），
//   有时再加语言按钮的 5 个属性 —— 看起来就是整页闪一下。
// 🔴 还有一类**不触发 visibilitychange**：切到别的应用窗口再回来。
//    探针里 4 次 `focus + input + anim` 的存档没有 `vis` 事件，正是这一种。
//    ⇒ window 的 blur/focus 也要管。
// 隐藏/失焦期间禁掉过渡，恢复后**等 3 秒**再解除。
// ⚠️ 120ms 不够：2026-11-17 手动标记的现场里，切回（ms 109227）后 **2.3 秒**
//    浏览器才重新计算结果列表的 `:hover`（4 个 `button.result-item` 一起渐变背景色）。
//    3 秒是实测延迟的两倍余量；恢复后 3 秒内的交互没有过渡，可以接受。
{
  const root = document.documentElement;
  const calm = () => root.classList.add('anim-off');
  const resume = () => window.setTimeout(() => root.classList.remove('anim-off'), 3000);
  document.addEventListener('visibilitychange', () => (document.hidden ? calm() : resume()));
  window.addEventListener('blur', calm);
  window.addEventListener('focus', resume);
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
