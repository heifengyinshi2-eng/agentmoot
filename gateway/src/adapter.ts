/**
 * oidc-provider 的持久化 adapter（文件级）。
 *
 * 默认的 in-memory adapter 在进程重启后会丢失 DCR 注册的客户端（pi-mcp 会因
 * `invalid_client` 重新注册，但其他客户端未必），且无法多实例共享。这里把每个
 * 记录存成 `<stateDir>/adapter/<type>-<sha256(id)>.json`：id 哈希后作为文件名，
 * 避免路径注入与大小写/非法字符问题。
 */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";

interface Stored {
	payload: Record<string, unknown>;
	expiresAt: number | null;
}

function key(id: string): string {
	return createHash("sha256").update(id).digest("hex");
}

export function createFileAdapter(stateDir: string) {
	const root = join(stateDir, "adapter");
	mkdirSync(root, { recursive: true, mode: 0o700 });

	const file = (name: string, id: string) => join(root, `${name}-${key(id)}.json`);

	return class FileAdapter {
		private name: string;

		constructor(name: string) {
			this.name = name;
		}

		async upsert(id: string, payload: Record<string, unknown>, expiresIn?: number): Promise<void> {
			const f = file(this.name, id);
			const expiresAt = expiresIn ? Date.now() + expiresIn * 1000 : null;
			const tmp = `${f}.tmp`;
			writeFileSync(tmp, JSON.stringify({ payload, expiresAt } satisfies Stored), { mode: 0o600 });
			renameSync(tmp, f);
		}

		async find(id: string): Promise<Record<string, unknown> | undefined> {
			const f = file(this.name, id);
			if (!existsSync(f)) return undefined;
			try {
				const data = JSON.parse(readFileSync(f, "utf-8")) as Stored;
				if (data.expiresAt !== null && Date.now() > data.expiresAt) {
					try {
						unlinkSync(f);
					} catch {
						/* ignore */
					}
					return undefined;
				}
				return data.payload;
			} catch {
				return undefined;
			}
		}

		async findByUserCode(userCode: string): Promise<Record<string, unknown> | undefined> {
			return this.findByField("userCode", userCode);
		}

		async findByUid(uid: string): Promise<Record<string, unknown> | undefined> {
			return this.findByField("uid", uid);
		}

		private async findByField(field: string, value: string): Promise<Record<string, unknown> | undefined> {
			for (const f of readdirSync(root)) {
				if (!f.startsWith(`${this.name}-`)) continue;
				try {
					const data = JSON.parse(readFileSync(join(root, f), "utf-8")) as Stored;
					if ((data.payload as Record<string, unknown>)[field] === value) return data.payload;
				} catch {
					/* 跳过损坏文件 */
				}
			}
			return undefined;
		}

		async consume(id: string): Promise<void> {
			const f = file(this.name, id);
			if (!existsSync(f)) return;
			try {
				const data = JSON.parse(readFileSync(f, "utf-8")) as Stored;
				data.payload.consumed = Math.floor(Date.now() / 1000);
				writeFileSync(f, JSON.stringify(data), { mode: 0o600 });
			} catch {
				/* ignore */
			}
		}

		async destroy(id: string): Promise<void> {
			try {
				unlinkSync(file(this.name, id));
			} catch {
				/* ignore */
			}
		}

		async revokeByGrantId(grantId: string): Promise<void> {
			for (const f of readdirSync(root)) {
				if (!f.startsWith(`${this.name}-`)) continue;
				const p = join(root, f);
				try {
					const data = JSON.parse(readFileSync(p, "utf-8")) as Stored;
					if ((data.payload as Record<string, unknown>).grantId === grantId) unlinkSync(p);
				} catch {
					/* ignore */
				}
			}
		}
	};
}
