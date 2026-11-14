/**
 * Upstream MCP client pool.
 *
 * The upstream is treated as an application API provider: the gateway does not
 * know any tool semantics, it only forwards `tools/list` and `tools/call`.
 * Each project gets its own upstream connection/token.
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { CallToolResult, Tool } from "@modelcontextprotocol/sdk/types.js";
import type { GatewayConfig } from "./config.ts";
import type { IdentityResolver } from "./identity.ts";

export interface Upstream {
	listTools(project: string): Promise<Tool[]>;
	callTool(project: string, name: string, args: Record<string, unknown>): Promise<CallToolResult>;
	close(): Promise<void>;
}

interface Entry {
	client: Client;
	ready: Promise<Client>;
}

export class UpstreamPool implements Upstream {
	private readonly entries = new Map<string, Entry>();

	private readonly cfg: GatewayConfig;
	private readonly identity: IdentityResolver;

	constructor(cfg: GatewayConfig, identity: IdentityResolver) {
		this.cfg = cfg;
		this.identity = identity;
	}

	async listTools(project: string): Promise<Tool[]> {
		const client = await this.clientFor(project);
		const result = await client.listTools();
		return result.tools;
	}

	async callTool(project: string, name: string, args: Record<string, unknown>): Promise<CallToolResult> {
		const client = await this.clientFor(project);
		try {
			return (await client.callTool({ name, arguments: args })) as CallToolResult;
		} catch (err) {
			// 上游连接可能因重启失效：丢弃缓存，下次请求重建。
			await this.drop(project);
			throw err;
		}
	}

	async close(): Promise<void> {
		const entries = [...this.entries.values()];
		this.entries.clear();
		await Promise.allSettled(entries.map((e) => e.client.close()));
	}

	private async clientFor(project: string): Promise<Client> {
		const existing = this.entries.get(project);
		if (existing) return existing.ready;
		const client = new Client(
			{ name: "moot-gateway", version: "0.1.0" },
			{ capabilities: {} },
		);
		const ready = this.connect(client, project).catch((err) => {
			this.entries.delete(project);
			throw err;
		});
		this.entries.set(project, { client, ready });
		return ready;
	}

	private async connect(client: Client, project: string): Promise<Client> {
		const token = await this.identity.tokenFor(project);
		const transport = new StreamableHTTPClientTransport(this.cfg.upstream.url, {
			requestInit: { headers: { authorization: `Bearer ${token}` } },
		});
		await client.connect(transport);
		return client;
	}

	private async drop(project: string): Promise<void> {
		const entry = this.entries.get(project);
		if (!entry) return;
		this.entries.delete(project);
		await entry.client.close().catch(() => {});
	}
}

const SECRET_KEYS = new Set(["token", "access_token", "refresh_token", "client_secret", "registration_access_token"]);

/** 递归移除上游结果中的凭据字段，避免把 moot token 透给客户端。 */
export function redactSecrets(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(redactSecrets);
	if (value && typeof value === "object") {
		const out: Record<string, unknown> = {};
		for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
			if (SECRET_KEYS.has(k)) continue;
			out[k] = redactSecrets(v);
		}
		return out;
	}
	return value;
}

/** 上游把业务对象序列化在 text 里，需要解析后再脱敏。 */
export function sanitizeToolResult(result: CallToolResult): CallToolResult {
	const content = result.content?.map((item) => {
		if (item.type !== "text" || typeof item.text !== "string") return item;
		try {
			const parsed: unknown = JSON.parse(item.text);
			const redacted = redactSecrets(parsed);
			return { ...item, text: JSON.stringify(redacted) };
		} catch {
			return item;
		}
	});
	const structuredContent =
		result.structuredContent === undefined ? undefined : (redactSecrets(result.structuredContent) as Record<string, unknown>);
	return {
		...result,
		content,
		...(structuredContent ? { structuredContent } : {}),
	};
}
