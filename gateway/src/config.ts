/**
 * Gateway configuration.
 *
 * Two layers: an optional JSON file (`moot-gateway.json`, or
 * `MOOT_GATEWAY_CONFIG`) and environment variables on top.
 *
 * The gateway is intentionally generic: `upstream` may be any MCP server that
 * speaks Streamable HTTP and accepts a Bearer token. The moot adapter only
 * supplies the per-project upstream token.
 */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

export interface GatewayConfig {
	host: string;
	port: number;
	/** Public origin of this gateway, e.g. http://127.0.0.1:18081 */
	origin: URL;
	/** OAuth issuer. Must equal `origin` unless behind a reverse proxy. */
	issuer: URL;
	/** Canonical URI of the protected MCP resource. */
	mcpResource: URL;
	/** MCP path on this gateway. */
	mcpPath: string;
	/** Upstream MCP server (moot) and its REST projects endpoint. */
	upstream: {
		name: string;
		url: URL;
		projectsUrl: URL;
	};
	oauth: {
		/** RFC 7591 Initial Access Token; empty/undefined means open DCR (dev only). */
		initialAccessToken?: string;
		/** Access token lifetime in seconds. */
		accessTokenTtl: number;
		scopes: string[];
		/** Extra static clients (pre-registered, skips DCR). */
		clients: StaticClient[];
	};
	/** Upstream tools that must not be exposed through the gateway. */
	denyTools: string[];
	/** Directory for generated keys. */
	stateDir: string;
}

export interface StaticClient {
	client_id: string;
	client_secret: string;
	name?: string;
}

interface FileConfig {
	host?: string;
	port?: number;
	mcpPath?: string;
	issuer?: string;
	mcpResource?: string;
	upstream?: { name?: string; url?: string; projectsUrl?: string };
	oauth?: {
		initialAccessToken?: string;
		accessTokenTtl?: number;
		scopes?: string[];
		clients?: StaticClient[];
	};
	denyTools?: string[];
	stateDir?: string;
}

const DEFAULT_DENY_TOOLS = ["moot_register_project"];

function parseUrl(value: string, name: string): URL {
	try {
		return new URL(value);
	} catch {
		throw new Error(`配置错误: ${name} 不是合法 URL: ${value}`);
	}
}

function readFileConfig(path: string): FileConfig {
	if (!existsSync(path)) return {};
	try {
		return JSON.parse(readFileSync(path, "utf-8")) as FileConfig;
	} catch (err) {
		throw new Error(`配置错误: 无法解析 ${path}: ${err instanceof Error ? err.message : String(err)}`);
	}
}

function envInt(env: NodeJS.ProcessEnv, name: string): number | undefined {
	const raw = env[name];
	if (raw === undefined || raw === "") return undefined;
	const n = Number(raw);
	if (!Number.isInteger(n) || n <= 0) throw new Error(`配置错误: ${name} 必须是正整数: ${raw}`);
	return n;
}

function envList(env: NodeJS.ProcessEnv, name: string): string[] | undefined {
	const raw = env[name];
	if (raw === undefined || raw.trim() === "") return undefined;
	return raw
		.split(",")
		.map((s) => s.trim())
		.filter(Boolean);
}

/**
 * 解析配置。纯函数（除读取配置文件外无副作用），便于测试。
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env, cwd: string = process.cwd()): GatewayConfig {
	const filePath = env.MOOT_GATEWAY_CONFIG ?? resolve(cwd, "moot-gateway.json");
	const file = readFileConfig(filePath);

	const host = env.HOST ?? file.host ?? "127.0.0.1";
	const port = envInt(env, "PORT") ?? file.port ?? 18081;
	const origin = parseUrl(env.MOOT_GATEWAY_ORIGIN ?? `http://${host}:${port}`, "MOOT_GATEWAY_ORIGIN");
	const issuer = parseUrl(env.MOOT_OAUTH_ISSUER ?? file.issuer ?? origin.href, "MOOT_OAUTH_ISSUER");
	const mcpPath = env.MOOT_MCP_PATH ?? file.mcpPath ?? "/mcp";
	const mcpResource = parseUrl(
		env.MOOT_MCP_RESOURCE ?? file.mcpResource ?? new URL(mcpPath, origin).href,
		"MOOT_MCP_RESOURCE",
	);

	const upstreamUrl = parseUrl(
		env.MOOT_UPSTREAM_URL ?? file.upstream?.url ?? "http://127.0.0.1:18080/mcp",
		"MOOT_UPSTREAM_URL",
	);
	const projectsUrl = parseUrl(
		env.MOOT_PROJECTS_URL ?? file.upstream?.projectsUrl ?? new URL("/projects", upstreamUrl).href,
		"MOOT_PROJECTS_URL",
	);

	const accessTokenTtl = envInt(env, "MOOT_ACCESS_TOKEN_TTL") ?? file.oauth?.accessTokenTtl ?? 3600;
	const scopes = envList(env, "MOOT_OAUTH_SCOPES") ?? file.oauth?.scopes ?? ["mcp"];
	const initialAccessToken = env.MOOT_INITIAL_ACCESS_TOKEN ?? file.oauth?.initialAccessToken ?? undefined;
	const clients = file.oauth?.clients ?? [];

	return {
		host,
		port,
		origin,
		issuer,
		mcpResource,
		mcpPath,
		upstream: {
			name: env.MOOT_UPSTREAM_NAME ?? file.upstream?.name ?? "moot",
			url: upstreamUrl,
			projectsUrl,
		},
		oauth: {
			initialAccessToken: initialAccessToken || undefined,
			accessTokenTtl,
			scopes,
			clients,
		},
		denyTools: envList(env, "MOOT_DENY_TOOLS") ?? file.denyTools ?? DEFAULT_DENY_TOOLS,
		stateDir: env.MOOT_GATEWAY_STATE ?? file.stateDir ?? resolve(cwd, ".moot-gateway"),
	};
}
