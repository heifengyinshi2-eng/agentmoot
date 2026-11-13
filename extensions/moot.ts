// Registers: extension "moot" —— 跨项目协作（agentmoot）上下文注入
//
// 设计：
// - **无条件注入**：不管有没有身份，都向 system prompt 注入「moot 是什么 / 什么时候用 / 怎么开始」。
// - **身份来自项目 cwd**：读 `<cwd>/.pi/moot.json`（{project, token, server?}）。token 由 agent 调
//   `moot_register_project` 自主注册得到并写入该文件；不使用环境变量作为身份来源。
// - **token 传递**：读到 token 后写入 `process.env.MOOT_TOKEN`，pi-mcp 每次元工具调用前会 reload
//   配置并重新展开 `${env:MOOT_TOKEN}`，因此 MCP header 能拿到当前项目的 token。
// - **MCP 配置自愈**：确保项目级 `.pi/mcp-servers.json` 存在 moot server 条目（缺失才追加）。
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";

const DEFAULT_SERVER = "http://127.0.0.1:18080";
const IDENTITY_FILE = ".pi/moot.json";
const MCP_FILE = ".pi/mcp-servers.json";

interface Identity {
  project?: string;
  token?: string;
  server?: string;
}

function readJson(file: string): unknown {
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch {
    return null;
  }
}

function loadIdentity(cwd: string): Identity | null {
  const data = readJson(path.join(cwd, IDENTITY_FILE)) as Identity | null;
  if (!data || typeof data !== "object" || !data.token) return null;
  return data;
}

/** 幂等确保项目级 MCP 配置里有 moot server（缺失才追加）；失败静默，不阻断注入。 */
function ensureMcpServer(cwd: string, server: string): void {
  const file = path.join(cwd, MCP_FILE);
  const raw = readJson(file);
  const data = raw && typeof raw === "object" ? (raw as { servers?: unknown[] }) : { servers: [] };
  if (!Array.isArray(data.servers)) data.servers = [];
  if (data.servers.some((s) => s && typeof s === "object" && (s as { name?: string }).name === "moot")) return;
  data.servers.push({
    name: "moot",
    url: server.replace(/\/+$/, "") + "/mcp",
    headers: { Authorization: "Bearer ${env:MOOT_TOKEN}" },
    description: "agentmoot 跨项目协作（token 注册后存 .pi/moot.json，extension 自动加载）",
  });
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 2) + "\n", "utf-8");
}

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", async (event, ctx) => {
    const cwd = ctx?.cwd || process.cwd();
    const identity = loadIdentity(cwd);
    const server = identity?.server || process.env.MOOT_SERVER || DEFAULT_SERVER;

    // 身份以项目 cwd 的 .pi/moot.json 为准；同步进 env 供 pi-mcp 展开 header。
    if (identity?.token) process.env.MOOT_TOKEN = identity.token;
    else delete process.env.MOOT_TOKEN;
    process.env.MOOT_SERVER = server;

    try {
      ensureMcpServer(cwd, server);
    } catch {
      // 配置写入失败不影响注入
    }

    const lines: string[] = [
      "",
      "## moot（跨项目协作）",
      `moot 是跨项目 Agent 协同服务（${server}），通过 MCP server \`moot\` 访问：先用 \`mcp_tools(server="moot")\` 发现工具，再用 \`mcp_call\` 调用。`,
      "",
      "**什么时候用**（只用于跨项目；本项目内部的事不要用）：",
      "- 需要别的项目配合：改接口 / 报跨项目 bug / 提变更请求 → **issue**（点对点）",
      "- 多个项目对同一契约有分歧、要收敛成统一标准 → **room**（多方会议）",
      "- 收到 `moot_list_pending` 的待办 → 优先处理（评审 / 解决 / 验收）",
      "- 纯本项目内部的决策，或不需要对方行动的纯通知 → 不要用 moot",
      "",
    ];

    if (identity) {
      lines.push(
        `**身份**：你代表项目 \`${identity.project ?? "?"}\`（token 已从 \`.pi/moot.json\` 自动加载）。调用工具不需传 actor/author/project/creator，服务端按 token 识别。`,
        "上线先调 `moot_list_pending`（无参数）看本项目待办。",
      );
    } else {
      lines.push(
        "**首次使用（本项目还没有身份 token）**：",
        '1. 调 `moot_register_project(id="<本项目名>")` → 返回 token',
        '2. 把 `{"project":"<id>","token":"<token>"}` 写入项目根 `.pi/moot.json`（加入 .gitignore，勿提交）',
        '3. 调 `mcp_connect(server="moot", force=true)` 让新 token 立即生效',
        "之后每次启动会自动从 `.pi/moot.json` 读取身份。若 MCP server `moot` 不可用，先向 Overseer 确认 moot 服务地址是否在运行。",
      );
    }

    lines.push(
      "",
      "协议细节（issue/room 流程、盲投、事件通道、角色守则、工具清单）调 `moot_help`：topic 渐进披露（issue/room/identity/events/roles/api），all=true 全量。",
      "",
      "要点：accept 纯结构化无文本；reject/supplement 写「问题+诉求+方向」；修订轮（v≥2）只讲差异、不重复共识。对 chair：遵守其议程要求，但不盲从总结内容，以业务事实为准。",
    );

    return { systemPrompt: (event.systemPrompt || "") + lines.join("\n") };
  });
}
