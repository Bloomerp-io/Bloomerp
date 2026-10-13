/** DOM regressions against the production URL widget and component lifecycle. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, type DOMWindow } from 'jsdom';
import type URLWidget from './URLWidget.ts';

const root = fileURLToPath(new URL('../../..', import.meta.url)).replace(/\/$/, '');
const entry = `${root}/url-widget-regression-entry.ts`;
const result = await build({
    configFile: false, root, logLevel: 'silent',
    plugins: [{
        name: 'url-widget-regression-entry',
        /** Resolve the in-memory production component entry. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Share the real widget and component registry in one bundle. */
        load(id: string): string | null {
            return id === entry ? `
                import URLWidget from '${root}/ts/components/widgets/URLWidget';
                import { registerComponent, initComponents, getComponent } from '${root}/ts/components/BaseComponent';
                registerComponent('url-widget', URLWidget);
                export { initComponents, getComponent };
            ` : null;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ['iife'], name: 'URLFixture' } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
/** Select the emitted production JavaScript. */
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;

interface FixtureWindow extends DOMWindow {
    URLFixture: {
        initComponents(element: HTMLElement): void;
        getComponent(element: HTMLElement): URLWidget;
    };
}
interface Fixture {
    dom: JSDOM;
    w: FixtureWindow;
    root: HTMLElement;
    input: HTMLInputElement;
    button: HTMLButtonElement;
    widget: URLWidget;
    opened: unknown[][];
}

/** Create a form with two independently registered URL inputs and record navigation. */
function fixture(): Fixture {
    const dom = new JSDOM(`<!doctype html><form>
        <div bloomerp-component="url-widget"><input type="url" name="website" value="https://old.example"><button type="button" data-open-url disabled><i></i></button></div>
        <div bloomerp-component="url-widget"><input type="url" name="other" value="https://other.example"><button type="button" data-open-url disabled></button></div>
    </form>`, { runScripts: 'outside-only', url: 'https://app.example/' });
    const w = dom.window as FixtureWindow;
    const opened: unknown[][] = [];
    /** Record the URL and security options instead of opening an actual window. */
    w.open = function open(...args: unknown[]): Window | null { opened.push(args); return null; };
    w.eval(scriptCode);
    w.URLFixture.initComponents(w.document.body);
    const root = w.document.querySelector<HTMLElement>('[bloomerp-component="url-widget"]')!;
    return { dom, w, root, input: root.querySelector('input')!, button: root.querySelector('button')!,
        widget: w.URLFixture.getComponent(root), opened };
}

/** Send the same native input event as a user edit. */
function edit(f: Fixture, value: string): void {
    f.input.value = value;
    f.input.dispatchEvent(new f.w.Event('input', { bubbles: true }));
}

test('opens the current edited value in a protected new tab without submitting', function (): void {
    const f = fixture();
    let submissions = 0;
    /** Count unexpected form submissions. */
    function submitted(event: Event): void { event.preventDefault(); submissions += 1; }
    f.w.document.querySelector('form')!.addEventListener('submit', submitted);
    edit(f, 'https://new.example/path?q=1#anchor');
    f.button.querySelector('i')!.click();
    assert.deepEqual(f.opened, [['https://new.example/path?q=1#anchor', '_blank', 'noopener,noreferrer']]);
    assert.equal(submissions, 0);
    assert.equal(f.w.location.href, 'https://app.example/');
    f.dom.window.close();
});

test('blocks blank, malformed and executable URLs, then recovers on the next edit', function (): void {
    const f = fixture();
    for (const value of ['', ' ', 'example.com', '/relative', '//example.com', 'https://', 'javascript:alert(1)', 'data:text/html,hello', 'file:///etc/passwd']) {
        edit(f, value);
        assert.equal(f.button.disabled, true, value);
        f.button.click();
    }
    assert.equal(f.opened.length, 0);
    edit(f, 'https://safe.example');
    f.button.click();
    assert.equal(f.opened.length, 1);
    f.dom.window.close();
});

test('rechecks programmatic changes at click time and never uses stale destinations', function (): void {
    const f = fixture();
    f.input.value = 'https://programmatic.example';
    f.button.click();
    f.input.value = 'javascript:alert(1)';
    f.button.click();
    assert.deepEqual(f.opened, [['https://programmatic.example/', '_blank', 'noopener,noreferrer']]);
    assert.equal(f.button.disabled, true);
    f.dom.window.close();
});

test('keeps multiple inputs independent and repeated initialization single-bound', function (): void {
    const f = fixture();
    f.widget.initialize();
    f.w.URLFixture.initComponents(f.w.document.body);
    f.button.click();
    f.w.document.querySelectorAll<HTMLButtonElement>('button')[1].click();
    assert.equal(f.opened.length, 2);
    assert.equal(f.opened[1][0], 'https://other.example/');
    f.widget.destroy();
    f.button.click();
    assert.equal(f.opened.length, 2);
    f.dom.window.close();
});

test('integrates scalar history and standard change notifications', function (): void {
    const f = fixture();
    let changes = 0;
    /** Count standard widget-change notifications. */
    function changed(): void { changes += 1; }
    f.root.addEventListener('bloomerp:widget-change', changed);
    f.widget.setValue('https://restored.example');
    assert.equal(changes, 0);
    assert.equal(f.widget.getValue(), 'https://restored.example');
    f.widget.setValue('https://changed.example', true);
    assert.equal(changes, 1);
    f.widget.setValue('https://changed.example', true);
    assert.equal(changes, 1);
    edit(f, 'https://typed.example');
    assert.equal(changes, 2);
    f.widget.setSerializableState({ value: null });
    assert.equal(f.input.value, '');
    assert.equal(f.button.disabled, true);
    f.dom.window.close();
});

test('respects disabled fields and fieldsets while allowing a read-only URL to open', function (): void {
    const f = fixture();
    f.input.disabled = true;
    f.button.click();
    assert.equal(f.opened.length, 0);
    f.input.disabled = false;
    f.input.readOnly = true;
    f.widget.onAfterSwap();
    f.button.click();
    assert.equal(f.opened.length, 1);
    const fieldset = f.w.document.createElement('fieldset');
    fieldset.disabled = true;
    f.root.replaceWith(fieldset);
    fieldset.append(f.root);
    f.widget.onAfterSwap();
    assert.equal(f.button.disabled, true);
    f.dom.window.close();
});

test('handles swapped inputs and history restoration without stale input references', function (): void {
    const f = fixture();
    f.root.innerHTML = '<input type="url" value="https://swapped.example"><button type="button" data-open-url disabled></button>';
    f.widget.onAfterSwap();
    f.root.querySelector<HTMLButtonElement>('button')!.click();
    assert.equal(f.opened[0][0], 'https://swapped.example/');
    f.widget.setValue('');
    f.root.querySelector<HTMLInputElement>('input')!.value = 'https://history.example';
    f.widget.onHistoryRestore();
    f.root.querySelector<HTMLButtonElement>('button')!.click();
    assert.equal(f.opened[1][0], 'https://history.example/');
    f.dom.window.close();
});

test('supports every safe URL scheme accepted by the Django URL field', function (): void {
    const f = fixture();
    for (const value of ['http://example.com', 'https://example.com', 'ftp://example.com', 'ftps://example.com']) {
        edit(f, value);
        assert.equal(f.button.disabled, false, value);
        f.button.click();
    }
    assert.equal(f.opened.length, 4);
    f.dom.window.close();
});
