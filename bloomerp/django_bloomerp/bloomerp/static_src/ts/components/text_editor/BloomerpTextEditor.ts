import { bindReferencePreviews } from "@/utils/referencePreviews";
import type { ContextMenuSubmenu } from "@/utils/contextMenu";
import { ReferencePicker } from "./utils/referencePicker";
import { ReferenceNode, type ReferenceTarget } from "./nodes/ReferenceNode";
import { FileImageNode } from "./nodes/FileImageNode";
import { TemplatePicker } from "./utils/templatePicker";
import { t as _ } from "@/utils/i18n";
import { Command, COMMANDS, registerCommands } from "./commands";
import { ImageNode } from "./nodes/ImageNode";
import { CodeBlockNode } from "./nodes/CodeBlockNode";
import { MermaidNode } from "./nodes/MermaidNode";
import { registerMermaidBehavior } from "./utils/mermaidBehavior";
import { registerLinkBehavior } from "./utils/linkBehavior";
import { registerHtmlBehavior } from "./utils/htmlBehavior";
import { registerImageBehavior } from "./utils/imageBehavior";
import { registerTableBehavior } from "./utils/tableBehavior";
import { $generateHtmlFromNodes, $generateNodesFromDOM } from "@lexical/html";

import {
    $isBlockElementNode,
    $createParagraphNode,
    $getRoot,
    $isElementNode,
    $isDecoratorNode,
    PASTE_COMMAND,
    $getNearestNodeFromDOMNode,
    $getSelection,
    $insertNodes,
    $isInlineElementOrDecoratorNode,
    $isRangeSelection,
    $isTextNode,
    COMMAND_PRIORITY_LOW,
    CLICK_COMMAND,
    KEY_SPACE_COMMAND,
    createEditor,
    LexicalEditor,
    type LexicalNode,
    type Klass,
} from "lexical";

import {
    HeadingNode,
    QuoteNode,
    registerRichText,
} from "@lexical/rich-text";

import { mergeRegister } from "@lexical/utils";

import {
    createEmptyHistoryState,
    registerHistory,
} from "@lexical/history";
import { $isListItemNode, $isListNode, ListItemNode, ListNode, registerList } from "@lexical/list";
import { LinkNode } from "@lexical/link";
import {
    TableCellNode,
    TableNode,
    TableRowNode,
} from "@lexical/table";
import { Action, ACTIONS } from "./actions";
import { EditorActionRegistry, type ActionSurface } from "./actionRegistry";
import { ActionToolbar, createActionToolbarButton } from "./actionToolbar";
import { SelectionToolbar } from "./selectionToolbar";
import { ResizableTableNode, $replaceTableNode } from "./nodes/ResizableTableNode";
import { registerTableColumnResizing } from "./utils/tableColumnResizing";
import { registerTableCellSelection } from "./utils/tableCellSelection";
import { createEditorHTMLConfig } from "./serialization";
import { BaseWidget } from "../widgets/BaseWidget";
import { parseBoolean } from "../../utils/booleans";

import HtmlNode from "./nodes/HtmlNode";
import {
    createToolbarVisibilityCookie,
    isToolbarHiddenFromCookie,
    TEXT_EDITOR_TOOLBAR_VISIBILITY_EVENT,
} from "./utils/toolbarVisibility";


export class BloomerpTextEditor extends BaseWidget {
    public editor: LexicalEditor | null = null;
    private referencePreviewCleanup: (() => void) | null = null;
    private referencePicker: ReferencePicker | null = null;
    private templatePicker: TemplatePicker | null = null;
    private unregister: (() => void) | null = null;
    private commands: Array<Command> = [];
    public readonly actionRegistry = new EditorActionRegistry(this, ACTIONS);
    private actionToolbar: ActionToolbar | null = null;
    private selectionToolbar: SelectionToolbar | null = null;
    /** Dispose portal controls when HTMX removes the owning editor widget. */
    private readonly beforeCleanup = (event: Event): void => {
        if (event.target === this.element) this.destroy();
    };
    
