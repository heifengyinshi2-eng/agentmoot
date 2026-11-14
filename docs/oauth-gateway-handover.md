# OAuth 网关交接文档

> 迁移日期：2026-11-14
> 来源：`C:/Users/linsen/.pi/pi-packages/packages/pi-moot`（原型，已删除）
> 目标：`agentmoot/gateway/`
> 状态：可用、测试通过；尚未提交 git

## 1. 这是什么

agentmoot 原先的接入方式要求客户端先调 `moot_register_project` 拿静态 token，再手工配置 `Authorization`。这不是标准 MCP 认证流程，客户端需要了解 moot 特有的注册步骤。

`gateway/` 提供一个**标准 MCP 认证网关**：

```
任意 MCP 客户端（pi-mcp 已验证）
   │  1. POST /mcp 无 token → 401 + WWW-Authenticate
   │  2. 读取 RFC 9728 PRM → AS metadata
   │  3. RFC 7591 DCR 注册（client_name = 项目 id）
   │  4. OAuth client_credentials 换 JWT
   ▼
moot gateway :18081
   │  以项目身份解析 moot token
   ▼
moot :18080/mcp（上游，业务本体）
```

设计目标：

- 标准流程（发现/注册/发 token/401/MCP 传输）与 moot 业务**解耦**；
- 网关不认识任何 `moot_*` 工具语义，只做认证 + 转发；
- moot 保持零依赖 Python；网关是独立的 Node/TS 进程；
- 客户端零配置（无需预先知道项目 token）。

## 2. 目录

```
agentmoot/
├── gateway/
│   ├── README.md                  # 使用/配置说明
│   ├── package.json               # @heifengyinshi2-eng/moot-gateway
│   ├── tsconfig.json
│   ├── moot-gateway.example.json  # 配置样例
│   ├── src/
│   │   ├── config.ts              # 环境变量 > JSON > 默认值
│   │   ├── keys.ts                # RS256 JWKS 生成/持久化（0600）
│   │   ├── oauth.ts               # oidc-provider 配置、PRM、JWT 校验
│   │   ├── identity.ts            # 项目 id → moot token（唯一 moot 适配）
│   │   ├── upstream.ts            # 上游 MCP 客户端池、结果脱敏
│   │   ├── gateway.ts             # 单请求 MCP server（tools 透传）
│   │   ├── http.ts                # 路由、401 挑战、PRM、OAuth/MCP 分发
│   │   ├── index.ts               # 启动与优雅退出
│   │   └── oidc-provider.d.ts     # 补 Provider.proxy 类型
│   └── tests/gateway.test.ts      # 6 个测试（stub 上游，不依赖 moot）
├── plans/mcp-oauth-gateway.md     # 设计与行动计划
└── docs/oauth-gateway-handover.md # 本文
```

根 `package.json` 增加了入口：

```bash
npm run gateway:start
npm run gateway:test
npm run gateway:typecheck
```

## 3. 协议端点

| 端点 | 规范 | 说明 |
|---|---|---|
| `GET /.well-known/oauth-protected-resource` | RFC 9728 | 根路径 |
| `GET /.well-known/oauth-protected-resource/mcp` | RFC 9728 | path-aware，与根路径同内容 |
| `GET /.well-known/oauth-authorization-server` | RFC 8414 | 由 oidc-provider 生成 |
| `POST /reg` | RFC 7591 | DCR；`client_name` 即项目 id |
| `POST /token` | OAuth 2.1 | 仅 `client_credentials`，支持 `resource`（RFC 8707） |
| `GET /jwks` | RFC 7517 | RS256 公钥 |
| `POST /mcp` | MCP Streamable HTTP | 认证后转发到上游 |
| `GET /health` | — | 健康检查 |

JWT claims 关键字段：

```json
{
  "iss": "http://127.0.0.1:18081/",
  "sub": "<client_id>",
  "aud": "http://127.0.0.1:18081/mcp",
  "client_id": "<client_id>",
  "project": "<DCR client_name>",
  "scope": "mcp",
  "exp": 1794618939
}
```

