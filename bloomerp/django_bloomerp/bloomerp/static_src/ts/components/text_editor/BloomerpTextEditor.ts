import { registerCommands } from "./commands";
import { registerTableBehavior } from "./utils/tableBehavior";
import { $generateHtmlFromNodes, $generateNodesFromDOM } from "@lexical/html";

import {
    $createParagraphNode,
    $getRoot,
    createEditor,
    LexicalEditor,
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
import { ListItemNode, ListNode } from "@lexical/list";
import { LinkNode } from "@lexical/link";
import {
    TableCellNode,
    TableNode,
    TableRowNode,
} from "@lexical/table";
import { Action, ACTIONS } from "./actions";
import { BaseWidget } from "../widgets/BaseWidget";

export class BloomerpTextEditor extends BaseWidget {
    private editor: LexicalEditor | null = null;
    private unregister: (() => void) | null = null;
    private button:HTMLButtonElement;
    private actionsToolbar:HTMLElement;
    private hiddenInput:HTMLInputElement;
    private suppressNextChange: boolean = false;
    private isInitializing: boolean = false;

    public initialize(): void {
        const editorRef = this.element.querySelector("#editor") as HTMLElement | null;

        if (!editorRef) {
            throw new Error("Could not find #lexical-editor");
        }

        this.hiddenInput = this.element.querySelector('[data-text-editor-input="true"]') as HTMLInputElement;

        this.editor = createEditor({
            namespace: "BloomerpTextEditor",
            theme: {
                paragraph: 'text-md',
                heading: {
                    h1: 'text-4xl font-bold mb-2',
                    h2: 'text-2xl font-bold mb-1',
                    h3: 'text-2xl font-bold',
                },
                list: {
                    ul: 'list-disc list-inside pl-4',
                    ol: 'list-decimal list-inside pl-4',
                },
                table: 'my-3 w-full table-fixed border-collapse overflow-hidden rounded-lg border border-gray-200 text-left',
                tableRow: 'border-b border-gray-200 last:border-b-0',
                tableCell: 'min-w-24 border-r border-gray-200 px-1 py-1 align-top text-sm outline-none last:border-r-0',
                tableCellHeader: 'bg-gray-100 font-medium',
            },
            nodes: [
                HeadingNode, 
                QuoteNode,
                ListNode,
                ListItemNode,
                LinkNode,
                TableNode,
                TableRowNode,
                TableCellNode,
            ],
            onError: (error: Error) => {
                throw error;
            },
        });
        this.button = this.element.querySelector('#h1-button')

        this.editor.setRootElement(editorRef);
        this.isInitializing = true;
        this.setValue(this.hiddenInput?.value ?? '', false);

        const historyState = createEmptyHistoryState();

        this.unregister = mergeRegister(
            registerRichText(this.editor),
            registerHistory(this.editor, historyState, 300),
            registerTableBehavior(this.editor, this.element),
            this.editor.registerUpdateListener(() => {
                if (this.isInitializing || this.suppressNextChange) {
                    this.suppressNextChange = false;
                    return;
                }

                if (this.hiddenInput && this.hiddenInput.value === this.getValue()) {
                    return;
                }

                this.onChange();
            }),
            ...registerCommands(this.editor),
        );

        this.registerActionsToolbar()
        queueMicrotask(() => {
            this.isInitializing = false;
            this.suppressNextChange = false;
        });
    }

    public destroy(): void {
        this.unregister?.();
        this.unregister = null;

        this.editor?.setRootElement(null);
        this.editor = null;

        this.actionsToolbar.innerHTML = ''
    }

    /**
     * Returns the actions available for this editor
     */
    public getActions() : Array<Action> {
        return Object.values(ACTIONS)
    }

    /**
     * Registers the actions toolbar
     */
    private registerActionsToolbar() {
        const actions = this.getActions()
        this.actionsToolbar = this.element.querySelector('#actions-toolbar') as HTMLElement;

        actions.map((action)=>{
            let actionBtn = document.createElement('button')
            actionBtn.type = 'button'
            actionBtn.tabIndex = -1
            actionBtn.className = 'btn btn-secondary btn-sm'
            actionBtn.innerHTML = `<i class='${action.icon}'></i> ${action.label}`
            actionBtn.addEventListener('mousedown', (event) => {
                event.preventDefault()
            })
            actionBtn.addEventListener('click', ()=> {
                action.handler(this.editor)
                this.editor?.focus()
            })

            this.actionsToolbar.appendChild(actionBtn)
        })
    }
    
    public override onChange(): void {
        if (this.hiddenInput) {
            this.hiddenInput.value = this.getValue();
        }

        super.onChange();
    }

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
                root.append(...nodes);
            } else {
                root.append($createParagraphNode());
            }
        }, { discrete: true });
        if (this.hiddenInput) {
            this.hiddenInput.value = this.getValue();
        }
    }

    public getValue(): string {
        return this.toHtml()
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

}
