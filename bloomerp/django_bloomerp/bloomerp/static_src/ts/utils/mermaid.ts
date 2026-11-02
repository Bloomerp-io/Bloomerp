import DOMPurify from 'dompurify';
import type { Mermaid } from 'mermaid';

let mermaidPromise: Promise<Mermaid> | null = null;
let renderCount = 0;

/** Load every bundled diagram type and prevent source directives from weakening rendering safety. */
async function loadMermaid(): Promise<Mermaid> {
    const { default: mermaid } = await import('mermaid');
    mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        htmlLabels: false,
        suppressErrorRendering: true,
        themeCSS: '',
        secure: [
            'secure', 'securityLevel', 'startOnLoad', 'maxTextSize', 'maxEdges',
            'suppressErrorRendering', 'htmlLabels', 'dompurifyConfig', 'themeCSS',
            'themeVariables', 'fontFamily',
        ],
    });
    return mermaid;
}

/** Render Mermaid source as sanitized SVG without binding interactive diagram callbacks. */
export async function renderMermaid(source: string): Promise<string> {
    mermaidPromise ??= loadMermaid();
    const mermaid = await mermaidPromise;
    const container = document.createElement('div');
    container.setAttribute('aria-hidden', 'true');
    container.style.cssText = 'position:absolute;left:-100000px;top:0;visibility:hidden;pointer-events:none';
    document.body.append(container);

    try {
        // Mermaid queues render calls itself. Keep its measuring container connected even if an
        // editor block is removed while the asynchronous diagram renderer is loading.
        const id = `bloomerp-mermaid-${Date.now()}-${++renderCount}`;
        const { svg } = await mermaid.render(id, source, container);
        return DOMPurify.sanitize(svg, {
            // Some diagram types always use foreignObject for text or mathematics, even with
            // htmlLabels disabled. Sanitize that content without discarding their labels.
            USE_PROFILES: { html: true, svg: true, svgFilters: true, mathMl: true },
            ADD_TAGS: ['foreignObject'],
            HTML_INTEGRATION_POINTS: { foreignobject: true },
            FORBID_TAGS: [
                'a', 'image', 'img', 'iframe', 'object', 'embed', 'form', 'input',
                'button', 'textarea', 'select', 'audio', 'video', 'link',
            ],
            FORBID_ATTR: ['href', 'xlink:href'],
        });
    } finally {
        container.remove();
    }
}
