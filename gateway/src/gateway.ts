/**
 * MCP server for one authenticated request.
 *
 * The MCP standard flow (transport, initialize, tools/list, tools/call) is
 * gateway-owned. Tool semantics live entirely in the upstream provider.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
	CallToolRequestSchema,
	ListToolsRequestSchema,
	type CallToolResult,
	type Tool,
} from "@modelcontextprotocol/sdk/types.js";
import type { Upstream } from "./upstream.ts";
import { sanitizeToolResult } from "./upstream.ts";

export interface GatewayRequestContext {
	project: string;
	upstream: Upstream;
	denyTools: ReadonlySet<string>;
}

const INSTRUCTIONS = `This is a standard MCP gateway. Identity is established by OAuth 2.1
(client_credentials) before the MCP session starts; tools never take an actor
parameter. Tools are provided by the configured upstream application.`;

export function createGatewayMcpServer(ctx: GatewayRequestContext): Server {
	const server = new Server(
		{ name: "moot-gateway", version: "0.1.0" },
		{ capabilities: { tools: {} }, instructions: INSTRUCTIONS },
	);

	server.setRequestHandler(ListToolsRequestSchema, async () => {
		const tools = await ctx.upstream.listTools(ctx.project);
		return { tools: tools.filter((t: Tool) => !ctx.denyTools.has(t.name)) };
	});

	server.setRequestHandler(CallToolRequestSchema, async (request): Promise<CallToolResult> => {
		const { name, arguments: args } = request.params;
		if (ctx.denyTools.has(name)) {
			return {
				isError: true,
				content: [{ type: "text", text: `工具 ${name} 已由网关禁用（身份由 OAuth 提供）` }],
			};
		}
		const result = await ctx.upstream.callTool(
			ctx.project,
			name,
			(args ?? {}) as Record<string, unknown>,
		);
		return sanitizeToolResult(result);
	});

	return server;
}
