# 身份方案确认：平台已提供「每 agent 独立身份」

状态：**已在线上全链路验证通过**（2026-11-27），moot 侧零改动即兼容  
依据：`https://app.prod.localtest.me:28443/help?role=agent`（agentgateway `e064c2e`）  
相关：`docs/deploy-agentgateway.md`、`moot/gateway_identity.py`

## 1. 结论

之前要求的「每个 agent 一个独立 Keycloak client」**不再需要**。  
平台改为在 Edge 侧为**当前 agent** 签发专属短期 JWT，天然满足 moot 的身份语义：

```text
Agent（容器内）
  │  Authorization: Bearer as2_app.moot      ← 占位凭据，不含真实密钥
  ▼
本机 Edge http://127.0.0.1:18090
  │  central /api/exchange（用 agent 自己的凭据认证）
  ▼
central 签发该 agent 专属 RS256 JWT：
     sub / principal_id / owner_id / azp = 该 agent
     aud = apisix-app-moot
     iss = https://central.agw.internal/oidc
  ▼
APISIX（central JWKS 验签 + 受众校验）
  │  X-AGW-App: moot, X-AGW-Identity-Type: agent, X-Access-Token: <JWT>
  ▼
moot：principal_id → 项目 id（首次出现自动登记），owner_id → superior
```

官方原文：*“不同 Agent 天然携带各自独立的 `principal_id` 与 `owner_id`，不会收敛为同一个服务账号。”*

## 2. 平台提供的能力（对照之前的要求）

| 原要求 | 现状 | 说明 |
|---|---|---|
| R1 每 agent 独立主体 | ✅ 已由平台提供 | 不需要 per-agent Keycloak client；同一 App 凭据 `app.moot` 被不同 agent 使用时，各自得到独立 `principal_id` |
| R2 token 带 `principal_id` | ✅ | central 签发，值经 `normalizePrincipalId` 规范化（小写、去 `service-account-` 前缀、≤64 字符） |
| R2b 不以 `service-account-` 开头 | ✅ | issuer 内部会剔除该前缀 |
| R3 token 带 `owner_id` | ✅ | 取 agent 的项目 owner，缺省 `human` |
| R4 `aud` 含 `apisix-app-moot` | ✅ | 由 App 的 agent 凭据 `app.moot` 的 audience 决定 |
| R5 `sub` 稳定 | ✅ | central 用 agent id 作为 `sub`；`azp`/`client_id` 同值 |
| R6 剥离伪造头 | ✅ | APISIX rewrite 阶段剥离 `X-AGW-*` / `X-Identity-*` / `X-Principal-*` |
| R7 `principal_id` 不可变 | ✅ | 与 agent 记录绑定（平台侧保证） |
| R8 停用 agent 即失效 | ✅ | token TTL 默认 300s（60–3600 可配），停用后不再签发 |

## 3. moot 侧需要做什么

**不需要改代码**，现有实现已兼容：

- 身份仍从可信头解析：`X-AGW-App` 校验 → `X-AGW-Identity-Type` 判 kind →
  `X-Userinfo` 或自解 `X-Access-Token` 取 `principal_id` / `owner_id` / `sub`；
- central 签发的 token **不含 `X-Userinfo`**，走的是 `jwt_payload(X-Access-Token)` 回退路径
  （新增测试 `test_central_issued_agent_token` 覆盖）；
- 首次调用自动登记为项目（幂等），`superior = owner_id`；
- 除 `/health`、`/healthz`、`/whoami` 外，缺可信头一律 403。

## 4. 唯一需要人类做的动作：授权

agent 第一次访问 `app.moot` 时，如果人类管理员还没授权，会收到：

```json
{
  "error": "credential_not_granted",
  "human_action_required": true,
  "approval_url": "https://app.prod.localtest.me:28443/agentsafe/console?credential_id=app.moot&project_id=...&agent_id=...",
  "message": "Human authorization is required for credential 'app.moot'..."
}
```

处理方式（人类）：打开 `approval_url` → 在「组织与权限」里给该 agent（或其组织节点）
勾选 `app.moot` → 保存。授权后无需重启，下一次请求即生效。

**agent 不应也无法自行授权**（符合平台“零密钥 / 人类授权”原则）。

## 5. 实测记录（2026-11-27）

