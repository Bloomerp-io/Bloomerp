import BaseComponent from "../BaseComponent";
import { registerCommands } from "./commands";

import {
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
import { Action, ACTIONS } from "./actions";

export class BloomerpTextEditor extends BaseComponent {
    private editor: LexicalEditor | null = null;
    private unregister: (() => void) | null = null;
    private button:HTMLButtonElement;
    private actionsToolbar:HTMLElement;

    public initialize(): void {
        const editorRef = this.element.querySelector("#editor") as HTMLElement | null;

        if (!editorRef) {
            throw new Error("Could not find #lexical-editor");
        }

        const editor = createEditor({
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
            },
            nodes: [
                HeadingNode, 
                QuoteNode,
                ListNode,
                ListItemNode,
                LinkNode,
            ],
            onError: (error: Error) => {
                throw error;
            },
        });
        this.button = this.element.querySelector('#h1-button')

        editor.setRootElement(editorRef);

        const historyState = createEmptyHistoryState();


        this.unregister = mergeRegister(
            registerRichText(editor),
            registerHistory(editor, historyState, 300),
            ...registerCommands(editor),
        );

        this.editor = editor;

        this.registerActionsToolbar()

    }

    public destroy(): void {
        this.unregister?.();
        this.unregister = null;

        this.editor?.setRootElement(null);
        this.editor = null;

        this.actionsToolbar.innerHTML = ''
    }

    public getActions() : Array<Action> {
        return Object.values(ACTIONS)
    }

    private registerActionsToolbar() {
        const actions = this.getActions()
        this.actionsToolbar = this.element.querySelector('#actions-toolbar') as HTMLElement;

        actions.map((action)=>{
            let actionBtn = document.createElement('button')
            actionBtn.className = 'btn btn-secondary btn-sm'
            actionBtn.innerHTML = `<i class='${action.icon}'></i> ${action.label}`
            actionBtn.addEventListener('click', ()=> {
                action.handler(this.editor)
            })

            this.actionsToolbar.appendChild(actionBtn)
        })
    }

    /**
     * 
     * @returns editor state in html
     */
    public toHtml() : string {
        return ''
    }
}
