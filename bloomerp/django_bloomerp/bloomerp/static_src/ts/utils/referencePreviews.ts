import { attachObjectPreviewTooltip } from './objectPreviewTooltip.ts';

/** Bind object tokens to the shared preview utility as editor content changes. */
export function bindReferencePreviews(root: HTMLElement): () => void {
    const bindings = new Map<HTMLElement, { key: string; cleanup: () => void }>();
    /** Reconcile token listeners after Lexical edits or imported HTML changes. */
    function synchronize(): void {
        const tokens = new Set(root.querySelectorAll<HTMLElement>('[data-reference-kind="object"][data-target-content-type-id][data-target-id]'));
        for (const [element, binding] of bindings) {
            if (!tokens.has(element)) { binding.cleanup(); bindings.delete(element); }
        }
        for (const element of tokens) {
            const objectId = element.dataset.targetId!;
            const contentTypeId = element.dataset.targetContentTypeId!;
            const key = `${contentTypeId}:${objectId}:${element.dataset.referenceUrl || ''}`;
            if (bindings.get(element)?.key === key) continue;
            bindings.get(element)?.cleanup();
            const cleanupPreview = attachObjectPreviewTooltip({ element, objectId, contentTypeId });
            const controller = new AbortController();
            element.tabIndex = 0;
            const raw = element.dataset.referenceUrl;
            let url: URL | null = null;
            try { url = raw ? new URL(raw, location.origin) : null; } catch { /* Malformed stored URLs never navigate. */ }
            const navigable = url && url.origin === location.origin && ['http:', 'https:'].includes(url.protocol);
            element.setAttribute('role', navigable ? 'link' : 'button');
            /** Follow only same-origin application links supplied by object metadata. */
            function navigate(event: MouseEvent | KeyboardEvent): void {
                if (!navigable || !url || (event instanceof KeyboardEvent && event.key !== 'Enter')) return;
                event.preventDefault();
                event.stopPropagation();
                if (event.ctrlKey || event.metaKey) window.open(url.href, '_blank', 'noopener');
                else location.assign(url.href);
            }
            element.addEventListener('click', navigate, { signal: controller.signal });
            element.addEventListener('keydown', navigate, { signal: controller.signal });
            /** Release preview timers and navigation listeners for a removed token. */
            function cleanup(): void { cleanupPreview(); controller.abort(); }
            bindings.set(element, { key, cleanup });
        }
    }
    const observer = new MutationObserver(synchronize);
    observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-reference-kind', 'data-target-id', 'data-target-content-type-id', 'data-reference-url'] });
    synchronize();
    /** Stop watching the editor or timeline and release every attached preview. */
    return function cleanupReferences(): void {
        observer.disconnect();
        for (const binding of bindings.values()) binding.cleanup();
        bindings.clear();
    };
}
