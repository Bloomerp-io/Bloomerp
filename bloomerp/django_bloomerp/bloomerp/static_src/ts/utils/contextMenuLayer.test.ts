import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { getContextMenuLayer } from './contextMenuLayer.ts';

/** Verify the shared menu clears a floating messaging panel and nested modal. */
function floatingEditorLayers(): void {
    const dom = new JSDOM('<section style="position:fixed;z-index:86"><div style="position:relative;z-index:2"><div contenteditable></div></div></section>');
    const editor = dom.window.document.querySelector<HTMLElement>('[contenteditable]')!;
    assert.equal(getContextMenuLayer(editor), 87);
    editor.parentElement!.style.zIndex = '120';
    assert.equal(getContextMenuLayer(editor), 121);
    dom.window.close();
}

/** Keep ordinary editors on the existing default menu layer. */
function defaultEditorLayer(): void {
    const dom = new JSDOM('<div contenteditable></div>');
    assert.equal(getContextMenuLayer(dom.window.document.querySelector<HTMLElement>('div')), 51);
    assert.equal(getContextMenuLayer(null), 51);
    dom.window.close();
}

test('slash and reference menus clear their floating editor containers', floatingEditorLayers);
test('ordinary editors retain the default menu layer', defaultEditorLayer);
