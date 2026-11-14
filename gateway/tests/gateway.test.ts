import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer as createHttpServer } from "node:http";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import {
	CallToolRequestSchema,
	ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { loadConfig, type GatewayConfig } from "../src/config.ts";
import { createGatewayHttpServer } from "../src/http.ts";
import { MootIdentityResolver } from "../src/identity.ts";
import { loadOrCreateJwks } from "../src/keys.ts";
import { createOAuthProvider, createTokenVerifier } from "../src/oauth.ts";
import { UpstreamPool } from "../src/upstream.ts";

interface Stub {
	url: string;
	projectsUrl: string;
	close(): Promise<void>;
}

async function getFreePort(): Promise<number> {
	const srv = createHttpServer();
	await new Promise<void>((r) => srv.listen(0, "127.0.0.1", r));
	const address = srv.address();
	const port = typeof address === "object" && address ? address.port : 0;
	await new Promise<void>((r) => srv.close(() => r()));
	return port;
}

async function startStub(): Promise<Stub> {
	const makeServer = (): Server => {
		const mcp = new Server(
			{ name: "stub-upstream", version: "1.0.0" },
			{ capabilities: { tools: {} } },
		);
		mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
			tools: [
				{ name: "echo", description: "echo", inputSchema: { type: "object", properties: {} } },
				{ name: "projects", description: "projects", inputSchema: { type: "object", properties: {} } },
				{ name: "moot_register_project", description: "should be denied", inputSchema: { type: "object", properties: {} } },
			],
		}));
		mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
			if (req.params.name === "echo") {
				return {
					content: [{ type: "text", text: JSON.stringify({ echoed: req.params.arguments, project: "stub" }) }],
				};
			}
			if (req.params.name === "projects") {
				return {
					content: [
						{
							type: "text",
							text: JSON.stringify([{ id: "stub", token: "moot_leaked_token", name: "stub" }]),
						},
					],
				};
			}
			return { content: [{ type: "text", text: "nope" }], isError: true };
		});
		return mcp;
	};

	const server = createHttpServer((req, res) => {
		const url = new URL(req.url ?? "/", "http://127.0.0.1");
		if (url.pathname === "/projects") {
			const payload =
				req.method === "GET"
					? { projects: [{ id: "stub", token: "moot_stub_token" }] }
					: { id: "stub", name: "stub", token: "moot_stub_token" };
			const data = Buffer.from(JSON.stringify(payload));
			res.writeHead(200, { "content-type": "application/json", "content-length": String(data.length) });
			res.end(data);
			return;
		}
		const mcp = makeServer();
		const transport = new StreamableHTTPServerTransport({
			sessionIdGenerator: undefined,
			enableJsonResponse: true,
		});
		res.on("close", () => {
			void transport.close().catch(() => {});
			void mcp.close().catch(() => {});
		});
		void mcp
			.connect(transport)
			.then(() => transport.handleRequest(req, res))
			.catch((e) => console.error("STUB ERR", e));
	});
	const port = await getFreePort();
	await new Promise<void>((r) => server.listen(port, "127.0.0.1", r));
	const base = `http://127.0.0.1:${port}`;
	return {
		url: `${base}/mcp`,
		projectsUrl: `${base}/projects`,
		close: async () => {
			await new Promise<void>((r) => server.close(() => r()));
		},
	};
}

interface Started {
	base: string;
	cfg: GatewayConfig;
	close(): Promise<void>;
}

async function startGateway(): Promise<Started> {
	const stub = await startStub();
	const port = await getFreePort();
	const stateDir = mkdtempSync(join(tmpdir(), "moot-gateway-test-"));
	const base = `http://127.0.0.1:${port}`;
	const cfg: GatewayConfig = {
		host: "127.0.0.1",
		port,
		origin: new URL(base),
		issuer: new URL(base),
		mcpResource: new URL(`${base}/mcp`),
		mcpPath: "/mcp",
		upstream: { name: "stub", url: new URL(stub.url), projectsUrl: new URL(stub.projectsUrl) },
		oauth: { accessTokenTtl: 3600, scopes: ["mcp"], clients: [] },
		denyTools: ["moot_register_project"],
		stateDir,
	};
	const jwks = await loadOrCreateJwks(join(stateDir, "jwks.json"));
	const provider = createOAuthProvider(cfg, jwks);
	const verify = createTokenVerifier(cfg, jwks);
	const upstream = new UpstreamPool(cfg, new MootIdentityResolver(cfg));
	const server = createGatewayHttpServer({ cfg, provider, verify, upstream });
	await new Promise<void>((r) => server.listen(port, "127.0.0.1", r));
	return {
		base,
		cfg,
		close: async () => {
			await upstream.close();
			await new Promise<void>((r) => server.close(() => r()));
			await stub.close();
			rmSync(stateDir, { recursive: true, force: true });
		},
	};
}

async function register(base: string, name: string): Promise<{ client_id: string; client_secret: string }> {
	const res = await fetch(`${base}/reg`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({
			client_name: name,
			redirect_uris: [],
			grant_types: ["client_credentials"],
			token_endpoint_auth_method: "client_secret_basic",
		}),
	});
	assert.equal(res.status, 201);
	return (await res.json()) as { client_id: string; client_secret: string };
}

