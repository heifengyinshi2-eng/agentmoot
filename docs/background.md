# agentmoot 背景与调研

> 调研时间：2026-11-11
> 状态：背景记录 / 方向待细化

## 1. 项目缘起

目标是为 pi 生态建立 Agent 之间的交互层，支持两类协作：

1. **点对点异步**：A 项目给 B 项目提 issue，B 项目审核 issue 并回复。
2. **多点同步或异步**：多个项目的 Agent 在同一个 group 中讨论一个问题，直到得出结论，类似开会。

现有 pi 能力的空缺：

- `subagent`：父子单向（父下发、子汇报），不是对等通信。
- `aside`：旁观者 → 项目 inbox 的单向 ticket，没有回复与状态回流。
- `redmine-cli`：面向人工工单，不是 Agent 通道。

因此需要一层**对等、双向、可持久、可审计**的通信与协作基础设施。

### 命名约定

- 项目名：**agentmoot**
- 具体工具名不带 `agent` 前缀：`moot issue`、`moot room`、`moot board`
- `moot` 作名词是"集会 / 辩论会"，`a moot point` 是"待议问题"——一个词同时覆盖 issue 与 meeting 两个场景。
- 备选名与取舍见第 6 节。

---

## 2. 场景拆解

### 2.1 点对点异步（issue 为核心）

核心对象是 **issue**：带状态、评论、验收标准、产物引用、幂等 ID。

需要一层**跨工单系统的抽象**：

```
moot issue  →  adapter  →  GitHub Issues / GitLab Issues / Redmine / Aside / 其他
```

对 Agent 暴露统一 API，对下做 adapter；Agent 不需要知道对方项目用的是什么工单系统。

推荐状态机（避免用自由文本表达状态）：

```
open → claimed → in_progress → (need_info ⇄ in_progress) → resolved → verified → closed
                                    ↘ rejected / cancelled
```

流程要点：

1. A 的 Agent `issue.create(target=B, type, spec, acceptance_criteria, evidence, idempotency_key)`
2. B 的 daemon 拉到后**先 `issue.claim` + ack**（SLA 内），而不是闷头就干
3. 信息不足 → `issue.need_info(具体缺什么)`，任务挂起而不是失败
4. 完成 → `issue.resolve(summary, evidence, artifacts)`，evidence 必须能对应 acceptance_criteria
5. A 侧 `issue.verify` → accept 或 reopen（reopen 必须带原因）
6. 超时未 ack → 自动催办 → 再超时 → 升级给人

三个必须做对的点：

- **验收标准合同化**：发起时就写清楚"什么算完成"，否则 Agent 之间会互相扯皮。
- **只交换 spec 和产物，不交换内部上下文**：对方不需要理解你的实现细节、记忆和工具。
- **不直接改对方仓库**：产出一份 patch / proposal，由确定性层或人应用。GitHub Agentic Workflows 的 safe-outputs 是同一思路。

### 2.2 多点讨论（room）

**不要做成持续聊天室**，而是做成"轮次屏障 + 提案—质疑—收敛"循环，天然支持异步：

```
Room: topic / participants / agenda[K 项] / chair / budget（轮次、时间、token）

每一轮：
  1. 各参与者独立提交（可先不看到别人 → Delphi 式，降低锚定）
  2. 每条发言结构化：{claim, evidence, open_question, proposal?}
  3. chair 汇总为 state.md：已达成 / 有分歧 / 未覆盖
  4. 满足终止条件 → decision.md（含少数派意见）；否则进入下一轮
```

**终止条件（确定性代码，不靠模型宣布"我们达成一致了"）：**

```python
done = (
    coverage(agenda) == 1.0            # 所有议程项都被明确处理
    and novelty(last_2_rounds) < ε     # 连续两轮没有新论点
    and consistency_score >= θ         # 无自相矛盾
) or rounds >= MAX or tokens >= BUDGET or wall_clock > DEADLINE
```

超限时不是继续吵，而是输出 `decision.md` + `open_issues.md` 并升级给人。可参考 COSMIC 的 coverage / consistency / stability 三指标。

防"开会发散"的具体手段：

- 每条发言必须有 `claim + evidence`，纯"我同意 / 我也觉得"由规则过滤，模型不参与判定
- 每轮每人每个议程项最多一条实质发言（发言配额）
- chair 与参与者**角色分离**：chair 只做汇总和判终止，不参与辩论
- 第一轮独立提交，之后再共享，避免第一个发言者带偏全场
- 不同模型 / 角色显式对抗（devil's advocate），而不是互相附和
- 人类 Overseer 通道永远存在且优先级最高

**同步 vs 异步**：用轮次屏障实现"准同步"，而不是真并发聊天。每个 Agent 在自己方便的时候提交当前轮，chair 在参与者到齐或超时后推进。跨时区、Agent 不在线都不阻塞，且每轮是一份可审计快照。

---

## 3. 市面方案调研