    private actionsToolbar: HTMLElement | null = null;
    private toolbarToggleButton: HTMLButtonElement | null = null;
    private toolbarToggleCleanup: (() => void) | null = null;
    private toolbarRevealButton: HTMLButtonElement | null = null;
    private toolbarHidden: boolean = true;
    private toolbarVisibilityHandler: ((event: Event) => void) | null = null;
    private hiddenInput:HTMLInputElement;
    private suppressNextChange: boolean = false;
    private isInitializing: boolean = false;
    private editorId:string;
    private includeToolbar:boolean = true;
    private editorRootSelector:string = '';
    private hostClickHandler: ((event: MouseEvent) => void) | null = null;

    // Extra commands
    public slashExtraActions:string[] = []
    public rangeExtraActions:string[] = []

    // Styling for the editor
    public styling: string | null = null;
    public overrideDefaultStyling: boolean = false;

    /** Let specialized editors register extra nodes before the initial HTML load. */
    protected getAdditionalNodes(): Array<Klass<LexicalNode>> { return []; }

    /** Show the configured hint only for an empty document, preserving non-text content. */
    private updatePlaceholder(editorRoot: HTMLElement): void {
        const placeholder = this.element.dataset.placeholder;
        if (!placeholder || !this.editor) return;
        editorRoot.dataset.placeholder = placeholder;
        editorRoot.setAttribute("aria-placeholder", placeholder);
        editorRoot.dataset.empty = String(this.editor.getEditorState().read(this.canShowPlaceholder));
    }

    /** Recognize the empty paragraph Lexical creates without hiding images, lists, or tables. */
    private canShowPlaceholder(): boolean {
        const children = $getRoot().getChildren();
        if (!children.length) return true;
        const first = children[0];
        return children.length === 1 && $isElementNode(first) && first.getType() === "paragraph" && first.isEmpty();
    }

