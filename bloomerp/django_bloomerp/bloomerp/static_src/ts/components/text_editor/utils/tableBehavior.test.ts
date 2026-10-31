/** Exercise table structure, contextual controls, persistence, and history using real Lexical nodes. */
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import { JSDOM } from "jsdom";
import type * as Lexical from "lexical";
import type * as Tables from "@lexical/table";
import type * as HTML from "@lexical/html";
import type * as History from "@lexical/history";
import type * as Structure from "./tableStructure";
import type * as Behavior from "./tableBehavior";
import type * as Resize from "../nodes/ResizableTableNode";
import type { TableAction, TableAxis } from "./tableStructure";

const root = fileURLToPath(new URL("../../../..", import.meta.url)).replace(/\/$/, "");
const entry = root + "/table-behavior-fixture.ts";
const result = await build({
    configFile: false, root, logLevel: "silent", resolve: { alias: { "@": root + "/ts" } },
    plugins: [{
        name: "table-behavior-fixture",
        /** Resolve the fixture without creating temporary source files in the repository. */
        resolveId(id: string): string | null { return id === entry ? entry : null; },
        /** Bundle one shared Lexical runtime for production behavior and test assertions. */
        load(id: string): string | null {
            if (id !== entry) return null;
            return `export * from 'lexical'; export * from '@lexical/table'; export * from '@lexical/html'; export * from '@lexical/history';
                export * from '${root}/ts/components/text_editor/utils/tableStructure';
                export * from '${root}/ts/components/text_editor/utils/tableBehavior';
                export * from '${root}/ts/components/text_editor/nodes/ResizableTableNode';`;
        },
    }],
    build: { write: false, minify: false, lib: { entry, formats: ["iife"], name: "TableFixture" } },
});
const bundle = Array.isArray(result) ? result[0] : result;
assert("output" in bundle);
/** Identify the executable fixture among emitted bundle assets. */
function isScript(item: import("rollup").OutputAsset | import("rollup").OutputChunk): item is import("rollup").OutputChunk { return item.type === "chunk"; }
const script = bundle.output.find(isScript)!;
type API = typeof Lexical & typeof Tables & typeof HTML & typeof History & typeof Structure & typeof Behavior & typeof Resize;
type Fixture = { dom: JSDOM; api: API; editor: Lexical.LexicalEditor; host: HTMLElement; tableKey: string; cleanup: () => void };

/** Create a real editor containing a distinct label in every table cell and nonuniform column widths. */
function fixture(): Fixture {
    const dom = new JSDOM('<!doctype html><body><div id="host"><div id="editor" contenteditable="true"></div></div></body>', { runScripts: "dangerously", pretendToBeVisual: true });
    /** Supply the range geometry API omitted by JSDOM's layout-free implementation. */
    function rangeBounds(): DOMRect { return new dom.window.DOMRect(); }
    Object.defineProperty(dom.window.Range.prototype, "getBoundingClientRect", { value: rangeBounds });
    dom.window.eval(script.code);
    const api = (dom.window as unknown as { TableFixture: API }).TableFixture;
    const editor = api.createEditor({ nodes: [api.ResizableTableNode, { replace: api.TableNode, with: api.$replaceTableNode, withKlass: api.ResizableTableNode }, api.TableCellNode, api.TableRowNode],
        /** Surface structural errors instead of allowing silent editor recovery. */
        onError(error: Error): never { throw error; },
    });
    const host = dom.window.document.getElementById("host")!;
    editor.setRootElement(dom.window.document.getElementById("editor"));
    const cleanup = api.registerTableBehavior(editor, host);
    let tableKey = "";
    /** Seed native cells and capture the stable table identity for later commands. */
    function seed(): void {
        const table = api.$createTableNodeWithDimensions(3, 3, { rows: true, columns: false });
        table.setColWidths([20, 30, 50]);
        tableKey = table.getKey();
        for (const [rowIndex, row] of table.getChildren<Tables.TableRowNode>().entries()) {
            for (const [columnIndex, cell] of row.getChildren<Tables.TableCellNode>().entries()) {
                cell.getFirstChild<Lexical.ElementNode>()!.append(api.$createTextNode(`${rowIndex}${columnIndex}`));
            }
        }
        api.$getRoot().append(table, api.$createParagraphNode().append(api.$createTextNode("After table")));
        table.getFirstDescendant()!.selectStart();
    }
    editor.update(seed, { discrete: true });
    return { dom, api, editor, host, tableKey, cleanup };
}

