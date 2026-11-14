/**
 * moot gateway entrypoint.
 *
 * Usage:
 *   node src/index.ts
 *   PORT=18081 MOOT_UPSTREAM_URL=http://127.0.0.1:18080/mcp node src/index.ts
 */
import { resolve } from "node:path";
import { loadConfig } from "./config.ts";
import { createGatewayHttpServer } from "./http.ts";
import { MootIdentityResolver } from "./identity.ts";
import { loadOrCreateJwks } from "./keys.ts";
import { createOAuthProvider, createTokenVerifier } from "./oauth.ts";
import { UpstreamPool } from "./upstream.ts";

async function main(): Promise<void> {
	const cfg = loadConfig();
	const jwks = await loadOrCreateJwks(resolve(cfg.stateDir, "jwks.json"));
	const provider = createOAuthProvider(cfg, jwks);
	const verify = createTokenVerifier(cfg, jwks);
	const upstream = new UpstreamPool(cfg, new MootIdentityResolver(cfg));
	const server = createGatewayHttpServer({ cfg, provider, verify, upstream });

	await new Promise<void>((resolveListen) => server.listen(cfg.port, cfg.host, resolveListen));

	const prm = new URL(`/.well-known/oauth-protected-resource${cfg.mcpPath}`, cfg.issuer).href;
	console.log(`moot gateway listening on ${cfg.origin.href}`);
	console.log(`  MCP endpoint : ${cfg.mcpResource.href}`);
	console.log(`  OAuth issuer : ${cfg.issuer.href}`);
	console.log(`  PRM          : ${prm}`);
	console.log(`  Upstream     : ${cfg.upstream.url.href}`);
	if (!cfg.oauth.initialAccessToken) {
		console.log("  DCR          : open (loopback dev only; set MOOT_INITIAL_ACCESS_TOKEN to require a token)");
	}

	const shutdown = (signal: string) => {
		console.log(`\n${signal}: shutting down`);
		server.close(() => {
			void upstream.close().finally(() => process.exit(0));
		});
		setTimeout(() => process.exit(1), 5_000).unref();
	};
	process.on("SIGINT", () => shutdown("SIGINT"));
	process.on("SIGTERM", () => shutdown("SIGTERM"));
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
