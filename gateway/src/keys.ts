/**
 * Persistent signing keys for the OAuth authorization server.
 *
 * Keys are generated on first start and stored with mode 0600. Keeping them
 * stable means access tokens stay verifiable across restarts.
 */
import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { exportJWK, generateKeyPair, type JWK } from "jose";

export interface Jwks {
	keys: JWK[];
}

/** 去掉 JWK 中的私钥参数，得到可公开的 JWK。 */
export function publicJwk(jwk: JWK): JWK {
	const { d, p, q, dp, dq, qi, oth, k, ...pub } = jwk as JWK & Record<string, unknown>;
	void d;
	void p;
	void q;
	void dp;
	void dq;
	void qi;
	void oth;
	void k;
	return pub as JWK;
}

export async function loadOrCreateJwks(path: string): Promise<Jwks> {
	if (existsSync(path)) {
		const parsed = JSON.parse(readFileSync(path, "utf-8")) as Jwks;
		if (!Array.isArray(parsed.keys) || parsed.keys.length === 0) {
			throw new Error(`JWKS 文件无效: ${path}`);
		}
		return parsed;
	}

	const { privateKey } = await generateKeyPair("RS256", { modulusLength: 2048, extractable: true });
	const jwk = await exportJWK(privateKey);
	jwk.use = "sig";
	jwk.alg = "RS256";
	jwk.kid = `moot-${Date.now().toString(36)}`;
	const jwks: Jwks = { keys: [jwk] };

	mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
	const tmp = `${path}.tmp`;
	writeFileSync(tmp, JSON.stringify(jwks, null, 2), { mode: 0o600 });
	try {
		chmodSync(tmp, 0o600);
	} catch {
		/* Windows 忽略 mode */
	}
	renameSync(tmp, path);
	return jwks;
}