    /** Create the Lexical editor and connect its actions to the widget value. */
    public initialize(): void {
        // Get the editor ID
        this.editorId = this.element.dataset.editorId;
        
        // Get the editor
        const editorRef = this.element.querySelector("#editor-" + this.editorId) as HTMLElement | null;
        
        // Throw error if the editor is not found
        if (!editorRef) {
            throw new Error("Could not find #lexical-editor");
        }
        this.editorRootSelector = `#editor-${CSS.escape(this.editorId)}`;

        // Get the hidden input
        this.hiddenInput = this.element.querySelector('[data-text-editor-input="true"]') as HTMLInputElement;

        // Get the override styling from the data attribute
        const overrideDefaultStyling = this.element.dataset.overrideDefaultStyling ?? 'False';
        this.overrideDefaultStyling = parseBoolean(overrideDefaultStyling, false);

        // Get the styling from the data attribute
        const styling = this.element.dataset.styling ?? null;
        this.setStyling(styling);

        this.editor = createEditor({
            namespace: "BloomerpTextEditor",
            editable: this.element.dataset.disabled !== "true",
            html: createEditorHTMLConfig(),
            theme: {
                text: {
                    italic: 'bloomerp-text-editor-italic',
                    underline: 'bloomerp-text-editor-underline',
                    strikethrough: 'bloomerp-text-editor-strikethrough',
                    underlineStrikethrough: 'bloomerp-text-editor-underline-strikethrough',
                },
                link: !this.overrideDefaultStyling ? 'text-blue-600 underline' : '',
                paragraph: !this.overrideDefaultStyling ? 'text-md mb-2 last:mb-0' : '',
                quote: !this.overrideDefaultStyling ? 'bloomerp-text-editor-quote' : '',
                heading: {
                    h1: !this.overrideDefaultStyling ? 'text-4xl font-bold mb-2' : '',
                    h2: !this.overrideDefaultStyling ? 'text-2xl font-bold mb-1' : '',
                    h3: !this.overrideDefaultStyling ? 'text-xl font-bold' : '',
                },
                list: {
                    ul: !this.overrideDefaultStyling ? 'list-disc list-inside pl-4' : '',
                    ol: !this.overrideDefaultStyling ? 'list-decimal list-inside pl-4' : '',
                    checklist: 'bloomerp-text-editor-checklist',
                    listitemChecked: 'bloomerp-text-editor-checklist-item-checked',
                    listitemUnchecked: 'bloomerp-text-editor-checklist-item-unchecked',
                    nested: {
                        listitem: 'bloomerp-text-editor-nested-list-item',
                    },
                },
                table: !this.overrideDefaultStyling ? 'my-3 w-full table-fixed border-collapse overflow-hidden rounded-lg border border-gray-200 text-left' : '',
                tableRow: !this.overrideDefaultStyling ? 'border-b border-gray-200 last:border-b-0' : '',
                tableCell: !this.overrideDefaultStyling ? 'min-w-24 border-r border-gray-200 px-1 py-1 align-top text-sm outline-none last:border-r-0' : '',
                tableCellHeader: 'bloomerp-text-editor-table-header' + (!this.overrideDefaultStyling ? ' font-medium' : ''),
                tableSelection: 'bloomerp-text-editor-table-selection',
                code: !this.overrideDefaultStyling ? 'bloomerp-text-editor-code-block' : '',
            },
            nodes: [
                HeadingNode, 
                QuoteNode,
                ListNode,
                ListItemNode,
                LinkNode,
                ResizableTableNode,
                { replace: TableNode, with: $replaceTableNode, withKlass: ResizableTableNode },
                TableRowNode,
                TableCellNode,
                ImageNode,
                ReferenceNode,
                FileImageNode,
                CodeBlockNode,
                MermaidNode,
                HtmlNode,
                ...this.getAdditionalNodes(),
            ],
            /** Surface editor failures instead of silently corrupting the field value. */
            onError: (error: Error): never => {
                throw error;
            },
        });
        this.includeToolbar = parseBoolean(this.element.dataset.includeToolbar, true);
        this.toolbarHidden = isToolbarHiddenFromCookie(document.cookie);
        this.toolbarVisibilityHandler = (event: Event) => {
            const customEvent = event as CustomEvent<{ hidden?: boolean }>;
            const hidden = customEvent.detail?.hidden;

            this.setToolbarHidden(
                typeof hidden === "boolean"
                    ? hidden
                    : isToolbarHiddenFromCookie(document.cookie),
                false,
            );
        };
        window.addEventListener(TEXT_EDITOR_TOOLBAR_VISIBILITY_EVENT, this.toolbarVisibilityHandler);

        this.editor.setRootElement(editorRef);
        editorRef.contentEditable = String(this.editor.isEditable());
        this.actionRegistry.initialize();
        this.element.addEventListener("htmx:beforeCleanupElement", this.beforeCleanup);
        this.referencePreviewCleanup = bindReferencePreviews(editorRef);
        this.hostClickHandler = (event: MouseEvent) => {
            if (event.target !== this.element) return;
            this.editor?.focus();
        };
        this.element.addEventListener('click', this.hostClickHandler);
        this.isInitializing = true;
        this.setValue(this.hiddenInput?.value ?? '', false);
        this.updateNestedListMarkers(editorRef);

        this.referencePicker = new ReferencePicker(this.element, this.editor);
        const historyState = createEmptyHistoryState();

        this.unregister = mergeRegister(
            /** Keep the native editing surface and action controls consistent with read-only state. */
            this.editor.registerEditableListener((editable: boolean): void => {
                editorRef.contentEditable = String(editable);
                this.actionToolbar?.refresh();
                if (!editable) this.selectionToolbar?.hide();
            }),
            this.editor.registerCommand(PASTE_COMMAND, this.pasteReferences.bind(this), COMMAND_PRIORITY_LOW),
            registerLinkBehavior(this.editor, this.element),
            registerRichText(this.editor),
            registerList(this.editor),
            registerHistory(this.editor, historyState, 300),
            registerTableBehavior(this.editor, this.element),
            registerTableColumnResizing(this.editor, this.element),
            registerTableCellSelection(this.editor, this.element),
            registerHtmlBehavior(this.editor),
            registerMermaidBehavior(this.editor, this.element),
            registerImageBehavior(this.editor, this.element),
            this.editor.registerCommand(CLICK_COMMAND, this.handleChecklistClick.bind(this), COMMAND_PRIORITY_LOW),
            this.editor.registerCommand(KEY_SPACE_COMMAND, this.handleChecklistSpace.bind(this), COMMAND_PRIORITY_LOW),
            /** Refresh action state and notify the form only when saved HTML changes. */
            this.editor.registerUpdateListener((): void => {
                this.updateNestedListMarkers(editorRef);
                this.updatePlaceholder(editorRef);
                this.actionToolbar?.refresh();

                if (this.isInitializing || this.suppressNextChange) {
                    this.suppressNextChange = false;
                    return;
                }

                if (this.hiddenInput && this.hiddenInput.value === this.getValue()) {
                    return;
                }

                this.onChange();
            }),
            ...registerCommands(this),
            ...this.commands.map(({ command, handler, priority = COMMAND_PRIORITY_LOW }) => (
                this.editor.registerCommand(command, (event) => handler.call(this, event), priority)
            )),
        );

        this.registerActionsToolbar()
        this.selectionToolbar = new SelectionToolbar(this);
        queueMicrotask(() => {
            this.isInitializing = false;
            this.suppressNextChange = false;
        });
    }

