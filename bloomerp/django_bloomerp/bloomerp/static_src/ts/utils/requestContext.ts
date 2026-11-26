/** Resolve the nearest context for a programmatic request within Bloomerp. */
export function requestContextHeaders(source: Element | null | undefined, url: string | URL): Record<string, string> {
    const id = source?.closest<HTMLElement>('[data-request-context-id]')?.dataset.requestContextId;
    if (!id || new URL(url, window.location.origin).origin !== window.location.origin) return {};
    return { 'X-Bloomerp-Context': id };
}
