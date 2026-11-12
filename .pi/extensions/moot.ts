// 项目本地加载入口：转发到 npm 包的 extension 源码（单一来源，避免两份重复维护）。
// pi 从 .pi/extensions/ 自动发现本文件，实际逻辑见 ../../extensions/moot.ts。
export { default } from "../../extensions/moot.ts";