    /** Release editor menus, subscriptions, and Lexical resources. */
    public destroy(): void {
        this.toolbarToggleCleanup?.();
        this.toolbarToggleCleanup = null;
        this.selectionToolbar?.destroy();
        this.selectionToolbar = null;
        this.actionToolbar?.destroy();
        this.actionToolbar = null;
        this.actionRegistry.destroy();
        this.element.removeEventListener("htmx:beforeCleanupElement", this.beforeCleanup);
        this.referencePreviewCleanup?.();
        this.referencePreviewCleanup = null;
        this.referencePicker?.destroy();
        this.referencePicker = null;
        this.templatePicker?.destroy();
        this.templatePicker = null;
        if (this.hostClickHandler) {
            this.element?.removeEventListener('click', this.hostClickHandler);
            this.hostClickHandler = null;
        }

        if (this.toolbarVisibilityHandler) {
            window.removeEventListener(
                TEXT_EDITOR_TOOLBAR_VISIBILITY_EVENT,
                this.toolbarVisibilityHandler,
            );
            this.toolbarVisibilityHandler = null;
        }

        this.unregister?.();
        this.unregister = null;

        this.editor?.setRootElement(null);
        this.editor = null;

        if (this.actionsToolbar) {
            this.actionsToolbar.innerHTML = ''
            this.actionsToolbar = null;
        }

        this.toolbarToggleButton = null;
        this.toolbarRevealButton?.remove();
        this.toolbarRevealButton = null;
    }

    /** Open mention, object, or stored-image selection for this editor. */
    public openReferencePicker(kind: "user" | "object" | "file"): void {
        if (!this.editor || this.element.dataset.disabled === "true") return;
        this.referencePicker ??= new ReferencePicker(this.element, this.editor);
        this.referencePicker.open(kind);
    }

    /** Supply searchable reference actions to the existing slash menu. */
    public getReferenceSubmenu(kind: "user" | "object" | "file"): ContextMenuSubmenu {
        this.referencePicker ??= new ReferencePicker(this.element, this.editor!);
        return this.referencePicker.submenu(kind);
    }

    /** Expose reference occurrences directly from the editor's current node state. */
    public getReferences(): ReferenceTarget[] {
        const references: ReferenceTarget[] = [];
        /** Collect reference tokens and stored media through nested editor blocks. */
        function collectReferences(node: LexicalNode): void {
            if (node instanceof ReferenceNode || node instanceof FileImageNode) references.push(node.getReference());
            else if ($isElementNode(node)) for (const child of node.getChildren()) collectReferences(child);
        }
        /** Read committed editor state without mutating content or selection. */
        function collectFromRoot(): void { collectReferences($getRoot()); }
        this.editor?.getEditorState().read(collectFromRoot);
        return references;
    }

    /** Remove only the reference represented by one occurrence chip. */
    public removeReferenceOccurrence(occurrenceId: string): void {
        if (!this.editor || this.element.dataset.disabled === "true") return;
        /** Visit editor nodes and remove the matching atomic reference. */
        function removeOccurrence(node: LexicalNode): void {
            if ((node instanceof ReferenceNode || node instanceof FileImageNode) && node.getReference().occurrence_id === occurrenceId) {
                node.remove();
            } else if ($isElementNode(node)) {
                for (const child of node.getChildren()) removeOccurrence(child);
            }
        }
        /** Apply the removal within a single undoable editor update. */
        function removeFromRoot(): void { removeOccurrence($getRoot()); }
        this.editor.update(removeFromRoot, { discrete: true });
    }

