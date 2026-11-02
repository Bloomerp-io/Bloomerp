import {
    $addUpdateTag, $getNodeByKey, $getRoot, $getSelection, $isElementNode, $isRangeSelection, $isTextNode,
    $setSelection, COMMAND_PRIORITY_HIGH, KEY_DOWN_COMMAND, createCommand,
    type BaseSelection, type ElementNode, type LexicalEditor, type RangeSelection, type TextNode,
} from "lexical";
import { $isTableNode, $isTableCellNode, $isTableSelection } from "@lexical/table";
import type { ContextMenuSubmenu } from "@/utils/contextMenu";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import { getCurrentWordFromSelection, removeTextFromCurrentSelection } from "./utils/wordSelector";

export type ActionSurface = "toolbar" | "selection" | "slash" | "shortcut";
export type ActionGroup = "text" | "block" | "list" | "alignment" | "table" | "insert" | "extension";
export type ActionPayload = { value?: string };
export type ActionState = { active?: boolean; mixed?: boolean; disabled?: boolean };
export type ActionOption = { label: string; value: string; input?: "color" };
export type ActionContext = {
    editor: LexicalEditor;
    source: ActionSurface;
    selection: BaseSelection | null;
    range: RangeSelection | null;
    blocks: ElementNode[];
    textNodes: TextNode[];
    afterCommit: (effect: () => void) => void;
};
export type Action = {
    label: string;
    icon: string;
    group?: ActionGroup;
    surfaces?: readonly ActionSurface[];
    /** Let confirmation dialogs consume their slash query only when the user applies content. */
    preserveSlashTrigger?: boolean;
    shortcuts?: readonly string[];
    options?: readonly ActionOption[];
    submenu?: (textEditor: BloomerpTextEditor) => ContextMenuSubmenu;
    handler: (textEditor: BloomerpTextEditor, context: ActionContext, payload: ActionPayload) => void;
    getState?: (context: ActionContext, payload: ActionPayload) => ActionState;
    isAvailable?: (context: ActionContext) => boolean;
};
export type RegisteredAction = { id: string; action: Action; state: ActionState };
type Invocation = { id: string; source: ActionSurface; selection?: BaseSelection | null; payload: ActionPayload };

const EXECUTE_ACTION = createCommand<Invocation>("BLOOMERP_EXECUTE_EDITOR_ACTION");
const BLOCK_TYPES = new Set(["paragraph", "heading", "quote", "listitem", "text-editor-code-block"]);

/** Ignore zero-character endpoints when reporting mixed formatting or touched blocks. */
function $getSelectedNodes(selection: BaseSelection | null): import("lexical").LexicalNode[] {
    const nodes = [...(selection?.getNodes() ?? [])];
    if (!$isRangeSelection(selection) || selection.isCollapsed()) return nodes;
    const start = selection.isBackward() ? selection.focus : selection.anchor;
    const end = selection.isBackward() ? selection.anchor : selection.focus;
    /** Exclude a text leaf when the range only touches its boundary. */
    function containsSelectedContent(node: import("lexical").LexicalNode): boolean {
        if ($isTextNode(node) && node.getKey() === start.key && start.offset === node.getTextContentSize()) return false;
        if (node.getKey() === end.key && end.offset === 0) return false;
        return true;
    }
    return nodes.filter(containsSelectedContent);
}

/** Find editable text blocks without treating list or table containers as paragraphs. */
export function $getActionBlocks(selection: BaseSelection | null): ElementNode[] {
    const blocks = new Map<string, ElementNode>();
    const nodes = $getSelectedNodes(selection);
    if ($isRangeSelection(selection) && selection.isCollapsed()) nodes.push(selection.anchor.getNode());
    for (let node of nodes) {
        while (node && !BLOCK_TYPES.has(node.getType())) node = node.getParent();
        if ($isElementNode(node)) blocks.set(node.getKey(), node);
    }
    return [...blocks.values()];
}

/** Describe the current Lexical selection inside an editor read or update. */
export function $getActionContext(editor: LexicalEditor, source: ActionSurface): ActionContext {
    const selection = $getSelection();
    /** Open dialogs only once the restored range and slash-trigger removal are committed. */
    function afterCommit(effect: () => void): void {
        /** Attach a completion callback to the current Lexical transaction. */
        function finish(): void { /* The command already contains the required state changes. */ }
        editor.update(finish, { onUpdate: effect });
    }
    return {
        editor, source, selection, afterCommit,
        range: $isRangeSelection(selection) ? selection : null,
        blocks: $getActionBlocks(selection),
        textNodes: $getSelectedNodes(selection).filter($isTextNode).filter(isOrdinaryText),
    };
}

