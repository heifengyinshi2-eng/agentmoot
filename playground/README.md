# playground：真实多方依赖站点

三层依赖链，用于 moot 实战演练：

```
app (:3100) ──HTTP──> middleware (:3101) ──require──> base-lib
```

- **base-lib**：JSON 序列化基础库（`stringify` / `parse`）。埋 bug：大整数（> 2^53）序列化丢精度。
- **middleware**：订单 API 服务，依赖 base-lib。埋 bug：把字符串雪花 ID 转 Number 再序列化，两个订单 ID 塌成同一个。
- **app**：面向用户的订单站点，依赖 middleware 的 `/api/orders` 渲染页面。

## 启动

```bash
node playground/base-lib/index.js          # 库，无端口
node playground/middleware/server.js       # :3101
node playground/app/app.js                 # :3100
```

访问 `http://127.0.0.1:3100/` 可见 bug：两个订单（alice/bob）的 ID 都显示为 `9007199254740992`（应为 `...93` / `...94`）。

## 依赖关系（moot 视角）

- app 依赖 middleware（app 调 middleware API）
- middleware 依赖 base-lib（middleware require base-lib）

典型 issue 链：
1. I-001（app → base-lib）：`stringify` 大整数丢精度（根因）。
2. I-002（app → middleware）：`/api/orders` 把 ID 转 Number 丢精度，应保持字符串。
3. I-003（middleware → base-lib）：middleware 需要 base-lib 的无损序列化能力（与 I-001 关联）。

## 实战结果（2026-11-12）

真实 pi agent 各自代表一方通过 moot MCP 处理：

| Issue | 处理路径 | agent 实际动作 |
|---|---|---|
| I-001 | accepted → resolved | base-lib agent 改 `base-lib/index.js`：BigInt/非安全整数序列化为字符串，parse 支持 bigint 还原 |
| I-002 | accepted → resolved | middleware agent 改 `middleware/server.js`：移除 `Number(id)`，雪花 ID 字符串透传 |
| I-003 | duplicate | base-lib agent 判「与 I-001 同根」，指向 I-001 |

修复后 `/api/orders` 输出 `{"id":"9007199254740993"}`（字符串，不再舍入），app 首页正确。
