/**
 * HTTP wiring: one Node server hosting both the OAuth authorization server and
 * the protected MCP endpoint.
 *
 *   /.well-known/oauth-protected-resource*  -> RFC 9728 (gateway-owned)
 *   /mcp                                   -> MCP (Bearer required)
 *   everything else                        -> oidc-provider (RFC 8414/7591/6749)
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type Provider from "oidc-provider";
import type { GatewayConfig } from "./config.ts";
import { createGatewayMcpServer } from "./gateway.ts";
import { protectedResourceMetadata, protectedResourceMetadataUrl, type TokenVerifier } from "./oauth.ts";
import type { Upstream } from "./upstream.ts";

export interface HttpDeps {
	cfg: GatewayConfig;
	provider: Provider;
	verify: TokenVerifier;
	upstream: Upstream;
}

interface Identity {
	project: string;
	payload: Record<string, unknown>;
}

function sendJson(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}): void {
	const data = Buffer.from(JSON.stringify(body));
	res.writeHead(status, {
		"content-type": "application/json; charset=utf-8",
		"content-length": String(data.length),
		...headers,
	});
	res.end(data);
}

function bearer(req: IncomingMessage): string | undefined {
	const auth = req.headers.authorization;
	if (!auth) return undefined;
	const match = /^Bearer\s+(.+)$/i.exec(auth);
	return match?.[1]?.trim() || undefined;
}

async function authenticate(
	req: IncomingMessage,
	cfg: GatewayConfig,
	provider: Provider,
	verify: TokenVerifier,
): Promise<Identity | undefined> {
	const token = bearer(req);
	if (!token) return undefined;
	let payload: Record<string, unknown>;
	try {
		payload = (await verify(token)) as Record<string, unknown>;
	} catch {
		return undefined;
	}
	let project = typeof payload.project === "string" ? payload.project : undefined;
	if (!project && typeof payload.client_id === "string") {
		const client = (await provider.Client.find(payload.client_id)) as
			| { clientName?: string; client_name?: string }
			| undefined;
		project = client?.clientName ?? client?.client_name;
	}
	if (!project) return undefined;
	return { project, payload };
}

function unauthorized(res: ServerResponse, cfg: GatewayConfig, error?: "invalid_token"): void {
	const params = [`resource_metadata="${protectedResourceMetadataUrl(cfg)}"`];
	if (error) params.push(`error="${error}"`);
	sendJson(
		res,
		401,
		{ error: "unauthorized", error_description: "A valid Bearer access token is required" },
		{ "www-authenticate": `Bearer ${params.join(", ")}` },
	);
}

async function handleMcp(req: IncomingMessage, res: ServerResponse, deps: HttpDeps): Promise<void> {
	const { cfg, provider, verify, upstream } = deps;
	const identity = await authenticate(req, cfg, provider, verify);
	if (!identity) {
		unauthorized(res, cfg, bearer(req) ? "invalid_token" : undefined);
		return;
	}

	const server = createGatewayMcpServer({
		project: identity.project,
		upstream,
		denyTools: new Set(cfg.denyTools),
	});
	const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });

	res.on("close", () => {
		void transport.close().catch(() => {});
		void server.close().catch(() => {});
	});

	try {
		await server.connect(transport);
		await transport.handleRequest(req, res);
	} catch (err) {
		if (!res.headersSent) {
			sendJson(res, 500, {
				jsonrpc: "2.0",
				error: { code: -32603, message: `gateway error: ${err instanceof Error ? err.message : String(err)}` },
				id: null,
			});
		}
	}
}

export function createGatewayHttpServer(deps: HttpDeps) {
	const { cfg, provider } = deps;
	const oauthCallback = provider.callback();

	return createServer((req, res) => {
		void (async () => {
			const url = new URL(req.url ?? "/", cfg.origin);

			if (req.method === "GET" && url.pathname === "/health") {
				sendJson(res, 200, { ok: true, service: "moot-gateway", issuer: cfg.issuer.href });
				return;
			}

			// RFC 9728 requires path-aware discovery for resources with a path.
			if (
				(req.method === "GET" || req.method === "HEAD") &&
				url.pathname.startsWith("/.well-known/oauth-protected-resource")
			) {
				sendJson(res, 200, protectedResourceMetadata(cfg), {
					"access-control-allow-origin": "*",
					"cache-control": "public, max-age=300",
				});
				return;
			}

			if (url.pathname === cfg.mcpPath) {
				if (req.method === "OPTIONS") {
					res.writeHead(204, {
						"access-control-allow-origin": "*",
						"access-control-allow-methods": "GET, POST, DELETE, OPTIONS",
						"access-control-allow-headers": "authorization, content-type, mcp-session-id, mcp-protocol-version",
					});
					res.end();
					return;
				}
				await handleMcp(req, res, deps);
				return;
			}

			// OAuth endpoints and discovery.
			oauthCallback(req, res);
		})().catch((err) => {
			if (!res.headersSent) {
				sendJson(res, 500, { error: "server_error", error_description: err instanceof Error ? err.message : String(err) });
			}
		});
	});
}
