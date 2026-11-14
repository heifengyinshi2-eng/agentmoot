# MCP OAuth 网关（标准 MCP + OAuth 服务端）

> 级别：L2
> 状态：已迁移至本仓库，测试通过（2026-11-14）

## 目标

在 agentmoot 仓库 `gateway/` 中实现一个**标准 MCP 网关**（最初在 pi-packages/packages/pi-moot 原型，2026-11-14 迁移至此）：

- 客户端用标准 MCP OAuth（DCR + `client_credentials`）认证；
- MCP 标准流程（传输、initialize、tools、401 挑战）与 moot 解耦；
- moot 只作为**上游应用接口提供方**，网关不实现任何 moot 业务语义；
- 技术栈 JS/TS，OAuth 交给 `oidc-provider`，MCP 交给官方 SDK。

## 需求（原始诉求）

- 客户端（pi-mcp）已实现标准 OAuth，服务端需与之互通。
- 尽量遵循标准，尽量用通用库、做配置。
- MCP server 本身的标准流程不要和 moot 紧耦合。
- 直接在当前项目实现服务端。

## 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 架构 | 认证网关 + 上游 MCP 透传 | 标准流程与业务解耦；moot 无需改造 |
| OAuth AS | `oidc-provider` v9 | 原生支持 DCR、client_credentials、RFC 8707、JWKS |
| MCP | `@modelcontextprotocol/sdk` | 与 pi-mcp 客户端同源，协议一致 |
| 身份 | DCR `client_name` → token `project` claim | 客户端零配置，网关把项目身份传给上游 |
| 上游身份 | moot 既有 per-project Bearer token | 不改 moot；`GET/POST /projects` 自动解析 |
| token 形式 | RS256 JWT，`aud`=MCP resource | 无状态验证；密钥持久化，重启可用 |
| 传输 | 每请求创建 stateless MCP server/transport | 无需会话存储，pi-mcp 可直接使用 |
| DCR | 默认开放；可选 initial access token | 本机开发零配置；对外可加鉴权 |
| 安全 | 递归脱敏上游结果中的 token 字段；默认禁用 `moot_register_project` | 避免凭据泄漏/身份绕过 |

### 关键发现

1. **MCP 官方 SDK 不支持服务端 `client_credentials`**（TS/Python 均只支持 authorization_code / refresh_token），因此不能用 `mcpAuthRouter`，必须用通用 OAuth AS 库。
2. `oidc-provider` 默认 `response_types: ["code"]`，导致 DCR 拒绝 `redirect_uris: []`；通过 `clientDefaults.response_types = []` 解决。
3. `oidc-provider` 的客户端注册必然生成不透明随机 `client_id`，符合 RFC 7591，也符合 pi-mcp 客户端预期。
4. 上游 moot 的 `GET /projects` 会返回 token，可用于恢复既有项目身份，无需改 moot。

## 模块

| 文件 | 职责 |
|---|---|
| `gateway/src/config.ts` | 配置分层（环境变量 > JSON > 默认） |
| `gateway/src/keys.ts` | RS256 JWKS 生成/持久化（0600） |
| `gateway/src/oauth.ts` | `oidc-provider` 配置、PRM、JWT 校验 |
| `gateway/src/identity.ts` | 上游项目 → moot token（唯一 moot 相关适配） |
| `gateway/src/upstream.ts` | 上游 MCP 客户端池、结果脱敏 |
| `gateway/src/gateway.ts` | 单次请求的 MCP server（tools/list、tools/call 透传） |
| `gateway/src/http.ts` | 路由、401 挑战、PRM、OAuth/MCP 分发 |
| `gateway/src/index.ts` | 启动与优雅退出 |

## 规格清单

### S-CFG-001 配置优先级
- **输入**：环境变量、`moot-gateway.json`、默认值
- **输出**：`GatewayConfig`
- **行为**：环境变量覆盖文件；缺失项取默认
- **异常**：非法 URL / 非正整数端口抛错

