import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.tsx';
import './flicker-probe.ts'; // 闪动探针：模块内部自带 import.meta.env.DEV 开关，生产环境为空
import './styles.css';
// B29：罕用汉字（扩展 B 及以后）兜底字体，按需切片；由 scripts/rare_han_font.py --build 生成
import './rare-han.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