    /** Assign new occurrence identities to copied references while preserving undo identities. */
    private pasteReferences(event: ClipboardEvent | InputEvent | KeyboardEvent): boolean {
        if (!(event instanceof ClipboardEvent) || !this.editor) return false;
        const html = event.clipboardData?.getData("text/html") ?? "";
        if (!html.includes("data-reference-kind")) return false;
        event.preventDefault();
        const document = new DOMParser().parseFromString(html, "text/html");
        for (const element of document.querySelectorAll<HTMLElement>("[data-reference-kind]")) element.dataset.occurrenceId = crypto.randomUUID();
        $insertNodes($generateNodesFromDOM(this.editor, document));
        return true;
    }

    /**
     * Returns the actions available for this editor
     */
    public getActions() : Array<Action> {
        /** Expose scoped definitions without leaking custom actions into another editor. */
        function definition(entry: import("./actionRegistry").RegisteredAction): Action { return entry.action; }
        return this.actionRegistry.list("toolbar").map(definition);
    }

    /** Resolve a scoped capability without exposing it to other editor instances. */
    public getAction(key: string): Action | undefined { return this.actionRegistry.get(key); }

    /**
     * Registers the actions toolbar
     */
    private registerActionsToolbar(): void {
        let actionsToolbarId = this.element.dataset.actionsToolbarSectionId;
        
        const standardToolbar = (!actionsToolbarId && this.includeToolbar)
        if (standardToolbar) {
            actionsToolbarId = 'actions-toolbar-' + this.editorId;
        }

        if (!actionsToolbarId) return;

        this.actionsToolbar = document.getElementById(actionsToolbarId) as HTMLElement | null;
        if (!this.actionsToolbar) return;

        this.toolbarToggleButton = null;
        this.actionToolbar?.destroy();
        this.actionsToolbar.innerHTML = ''
        this.actionToolbar = new ActionToolbar(this, "toolbar", this.actionRegistry.captureSelection.bind(this.actionRegistry));
        this.actionsToolbar.appendChild(this.actionToolbar.element);

        if (standardToolbar) {
            this.actionsToolbar.className = 'flex mb-4 gap-2 overflow-x-scroll'
        }

        this.actionsToolbar.dataset.textEditorToolbar = 'true';
        this.createToolbarToggleButton();
        this.createToolbarRevealButton();
        this.setToolbarHidden(this.toolbarHidden, false);
    }

    /** Create the localized control for collapsing the formatting toolbar. */
    private createToolbarToggleButton(): void {
        if (!this.actionsToolbar) return;

        this.toolbarToggleCleanup?.();
        const control = createActionToolbarButton(_('Hide formatting toolbar'), 'fa-solid fa-eye-slash');
        const toggleButton = control.element;
        this.toolbarToggleCleanup = control.destroy;
        /** Keep the selected text intact while collapsing formatting controls. */
        toggleButton.addEventListener('mousedown', (event: MouseEvent): void => {
            event.preventDefault();
        });
        /** Persist the shared toolbar visibility preference through the standard control. */
        toggleButton.addEventListener('click', (): void => {
            this.setToolbarHidden(true, true);
        });

        this.actionToolbar?.appendControl(toggleButton);
        this.toolbarToggleButton = toggleButton;
    }

    /** Create the localized control for revealing the formatting toolbar. */
    private createToolbarRevealButton(): void {
        if (this.toolbarRevealButton || !this.element) return;

        const revealButton = document.createElement('button');
        revealButton.type = 'button';
        revealButton.className = 'btn btn-secondary btn-sm';
        revealButton.setAttribute('aria-label', _('Show formatting toolbar'));
        revealButton.title = _('Show formatting toolbar');
        revealButton.dataset.textEditorToolbarReveal = 'true';
        revealButton.innerHTML = '<i class="fa-solid fa-ellipsis" aria-hidden="true"></i>';
        revealButton.addEventListener('click', () => {
            this.setToolbarHidden(false, true);
        });

        this.element.appendChild(revealButton);
        this.toolbarRevealButton = revealButton;
    }

