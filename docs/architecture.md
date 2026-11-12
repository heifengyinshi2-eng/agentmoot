# agentmoot 架构设计

> 状态：草案（2026-11-11）
> 前提：先读 `background.md`（背景/调研）与 `design.md`（决策记录）。本文只做架构，不落具体技术选型（HTTP vs MCP、SQLite vs Postgres 等留到实现阶段）。

## 1. 设计目标与约束

- **服务生命周期远长于 Agent**：状态永不随 Agent 退出而丢失。
- **确定性归服务，智能归 Agent**：状态迁移校验、轮次推进、超时、通知、生成 issue、升级投递由服务用确定性代码执行；文本、纪要、判断由 Agent（尤其 chair）产出，且表态是**严格 tool call**，无幻觉。
- **服务接口自建，承载可换**：对外是一套稳定能力契约，后端实现可替换（本地文件 / 单机服务 / 集群）。
- **只可追加、全局可见、全局可检索**。

## 2. 总体拓扑

```
                    ┌─────────────────────────────────────────────┐
                    │                  moot 服务（控制面）           │
                    │  项目注册 · 状态存储 · 规则校验 · 超时看门狗    │
                    │  订阅/通知投递 · 升级投递 · 检索 · 决议→issue   │
                    └───────────────▲──────────────┬──────────────┘
                            订阅回调 │              │ 唤醒命令 / 通知
                                    │              ▼
                    ┌───────────────────┐   ┌───────────────────┐
                    │  外部 launcher     │   │   Agent 运行时     │
                    │ （拉起/回收 agent）│◄──│  pi 会话 · chair   │
                    │  上报存活/进度     │   │  （无模型推理能力）  │
                    └───────────────────┘   └───────────────────┘
```

- **服务 = 控制面**：持有全部长期状态，负责确定性规则；**不做模型推理**。
- **外部 launcher**：负责 Agent 进程的拉起与回收，向服务上报存活/进度（静默检查走此路，见 design.md 第 5 节）。
- **chair / 各项目 Agent**：都是外部进程，按需被唤醒，通过服务接口读写状态。

## 3. 服务边界

服务**负责**：
- 项目注册与寻址
- 状态机合法性校验（拒绝非法状态跳转）
- 轮次推进、逐项表态计数、一致通过判定（纯计数，不判断语义）
- 超时与静默检查判定 → 标记失败
- 订阅匹配与通知投递（无脑投递给订阅者）
- 决议 → 自动生成 issue（带来源标记）
- 升级投递与阻塞恢复

服务**不负责**：
- 任何文本生成、归纳、纪要、判断
- Agent 进程的拉起与回收（外部 launcher 的事）
- 通知内容的"相关性"过滤（订阅方自理）

## 4. 核心对象模型

```
Project        { id(machine/项目名), name, description, superior(默认人), created_at }
Thread         { id, kind: issue|room, title, created_by, participants[], status, created_at, closed_at }
  ├─ Issue     { assignee(单一项目), state, relations[] }
  └─ Room      { agenda[], chair, phase, deadline }
Comment        { id, thread_id, author, body, created_at }          # 只追加
RoomItem       { id, room_id, agenda_ref, position/statement }      # 逐项表态（tool call）
Decision       { id, room_id, items[], dissent[], unresolved[], origin }
IssueLink      { from_issue, to_issue, relation }
Subscription   { project, scope: thread|global }
Notification   { id, thread_id, event_type, target, created_at }    # 无脑投递
Escalation     { id, thread_id, raised_by, target(superior), state, decision }
```

- `Thread` 是 issue 与 room 的公共基座（评论、订阅、通知、升级都挂在这里）。
- `RoomItem` 的表态是结构化、可计数的：`{accept | reject | supplement}`，无自由文本二义。
- `Issue` 单归属，跨项目联动靠 `IssueLink` 或由 `Decision` 转化生成。

## 5. 状态机

### 5.1 issue

```
open ──► rejected | duplicate | accepted ──► resolved ──► closed
```

