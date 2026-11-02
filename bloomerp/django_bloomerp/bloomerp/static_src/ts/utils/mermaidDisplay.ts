import { renderMermaid } from './mermaid';
import { t as _ } from './i18n';

const selector = 'pre[data-text-editor-mermaid="true"]';
const sources = new WeakMap<HTMLElement, string>();

/** Render saved source without changing the code used for reimport or copy. */
async function renderSavedDiagram(block: HTMLElement): Promise<void> {
    // Lexical owns its own previews and must import the original source unchanged.
    if (block.closest('[bloomerp-component="bloomerp-text-editor"], [contenteditable="true"]')) return;
    const code = block.querySelector<HTMLElement>('code');
    if (!code) return;
    const source = code.textContent ?? '';
    if (sources.get(block) === source && block.querySelector('[data-mermaid-display]')) return;
    sources.set(block, source);
    block.querySelector('[data-mermaid-display]')?.remove();
    code.hidden = false;
    const preview = document.createElement('div');
    preview.dataset.mermaidDisplay = 'true';
    preview.className = 'overflow-x-auto whitespace-normal';
    preview.setAttribute('role', 'img');
    preview.setAttribute('aria-label', _('Mermaid diagram'));
    preview.setAttribute('aria-busy', 'true');
    block.append(preview);
    try {
        const svg = await renderMermaid(source);
        if (!block.isConnected || sources.get(block) !== source || !block.contains(preview)) return;
        preview.innerHTML = svg;
        code.hidden = true;
    } catch (_error: unknown) {
        // Invalid source remains readable; it can still be reimported and corrected.
        preview.hidden = true;
    } finally {
        preview.removeAttribute('aria-busy');
        if (!block.isConnected && sources.get(block) === source) sources.delete(block);
    }
}

/** Hydrate persisted diagrams in messages, previews, and other rich-text displays. */
export function hydrateMermaidBlocks(container: ParentNode): void {
    if (container instanceof HTMLElement && container.matches(selector)) void renderSavedDiagram(container);
    for (const block of container.querySelectorAll<HTMLElement>(selector)) void renderSavedDiagram(block);
}

/** Cover initial HTML, HTMX swaps, and messages appended without a component swap. */
export function setupMermaidDisplay(): void {
    hydrateMermaidBlocks(document);
    /** Scan changed sources and newly inserted subtrees without observing SVG attributes. */
    function hydrateChanges(records: MutationRecord[]): void {
        for (const record of records) {
            const target = record.target instanceof Element ? record.target : record.target.parentElement;
            if (target) {
                const block = target.closest<HTMLElement>(selector);
                if (block) hydrateMermaidBlocks(block);
            }
            for (const node of record.addedNodes) {
                if (node instanceof HTMLElement) hydrateMermaidBlocks(node);
            }
        }
    }
    const observer = new MutationObserver(hydrateChanges);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}
