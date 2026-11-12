# playground-drill：真实多方依赖站点的 issue 实战

## 目标

搭一个真实的「小站点」（app → middleware → base-lib 三层依赖，Node.js 纯标准库），埋真实 bug，用 moot 发起针对性 issue，让真实 pi agent 各自代表一方通过 MCP 处理，观察实际执行闭环。

## 需求

1. 三个测试环境（项目目录 + 可运行代码）：`playground/base-lib`、`playground/middleware`、`playground/app`。
2. 依赖链：app → middleware → base-lib。
3. 站点能跑（app :3100 → middleware :3101 → base-lib），基线有真实 bug（大整数序列化丢精度）。
4. 用 moot 注册三方 + 发起 3 个针对性 issue（覆盖 accept / duplicate / 关联依赖 等不同路径）。
5. 真实 pi agent（MOOT_PROJECT 分别 = base-lib / middleware / app）通过 MCP 处理，观察闭环。

## 验收标准

- [x] 站点基线可运行，复现 bug（alice 订单 ID 9007199254740993 → 被舍入成 ...92）。
- [x] moot 注册三方 + 3 个 issue 成功。
- [x] 两个 agent 真实走通「查待办 → 评审 → resolve」，且都实际改了代码。
- [x] 记录每个 issue 的实际处理路径（accept/resolve / duplicate）。

## 任务列表

- [x] 搭 playground 三项目 + 站点代码（埋 bug）
- [x] 验证站点基线运行 + 复现 bug
- [x] 起 moot 服务 + 注册三方 + 发起 issue
- [x] 真实 agent 处理 issue，观察闭环

## 实战结果

| Issue | 链路 | 处理路径 | agent 实际动作 |
|---|---|---|---|
| I-001 | app → base-lib | accepted → resolved | **改了 `base-lib/index.js`**：BigInt/非安全整数序列化为字符串，parse 支持 bigint 还原 |
| I-002 | app → middleware | accepted → resolved | **改了 `middleware/server.js`**：移除 `Number(id)`，雪花 ID 字符串透传 |
| I-003 | middleware → base-lib | duplicate | 正确判「与 I-001 同根」，指向 I-001 |

修复后重启 middleware，`/api/orders` 输出 `{"id":"9007199254740993"}`（字符串，不再舍入），app 首页正确。

## 更新记录

- 2026-11-12 建计划（L1）。
- 2026-11-12 搭建 playground + 发起 issue + 两个 agent 处理并修代码，完整闭环验证通过。
