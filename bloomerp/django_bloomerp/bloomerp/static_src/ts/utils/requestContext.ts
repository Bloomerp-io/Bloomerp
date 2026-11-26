/** Resolve the nearest context for a programmatic request within Bloomerp. */
export function requestContextHeaders(source: Element | null | undefined, url: string | URL): Record<string, string> {
    const id = source?.closest<HTMLElement>('[data-request-context-id]')?.dataset.requestContextId;
    if (!id || new URL(url, window.location.origin).origin !== window.location.origin) return {};
    return { 'X-Bloomerp-Context': id };
}

/** Fetch from a component, inheriting its nearest same-origin request context. */
export function fetchFromComponent(
    source: Element | null | undefined,
    input: RequestInfo | URL,
    init?: RequestInit,
): Promise<Response> {
    const isRequest = typeof input !== "string" && "url" in input;
    const url = isRequest ? input.url : input;
    const context = requestContextHeaders(source, url)["X-Bloomerp-Context"];
    if (!context) return fetch(input, init);

    const headers = new Headers(init?.headers ?? (isRequest ? input.headers : undefined));
    headers.set("X-Bloomerp-Context", context);
    return fetch(input, { ...init, headers, mode: "same-origin" });
}
