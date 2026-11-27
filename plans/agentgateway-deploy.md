# 计划：部署到 agentgateway（AppRegistry）

状态：已完成（prod-local 实证）
级别：L2
最后更新：2026-11-26

## 目标

把 moot 作为 agentgateway 的 App 部署：平台负责 Keycloak / APISIX / central 凭据 /
容器编排，moot 只实现 App 契约（`/healthz`、`X-AGW-App` 校验、可信身份头）。

## 任务

- [x] 调研 `agentgateway/docs/app-deployment.md` 旧接入方式并完成首次部署（2026-11-20）
- [x] agentgateway 升级为 AppRegistry + APISIX etcd Admin API 后重新部署（2026-11-26）
- [x] moot 支持 `/healthz`（平台健康检查路径）
- [x] `moot/gateway_identity.py` 新增“可信头”模式：
      `X-AGW-App` / `X-AGW-Identity-Type` / `X-AGW-Identity-Mode` / `X-Access-Token` / `X-Userinfo`
- [x] 可信头模式强制身份：除 `/health`、`/healthz`、`/whoami` 外，缺身份头返回 403
- [x] 保留旧 HMAC proof 模式（兼容，`MOOT_GATEWAY_PROOF_SECRET`）
- [x] 注册 AppSpec（`id=moot`、volume `moot-data`、env `MOOT_AUTH_MODE=gateway` 等）
- [x] `app-reconciler --once` 部署成功：`phase=active`，四项 condition 全 True
- [x] 验证：人类 OIDC 登录 → UI 200；agent token → `/agent-api/moot/*` 200；
      MCP / SSE 正常；直连端口业务路径 403
- [x] 清理旧部署物：`agw-svc-moot` 路由、`apisix-moot` client、`AGW_PROOF_SECRET_MOOT`、
      podman secret `moot_proof`、`deploy/agentgateway/` 脚本
- [x] 文档重写 `docs/deploy-agentgateway.md`
- [x] 新增自解释帮助页：`/help`（HTML）、`/help.md`、`/help.json`，内容随 auth mode 切换
- [x] 帮助页绝对链接用 `MOOT_PUBLIC_BASE`（nginx 终止 TLS 时 X-Forwarded-Proto=http）
- [x] Web UI 头部加「帮助 / 接入文档」入口

## 关键决策

- **身份来源**：新平台直接给 `X-AGW-Identity-Type`，不再需要 moot 猜 agent/human；
  proof 机制由平台统一剥离/注入替代。
- **人类语义**：观察者/仲裁者，不入项目，可读全量、可发 issue/评论，不参与盲投。
- **agent 语义**：首次出现自动登记为同名项目（`superior=owner_id`）。
- **多 agent 身份**：平台默认 `app.moot` 凭据换出的 token 主体是
  `service-account-agent-moot`，会让所有 agent 收敛成同一 principal。为保持 moot 的
  多 agent 语义，给参与协作的 agent client 各加 `aud=apisix-app-moot` 的 audience mapper，
  agent 用自己的 client_credentials token 访问 `/agent-api/moot/*`。
  代价：绕过 central 的 App 级 ACL（凭据授权），由 moot 自身做项目级隔离。
- **不发布端口才是终态**：当前平台仍发布 `192.168.13.139:<port>`，靠 moot 的
  身份头强制兜底（直连业务路径 403）。

## 踩坑记录

- **平台路由裸路径 500**：`proxy-rewrite ^/svc/moot(/.*)?$ → $1` 对 `/svc/moot`
  产生空 upstream path → 500。必须用 `/svc/moot/`。平台侧问题，影响所有 app。
- **reconciler 默认是守护循环**：不带 `--once` 会每 3s 轮询且永不退出，别当成卡死。
- **npx 在 Windows/Git Bash 下会挂起**：直接
  `node v2/node_modules/tsx/dist/cli.mjs src/cli/app-reconciler.ts`。
- **admin token 用 master realm**：`admin-cli` 必须走 `/realms/master/...`。
- 旧静态路由随 APISIX 切 etcd 自动消失，无需手工删（Admin API 查无此 ID）。
- 直接改 `state.json` / 另起进程写 store 会被运行中 server 的内存覆盖。

## 后续

- [ ] 不发布端口（正式私网形态）
- [ ] 若平台后续支持 Edge 注入调用方 agent 身份，可去掉 per-agent audience mapper
- [ ] Web UI 增加“当前身份 / 退出登录”入口（当前靠 APISIX session）