| 方案 | 定位 | 场景 1 | 场景 2 | 成熟度 / 备注 |
|---|---|---|---|---|
| **A2A (Agent2Agent)** | 跨组织 Agent 对等任务委托；AgentCard 发现、8 种任务状态、异步/流式；JSON-RPC / gRPC / REST | ✅ 很合适，`input_required` 对应"审核/要补充信息" | ❌ 任务中心的一对一委托，无多播/共享会话 | v1.0（2026-03），150+ 组织；线上实际仍大量跑 0.3 旧方言；只签 AgentCard |
| **MCP** | Agent 连工具/数据；2026 加入 Tasks 扩展、MCP Apps | △ 只能当"调用对方工具" | ❌ | 事实标准 |
| **Coral Protocol / CoralOS** | 用 MCP 工具实现 thread = Agent 群聊：`create_thread` / `send_message` / `@mention` / `wait_for_mention` | △ 可用，但偏运行时内协作 | ✅ 最接近场景 2 的开源形态 | 可用；session 有 TTL，不是长期项目级工作流 |
| **Claude Code Agent Teams** | 共享 task list + 每 Agent 一个 JSON mailbox + 直发消息 + lead | ✅ mailbox 模式可借鉴 | △ 单 session、实验性、ephemeral、一个 lead 只能带一个 team、不能嵌套 | 实验特性 |
| **MCP Agent Mail + Beads** | Git+SQLite 的 Agent 邮件：身份、inbox、thread、ack、优先级、跨项目 contact、文件租约、人类 Overseer | ✅ 场景 1 最完整的工程参考 | △ 有 thread，但无议程/收敛/终止 | 2025-10 起活跃；偏同机多 coding agent |
| **GitHub Agentic Workflows** | label / slash command 触发 Agent；Agent 只读，写操作走 safe-outputs；带 confidence / approval / rationale | ✅ 可直接落地 | ❌ | 生产可用，绑定 GitHub |
| **AutoGen GroupChat / CrewAI / LangGraph** | 进程内多 Agent 编排、speaker selection | △ | △ 只在单进程内，重启即失 | 成熟但非分布式 |
| **COSMIC（学术）** | GroupChat + leader 心跳，用 coverage / consistency / stability 判终止 | — | ✅ 终止条件可直接借用 | 论文级 |
| **PACE / IoA Task Protocol（IETF）** | PACE 在 A2A/MCP 之上补多方 dialog 生命周期；IoA 补注册、嵌套团队、会话状态机 | — | 方向正确 | draft（2026），不宜现在依赖 |
| **mail-swarms (MAIL)** | MAIL 消息信封、swarm 间联邦、REST + SSE | △ 联邦思路可参考 | △ | 小众 |
| **Nexus（私有）** | broker / relay / frame-funnel、跨机 Agent 协作 | — | 架构参考 | 未开源 |

### 关键判断

1. **传输层有标准，协作语义没有。** A2A 解决"怎么互认派活"，不解决"怎么验收、怎么开会"。
2. **已送达 ≠ 已完成。** 所有方案都只解决"怎么传"，不解决"对方真的做了没有、做得对不对"。
3. **A2A 只签 AgentCard，消息和产物不签名；跨组织授权明确留给使用方。** 身份、授权、验收必须自建。
4. **群聊类方案都死在三个地方**：上下文爆炸、互相客气导致假共识、无限循环。终止条件必须是确定性代码。
5. **消息不是主体，事件日志才是。** 聊天、工单页、Redmine 都只是日志的视图；这样重启、换模型、人接管都不丢状态。
6. **越权与安全**：A 不能借 B 的手执行危险操作；默认最小权限，不可逆动作必须人工闸门。

---

## 4. 设计方向

### 4.1 分层

```
L4 治理层      确定性守门：轮次上限 / 预算 / 去重 / 反对意见 / 人工闸门
L3 运行时      每个项目的 agent daemon：poll inbox → 唤醒 pi → 执行 → 回写
L2 交互原语    Issue（P2P 异步） + Room（多点讨论）
L1 持久事件总线  append-only log + 线程索引（SQLite / JSONL / Git）
L0 身份与寻址   project_id + agent_id + capability card + token
```

### 4.2 统一事件模型

```yaml
Event:
  id: ULID
  thread_id: <issue-id 或 room-id>
  type: issue.created | issue.claimed | issue.need_info | issue.resolved
      | comment.added | proposal.made | objection.raised
      | round.summary | decision.accepted | task.completed | escalated
  sender: projectA/agent-x
  causation_id: <触发它的上一条事件>
  payload: { schema_version, ... }   # JSON Schema 强约束
  artifacts: [uri]                   # 大内容只传引用，不塞进消息
  ts: ISO8601
```

- **单写者 append-only**：每个 Agent 只追加自己的分片文件，读时合并，从根上消灭并发写冲突。
- **幂等**：`idempotency_key` + 去重窗口；handler 必须可重放。
- **能力声明**：每个项目一份 `agent-card.json`（能力、可接受任务类型、SLA、鉴权方式）。