async function mintToken(base: string, client: { client_id: string; client_secret: string }): Promise<string> {
	const basic = Buffer.from(`${client.client_id}:${client.client_secret}`).toString("base64");
	const body = new URLSearchParams({
		grant_type: "client_credentials",
		resource: `${base}/mcp`,
		scope: "mcp",
	});
	const res = await fetch(`${base}/token`, {
		method: "POST",
		headers: { authorization: `Basic ${basic}`, "content-type": "application/x-www-form-urlencoded" },
		body,
	});
	const text = await res.text();
	assert.equal(res.status, 200, text);
	const json = JSON.parse(text) as { access_token: string; token_type: string; expires_in: number };
	assert.equal(json.token_type, "Bearer");
	assert.ok(json.expires_in > 0);
	return json.access_token;
}

async function mcpCall(base: string, token: string, payload: unknown): Promise<unknown> {
	const res = await fetch(`${base}/mcp`, {
		method: "POST",
		headers: {
			authorization: `Bearer ${token}`,
			"content-type": "application/json",
			accept: "application/json, text/event-stream",
		},
		body: JSON.stringify(payload),
	});
	const text = await res.text();
	assert.equal(res.status, 200, text);
	return JSON.parse(text) as unknown;
}

test("PRM 同时支持根路径与 path-aware 路径", async () => {
	const gw = await startGateway();
	try {
		for (const path of ["/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"]) {
			const res = await fetch(`${gw.base}${path}`);
			assert.equal(res.status, 200);
			const body = (await res.json()) as { resource: string; authorization_servers: string[] };
			assert.equal(body.resource, `${gw.base}/mcp`);
			assert.deepEqual(body.authorization_servers, [`${gw.base}/`]);
		}
	} finally {
		await gw.close();
	}
});

test("未携带 token 的 /mcp 返回 401 + RFC 9728 挑战", async () => {
	const gw = await startGateway();
	try {
		const res = await fetch(`${gw.base}/mcp`, {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
		});
		assert.equal(res.status, 401);
		assert.match(res.headers.get("www-authenticate") ?? "", /resource_metadata=".+\/\.well-known\/oauth-protected-resource\/mcp"/);
	} finally {
		await gw.close();
	}
});

test("DCR + client_credentials + MCP 工具透传", async () => {
	const gw = await startGateway();
	try {
		const client = await register(gw.base, "proj-alpha");
		const token = await mintToken(gw.base, client);

		const init = (await mcpCall(gw.base, token, {
			jsonrpc: "2.0",
			id: 1,
			method: "initialize",
			params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "1" } },
		})) as { result: { serverInfo: { name: string } } };
		assert.equal(init.result.serverInfo.name, "moot-gateway");

		const listed = (await mcpCall(gw.base, token, { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} })) as {
			result: { tools: { name: string }[] };
		};
		const names = listed.result.tools.map((t) => t.name);
		assert.ok(names.includes("echo"));
		assert.ok(!names.includes("moot_register_project"), "denyTools 应过滤掉注册工具");

		const echoed = (await mcpCall(gw.base, token, {
			jsonrpc: "2.0",
			id: 3,
			method: "tools/call",
			params: { name: "echo", arguments: { hello: "world" } },
		})) as { result: { content: { text: string }[] } };
		assert.deepEqual(JSON.parse(echoed.result.content[0].text), { echoed: { hello: "world" }, project: "stub" });
	} finally {
		await gw.close();
	}
});

test("上游结果中的 token 字段被脱敏", async () => {
	const gw = await startGateway();
	try {
		const client = await register(gw.base, "proj-redact");
		const token = await mintToken(gw.base, client);
		const out = (await mcpCall(gw.base, token, {
			jsonrpc: "2.0",
			id: 4,
			method: "tools/call",
			params: { name: "projects", arguments: {} },
		})) as { result: { content: { text: string }[] } };
		const parsed = JSON.parse(out.result.content[0].text) as { id: string; token?: string }[];
		assert.equal(parsed[0].id, "stub");
		assert.equal(parsed[0].token, undefined);
	} finally {
		await gw.close();
	}
});

test("无效 token 返回 401 invalid_token", async () => {
	const gw = await startGateway();
	try {
		const res = await fetch(`${gw.base}/mcp`, {
			method: "POST",
			headers: { authorization: "Bearer not-a-token", "content-type": "application/json" },
			body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
		});
		assert.equal(res.status, 401);
		assert.match(res.headers.get("www-authenticate") ?? "", /error="invalid_token"/);
	} finally {
		await gw.close();
	}
});

test("loadConfig 支持环境变量覆盖与默认值", () => {
	const cfg = loadConfig(
		{
			PORT: "19001",
			MOOT_UPSTREAM_URL: "http://127.0.0.1:19000/mcp",
			MOOT_OAUTH_SCOPES: "mcp,extra",
		},
		"/tmp/does-not-exist",
	);
	assert.equal(cfg.port, 19001);
	assert.equal(cfg.mcpResource.href, "http://127.0.0.1:19001/mcp");
	assert.equal(cfg.upstream.url.href, "http://127.0.0.1:19000/mcp");
	assert.equal(cfg.upstream.projectsUrl.href, "http://127.0.0.1:19000/projects");
	assert.deepEqual(cfg.oauth.scopes, ["mcp", "extra"]);
	assert.deepEqual(cfg.denyTools, ["moot_register_project"]);
});