    private setToolbarHidden(hidden: boolean, persist: boolean): void {
        this.toolbarHidden = hidden;
        this.element.dataset.toolbarHidden = hidden ? 'true' : 'false';

        if (this.actionsToolbar) {
            this.actionsToolbar.dataset.toolbarHidden = hidden ? 'true' : 'false';
        }

        if (this.toolbarToggleButton) {
            this.toolbarToggleButton.hidden = hidden;
        }

        if (this.toolbarRevealButton) {
            this.toolbarRevealButton.hidden = !hidden;
        }

        if (!persist) return;

        document.cookie = createToolbarVisibilityCookie(hidden);
        window.dispatchEvent(new CustomEvent(TEXT_EDITOR_TOOLBAR_VISIBILITY_EVENT, {
            detail: { hidden },
        }));
    }
    
    /** Synchronize saved HTML and notify only this editor’s owning form. */
    public override onChange(): void {
        if (this.hiddenInput) {
            this.hiddenInput.value = this.getValue();
        }

        super.onChange();
        this.element.dispatchEvent(new CustomEvent("bloomerp:references-changed", { bubbles: true }));
    }

    /** Restore editor HTML and refresh occurrence chips after initialization or form undo. */
    public setValue(value: unknown, emitChange: boolean = false): void {
        const editor = this.editor;
        if (!editor) {
            return;
        }

        const html = typeof value === 'string' ? value : '';
        this.suppressNextChange = !emitChange;

        editor.update(() => {
            const root = $getRoot();
            root.clear();

            if (!html.trim()) {
                root.append($createParagraphNode());
                return;
            }

            const parser = new DOMParser();
            const document = parser.parseFromString(html, 'text/html');
            const nodes = $generateNodesFromDOM(editor, document);

            if (nodes.length > 0) {
                const validNodes = this.normalizeImportedNodesForRoot(nodes);

                if (validNodes.length > 0) {
                    root.append(...validNodes);
                } else {
                    root.append($createParagraphNode());
                }
            } else {
                root.append($createParagraphNode());
            }
        }, { discrete: true });
        if (this.hiddenInput) {
            this.hiddenInput.value = this.getValue();
        }
        const editorRoot = editor.getRootElement();
        if (editorRoot) this.updatePlaceholder(editorRoot);
        this.element.dispatchEvent(new CustomEvent("bloomerp:references-changed", { bubbles: true }));
    }

    /** Hide markers on list wrappers and make checklist items keyboard reachable. */
    private updateNestedListMarkers(editorRoot: HTMLElement): void {
        editorRoot.querySelectorAll<HTMLElement>('.bloomerp-text-editor-nested-list-item').forEach((listItem) => {
            const elementChildren = Array.from(listItem.children);
            const containsOnlyNestedList = elementChildren.length === 1
                && elementChildren[0].matches('ul, ol');

            listItem.classList.toggle('list-none', containsOnlyNestedList);
        });
        editorRoot.querySelectorAll<HTMLElement>('li[role="checkbox"]').forEach((listItem) => {
            listItem.tabIndex = 0;
        });
    }

    /** Toggle a checklist item when its visible checkbox marker is clicked. */
    private handleChecklistClick(event: MouseEvent): boolean {
        const target = event.target;
        if (!(target instanceof Element)) return false;

        const listItem = target.closest<HTMLElement>('li[role="checkbox"]');
        if (!listItem || !this.editor?.getRootElement()?.contains(listItem)) return false;

        const bounds = listItem.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.left + 24) return false;