/** Run a structural operation as the same discrete history transaction used by the controls. */
function edit(f: Fixture, axis: TableAxis, index: number, action: TableAction, destination?: number): boolean {
    let changed = false;
    /** Resolve a live table immediately before applying its structural operation. */
    function mutate(): void {
        const table = f.api.$getNodeByKey(f.tableKey);
        assert(f.api.$isTableNode(table));
        changed = f.api.$editTableStructure(table, axis, index, action, destination);
    }
    f.editor.update(mutate, { discrete: true, tag: "history-push" });
    return changed;
}

/** Export the production HTML saved by forms and rendered by PDF generation. */
function html(f: Fixture): string {
    /** Serialize the current immutable editor state. */
    function serialize(): string { return f.api.$generateHtmlFromNodes(f.editor); }
    return f.editor.getEditorState().read(serialize);
}

/** Read physical cell labels from exported HTML, independent of editor-only wrappers. */
function cells(f: Fixture): string[][] {
    const document = new f.dom.window.DOMParser().parseFromString(html(f), "text/html");
    /** Read one row's cell labels in their saved order. */
    function labels(row: HTMLTableRowElement): string[] { return Array.from(row.cells, text); }
    /** Read the visible cell text without relying on its inline formatting structure. */
    function text(cell: HTMLTableCellElement): string { return cell.textContent ?? ""; }
    return Array.from(document.querySelectorAll("tr"), labels);
}

/** Read saved column weights from the current table state. */
function widths(f: Fixture): readonly number[] | undefined {
    /** Resolve the latest table snapshot after a structural update. */
    function read(): readonly number[] | undefined {
        const saved = f.api.$getNodeByKey<Tables.TableNode>(f.tableKey)?.getColWidths();
        return saved ? Array.from(saved) : undefined;
    }
    return f.editor.getEditorState().read(read);
}

/** Release native observers and the body-mounted controls for every fixture. */
function close(f: Fixture): void {
    f.cleanup();
    assert.equal(f.dom.window.document.querySelector(".bloomerp-table-controls"), null);
    f.editor.setRootElement(null);
    f.dom.window.close();
}

/** Flush animation frames and editor mutations before inspecting controls or history. */
async function settle(): Promise<void> {
    /** Resolve after one rendered frame has had time to run in JSDOM. */
    function delay(resolve: () => void): void { setTimeout(resolve, 30); }
    await new Promise<void>(delay);
}

test("insert and delete a middle row without changing its neighbors", function rowStructure(): void {
    const f = fixture();
    try {
        edit(f, "row", 1, "insert-before");
        assert.deepEqual(cells(f), [["00", "01", "02"], ["", "", ""], ["10", "11", "12"], ["20", "21", "22"]]);
        edit(f, "row", 2, "delete");
        assert.deepEqual(cells(f), [["00", "01", "02"], ["", "", ""], ["20", "21", "22"]]);
        assert.deepEqual(widths(f), [20, 30, 50]);
    } finally { close(f); }
});

