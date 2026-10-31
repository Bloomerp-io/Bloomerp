/** Header regressions exercise the production builder with synthetic API/image data. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import type { OutputAsset, OutputChunk } from 'rollup';
import { JSDOM, type DOMWindow } from 'jsdom';
import type { DocumentTemplateHeader } from '../sdk/sdk';

const root = fileURLToPath(new URL('../..', import.meta.url)).replace(/\/$/, '');
const mocks: Record<string, string> = {
    lexical: 'export const $createParagraphNode=()=>{}, $createTextNode=()=>{}, $getSelection=()=>{}, $isNodeSelection=()=>{}, $isRangeSelection=()=>{}, $isTextNode=()=>{}, LexicalNode=class{}, ParagraphNode=class{};',
    './text_editor/BloomerpTextEditor': 'export class BloomerpTextEditor {}',
    './widgets/ForeignFieldWidget': 'export default class ForeignFieldWidget {}',
    '@/sdk/getSdk': 'export default function getSdk(){return window.headerSdk}',
    './widgets/CodeEditorWidget': 'export default class CodeEditorWidget {}',
    '@/utils/modals': 'export default function getGeneralModal(){}; export function getModal(){}',
    'ace-builds': 'export function edit(){}',
    './text_editor/utils/wordSelector': 'export function getCurrentWordFromSelection(){}; export function removeTextFromCurrentSelection(){}',
    'htmx.org': 'export default {}',
    '@/utils/messages': 'export default function showMessage(){}',
    './UiMessage': 'export const MessageType={}',
};
const result = await build({
    configFile: false, root, logLevel: 'silent',
    plugins: [{
        name: 'synthetic-header-dependencies',
        enforce: 'pre',
        /** Substitute unrelated editor services while retaining the real builder and base. */
        resolveId(id: string): string | null { return id in mocks ? `\0header-mock:${id}` : null; },
        /** Supply isolated dependencies without network or document data. */
        load(id: string): string | null { return id.startsWith('\0header-mock:') ? mocks[id.slice(13)] : null; },
    }],
    build: { write: false, minify: false, lib: { entry: `${root}/ts/components/DocumentTemplateBuilder.ts`, formats: ['iife'], name: 'HeaderFixture' } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert('output' in bundle);
const script = bundle.output.find((item: OutputAsset | OutputChunk): boolean => item.type === 'chunk');
assert(script?.type === 'chunk');
const scriptCode = script.code;

interface Builder {
    pageContainer: HTMLDivElement;
    pageHeaderSection: HTMLDivElement;
    pageContentSection: HTMLDivElement;
    applyPageHeader(id: string | null): void;
    applyPageSize(size: 'A4' | 'A3' | 'Letter'): void;
    applyPageOrientation(orientation: 'portrait' | 'landscape'): void;
    applyPageMargin(margin: number | string): void;
    destroy(): void;
}
interface FixtureWindow extends DOMWindow {
    HeaderFixture: { DocumentTemplateBuilder: new (element: HTMLElement) => Builder };
    headerSdk: { documentTemplateHeaders: { retrieve(id: string): Promise<DocumentTemplateHeader> } };
}
interface Fixture {
    dom: JSDOM;
    w: FixtureWindow;
    builder: Builder;
    images: HTMLImageElement[];
    resolve: Map<string, (header: DocumentTemplateHeader) => void>;
    reject: Map<string, (error: Error) => void>;
}

/** Build an isolated paper and defer API responses and image loads independently. */
function fixture(): Fixture {
    const dom = new JSDOM('<div id="paper"><div id="header"></div><div id="body"></div></div>', { runScripts: 'outside-only' });
    const w = dom.window as FixtureWindow;
    const resolve = new Map<string, (header: DocumentTemplateHeader) => void>();
    const reject = new Map<string, (error: Error) => void>();
    w.headerSdk = { documentTemplateHeaders: { retrieve(id: string): Promise<DocumentTemplateHeader> {
        return new Promise((accept, fail): void => { resolve.set(id, accept); reject.set(id, fail); });
    } } };
    w.eval(scriptCode);
    const builder = new w.HeaderFixture.DocumentTemplateBuilder(w.document.body);
    builder.pageContainer = w.document.querySelector('#paper')!;
    builder.pageHeaderSection = w.document.querySelector('#header')!;
    builder.pageContentSection = w.document.querySelector('#body')!;
    const images: HTMLImageElement[] = [];
    const createElement = w.document.createElement.bind(w.document);
    /** Capture detached images so tests can deliver late load and error events. */
    w.document.createElement = ((tag: string): HTMLElement => {
        const element = createElement(tag);
        if (tag === 'img') { images.push(element as HTMLImageElement); }
        return element;
    }) as typeof w.document.createElement;
    builder.applyPageMargin(1);
    builder.applyPageSize('A4');
    return { dom, w, builder, images, resolve, reject };
}

/** Resolve a synthetic header record without fetching any real assets. */
async function respond(f: Fixture, id: string, overrides: Partial<DocumentTemplateHeader> = {}): Promise<void> {
    f.resolve.get(id)!({ id, name: 'Synthetic logo', header: 'https://example.invalid/logo.svg', height: 1,
        margin_top: 0.5, margin_bottom: 0, margin_left: 1, margin_right: 1,
        created_by: null, updated_by: null, datetime_created: '', datetime_updated: '', object_labels: [], ...overrides });
    await Promise.resolve();
}

/** Supply intrinsic image dimensions and dispatch a browser-style load event. */
function loaded(f: Fixture, image: HTMLImageElement, width: number, height: number): void {
    Object.defineProperties(image, { naturalWidth: { value: width }, naturalHeight: { value: height } });
    image.dispatchEvent(new f.w.Event('load'));
}

/** Assert numeric CSS dimensions without depending on serialization precision. */
function close(actual: string, expected: number): void {
    assert.ok(Math.abs(parseFloat(actual) - expected) < 0.000001, `${actual} != ${expected}in`);
}

test('fits wide and tall logos across every page size and orientation and preserves margins', async function (): Promise<void> {
    const f = fixture();
    for (const ratio of [4, 0.25, 16]) {
        f.builder.applyPageHeader(String(ratio));
        await respond(f, String(ratio));
        const image = f.images.at(-1)!;
        loaded(f, image, ratio * 100, 100);
        for (const [size, portraitWidth, portraitHeight] of [['A4', 210 / 25.4, 297 / 25.4], ['A3', 297 / 25.4, 420 / 25.4], ['Letter', 8.5, 11]] as const) {
            f.builder.applyPageSize(size);
            for (const orientation of ['portrait', 'landscape'] as const) {
                f.builder.applyPageOrientation(orientation);
                const pageWidth = orientation === 'portrait' ? portraitWidth : portraitHeight;
                const height = Math.min(1, (pageWidth - 2) / ratio);
                close(image.style.height, height);
                close(image.style.width, height * ratio);
                close(f.builder.pageContainer.style.width, pageWidth);
                for (const margin of [0.25, 1, 3]) {
                    f.builder.applyPageMargin(String(margin));
                    close(f.builder.pageContentSection.style.paddingTop, Math.max(0, margin - 0.5 - height));
                    for (const side of ['paddingLeft', 'paddingRight', 'paddingBottom'] as const) {
                        close(f.builder.pageContentSection.style[side], margin);
                    }
                }
            }
        }
    }
    f.dom.window.close();
});

test('uses current settings after delayed load and honors nonzero bottom gap and zero available width', async function (): Promise<void> {
    const f = fixture();
    f.builder.applyPageHeader('wide');
    await respond(f, 'wide', { margin_bottom: 0.75, height: 2 });
    f.builder.applyPageSize('Letter');
    f.builder.applyPageOrientation('landscape');
    f.builder.applyPageMargin(2);
    loaded(f, f.images[0], 1600, 100);
    close(f.images[0].style.width, 9);
    close(f.images[0].style.height, 9 / 16);
    close(f.builder.pageContentSection.style.paddingTop, 2 - 0.5 - 0.75 - 9 / 16);
    f.builder.applyPageHeader('zero');
    await respond(f, 'zero', { margin_left: 6, margin_right: 6 });
    loaded(f, f.images[1], 400, 100);
    close(f.images[1].style.width, 0);
    close(f.images[1].style.height, 0);
    f.dom.window.close();
});

test('clear and reselect reject stale API responses and stale image loads', async function (): Promise<void> {
    const f = fixture();
    f.builder.applyPageHeader('old-response');
    f.builder.applyPageHeader('old-image');
    await respond(f, 'old-image');
    f.builder.applyPageHeader(null);
    await respond(f, 'old-response');
    loaded(f, f.images[0], 400, 100);
    assert.equal(f.images.length, 1);
    assert.equal(f.builder.pageHeaderSection.childElementCount, 0);
    close(f.builder.pageContentSection.style.paddingTop, 1);
    f.builder.applyPageHeader('selected');
    await respond(f, 'selected');
    loaded(f, f.images[1], 100, 400);
    close(f.images[1].style.height, 1);
    assert.equal(f.builder.pageHeaderSection.firstChild, f.images[1]);
    f.builder.applyPageHeader('destroyed');
    f.builder.destroy();
    await respond(f, 'destroyed');
    assert.equal(f.images.length, 2);
    f.dom.window.close();
});

test('failed retrieval and broken images retain ordinary page spacing', async function (): Promise<void> {
    const f = fixture();
    f.w.console.error = (): void => {};
    f.builder.applyPageHeader('failed');
    f.reject.get('failed')!(new Error('Synthetic failure'));
    await Promise.resolve();
    await Promise.resolve();
    f.builder.applyPageHeader('broken');
    await respond(f, 'broken');
    f.images[0].dispatchEvent(new f.w.Event('error'));
    assert.equal(f.builder.pageHeaderSection.childElementCount, 0);
    close(f.builder.pageContentSection.style.paddingTop, 1);
    f.dom.window.close();
});
