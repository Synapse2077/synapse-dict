// dict-core 用 node:sqlite 的 DatabaseSync（Node ≥ 22.5 才内置该模块）。
// 若在旧版 Node 上启动，`import { DatabaseSync } from 'node:sqlite'` 会在模块加载阶段
// 以晦涩的 `ERR_UNKNOWN_BUILTIN_MODULE: node:sqlite` 崩溃，并被 pm2 反复重启成崩溃循环
// （2026-07 生产 Node 20→24 升级窗口曾真实发生）。
//
// 本模块必须作为 index.ts 的「第一个」import：ESM 按源码顺序深度优先求值各 import，
// 先跑到这里断言 Node 版本，抢在 dict-core 的 node:sqlite 静态 import 求值之前，
// 把崩溃循环换成一条清晰、可诊断的报错。
const [major, minor] = process.versions.node.split('.').map(Number);
if (major < 22 || (major === 22 && minor < 5)) {
  console.error(
    `[synapse-dict] 需要 Node >= 22.5（依赖 node:sqlite 的 DatabaseSync），当前 Node 版本为 ${process.versions.node}。` +
      `请升级 Node 后再启动。`,
  );
  process.exit(1);
}
