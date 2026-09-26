import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.tsx';
import './flicker-probe.ts'; // 闪动探针：模块内部自带 import.meta.env.DEV 开关，生产环境为空
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
