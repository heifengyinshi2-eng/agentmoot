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

- [x] `node scripts/release/pack.mjs --pack` 产出 tgz，内容仅白名单（11 文件）
- [x] tgz 内 package.json 含 `pi.extensions` 与 `pi-package` keyword
- [x] `git push` 到 github.com/heifengyinshi2-eng/agentmoot 成功（SSH remote，绕过 PAT 的 workflow scope 限制）
- [x] `npm publish` 到 npm.pkg.github.com 成功（CI + GITHUB_TOKEN，版本 0.1.0，registry shasum 与本地 tgz 一致）
- [x] 干净屋 `npm install <tgz>` 只加 1 包；`pi -e <包目录>` 加载 extension 无错，注入生效（agent 复述「你代表项目 test-project」）

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
- [x] commit + push（SSH）
- [x] npm publish（GitHub Actions，tag v0.1.0）
- [x] 回拉验证（registry shasum + 干净屋安装 + pi 加载 + 注入）

## 备注

- 原目录属于 L:/piworkspace（nxbuild remote）仓库，但该目录未被父仓库追踪；在其内 `git init` 形成独立仓库，父仓库不受影响。
- bin/ 下本机部署二进制（moot.exe、python312.dll 等）已 gitignore，不入库、不入包。

## 更新记录

- 2026-11-12：建立计划；完成包结构、白名单打包、本地 npm pack 验证（11 文件）
- 2026-11-12：发布完成。关键经验（来自 `agentcodemode/docs/14-release-playbook.md`）：① 带 `.github/workflows/*` 的 commit 用 HTTPS+PAT 推送会被拒（缺 workflow scope），改用 **SSH remote** 即可；② 本地 token 只需 read:packages，**write:packages 交给 CI 的 GITHUB_TOKEN**；③ `peerDependencies` 绝不要声明（会导致 pi install 拉整棵依赖树）；④ `.gitattributes` 强制 `eol=lf`。CI run 43219124558，6s 成功。

## 0.2.0 — extension 改为无条件注入 + 项目级身份

用户裁定：不要用环境变量提供身份。新设计：

- **无条件注入**：不论有无身份，都注入 moot 是什么 / 何时用（issue、room、注册）/ 如何用 MCP。
- **身份来自项目 cwd**：`<cwd>/.pi/moot.json` = `{project, token, server?}`，由 agent 调 `moot_register_project` 自主注册后写入。
- **token 通道**：extension 读到 token 后设 `process.env.MOOT_TOKEN`；pi-mcp 每次元工具调用前 reload 配置并重新展开 `${env:...}`（`src/mcp-bridge.ts:95`），因此生效。同 session 内新注册需 `mcp_connect(server="moot", force=true)` 触发重连。
- **MCP 配置自愈**：extension 幂等确保项目级 `.pi/mcp-servers.json` 有 moot 条目（缺失才追加）。
- 安全性：`.pi/moot.json` 含 token，README 提示加入 `.gitignore`。

验证：无 `.pi/moot.json` 时输出注册引导并自动生成 MCP 配置；有身份时 `moot_list_pending` 返回 `{"project":"base-lib",...}`。
