import assert from 'node:assert/strict';
import test, { mock } from 'node:test';
import { JSDOM } from 'jsdom';

/** Check shared preview attachment, safe navigation and editor mutation cleanup. */
async function referenceInteractions(): Promise<void> {
    const dom = new JSDOM('<div id="editor"><span data-reference-kind="object" data-target-content-type-id="12" data-target-id="42" data-reference-url="/objects/42/">Object</span></div>', { url: 'https://erp.test/' });
    let attachments = 0;
    let cleanups = 0;
    let destination = '';
    /** Record that the existing tooltip utility receives each tag identity. */
    function attachPreview(options: { objectId: string; contentTypeId: string }): () => void {
        assert.equal(options.objectId, '42');
        assert.equal(options.contentTypeId, '12');
        attachments++;
        /** Record released listeners without opening a real tooltip. */
        return function cleanupPreview(): void { cleanups++; };
    }
    /** Capture navigation without changing the test document. */
    function assign(url: string): void { destination = url; }
    mock.module('./objectPreviewTooltip.ts', { namedExports: { attachObjectPreviewTooltip: attachPreview } });
    const { bindReferencePreviews } = await import('./referencePreviews.ts');
    Object.assign(globalThis, { MutationObserver: dom.window.MutationObserver, AbortController: dom.window.AbortController, KeyboardEvent: dom.window.KeyboardEvent, location: { origin: 'https://erp.test', assign }, window: dom.window });
    const root = dom.window.document.getElementById('editor')!;
    const cleanup = bindReferencePreviews(root);
    const token = root.querySelector('span')!;
    assert.equal(attachments, 1);
    assert.equal(token.tabIndex, 0);
    token.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    assert.equal(destination, 'https://erp.test/objects/42/');
    token.dataset.referenceUrl = 'javascript:alert(1)';
    await Promise.resolve();
    destination = '';
    token.click();
    assert.equal(destination, '');
    token.remove();
    await Promise.resolve();
    assert.equal(cleanups, attachments);
    root.append(token);
    await Promise.resolve();
    assert.equal(attachments, 3);
    cleanup();
    assert.equal(cleanups, attachments);
    dom.window.close();
    mock.restoreAll();
}

test('object tags reuse previews, navigate safely and release replaced nodes', referenceInteractions);