test("insert and delete a particular column while preserving headers and proportions", function columnStructure(): void {
    const f = fixture();
    try {
        edit(f, "column", 1, "insert-after");
        assert.deepEqual(cells(f)[1], ["10", "11", "", "12"]);
        assert.deepEqual(widths(f), [20, 30, 30, 50]);
        const document = new f.dom.window.DOMParser().parseFromString(html(f), "text/html");
        assert.equal(document.querySelectorAll("tr:first-child th").length, 4);
        assert.equal(document.querySelectorAll("tr:nth-child(2) td").length, 4);
        edit(f, "column", 1, "delete");
        assert.deepEqual(cells(f)[1], ["10", "", "12"]);
        assert.deepEqual(widths(f), [20, 30, 50]);
    } finally { close(f); }
});

test("reorder rows and columns in both directions while widths travel with columns", function reorder(): void {
    const f = fixture();
    try {
        edit(f, "row", 0, "move", 2);
        assert.deepEqual(cells(f)[2], ["00", "01", "02"]);
        edit(f, "row", 2, "move-before");
        assert.deepEqual(cells(f)[1], ["00", "01", "02"]);
        edit(f, "column", 0, "move", 2);
        assert.deepEqual(cells(f)[0], ["11", "12", "10"]);
        assert.deepEqual(widths(f), [30, 50, 20]);
        edit(f, "column", 2, "move", 0);
        assert.deepEqual(cells(f)[0], ["10", "11", "12"]);
        assert.deepEqual(widths(f), [20, 30, 50]);
        assert.equal(edit(f, "column", 0, "move-before"), false);
        assert.equal(edit(f, "row", 2, "move-after"), false);
    } finally { close(f); }
});

test("reordered content and column proportions survive HTML reload without controls", function persistence(): void {
    const f = fixture();
    try {
        edit(f, "column", 0, "move-after");
        edit(f, "row", 2, "move-before");
        const saved = html(f);
        const expectedCells = cells(f);
        assert.doesNotMatch(saved, /button|table-control|Row options|Add row|table-menu/);
        /** Reload the same markup supplied to document templates and printable PDFs. */
        function reload(): void {
            f.api.$getRoot().clear().append(...f.api.$generateNodesFromDOM(f.editor, new f.dom.window.DOMParser().parseFromString(saved, "text/html")));
        }
        f.editor.update(reload, { discrete: true });
        const reloaded = new f.dom.window.DOMParser().parseFromString(html(f), "text/html");
        /** Read each column's printable proportion independently of incidental style ordering. */
        function columnWidth(column: HTMLTableColElement): string { return column.style.width; }
        assert.deepEqual(Array.from(reloaded.querySelectorAll("col"), columnWidth), ["30%", "20%", "50%"]);
        assert.deepEqual(cells(f), expectedCells);
        assert.equal(reloaded.querySelectorAll("th").length, 3);
    } finally { close(f); }
});

test("a complete reorder is undone and redone in one history step", async function history(): Promise<void> {
    const f = fixture();
    const cleanup = f.api.registerHistory(f.editor, f.api.createEmptyHistoryState(), 300);
    try {
        /** Seed the history baseline without changing the document's contents. */
        function baseline(): void { f.api.$getNodeByKey<Tables.TableNode>(f.tableKey)!.getFirstDescendant()!.selectEnd(); }
        f.editor.update(baseline, { discrete: true });
        const before = html(f);
        edit(f, "column", 0, "move", 2);
        const after = html(f);
        f.editor.dispatchCommand(f.api.UNDO_COMMAND, undefined);
        await settle();
        assert.equal(html(f), before);
        f.editor.dispatchCommand(f.api.REDO_COMMAND, undefined);
        await settle();
        assert.equal(html(f), after);
    } finally { cleanup(); close(f); }
});

test("deleting the last row or column leaves an editable paragraph at the table position", function lastAxis(): void {
    for (const axis of ["row", "column"] as const) {
        const f = fixture();
        try {
            edit(f, axis, 1, "delete");
            edit(f, axis, 1, "delete");
            edit(f, axis, 0, "delete");
            assert.doesNotMatch(html(f), /<table/);
            assert.match(html(f), /After table/);
            /** Validate that selection stays in an attached editable paragraph. */
            function selection(): void {
                const selected = f.api.$getSelection();
                assert(f.api.$isRangeSelection(selected));
                assert.equal(selected.anchor.getNode().isAttached(), true);
            }
            f.editor.getEditorState().read(selection);
        } finally { close(f); }
    }
});

