/** Submit locale changes with the current route after HTMX navigation. */
export function updateLanguageReturnTarget(event: Event): void {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches('[data-language-switch]')) return;
    const next = form.querySelector<HTMLInputElement>('input[name="next"]');
    if (next) next.value = window.location.pathname + window.location.search + window.location.hash;
}

/** Keep persistent sidebar locale forms synchronized at submission time. */
export function setupLanguageSwitch(): void {
    document.addEventListener('submit', updateLanguageReturnTarget, { capture: true });
}