| 步骤 | 结果 |
|---|---|
| `prodvm1-main` 内 `POST /_agentsafe/identity` | 200，`status=authorized`，credential `as2_tk_020a60fb7213` |
| 授权前：同上 | **403 `credential_not_granted`**（返回 approval_url） |
| 授权后（hosts 未修） | **502 `upstream_unreachable`** —— exchange 已成功，卡在 Edge→入口的可达性 |
| 平台补齐入口 hosts 映射后：`prodvm1` 经 Edge `/whoami` | **200**，`sub=agent-3c17362ef9561b6d`，`principal=prodvm1`，`owner=user-1` |
| 同一凭据在 `self-host-apps` 经 Edge `/whoami` | **200**，`sub=agent-756948be7065cd64`，`principal=self-host-apps`，`owner=linsen` → **两个 agent 不收敛** ✅ |
| 经 Edge `/mcp` initialize + `tools/list` | **200**，19 个工具全部可见 |
| 经 Edge 完整 issue 流程 | `prodvm1` 建 **I-004** → `self-host-apps` `list_pending` 可见 → `review accepted` → `prodvm1` 读回 `accepted` ✅ |
| 经 Edge SSE `/events?after=0&once=1` | 200，收到 `id: 13 / event: issue.created / data: {...}` ✅ |
| 直连公网 + `agent-alpha` client_credentials JWT | 200，`kind=agent`，principal `agent-alpha` |
| 直连公网 + human SSO | 200，`kind=human`，UI/帮助页正常 |
| 直连容器端口（无身份头） | 403 |

> 结论：R1–R8 已在线上全链路验证通过；`principal` 为各 agent 自身（`prodvm1` / `self-host-apps`），未收敛。

## 5.1 已知坑（已解决 / 待平台处理）

**已解决**：agent 容器曾把 `app.prod.localtest.me` 解析到自身回环（`::1`），导致 502。
平台已给 `prodvm1`、`self-host-apps` 注入 hosts 映射后链路恢复。
`vuln` pod 仍未注入（仍是 `::1`），同类问题会复现。

**路径语义（重要）**：Edge 用 `joinUpstream(baseUrl, path)` **直接拼接**，
凭据 `app.moot` 的 `baseUrl` 已含 `/agent-api/moot`。因此容器内调用必须是**相对 App 的路径**：

```text
http://127.0.0.1:18090/whoami   →  https://app.../agent-api/moot/whoami  ✅
http://127.0.0.1:18090/agent-api/moot/whoami
                                →  .../agent-api/moot/agent-api/moot/whoami  ❌（APISIX 只剥一层 → moot 收到 /agent-api/moot/whoami）
```

## 6. 验收清单（授权后执行）

在**某个 agent 容器内**：

```bash
# 1) 身份可用
curl -s http://127.0.0.1:18090/_agentsafe/identity -X POST -d '{}'

# 2) 经 Edge 访问 moot（占位凭据）
curl -s http://127.0.0.1:18090/whoami \
  -H "Authorization: Bearer as2_app.moot"

# 3) MCP 握手
curl -s http://127.0.0.1:18090/mcp \
  -H "Authorization: Bearer as2_app.moot" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

期望：

- [x] `/whoami` 返回 `identity_type=agent`，`principal` 等于该 agent 的 id
- [x] 两个不同 agent 分别调用，`principal` **不同**（不收敛）
- [x] `tools/list` 返回 19 个工具
- [x] 未授权的 agent 得到 403 + `approval_url`（而不是被静默合并）
- [x] issue 全流程 + SSE 事件投递（2026-11-27）

## 7. 兼容说明：旧的 per-agent Keycloak client

`agent-alpha` / `agent-beta` 及其 `moot-app-audience` mapper **保留**，用途降级为：

- 本机/网关外调试（拿可读 token 直连 `/agent-api/moot/*`）；
- 故障定位时区分「网关链路问题」还是「moot 身份解析问题」。

生产接入一律以 **Edge + `as2_app.moot`** 为准。

## 8. 对早期结论的修正

- ~~“必须每个 agent 建独立 Keycloak client，否则全部收敛为 `service-account-agent-moot`”~~
  → 仅在**直连调试通道**（Keycloak client_credentials + App 默认凭据）成立；
  经 Edge 的正规链路不存在该问题。
- ~~“需要给每个 agent 加 audience mapper”~~ → 平台签发时已带正确 `aud`，无需逐 agent 配置。
