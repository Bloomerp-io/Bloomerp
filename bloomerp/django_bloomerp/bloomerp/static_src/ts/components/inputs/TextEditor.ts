import BaseComponent from "../BaseComponent";

import {
    $getRoot,
    $getSelection,
    COMMAND_PRIORITY_NORMAL,
    createEditor,
    type LexicalEditor,
    KEY_DOWN_COMMAND,
    $createParagraphNode,
    $getNodeByKey,
    $isRangeSelection,
    $isTextNode,
    $createTextNode,
} from "lexical";
import { $generateNodesFromDOM } from "@lexical/html";
import { $createHeadingNode, HeadingNode, registerRichText } from "@lexical/rich-text";
import {
    $createListItemNode,
    $createListNode,
    $isListItemNode,
    $isListNode,
    INDENT_LIST_COMMAND,
    ListItemNode,
    ListNode,
    OUTDENT_LIST_COMMAND,
    INSERT_UNORDERED_LIST_COMMAND,
    REMOVE_LIST_COMMAND,
} from "@lexical/list";
import { LinkNode } from "@lexical/link";
import { ContextMenuController, getContextMenu, type ContextMenuItem } from "../../utils/contextMenu";


type CommandMenuType = 'slash' | 'mention';

type CommandMenuState = {
    type: CommandMenuType | null;
    triggerNodeKey: string | null;
    triggerOffset: number | null;
    query: string;
    requestId: number;
};

type CommandDefinition = {
    id: string;
    label: string;
    icon?: string;
    keywords?: string[];
    onSelect: (editor: LexicalEditor) => void;
};

const SLASH_COMMANDS: CommandDefinition[] = [
    {
        id: 'heading-1',
        label: 'Heading 1',
        icon: 'fa-solid fa-heading',
        keywords: ['h1', 'heading'],
        onSelect: (editor) => {
            editor.update(() => {
                const heading = $createHeadingNode('h1');
                heading.append($createTextNode(''));
                TextEditor.insertBlockNode(heading);
            });
        },
    },
    {
        id: 'heading-2',
        label: 'Heading 2',
        icon: 'fa-solid fa-heading',
        keywords: ['h2', 'heading'],
        onSelect: (editor) => {
            editor.update(() => {
                const heading = $createHeadingNode('h2');
                heading.append($createTextNode(''));
                TextEditor.insertBlockNode(heading);
            });
        },
    },
    {
        id: 'heading-3',
        label: 'Heading 3',
        icon: 'fa-solid fa-heading',
        keywords: ['h3', 'heading'],
        onSelect: (editor) => {
            editor.update(() => {
                const heading = $createHeadingNode('h3');
                heading.append($createTextNode(''));
                TextEditor.insertBlockNode(heading);
            });
        },
    },
    {
        id: 'paragraph',
        label: 'Text',
        icon: 'fa-solid fa-paragraph',
        keywords: ['text', 'paragraph'],
        onSelect: (editor) => {
            editor.update(() => {
                const paragraph = $createParagraphNode();
                paragraph.append($createTextNode(''));
                TextEditor.insertBlockNode(paragraph);
            });
        },
    },
    {
        id: 'bulleted-list',
        label: 'Bulleted list',
        icon: 'fa-solid fa-list',
        keywords: ['bullet', 'list', 'ul'],
        onSelect: (editor) => {
            editor.update(() => {
                const list = $createListNode('bullet');
                const item = $createListItemNode();
                const paragraph = $createParagraphNode();
                paragraph.append($createTextNode(''));
                item.append(paragraph);
                list.append(item);
                TextEditor.insertBlockNode(list);
            });
        },
    },
    {
        id: 'numbered-list',
        label: 'Numbered list',
        icon: 'fa-solid fa-list-ol',
        keywords: ['number', 'list', 'ol'],
        onSelect: (editor) => {
            editor.update(() => {
                const list = $createListNode('number');
                const item = $createListItemNode();
                const paragraph = $createParagraphNode();
                paragraph.append($createTextNode(''));
                item.append(paragraph);
                list.append(item);
                TextEditor.insertBlockNode(list);
            });
        },
    },
    {
        id: 'todo-list',
        label: 'Todo list',
        icon: 'fa-solid fa-list-check',
        keywords: ['todo', 'check', 'task'],
        onSelect: (editor) => {
            editor.update(() => {
                const list = $createListNode('check');
                const item = $createListItemNode();
                const paragraph = $createParagraphNode();
                paragraph.append($createTextNode(''));
                item.append(paragraph);
                list.append(item);
                TextEditor.insertBlockNode(list);
            });
        },
    },
    {
        id: 'dummy-action',
        label: 'Dummy action',
        icon: 'fa-solid fa-wand-magic-sparkles',
        keywords: ['dummy', 'example'],
        onSelect: () => {
            // Placeholder action for future commands.
        },
    },
];

