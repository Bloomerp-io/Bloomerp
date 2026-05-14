import BloomerpSdk from "./sdk";
import { getCsrfToken } from "../utils/cookies";

/**
 * Returns an SDK configured to authenticate with the browser session cookies.
 */
function getSdk(baseUrl?: string): BloomerpSdk {
	const resolvedBaseUrl = baseUrl ?? globalThis.location?.origin;

	if (!resolvedBaseUrl) {
		throw new Error("getSdk requires a baseUrl when used outside the browser.");
	}

	return new BloomerpSdk({
		baseUrl: resolvedBaseUrl,
		auth: {
			type: "session",
			credentials: "include",
			csrf: {
				token: getCsrfToken,
			},
		},
	});
}

export { getSdk };
export default getSdk;