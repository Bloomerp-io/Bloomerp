import BaseComponent from "../BaseComponent";
import { getContextMenu, type ContextMenuItem } from "../../utils/contextMenu";
import {
    COMMAND_PRIORITY_LOW,
    KEY_DOWN_COMMAND,
    $createParagraphNode,
    $getRoot,
    $getSelection,
    $isRangeSelection,
    createEditor,
    type LexicalEditor,
} from "lexical";
import { $generateHtmlFromNodes, $generateNodesFromDOM } from "@lexical/html";
import { HeadingNode, $createHeadingNode } from "@lexical/rich-text";
import {
    INSERT_ORDERED_LIST_COMMAND,
    INSERT_UNORDERED_LIST_COMMAND,
    ListItemNode,
    ListNode,
} from "@lexical/list";
import { LinkNode, TOGGLE_LINK_COMMAND } from "@lexical/link";
import { $setBlocksType } from "@lexical/selection";

type MentionUser = {
    id?: number | string;
    name?: string;
    username?: string;
    display_name?: string;
    email?: string;
};

export default class TextEditor extends BaseComponent {
    private editor: LexicalEditor | null = null;
    private editorBody: HTMLDivElement | null = null;
    private inputElement: HTMLInputElement | HTMLTextAreaElement | null = null;
    private placeholderElement: HTMLDivElement | null = null;
    private cleanupHandlers: Array<() => void> = [];
    private menuId: string;

    constructor(element?: HTMLElement) {
        super(element);
        this.menuId = `bloomerp-text-editor-menu-${Math.random().toString(36).slice(2, 10)}`;
    }

    public initialize(): void {
        if (!this.element) return;

        this.editorBody = this.element.querySelector<HTMLDivElement>("[data-text-editor-body]");
        this.inputElement = this.element.querySelector<HTMLInputElement | HTMLTextAreaElement>(
            "[data-text-editor-input]"
        );

        if (!this.editorBody) {
            console.warn("TextEditor: data-text-editor-body not found in DOM. Ensure the template provides it.");
            return;
        }

        const styling = this.element.getAttribute("data-styling") ?? "";
        this.applyStylingClasses(styling, this.editorBody);

        this.setupPlaceholder();

        const isDisabled = this.element.getAttribute("data-disabled") === "true";

        this.editor = createEditor({
            namespace: "BloomerpTextEditor",
            editable: !isDisabled,
            nodes: [HeadingNode, ListNode, ListItemNode, LinkNode],
            onError: (error) => {
                console.error("Lexical error", error);
            },
        });

        this.editor.setRootElement(this.editorBody);
        this.editorBody.setAttribute("contenteditable", String(!isDisabled));

        const initialValue = this.inputElement?.value ?? "";
        if (initialValue.trim().length > 0) {
            this.setEditorContentFromHtml(initialValue);
        } else {
            this.ensureDefaultParagraph();
        }

        this.registerListeners();
    }

    public destroy(): void {
        this.cleanupHandlers.forEach((cleanup) => cleanup());
        this.cleanupHandlers = [];
        this.editor?.setRootElement(null);
        this.editor = null;
    }

    private setupPlaceholder(): void {
        if (!this.element || !this.editorBody) return;

        const placeholderText = this.element.getAttribute("data-placeholder") ?? "";
        if (!placeholderText) return;

        this.element.classList.add("relative");

        const placeholder = document.createElement("div");
        placeholder.className =
            "pointer-events-none absolute left-3 top-2 text-sm text-gray-400 select-none";
        placeholder.textContent = placeholderText;
        this.element.appendChild(placeholder);
        this.placeholderElement = placeholder;
    }

    private registerListeners(): void {
        if (!this.editor) return;

        const removeUpdateListener = this.editor.registerUpdateListener(({ editorState }) => {
            if (this.inputElement) {
                const html = editorState.read(() => $generateHtmlFromNodes(this.editor!));
                this.inputElement.value = html;
            }
            this.syncPlaceholder(editorState);
        });

        const removeKeyDownListener = this.editor.registerCommand(
            KEY_DOWN_COMMAND,
            (event) => {
                if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
                    event.preventDefault();
                    this.openSlashMenu();
                    return true;
                }

                if (event.key === "@" && !event.metaKey && !event.ctrlKey && !event.altKey) {
                    event.preventDefault();
                    void this.openMentionMenu();
                    return true;
                }

                return false;
            },
            COMMAND_PRIORITY_LOW
        );

