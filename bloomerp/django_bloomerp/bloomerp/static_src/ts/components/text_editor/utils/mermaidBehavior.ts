import {
    $createNodeSelection,
    $createParagraphNode,
    $getNodeByKey,
    $getRoot,
    $getSelection,
    $insertNodes,
    $isNodeSelection,
    $isRangeSelection,
    $setSelection,
    type LexicalEditor,
    type NodeKey,
    type RangeSelection,
} from "lexical";
import { createModalInstance } from "../../../utils/modals";
import { t as _ } from "../../../utils/i18n";
import { renderMermaid } from "../../../utils/mermaid";
import { $createMermaidNode, $isMermaidNode } from "../nodes/MermaidNode";
import { getCurrentWordFromSelection, removeTextFromCurrentSelection } from "./wordSelector";

type MermaidBehaviorState = {
    closeDialog: (() => void) | null;
};

const behaviorStates = new WeakMap<LexicalEditor, MermaidBehaviorState>();
const DEFAULT_SOURCE = "flowchart TD\n    A[Start] --> B[End]";

/** Require a connected, editable owner before changing diagram content. */
function canEditDiagram(editor: LexicalEditor, host: HTMLElement): boolean {
    return editor.isEditable() && host.dataset.disabled !== "true" && host.isConnected;
}

/** Select one diagram using Lexical state so copy, deletion, and undo remain native. */
function selectDiagram(nodeKey: NodeKey): void {
    const node = $getNodeByKey(nodeKey);
    if (!$isMermaidNode(node)) return;
    const selection = $createNodeSelection();
    selection.add(nodeKey);
    $setSelection(selection);
}

/** Bind diagram selection, keyboard editing, deletion, and lifecycle cleanup. */
export function registerMermaidBehavior(editor: LexicalEditor, host: HTMLElement): () => void {
    const root = editor.getRootElement();
    const lifecycle = new AbortController();
    const state: MermaidBehaviorState = { closeDialog: null };
    behaviorStates.set(editor, state);

    /** Select this editor's clicked diagram and open its source on double-click. */
    function handleClick(event: MouseEvent): void {
        if (!(event.target instanceof Element) || !canEditDiagram(editor, host)) return;
        const diagram = event.target.closest<HTMLElement>("[data-mermaid-node-key]");
        const nodeKey = diagram?.dataset.mermaidNodeKey;
        if (!nodeKey || !root?.contains(diagram)) return;
        event.preventDefault();
        event.stopPropagation();
        root.focus();
        /** Commit a selection without changing the diagram's source. */
        function selectClickedDiagram(): void { selectDiagram(nodeKey); }
        editor.update(selectClickedDiagram);
        if (event.detail === 2) promptMermaidEdit(editor, host, nodeKey);
    }

    /** Edit or remove a focused diagram without affecting another editor's content. */
    function handleKeyDown(event: KeyboardEvent): void {
        if (!canEditDiagram(editor, host)) return;
        if (!["Enter", " ", "Backspace", "Delete"].includes(event.key)) return;
        let nodeKey: NodeKey | null = null;
        /** Prefer the keyboard-focused diagram over a stale Lexical node selection. */
        function readSelectedDiagram(): void {
            if (event.target instanceof HTMLElement) {
                const diagram = event.target.closest<HTMLElement>("[data-mermaid-node-key]");
                const key = diagram?.dataset.mermaidNodeKey;
                if (key && root?.contains(diagram) && $isMermaidNode($getNodeByKey(key))) {
                    nodeKey = key;
                    return;
                }
            }
            const selection = $getSelection();
            if ($isNodeSelection(selection)) {
                const nodes = selection.getNodes();
                if (nodes.length === 1 && $isMermaidNode(nodes[0])) nodeKey = nodes[0].getKey();
            }
        }
        editor.getEditorState().read(readSelectedDiagram);
        if (!nodeKey) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.key === "Enter" || event.key === " ") {
            promptMermaidEdit(editor, host, nodeKey);
            return;
        }
        /** Remove the selected block and leave a usable text insertion point. */
        function deleteDiagram(): void {
            const node = $getNodeByKey(nodeKey);
            if (!$isMermaidNode(node)) return;
            const paragraph = $createParagraphNode();
            node.insertAfter(paragraph);
            node.remove();
            paragraph.selectStart();
        }
        editor.update(deleteDiagram, { tag: "history-push" });
        editor.focus();
    }

    /** Reflect native node selection without storing a second selection state. */
    function refreshSelection(): void {
        let selectedKeys = new Set<NodeKey>();
        /** Read the keys currently selected by Lexical. */
        function readSelectedKeys(): void {
            const selection = $getSelection();
            if ($isNodeSelection(selection)) {
                for (const node of selection.getNodes()) selectedKeys.add(node.getKey());
            }
        }
        editor.getEditorState().read(readSelectedKeys);
        for (const diagram of root?.querySelectorAll<HTMLElement>("[data-mermaid-node-key]") ?? []) {
            const selected = selectedKeys.has(diagram.dataset.mermaidNodeKey ?? "");
            diagram.classList.toggle("ring-2", selected);
            diagram.classList.toggle("ring-primary", selected);
        }
    }

    root?.addEventListener("click", handleClick, { capture: true, signal: lifecycle.signal });
    root?.addEventListener("keydown", handleKeyDown, { capture: true, signal: lifecycle.signal });
    const unregisterSelection = editor.registerUpdateListener(refreshSelection);

    /** Release root handlers and an open dialog when the editor is destroyed. */
    function cleanupMermaidBehavior(): void {
        lifecycle.abort();
        unregisterSelection();
        state.closeDialog?.();
        behaviorStates.delete(editor);
    }
    return cleanupMermaidBehavior;
}

