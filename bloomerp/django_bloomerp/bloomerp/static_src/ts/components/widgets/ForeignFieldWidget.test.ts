/** Real-widget DOM regressions for foreign-key menus nested in top-layer filters. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { JSDOM, VirtualConsole, type DOMWindow } from 'jsdom';

const root = fileURLToPath(new URL('../../..', import.meta.url));
const result = await build({
    configFile: false, root, logLevel: 'silent',
    resolve: { alias: { '@': `${root}/ts` } },
    build: { write: false, minify: false, lib: {
        entry: `${root}/ts/components/widgets/ForeignFieldWidget.ts`, formats: ['iife'], name: 'ForeignFieldWidget',
    } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
const script = bundle.output.find((item): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;

interface WidgetInstance { initialize(): void; destroy(): void; getValue(): string | string[]; }
interface Fixture { dom: JSDOM; w: DOMWindow; panel: HTMLElement; widget: HTMLElement; input: HTMLInputElement; menu: HTMLElement; component: WidgetInstance; }

/** Instantiate production code with only network and browser geometry replaced. */
async function fixture(popover: boolean = true): Promise<Fixture> {
    const dom = new JSDOM('<!doctype html><body><button id="outside">Outside</button><div id="panel" data-dropdown-panel><div id="widget" data-content-type-id="1" data-field-name="owner"><input type="text"><div class="foreign-field-dropdown hidden"><ul class="foreign-field-results"></ul></div><span id="sibling"></span><div class="foreign-field-selected"></div></div></div></body>', {
        url: 'https://fixture.test', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: new VirtualConsole(),
    });
    const w = dom.window;
    const panel = w.document.getElementById('panel')!;
    if (popover) {
        panel.setAttribute('popover', 'manual');
        const matches = panel.matches.bind(panel);
        /** Model an open native popover; jsdom has no top-layer renderer. */
        panel.matches = (selector: string): boolean => selector === ':popover-open' || matches(selector);
    }
    Object.assign(w, { fetch: async (): Promise<unknown> => ({ ok: true, json: async (): Promise<unknown> => ({ objects: [{id: 7, string_representation: 'Alice'}] }) }) });
    const evaluate = w.XPathExpression.prototype.evaluate;
    /** Supply the browser's default XPath result type for jsdom. */
    w.XPathExpression.prototype.evaluate = function(context: Node, type?: number, res?: XPathResult | null): XPathResult { return evaluate.call(this, context, type ?? 0, res ?? null); };
    w.eval(scriptCode);
    const widget = w.document.getElementById('widget')!;
    const input = widget.querySelector('input')!;
    const menu = widget.querySelector('.foreign-field-dropdown') as HTMLElement;
    const component = new (w as DOMWindow & { ForeignFieldWidget: new (element: HTMLElement) => WidgetInstance }).ForeignFieldWidget(widget);
    component.initialize();
    /** Represent a half-scale transformed parent with borders and internal scroll. */
    panel.getBoundingClientRect = (): DOMRect => ({left: 100, top: 50, width: 200, height: 150} as DOMRect);
    Object.defineProperties(panel, {offsetWidth:{value:400}, offsetHeight:{value:300}, clientLeft:{value:2}, clientTop:{value:2}, scrollLeft:{value:10}, scrollTop:{value:20}});
    input.getBoundingClientRect = (): DOMRect => ({left: 120, bottom: 90, width: 80} as DOMRect);
    input.focus();
    await new Promise<void>((resolve: () => void): void => { w.setTimeout(resolve, 0); });
    return {dom,w,panel,widget,input,menu,component};
}

