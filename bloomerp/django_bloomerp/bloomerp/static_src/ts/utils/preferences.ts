import htmx from "htmx.org";
import { getCsrfToken } from "./cookies";

export interface SavePreferenceOptions {
    target: HTMLElement;
    source?: HTMLElement;
    swap?: "innerHTML" | "outerHTML" | "none";
    queryParams?: Record<string, string | number | boolean>;
    headers?: Record<string, string>;
}

/** Save preference values with CSRF protection and swap the endpoint's response into its target. */
export default async function savePreference(
    url: string,
    values: Record<string, string | string[]>,
    options: SavePreferenceOptions,
): Promise<void> {
    const requestUrl = new URL(url, window.location.origin);
    for (const [key, value] of Object.entries(options.queryParams ?? {})) {
        requestUrl.searchParams.set(key, String(value));
    }
    await htmx.ajax("post", `${requestUrl.pathname}${requestUrl.search}`, {
        source: options.source ?? options.target,
        target: options.target,
        swap: options.swap ?? "innerHTML",
        values,
        headers: { ...options.headers, "X-CSRFToken": getCsrfToken() || "" },
    });
}
