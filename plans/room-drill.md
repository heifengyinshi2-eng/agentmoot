# room-drill：多方协调案例（信息差隔离）

## 目标

在现有 base-lib / middleware / app 三方基础上，追加一个「不拉起 room 就难解决」的任务，用真实 agent 走通 room 流程，产生 room 展示数据。

## 场景：订单金额的类型契约与展示规范

衔接 I-001（大整数序列化已修复）：订单 `amount` 字段（Number）存在浮点精度 + 展示格式两个新隐患。三方立场天然冲突（信息差隔离）：

| 项目 | 角色 | 立场（各自只知道自己的局部约束） |
|---|---|---|
| app | 发起方（creator） | 展示要币种 ¥ + 千分位 + 两位小数，但数据源类型不明确 |
| base-lib | 表态方 | 金额应字符串无损传输（防浮点精度 0.1+0.2 丢失） |
| middleware | 表态方 | amount 保持 Number，便于订单汇总/统计/求和 |

点对点 issue 会陷入踢皮球（诉求冲突），需 room 对齐。

## room 定义

- title：订单金额的类型契约与展示规范
- participants：base-lib / middleware / app
- chair：human（独立主席，只引导不给方案）
- agenda：1 个提案 P1（creator=app）

## 流程（四段式）

1. chair 创建 room
2. base-lib / middleware 各自查待办 → 表态（信息差隔离 prompt，各自只给立场）
3. chair judge（分歧则 continue + 引导）
4. 需要时 creator（app）revise 出新版本 → 再表态 → 收敛
5. chair finalize 汇编决议

## 验收标准

- [x] room 创建成功，三方参与
- [x] 两个表态方真实走「查待办 → get room → submit」
- [x] chair 完成 judge（多轮 continue 引导）→ finalize，room 状态 agreed
- [x] resolution 记录三方对齐的金额契约
- [x] Web UI dashboard 能看到 room（R-001 agreed + 参与方 + 提案）

## 实战结果（真实 agent 多轮收敛）

R-001「订单金额的类型契约与展示规范」，chair=agent，participants=[base-lib, middleware, app]，提案 P1（creator=app）。四轮收敛：

| 轮 | 动作 | 分歧/收敛点 |
|---|---|---|
| v1 | base-lib supplement（金额必须 String 无损）、middleware supplement（金额必须 Number 整数分可运算） | 双方 String vs Number 实质分歧 |
| v2 | app revise 出「双表示同源」：amount 字符串真值 + amount_minor 整数投影 | middleware accept；base-lib supplement（指出「性能优先降级分支」会让 amount 可选，破坏无损） |
| v3 | app revise 收紧：amount 必填不可降级、废除降级分支、total_minor 纳入不变量 | base-lib accept；middleware supplement（指出 amount_minor 改纯可选对其「汇总不 parse」是回退） |
| v4 | app revise 协调两层可选性：L1 字段层 amount_minor 可选 + L2 消费接口层 compute/display 按用途必填 | base-lib + middleware 均 accept → chair judge agree → finalize |

最终决议：money/v2 契约（amount 字符串唯一真值不可降级、amount_minor 字段层可选但 compute 路径必填、currency+scale、一致性机检、链路禁 double、格式化归 app）。

信息差隔离体现：每个 agent 的 prompt 只给自身局部立场（base-lib 只知字符串原则、middleware 只知运算需求），各自基于局部信息表态，产生真实理解误差；但通过 moot_get_room 看到对方已表态内容后，能针对性补充/质疑，最终在 chair 引导下收敛。

## 更新记录

- 2026-11-12 建计划（L1）。
- 2026-11-12 执行完成：R-001 四轮收敛（v1→v4），room 状态 agreed，决议 money/v2，dashboard 可展示。
- 2026-11-12 chair 标注修正：R-001 chair `human` → `agent`（chair 是 agent 扮演的独立协调者，非人类）；页面显示「主席 agent」。
- 2026-11-12 盲投 A：`store.room_view(rid, actor)` 加盲投投影——`moot_get_room` 传 `actor` 时屏蔽「当前版本 && 其他方」的 statements（后表态方看不到先表态方本轮内容，防 anchoring）；历史版本/chair 判定/本人表态可见；actor=None 或 chair 看全量；REST `GET /rooms/{id}`（Web UI 复盘）保持全量。新增 `test_room_blind_view` 测试（12 passed）。
- 2026-11-12 发言收束：committee-code.md + extension 注入补「针对修订案（v≥2）发言结构」——简要肯定认可部分（已认可且未变的不重复）→ 说明不认可部分 → 简要提诉求（方向即可）；chair 发言遵循界限（遵守议程要求、不盲从总结）。

## 实战二：R-003 时间戳契约（盲投 + 发言收敛验证）