### 4.3 存储与传输

- 存储：SQLite 作索引 + 每 Agent 一个 append-only JSONL 分片 + 定期 Git 归档（审计、可回放）。
- 传输：本地文件即可起步；远程用 HTTP + SSE；对外暴露 MCP 工具。
- 外部适配：A2A 只作为对外协议适配器，内部不直接依赖其 wire format。
- 唤醒：项目侧 daemon 轮询 inbox 或 webhook → 起 headless pi → 回写；失败进 dead-letter 队列。

### 4.4 人机边界

- 人类 Overseer 通道永远存在，优先级最高。
- 只在超限、不可逆操作、跨项目授权时强制人工确认；其余自动流转。
- 所有决定落盘为 decision record，保留少数派意见与证据链。

---

## 5. MVP 路径

| 阶段 | 内容 |
|---|---|
| P1 | issue 抽象 + 事件总线：SQLite 索引 + JSONL 分片 + MCP `issue.*` 工具 + CLI |
| P2 | Ticket 状态机 + ack / SLA / 催办；接入 Aside ticket 格式；Redmine 双向镜像 |
| P3 | Room：round / chair / state.md / decision.md / 确定性终止条件 |
| P4 | 项目侧 daemon：轮询 → headless pi → 回写；dead-letter |
| P5 | A2A AgentCard / JSON-RPC 适配器（仅对外） |

先做场景 1：边界清楚、价值直接，可验证"身份 + 幂等 + 验收"三件事。场景 2 复用同一套 thread / event 模型，不另起系统。

---

## 6. 命名决策

**最终：`agentmoot`**（工具名 `moot`，不带 agent 前缀）

- 双关：集会 / 辩论 + 待议问题。
- 符合现有命名风格：`aside`、`seedflow`、`subagent`、`relay` 都是短、小写、单意象。
- CLI 自然：`moot issue new`、`moot issue reply`、`moot room open`、`moot inbox`。
- 可动词化："这个先 moot 一下"。

备选与排除：

| 名字 | 结论 | 原因 |
|---|---|---|
| `commons` | 备选 | 共享空间 + 下议院；与 Creative Commons 联想 |
| `parley` | 备选 | 跨项目谈判意味最准；偏对抗色彩 |
| `curia` / `witan` | 备选 | 独特但冷僻，认知成本高 |
| `agora` | 排除 | 国内技术圈对 Agora = 声网 的联想太强 |
| `relay` | 排除 | 已有 `agent-relay` |
| `nexus` / `hub` / `bus` / `forum` / `board` | 排除 | 太泛、重名严重 |
| `docket` | 排除 | 与 docker 只差一个字母 |
| `envoy` / `consul` / `quorum` | 排除 | 已被成熟基础设施产品占用 |

补充事实：

- npm 上 `moot` / `commons` / `parley` / `curia` / `witan` 等裸名均已被占用，发布时使用 scope（如 `@piworkspace/moot`）。
- npm 上已有 `roundtable` 包，描述为 "Multiple Claude Code agents debate. One moderator synthesizes."，因此会议模块不叫 roundtable，叫 `room`。

---

## 7. 未决问题

- [ ] issue 抽象的最小公约数：哪些字段能同时映射 GitHub / GitLab / Redmine / Aside？
- [ ] 状态机严格对齐 A2A 的 8 态，还是按自身语义自定义？
- [ ] 会议是否允许子 room（嵌套议程），还是单层轮次？
- [ ] 身份与授权粒度：项目级 token 还是 agent 级 token？
- [ ] 唤醒机制：轮询、webhook、长连接如何取舍？
- [ ] 人在环的位置：只在超限 / 不可逆操作时介入，还是每个 decision 都要确认？
- [ ] 与 Aside / Redmine 的边界：谁是 source of truth？
- [ ] 多模型输出格式漂移：JSON Schema 校验失败后的重试与降级策略？

---

## 8. 参考

- A2A Protocol — https://a2a-protocol.org/
- Linux Foundation A2A 一周年 — https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year
- Coral Protocol Threads — https://docs.coralos.ai/concepts/threads
- Claude Code Agent Teams — https://code.claude.com/docs/en/agent-teams
- MCP Agent Mail — https://github.com/Dicklesworthstone/mcp_agent_mail
- Beads — https://github.com/steveyegge/beads
- GitHub Agentic Workflows — https://github.github.io/gh-aw/
- COSMIC: Leader-Driven Context-Oriented Collaboration Between Agents — https://ieeexplore.ieee.org/document/11417193
- PACE: Protocol for Agent Communication Exchange (IETF draft) — https://datatracker.ietf.org/doc/draft-nandakumar-agentproto-pace/
- IoA Task Protocol (IETF draft) — https://datatracker.ietf.org/doc/draft-yang-dmsc-ioa-task-protocol/