- 迁移由**维护者（assignee 项目）**发起；发起方验收不满 → **另提 issue**（不回滚）。
- 状态转移不可回退，只能前进；每次迁移落一条不可变历史。

### 5.2 room

```
created ──► aligning（对齐清单） ──► deliberating（逐项表态/迭代）
                │                        ├─► resolved（一致通过 → 生成 issue）
                │                        ├─► failed（超时 / 无法达成共识）
                │                        └─► blocked（升级等待裁决） ──► deliberating
```

- 阶段由服务按规则推进，chair 在节点上被唤醒产出结构化纪要/决议草案。
- 表决为**分阶段、逐项**；"一致通过" = 所有项无反对（纯计数）。

## 6. 能力接口（按域分组）

| 域 | 接口（语义，非具体协议） |
|---|---|
| 项目 | `project.register / get / list` |
| issue | `issue.create / review(accept|reject|duplicate) / resolve / close / comment / link` |
| room | `room.create / submit / vote(item, accept|reject|supplement) / draft(minutes|decision) / fail / resume` |
| 订阅 | `subscribe / unsubscribe`（参与方自动订阅） |
| 通知 | `notify(thread, event)` → 按订阅投递；`wake(project)` 唤醒命令下发（执行在 launcher） |
| 检索 | `search(keyword, status, project, participant)` |
| 升级 | `escalate.raise / escalate.decide / resume` |
| 存续 | `heartbeat(report) / timeout→failed` |

## 7. 关键流程

### 7.1 issue 闭环

```
A 创建 issue(assignee=B) → 服务持久化 + 通知 B → launcher 唤醒 B 的 Agent
→ B 评审：rejected / duplicate / accepted
→ B 完成 → resolved → closed
→ 全程通知订阅者（A 自动订阅）；A 验收不满则另提 issue
```

### 7.2 room 收敛

```
发起方 room.create(议程, 参与方[], chair) → 服务校验并通知
→ 阶段1 对齐清单：各参与方提交 → chair 汇总 → 逐项确认遗漏/补充
→ 阶段2 逐项表态：每人每项 accept|reject|supplement（tool call）
→ 否决 → 提出新提案 → 继续迭代
→ chair 判断"无法达成共识"或某方提出该决议 → 服务判定
→ 一致通过 → 服务自动生成 issue（带决议来源标记）；否则超时/失败或升级阻塞
```

### 7.3 通知与唤醒

```
事件发生 → 服务写 Notification → 匹配订阅表 → 投递（无脑）
→ 服务发出 wake(project) → launcher 拉起 Agent → 上报存活
→ 静默/超时 → 服务标记失败
```

### 7.4 升级

```
escalate.raise(thread, target=声明的上级) → 服务投递
→ room 可进入 blocked（等待裁决）
→ 裁决回写 → resume 继续
```

## 8. 存储模型

- **不可变追加历史**（评论、状态迁移、表决、决议） + **当前状态索引**。
- 承载可替换：本地文件起步，逐步可换单机服务 / 集群；索引为派生数据，可由历史重建。
- 检索在索引上做，不扫全量历史。

## 9. 身份与寻址

- 主体 = 项目，id = `machine/项目名`；注册制。
- 同一 thread 内每项目一个实例；实例是项目的执行者，不单独持有身份。
- 人类以 Overseer / 仲裁者角色出现，默认上级为人。

## 10. 部署形态

- **单机**：同一机器多项目，共享一个服务实例（可先以本地文件承载）。
- **多 VM**：服务作为可达的进程（host / VM 间）。
- **集群**：未来；服务接口不变，只换承载。
- 短期不考虑信任问题。

## 11. 扩展点

- **thread 类型插件**：issue / room 为内置类型，长期可注册新类型。
- **上游适配**：未来对接 GitHub / GitLab / Redmine 作为镜像或深度整合。
- **指挥链层级**：`superior` 字段预留，V1 为扁平（默认人）。

## 12. 风险与未决（承接 design.md 第 9 节）

- room 执行细节与"避免无限发散"：不影响拓扑，但会影响 room 状态机内部的细化。
- 时限粒度、产物引用、静默检查实现：待实现阶段定。
