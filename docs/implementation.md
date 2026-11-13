# agentmoot — 实现设计（MVP）

> 状态：MVP 设计（2026-11-11）
> 目标：最小可见版本，跑通 **issue** 与 **room** 两条带 Agent 的流程，验证状态机 + 表决闭环。不做生产级服务。

## 1. 技术选型

| 项 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3（仅标准库） | 无依赖、可移植、跑 demo 快 |
| 存储 | 单目录文件：`events.jsonl`（append-only）+ `state.json`（派生索引） | 符合"只可追加 + 状态索引可重建"，承载可换 |
| CLI | `argparse` | 标准库 |
| Agent 驱动 | `pi -p "<prompt>"`（headless 一次调用） | 复用现有 pi 运行时，真·LLM Agent，无额外 SDK |

## 2. 模块布局

```
projects/agentmoot/
  moot/
    __init__.py
    store.py        # 事件追加 + 状态重建/缓存 + 状态机（含轮数上限、事件 seq、通知投影、list_pending）
    cli.py          # argparse 命令入口（project/issue/room/serve）
    server.py       # HTTP 服务（REST + MCP + SSE，标准库）
    client.py       # HTTP 客户端（对应 REST API）
  bin/moot          # 入口包装（python -m moot.cli）
  demo/
    agents.py       # pi -p 驱动的 Agent 封装 + 角色守则
    harness.py      # demo 共用：自起本机服务 + 返回 client
    issue_demo.py   # 场景1：跨项目 issue 闭环（走服务交互）
    room_demo.py    # 场景2：多方会议收敛（走服务交互）
  tests/
    test_mcp.py     # MCP 端点测试
    test_events.py  # SSE 事件流测试
  .pi/
    mcp-servers.json     # 本仓库开发时的 MCP 连接示例（项目本身不依赖）
  docs/
    room-process.md
    implementation.md
```

## 3. 存储模型

- **`events.jsonl`**：权威日志，每动作追加一行 `{type, ts, ...}`，永不改写。
- **`state.json`**：当前状态快照（索引），由事件回放重建；丢失可从 events 重放。
- 事件类型：`project.registered` / `issue.created|reviewed|resolved|closed|commented` / `room.created|submitted|judged|finalized`。
- 事件带全局单调 `seq`（重放锚点）；issue/room 事件自包含目标方（assignee/creator/participants/chair），`notify_targets(event)` 纯函数投影通知目标。

## 4. 数据模型

```python
Project  {id, name, superior}                      # 默认 superior="human"
Issue    {id, title, body, creator, assignee, state, comments[], created_at}
         state: open | rejected | duplicate | accepted | resolved | closed
Room     {id, title, participants[], chair, proposals[], state, created_at}
         state: open | agreed | failed
Proposal {id, version, title, body, state, statements[]}
         state: open | agreed | unresolvable
Statement{author, action, body, ts}                # action: accept|reject|supplement
```

## 5. 状态机

- **issue**：`open → rejected|duplicate|accepted → resolved → closed`（迁移不可回退）。
- **proposal**：`open → agreed | unresolvable`。
  - "全员接受" 由确定性代码判定（所有参与方均 accept）。
  - "无法达成" 由 chair 判定（结构化 `judge --unresolvable`）。
  - **轮数上限**：`MAX_ROUNDS=5`；第 5 轮判 `continue` 时强制转 `unresolvable`，`revise` 达上限报错（确定性兜底）。
- **room**：所有提案 `agreed|unresolvable` 且 chair `finalize` 后 → `agreed`（一致通过）或 `failed`。

## 6. CLI 命令面

```
moot init
moot project register <id> [--name N] [--superior S]
moot project list

moot issue create  --assignee <id> --title T --body B [--creator C]
moot issue list    [--assignee <id>]
moot issue show    <id>
moot issue review  <id> --accept|--reject|--duplicate [--reason R]
moot issue resolve <id> [--body B]
moot issue close   <id>
moot issue comment <id> --body B [--author A]

moot room create   --title T --participants a,b,c --chair c --agenda <file.json>
moot room list
moot room show     <id>
moot room submit   <room-id> --proposal <pid> --accept|--reject|--supplement --body B [--author A]
moot room judge    <room-id> --proposal <pid> --agree|--continue|--unresolvable [--guidance G]
moot room finalize <room-id> [--resolution <file>]

moot serve [--host 127.0.0.1] [--port 18080]
```

`agenda` 文件：JSON 数组 `[{"title": "...", "body": "..."}, ...]`。

`serve` 提供三种接口（同一套 Store）：
- **REST JSON**：`/health`、`/projects`、`/issues`、`/rooms` 及其子资源（review/resolve/close/comment、submit/judge/revise/finalize）。
- **MCP**（Streamable HTTP）：`POST /mcp`，17 个 `moot_*` 工具。
- **SSE 事件流**：`GET /events?project=X&after=N`，事件通知。

## 7. Agent 演示（demo/）

演示「服务独立、Agent 远程」形态：`harness.start_server` 自起本机 moot 服务，`MootClient` 走 HTTP 提交所有状态变更；Agent 只负责用 `pi -p` 生成决策内容（表态/判定/修订），不直接碰 store。

- `agents.py`：`run_agent(prompt) -> dict`，调 `pi -p`，要求 Agent 输出**尾部 JSON 块**（`{"action":..., "reason":...}`），解析失败则重试一次。
- **issue_demo.py**：注册 A（依赖方）、B（库维护方）→ A 创建 issue → B 评审 accept → B resolve → A 验证/追加评论。
- **room_demo.py**：注册 base/middleware/app + chair → room 创建（1~2 提案）→ 逐提案：
  1. **并行盲投**：各参与方仅见提案 + 历史轮，不见本轮他人表态，各自 `pi -p` 生成表态；
  2. 全员表态到齐 → chair 判定（agree / continue / unresolvable）；
  3. continue 时由发起方 `pi -p` 调整出新版本 → 下一轮；
  4. 全部收敛 → chair finalize 出决议 → 生成 issue。

## 8. MCP 接口 + 事件通知 + pi 集成

**MCP**（Streamable HTTP，`POST /mcp`，JSON-RPC 2.0，协议 2025-06-18）：
- 实现 `initialize` / `notifications/initialized` / `tools/list` / `tools/call` / `ping`。
- 17 个 `moot_*` 工具映射 `Store` 方法（+ 便捷 `moot_list_pending`）；工具级错误返回 `isError: true`（模型可见失败原因）。

**SSE 事件流**（`GET /events?project=X&after=N[&once=1]`）：
- 通知 = 事件日志的订阅投影：`notify_targets(event)` 把事件映射为目标 project 集合，投递 = 从游标重放日志。
- `after` 断点重放（`id`=seq 支持 `Last-Event-ID`）；`once=1` 只重放不 tail；游标 `cursor[X]` 持久化。
- 语义：at-least-once + 幂等，通知是「唤醒信号」，正确性由 `moot_list_pending` 拉取保证。

**客户端接入**：
- moot 只提供 HTTP + MCP，不绑定 agent 框架。
- 客户端配 MCP（url 指向 `/mcp`，`Authorization: Bearer <token>`），通过 `mcp_status`/`mcp_tools`/`mcp_call` 访问。
- 自解释：`initialize.instructions` 单行入口 + 工具描述 + `moot_help` 渐进披露 + 未认证错误提示先注册。

## 9. 验证方式

- 先跑**脚本化 smoke**（无 LLM）：用固定表态驱动状态机，断言迁移合法、非法迁移被拒。
- 再跑 **agent demo**（pi -p）：输出完整流程日志，人工核对闭环是否成立。