### S-OAUTH-001 PRM
- **输入**：`GET /.well-known/oauth-protected-resource` 或 `.../<mcpPath>`
- **输出**：`{resource, authorization_servers:[issuer], scopes_supported, bearer_methods_supported:["header"], resource_name}`
- **行为**：两条路径返回相同内容

### S-OAUTH-002 AS 元数据
- **输出**：必须包含 `issuer`、`authorization_endpoint`、`token_endpoint`、`response_types_supported`、`registration_endpoint`、`grant_types_supported` 含 `client_credentials`
- **行为**：由 `oidc-provider` 生成

### S-OAUTH-003 DCR
- **输入**：`POST /reg`，含 `client_name`、`redirect_uris: []`、`grant_types:["client_credentials"]`、`token_endpoint_auth_method:"client_secret_basic"`
- **输出**：201，`client_id`、`client_secret`、`client_secret_expires_at: 0`
- **异常**：配置 initial access token 时，缺失/错误返回 401 `invalid_token`

### S-OAUTH-004 token
- **输入**：Basic 客户端认证 + `grant_type=client_credentials` + `resource=<mcp resource>` + `scope`
- **输出**：`access_token`（JWT，含 `iss/sub/client_id/aud/exp/project/scope`）、`token_type:"Bearer"`、`expires_in`
- **异常**：resource 不匹配 → `invalid_target`；客户端错误 → `invalid_client`

### S-AUTH-001 /mcp 认证
- **输入**：`Authorization: Bearer <JWT>`
- **输出**：有效时进入 MCP；无效/缺失时 401 + `WWW-Authenticate: Bearer resource_metadata="…"`（无效 token 附 `error="invalid_token"`）
- **行为**：校验 issuer、audience、签名；项目取 `project` claim

### S-GW-001 工具透传
- **输入**：MCP `tools/list` / `tools/call`
- **输出**：上游结果
- **行为**：`tools/list` 过滤 `denyTools`；`tools/call` 禁用工具返回 `isError`；上游结果递归删除 `token` 等字段
- **异常**：上游连接失败 → 丢弃缓存并返回 JSON-RPC 错误

### S-ID-001 上游身份
- **输入**：项目 id
- **输出**：moot Bearer token
- **行为**：缓存命中直接返回；否则 `GET /projects` 匹配；不存在则 `POST /projects` 注册
- **异常**：上游 4xx/5xx → 明确错误

## 测试

`gateway/tests/gateway.test.ts`（本地 stub 上游，不依赖 moot）：

- PRM 根路径 + path-aware
- 无 token → 401 挑战
- DCR → token → initialize → tools/list → tools/call
- denyTools 过滤
- 上游 token 字段脱敏
- 无效 token → 401 `invalid_token`
- 配置默认值与覆盖

真实链路验证（手动）：用 pi-mcp 的 `McpOAuthProvider` 对运行中的网关完成 DCR → token → `moot_list_pending`，返回项目身份正确。

## 行动计划

- [x] 1. 调研 SDK / AS 库能力与限制
- [x] 2. 配置 + JWKS
- [x] 3. OAuth AS（PRM / DCR / token / JWKS）
- [x] 4. 401 挑战 + JWT 校验
- [x] 5. MCP 透传 + 上游客户端池
- [x] 6. moot 身份适配 + 结果脱敏
- [x] 7. 自动化测试（stub 上游）
- [x] 8. 与 pi-mcp 真实客户端端到端验证
- [x] 9. README / 示例配置

## 备注

- `oidc-provider` 使用内存 adapter 会打印警告；客户端丢失后会在 `invalid_client` 时自动重新 DCR，token 为 JWT 不受影响。
- 开放 DCR 等于本机任意进程可冒充项目；非 loopback 部署必须设置 `MOOT_INITIAL_ACCESS_TOKEN`。
- 后续可做：持久化 adapter、room/moot 的 REST 直连（若不再用 MCP 透传）、`moot_whoami` 调试工具。

## 更新记录

- 2026-11-13 完成网关实现、测试与 pi-mcp 端到端验证（原 pi-moot 原型）。
- 2026-11-14 迁移到 agentmoot `gateway/`，新增交接文档 `docs/oauth-gateway-handover.md`；`npm test` 6/6、typecheck 通过。
