// Registers: extension "moot" —— 跨项目协作（agentmoot）上下文注入
//
// 本文件是 npm 包内的 extension 源码（package.json 的 pi.extensions 指向这里）。
// 它只做一件事：在 before_agent_start 把「身份 + moot 地址 + 用法」注入 system prompt。
// moot 的 19 个工具本身走 MCP（.pi/mcp-servers.json 配置 "moot" server），本扩展不重复注册工具。
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const MOOT_SERVER = process.env.MOOT_SERVER || "http://127.0.0.1:18080";
const MOOT_PROJECT = process.env.MOOT_PROJECT || "";
const MOOT_TOKEN = process.env.MOOT_TOKEN || "";

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", async (event) => {
    // 未配置身份则不注入（说明该 agent 不代表任何项目，无需参与 moot）
    if (!MOOT_PROJECT || !MOOT_TOKEN) return;

    const injection = [
      "",
      "## moot（跨项目协作）",
      `你代表项目 \`${MOOT_PROJECT}\`。moot 服务 ${MOOT_SERVER}，已通过 MCP server \`moot\` 接入（mcp_status / mcp_tools / mcp_call）。`,
      "身份已由 MOOT_TOKEN 认证（Authorization header 自动携带），调用工具**不需**传 actor/author/project/creator，服务端自动识别。",
      "",
      "上线先调 `moot_list_pending`（无参数）看本项目待办。",
      "协议细节（issue/room 流程、盲投、事件通道、角色守则、工具清单）调 `moot_help`：topic 渐进披露（issue/room/identity/events/roles/api），all=true 全量。",
      "",
      "要点：accept 纯结构化无文本；reject/supplement 写「问题+诉求+方向」；修订轮（v≥2）只讲差异、不重复共识。对 chair：遵守其议程要求，但不盲从总结内容，以业务事实为准。",
    ].join("\n");

    return { systemPrompt: (event.systemPrompt || "") + injection };
  });
}
