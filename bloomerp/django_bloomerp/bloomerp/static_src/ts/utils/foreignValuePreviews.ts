import { attachObjectPreviewTooltip } from './objectPreviewTooltip';

/** Bind dataview foreign values without introducing nested cell/component identities. */
export function bindForeignValuePreviews(root: HTMLElement): () => void {
    const bindings = new Map<HTMLElement, { key: string; anchor: HTMLElement; cleanup: () => void }>();
    const selector = '[data-foreign-preview-object-id][data-foreign-preview-content-type-id]';

    /** Reconcile preview anchors after pagination, lane moves, calendar refreshes and HTMX swaps. */
    function synchronize(): void {
        const targets = new Set(root.querySelectorAll<HTMLElement>(selector));
        for (const [target, binding] of bindings) {
            if (!targets.has(target)) { binding.cleanup(); bindings.delete(target); }
        }
        for (const target of targets) {
            const objectId = target.dataset.foreignPreviewObjectId?.trim();
            const contentTypeId = target.dataset.foreignPreviewContentTypeId?.trim();
            const anchor = target.querySelector<HTMLElement>('a[href]') ?? target;
            const key = `${contentTypeId}:${objectId}`;
            const existing = bindings.get(target);
            if (existing?.key === key && existing.anchor === anchor) continue;
            existing?.cleanup();
            bindings.delete(target);
            if (!objectId || !contentTypeId || !/^\d+$/.test(contentTypeId)) continue;
            bindings.set(target, {
                key, anchor,
                cleanup: attachObjectPreviewTooltip({ element: anchor, objectId, contentTypeId }),
            });
        }
    }

    /** Release a fragment before HTMX removes it, including delayed hover requests. */
    function onCleanup(event: Event): void {
        const element = (event as CustomEvent<{ elt?: HTMLElement }>).detail?.elt ?? event.target;
        if (element === root) { cleanup(); return; }
        if (!(element instanceof Element)) return;
        for (const [target, binding] of bindings) {
            if (element.contains(target) || element.contains(binding.anchor)) {
                binding.cleanup(); bindings.delete(target);
            }
        }
    }

    const observer = new MutationObserver(synchronize);
    observer.observe(root, {
        childList: true, subtree: true, attributes: true,
        attributeFilter: ['data-foreign-preview-object-id', 'data-foreign-preview-content-type-id'],
    });
    root.addEventListener('htmx:beforeCleanupElement', onCleanup);
    synchronize();

    /** Stop observing a dataview and release every preview listener it owns. */
    function cleanup(): void {
        observer.disconnect();
        root.removeEventListener('htmx:beforeCleanupElement', onCleanup);
        for (const binding of bindings.values()) binding.cleanup();
        bindings.clear();
    }
    return cleanup;
}
