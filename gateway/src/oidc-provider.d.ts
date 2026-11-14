declare module "oidc-provider" {
	import type { IncomingMessage, ServerResponse } from "node:http";

	interface ProviderOptions {
		[key: string]: unknown;
	}

	export default class Provider {
		constructor(issuer: string, options?: ProviderOptions);
		issuer: string;
		proxy: boolean;
		callback(): (req: IncomingMessage, res: ServerResponse) => void;
		Client: {
			find(id: string): Promise<Client | undefined>;
		};
		listen(port?: number, host?: string, callback?: () => void): unknown;
	}
}
