# mcp-notify：MCP 接口 + 事件通知 + pi extension 集成

## 目标

把 moot 从「REST + CLI」升级为「标准 MCP 接口 + SSE 事件通知」，并配一个 pi extension 做会话启动注入与通知订阅，让真实 pi agent 能通过标准 MCP 连接调用 moot、并被动收到「有活要干」的唤醒信号。

## 需求

1. **MCP 接口**：moot 服务暴露 Streamable HTTP MCP 端点（`/mcp`），把 store 方法映射为 `moot_*` 工具；pi 通过 `.pi/mcp-servers.json` 配置连接，用 `mcp_tools`/`mcp_call` 调用。不再依赖 CLI。
2. **事件通知**：moot 服务暴露 SSE 端点（`/events`），事件日志按 project 投影为通知流；支持断线重放（`after` 游标 / `Last-Event-ID`），服务端永久保留事件（append-only）。
3. **pi extension**：会话启动时注入 moot 上下文（身份 + 服务地址 + 待办），可选订阅 SSE 唤醒 agent。
4. 保持零第三方依赖（服务侧仍仅标准库）；状态机 `store.py` 不改业务逻辑。

## 设计

### 通知 = 事件日志的订阅投影

- store 已是 append-only `events.jsonl`，每次变更 `_event(type, ...)` 追加一行，payload 含目标方（assignee/creator/participants/chair）。
- 通知**不另建存储**：给事件加全局单调序号 `seq`，用 `notify_targets(event) -> [project]` 纯函数把事件投影为目标 project 集合，投递 = 从 project 的游标位置重放日志。
- 语义：**at-least-once + 幂等**。通知是「唤醒信号」，可重复、可丢；权威状态由 `moot_list_pending` 拉取保证。agent 上线先无条件拉一次，正确性不依赖通知链路。

### MCP 端点（Streamable HTTP，最简实现）

- `POST /mcp`，JSON-RPC 2.0 over HTTP；响应单 JSON（不用 SSE 流式）。
- 实现四个方法：`initialize`（返回 protocolVersion 2025-06-18 + capabilities.tools）、`notifications/initialized`（202）、`tools/list`（返回工具清单 + inputSchema）、`tools/call`（执行并返回 content）。
- 工具映射 store 方法 + 便捷 `moot_list_pending(project)`（一次返回某 project 全部待办：assignee 的 issue + 待表态 room）。

### SSE 端点

- `GET /events?project=X&after=SEQ`：把 `seq > after` 且 `X ∈ notify_targets(ev)` 的事件逐条推为 SSE event，`id` = seq，`retry` 提示重连。
- 游标 `state["cursor"][project]` 持久化（尽力而为，丢了重放无害）。

### pi extension（TypeScript）

- `session_start`：从配置读 moot 地址 + 本项目身份，注入上下文。
- `before_agent_start`：把「我是谁、moot 在哪、当前待办」追加进 system prompt（或注入 message）。
- 常驻订阅（可选/后续）：挂 `/events` SSE，事件到达 `sendUserMessage` 唤醒。

## 测试

- `tests/test_mcp.py`：起服务 → MCP initialize 握手 → tools/list → tools/call（create issue）→ 断言状态流转。
- `tests/test_events.py`：造事件 → SSE 拉流断言收到 → 断线后 `after` 游标重放断言补发。
- 真实 pi 集成：`.pi/mcp-servers.json` 配 moot → `mcp_tools(server="moot")` 可见工具 → `mcp_call` 跑通。

## 验收标准

- [x] `POST /mcp` initialize/tools/list/tools/call 全流程通过，非法参数返回 JSON-RPC 错误。
- [x] `GET /events?project=X&after=N` 只推 X 相关事件；`after` 断点重放不漏。
- [x] 事件带全局 `seq`，事件日志 append-only 不变。
- [x] `moot_list_pending` 返回某 project 的 issue + room 待办。
- [x] extension 加载后 agent 知晓 moot 地址与身份（真实 pi -p 验证通过）。
- [x] 全零第三方依赖（服务侧仅标准库）。

## 任务列表

- [x] store.py：`_event` 加全局 seq；`notify_targets(event)` 投影；`list_pending(project)` 便捷查询；cursor 持久化
- [x] server.py：`/mcp` JSON-RPC 端点（initialize/tools/list/tools/call）
- [x] server.py：`/events` SSE 端点（project 过滤 + after 重放 + once 参数）
- [x] tests/test_mcp.py + tests/test_events.py 编写并跑绿（11 passed）
- [x] pi extension（`.pi/extensions/moot.ts`，before_agent_start 上下文注入）
- [x] `.pi/mcp-servers.json` 配置 + 真实 pi 集成验证（官方 SDK 连接 17 工具 + agent 自主评审闭环）
- [x] 文档更新（README/design/implementation）

## 更新记录

- 2026-11-12 建计划（L2），设计基于前几轮 MCP/通知协议讨论结论。
- 2026-11-12 store/server/tests/extension 全部实现；官方 SDK 连接验证 17 工具；真实 pi agent 自主完成「查待办→评审 I-001」闭环；SSE 通知流 project 过滤 + after 重放验证通过。

## 备注

- MCP 协议版本用 2025-06-18（经典 Streamable HTTP，官方 SDK 必然支持）。
- pi-mcp 用 `@modelcontextprotocol/sdk`，已确认三 transport；moot 走 Streamable HTTP（url 配置）。
- extension 放项目 `.pi/extensions/moot.ts`（项目级，auto-discover）。