        event.preventDefault();
        this.toggleChecklistItem(listItem);
        return true;
    }

    /** Toggle a focused checklist item with the Space key. */
    private handleChecklistSpace(event: KeyboardEvent): boolean {
        const target = event.target;
        if (!(target instanceof HTMLElement) || !target.matches('li[role="checkbox"]')) return false;
        if (!this.editor?.getRootElement()?.contains(target)) return false;

        event.preventDefault();
        this.toggleChecklistItem(target);
        return true;
    }

    /** Change the Lexical checked state so the next HTML save retains it. */
    private toggleChecklistItem(listItem: HTMLElement): void {
        const editor = this.editor;
        if (!editor) return;

        /** Update only a checklist item belonging to this editor. */
        function toggleNode(): void {
            const node = $getNearestNodeFromDOMNode(listItem);
            const parent = node?.getParent();
            if ($isListItemNode(node) && $isListNode(parent) && parent.getListType() === 'check') {
                node.toggleChecked();
            }
        }

        editor.update(toggleNode);
    }

    private normalizeImportedNodesForRoot(nodes: LexicalNode[]): LexicalNode[] {
        const rootNodes: LexicalNode[] = [];
        let inlineParagraph: ReturnType<typeof $createParagraphNode> | null = null;

        const flushInlineParagraph = () => {
            if (inlineParagraph && !inlineParagraph.isEmpty()) {
                rootNodes.push(inlineParagraph);
            }
            inlineParagraph = null;
        };

        for (const node of nodes) {
            if (this.isRootCompatibleImportedNode(node)) {
                flushInlineParagraph();
                rootNodes.push(node);
                continue;
            }

            if ($isTextNode(node) || $isInlineElementOrDecoratorNode(node)) {
                inlineParagraph ??= $createParagraphNode();
                inlineParagraph.append(node);
                continue;
            }

            flushInlineParagraph();
        }

        flushInlineParagraph();
        return rootNodes;
    }

    /** Preserve block decorators alongside standard imported document blocks. */
    private isRootCompatibleImportedNode(node: LexicalNode): boolean {
        const type = node.getType();
        return ['paragraph', 'heading', 'quote', 'list', 'table'].includes(type)
            || $isBlockElementNode(node)
            || ($isDecoratorNode(node) && !node.isInline());
    }

    public getValue(): string {
        return this.toHtml()
    }

    /** Supply template search to any context-menu entry point. */
    public getTemplateSubmenu(): ContextMenuSubmenu {
        this.templatePicker ??= new TemplatePicker(this.element, this.editor!);
        return this.templatePicker.submenu();
    }

    /** Open the shared template command while keeping the current insertion range. */
    public openTemplatePicker(): void {
        if (!this.editor || !this.element.dataset.templateSearchUrl) return;
        this.templatePicker ??= new TemplatePicker(this.element, this.editor);
        this.templatePicker.open();
    }

    public insertNode(node: LexicalNode | (() => LexicalNode)): void {
        const editor = this.editor;
        if (!editor) {
            return;
        }

        editor.focus();
        editor.update(() => {
            const resolvedNode = typeof node === 'function' ? node() : node;
            const selection = $getSelection();

            if ($isRangeSelection(selection)) {
                $insertNodes([resolvedNode]);
                return;
            }

            const paragraph = $createParagraphNode();
            paragraph.append(resolvedNode);
            $getRoot().append(paragraph);
            paragraph.selectEnd();
        });
    }

    /**
     * 
     * @returns editor state in html
     */
    public toHtml() : string {
        const editor = this.editor;
        if (!editor) {
            return this.hiddenInput?.value ?? '';
        }

        let html = '';
        editor.getEditorState().read(() => {
            html = $generateHtmlFromNodes(editor, null);
        });

        return html;
    }

    /**
     * Hook to register extra commands
     * @param command the command to register
     */
    public registerCommand(command:Command) {
        this.commands.push(command);

        if (!this.editor) {
            return;
        }

        const { command: lexicalCommand, handler, priority = COMMAND_PRIORITY_LOW } = command;
        const unregister = this.editor.registerCommand(
            lexicalCommand,
            (event) => handler.call(this, event),
            priority,
        );

        this.unregister = this.unregister
            ? mergeRegister(this.unregister, unregister)
            : unregister;

    }

    /**
     * Hook to register extra actions
     * @param action the action to register
     * @param key the key to register the action under
     * @param addToSlash whether to add the action to the slash menu
     * @param addToRange whether to add the action to the range menu
     */
    public registerAction(action: Action, key: string, addToSlash: boolean = false, addToRange: boolean = false): void {
        const surfaces = new Set<ActionSurface>(action.surfaces ?? ["toolbar"]);
        if (addToSlash) surfaces.add("slash");
        if (addToRange) surfaces.add("selection");
        this.actionRegistry.register(key, { ...action, surfaces: [...surfaces] });
        if (addToSlash && !this.slashExtraActions.includes(key)) this.slashExtraActions.push(key);
        if (addToRange && !this.rangeExtraActions.includes(key)) this.rangeExtraActions.push(key);
    }

    /**
     * Set the styling for the editor
     * @param styling the styling to apply
     */
    public setStyling(styling: string | null) {
        this.styling = styling;

        const stylingElement = this.element.querySelector('#text-editor-styling-' + this.editorId) as HTMLStyleElement | null;
        if (!stylingElement) {
            return;
        }

        const scopedStyling = this.styling ? this.scopeStylingToEditor(this.styling) : '';
        stylingElement.textContent = [
            this.overrideDefaultStyling ? this.getDocumentResetStyling() : '',
            scopedStyling,
        ].filter(Boolean).join('\n\n');
    }

    /** Reset application presentation without disabling native editing or atomic read-only nodes. */
    private getDocumentResetStyling(): string {
        if (!this.editorRootSelector) {
            return '';
        }

        return `
:where(${this.editorRootSelector}, ${this.editorRootSelector} *) {
    all: revert;
}

:where(${this.editorRootSelector}[contenteditable="true"]) {
    -webkit-user-modify: read-write;
}

:where(${this.editorRootSelector} *) {
    -webkit-user-modify: inherit;
}

:where(${this.editorRootSelector}[contenteditable="false"], ${this.editorRootSelector}[contenteditable="false"] *, ${this.editorRootSelector} [contenteditable="false"], ${this.editorRootSelector} [contenteditable="false"] *) {
    -webkit-user-modify: read-only;
}

:where(${this.editorRootSelector}) {
    display: block;
    min-height: inherit;
    outline: none;
    white-space: normal;
    word-break: normal;
    overflow-wrap: normal;
}
`.trim();
    }

    /**
     * Scopes caller-provided CSS so selectors only affect this editor root.
     */
    private scopeStylingToEditor(styling: string): string {
        const trimmedStyling = styling.trim();
        if (!trimmedStyling || !this.editorRootSelector) {
            return '';
        }

        try {
            const stylesheet = new CSSStyleSheet();
            stylesheet.replaceSync(trimmedStyling);
            return Array.from(stylesheet.cssRules)
                .map((rule)=>this.scopeCssRule(rule))
                .filter(Boolean)
                .join('\n');
        } catch {
            return `${this.editorRootSelector} {\n${trimmedStyling}\n}`;
        }
    }

    private scopeCssRule(rule: CSSRule): string {
        if (rule instanceof CSSStyleRule) {
            const selectorText = rule.selectorText
                .split(',')
                .map((selector)=>this.scopeCssSelector(selector.trim()))
                .join(', ');
            return `${selectorText} { ${rule.style.cssText} }`;
        }

        if (rule instanceof CSSMediaRule) {
            const childRules = Array.from(rule.cssRules)
                .map((childRule)=>this.scopeCssRule(childRule))
                .filter(Boolean)
                .join('\n');
            return childRules ? `@media ${rule.conditionText} {\n${childRules}\n}` : '';
        }

        return rule.cssText;
    }

    private scopeCssSelector(selector: string): string {
        if (['body', 'html', ':root'].includes(selector)) {
            return this.editorRootSelector;
        }

        if (selector.startsWith('body.')) {
            return `${this.editorRootSelector}${selector.slice(4)}`;
        }

        if (selector.startsWith('html.')) {
            return `${this.editorRootSelector}${selector.slice(4)}`;
        }

        if (selector.startsWith(':root.')) {
            return `${this.editorRootSelector}${selector.slice(5)}`;
        }

        if (selector.startsWith('body ')) {
            return `${this.editorRootSelector} ${selector.slice(5)}`;
        }

        if (selector.startsWith('html ')) {
            return `${this.editorRootSelector} ${selector.slice(5)}`;
        }

        if (selector.startsWith(':root ')) {
            return `${this.editorRootSelector} ${selector.slice(6)}`;
        }

        return `${this.editorRootSelector} ${selector}`;
    }

}
