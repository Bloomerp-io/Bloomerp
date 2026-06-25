import { Command, COMMANDS, registerCommands } from "./commands";
import { ImageNode } from "./nodes/ImageNode";
import { registerHtmlBehavior } from "./utils/htmlBehavior";
import { registerImageBehavior } from "./utils/imageBehavior";
import { registerTableBehavior } from "./utils/tableBehavior";
import { $generateHtmlFromNodes, $generateNodesFromDOM } from "@lexical/html";

import {
    $isBlockElementNode,
    $createParagraphNode,
    $getRoot,
    $getSelection,
    $insertNodes,
    $isInlineElementOrDecoratorNode,
    $isRangeSelection,
    $isTextNode,
    COMMAND_PRIORITY_LOW,
    createEditor,
    LexicalEditor,
    type LexicalNode,
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
import { parseBoolean } from "../../utils/booleans";

import HtmlNode from "./nodes/HtmlNode";


export class BloomerpTextEditor extends BaseWidget {
    public editor: LexicalEditor | null = null;
    private unregister: (() => void) | null = null;
    private commands: Array<Command> = [];
    private actions: Array<Action> = [];
    
    private actionsToolbar: HTMLElement | null = null;
    private hiddenInput:HTMLInputElement;
    private suppressNextChange: boolean = false;
    private isInitializing: boolean = false;
    private editorId:string;
    private includeToolbar:boolean = true;
    private editorRootSelector:string = '';

    // Extra commands
    public slashExtraActions:string[] = []
    public rangeExtraActions:string[] = []

    // Styling for the editor
    public styling: string | null = null;
    public overrideDefaultStyling: boolean = false;

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

        // Get the styling from the data attribute
        const styling = this.element.dataset.styling ?? null;
        this.setStyling(styling);

        // Get the override styling from the data attribute
        const overrideDefaultStyling = this.element.dataset.overrideDefaultStyling ?? 'False';
        this.overrideDefaultStyling = parseBoolean(overrideDefaultStyling, false);

        this.editor = createEditor({
            namespace: "BloomerpTextEditor",
            theme: {
                paragraph: !this.overrideDefaultStyling ? 'text-md' : '',
                heading: {
                    h1: !this.overrideDefaultStyling ? 'text-4xl font-bold mb-2' : '',
                    h2: !this.overrideDefaultStyling ? 'text-2xl font-bold mb-1' : '',
                    h3: !this.overrideDefaultStyling ? 'text-2xl font-bold' : '',
                },
                list: {
                    ul: !this.overrideDefaultStyling ? 'list-disc list-inside pl-4' : '',
                    ol: !this.overrideDefaultStyling ? 'list-decimal list-inside pl-4' : '',
                },
                table: !this.overrideDefaultStyling ? 'my-3 w-full table-fixed border-collapse overflow-hidden rounded-lg border border-gray-200 text-left' : '',
                tableRow: !this.overrideDefaultStyling ? 'border-b border-gray-200 last:border-b-0' : '',
                tableCell: !this.overrideDefaultStyling ? 'min-w-24 border-r border-gray-200 px-1 py-1 align-top text-sm outline-none last:border-r-0' : '',
                tableCellHeader: !this.overrideDefaultStyling ? 'bg-gray-100 font-medium' : '',
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
                ImageNode,
                HtmlNode,
            ],
            onError: (error: Error) => {
                throw error;
            },
        });
        this.includeToolbar = parseBoolean(this.element.dataset.includeToolbar, true);

        this.editor.setRootElement(editorRef);
        this.isInitializing = true;
        this.setValue(this.hiddenInput?.value ?? '', false);

        const historyState = createEmptyHistoryState();

        this.unregister = mergeRegister(
            registerRichText(this.editor),
            registerHistory(this.editor, historyState, 300),
            registerTableBehavior(this.editor, this.element),
            registerHtmlBehavior(this.editor),
            registerImageBehavior(this.editor, this.element),
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
            ...registerCommands(this),
            ...this.commands.map(({ command, handler, priority = COMMAND_PRIORITY_LOW }) => (
                this.editor.registerCommand(command, (event) => handler.call(this, event), priority)
            )),
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

        if (this.actionsToolbar) {
            this.actionsToolbar.innerHTML = ''
            this.actionsToolbar = null;
        }
    }

    /**
     * Returns the actions available for this editor
     */
    public getActions() : Array<Action> {
        return Array.from(new Set([...Object.values(ACTIONS), ...this.actions]))
    }

    /**
     * Registers the actions toolbar
     */
    private registerActionsToolbar() {
        const actions = this.getActions()
        let actionsToolbarId = this.element.dataset.actionsToolbarSectionId;
        
        const standardToolbar = (!actionsToolbarId && this.includeToolbar)
        if (standardToolbar) {
            actionsToolbarId = 'actions-toolbar-' + this.editorId;
        }

        if (!actionsToolbarId) return;

        this.actionsToolbar = document.getElementById(actionsToolbarId) as HTMLElement | null;
        if (!this.actionsToolbar) return;

        this.actionsToolbar.innerHTML = ''


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
                action.handler(this)
                this.editor?.focus()
            })

            this.actionsToolbar.appendChild(actionBtn)
        })


        if (standardToolbar) {
            this.actionsToolbar.className = 'flex mb-4 gap-2 overflow-x-scroll'
        }
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

    private isRootCompatibleImportedNode(node: LexicalNode): boolean {
        const type = node.getType();
        return ['paragraph', 'heading', 'quote', 'list', 'table'].includes(type) || $isBlockElementNode(node);
    }

    public getValue(): string {
        return this.toHtml()
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
    public registerAction(action:Action, key:string, addToSlash:boolean=false, addToRange:boolean=false) {
        this.actions.push(action);

        if (this.actionsToolbar) {
            this.registerActionsToolbar();
        }

        // Add command to repo
        ACTIONS[key] = action

        if (addToSlash) {this.slashExtraActions.push(key)}
        if (addToRange) {this.rangeExtraActions.push(key)}
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

    private getDocumentResetStyling(): string {
        if (!this.editorRootSelector) {
            return '';
        }

        return `
:where(${this.editorRootSelector}, ${this.editorRootSelector} *) {
    all: revert;
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