        this.cleanupHandlers.push(removeUpdateListener, removeKeyDownListener);
    }

    private syncPlaceholder(editorState?: { read: <T>(fn: () => T) => T }): void {
        if (!this.placeholderElement || !this.editor) return;

        const isEmpty = (editorState ?? this.editor.getEditorState()).read(() => {
            const root = $getRoot();
            return root.getTextContent().replace(/\u200b/g, "").trim().length === 0;
        });

        this.placeholderElement.classList.toggle("hidden", !isEmpty);
    }

    private ensureDefaultParagraph(): void {
        if (!this.editor) return;
        this.editor.update(() => {
            const root = $getRoot();
            if (root.getChildrenSize() === 0) {
                root.append($createParagraphNode());
            }
        });
    }

    private setEditorContentFromHtml(html: string): void {
        if (!this.editor) return;
        this.editor.update(() => {
            const parser = new DOMParser();
            const dom = parser.parseFromString(html, "text/html");
            const nodes = $generateNodesFromDOM(this.editor!, dom);
            const root = $getRoot();
            root.clear();
            if (nodes.length > 0) {
                root.append(...nodes);
            } else {
                root.append($createParagraphNode());
            }
        });
    }

    private applyStylingClasses(styling: string, target: HTMLElement): void {
        if (!styling.trim()) return;
        const classes = styling.split(/\s+/).filter(Boolean);
        if (classes.length > 0) {
            target.classList.add(...classes);
        }
    }

    private getCaretPoint(): { x: number; y: number } {
        const selection = window.getSelection();
        if (selection && selection.rangeCount > 0) {
            const range = selection.getRangeAt(0);
            const rect = range.getBoundingClientRect();
            if (rect && (rect.left || rect.top)) {
                return { x: rect.left, y: rect.bottom };
            }
        }

        const fallbackRect = this.editorBody?.getBoundingClientRect();
        return {
            x: fallbackRect?.left ?? 0,
            y: fallbackRect?.bottom ?? 0,
        };
    }

    private showContextMenu(items: ContextMenuItem[]): void {
        if (!this.editorBody) return;
        const menu = getContextMenu(this.menuId);
        const { x, y } = this.getCaretPoint();
        const event = new MouseEvent("click", { clientX: x, clientY: y, bubbles: true });
        menu.show(event, this.editorBody, items);
    }

    private openSlashMenu(): void {
        if (!this.editor) return;

        const items: ContextMenuItem[] = [
            {
                label: "Paragraph",
                icon: "fa-solid fa-paragraph",
                onClick: () => this.setBlockType("paragraph"),
            },
            {
                label: "Heading 1",
                icon: "fa-solid fa-heading",
                onClick: () => this.setBlockType("h1"),
            },
            {
                label: "Heading 2",
                icon: "fa-solid fa-heading",
                onClick: () => this.setBlockType("h2"),
            },
            {
                label: "Heading 3",
                icon: "fa-solid fa-heading",
                onClick: () => this.setBlockType("h3"),
            },
            {
                label: "Bulleted list",
                icon: "fa-solid fa-list-ul",
                onClick: () => this.editor?.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined),
            },
            {
                label: "Numbered list",
                icon: "fa-solid fa-list-ol",
                onClick: () => this.editor?.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined),
            },
            {
                label: "Link",
                icon: "fa-solid fa-link",
                onClick: () => this.promptForLink(),
            },
        ];

        this.showContextMenu(items);
    }

    private setBlockType(type: "paragraph" | "h1" | "h2" | "h3"): void {
        if (!this.editor) return;
        this.editor.update(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection)) return;

            if (type === "paragraph") {
                $setBlocksType(selection, () => $createParagraphNode());
                return;
            }

            $setBlocksType(selection, () => $createHeadingNode(type));
        });
    }

    private promptForLink(): void {
        if (!this.editor) return;
        const url = window.prompt("Enter URL");
        if (!url) return;
        this.editor.dispatchCommand(TOGGLE_LINK_COMMAND, url);
    }

    private async openMentionMenu(): Promise<void> {
        const users = await this.fetchMentionUsers();
        const items: ContextMenuItem[] = [];

        if (users.length === 0) {
            items.push({
                label: "No users found",
                icon: "fa-solid fa-user",
                disabled: true,
                onClick: () => {},
            });
        } else {
            for (const user of users) {
                const label =
                    user.display_name || user.name || user.username || user.email || String(user.id ?? "User");

                items.push({
                    label,
                    icon: "fa-solid fa-user",
                    onClick: () => this.insertMention(label),
                });
            }
        }

        this.showContextMenu(items);
    }

    private async fetchMentionUsers(): Promise<MentionUser[]> {
        try {
            const response = await fetch("/api/users");
            if (!response.ok) return [];
            const data = await response.json();

            if (Array.isArray(data)) {
                return data;
            }

            if (Array.isArray(data?.results)) {
                return data.results;
            }

            if (Array.isArray(data?.data)) {
                return data.data;
            }

            return [];
        } catch (error) {
            console.error("Failed to load mention users", error);
            return [];
        }
    }

    private insertMention(label: string): void {
        if (!this.editor) return;
        this.editor.update(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection)) return;
            selection.insertText(`@${label} `);
        });
    }
}
