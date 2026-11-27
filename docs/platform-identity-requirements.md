# 平台身份能力要求（moot 侧，待平台确认）

状态：待平台确认  
版本：2026-11-27  
适用：agentgateway（AppRegistry + Keycloak + APISIX）接入 moot

## 0. 一句话

moot 的「agent 自动注册」**完全依赖平台给的 token 身份**：平台必须保证
**一个 agent ↔ 一个稳定的 Keycloak 主体（client）**，并在 token 里带上
`principal_id`（项目 id）与 `owner_id`（人类负责人）。  
满足这三点，agent 第一次调用就会自动登记为同名项目，moot 侧零配置。

反例（已实测）：所有 agent 复用 App 的默认 `agent-moot` 凭据 →
token 里只有 `service-account-agent-moot`，**全部 agent 收敛成同一个项目**，
moot 无法区分谁是谁。

## 1. moot 如何消费身份

```text
agent ──JWT──▶ APISIX（验签，剥离伪造头）
                 │ 注入 X-AGW-App / X-AGW-Identity-Type / X-Access-Token / X-Userinfo
                 ▼
              moot 解析 claims（按优先级）
                 principal = X-Principal-Id → principal_id → preferred_username → sub
                 owner     = owner_id
                 kind      = X-AGW-Identity-Type
                 ▼
              首次出现 → register_project(principal, name=principal, superior=owner)
```

| 字段 | 用途 | 缺失时 moot 的降级 |
|---|---|---|
| `principal_id` | 项目 id（issue 的 assignee 引用它） | 退到 `preferred_username`，即 `service-account-xxx` |
| `owner_id` | 项目 superior（人类仲裁者） | 记为 `human` |
| `sub` | 兜底唯一性 | — |
| `aud` | APISIX 校验受众 | 请求被 APISIX 401 |
| `azp` / `client_id` | 目前仅记录，建议保留 | — |

## 2. 必须保障的能力（R1–R8）

| 编号 | 要求 | 原因 / 不满足的后果 | 平台侧动作 |
|---|---|---|---|
| **R1** | **每个 agent 一个独立 Keycloak client**（不复用 App 默认 `agent-<app>` 凭据） | 否则所有 agent 同一身份，moot 无法区分（已实测收敛为 `service-account-agent-moot`） | 为每个 agent 建 confidential client，开启 service account |
| **R2** | token 必带 `principal_id`，值 = 该 agent 的稳定可读 id（如 `agent-alpha`） | 这是 moot 的项目 id；缺失则退化成 `service-account-xxx` | 加 `oidc-hardcoded-claim-mapper` |
| **R2b** | `principal_id` 不得以 `service-account-` 开头，且在平台内唯一 | 保证可读性与唯一性 | 按 agent 命名规范填写 |
| **R3** | token 必带 `owner_id`，值 = 负责该 agent 的人类账号 | 作为项目 superior（仲裁者） | 加 hardcoded claim mapper |
| **R4** | token 的 `aud` 包含 `apisix-app-moot` | APISIX 受众校验；缺失即 401 | 加 `oidc-audience-mapper` |
| **R5** | `sub` / `azp` 稳定，不随 client 重建/重启变化 | 备用唯一性与审计 | 不删除重建 client（改配置即可） |
| **R6** | 调用方不得伪造身份：APISIX 必须剥离 `X-AGW-*` / `X-Identity-*` / `X-Principal-*` 后重新注入 | 否则可冒充他人项目 | 已实现，需保持 |
| **R7** | `principal_id` 一旦下发不得更改 | 它是项目 id，改名会等于换项目 | 改名走"新 client + 迁移"流程 |
| **R8** | 停用 agent 时，令其 client 的 token 立即失效（disable client / 撤销 service account） | moot 侧不做吊销；依赖 token 失效 | 停用时禁用 client |

> 补充：平台的 **App 默认凭据 `app.moot` / `agent-moot` 仍然保留**，但仅用于
> "一个应用一个 agent 身份"的场景。moot 这类**多 agent 协作服务**必须走 R1。

## 3. Keycloak 配置模板（每 agent 一份）

对每个 agent 的 client（`clientId=agent-xxx`，confidential，service account 开启）：

```json
[
  {
    "name": "principal_id",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-hardcoded-claim-mapper",
    "config": {
      "claim.name": "principal_id",
      "claim.value": "agent-xxx",
      "jsonType.label": "String",
      "access.token.claim": "true",
      "id.token.claim": "true",
      "userinfo.token.claim": "true",
      "introspection.token.claim": "true"
    }
  },
  {
    "name": "owner_id",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-hardcoded-claim-mapper",
    "config": {
      "claim.name": "owner_id",
      "claim.value": "<负责人的平台账号>",
      "jsonType.label": "String",
      "access.token.claim": "true",
      "id.token.claim": "true",
      "userinfo.token.claim": "true",
      "introspection.token.claim": "true"
    }
  },
  {
    "name": "moot-app-audience",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-audience-mapper",
    "config": {
      "included.custom.audience": "apisix-app-moot",
      "access.token.claim": "true",
      "id.token.claim": "false",
      "introspection.token.claim": "true",
      "userinfo.token.claim": "false"
    }
  }
]
```

