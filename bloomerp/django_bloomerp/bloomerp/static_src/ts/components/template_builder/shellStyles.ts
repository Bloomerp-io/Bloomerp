export function injectTemplateBuilderShellStyles(host: HTMLElement): HTMLStyleElement | null {
    if (!host) return null;

    const scopeId = host.id;
    const styleEl = document.createElement("style");
    styleEl.setAttribute("data-template-builder-shell-styles", scopeId);
    styleEl.textContent = `
        #${scopeId} [data-template-builder-page] {
        box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
        }

        #${scopeId} [data-template-builder-editor-root] {
        outline: none;
        cursor: text;
        }

        #${scopeId} .doc-heading-1 {
        margin: 0 0 12px;
        font-size: 30pt;
        line-height: 1.05;
        font-weight: 700;
        }

        #${scopeId} .doc-heading-2 {
        margin: 0 0 10px;
        font-size: 18pt;
        line-height: 1.2;
        font-weight: 700;
        }

        #${scopeId} .doc-heading-3 {
        margin: 0 0 8px;
        font-size: 14pt;
        line-height: 1.3;
        font-weight: 700;
        }

        #${scopeId} .doc-paragraph {
        margin: 0 0 14px;
        }

        #${scopeId} .doc-list-ul,
        #${scopeId} .doc-list-ol {
        margin: 0 0 16px;
        padding-left: 1.4rem;
        }

        #${scopeId} .doc-list-ul {
        list-style-type: disc;
        }

        #${scopeId} .doc-list-ol {
        list-style-type: decimal;
        }

        #${scopeId} .doc-list-item {
        margin-bottom: 0.3rem;
        }

        #${scopeId} .doc-text-bold { font-weight: 700; }
        #${scopeId} .doc-text-italic { font-style: italic; }
        #${scopeId} .doc-text-underline { text-decoration: underline; }

        #${scopeId} .template-builder-toolbar-button {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        border: 1px solid #cbd5e1;
        border-radius: 999px;
        background: #fff;
        color: #334155;
        padding: 0.5rem 0.8rem;
        font-size: 0.875rem;
        font-weight: 500;
        }

        #${scopeId} .template-builder-toolbar-button:hover,
        #${scopeId} .template-builder-style-button:hover {
        background: #f8fafc;
        border-color: #94a3b8;
        }

        #${scopeId} .template-builder-panel-section {
        margin-bottom: 0.9rem;
        border: 1px solid #dbe4f0;
        border-radius: 1rem;
        overflow: hidden;
        background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
        }

        #${scopeId} .template-builder-panel-title {
        margin: 0;
        padding: 0.85rem 0.95rem;
        border-bottom: 1px solid #e2e8f0;
        font-size: 0.82rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #0f172a;
        }

        #${scopeId} .template-builder-block-list {
        display: grid;
        grid-template-columns: 1fr;
        gap: 0.45rem;
        padding: 0.7rem;
        }

        #${scopeId} .template-builder-block-item {
        display: grid;
        grid-template-columns: 2.35rem minmax(0, 1fr) auto;
        align-items: center;
        gap: 0.85rem;
        width: 100%;
        border: 1px solid #e2e8f0;
        border-radius: 0.95rem;
        background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
        padding: 0.8rem 0.9rem;
        text-align: left;
        box-shadow: 0 1px 1px rgba(15, 23, 42, 0.02);
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        }

        #${scopeId} .template-builder-block-item-body {
        display: flex;
        flex-direction: column;
        gap: 0.18rem;
        min-width: 0;
        }

        #${scopeId} .template-builder-block-item-label {
        font-size: 0.95rem;
        font-weight: 600;
        color: #1e293b;
        line-height: 1.2;
        }

        #${scopeId} .template-builder-block-item-description,
        #${scopeId} .template-builder-merge-description,
        #${scopeId} .template-builder-help-copy {
        font-size: 0.82rem;
        color: #64748b;
        line-height: 1.5;
        }

        #${scopeId} .template-builder-merge-list {
        display: grid;
        grid-template-columns: 1fr;
        gap: 0.45rem;
        padding: 0.7rem;
        }

        #${scopeId} .template-builder-merge-item {
        display: grid;
        grid-template-columns: 2.35rem minmax(0, 1fr) auto;
        align-items: center;
        gap: 0.85rem;
        width: 100%;
        border: 1px solid #dbe7ff;
        border-radius: 0.95rem;
        background: linear-gradient(180deg, #f8fbff 0%, #eff6ff 100%);
        padding: 0.8rem 0.9rem;
        text-align: left;
        box-shadow: 0 1px 1px rgba(15, 23, 42, 0.02);
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        }

        #${scopeId} .template-builder-merge-item-body {
        display: flex;
        flex-direction: column;
        gap: 0.22rem;
        min-width: 0;
        }

        #${scopeId} .template-builder-merge-token {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: fit-content;
        min-height: 1.6rem;
        padding: 0 0.55rem;
        border-radius: 999px;
        background: #e0ecff;
        color: #1d4ed8;
        font-size: 0.72rem;
        font-weight: 700;
        line-height: 1;
        white-space: nowrap;
        }

        #${scopeId} .template-builder-merge-label {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: #1e293b;
        font-size: 0.92rem;
        font-weight: 500;
        }

        #${scopeId} .template-builder-block-item-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2.35rem;
        height: 2.35rem;
        border-radius: 0.8rem;
        background: #eff6ff;
        color: #2563eb;
        font-size: 0.9rem;
        flex-shrink: 0;
        }

        #${scopeId} .template-builder-merge-item-icon {
        background: #dbeafe;
        color: #1d4ed8;
        }

        #${scopeId} .template-builder-block-item-chevron {
        color: #94a3b8;
        font-size: 0.78rem;
        flex-shrink: 0;
        transition: transform 0.15s ease, color 0.15s ease;
        }

        #${scopeId} .template-builder-block-item:hover,
        #${scopeId} .template-builder-merge-item:hover {
        transform: translateY(-1px);
        border-color: #bfd0ea;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
        }

        #${scopeId} .template-builder-block-item:hover .template-builder-block-item-chevron,
        #${scopeId} .template-builder-merge-item:hover .template-builder-block-item-chevron {
        transform: translateX(1px);
        color: #64748b;
        }

        #${scopeId} .template-builder-style-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.6rem;
        margin-bottom: 0.9rem;
        }

        #${scopeId} .template-builder-style-button {
        border: 1px solid #cbd5e1;
        border-radius: 0.85rem;
        background: #fff;
        color: #334155;
        padding: 0.7rem 0.8rem;
        font-size: 0.88rem;
        font-weight: 500;
        }

        #${scopeId} .template-builder-layer-list {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        }

        #${scopeId} .template-builder-layer-item {
        border: 1px solid #e2e8f0;
        border-radius: 0.85rem;
        background: #fff;
        padding: 0.7rem 0.8rem;
        color: #334155;
        font-size: 0.88rem;
        }

        #${scopeId} .template-builder-variable-list {
        display: grid;
        grid-template-columns: 1fr;
        gap: 0.55rem;
        padding: 0.7rem;
        }

        #${scopeId} .template-builder-variable-item {
        border: 1px solid #e2e8f0;
        border-radius: 0.95rem;
        background: #fff;
        padding: 0.75rem;
        }

        #${scopeId} .template-builder-variable-item-header {
        display: grid;
        grid-template-columns: 2.35rem minmax(0, 1fr);
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.65rem;
        }

        #${scopeId} .template-builder-variable-item-body {
        display: flex;
        min-width: 0;
        flex-direction: column;
        gap: 0.15rem;
        }

        #${scopeId} .template-builder-variable-label {
        overflow: hidden;
        color: #1e293b;
        font-size: 0.92rem;
        font-weight: 600;
        line-height: 1.25;
        text-overflow: ellipsis;
        white-space: nowrap;
        }

        #${scopeId} .template-builder-variable-description {
        color: #64748b;
        font-size: 0.78rem;
        line-height: 1.3;
        }

        #${scopeId} .template-builder-variable-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
        }

        #${scopeId} .template-builder-variable-action {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        border: 1px solid #dbe7ff;
        border-radius: 999px;
        background: #f8fbff;
        color: #1d4ed8;
        padding: 0.38rem 0.55rem;
        font-size: 0.75rem;
        font-weight: 700;
        line-height: 1;
        }

        #${scopeId} .template-builder-variable-action:hover {
        background: #eff6ff;
        border-color: #bfdbfe;
        }

        #${scopeId} .template-builder-image-node {
        margin: 0 0 1rem;
        cursor: pointer;
        position: relative;
        display: inline-block;
        max-width: 100%;
        }

        #${scopeId} .template-builder-image-node-selected img {
        border-color: #2563eb;
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
        }

        #${scopeId} .template-builder-image-resize-handle {
        position: absolute;
        right: -8px;
        bottom: 24px;
        width: 16px;
        height: 16px;
        border: 2px solid #ffffff;
        border-radius: 999px;
        background: #2563eb;
        box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.25);
        cursor: nwse-resize;
        opacity: 0;
        transition: opacity 0.15s ease;
        }

        #${scopeId} .template-builder-image-node:hover .template-builder-image-resize-handle,
        #${scopeId} .template-builder-image-node-selected .template-builder-image-resize-handle {
        opacity: 1;
        }
    `;

    document.head.appendChild(styleEl);
    return styleEl;
}
