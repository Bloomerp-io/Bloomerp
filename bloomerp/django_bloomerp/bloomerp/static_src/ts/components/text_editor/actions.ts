import { $createParagraphNode, $insertNodes, UNDO_COMMAND, REDO_COMMAND } from "lexical";
import { $createTableNodeWithDimensions } from "@lexical/table";
import type { ContextMenuSubmenu } from "@/utils/contextMenu";
import { t } from "@/utils/i18n";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import type { Action, ActionContext } from "./actionRegistry";
import { createFormattingActions } from "./formattingActions";
import { createTableActions } from "./tableActions";
import { promptLinkInsert } from "./utils/linkPicker";
import { promptHtmlInsert } from "./utils/htmlBehavior";
import { promptMermaidInsert } from "./utils/mermaidBehavior";

export type { Action } from "./actionRegistry";

/** Open the diagram source form after the registry commits its restored selection. */
function handleMermaid(host: BloomerpTextEditor, context: ActionContext): void {
    /** Preserve the slash query until the user confirms a valid diagram. */
    function openDiagram(): void { if (host.editor) promptMermaidInsert(host.editor, host.element); }
    context.afterCommit(openDiagram);
}

/** Open the shared template picker from a registered action surface. */
function handleTemplate(host: BloomerpTextEditor, context: ActionContext): void {
    /** Let template search capture the committed insertion range. */
    function open(): void { host.openTemplatePicker(); }
    context.afterCommit(open);
}
/** Supply template search to slash and toolbar menus. */
function templateSubmenu(host: BloomerpTextEditor): ContextMenuSubmenu { return host.getTemplateSubmenu(); }
/** Open stored-image selection in this editor. */
function handleImage(host: BloomerpTextEditor, context: ActionContext): void {
    /** Let image search capture the committed insertion range. */
    function open(): void { host.openReferencePicker("file"); }
    context.afterCommit(open);
}
/** Supply stored-image search to the shared menu presenter. */
function imageSubmenu(host: BloomerpTextEditor): ContextMenuSubmenu { return host.getReferenceSubmenu("file"); }
/** Open mention selection in this editor. */
function handleMention(host: BloomerpTextEditor, context: ActionContext): void {
    /** Let mention search capture the committed insertion range. */
    function open(): void { host.openReferencePicker("user"); }
    context.afterCommit(open);
}
/** Supply mention search to the shared menu presenter. */
function mentionSubmenu(host: BloomerpTextEditor): ContextMenuSubmenu { return host.getReferenceSubmenu("user"); }
/** Open object-reference selection in this editor. */
function handleObject(host: BloomerpTextEditor, context: ActionContext): void {
    /** Let object search capture the committed insertion range. */
    function open(): void { host.openReferencePicker("object"); }
    context.afterCommit(open);
}
/** Supply object-reference search to the shared menu presenter. */
function objectSubmenu(host: BloomerpTextEditor): ContextMenuSubmenu { return host.getReferenceSubmenu("object"); }

/** Open the link dialog after Lexical commits the restored selection. */
function handleLink(host: BloomerpTextEditor, context: ActionContext): void {
    /** Let the existing link form capture the command's committed selection. */
    function open(): void { if (host.editor) promptLinkInsert(host.editor, host.element); }
    context.afterCommit(open);
}

/** Insert a table with valid cell children and a following editing paragraph. */
function handleTable(_host: BloomerpTextEditor, context: ActionContext): void {
    if (context.range) $insertNodes([$createTableNodeWithDimensions(3, 2, { rows: true, columns: false }), $createParagraphNode()]);
}

/** Open HTML insertion after the registry's selection update commits. */
function handleHtml(host: BloomerpTextEditor, context: ActionContext): void {
    /** Reuse the source editor without adding another insertion implementation. */
    function open(): void { if (host.editor) promptHtmlInsert(host.editor); }
    context.afterCommit(open);
}

/** Provide portable undo even when the browser's native key mapping differs by platform. */
function undo(_host: BloomerpTextEditor, context: ActionContext): void { context.editor.dispatchCommand(UNDO_COMMAND, undefined); }
/** Share Cmd/Ctrl+Shift+Z and Ctrl+Y with Lexical's existing history state. */
function redo(_host: BloomerpTextEditor, context: ActionContext): void { context.editor.dispatchCommand(REDO_COMMAND, undefined); }

/** Retain insertion capabilities alongside the shared formatting definitions. */
export const ACTIONS: Readonly<Record<string, Action>> = Object.freeze({
    ...createFormattingActions(),
    ...createTableActions(),
    mermaid: {
        /** Make diagram insertion searchable by its format and translated label. */
        get label(): string { return t("Mermaid diagram"); },
        icon: "fa-solid fa-diagram-project", group: "insert", surfaces: ["toolbar", "slash"],
        preserveSlashTrigger: true, handler: handleMermaid,
    },
    undo: {
        /** Translate the command name without changing its stable shortcut identifier. */
        get label(): string { return t("Undo"); },
        icon: "fa-solid fa-rotate-left", surfaces: ["shortcut"], shortcuts: ["mod+z"], handler: undo,
    },
    redo: {
        /** Translate the command name without changing its stable shortcut identifier. */
        get label(): string { return t("Redo"); },
        icon: "fa-solid fa-rotate-right", surfaces: ["shortcut"], shortcuts: ["mod+shift+z", "mod+y"], handler: redo,
    },
    link: {
        /** Resolve the link label using the loaded catalog. */
        get label(): string { return t("Link"); },
        icon: "fa-solid fa-link", group: "text", surfaces: ["toolbar", "selection", "slash", "shortcut"],
        shortcuts: ["mod+k"], handler: handleLink,
        /** Require a text range outside literal code before opening a link form. */
        getState(context: ActionContext): import("./actionRegistry").ActionState {
            return { disabled: !context.range || context.blocks.some(isCodeBlock) };
        },
    },
    template: {
        /** Resolve the template label using the loaded catalog. */
        get label(): string { return t("Template"); },
        icon: "fa-solid fa-file-lines", group: "insert", surfaces: ["toolbar", "slash"], handler: handleTemplate, submenu: templateSubmenu,
    },
    image: {
        /** Resolve the image label using the loaded catalog. */
        get label(): string { return t("Image"); },
        icon: "fa-solid fa-image", group: "insert", surfaces: ["toolbar", "slash"], handler: handleImage, submenu: imageSubmenu,
    },
    table: {
        /** Resolve the table label using the loaded catalog. */
        get label(): string { return t("Table"); },
        icon: "fa-solid fa-table", group: "insert", surfaces: ["toolbar", "slash"], handler: handleTable,
    },
    mention: {
        /** Resolve the mention label using the loaded catalog. */
        get label(): string { return t("Mention"); },
        icon: "fa-solid fa-at", group: "insert", surfaces: ["toolbar", "slash"], handler: handleMention, submenu: mentionSubmenu,
    },
    object_reference: {
        /** Resolve the reference label using the loaded catalog. */
        get label(): string { return t("Object"); },
        icon: "fa-solid fa-link", group: "insert", surfaces: ["toolbar", "slash"], handler: handleObject, submenu: objectSubmenu,
    },
    html: {
        /** Resolve the source-HTML label using the loaded catalog. */
        get label(): string { return t("HTML"); },
        icon: "fa-solid fa-code", group: "insert", surfaces: ["toolbar"], handler: handleHtml,
    },
});

/** Identify literal code where semantic link insertion is inappropriate. */
function isCodeBlock(block: import("lexical").ElementNode): boolean { return block.getType() === "text-editor-code-block"; }
