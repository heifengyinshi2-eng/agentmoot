# 部署到 agentgateway（prod-local）

按 `agentgateway/docs/app-deployment.md` 把 moot 作为「挂在 APISIX 后面的自建服务」部署，
身份由 Keycloak/APISIX 提供（`MOOT_AUTH_MODE=gateway`）。

## 1. 拓扑

```text
Agent / 人类
  │  Keycloak JWT（agent=client_credentials，human=authorization code）
  ▼
nginx :28443 → APISIX（openid-connect 验签 + 注入身份头 + per-app HMAC）
  │           /svc/moot/*  →  proxy-rewrite 去掉前缀
  ▼
host.containers.internal:30001
  ▼
svc-moot（agentgateway-prod-app 机器，network agw-app）
  └─ /data（named volume moot-data）
```

## 2. 镜像

```bash
cd L:/piworkspace/projects/agentmoot
podman --connection agentgateway-prod-app build -f deploy/Dockerfile -t localhost/moot:local .
```

镜像只含 Python 标准库 + `moot/`，入口：

```text
python -m moot.server --host 0.0.0.0 --port 8080 --store /data
```

## 3. 证明密钥

复用 agentgateway 现有的 per-app 证明密钥（**临时**，见限制 1）：

```bash
cd L:/piworkspace/projects/agentgateway
set -a; . deploy/podman/runtime/prod/env; set +a
printf '%s' "$AGW_PROOF_SECRET_APP_A" | \
  podman --connection agentgateway-prod-app secret create moot_proof -
```

## 4. 启动容器

```bash
podman --connection agentgateway-prod-app run -d --name svc-moot \
  --restart=unless-stopped \
  --network agw-app \
  -p 192.168.13.139:30001:8080 \
  -v moot-data:/data \
  --secret moot_proof \
  -e MOOT_AUTH_MODE=gateway \
  -e MOOT_GATEWAY_APP=moot \
  -e MOOT_GATEWAY_PROOF_SECRET_FILE=/run/secrets/moot_proof \
  --health-cmd "python -c 'import urllib.request,sys; sys.exit(0 if urllib.request.urlopen(\"http://127.0.0.1:8080/health\",timeout=2).status==200 else 1)'" \
  --health-interval 15s --health-timeout 3s \
  localhost/moot:local
```

说明：

- `--memory/--cpus` 在本机 rootless cgroup 下会失败（`open memory.max: No such file`），
  暂未加资源限制。
- 容器 healthcheck 用 `--health-cmd` 注入（镜像 OCI 格式会忽略 Dockerfile HEALTHCHECK）。

## 5. APISIX 路由

在 `deploy/podman/apisix/apisix.yaml` 增加 `agw-svc-moot`（详见该文件），要点：

- `client_id: apisix-app-a`（agent-alpha 的 audience 已含 app-a；见限制 2）
- `bearer_only: true` + `claim_validator.audience.match_with_client_id`
- `proxy-rewrite.regex_uri: ["^/svc/moot(.*)", "$1"]`
- `serverless-post-function`（before_proxy）里：
  1. 优先读 `X-Userinfo`（人类 token 有；**client_credentials 的 userinfo 返回 403**）
  2. 缺失时解析 APISIX 已验签的 `X-Access-Token` JWT payload
  3. 取 `sub` / `principal_id` / `owner_id`，按
     `v1.<exp>.<hmac(secret, "moot|sub|principal|request_id|exp")>` 注入 `X-AGW-Proof`

重启生效：

```bash
AGW_ENV=prod bash deploy/podman/run.sh up-apisix   # 重新渲染 runtime/prod/apisix.yaml
podman --connection agentgateway-prod-core restart agw-apisix
```

## 6. 身份契约（实测）

| | agent | human |
|---|---|---|
| Keycloak | `agent-alpha`（serviceAccountsEnabled） | 用户 `demo`（apisix-app-a 标准流） |
| 获取方式 | `client_credentials` | authorization code |
| `sub` | service account UUID | 用户 UUID |
| `principal_id` | `agent-alpha`（hardcoded mapper） | `demo`（employee_id mapper） |
| `owner_id` | `demo`（hardcoded mapper） | 无 |
| `preferred_username` | `service-account-agent-alpha` | `demo` |
| `client_id` claim | 有 | 无 |
| userinfo 端点 | **403** | 200 |

moot 的判定：**`owner_id` 存在或 `preferred_username` 以 `service-account-` 开头 → agent，否则 human**。

行为差异：

- **agent**：首次请求自动登记为同名项目（`superior = owner_id`），可完整参与 issue/room。
- **human**：不入项目，是观察者/仲裁者；可读全量（room 不做盲投屏蔽）、可发 issue/评论，不能 `submit`（非参与方）。
- 网关模式下 `moot_register_project` 与 REST 写入均禁用；`moot_list_projects`/`GET /projects` 不返回 token。

## 7. 验证

```bash
TOKEN=...  # Keycloak token
curl -sk https://app.prod.localtest.me:28443/svc/moot/whoami -H "Authorization: Bearer $TOKEN"
# agent: {"principal_id":"agent-alpha","actor":{"kind":"agent","owner":"demo",...},"identified":true}
# human: {"principal_id":"demo","actor":{"kind":"human",...},"identified":true}

curl -sk -X POST https://app.prod.localtest.me:28443/svc/moot/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"moot_list_pending","arguments":{}}}'
```

实测结果：

- 无 token → 401；agent/human token → 200
- agent 自动登记、issue 创建/评论、`list_pending` 正常
- human 可读全量、可评论、不能自注册
- SSE：`GET /svc/moot/events?once=1` 经 APISIX 正常返回事件
- 容器重启后数据保留（named volume）

## 8. 已知限制 / 后续

1. **证明密钥复用 app-a**：临时用 `AGW_PROOF_SECRET_APP_A`。正式应新增
   `AGW_PROOF_SECRET_MOOT` + 独立 client `apisix-moot`。
2. **agent-beta 无法访问**：其 audience 是 `apisix-app-b`，而路由以 `apisix-app-a`
   做 audience 校验。多 agent 接入需给所有 agent client 增加 `apisix-moot` audience
   mapper，或按项目拆路由。
3. **人类登录入口**：当前人类 token 来自 app-a 的 OAuth 客户端；moot 自身没有
   人类登录页/回调 URI。若需要独立人类入口，应新增 `apisix-moot` 客户端。
4. **Web UI**：`bearer_only` 路由下浏览器无法直接打开 `/svc/moot/`；当前 UI 只能
   经 app 机器端口 `192.168.13.139:30001` 直连（本机）。网关模式下 UI 只读。
5. **端口直连**：30001 发布在 WSL host IP，绕过 APISIX。已通过「网关模式禁用 REST
   写入 + 列表不含 token」降低风险；彻底做法是不发布端口（正式 Linux 私网形态）。
6. **资源限制**：未启用 memory/cpu 限制（本机 cgroup 限制）。
7. **agentgateway 仓库改动未提交**：`deploy/podman/apisix/apisix.yaml` 新增了
   `agw-svc-moot` 路由。