`project` 由网关附加，用于向上游换取 moot token。

## 4. 运行与测试

```bash
cd agentmoot/gateway
npm install
npm start                # 127.0.0.1:18081，上游默认 127.0.0.1:18080/mcp
npm test                 # 6/6
npm run typecheck
```

前置条件：moot 服务已运行在 18080。若只跑测试则不需要 moot（测试内置 stub 上游）。

验证结果（迁移后）：

- `npm test`：6/6 通过
- `npm run typecheck`：通过
- 迁移前用真实 pi-mcp `McpOAuthProvider` 端到端验证：自动 DCR → token → `initialize` → `tools/list`（18 个工具）→ `moot_list_pending` 返回正确项目身份。

## 5. 配置

优先级：环境变量 > `moot-gateway.json`（或 `MOOT_GATEWAY_CONFIG`）> 默认值。
样例见 `gateway/moot-gateway.example.json`。

| 变量 | 默认 | 说明 |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `18081` | 监听地址 |
| `MOOT_GATEWAY_ORIGIN` | `http://HOST:PORT` | 对外 origin |
| `MOOT_OAUTH_ISSUER` | origin | OAuth issuer |
| `MOOT_MCP_PATH` | `/mcp` | MCP 路径 |
| `MOOT_MCP_RESOURCE` | `<origin><mcpPath>` | token audience |
| `MOOT_UPSTREAM_URL` | `http://127.0.0.1:18080/mcp` | 上游 MCP |
| `MOOT_PROJECTS_URL` | `<upstream origin>/projects` | 项目身份 API |
| `MOOT_ACCESS_TOKEN_TTL` | `3600` | access token 秒数 |
| `MOOT_OAUTH_SCOPES` | `mcp` | 逗号分隔 |
| `MOOT_INITIAL_ACCESS_TOKEN` | 空 | 设置后 DCR 需要 initial access token |
| `MOOT_DENY_TOOLS` | `moot_register_project` | 不暴露的上游工具 |
| `MOOT_GATEWAY_STATE` | `.moot-gateway` | JWKS 目录 |

## 6. 客户端接入

pi-mcp：

```json
{
  "name": "moot",
  "url": "http://127.0.0.1:18081/mcp",
  "auth": { "type": "oauth", "clientName": "my-project" },
  "instructions": "eager"
}
```

- `clientName` 省略时由客户端取当前目录名。
- 首次连接自动完成 DCR + token；缓存默认在 `~/.pi/mcp-oauth/`。
- 已有静态 token 的客户端仍可直连 `:18080`，两条路互不影响。

## 7. 关键设计决策

### 7.1 为什么不用 MCP 官方 SDK 做授权服务器

TS/Python 官方 SDK 的 token 端点都**不支持 `client_credentials`**（TS 明确抛 `UnsupportedGrantTypeError`，Python 的 `TokenRequest` 只接受 authorization_code / refresh_token）。因此 `mcpAuthRouter` 不能复用，改用通用 OAuth AS：`oidc-provider`。

### 7.2 为什么选 oidc-provider

- 原生支持 DCR（RFC 7591）、`client_credentials`、RFC 8707 resource indicators、JWKS；
- 协议细节（错误码、`no-store`、Basic 认证、metadata）不用自己维护；
- 纯配置即可，业务胶水只有路由和身份适配。

### 7.3 DCR 空 redirect_uris

`oidc-provider` 默认 `response_types: ["code"]`，会要求 `redirect_uris` 非空，而 pi-mcp 对 `client_credentials` 客户端发送 `redirect_uris: []`。
配置 `clientDefaults.response_types = []` 后，DCR 通过，且 `client_secret_expires_at` 为 `0`（机器身份不过期）。

### 7.4 身份传递

DCR 的 `client_name` → JWT `project` claim → 网关向上游解析 token：

1. 内存缓存命中直接返回；
2. `GET /projects` 查找同名项目（moot 会返回 token）；
3. 不存在则 `POST /projects` 注册。

