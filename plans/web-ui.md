# web-ui：给人类查看的 moot 页面

## 目标

在 moot 服务上内嵌一个单文件 HTML 页面，让人能浏览器查看整体情况（dashboard）并深入单个 issue 看细节。

## 需求

1. **全局视图**：项目列表、issue 列表（状态徽章）、各状态统计、room 列表。
2. **详情视图**：深入特定 issue，看标题/正文/状态历史时间线/评论。
3. 数据实时来自 moot 的 REST API（同源 fetch，无 CORS）；单文件自包含（内嵌 CSS+JS），零依赖。
4. 利用本次 playground 跑出的真实数据（I-001/I-002 resolved、I-003 duplicate）作为展示内容。

## 设计

- **服务端**：`server.py` 加 `GET /` 返回 `moot/ui/index.html`（`GET /health` 仍是 JSON，不受影响）。
- **前端**：单文件 HTML，hash 路由 `#/`（dashboard）与 `#/issue/{id}`（详情）；fetch `/projects`、`/issues`、`/issues/{id}`、`/rooms` 渲染；轻量 markdown 渲染 issue 正文（标题/列表/代码块/inline code/粗体）。

## 验收标准

- [x] `GET /` 返回 HTML 页面，`GET /health` 仍返回 JSON。
- [x] 浏览器打开能看全局：3 项目、3 issue、状态徽章正确（I-001/I-002 resolved、I-003 duplicate）。
- [x] 点击 issue 能深入看详情：标题、正文（复现步骤/解决方案）、历史时间线、评论。

## 任务列表

- [x] 写 `moot/ui/index.html`（dashboard + 详情 + markdown 渲染）
- [x] 改 `server.py` 加 `GET /` serve HTML
- [x] 起服务 + 浏览器验证两个视图

## 更新记录

- 2026-11-12 建计划（L1）。
- 2026-11-12 实现 + agent-browser 验证：dashboard 正确渲染 3 issue（状态/链路/时间），详情页正确渲染 markdown 正文 + 历史时间线 + 评论。
- 2026-11-12 重构（用户反馈）：① `resolve_issue` 修复重复写入（解决方案原本同时写进 `comments` 和 `history.reason`，现只写 `reason`）；② 详情页改为一条统一时间线（open 节点放 issue 正文 + 状态切换 + 评论，按 ts 排序）；③ 页面层对旧数据做内容去重（评论 body 与某 reason 相同时跳过）；④ 加过滤（全部/状态切换/评论）；⑤ 每条信息 markdown 渲染。Chrome headless --dump-dom 验证：时间线 3 节点、解决方案只出现 1 次、正文/理由/方案均正确渲染。
- 2026-11-12 补 room 详情页：hash 路由 `#/room/{id}`，展示最终决议（resolution）+ 每个提案的表决时间线（表态 statement + 判定 judgement 按 ts 合并，含 action/verdict 徽章）+ 版本演进折叠。Chrome headless 验证 R-001：11 条表态、4 次判定、4 accept/3 continue/1 agree 徽章、时间线按 ts 正确排序。
