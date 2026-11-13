# service-boundary — 收回 extension，只保留 server + MCP

## 背景

此前为把 moot 接入 pi，写了一个 pi extension（注入 system prompt、管 `.pi/moot.json`、自愈 `.pi/mcp-servers.json`）。
问题：这些都需要了解 pi 的内部机制（`before_agent_start`、MCP reload、settings、cwd 约定），属于**客户端职责**；
项目本身不应了解 pi / 项目管理的细节。且该注入只对 pi 生效，换成其他 MCP 客户端即失效——"信息不足"。

## 决策（用户 2026-11-13）

- **项目边界**：moot 只提供 **server + 标准 MCP**，不绑定任何 agent 框架。
- 取消 extension；本地卸载。
- 身份：MCP 标准 `Authorization: Bearer <token>`，客户端自行获取/保存 token。
- 自解释做好：`initialize.instructions`（最小化单行入口）+ 工具描述 + `moot_help` + 未认证错误引导。
- SSE 通知保留。
- npm 包分发方式先不动。

## 改动

- 删除 `extensions/moot.ts`、`.pi/`（含 `.pi/mcp-servers.json`）。
- `package.json`：移除 `pi` 字段、`pi-package` keyword、files 中的 extension；description 改为服务定位。
- `moot/server.py`：
  - `initialize` 返回 `instructions` 单行入口（`MCP_INSTRUCTIONS`）。
  - 未认证错误统一改为引导：先调 `moot_register_project` 注册拿 token，再由客户端在 header 携带。
- README / docs/implementation.md：删除 pi 集成说明，改为「客户端接入（MCP 通用）」。

## 验收

- [x] 本地 extension 卸载（settings 无残留）
- [x] `initialize.instructions` 返回单行提示（含 `moot_register_project` 与 `moot_help`）
- [x] 未认证调用返回注册引导
- [x] 19 tests passed（新增 instructions 与错误引导断言）
- [x] 服务重启后真实验证通过

## 更新记录

- 2026-11-13：完成边界收回与自解释入口；npm 分发暂不动。