test('foreign-key results remain inside the top-layer filter and use host coordinates', async (): Promise<void> => {
    const f = await fixture();
    try {
        assert.equal(f.menu.parentElement, f.panel);
        assert.equal(f.menu.style.left, '48px');
        assert.equal(f.menu.style.top, '106px');
        assert.equal(f.menu.style.width, '160px');
        assert.equal(f.menu.classList.contains('hidden'), false);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

test('ordinary widgets preserve the body portal and viewport-plus-scroll coordinates', async (): Promise<void> => {
    const f = await fixture(false);
    try {
        assert.equal(f.menu.parentElement, f.w.document.body);
        assert.equal(f.menu.style.left, '120px');
        assert.equal(f.menu.style.top, '94px');
        assert.equal(f.menu.style.zIndex, '9999');
    } finally { f.component.destroy(); f.dom.window.close(); }
});

test('selection bubbles inside the parent filter and restores the original DOM order', async (): Promise<void> => {
    const f = await fixture();
    try {
        let clicks = 0;
        f.panel.addEventListener('click', (): void => { clicks += 1; });
        f.menu.querySelector<HTMLElement>('li')!.click();
        assert.equal(clicks, 1);
        assert.equal(f.component.getValue(), '7');
        assert.equal(f.menu.parentElement, f.widget);
        assert.equal(f.menu.nextElementSibling!.id, 'sibling');
    } finally { f.component.destroy(); f.dom.window.close(); }
});

test('Escape closes only results and outside clicks restore the portal', async (): Promise<void> => {
    const f = await fixture();
    try {
        const key = new f.w.KeyboardEvent('keydown', {key:'Escape', bubbles:true, cancelable:true});
        f.input.dispatchEvent(key);
        assert.equal(key.defaultPrevented, true);
        assert.equal(f.menu.parentElement, f.widget);
        f.input.dispatchEvent(new f.w.FocusEvent('focus'));
        await new Promise<void>((resolve: () => void): void => { f.w.setTimeout(resolve, 0); });
        assert.equal(f.menu.parentElement, f.panel);
        f.w.document.getElementById('outside')!.click();
        assert.equal(f.menu.parentElement, f.widget);
    } finally { f.component.destroy(); f.dom.window.close(); }
});

test('closing the parent popover and destroying the widget leave no detached results', async (): Promise<void> => {
    const f = await fixture();
    try {
        const event = new f.w.Event('beforetoggle');
        Object.defineProperty(event, 'newState', {value:'closed'});
        f.panel.dispatchEvent(event);
        assert.equal(f.menu.parentElement, f.widget);
        assert.equal(f.menu.classList.contains('hidden'), true);
        assert.equal(f.menu.style.left, '');
    } finally { f.component.destroy(); f.dom.window.close(); }
});


test('repeated results retain restoration state and respond to resize and transition completion', async (): Promise<void> => {
    const f = await fixture();
    try {
        f.input.dispatchEvent(new f.w.FocusEvent('focus'));
        await new Promise<void>((resolve: () => void): void => { f.w.setTimeout(resolve, 0); });
        f.input.getBoundingClientRect = (): DOMRect => ({left:140, bottom:110, width:100} as DOMRect);
        f.w.dispatchEvent(new f.w.Event('resize'));
        assert.equal(f.menu.style.left, '88px');
        assert.equal(f.menu.style.top, '146px');
        assert.equal(f.menu.style.width, '200px');
        f.input.getBoundingClientRect = (): DOMRect => ({left:150, bottom:120, width:100} as DOMRect);
        f.panel.dispatchEvent(new f.w.Event('transitionend'));
        assert.equal(f.menu.style.left, '108px');
        f.component.destroy();
        assert.equal(f.menu.parentElement, f.widget);
        assert.equal(f.menu.nextElementSibling?.id, 'sibling');
        f.w.dispatchEvent(new f.w.Event('resize'));
        assert.equal(f.menu.style.left, '');
    } finally { f.component.destroy(); f.dom.window.close(); }
});

test('focused result Escape returns focus and focus leaving results closes the menu', async (): Promise<void> => {
    const f = await fixture();
    try {
        const option = f.menu.querySelector<HTMLElement>('li')!;
        option.focus();
        const key = new f.w.KeyboardEvent('keydown', {key:'Escape', bubbles:true, cancelable:true});
        option.dispatchEvent(key);
        assert.equal(key.defaultPrevented, true);
        assert.equal(f.w.document.activeElement, f.input);
        assert.equal(f.menu.parentElement, f.widget);
        f.input.dispatchEvent(new f.w.FocusEvent('focus'));
        await new Promise<void>((resolve: () => void): void => { f.w.setTimeout(resolve, 0); });
        f.menu.querySelector<HTMLElement>('li')!.focus();
        f.w.document.getElementById('outside')!.focus();
        assert.equal(f.menu.parentElement, f.widget);
        assert.equal(f.menu.classList.contains('hidden'), true);
    } finally { f.component.destroy(); f.dom.window.close(); }
});