const MENTION_PLACEHOLDERS = [
    { id: 'user-1', label: 'Ada Lovelace', icon: 'fa-solid fa-user' },
    { id: 'user-2', label: 'Grace Hopper', icon: 'fa-solid fa-user' },
    { id: 'user-3', label: 'Alan Turing', icon: 'fa-solid fa-user' },
    { id: 'user-4', label: 'Linus Torvalds', icon: 'fa-solid fa-user' },
];


export default class TextEditor extends BaseComponent {
    private editor: LexicalEditor | null = null;
    private editorBody: HTMLDivElement | null = null;
    private contextMenu:ContextMenuController;
    private commandMenuState: CommandMenuState = {
        type: null,
        triggerNodeKey: null,
        triggerOffset: null,
        query: '',
        requestId: 0,
    };

    public initialize(): void {
        // Get the editor body element
        this.editorBody = this.element.querySelector('[data-text-editor-body]') as HTMLDivElement;

        // Create config
        const editorConfig = {
            namespace: 'TextEditor',
            onError(error: Error) {
                throw error;
            },
            theme: {
                paragraph: 'text-md',
                heading: {
                    h1: 'text-4xl font-bold',
                    h2: 'text-2xl font-bold',
                    h3: 'text-2xl font-bold',
                },
                list: {
                    ul: 'list-disc list-inside',
                    ol: 'list-decimal list-inside',
                    listitem: 'my-1',
                    nested: {
                        listitem: 'ml-6',
                    },
                },
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
        this.registerListBehavior();

        registerRichText(this.editor);

        // Initialize state
        const input = this.element.querySelector('input[type="hidden"]') as HTMLInputElement;
        const initialValue = input ? input.value : '';
        this.initState(initialValue);

        // Create context menu
        this.contextMenu = getContextMenu('text-editor-context-menu');

    }

    public destroy(): void {
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
                if (!this.isTriggerAtStart('/')) return false;

                queueMicrotask(() => {
                    this.activateCommandMenu('slash');
                });

                return false;
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
                if (!this.isTriggerAtStart('@')) return false;

                queueMicrotask(() => {
                    this.activateCommandMenu('mention');
                });

                return false;
            },
            COMMAND_PRIORITY_NORMAL
        )


    }

    private registerListBehavior(): void {
        if (!this.editor) return;

        this.editor.registerCommand(
            KEY_DOWN_COMMAND,
            (event) => {
                if (!this.editor) return false;

                if (this.commandMenuState.type) {
                    if (['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(event.key)) {
                        event.preventDefault();
                        event.stopPropagation();
                        if (event.key === 'Escape') {
                            this.deactivateCommandMenu();
                        }
                        return true;
                    }
                }

                if (event.key === 'Tab') {
                    const isInList = this.isSelectionInList();
                    if (isInList) {
                        event.preventDefault();
                        event.stopPropagation();
                        this.editor.dispatchCommand(INDENT_LIST_COMMAND, undefined);
                        return true;
                    }
                }

                if (event.key === 'Enter') {
                    const listInfo = this.getListInfo();
                    if (listInfo.inList && listInfo.isEmpty) {
                        event.preventDefault();
                        event.stopPropagation();
                        if (listInfo.depth > 1) {
                            this.editor.dispatchCommand(OUTDENT_LIST_COMMAND, undefined);
                        } else {
                            this.editor.dispatchCommand(REMOVE_LIST_COMMAND, undefined);
                        }
                        return true;
                    }
                }

                if (event.key === ' ' || event.key === 'Spacebar') {
                    const shouldConvert = this.shouldConvertDashToList();
                    if (shouldConvert) {
                        event.preventDefault();
                        event.stopPropagation();
                        this.editor.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined);
                        return true;
                    }
                }

                if (this.commandMenuState.type) {
                    if (event.key === 'Backspace') {
                        queueMicrotask(() => this.refreshCommandMenu());
                        return false;
                    }
                    if (event.key === 'Delete') {
                        queueMicrotask(() => this.refreshCommandMenu());
                        return false;
                    }
                    if (event.key.length === 1) {
                        if (event.key === ' ') {
                            this.deactivateCommandMenu();
                            return false;
                        }
                        queueMicrotask(() => this.refreshCommandMenu());
                        return false;
                    }
                }

                return false;
            },
            COMMAND_PRIORITY_NORMAL
        )
    }

