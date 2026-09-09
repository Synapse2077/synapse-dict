// ============================================================================
// @synapse-dict/dict-labels —— 展示层映射表（原始标签 → 中文）
//
// 纯数据、零依赖：不 import 任何 node API，也不 import React。
// 因此浏览器端（划词弹窗）与 Node 端都能直接使用 —— 这是它独立于
// `@synapse-dict/dict-core` 的原因，后者依赖 `node:sqlite` / `node:fs`，进不了浏览器。
//
// 分文件原则沿用既有事实，不新定政策：
//   common —— 确实被多门语言共用的（`TRANS_LABELS` 有 4 门在用）
//   es/it/fr/pt/de —— 各语种专属，互不引用（见「按语种解耦」铁律）
// ============================================================================

export * from './common.js';
export * from './es.js';
export * from './it.js';
export * from './fr.js';
export * from './pt.js';
export * from './de.js';
export * from './en.js';
