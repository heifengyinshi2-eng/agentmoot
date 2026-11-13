# agentmoot

Agent 间交互方案：点对点 issue 协作 + 多点会议讨论。

## 接入（MCP）

moot 是独立的协同服务（HTTP + MCP），**不依赖任何特定 agent 框架**。任何支持 MCP 的客户端都可接入：

```json
{"name":"moot","url":"http://127.0.0.1:18080/mcp","headers":{"Authorization":"Bearer <token>"}}
```

- **身份**：调 `moot_register_project(id)` 注册项目，返回 token；客户端自行保存并在 `Authorization: Bearer` 里带上。服务端从 token 识别身份，工具参数不需自报 actor。
- **自解释**：客户端可从 `initialize.instructions`、工具描述、`moot_help` 与错误信息中自行了解协议。
- **边界**：服务端不关心客户端如何保存 token，不提供 prompt 注入、项目目录管理或部署方法。

启动服务（本仓库暂不提供部署方法）：

```bash
cd <仓库目录>
python -m moot.serve --store /path/to/moot-data --port 18080
```

## 状态

MVP 已落地（2026-11）：核心存储 + 状态机 + HTTP 服务 + **标准 MCP 接口** + **SSE 事件通知** + 带 Agent 的 issue/room 演示。项目只提供 server + MCP，不绑定任何 agent 框架。

## 命名约定

- 项目名：**agentmoot**
- 具体工具名不带 `agent` 前缀：`moot issue`、`moot room`、`moot board`
- `moot` = 集会 / 辩论；`a moot point` = 待议问题，双关覆盖两个场景

## 目录

- `docs/background.md` — 背景、场景拆解、市面方案调研、设计方向
- `docs/design.md` — 设计决策记录（已锁定结论 + 能力清单 + 延后项）
- `docs/architecture.md` — 架构设计（拓扑、对象模型、状态机、能力接口、关键流程）
- `docs/room-process.md` — room 核心流程（提案收敛、表态三态、chair 职责、决议确认）
- `docs/committee-code.md` — 参会成员守则（发言质量规范，注入 Agent prompt）
- `docs/implementation.md` — MVP 实现设计（技术选型、模块布局、存储/状态机/CLI）

## MVP 代码

- `moot/store.py` — append-only 事件日志 + 状态索引 + 状态机（issue / room），含轮数上限兑底
- `moot/cli.py` — CLI（`project` / `issue` / `room` / `serve`）
- `moot/server.py` — HTTP 服务（标准库 http.server，JSON API，长期运行）
- `moot/client.py` — HTTP 客户端（对应 server API，供 Agent / demo 远程交互）
- `demo/scripted_demo.py` — 确定性演示（秒级跑通 issue + room 全流程）
- `demo/issue_demo.py` — 带 LLM Agent 的 issue 闭环（走 HTTP 服务交互）
- `demo/room_demo.py` — 带 LLM Agent 的多方会议收敛（走 HTTP 服务交互）
- `demo/harness.py` — demo 共用：起本机服务并返回 client
- `.pi/mcp-servers.json` — 本仓库开发时的 MCP 连接示例（客户端可自行放在自己的配置里，项目本身不依赖）
- `tests/test_mcp.py` + `tests/test_events.py` — MCP 端点 + SSE 事件流测试

运行：
```bash
PYTHONPATH=. python bin/moot --store /tmp/moot issue create --assignee base-lib --title t --body b --creator app
PYTHONPATH=. python demo/scripted_demo.py   # 秒级演示
PYTHONPATH=. python demo/issue_demo.py     # LLM Agent 演示（内部自起服务，走 HTTP）
PYTHONPATH=. python demo/room_demo.py      # LLM 多方会议演示（内部自起服务，走 HTTP）
```

## 服务接口（REST + MCP + SSE）

`moot serve` 起一个长期运行的服务，CLI 与 Agent 都经它访问（同一套状态机）：

```bash
PYTHONPATH=. python bin/moot --store /tmp/moot serve --port 18080
# 或
PYTHONPATH=. python -m moot.server --store /tmp/moot --port 18080
```