这样无需改 moot，也无需客户端预先注册。**这是整个网关里唯一依赖 moot 的代码**（`src/identity.ts`）。

### 7.5 无状态 MCP 传输

每个 HTTP 请求新建 MCP `Server` + `StreamableHTTPServerTransport`（`sessionIdGenerator: undefined`），上游同样按请求创建客户端。好处：无会话存储、天然支持多实例；代价：每次请求一次上游握手（本机开销可接受）。

### 7.6 安全处理

- `tools/list` 过滤 `denyTools`（默认 `moot_register_project`），`tools/call` 调用被禁工具返回明确错误。
- 上游返回的 JSON 递归删除 `token` / `client_secret` / `access_token` 等字段，防止 `moot_list_projects` 泄漏他人 token。
- JWKS 私钥落盘权限 0600，重启后 token 仍可验证。
- 默认只监听 loopback；issuer 为 HTTP 也仅限本机。

## 8. 已知限制 / 后续 TODO

1. ✅ **内存 adapter → 文件 adapter**（2026-11-14）：新增 `gateway/src/adapter.ts`，记录存 `<stateDir>/adapter/<type>-<sha256(id)>.json`。已验证 DCR 注册后重启网关，原 client_id/secret 仍可换 token。多实例共享需换 Redis/SQLite（当前文件实现适合单机；多实例下文件不共享）。
2. ✅ **开放 DCR → 可选 initial access token**：`MOOT_INITIAL_ACCESS_TOKEN` 已实现并验证——无 token DCR 返回 401，带 `Authorization: Bearer <token>` 返回 201。**对外暴露前必须设置**。
3. ✅ **`moot_help` 文案按认证方式裁剪**：moot 新增 `MOOT_AUTH_MODE=oauth`（默认 `token`）。oauth 模式下 `identity` 主题与 `overview` 身份行改为 OAuth 说明，`initialize.instructions` 也不再提 `moot_register_project`。已验证。
4. ⏳ **重复凭据路径**：静态 `moot_` token（直连 18080）与 OAuth（经 18081）并存。长期可让网关成为唯一入口，moot 只信任网关——**留待架构调整讨论**。
5. ✅ **可观测性**：网关每个请求生成 request id（响应头 `x-request-id`），stdout 输出一行结构化 JSON（`ts/service/level/requestId/method/path/status/durationMs`）；未处理异常额外记录 `event:"unhandled"` + stack。
6. ✅ **已提交 git**：`b45bfd4`（网关整体）；后续 TODO 改动随下一次提交。

## 9. 部署建议

```bash
MOOT_UPSTREAM_URL=http://127.0.0.1:18080/mcp \
MOOT_GATEWAY_ORIGIN=https://moot.example.com \
MOOT_OAUTH_ISSUER=https://moot.example.com \
MOOT_INITIAL_ACCESS_TOKEN=<random-secret> \
npm start
```

- 反向代理需透传 `Host`、`Authorization`，并关闭对 `/mcp` 的缓冲（SSE/流式）。
- `MOOT_GATEWAY_STATE` 指向持久卷，确保重启后 JWKS 不变。
- 若多实例，所有实例共享同一 JWKS 与持久化 adapter。

## 10. 迁移清单

- [x] 源码/测试/配置样例迁至 `agentmoot/gateway/`
- [x] 包名改为 `@heifengyinshi2-eng/moot-gateway`
- [x] 服务标识改为 `moot-gateway`
- [x] 配置文件名变量改为 `MOOT_GATEWAY_CONFIG`
- [x] 根 `package.json` 增加 gateway 脚本
- [x] 根 `README.md` 增加网关章节
- [x] `.gitignore` 增加 `gateway/.moot-gateway/`
- [x] 计划文档迁至 `plans/mcp-oauth-gateway.md`
- [x] 在 agentmoot 内重新 `npm install`、`npm test`、`npm run typecheck`（全部通过）
- [x] 删除原 `pi-packages/packages/pi-moot` 原型内容；仅剩空目录（当前 pi 会话以它为 cwd，Windows 锁定，会话结束后可删）
