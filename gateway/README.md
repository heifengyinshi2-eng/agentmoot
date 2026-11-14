# moot OAuth 网关

> agentmoot 仓库的可选组件：标准 MCP 认证网关（`gateway/`）。moot 本体仍是零依赖 Python 服务。

标准 MCP 网关：**OAuth 2.1 认证 + MCP Streamable HTTP**，moot 只是上游应用接口提供方。

```
pi-mcp / 任意 MCP 客户端
        │  OAuth client_credentials + DCR
        ▼
moot gateway (本目录)
        │  以项目身份携带 Bearer token
        ▼
moot (上游 MCP 服务)
```

网关不实现任何 moot 工具语义：`tools/list` 和 `tools/call` 原样转发给上游。
标准流程（发现、注册、发 token、401 挑战、MCP 传输）与 moot 解耦。

## 协议实现

| 规范 | 端点 | 实现 |
|---|---|---|
| RFC 9728 Protected Resource Metadata | `/.well-known/oauth-protected-resource[/<path>]` | 本目录 |
| RFC 8414 AS Metadata | `/.well-known/oauth-authorization-server` | `oidc-provider` |
| RFC 7591 Dynamic Client Registration | `/reg` | `oidc-provider` |
| OAuth 2.1 `client_credentials` | `/token` | `oidc-provider` |
| RFC 8707 Resource Indicators | `/token` 的 `resource` 参数 | `oidc-provider` |
| JWT access token + JWKS | `/jwks` | `oidc-provider`（RS256） |
| MCP Streamable HTTP | `/mcp` | MCP 官方 SDK |

- 身份约定：DCR 的 `client_name` 即项目 id；token 中携带 `project` claim。
- `/mcp` 无 token 时返回 `401` + `WWW-Authenticate: Bearer resource_metadata="…"`，客户端据此自动发现并注册。
- 上游 token 由网关按项目自动解析：先读 `GET /projects`，不存在再 `POST /projects`。
- 上游结果中的 `token` / `client_secret` 等字段会被递归脱敏。
- 默认禁用 `moot_register_project`（身份已由 OAuth 提供）。

## 运行

```bash
cd gateway
npm install
node src/index.ts
# 或
PORT=18081 MOOT_UPSTREAM_URL=http://127.0.0.1:18080/mcp node src/index.ts
```

默认监听 `127.0.0.1:18081`，上游为 `http://127.0.0.1:18080/mcp`。

### 配置

优先级：环境变量 > `moot-gateway.json`（或 `MOOT_GATEWAY_CONFIG`）> 默认值。
示例见 `moot-gateway.example.json`。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `18081` | 监听地址 |
| `MOOT_GATEWAY_ORIGIN` | `http://HOST:PORT` | 对外 origin |
| `MOOT_OAUTH_ISSUER` | origin | OAuth issuer |
| `MOOT_MCP_PATH` | `/mcp` | MCP 路径 |
| `MOOT_MCP_RESOURCE` | `<origin><mcpPath>` | RFC 8707 resource / token audience |
| `MOOT_UPSTREAM_URL` | `http://127.0.0.1:18080/mcp` | 上游 MCP |
| `MOOT_PROJECTS_URL` | `<upstream origin>/projects` | 项目身份 API |
| `MOOT_ACCESS_TOKEN_TTL` | `3600` | access token 秒数 |
| `MOOT_OAUTH_SCOPES` | `mcp` | 逗号分隔 |
| `MOOT_INITIAL_ACCESS_TOKEN` | 空 | 设置后 DCR 需要 RFC 7591 initial access token |
| `MOOT_DENY_TOOLS` | `moot_register_project` | 逗号分隔，不暴露的上游工具 |
| `MOOT_GATEWAY_STATE` | `.moot-gateway` | 签名密钥目录 |

### 客户端配置（pi-mcp）

```json
{
  "servers": [
    {
      "name": "moot",
      "url": "http://127.0.0.1:18081/mcp",
      "auth": { "type": "oauth" },
      "instructions": "eager"
    }
  ]
}
```

`auth.clientName` 省略时取当前目录名，作为项目 id。首次连接会自动 DCR 并换取 token。

## 安全边界

- **开放 DCR 仅限本机开发**：不设 `MOOT_INITIAL_ACCESS_TOKEN` 时，任何本机进程都能注册任意 `client_name`（即冒充任意项目）。对外暴露前必须设置 initial access token。
- 网关默认只监听 `127.0.0.1`；`issuer` 使用明文 HTTP 也仅限 loopback。
- 签名密钥保存在 `stateDir/jwks.json`（0600），token 在重启后仍可验证。
- `oidc-provider` 使用内存 adapter：重启后已注册客户端丢失，客户端会在 `invalid_client` 时自动重新注册；access token 为自包含 JWT，不受影响。

## 测试

```bash
npm test          # 单元 + 集成（本地 stub 上游，不依赖 moot）
npm run typecheck
```

## 与 pi-mcp 的关系

- `pi-mcp` 已有标准 OAuth 客户端（`src/oauth.ts`）。
- 本目录的端到端验证使用真实的 `McpOAuthProvider` 跑通 DCR → token → MCP 工具调用。
- 设计背景见 `../plans/mcp-oauth-gateway.md`，交接说明见 `../docs/oauth-gateway-handover.md`。
