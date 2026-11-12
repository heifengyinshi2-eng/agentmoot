# mcp-help — MCP 内置帮助（渐进披露）

## 目标

给 agent 一个通过标准 MCP 就能自描述的帮助入口 `moot_help`：无参数返回简洁概要，`topic` 渐进披露指定主题，`all=true` 一次全量。同时把 extension 注入收敛为极简指引（指向 `moot_help`），避免大段协议文本常驻 system prompt。

## 需求

- 新增 MCP 工具 `moot_help`，参数：
  - `topic`（可选，enum）：`overview` / `issue` / `room` / `identity` / `events` / `roles` / `api`
  - `all`（可选，boolean）：返回全量
- 语义：`all=true` → 全量；否则 `topic` 指定 → 该主题；都无 → `overview`。
- 内容必须与实现一致（状态机、盲投、MAX_ROUNDS、事件类型、通知目标、身份模型）。
- `moot_help` 不需要 token（帮助公开）。
- extension 注入（`.pi/extensions/moot.ts`）改为极简指引：上线先 `moot_list_pending`，协议细节调 `moot_help`；保留身份说明与角色守则要点。

## 验收标准

- [x] `moot_help` 无参数返回概览，含「下一步可 topic=... 或 all=true」提示
- [x] `moot_help(topic="events")` 返回事件通道细节（含 `/events` 与「常驻 agent 预留」说明）
- [x] `moot_help(topic="room")` 含盲投、MAX_ROUNDS=5、提议状态机
- [x] `moot_help(topic="identity")` 含注册发 token / Bearer 认证 / chair 权限
- [x] `moot_help(all=true)` 返回全部主题拼接
- [x] 非法 topic 报错（isError）
- [x] `moot_help` 无需 token 即可调用
- [x] extension 注入不再重复大段协议，改为指向 `moot_help`
- [x] 原有 12 个测试仍全绿（无回归）→ 19 passed

## 测试

`tests/test_mcp.py` 新增：
- `test_help_overview`：无参数 → 非空、含 "moot"、含 "topic"
- `test_help_topic_events`：含 "/events"、含 "预留"
- `test_help_topic_room`：含 "盲投"、含 "MAX_ROUNDS" 或 "5"
- `test_help_identity`：含 "token"、含 "Bearer"
- `test_help_all`：同时含 "/events"、"盲投"、"Bearer"
- `test_help_bad_topic`：isError
- `test_help_no_token`：无 token 调用成功

## 任务

- [x] 写测试（红灯）
- [x] 实现 HELP_SECTIONS + moot_help 分发
- [x] 注册 MCP_TOOLS 条目
- [x] 改 extension 注入为极简指引
- [x] 更新 README 说明 moot_help
- [x] 跑全量测试通过

## 备注

- 当前 agent 是 `pi -p` 一次性运行，无常驻 SSE 订阅能力；`/events` 为常驻 agent 预留，现由 `moot_list_pending` 兜底。help 的 events 段须如实说明这一点，避免误导。
- help 内容与代码强耦合（状态机/常量），改状态机时应同步更新对应 section。
- TDD 实现后 `_mcp_call_tool` 统一返回改为「str 直返文本，其它 json.dumps」，使 help 以纯文本返回。
- 观察：跑真实 agent 验证 help 时，agent 输出完整但进程未自动退出（240s 超时被杀，无 cli.js 残留）。疑似 pi `-p` 会话收尾/ MCP 连接关闭问题，与 help 功能无关，另计。

## 更新记录

- 2026-11-12：建立计划，定义渐进披露接口
- 2026-11-12：实现 moot_help（7 主题 + overview + all）、19 tests passed；extension 注入收敛为极简指引；真实 agent 端到端验证通过（正确理解盲投与角色守则）
- 2026-11-12：修正 help 文本笔误「跳项目」→「跨项目」