/** Open a diagram form without removing slash text or changing content until Apply. */
export function promptMermaidInsert(editor: LexicalEditor, host: HTMLElement): void {
    if (!canEditDiagram(editor, host)) return;
    let selection: RangeSelection | null = null;
    /** Preserve the insertion range before the source form takes keyboard focus. */
    function captureSelection(): void {
        const current = $getSelection();
        if ($isRangeSelection(current)) selection = current.clone();
    }
    editor.getEditorState().read(captureSelection);

    /** Insert source at the saved range as a single undoable editor change. */
    function applyDiagram(source: string): void {
        if (!canEditDiagram(editor, host)) return;
        /** Restore the original range, remove its slash trigger, and insert the block. */
        function insertDiagram(): void {
            if (selection) {
                if (!$getNodeByKey(selection.anchor.key)?.isAttached()
                    || !$getNodeByKey(selection.focus.key)?.isAttached()) return;
                $setSelection(selection.clone());
                const trigger = getCurrentWordFromSelection();
                if (trigger.startsWith("/")) removeTextFromCurrentSelection(trigger);
            } else {
                $getRoot().selectEnd();
            }
            const node = $createMermaidNode(source);
            $insertNodes([node]);
            const paragraph = $createParagraphNode();
            node.insertAfter(paragraph);
            paragraph.selectStart();
        }
        editor.update(insertDiagram, { tag: "history-push" });
        editor.focus();
    }
    openMermaidModal(editor, host, DEFAULT_SOURCE, false, applyDiagram);
}

/** Reopen an existing diagram's source and replace only that node after validation. */
function promptMermaidEdit(editor: LexicalEditor, host: HTMLElement, nodeKey: NodeKey): void {
    if (!canEditDiagram(editor, host)) return;
    let source: string | null = null;
    /** Read source while retaining the selected node's stable identity. */
    function readSource(): void {
        const node = $getNodeByKey(nodeKey);
        if ($isMermaidNode(node)) source = node.getSource();
    }
    editor.getEditorState().read(readSource);
    if (source === null) return;
    /** Apply validated source as a separate undoable edit to the original diagram. */
    function applyDiagram(nextSource: string): void {
        if (!canEditDiagram(editor, host)) return;
        /** Replace source only if the original diagram still exists in this editor. */
        function updateDiagram(): void {
            const node = $getNodeByKey(nodeKey);
            if (!$isMermaidNode(node) || !node.isAttached()) return;
            node.setSource(nextSource);
            selectDiagram(nodeKey);
        }
        // Lexical's focus method does not focus the DOM when restoring a node selection.
        editor.getRootElement()?.focus({ preventScroll: true });
        editor.update(updateDiagram, { tag: "history-push" });
        editor.focus();
    }
    openMermaidModal(editor, host, source, true, applyDiagram);
}

