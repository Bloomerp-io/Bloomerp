import createDOMPurify, { type DOMPurify, type WindowLike } from 'dompurify';
import { Marked, type Tokens } from 'marked';
import Turndown from 'turndown';
import { gfm } from 'turndown-plugin-gfm';

/** Preserve model-supplied HTML as visible text rather than active markup. */
function escapeHtml(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Escape raw HTML tokens, including incomplete tags received during streaming. */
function renderHtml(token: Tokens.HTML | Tokens.Tag): string {
    return escapeHtml(token.text);
}

/** Show image labels without fetching model-supplied remote resources. */
function renderImage(token: Tokens.Image): string {
    return escapeHtml(token.text);
}

const markdown = new Marked({async: false, gfm: true, renderer: {html: renderHtml, image: renderImage}});
const sanitizers = new WeakMap<Document, DOMPurify>();
const formatter = new Turndown({headingStyle: 'atx', codeBlockStyle: 'fenced'}).use(gfm);

/** Convert saved editor HTML to chat Markdown while keeping images in the attachment flow. */
export function formatAgentPrompt(html: string, document: Document): string {
    const template = document.createElement('template');
    template.innerHTML = html;
    for (const element of template.content.querySelectorAll('img, script, style')) element.remove();
    // Lexical's export can wrap a semantic mark in a second equivalent element.
    for (const mark of template.content.querySelectorAll(':is(b, strong) :is(b, strong), :is(i, em) :is(i, em), :is(s, strike, del) :is(s, strike, del), code code')) {
        mark.replaceWith(...mark.childNodes);
    }
    for (const table of template.content.querySelectorAll('table')) {
        const firstRow = table.rows[0];
        if (!firstRow?.cells.length) {
            table.remove();
        } else if (Array.from(firstRow.cells).some(isDataCell)) {
            const row = table.createTHead().insertRow(0);
            for (const cell of firstRow.cells) {
                const heading = document.createElement('th');
                heading.colSpan = cell.colSpan;
                row.append(heading);
            }
        }
    }
    return formatter.turndown(template.content);
}

/** Identify the first row of a table that needs an empty Markdown heading. */
function isDataCell(cell: HTMLTableCellElement): boolean { return cell.tagName === 'TD'; }

/** Render formatted messages safely and display plain text literally. */
export function renderAgentMessage(target: HTMLElement, content: string, user: boolean, markdownForm: boolean = !user): void {
    if (!markdownForm) {
        target.textContent = content;
        return;
    }
    try {
        const document = target.ownerDocument;
        let sanitizer = sanitizers.get(document);
        if (!sanitizer) {
            if (!document.defaultView) throw new Error('A browser document is required');
            sanitizer = createDOMPurify(document.defaultView as unknown as WindowLike);
            sanitizers.set(document, sanitizer);
        }
        const html = markdown.parse(content, {async: false});
        const fragment = sanitizer.sanitize(html, {
            ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'del', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td'],
            ALLOWED_ATTR: ['href', 'title', 'start', 'align'],
            ALLOW_DATA_ATTR: false,
            ALLOW_ARIA_ATTR: false,
            RETURN_DOM_FRAGMENT: true,
        });
        // These wrappers are application-owned; untrusted HTML cannot supply classes or attributes.
        for (const table of fragment.querySelectorAll('table')) {
            const wrapper = document.createElement('div');
            wrapper.className = 'agent-markdown-table';
            table.replaceWith(wrapper);
            wrapper.append(table);
        }
        target.replaceChildren(fragment);
    } catch {
        // A renderer failure must never discard the accumulated response.
        target.textContent = content;
    }
}
