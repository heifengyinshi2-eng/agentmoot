/**
 * OAuth 2.1 authorization server for the MCP gateway.
 *
 * Everything protocol-related is delegated to `oidc-provider`:
 *   - RFC 8414 discovery (`/.well-known/oauth-authorization-server`)
 *   - RFC 7591 dynamic client registration (`/reg`)
 *   - client_credentials grant (`/token`)
 *   - JWKS (`/jwks`)
 *
 * Only RFC 9728 Protected Resource Metadata is served by us, because the
 * provider is an authorization server and does not know about resource servers.
 *
 * Identity convention: the DCR `client_name` is the application project id.
 * It is copied into the access token as the `project` claim. The upstream
 * adapter uses that claim to obtain the project-scoped upstream token.
 */
import { randomBytes } from "node:crypto";
import Provider from "oidc-provider";
import { createLocalJWKSet, jwtVerify, type JWTVerifyGetKey, type JWTPayload } from "jose";
import type { GatewayConfig } from "./config.ts";
import type { Jwks } from "./keys.ts";
import { publicJwk } from "./keys.ts";

export interface ProtectedResourceMetadata {
	resource: string;
	authorization_servers: string[];
	scopes_supported: string[];
	bearer_methods_supported: string[];
	resource_name: string;
}

export function protectedResourceMetadata(cfg: GatewayConfig): ProtectedResourceMetadata {
	return {
		resource: cfg.mcpResource.href,
		authorization_servers: [cfg.issuer.href],
		scopes_supported: cfg.oauth.scopes,
		bearer_methods_supported: ["header"],
		resource_name: cfg.upstream.name,
	};
}

/** Path-aware PRM URL per RFC 9728 (used in the 401 challenge). */
export function protectedResourceMetadataUrl(cfg: GatewayConfig): string {
	return new URL(`/.well-known/oauth-protected-resource${new URL(cfg.mcpResource).pathname}`, cfg.issuer).href;
}

export function createOAuthProvider(cfg: GatewayConfig, jwks: Jwks): Provider {
	const provider = new Provider(cfg.issuer.href, {
		jwks,
		clients: cfg.oauth.clients.map((c) => ({
			client_id: c.client_id,
			client_secret: c.client_secret,
			client_name: c.name ?? c.client_id,
			grant_types: ["client_credentials"],
			token_endpoint_auth_method: "client_secret_basic",
			redirect_uris: [],
		})),
		scopes: cfg.oauth.scopes,
		// 本网关只服务 client_credentials：默认不给客户端授权码相关的响应类型，
		// 否则 DCR 会要求 redirect_uris（pi-mcp 发送的是空数组）。
		clientDefaults: {
			grant_types: ["client_credentials"],
			response_types: [],
			token_endpoint_auth_method: "client_secret_basic",
			id_token_signed_response_alg: "RS256",
		},
		// client_credentials 只需要签发 Access Token，不需要 OIDC / 授权码相关能力。
		features: {
			clientCredentials: { enabled: true },
			registration: cfg.oauth.initialAccessToken
				? { enabled: true, initialAccessToken: cfg.oauth.initialAccessToken }
				: { enabled: true },
			resourceIndicators: {
				enabled: true,
				defaultResource: () => cfg.mcpResource.href,
				getResourceServerInfo: () => ({
					scope: cfg.oauth.scopes.join(" "),
					audience: cfg.mcpResource.href,
					accessTokenFormat: "jwt",
				}),
			},
			// 本期只做机器对机器，关闭用不到的端点，减少攻击面。
			introspection: { enabled: false },
			revocation: { enabled: false },
			userinfo: { enabled: false },
			devInteractions: { enabled: false },
			backchannelLogout: { enabled: false },
			rpInitiatedLogout: { enabled: false },
			deviceFlow: { enabled: false },
			pushedAuthorizationRequests: { enabled: false },
			jwtIntrospection: { enabled: false },
		},
		ttl: {
			AccessToken: cfg.oauth.accessTokenTtl,
			ClientCredentials: cfg.oauth.accessTokenTtl,
		},
		cookies: {
			keys: [randomBytes(32).toString("hex")],
		},
		clientBasedCORS: () => true,
		// 把 client_name（项目 id）写进 JWT access token 的自定义 claim。
		extraTokenClaims: async (_ctx: unknown, token: { client?: { clientName?: string } }) => {
			const project = token.client?.clientName;
			return project ? { project } : undefined;
		},
	});

	// 本地回环开发场景，不允许 provider 走代理时信任 X-Forwarded-*。
	provider.proxy = false;
	return provider;
}

export interface TokenVerifier {
	(token: string): Promise<JWTPayload>;
}

export function createTokenVerifier(cfg: GatewayConfig, jwks: Jwks): TokenVerifier {
	const localJwks = createLocalJWKSet({ keys: jwks.keys.map(publicJwk) }) as unknown as JWTVerifyGetKey;
	return async (token: string) => {
		const { payload } = await jwtVerify(token, localJwks, {
			issuer: cfg.issuer.href,
			audience: cfg.mcpResource.href,
		});
		return payload;
	};
}