/** Present source and live preview while keeping invalid or cancelled edits out of history. */
function openMermaidModal(
    editor: LexicalEditor,
    host: HTMLElement,
    initialSource: string,
    editing: boolean,
    onApply: (source: string) => void,
): void {
    const state = behaviorStates.get(editor);
    state?.closeDialog?.();
    const modal = createModalInstance("bloomerp-general-use-modal", host);
    const body = modal.getBodyElement();
    if (!body) {
        modal.destroy();
        return;
    }
    modal.setTitle(editing ? _("Edit Mermaid diagram") : _("Insert Mermaid diagram"));
    modal.setSize("xl");
    body.style.maxHeight = "calc(100dvh - 12rem)";
    const lifecycle = new AbortController();
    const options = { signal: lifecycle.signal };
    let disposed = false;
    let renderVersion = 0;
    let previewTimer: number | null = null;
    let validSource: string | null = null;

    const form = document.createElement("form");
    form.className = "flex flex-col gap-3";
    const panels = document.createElement("div");
    panels.className = "grid gap-4 md:grid-cols-2";
    const sourceLabel = document.createElement("label");
    sourceLabel.className = "flex flex-col gap-2 font-medium";
    sourceLabel.textContent = _("Mermaid source");
    const source = document.createElement("textarea");
    source.className = "textarea w-full min-h-72 resize-y font-mono text-sm font-normal";
    source.rows = 14;
    source.spellcheck = false;
    source.required = true;
    source.value = initialSource;
    source.dataset.mermaidSource = "true";
    sourceLabel.appendChild(source);
    const previewPanel = document.createElement("div");
    previewPanel.className = "flex min-w-0 flex-col gap-2";
    const previewHeading = document.createElement("p");
    previewHeading.className = "font-medium";
    previewHeading.textContent = _("Preview");
    const preview = document.createElement("div");
    preview.className = "min-h-72 overflow-auto rounded-xl border border-gray-200 p-3";
    preview.style.maxHeight = "min(55vh, 32rem)";
    preview.dataset.mermaidPreview = "true";
    preview.setAttribute("aria-label", _("Diagram preview"));
    previewPanel.append(previewHeading, preview);
    panels.append(sourceLabel, previewPanel);
    const errorMessage = document.createElement("p");
    errorMessage.className = "whitespace-pre-wrap text-sm text-danger-dark";
    errorMessage.setAttribute("role", "alert");
    errorMessage.hidden = true;
    const actions = document.createElement("div");
    actions.className = "flex justify-end gap-2";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn btn-secondary";
    cancel.textContent = _("Cancel");
    const apply = document.createElement("button");
    apply.type = "submit";
    apply.className = "btn btn-primary";
    apply.textContent = editing ? _("Apply") : _("Insert diagram");
    apply.disabled = true;
    actions.append(cancel, apply);
    form.append(panels, errorMessage, actions);
    body.replaceChildren(form);

    /** Cancel pending rendering and release the disposable form immediately. */
    function closeDialog(): void {
        if (disposed) return;
        disposed = true;
        renderVersion += 1;
        if (previewTimer !== null) window.clearTimeout(previewTimer);
        lifecycle.abort();
        if (state?.closeDialog === closeDialog) state.closeDialog = null;
        modal.destroy();
    }

    /** Show only a preview corresponding to the current source and open dialog. */
    async function refreshPreview(): Promise<void> {
        previewTimer = null;
        const version = ++renderVersion;
        const value = source.value;
        validSource = null;
        apply.disabled = true;
        errorMessage.hidden = true;
        preview.setAttribute("aria-busy", "true");
        preview.textContent = _("Rendering diagram…");
        try {
            if (!value.trim()) throw new Error(_("Enter Mermaid source to create a diagram."));
            const svg = await renderMermaid(value);
            if (disposed || version !== renderVersion || value !== source.value) return;
            preview.innerHTML = svg;
            validSource = value;
            apply.disabled = false;
        } catch (error: unknown) {
            if (disposed || version !== renderVersion || value !== source.value) return;
            preview.textContent = _("Fix the source to preview this diagram.");
            errorMessage.textContent = error instanceof Error ? error.message : _("Unable to render this diagram.");
            errorMessage.hidden = false;
        } finally {
            if (!disposed && version === renderVersion) preview.removeAttribute("aria-busy");
        }
    }

    /** Start a deferred preview without leaving an unhandled rendering promise. */
    function renderPreview(): void { void refreshPreview(); }

    /** Invalidate the previous preview immediately and debounce source edits. */
    function schedulePreview(): void {
        renderVersion += 1;
        validSource = null;
        apply.disabled = true;
        if (previewTimer !== null) window.clearTimeout(previewTimer);
        previewTimer = window.setTimeout(renderPreview, 250);
    }

    /** Commit only the exact source that successfully produced the current preview. */
    function submitDiagram(event: SubmitEvent): void {
        event.preventDefault();
        if (disposed || !canEditDiagram(editor, host)) {
            closeDialog();
            return;
        }
        if (validSource !== source.value) return;
        const value = source.value;
        closeDialog();
        onApply(value);
    }

    cancel.addEventListener("click", closeDialog, options);
    source.addEventListener("input", schedulePreview, options);
    form.addEventListener("submit", submitDiagram, options);
    modal.element.addEventListener("bloomerp:modal-closed", closeDialog, options);
    if (state) state.closeDialog = closeDialog;
    modal.open();
    source.focus();
    renderPreview();
}
