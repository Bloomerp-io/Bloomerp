import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { renderAgentMessage } from './agentMarkdown.ts';

/** Create a browser-owned message target without executing scripts or fetching resources. */
function messageTarget(): HTMLElement {
    const dom = new JSDOM('<div id="message"></div>', {url: 'https://erp.test/chat/'});
    return dom.window.document.getElementById('message')!;
}

/** Render ordinary block and inline Markdown, including a scrollable aligned table. */
function formatsAssistantMarkdown(): void {
    const target = messageTarget();
    renderAgentMessage(target, '# Heading\n\n**Bold** and *italic*, ~~old~~, `inline`.\n\n- First\n- Second\n\n3. Third\n\n> Quote\n\n| Name | Value |\n| --- | ---: |\n| Item | 2 |\n\n[Details](/details/)\n\n---', false);
    assert.equal(target.querySelector('h1')?.textContent, 'Heading');
    assert.equal(target.querySelector('strong')?.textContent, 'Bold');
    assert.equal(target.querySelector('em')?.textContent, 'italic');
    assert.equal(target.querySelector('del')?.textContent, 'old');
    assert.equal(target.querySelector('code')?.textContent, 'inline');
    assert.equal(target.querySelectorAll('ul > li').length, 2);
    assert.equal(target.querySelector('ol')?.getAttribute('start'), '3');
    assert.equal(target.querySelector('blockquote')?.textContent?.trim(), 'Quote');
    assert.ok(target.querySelector('.agent-markdown-table > table'));
    assert.equal(target.querySelector('td[align="right"]')?.textContent, '2');
    assert.equal(target.querySelector('a')?.getAttribute('href'), '/details/');
    assert.ok(target.querySelector('hr'));
}

/** Preserve literal user Markdown and HTML without creating any child elements. */
function keepsUserTextLiteral(): void {
    const target = messageTarget();
    const content = '# Title\n**bold** <img src=x onerror=alert(1)>\nSecond line';
    renderAgentMessage(target, content, true);
    assert.equal(target.textContent, content);
    assert.equal(target.children.length, 0);
}

/** Reparse every streamed prefix safely and converge to the same HTML as restored history. */
function handlesPartialStreams(): void {
    const streamed = messageTarget();
    const history = messageTarget();
    const content = '## Result\n\n```html\n<div onclick="bad()">literal code</div>\n```\n\n[Read more](https://example.com/page)\n\n**Finished**';
    for (let length = 1; length <= content.length; length += 1) {
        /** Render one incomplete prefix through the same production Markdown parser. */
        function renderPrefix(): void {
            renderAgentMessage(streamed, content.slice(0, length), false);
        }
        assert.doesNotThrow(renderPrefix);
        assert.equal(streamed.querySelector('[onclick]'), null);
    }
    renderAgentMessage(history, content, false);
    assert.equal(streamed.innerHTML, history.innerHTML);
    assert.equal(streamed.querySelector('pre code')?.textContent, '<div onclick="bad()">literal code</div>\n');
    renderAgentMessage(streamed, '```python\nprint("still streaming")', false);
    assert.equal(streamed.querySelector('pre code')?.textContent, 'print("still streaming")\n');
    renderAgentMessage(streamed, '[unfinished](https://exam', false);
    assert.ok(streamed.textContent?.includes('[unfinished](https://exam'));
}

/** Escape raw HTML instead of activating scripts, components, event handlers or HTMX. */
function escapesUntrustedHtml(): void {
    const target = messageTarget();
    const content = '<div bloomerp-component="agent-chat" hx-get="/delete/" data-agent-action="cancel" onclick="bad()">Hello</div>\n\n<script>alert(1)</script>\n\n<svg onload="bad()"></svg>\n\n<img src=x onerror="bad()">';
    renderAgentMessage(target, content, false);
    assert.equal(target.querySelector('div, script, svg, img, [bloomerp-component], [hx-get], [onclick]'), null);
    assert.ok(target.textContent?.includes('<script>alert(1)</script>'));
    assert.ok(target.textContent?.includes('bloomerp-component="agent-chat"'));
}

/** Strip unsafe link destinations while preserving safe links and visible labels. */
function sanitizesLinks(): void {
    const target = messageTarget();
    for (const url of ['javascript:alert%281%29', 'javascript&#58;alert%281%29', 'data:text/html,bad', 'vbscript:bad']) {
        renderAgentMessage(target, `[Unsafe](${url})`, false);
        assert.equal(target.querySelector('a[href]'), null);
        assert.equal(target.textContent?.trim(), 'Unsafe');
    }
    renderAgentMessage(target, '[Safe](https://example.com "Title") and [Email](mailto:test@example.com)', false);
    assert.equal(target.querySelectorAll('a[href]').length, 2);
    assert.equal(target.querySelector('a')?.getAttribute('title'), 'Title');
    assert.equal(target.querySelector('[target], [style], [id]'), null);
}

/** Display image descriptions without triggering external resource loads. */
function keepsImageLabels(): void {
    const target = messageTarget();
    renderAgentMessage(target, '![Diagram](https://example.com/tracking.png)', false);
    assert.equal(target.querySelector('img'), null);
    assert.equal(target.textContent?.trim(), 'Diagram');
}

/** Retain the raw response if the document cannot provide the sanitizer's browser APIs. */
function fallsBackWithoutBrowser(): void {
    const document = messageTarget().ownerDocument.implementation.createHTMLDocument();
    const target = document.createElement('div');
    renderAgentMessage(target, '**Keep this text**', false);
    assert.equal(target.textContent, '**Keep this text**');
}

test('assistant Markdown formats blocks and inline text', formatsAssistantMarkdown);
test('user messages remain plain text', keepsUserTextLiteral);
test('partial streamed Markdown matches restored history', handlesPartialStreams);
test('raw HTML cannot activate browser or application behavior', escapesUntrustedHtml);
test('unsafe URLs are removed', sanitizesLinks);
test('Markdown images display their labels without loading resources', keepsImageLabels);
test('renderer failures preserve text', fallsBackWithoutBrowser);