/** Exclude atomic mentions and other specialized text entities from inline formatting. */
function isOrdinaryText(node: TextNode): boolean { return node.isSimpleText(); }

/** Reject a stale range before restoring it into a changed document. */
function $selectionIsAttached(selection: BaseSelection): boolean {
    if ($isRangeSelection(selection)) {
        return validPoint(selection.anchor) && validPoint(selection.focus);
    }
    if ($isTableSelection(selection)) {
        const table = $getNodeByKey(selection.tableKey);
        const anchor = $getNodeByKey(selection.anchor.key);
        const focus = $getNodeByKey(selection.focus.key);
        return $isTableNode(table) && table.isAttached() && $isTableCellNode(anchor) && $isTableCellNode(focus)
            && anchor.getParent()?.getParent()?.is(table) === true && focus.getParent()?.getParent()?.is(table) === true;
    }
    return selection.getNodes().every(isAttached);
}

/** Validate an offset as well as attachment before restoring a menu's saved range. */
function validPoint(point: import("lexical").PointType): boolean {
    const node = $getNodeByKey(point.key);
    if (!node?.isAttached()) return false;
    const size = point.type === "text" && $isTextNode(node) ? node.getTextContentSize()
        : point.type === "element" && $isElementNode(node) ? node.getChildrenSize() : -1;
    return point.offset >= 0 && point.offset <= size;
}

/** Check whether a selected node still belongs to its document. */
function isAttached(node: import("lexical").LexicalNode): boolean { return node.isAttached(); }

/** Match portable shortcut descriptions without swallowing AltGr or composition input. */
function matchesShortcut(event: KeyboardEvent, shortcut: string): boolean {
    if (event.isComposing || event.altKey) return false;
    const parts = shortcut.toLowerCase().split("+");
    const key = parts.pop();
    return (event.key.toLowerCase() === key || (/^Digit/.test(event.code) && event.code.slice(5) === key))
        && (event.metaKey || event.ctrlKey) === parts.includes("mod")
        && event.shiftKey === parts.includes("shift");
}

/** Own one editor's action definitions and shared, undoable command execution. */
export class EditorActionRegistry {
    private readonly definitions = new Map<string, Action>();
    private readonly listeners = new Set<() => void>();
    private unregister: (() => void) | null = null;

    /** Copy built-ins so later extensions cannot leak into another editor. */
    public constructor(private readonly host: BloomerpTextEditor, builtins: Readonly<Record<string, Action>>) {
        for (const [id, action] of Object.entries(builtins)) this.definitions.set(id, action);
    }

    /** Connect registry execution and shortcuts to this editor's Lexical lifecycle. */
    public initialize(): void {
        const editor = this.host.editor;
        if (!editor || this.unregister) return;
        const removeAction = editor.registerCommand(EXECUTE_ACTION, this.handleInvocation, COMMAND_PRIORITY_HIGH);
        const removeKeys = editor.registerCommand(KEY_DOWN_COMMAND, this.handleShortcut, COMMAND_PRIORITY_HIGH);
        this.unregister = (): void => { removeAction(); removeKeys(); };
    }

    /** Register or replace one scoped extension and refresh its presentation surfaces. */
    public register(id: string, action: Action): void {
        this.definitions.set(id, action);
        for (const listener of this.listeners) listener();
    }

    /** Subscribe to capability changes without rebuilding editor command listeners. */
    public subscribe(listener: () => void): () => void {
        this.listeners.add(listener);
        /** Unsubscribe only this surface's registry listener. */
        return (): void => { this.listeners.delete(listener); };
    }

    /** Resolve an action by its stable ID within this editor. */
    public get(id: string): Action | undefined { return this.definitions.get(id); }