R-003「时间戳的表示与展示规范」，chair=agent，participants=[base-lib, middleware, app]，提案 P1（creator=app）。信息差隔离：base-lib 只知「存储/传输无损+可排序+紧凑→int64」、middleware 只知「日志/审计可读+无时区歧义→RFC 3339」、app 只见「展示诉求」。四轮收敛（v1→v3 + agree）：

| 轮 | 动作 | 结果 |
|---|---|---|
| v1 | base-lib supplement（底层 int64 + 边界单一转换）、middleware supplement（认可 int64 但日志落盘保留 RFC 3339 双字段） | 双方已近：底层 int64 + 唯一转换点一致，分歧仅「日志落盘是否保留 RFC 3339 冗余」 |
| v2 | app 整合（底层 int64 + 日志双字段同源派生 + 三列职责矩阵） | base-lib supplement（4 点实现层修正）、middleware supplement（3 点实现层修正）——双方同向 |
| v3 | app 吸收 4 项修正（不丢事件降级矩阵/tz 必填/legacy 独立入口/精度区间+命名统一） | base-lib accept（无文本）、middleware accept（无文本） |
| agree | chair judge agree → finalize | room=agreed，决议 time/v3 |

**盲投验证（真实 agent）**：base-lib v2 表态引用的只是 middleware 的 **v1 表态（历史公开）**，双方 v2 表态完全独立（无同轮互引）。**发言收敛验证**：base-lib v2 开头「只列与 v1 有差异处」、middleware v2「认可（不重复细节）」、v3 双方 accept 零文本。

### 盲投 A 落地时踩的三个坑（已修复）

1. **盲投依赖 agent 自觉传 actor 不可靠**：middleware 首次跑 `moot_get_room` 未传 `actor`，直接看到全量。→ 修复：`moot_get_room` **强制要求 actor**（不传报错）；新增 `moot_get_room_full`（chair/复盘看全量）。
2. **submit 返回值泄露**：`moot_submit` 返回完整 prop（含全量 statements），agent 表态后从返回值看到他人本轮表态（防 anchoring 被破）。→ 修复：submit 返回值盲投投影。
3. **judge 后公开缺失**：chair 判定 continue 后，当前版本表态仍被盲投屏蔽，发起方无法看全量整合修订。→ 修复：`judge` 记录 `version`，`room_view` 对「当前版本已被 chair 判定」的表态不屏蔽（公开）。

## token 认证（注册发 key，agent 持 key 代表身份）

用户指出「agent 不应该自己传 actor，项目是注册制的，应该持 key 代表身份」。改造：

1. **注册发 token**：`register_project` 注册即发 token（`moot_` + secrets.token_hex(16)），存 `projects[id].token`。
2. **身份传递**：MCP server 配置 `headers: {"Authorization": "Bearer ${env:MOOT_TOKEN}"}`，pi-mcp 运行时从环境变量展开（密钥不落盘明文）。
3. **服务端识别**：`store.identify(token)` 从 header 读 token → 项目 id；`_mcp_call_tool` 用 `actor = identify(token)`，不信任调用方自报。
4. **工具签名简化**：`moot_get_room`/`moot_submit`/`moot_list_pending`/`moot_create_issue`/`moot_comment_issue`/`moot_revise` 不再需要 actor/author/project/creator 参数，身份从 token 自动识别。
5. **chair 权限**：`moot_get_room_full`/`moot_judge`/`moot_finalize` 仅 chair（校验 token 识别身份 == room.chair），`_require_chair` 强制。

## 实战三：R-004 分页契约（token 认证端到端验证）

R-004「列表分页契约与转换职责」，chair=agent，participants=[base-lib, middleware, app]，提案 P1（creator=app）。信息差隔离：base-lib 只知「offset/limit 稳定深翻页」、middleware 只知「page/pageSize + total 业务分页」、app 只见「无限滚动 cursor」。两轮收敛（v1→v2 + agree）：

| 轮 | 动作 | 结果 |
|---|---|---|
| v1 | base-lib supplement（底层 offset/limit + 稳定排序键）、middleware supplement（契约分层：业务层 page/total + 可选 cursor） | 双方已在三层分工上趋同，分歧仅 cursor 定位 |
| v2 | app 整合（契约分层 + cursor=传输层不透明令牌非业务契约 + HMAC 签名 + 转换职责表） | base-lib accept（无文本）、middleware accept（无文本） |
| agree | chair judge agree → finalize | room=agreed，决议 pagination/v2 |

**token 认证验证**：base-lib/middleware 用各自 token 认证，`moot_submit` 不再传 author、`moot_list_pending` 不再传 project、`moot_get_room` 不再传 actor，身份全自动识别；app 调 `moot_get_room_full` 被 chair 权限拒，自动改用成员视角 `moot_get_room`。**盲投验证**：双方 v1 表态独立（各自提分工建议，无「对方已表态/已 supplement」式引用）。**发言收敛验证**：v2 双方 accept 零文本。
