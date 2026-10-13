import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import postcss from 'postcss';

const stylesheet = postcss.parse(readFileSync(new URL('../../../src/styles.css', import.meta.url), 'utf8'));

/** Read a shared utility's background without depending on minified build output. */
function background(selector: string): string | undefined {
    let value: string | undefined;
    stylesheet.walkRules(function inspectRule(rule: postcss.Rule): void {
        if (!rule.selectors.includes(selector)) return;
        rule.walkDecls('background-color', function inspectDeclaration(declaration: postcss.Declaration): void {
            value = declaration.value;
        });
    });
    return value;
}

test('neutral keyboard highlights contrast with dark menu surfaces', function keyboardHighlights(): void {
    /** Keep both legacy class-driven and ARIA-selected options visible. */
    assert.equal(background('.dark .bg-white'), 'var(--color-zinc-800)');
    assert.equal(background('.dark .bg-gray-100'), 'var(--color-zinc-700)');
    assert.equal(background('.dark .bg-base[aria-selected="true"]'), 'var(--color-zinc-700)');
});

test('stationary hover cannot replace a keyboard highlight with the menu color', function hoveredHighlights(): void {
    /** Result rows, foreign-field actions, and slash options share the same highlight. */
    const selected = background('.dark .bg-gray-100');
    assert.equal(selected, 'var(--color-zinc-700)');
    for (const selector of [
        '.dark .hover\\:bg-gray-100:hover',
        '.dark .hover\\:bg-gray-50:hover',
        '.dark .hover\\:bg-base:hover',
    ]) {
        assert.equal(background(selector), selected, selector);
    }
});

test('selection rules preserve ordinary base surfaces and light-mode utilities', function unchangedSurfaces(): void {
    /** Do not remap bg-base globally or override Tailwind's existing light colors. */
    assert.equal(background('.dark .bg-base'), undefined);
    assert.equal(background('.dark .bg-base[aria-selected="false"]'), undefined);
    for (const selector of ['.bg-base', '.bg-gray-100', '.hover\\:bg-base:hover', '.hover\\:bg-gray-100:hover']) {
        assert.equal(background(selector), undefined, selector);
    }
    let darkBase: string | undefined;
    stylesheet.walkRules('html.dark', function inspectDarkTheme(rule: postcss.Rule): void {
        rule.walkDecls('--color-base', function inspectBase(declaration: postcss.Declaration): void {
            darkBase = declaration.value;
        });
    });
    assert.equal(darkBase, 'var(--color-zinc-800)');
});
