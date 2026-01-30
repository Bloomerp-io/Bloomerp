import BaseComponent from "../BaseComponent";

import {
    $getRoot,
    $getSelection,
    COMMAND_PRIORITY_NORMAL,
    createEditor,
    type LexicalEditor,
    KEY_DOWN_COMMAND,
} from "lexical";
import { $generateNodesFromDOM } from "@lexical/html";
import { HeadingNode, registerRichText } from "@lexical/rich-text";
import {
    ListItemNode,
    ListNode,
} from "@lexical/list";
import { LinkNode } from "@lexical/link";
import { ContextMenuController, getContextMenu, type ContextMenuItem } from "../../utils/contextMenu";


interface ElementStylingDefintion {
    label: string;
    className: string;
    icon?: string; // FontAwesome icon class
    onClick?: (editor: LexicalEditor) => void;
    
}

const ElementStyling: Record<string, ElementStylingDefintion> = {
    H1: {
        label: 'Heading 1',
        className: 'text-3xl font-bold',
        icon: 'fa-solid fa-heading'
    },
    H2: {
        label: 'Heading 2',
        className: 'text-2xl font-bold',
        icon: 'fa-solid fa-heading',
    },
    H3: {
        label: 'Heading 3',
        className: 'text-xl font-bold',
        icon: 'fa-solid fa-heading',
    },
    P: {
        label: 'Paragraph',
        className: 'text-base',
        icon: 'fa-solid fa-paragraph',
    },
    UL: {
        label: 'Bullet List',
        className: 'list-disc list-inside',
        icon: 'fa-solid fa-list',
    },
    OL: {
        label: 'Numbered List',
        className: 'list-decimal list-inside',
        icon: 'fa-solid fa-list-ol',
    },
};


export default class TextEditor extends BaseComponent {
    private editor: LexicalEditor | null = null;
    private editorBody: HTMLDivElement | null = null;
    private unregisterSlashCommand: (() => void) | null = null;
    private contextMenu:ContextMenuController;

    public initialize(): void {
        // Get the editor body element
        this.editorBody = this.element.querySelector('[data-text-editor-body]') as HTMLDivElement;

        // Create config
        const editorConfig = {
            namespace: 'TextEditor',
            onError(error: Error) {
                throw error;
            },
            nodes: [
                HeadingNode,
                ListNode,
                ListItemNode,
                LinkNode,
            ],
        };

        // Create the editor
        this.editor = createEditor(editorConfig);

        // Set the root element
        this.editor.setRootElement(this.editorBody);

        // Init slash command
        this.registerSlashCommand();
        this.registerMentionCommand();

        registerRichText(this.editor);

        // Initialize state
        const input = this.element.querySelector('input[type="hidden"]') as HTMLInputElement;
        const initialValue = input ? input.value : '';
        this.initState(initialValue);

        // Create context menu
        this.contextMenu = getContextMenu('text-editor-context-menu');

    }

    public destroy(): void {
        if (this.unregisterSlashCommand) {
            this.unregisterSlashCommand();
            this.unregisterSlashCommand = null;
        }
    }
    

    public initState(value: string) : void {
        // Get the input
        
        const parser = new DOMParser();
        const dom = parser.parseFromString(value, 'text/html');

        this.editor!.update(() => {
            const root = $getRoot();
            root.clear();

            const nodes = $generateNodesFromDOM(this.editor, dom);
            root.append(...nodes);
        });
    }

    /**
     * Registers the slash command to open the context menu.
     */
    public registerSlashCommand() : void {
        if (!this.editor || !this.editorBody) return;

        // Register command
        this.editor.registerCommand(
            KEY_DOWN_COMMAND,
            (event) => {
                if (event.key !== '/') return false;

                // Calculate positioning
                const selection = window.getSelection();
                const range = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
                const rect = range ? range.getBoundingClientRect() : this.editorBody!.getBoundingClientRect();

                const clickEvent = new MouseEvent('click', {
                    clientX: rect.left,
                    clientY: rect.bottom,
                    bubbles: true,
                    cancelable: true,
                    view: window,
                });

                // Register 
                const items: ContextMenuItem[] = [];
                Object.entries(ElementStyling).forEach(([key, className]) => {
                    items.push({
                        label: key,
                        onClick: () => {
                            if (!this.editor) return;
                            this.editor.update(() => {
                                const selection = $getSelection();
                            });
                        },
                        icon: className.icon
                    });
                });

                this.contextMenu.show(clickEvent, this.editorBody!, items);
                return true;
            },
            COMMAND_PRIORITY_NORMAL
        )
    }

    /**
     * Registers the mention command to open the context menu.
     */
    private registerMentionCommand() : void {
        if (!this.editor || !this.editorBody) return;
        

        this.editor.registerCommand(
            KEY_DOWN_COMMAND,
            (event) => {
                if (event.key !== '@') return false;

                // Calculate positioning
                const selection = window.getSelection();
                const range = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
                const rect = range ? range.getBoundingClientRect() : this.editorBody!.getBoundingClientRect();

                const clickEvent = new MouseEvent('click', {
                    clientX: rect.left,
                    clientY: rect.bottom,
                    bubbles: true,
                    cancelable: true,
                    view: window,
                });

                // Register 
                const items: ContextMenuItem[] = [];
                Object.entries(ElementStyling).forEach(([key, className]) => {
                    items.push({
                        label: key,
                        onClick: () => {
                            if (!this.editor) return;
                            this.editor.update(() => {
                                const selection = $getSelection();
                            });
                        },
                        icon: className.icon
                    });
                });

                this.contextMenu.show(clickEvent, this.editorBody!, items);
                return true;
            },
            COMMAND_PRIORITY_NORMAL
        )


    }
}


