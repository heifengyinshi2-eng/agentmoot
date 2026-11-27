# 部署到 agentgateway（AppRegistry，App 无需改平台配置）

agentgateway 已提供 **App 注册即部署** 的能力：App 侧不写任何平台 YAML，只提交 `AppSpec`，
平台自动完成 Keycloak、APISIX（etcd Admin API）、central 凭据与容器编排。

官方文档：`https://app.prod.localtest.me:28443/help`（Markdown：`?format=md`）。

## 1. 拓扑

```text
人类浏览器 ──OIDC 登录──▶ /svc/moot/*        ┐
Agent ──Bearer JWT──────▶ /agent-api/moot/*  ├─▶ APISIX（验签 + 注入身份头）
                                             ┘        │ proxy-rewrite 去前缀
                                                      ▼
                                       host.containers.internal:<port>
                                                      ▼
                                 svc-moot（app machine，network agw-app）
                                       └─ /data（named volume moot-data）
```

平台为 moot 分配的容器名是 `svc-moot`，端口自动落在 `30000..30999`（当前 30000）。

## 2. 构建镜像

镜像必须在 **app machine** 上构建（reconciler 通过该连接创建容器）：

```bash
podman --connection agentgateway-prod-app build \
  -f deploy/Dockerfile -t localhost/moot:local .
```

## 3. 注册并部署

`AppSpec`（POST `/agentsafe/admin/apps`）：

```json
{
  "id": "moot",
  "name": "Agent Moot",
  "description": "多 Agent 治理：issue 点对点协作 + room 多方决策（MCP + Web UI）",
  "owner": "platform",
  "enabled": true,
  "runtime": {
    "image": "localhost/moot:local",
    "containerPort": 8080,
    "healthPath": "/healthz",
    "env": [
      { "name": "MOOT_AUTH_MODE", "value": "gateway" },
      { "name": "MOOT_GATEWAY_APP", "value": "moot" },
      { "name": "MOOT_GATEWAY_TRUST_HEADERS", "value": "1" },
      { "name": "MOOT_HOME", "value": "/data" },
      { "name": "MOOT_PUBLIC_BASE", "value": "https://app.prod.localtest.me:28443" }
    ],
    "secretRefs": [],
    "volumes": [{ "name": "moot-data", "mountPath": "/data" }]
  },
  "ingress": {
    "human": { "enabled": true, "identityMode": "jwt" },
    "agent": { "enabled": true, "identityMode": "jwt" }
  }
}
```

步骤：

```bash
# 1) 注册（或 PUT 更新）
curl -sk -X POST "$ADMIN/apps" -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" -d @spec.json
# 2) 触发部署
curl -sk -X POST "$ADMIN/apps/moot/apply" -H "Authorization: Bearer $ADMIN_TOKEN"
# 3) 跑 reconciler（循环守护；--once 跑一轮）
AGW_ENV=prod bash deploy/podman/run.sh app-reconciler --once
# 4) 轮询状态
curl -sk "$ADMIN/apps/moot/status" -H "Authorization: Bearer $ADMIN_TOKEN"
```

`phase=active` 时以下条件全为 True：`IdentityReady`、`CredentialReady`、
`RuntimeReady`、`GatewayReady`。

平台自动产生（moot 侧无需配置）：

| 资源 | 说明 |
|---|---|
| Keycloak `apisix-app-moot` | 人类登录 client（回调 `/svc/moot/oauth2/callback`） |
| Keycloak `agent-moot` | App 的 agent client（audience 指向 `apisix-app-moot`） |
| central 凭据 `app.moot` | Agent 经 Edge 换取 token 用 |
| APISIX 路由 | `agw-app-moot-oauth2` / `-human` / `-agent`，经 Admin API 写入 etcd |
| 容器 `svc-moot` | 仅接 `agw-app`，健康检查 `GET /healthz` |

## 4. 身份契约APISIX 在 rewrite 阶段剥离客户端伪造的 `X-AGW-*` / `X-Identity-*` / `X-Principal-*`，
再注入：

