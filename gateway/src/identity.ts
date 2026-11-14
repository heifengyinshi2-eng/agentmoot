/**
 * Upstream identity adapter (the only moot-aware piece).
 *
 * OAuth clients authenticate as a project. The upstream (moot) still uses its
 * own per-project Bearer token, so we resolve it lazily:
 *   1. GET /projects and reuse the existing token when the project exists
 *   2. otherwise POST /projects to register the project
 *
 * This keeps the MCP/OAuth core independent from moot: any upstream that can
 * map a project id to a Bearer token can be plugged in here.
 */
import type { GatewayConfig } from "./config.ts";

interface ProjectRecord {
	id: string;
	name?: string;
	token?: string;
}

export interface IdentityResolver {
	tokenFor(project: string): Promise<string>;
}

export class MootIdentityResolver implements IdentityResolver {
	private readonly cache = new Map<string, string>();

	private readonly cfg: GatewayConfig;

	constructor(cfg: GatewayConfig) {
		this.cfg = cfg;
	}

	async tokenFor(project: string): Promise<string> {
		const cached = this.cache.get(project);
		if (cached) return cached;

		const existing = await this.findProject(project);
		if (existing?.token) {
			this.cache.set(project, existing.token);
			return existing.token;
		}

		const created = await this.registerProject(project);
		if (!created.token) throw new Error(`moot 注册项目 ${project} 未返回 token`);
		this.cache.set(project, created.token);
		return created.token;
	}

	private async findProject(project: string): Promise<ProjectRecord | undefined> {
		const res = await fetch(this.cfg.upstream.projectsUrl, {
			headers: { accept: "application/json" },
		});
		if (!res.ok) {
			throw new Error(`读取 moot 项目列表失败: HTTP ${res.status}`);
		}
		const body = (await res.json()) as { projects?: ProjectRecord[] };
		return body.projects?.find((p) => p.id === project);
	}

	private async registerProject(project: string): Promise<ProjectRecord> {
		const res = await fetch(this.cfg.upstream.projectsUrl, {
			method: "POST",
			headers: { "content-type": "application/json", accept: "application/json" },
			body: JSON.stringify({ id: project, name: project }),
		});
		const text = await res.text();
		let body: unknown;
		try {
			body = text ? JSON.parse(text) : {};
		} catch {
			body = { raw: text };
		}
		if (!res.ok) {
			const detail =
				typeof body === "object" && body !== null && "error" in body
					? String((body as { error: unknown }).error)
					: text;
			throw new Error(`moot 注册项目 ${project} 失败: HTTP ${res.status}${detail ? `: ${detail}` : ""}`);
		}
		return body as ProjectRecord;
	}
}