test("merged cells reject structural edits without losing content", function mergedCells(): void {
    const f = fixture();
    try {
        /** Represent an imported merged cell before attempting a row or column operation. */
        function merge(): void {
            f.api.$getNodeByKey<Tables.TableNode>(f.tableKey)!.getFirstChild<Tables.TableRowNode>()!.getFirstChild<Tables.TableCellNode>()!.setColSpan(2);
        }
        f.editor.update(merge, { discrete: true });
        const before = html(f);
        assert.equal(edit(f, "column", 0, "move-after"), false);
        assert.equal(edit(f, "row", 1, "delete"), false);
        assert.equal(html(f), before);
        assert.equal(edit(f, "row", 0, "delete-table"), true);
    } finally { close(f); }
});

test("edge menus target the hovered row, support keyboard dismissal, and clean up on teardown", async function controls(): Promise<void> {
    const f = fixture();
    try {
        const table = f.editor.getElementByKey(f.tableKey) as HTMLTableElement;
        /** Provide physical table geometry because JSDOM intentionally does not perform layout. */
        function tableBounds(): DOMRect { return new f.dom.window.DOMRect(100, 100, 300, table.rows.length * 30); }
        table.getBoundingClientRect = tableBounds;
        for (const [index, row] of Array.from(table.rows).entries()) {
            /** Place each physical row in its own hover band. */
            function rowBounds(): DOMRect { return new f.dom.window.DOMRect(100, 100 + index * 30, 300, 30); }
            row.getBoundingClientRect = rowBounds;
            for (const [column, cell] of Array.from(row.cells).entries()) {
                /** Place each cell in the expected column for hover-based handle selection. */
                function cellBounds(): DOMRect { return new f.dom.window.DOMRect(100 + column * 100, 100 + index * 30, 100, 30); }
                cell.getBoundingClientRect = cellBounds;
            }
        }
        table.dispatchEvent(new f.dom.window.MouseEvent("pointermove", { bubbles: true, clientX: 101, clientY: 145 }));
        await settle();
        const rowHandle = f.dom.window.document.querySelector<HTMLButtonElement>('[data-table-control="row"]')!;
        assert.equal(rowHandle.dataset.revealed, "true");
        rowHandle.click();
        const menu = f.dom.window.document.querySelector<HTMLElement>('[role="menu"]')!;
        assert.equal(menu.hidden, false);
        menu.querySelector<HTMLButtonElement>('[data-table-action="delete"]')!.click();
        assert.deepEqual(cells(f), [["00", "01", "02"], ["20", "21", "22"]]);
        assert.equal(menu.hidden, true);
        rowHandle.click();
        f.dom.window.document.activeElement!.dispatchEvent(new f.dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        assert.equal(menu.hidden, true);
        assert.equal(f.dom.window.document.activeElement, rowHandle);
        table.dispatchEvent(new f.dom.window.MouseEvent("pointermove", { bubbles: true, clientX: 250, clientY: 165 }));
        await settle();
        const addRow = f.dom.window.document.querySelector<HTMLButtonElement>('[data-table-control="add-row"]')!;
        assert.equal(addRow.dataset.revealed, "true");
        addRow.click();
        await settle();
        assert.equal(cells(f).length, 3);
        assert.equal(addRow.dataset.revealed, "false");
        f.editor.setEditable(false);
        await settle();
        assert.equal(f.dom.window.document.querySelector<HTMLElement>(".bloomerp-table-controls")!.hidden, true);
        rowHandle.click();
        assert.equal(menu.hidden, true);
    } finally { close(f); }
});