参考实现：`agent-alpha`、`agent-beta` 当前即为上述配置（可直接照抄）。

## 4. 验收清单（平台确认时逐条打勾）

用 `tools/check_agent_token.py` 做机械校验：

```bash
# 1) 用该 agent 的 client_credentials 换 token
curl -sk -X POST "$AUTH/realms/platform/protocol/openid-connect/token" \
  -d grant_type=client_credentials \
  -d client_id=agent-xxx -d client_secret=<secret> \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])" > /tmp/agent-xxx.token

# 2) 校验 claim 契约（要求 exit 0 且全 PASS）
python tools/check_agent_token.py --file /tmp/agent-xxx.token

# 3) 端到端：whoami 应返回该项目名与 kind=agent
curl -sk -H "Authorization: Bearer $(cat /tmp/agent-xxx.token)" \
  $APP/agent-api/moot/whoami
```

期望：

- [ ] R1 每个 agent 独立 client（`azp` 互不相同）
- [ ] R2/R2b `check_agent_token.py` 全部 PASS
- [ ] R3 `owner_id` 存在且为真实负责人
- [ ] R4 `aud` 含 `apisix-app-moot`
- [ ] R5 连续两次换 token，`sub` 不变
- [ ] R6 伪造 `X-AGW-App`/`X-Principal-Id` 直连容器端口 → 403（现状已满足）
- [ ] R7 明确"principal_id 不可变"的变更流程
- [ ] R8 明确停用 agent 的吊销方式

## 5. 当前实测状态（2026-11-27）

| 主体 | principal | owner | aud 含 moot | 结论 |
|---|---|---|---|---|
| `agent-alpha` | `agent-alpha` | `demo` | ✅ | 符合，自动注册正确 |
| `agent-beta` | `agent-beta` | `demo` | ✅ | 符合，自动注册正确 |
| `app.moot` / `agent-moot`（App 默认凭据） | 无 `principal_id`（`service-account-agent-moot`） | —（human） | ✅ | **不符合 R1/R2**，所有 agent 会收敛 |
| human（`demo`） | `demo` | — | ✅ | 不注册项目，观察者/仲裁者 |

## 6. 需要平台回答的问题

1. **是否为每个 agent 建独立 client？** 若平台有"agent 注册中心"（每个 agent 一条记录），
   该记录能否自动映射为一个 Keycloak client + `principal_id`？
2. **`principal_id` 的命名规则**是什么（谁定、是否全局唯一、是否允许中文/斜杠）？
   moot 直接把它当项目 id（issue 的 assignee），建议限定 `[a-z0-9][a-z0-9._/-]*`。
3. **`owner_id` 的来源**：是创建者、还是部门负责人？变更 owner 是否影响历史项目
   （moot 只在首次注册时读取，之后不覆盖）。
4. **停用/删除 agent** 的标准动作是什么（disable client / 删 service account）？
5. 若短期无法做到每 agent 一 client，平台能否在 Edge 注入调用方身份
   （见 §8 备选方案 B）？

## 7. 新增一个 agent 的标准流程（平台 SOP）

1. 平台创建 agent 记录（id、显示名、负责人）
2. Keycloak：新建 confidential client `agent-<id>`，开启 service account
3. 挂 3 个 mapper：`principal_id`、`owner_id`、`moot-app-audience`（§3）
4. 把 client 凭据下发给该 agent（不落盘明文，运行时注入）
5. agent 首次调用 `moot_list_pending` → moot 自动登记为项目 `<id>`
6. 验证：`check_agent_token.py` + `/whoami`

> 无需通知 moot，无需在 moot 侧做任何操作（自动登记幂等）。

## 8. 备选方案 B（若平台坚持"一个 App 一个 agent 凭据"）

由 Edge 在换取 token 后额外注入调用方身份头，例如：

```
X-AGW-Agent-Id: agent-alpha
```

moot 侧改动很小：`principal` 优先级里插入 `X-AGW-Agent-Id`（在 `X-Principal-Id` 之后）。
但该头必须由平台在剥离客户端伪造头**之后**注入，否则等于允许自报身份。

若选 B，则 §2 的 R1/R2 可放宽为：Edge 必须为每个 agent 提供稳定唯一 id，
不得缺省或透传客户端值。

## 9. moot 承诺不做的事（避免平台侧误解）

- **不接受自报身份**：工具参数里没有 project / actor / creator。
- **不做动态客户端注册（DCR）** 来给 agent 发身份（那是平台职责）。
- **不依赖 userinfo 接口**（agent token 调 userinfo 会 403，moot 只用 `X-Userinfo`
  或自己解 JWT payload）。
- **不做 token 吊销**：停用 agent 由平台禁用 client 实现。
- **不跨 agent 合并身份**：principal 不同即不同项目，moot 不做"同一人多个 client"的合并。