    private isTriggerAtStart(trigger: '/' | '@'): boolean {
        if (!this.editor) return false;
        let isValid = false;

        this.editor.getEditorState().read(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection) || !selection.isCollapsed()) return;

            const node = selection.anchor.getNode();
            if (!$isTextNode(node)) return;

            const offset = selection.anchor.offset;
            const text = node.getTextContent();
            const before = text.slice(0, offset);
            if (before.length === 0 || /\s$/.test(before)) {
                isValid = true;
                return;
            }

            if (before.endsWith(trigger)) {
                const charBefore = before.slice(0, -1);
                if (charBefore.length === 0 || /\s$/.test(charBefore)) {
                    isValid = true;
                }
            }
        });

        return isValid;
    }

    private activateCommandMenu(type: CommandMenuType): void {
        if (!this.editor || !this.editorBody) return;

        this.commandMenuState.type = type;
        this.refreshCommandMenu();
    }

    private deactivateCommandMenu(): void {
        this.commandMenuState = {
            type: null,
            triggerNodeKey: null,
            triggerOffset: null,
            query: '',
            requestId: this.commandMenuState.requestId + 1,
        };
        this.contextMenu.hide();
    }

    private refreshCommandMenu(): void {
        if (!this.editor || !this.commandMenuState.type) return;

        const triggerChar = this.commandMenuState.type === 'slash' ? '/' : '@';
        const info = this.getTriggerInfo(triggerChar);

        if (!info) {
            this.deactivateCommandMenu();
            return;
        }

        this.commandMenuState.triggerNodeKey = info.nodeKey;
        this.commandMenuState.triggerOffset = info.triggerOffset;
        this.commandMenuState.query = info.query;
        this.commandMenuState.requestId += 1;
        const requestId = this.commandMenuState.requestId;

        const position = this.getMenuPosition();
        if (!position) return;

        if (this.commandMenuState.type === 'slash') {
            const items = this.getSlashMenuItems(info.query);
            this.showMenuAt(position, items);
            return;
        }

        void this.getMentionMenuItems(info.query).then((items) => {
            if (this.commandMenuState.requestId !== requestId) return;
            if (!this.commandMenuState.type) return;
            this.showMenuAt(position, items);
        });
    }

    private getTriggerInfo(trigger: '/' | '@'): { nodeKey: string; triggerOffset: number; query: string } | null {
        if (!this.editor) return null;

        let info: { nodeKey: string; triggerOffset: number; query: string } | null = null;

        this.editor.getEditorState().read(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection) || !selection.isCollapsed()) return;

            const node = selection.anchor.getNode();
            if (!$isTextNode(node)) return;

            const offset = selection.anchor.offset;
            const textBefore = node.getTextContent().slice(0, offset);
            const match = textBefore.match(/(^|\s)([\/@][^\s]*)$/);
            if (!match) return;

            const word = match[2];
            if (!word.startsWith(trigger)) return;

            info = {
                nodeKey: node.getKey(),
                triggerOffset: textBefore.length - word.length,
                query: word.slice(1),
            };
        });

        return info;
    }

    private getMenuPosition(): { x: number; y: number } | null {
        if (!this.editorBody) return null;
        const selection = window.getSelection();
        const range = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
        const rect = range ? range.getBoundingClientRect() : this.editorBody.getBoundingClientRect();

        return {
            x: rect.left,
            y: rect.bottom,
        };
    }

    private showMenuAt(position: { x: number; y: number }, items: ContextMenuItem[]): void {
        if (!this.editorBody) return;
        if (items.length === 0) {
            this.contextMenu.hide();
            return;
        }
        const clickEvent = new MouseEvent('click', {
            clientX: position.x,
            clientY: position.y,
            bubbles: true,
            cancelable: true,
            view: window,
        });

        this.contextMenu.show(clickEvent, this.editorBody, items);
    }

    private getSlashMenuItems(query: string): ContextMenuItem[] {
        const normalized = query.trim().toLowerCase();
        const items = normalized
            ? SLASH_COMMANDS.filter((command) => {
                  const haystack = [command.label, ...(command.keywords ?? [])]
                      .join(' ')
                      .toLowerCase();
                  return haystack.includes(normalized);
              })
            : SLASH_COMMANDS;

        return items.map((command) => ({
            label: command.label,
            icon: command.icon,
            onClick: () => {
                if (!this.editor) return;
                this.editor.update(() => {
                    this.removeTriggerText();
                });
                command.onSelect(this.editor);
                this.deactivateCommandMenu();
            },
        }));
    }

    private async getMentionMenuItems(query: string): Promise<ContextMenuItem[]> {
        const results = await this.fetchMentionResults(query);

        return results.map((result) => ({
            label: result.label,
            icon: result.icon,
            onClick: () => {
                if (!this.editor) return;
                this.editor.update(() => {
                    this.replaceTriggerText(`@${result.label} `);
                });
                this.deactivateCommandMenu();
            },
        }));
    }

    private async fetchMentionResults(query: string): Promise<{ id: string; label: string; icon?: string }[]> {
        const normalized = query.trim().toLowerCase();
        if (!normalized) {
            return MENTION_PLACEHOLDERS;
        }

        return MENTION_PLACEHOLDERS.filter((item) =>
            item.label.toLowerCase().includes(normalized)
        );
    }

    private removeTriggerText(): void {
        this.replaceTriggerText('');
    }

    private replaceTriggerText(replacement: string): void {
        if (!this.editor) return;
        const { triggerNodeKey, triggerOffset } = this.commandMenuState;
        if (!triggerNodeKey || triggerOffset === null) return;

        const node = $getNodeByKey(triggerNodeKey);
        if (!$isTextNode(node)) return;
        const endOffset = Math.min(
            triggerOffset + 1 + this.commandMenuState.query.length,
            node.getTextContent().length
        );

        const text = node.getTextContent();
        const before = text.slice(0, triggerOffset);
        const after = text.slice(endOffset);
        node.setTextContent(`${before}${replacement}${after}`);
        const newOffset = before.length + replacement.length;
        node.select(newOffset, newOffset);
    }

    private static insertBlockNode(node: ListNode | HeadingNode | ReturnType<typeof $createParagraphNode>): void {
        const selection = $getSelection();
        if (!$isRangeSelection(selection)) return;
        const anchorNode = selection.anchor.getNode();
        const topLevel = anchorNode.getTopLevelElementOrThrow();
        topLevel.insertAfter(node);
        if ($isListNode(node)) {
            const firstItem = node.getFirstChild();
            if ($isListItemNode(firstItem)) {
                firstItem.selectStart();
                return;
            }
        }
        node.selectStart();
    }

    private isSelectionInList(): boolean {
        if (!this.editor) return false;
        let inList = false;

        this.editor.getEditorState().read(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection)) return;
            const node = selection.anchor.getNode();
            let current: typeof node | null = node;
            while (current) {
                if ($isListItemNode(current)) {
                    inList = true;
                    return;
                }
                current = current.getParent();
            }
        });

        return inList;
    }

    private getListInfo(): { inList: boolean; isEmpty: boolean; depth: number } {
        if (!this.editor) return { inList: false, isEmpty: false, depth: 0 };

        let info = { inList: false, isEmpty: false, depth: 0 };

        this.editor.getEditorState().read(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection)) return;

            const node = selection.anchor.getNode();
            let current: typeof node | null = node;
            let listItem: ListItemNode | null = null;

            while (current) {
                if ($isListItemNode(current)) {
                    listItem = current;
                    break;
                }
                current = current.getParent();
            }

            if (!listItem) return;

            info.inList = true;
            info.isEmpty = listItem.getTextContent().trim() === '';

            let depth = 0;
            let parent = listItem.getParent();
            while (parent && $isListNode(parent)) {
                depth += 1;
                const maybeListItem = parent.getParent();
                if (!maybeListItem || !$isListItemNode(maybeListItem)) break;
                parent = maybeListItem.getParent();
            }
            info.depth = depth;
        });

        return info;
    }

    private shouldConvertDashToList(): boolean {
        if (!this.editor) return false;
        let shouldConvert = false;

        this.editor.update(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection) || !selection.isCollapsed()) return;

            const node = selection.anchor.getNode();
            if (!$isTextNode(node)) return;

            const text = node.getTextContent();
            const offset = selection.anchor.offset;
            if (text.trim() !== '-' || offset !== text.length) return;

            node.setTextContent('');
            shouldConvert = true;
        });

        return shouldConvert;
    }
}
