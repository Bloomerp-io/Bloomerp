import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import postcss from 'postcss';

const template = readFileSync(new URL('../../../templates/cotton/features/document_templates/builder.html', import.meta.url), 'utf8');
const css = postcss.parse(template.match(/<style>([\s\S]*?)<\/style>/)![1]);
const darkRule = css.nodes.flatMap(function screenRules(node: postcss.ChildNode): postcss.ChildNode[] {
    /** Inspect only screen rules; editing colors must never become print styles. */
    return node.type === 'atrule' && node.name === 'media' && node.params === 'screen' ? node.nodes || [] : [];
}).find(function themedPage(node: postcss.ChildNode): boolean {
    /** Locate the unstyled-document fallback rather than the paper baseline. */
    return node.type === 'rule' && node.selector.includes(':not([data-document-styling');
}) as postcss.Rule;

/** Build an isolated editor fixture with the real document-reset style element. */
function page(dark: boolean, content: string = '', styled: boolean = false): HTMLElement {
    const dom = new JSDOM(`<html class="${dark ? 'dark' : ''}"><body>
        <div class="document-template-builder-page" data-document-styling="${styled}">
            <div id="page-header-section"></div>
            <style>:where(.editor, .editor *) { all: revert; }</style>
            <div class="editor">${content}</div>
        </div></body></html>`);
    return dom.window.document.querySelector('.document-template-builder-page')!;
}

/** Read one declaration from the actual builder CSS. */
function declaration(rule: postcss.Rule, property: string): string | undefined {
    let result: string | undefined;
    rule.walkDecls(property, function readDeclaration(value: postcss.Declaration): void {
        /** Capture the declaration without relying on minified assets. */
        result = value.value;
    });
    return result;
}

test('unstyled dark documents use the app surface and readable foreground', function unstyledDark(): void {
    /** Reset styles and normal Lexical whitespace must not force white paper. */
    assert.equal(page(true, '<p><span style="white-space: pre-wrap">Content</span></p>').matches(darkRule.selector), true);
    assert.equal(declaration(darkRule, 'background'), 'var(--color-base)');
    assert.equal(declaration(darkRule, 'color'), 'var(--color-zinc-100)');
});

test('light mode and applied styles preserve the paper baseline', function preservePaper(): void {
    /** A CSS foreground alone may rely on white paper, so do not recolor it. */
    assert.equal(page(false).matches(darkRule.selector), false);
    assert.equal(page(true, '<p>Custom document</p>', true).matches(darkRule.selector), false);
    for (const content of [
        '<p style="color: black">Black text</p>',
        '<p style="BACKGROUND: white">White panel</p>',
        '<img src="logo.png" alt="Document logo">',
        '<svg></svg>',
    ]) {
        assert.equal(page(true, content).matches(darkRule.selector), false, content);
    }
});

test('removing applied styling immediately restores dark editing', function repeatChanges(): void {
    /** CSS selection updates without serializing appearance into document content. */
    const element = page(true, '<p style="color: black">Content</p>', true);
    const original = element.querySelector('.editor')!.innerHTML;
    element.dataset.documentStyling = 'false';
    assert.equal(element.matches(darkRule.selector), false);
    assert.equal(element.querySelector('.editor')!.innerHTML, original);
    element.querySelector('p')!.removeAttribute('style');
    assert.equal(element.matches(darkRule.selector), true);
    element.ownerDocument.documentElement.classList.remove('dark');
    assert.equal(element.matches(darkRule.selector), false);
});

test('screen-only page borders match dark inputs and keep editor styling override', function boundaryContract(): void {
    /** Border belongs to the builder frame, never to the saved editor HTML. */
    const media = css.nodes.find(function screenMedia(node: postcss.ChildNode): boolean {
        /** Find the single screen-only appearance override. */
        return node.type === 'atrule' && node.name === 'media';
    }) as postcss.AtRule;
    assert.equal(media.params, 'screen');
    const frame = media.nodes![0] as postcss.Rule;
    assert.equal(declaration(frame, 'border'), '1px solid var(--color-zinc-600)');
    assert.equal(declaration(frame, 'color'), '#000000');
    assert.match(template, /override_default_styling="True"/);
    assert.match(template, /:has\([^)]*#page-header-section style/);
});
