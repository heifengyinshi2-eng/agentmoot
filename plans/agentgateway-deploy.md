# 计划：部署到 agentgateway（APISIX + Keycloak）

状态：已完成（prod-local 实证）
级别：L2
最后更新：2026-11-20

## 目标

按 `agentgateway/docs/app-deployment.md` 把 moot 部署为 APISIX 后面的自建服务，
并解决 agent / human 身份认定。

## 任务

- [x] 调研 app-deployment 与 agentgateway 身份契约（D-011/D-018/D-021）
- [x] 实测 Keycloak claims：agent（client_credentials）vs human（authorization code）
- [x] 实测 APISIX：agent token 的 userinfo 返回 403，但 `X-Userinfo` 仍被注入
- [x] 新增 `moot/gateway_identity.py`（proof 校验 + agent/human 判定）
- [x] `MOOT_AUTH_MODE=gateway`：身份来自可信头；agent 自动登记；human 观察者
- [x] 网关模式关闭自注册 / REST 写入；项目列表不返回 token
- [x] SSE 在网关模式按身份取 project（agent 自身 / human 全量）
- [x] Docker 镜像（`deploy/Dockerfile`、`.dockerignore`）
- [x] 部署到 `agentgateway-prod-app`：30001 + named volume + podman secret
- [x] APISIX 路由 `agw-svc-moot`（userinfo / JWT payload 双路径）
- [x] 端到端验证（agent / human / 401 / SSE / 重启持久化）
- [x] 文档 `docs/deploy-agentgateway.md`

## 关键决策

- **身份判定**：`owner_id` 存在或 `preferred_username=service-account-*` → agent。
- **人类语义**：不入项目，观察者/仲裁者；可读全量、可发 issue/评论，不参与盲投。
- **agent 语义**：首次出现自动登记为同名项目（`superior=owner_id`）。
- **不新增自定义头**：moot 自行解 `X-Access-Token` 判定 kind，proof 仍按
  `app|sub|principal|request|exp`，与 agentgateway 约定一致。
- **网关模式下 REST 只读**：写操作必须走 MCP，避免自报 creator/author。

## 踩坑记录

- `podman run --memory` 在本机 rootless cgroup 报 `open memory.max: No such file`，
  暂不加资源限制。
- 镜像默认 OCI 格式会忽略 Dockerfile `HEALTHCHECK`，改用 `--health-cmd`。
- 直接改 `state.json` / 另起进程写 store 会被运行中的 server 内存覆盖；seed 数据
  必须先停容器，用同卷一次性容器写完再启动。
- APISIX `up-apisix` 在容器已运行时不会重启，改路由后必须显式
  `podman restart agw-apisix`。

## 后续

- [x] 独立 `apisix-moot` client + `AGW_PROOF_SECRET_MOOT`
- [x] 给 `agent-alpha` / `agent-beta` 增加 `moot-audience` mapper（二者实测 200）
- [x] 人类独立登录（`apisix-moot` standard flow，回调 `/svc/moot/oauth2/callback`）
- [ ] Web UI 认证（当前仅端口直连、只读）
- [ ] 不发布端口（正式私网形态）
- [ ] agentgateway 仓库三处改动提交