- **REST**（JSON，仅标准库）：`GET /health`、`GET|POST /projects`、`GET|POST /issues`、`POST /issues/{id}/review|resolve|close|comment`、`GET|POST /rooms`、`POST /rooms/{id}/proposals/{pid}/submit|judge|revise`、`POST /rooms/{id}/finalize`。
- **MCP**（Streamable HTTP）：`POST /mcp`，JSON-RPC 2.0，协议版本 2025-06-18，暴露 19 个 `moot_*` 工具（issue/room/待办/帮助），工具级错误返回 `isError: true`。**`moot_help` 自描述**：无参数返概要，`topic=overview|issue|room|identity|events|roles|api` 渐进披露，`all=true` 全量（无需 token）。身份经 `Authorization: Bearer <token>` 认证：`moot_register_project` 注册即发 token，服务端从 header 识别身份，工具不需自报 actor/author/project。
- **SSE 事件流**：`GET /events?project=X&after=N`，把 `seq > N` 且涉及 X 的事件推为 SSE event（`id`=seq）；`after` 断点重放，`once=1` 只重放不 tail；服务端 append-only 事件日志永久保留，游标 `cursor[X]` 持久化。
- **Web UI**（给人类看）：`GET /` 返回单文件看板（`moot/ui/index.html`），dashboard 全局视图（项目/issue/room/统计）+ hash 路由深入 issue 详情（一条统一时间线：open 节点放正文 + 状态切换 + 评论，按 ts 排序、内容去重、过滤全部/状态切换/评论、每条 markdown 渲染）+ room 详情（`#/room/{id}`：最终决议 + 每提案的表决时间线【表态/判定按 ts 合并 + 徽章】+ 版本演进折叠），同源 fetch REST API 实时渲染。

## 客户端接入

moot 只提供 HTTP + MCP，**不绑定任何 agent 框架**。客户端负责：配置 MCP 连接、保存 token、把 `initialize.instructions` / `moot_help` 喂给模型。

1. **MCP 连接**：`{"name":"moot","url":"http://127.0.0.1:18080/mcp","headers":{"Authorization":"Bearer <token>"}}`。
2. **身份**：调 `moot_register_project(id=...)` 注册，返回 token；客户端自行保存并在 `Authorization: Bearer` 携带。服务端从 token 识别身份，工具参数不需自报 actor。
3. **自解释**：`initialize.instructions`（单行入口）+ 工具描述 + `moot_help` 渐进披露 + 未认证错误引导（提示先注册）。

通知语义：SSE 是「唤醒信号」（at-least-once，可重复可丢），权威状态由 `moot_list_pending` 拉取保证；agent 上线先无条件拉一次待办，正确性不依赖通知链路。

自测：`python tools/serve_smoke.py`（起服务 → 跑通 issue + room 全流程 → 断言非法迁移被拒）。

跑测报告：`tools/gen_report.py` 生成 `demo-out/report.html`（含 mermaid 流程图 + 四组跑测转录）。

改过 mermaid 图后务必校验语法：`python tools/check_mermaid.py`（首次需 `cd tools/.mmd-check && npm install mermaid jsdom`）。

## 本机部署（开机自启服务）

moot 作为本机常驻服务：数据在 `%LOCALAPPDATA%\moot`，开机登录自启，崩溃自动重启，**无控制台窗口、进程名为 `moot.exe`**。

- **数据目录**：`%LOCALAPPDATA%\moot`（`state.json` + `events.jsonl` + `moot-service.log`）。
- **可执行文件**：`bin\moot.exe`（= 全局 `pythonw.exe` 的副本，故进程名为 `moot.exe` 且无窗口）+ `bin\python312.dll` 等运行时 dll（同目录优先于 PATH，开机自启不依赖 PATH）；守护与 server 均为 `moot.exe` 进程。
- **守护进程**：`bin/moot-service.py`（用 `sys.executable` 拉起 `moot.server`；崩溃 3s 后自动重启；启动前查端口，已监听则退出防重复实例）。
- **开机自启**：启动文件夹 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\start-moot.cmd`（登录时无窗口拉起守护进程；显式 `set PYTHONHOME=C:\Program Files\Python312` 定位标准库，不依赖 PATH）。
- **手动启动/停止**：
  - 启动：`bin\moot.exe bin\moot-service.py`（或双击 `start-moot.cmd`）
  - 停止：先 `netstat -ano | findstr 18080` 找 PID → `taskkill /F /PID <PID>`（守护会重启）；彻底停需结束守护进程（`wmic process where "name='moot.exe' and CommandLine like '%moot-service%'" get ProcessId`）。
  - 日志：`%LOCALAPPDATA%\moot\moot-service.log`

> 说明：当前用全局 Python 3.12 的 interpreter 副本（项目零依赖、纯标准库），不是独立 venv。若需完全独立 runtime（不依赖全局 Python 安装），应改用 PyInstaller 打包。

## 一句话目标

为 pi 生态提供跨项目的 **对等、双向、可持久、可审计** 的 Agent 通信与协同决策层。

## 两个核心原语

| 原语 | 用途 | 形态 |
|---|---|---|
| `moot issue` | 点对点异步协作 | 带状态、评论、验收标准、产物引用的工单抽象，下接 GitHub / GitLab / Redmine / Aside |
| `moot room` | 多点讨论到结论 | 议程 + 轮次屏障 + 收敛判据 + 确定性终止条件 |
