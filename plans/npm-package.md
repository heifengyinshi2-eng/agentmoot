# npm-package — 打包为可安装的 pi 包并发布

## 目标

把 agentmoot 整理成可 `pi install` 的 npm 包（GitHub Packages），推送源码到 GitHub。

## 需求

- 独立 git 仓库（原在 L:/piworkspace/nxbuild 子目录下）。
- `package.json` 带 `pi-package` keyword + `pi.extensions` 指向 `extensions/moot.ts`。
- `files` 白名单只含运行必需：extension + Python server 源码 + README/LICENSE。
- 服务器部分打进包（Python 源码），**暂不提供部署方法**。
- 发布到 GitHub Packages（对齐 agentcodemode 的 `publishConfig`）。

## 验收标准

- [ ] `node scripts/release/pack.mjs --pack` 产出 tgz，内容仅白名单（11 文件）
- [ ] tgz 内 package.json 含 `pi.extensions` 与 `pi-package` keyword
- [ ] `git push` 到 github.com/heifengyinshi2-eng/agentmoot 成功
- [ ] `npm publish` 到 npm.pkg.github.com 成功（版本 0.1.0）
- [ ] 从 registry 回拉 `pi install npm:@heifengyinshi2-eng/agentmoot@0.1.0` 能加载 extension（后续验证）

## 设计要点

- **单一来源**：extension 源码放 `extensions/moot.ts`；项目本地 `.pi/extensions/moot.ts` 改为转发（`export { default } from "../../extensions/moot.ts"`）。
- **白名单打包**：`scripts/release/pack.mjs` 复制白名单到 `dist-release/` 再 `npm pack`，避免 npm 读子目录 .gitignore 带入无关文件（参考 agentcodemode）。
- **不声明 peerDependencies**：typebox / pi-coding-agent 由 pi 自身提供（agentcodemode 实测声明会拉 189 包）。
- **不自动改用户 MCP 配置**：extension 只做注入；MCP 配置与服务器启动由用户按 README 操作（暂不提供部署方法）。

## 任务

- [x] 建 extensions/moot.ts + .pi 转发
- [x] package.json / LICENSE / README 安装段
- [x] scripts/release/pack.mjs
- [x] 本地 npm pack 验证
- [x] git init + .gitignore
- [ ] commit + push
- [ ] npm publish
- [ ] 回拉验证

## 备注

- 原目录属于 L:/piworkspace（nxbuild remote）仓库，但该目录未被父仓库追踪；在其内 `git init` 形成独立仓库，父仓库不受影响。
- bin/ 下本机部署二进制（moot.exe、python312.dll 等）已 gitignore，不入库、不入包。

## 更新记录

- 2026-11-12：建立计划；完成包结构、白名单打包、本地 npm pack 验证（11 文件）