| 头 | 值 |
|---|---|
| `X-AGW-App` | `moot` |
| `X-AGW-Identity-Type` | `human` / `agent` |
| `X-AGW-Identity-Mode` | `jwt` |
| `X-AGW-Request-Id` | 请求 ID |
| `X-Access-Token` | 已验签的 Keycloak JWT |
| `X-Userinfo` | base64 JSON（可能缺失，moot 会回退解 JWT payload） |

> `MOOT_PUBLIC_BASE` 用来生成帮助页/文档里的绝对链接。APISIX 前面若有 nginx 终止 TLS，
> `X-Forwarded-Proto` 会变成 `http`，不设此项链接会写成 http。

moot 侧：

- `MOOT_AUTH_MODE=gateway` + `MOOT_GATEWAY_TRUST_HEADERS=1` 启用可信头模式；
- 校验 `X-AGW-App == MOOT_GATEWAY_APP`；
- 类型直接取 `X-AGW-Identity-Type`；principal 依次取 `principal_id` → `preferred_username` → `sub`；
- **除 `/health`、`/healthz`、`/whoami` 外，缺身份头一律 403**（防止绕过 APISIX 直连端口）。

## 5. 验证
```bash
# 健康（直连端口，无需身份）
curl -s http://192.168.13.139:30000/healthz           # 200

# 直连端口访问业务 → 403
curl -s http://192.168.13.139:30000/projects          # 403

# 人类：浏览器打开 https://app.prod.localtest.me:28443/svc/moot/ ，用 demo/demo-pass 登录
# Agent：拿 aud 含 apisix-app-moot 的 token
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://app.prod.localtest.me:28443/agent-api/moot/whoami
```

实测（2026-11-26）：

- 匿名访问 `/svc/moot/` → 302 跳 Keycloak；登录后 UI 200（`<title>moot · Agent 协作看板</title>`）
- `agent-alpha` / `agent-beta` token → `/agent-api/moot/*` 200，`kind=agent`，principal 为各自项目名
- MCP `tools/call`、SSE `/events?once=1` 正常
- 直连端口 `/projects`、`/mcp` → 403
- 帮助页 `…/svc/moot/help` → 200（HTML）；`help.md` / `help.json` 同路径可换格式

## 6. 多 Agent 身份（平台已内建）

平台在 Edge 侧为**当前 agent** 签发专属短期 JWT（`sub` / `principal_id` / `owner_id` /
`aud=apisix-app-moot`），因此：

- 容器内推荐：`http://127.0.0.1:18090/*` + 占位凭据 `Authorization: Bearer as2_app.moot`（**路径相对 App**：`/mcp`、`/whoami`、`/events`；不要带 `/agent-api/moot` 前缀，否则会双前缀）
- 不同 agent 天然是不同的 `principal_id`，**不会收敛**，moot 首次调用自动登记为同名项目
- 唯一前置条件：人类管理员在控制台给该 agent（或其组织节点）授权 `app.moot`；
  未授权时返回 `403 credential_not_granted` + `approval_url`

**旧的 per-agent Keycloak client 方案已降级为“直连调试通道”**：
`agent-alpha` / `agent-beta` 及 `moot-app-audience` mapper 保留，用于拿可读 token 直接
访问 `/agent-api/moot/*`（不经 Edge）。生产接入不需要逐 agent 配置。

> 完整说明与验收清单见 [`platform-identity-requirements.md`](platform-identity-requirements.md)。
> 机械校验直连 token：`python tools/check_agent_token.py --file <token>`。

## 7. 已知问题 / 限制

1. **`/svc/moot`（无尾斜杠）返回 500**：平台路由的 `proxy-rewrite`（`^/svc/<id>(/.*)?$ → $1`）
   对裸路径产生空 upstream path。用 `/svc/moot/`。这是平台侧问题，影响所有 app。
2. **端口发布**：`-p 192.168.13.139:<port>:8080` 会绕过 APISIX。已用“缺身份头即 403”缓解；
   正式形态应不发布端口。
3. **Web UI 走 SSO**：浏览器需先登录；不再需要端口直连。
4. **moot 不再需要 HMAC 证明密钥**：`MOOT_GATEWAY_PROOF_SECRET` 仅保留给旧部署兼容。