    /** Read available actions and their active, mixed, and disabled states. */
    public list(source: ActionSurface, selection?: BaseSelection | null): RegisteredAction[] {
        const editor = this.host.editor;
        if (!editor) return [];
        const result: RegisteredAction[] = [];
        /** Evaluate capability predicates against immutable committed editor state. */
        const readActions = (): void => {
            const context = $getActionContext(editor, source);
            if (selection && $selectionIsAttached(selection)) {
                context.selection = selection;
                context.range = $isRangeSelection(selection) ? selection : null;
                context.blocks = $getActionBlocks(selection);
                context.textNodes = $getSelectedNodes(selection).filter($isTextNode).filter(isOrdinaryText);
            }
            for (const [id, action] of this.definitions) {
                if (!(action.surfaces ?? ["toolbar"]).includes(source)) continue;
                if (action.isAvailable && !action.isAvailable(context)) continue;
                const state = action.getState?.(context, {}) ?? {};
                result.push({ id, action, state: { ...state, disabled: !this.isEditable() || state.disabled } });
            }
        };
        editor.getEditorState().read(readActions);
        return result;
    }

    /** Clone the editor selection before a toolbar, submenu, or dialog takes focus. */
    public captureSelection(): BaseSelection | null {
        let selection: BaseSelection | null = null;
        /** Keep the immutable selection independent of future editor updates. */
        const capture = (): void => { selection = $getSelection()?.clone() ?? null; };
        this.host.editor?.getEditorState().read(capture);
        return selection;
    }

    /** Restore a captured selection before an existing picker captures its own state. */
    public restoreSelection(selection: BaseSelection | null): void {
        /** Restore attached ranges only, without creating a content history entry. */
        const restore = (): void => {
            if (selection && $selectionIsAttached(selection)) $setSelection(selection.clone());
        };
        this.host.editor?.update(restore, { discrete: true });
    }

    /** Invoke the same Lexical command from a toolbar, slash menu, or shortcut. */
    public execute(id: string, source: ActionSurface, selection?: BaseSelection | null, payload: ActionPayload = {}): boolean {
        return this.host.editor?.dispatchCommand(EXECUTE_ACTION, { id, source, selection, payload }) ?? false;
    }

    /** Release command and surface subscriptions when the owning widget is removed. */
    public destroy(): void {
        this.unregister?.();
        this.unregister = null;
        this.listeners.clear();
    }

    /** Respect both Lexical read-only state and the widget's disabled contract. */
    private isEditable(): boolean {
        return Boolean(this.host.editor?.isEditable() && this.host.element.dataset.disabled !== "true");
    }

    /** Restore the target and execute a capability inside Lexical's command transaction. */
    private handleInvocation = (invocation: Invocation): boolean => {
        const editor = this.host.editor;
        const action = this.get(invocation.id);
        if (!editor || !action || !this.isEditable()) return false;
        if (action.options && !action.options.some(matchesValue)) return false;
        /** Accept declared presets or a validated value from this capability's custom input. */
        function matchesValue(option: ActionOption): boolean {
            return option.input === "color" ? /^#[0-9a-f]{6}$/i.test(invocation.payload.value ?? "")
                : option.value === invocation.payload.value;
        }
        if (invocation.selection) {
            if (!$selectionIsAttached(invocation.selection)) return false;
            $setSelection(invocation.selection.clone());
        } else {
            const selection = $getSelection();
            if (selection) $setSelection(selection.clone());
            else $getRoot().selectEnd();
        }
        let context = $getActionContext(editor, invocation.source);
        if (action.isAvailable && !action.isAvailable(context)) return false;
        if (action.getState?.(context, invocation.payload).disabled) return false;
        if (invocation.source === "slash" && !action.preserveSlashTrigger) {
            const trigger = getCurrentWordFromSelection();
            if (trigger.startsWith("/")) removeTextFromCurrentSelection(trigger);
            context = $getActionContext(editor, invocation.source);
        }
        $addUpdateTag("history-push");
        action.handler(this.host, context, invocation.payload);
        return true;
    };

    /** Route registered shortcuts through the same capability checks as visible controls. */
    private handleShortcut = (event: KeyboardEvent): boolean => {
        if (!this.isEditable()) return false;
        for (const [id, action] of this.definitions) {
            if (!(action.surfaces ?? []).includes("shortcut")) continue;
            if (!action.shortcuts?.some(matchesShortcut.bind(null, event))) continue;
            if (this.execute(id, "shortcut")) {
                event.preventDefault();
                event.stopPropagation();
                return true;
            }
        }
        return false;
    };
}
