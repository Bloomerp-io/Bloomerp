import BloomerpSdk from "./sdk";
import { getCsrfToken } from "../utils/cookies";
import { fetchFromComponent } from "../utils/requestContext";

/**
 * Returns an SDK configured to authenticate with the browser session cookies.
 */
function getSdk(baseUrl?: string): BloomerpSdk {
	return createSessionSdk(baseUrl);
}

/** Return the browser SDK with the nearest context for requests from this component. */
export function getSdkForComponent(source: Element | null | undefined): BloomerpSdk {
	return createSessionSdk(undefined, source);
}

/** Configure session authentication and optionally route transport through a component. */
function createSessionSdk(baseUrl?: string, source?: Element | null): BloomerpSdk {
	const resolvedBaseUrl = baseUrl ?? globalThis.location?.origin;

	if (!resolvedBaseUrl) {
		throw new Error("getSdk requires a baseUrl when used outside the browser.");
	}

	return new BloomerpSdk({
		baseUrl: resolvedBaseUrl,
		fetch: source ? fetchFromComponent.bind(null, source) : undefined,
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
