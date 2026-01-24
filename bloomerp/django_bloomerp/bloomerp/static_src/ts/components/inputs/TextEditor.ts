import BaseComponent from "../BaseComponent";
import { getContextMenu, type ContextMenuItem } from "../../utils/contextMenu";

type TextStyleKind = "block" | "inline";

interface TextStyleDefinition {
    name: string;
    icon: string;
    shortcut?: string | null; // Always starts with cmnd / cntrl
    tag: string; // HTML TAG
    kind: TextStyleKind;
    styles?: Record<string, string>;
}

const TextStyleDefinition = (definition: TextStyleDefinition): TextStyleDefinition => definition;

const TextStyle = {
    H1: TextStyleDefinition({
        name: "Heading 1",
        icon: "fa-solid fa-heading",
        shortcut: "cmd+shift+1",
        tag: "h1",
        kind: "block",
        styles: { 'font-size': '2.25rem', 'font-weight': '700', 'margin': '0 0 0.75rem 0' }
    }),
    H2: TextStyleDefinition({
        name: "Heading 2",
        icon: "fa-solid fa-heading",
        shortcut: "cmd+shift+2",
        tag: "h2",
        kind: "block",
        styles: { 'font-size': '1.75rem', 'font-weight': '600', 'margin': '0 0 0.6rem 0' }
    }),
    H3: TextStyleDefinition({
        name: "Heading 3",
        icon: "fa-solid fa-heading",
        shortcut: "cmd+shift+3",
        tag: "h3",
        kind: "block",
        styles: { 'font-size': '1.5rem', 'font-weight': '600', 'margin': '0 0 0.5rem 0' }
    }),
    PARAGRAPH: TextStyleDefinition({
        name: "Paragraph",
        icon: "fa-solid fa-paragraph",
        shortcut: "cmd+shift+0",
        tag: "p",
        kind: "block",
        styles: { 'font-size': '1rem', 'line-height': '1.6', 'margin': '0 0 1rem 0' }
    }),
    BULLETED_LIST: TextStyleDefinition({
        name: "Bulleted List",
        icon: "fa-solid fa-list-ul",
        shortcut: null,
        tag: "ul",
        kind: "block",
        styles: { 'margin': '0 0 1rem 0', 'padding-left': '1.25rem' }
    }),
    BOLD: TextStyleDefinition({
        name: "Bold",
        icon: "fa-solid fa-bold",
        shortcut: "cmd+b",
        tag: "strong",
        kind: "inline",
        styles: { 'font-weight': '700' }
    }),
    ITALIC: TextStyleDefinition({
        name: "Italic",
        icon: "fa-solid fa-italic",
        shortcut: "cmd+i",
        tag: "em",
        kind: "inline",
        styles: { 'font-style': 'italic' }
    }),
    UNDERLINE: TextStyleDefinition({
        name: "Underline",
        icon: "fa-solid fa-underline",
        shortcut: "cmd+u",
        tag: "u",
        kind: "inline",
        styles: { 'text-decoration': 'underline' }
    }),
    STRIKETHROUGH: TextStyleDefinition({
        name: "Strikethrough",
        icon: "fa-solid fa-strikethrough",
        shortcut: "cmd+shift+x",
        tag: "s",
        kind: "inline",
        styles: { 'text-decoration': 'line-through' }
    }),
    CODE: TextStyleDefinition({
        name: "Code",
        icon: "fa-solid fa-code",
        shortcut: "cmd+e",
        tag: "code",
        kind: "inline",
        styles: { 'font-family': 'SFMono-Regular, Menlo, Monaco, monospace', 'background-color': '#f6f8fa', 'padding': '2px 4px', 'border-radius': '4px' }
    }),
} as const;

type TextStyle = (typeof TextStyle)[keyof typeof TextStyle];

export default class TextEditor extends BaseComponent {
    private editorBody: HTMLDivElement | null = null;
    private inputElement: HTMLInputElement | HTMLTextAreaElement | null = null;
    private pendingSlashRemoval = false;
    private contextMenuMode: "slash" | "selection" | null = null;

    private onKeydownHandler: ((event: KeyboardEvent) => void) | null = null;
    private onInputHandler: ((event: Event) => void) | null = null;
    private onPasteHandler: ((event: ClipboardEvent) => void) | null = null;
    private onSelectionChangeHandler: (() => void) | null = null;
    private slashBlock: HTMLElement | null = null;
    private slashId: string | null = null;
    private onClickHandler: ((event: MouseEvent) => void) | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.editorBody = this.element.querySelector<HTMLDivElement>("[data-text-editor-body]");
        
        this.inputElement = this.element.querySelector<HTMLInputElement | HTMLTextAreaElement>(
            "[data-text-editor-input]"
        );

        
        // Set value
        if (this.inputElement?.value) {
            this.setText(this.inputElement.value);
        }

        this.ensureDefaultBlock();
        this.syncPlaceholder();
        this.updateEmptyState();
        this.setUpEventListeners();
    }

    // Handlers
    /**
     * Inserting the @ sign will trigger a dropdown at the point of
     * the cursor. The values will be populated by the users in the system.
     * (For)
     * 
     * If the user starts typing, it will send another htmx request as this queries
     * the user base. If the user adds enters on a particular element within the context
     * menu, it will add a new sort of element at cursor level. 
     */
    public onAt() : void {
        const editorBody = this.editorBody;
        if (!editorBody) return;

        const items: ContextMenuItem[] = [
            {
                label: "Search users...",
                icon: "fa-solid fa-user",
                disabled: true,
                onClick: () => {},
            },
        ];

        this.openContextMenuAtCaret(items);

        this.element?.dispatchEvent(
            new CustomEvent("text-editor:at", {
                detail: { editor: this },
            })
        );
    }


    /**
     * Returns the current text style of the cursor
     */
    public getTextStyle() : TextStyle {
        if (!this.editorBody) return TextStyle.PARAGRAPH;

        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0) return TextStyle.PARAGRAPH;

        const anchorNode = selection.anchorNode;
        if (!anchorNode) return TextStyle.PARAGRAPH;

        const anchorElement = anchorNode.nodeType === Node.ELEMENT_NODE
            ? (anchorNode as HTMLElement)
            : (anchorNode.parentElement ?? null);

        if (!anchorElement || !this.editorBody.contains(anchorElement)) {
            return TextStyle.PARAGRAPH;
        }

        const codeAncestor = anchorElement.closest("code");
        if (codeAncestor) return TextStyle.CODE;

        const block = this.getClosestBlock(anchorElement);
        if (block) {
            const tag = block.tagName.toLowerCase();
            if (tag === "h1") return TextStyle.H1;
            if (tag === "h2") return TextStyle.H2;
            if (tag === "h3") return TextStyle.H3;
        }

        return TextStyle.PARAGRAPH;
    }


    /**
     * Fetches all of the user ID's from the text and 
     * adds it as a list
     * @returns array of user ID's
     */
    public getTaggedUserIds() : Array<number> {
        return []
    }

    public destroy(): void {
        if (!this.editorBody) return;

        if (this.onKeydownHandler) {
            this.editorBody.removeEventListener("keydown", this.onKeydownHandler);
        }
        if (this.onInputHandler) {
            this.editorBody.removeEventListener("input", this.onInputHandler);
        }
        if (this.onPasteHandler) {
            this.editorBody.removeEventListener("paste", this.onPasteHandler);
        }
        if (this.onSelectionChangeHandler) {
            document.removeEventListener("selectionchange", this.onSelectionChangeHandler);
        }
        if (this.onClickHandler) {
            this.element?.removeEventListener("click", this.onClickHandler);
        }
    }

    public onHighlight() : void {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0) return;

        const range = selection.getRangeAt(0);
        if (selection.isCollapsed) return;

        if (!this.isRangeInsideEditor(range)) return;

        const rect = range.getBoundingClientRect();
        const items = this.getInlineStyleMenuItems();
        this.contextMenuMode = "selection";
        this.openContextMenuAtRect(items, rect);
    }

    public onSlash() : void {
        const selection = window.getSelection();
        console.log(selection)
        if (!selection || selection.rangeCount === 0) return;
        const range = selection.getRangeAt(0);
        if (!this.isRangeInsideEditor(range)) return;

        const anchorNode = selection.anchorNode;
        const anchorElement = anchorNode && anchorNode.nodeType === Node.ELEMENT_NODE
            ? (anchorNode as HTMLElement)
            : (anchorNode?.parentElement ?? null);

        const block = this.getClosestBlock(anchorElement);
        if (!block) return;

        // Clear any existing slash markers so multiple markers don't conflict
        const existing = this.element?.querySelectorAll('[data-slash-id]');
        existing?.forEach((el) => el.removeAttribute('data-slash-id'));

        // Remember the block where the slash was triggered so subsequent actions target it
        const id = `slash-${Date.now()}-${Math.floor(Math.random()*10000)}`;
        block.setAttribute('data-slash-id', id);
        this.slashId = id;
        this.slashBlock = block;
        this.pendingSlashRemoval = true;

        const items = this.getBlockStyleMenuItems();
        this.contextMenuMode = "slash";
        this.openContextMenuAtCaret(items);
    }

    public getText() : string {
        return this.editorBody.innerHTML;
    }

    public setText(text:string) : void {
        const editorBody = this.editorBody;
        
        editorBody.innerHTML = text;
        this.ensureDefaultBlock();
        this.updateEmptyState();
        this.updateInputValue();
    }

    public getHighlightedText() {
        const selection = window.getSelection();
        return selection?.toString() ?? "";
    }

    public setTextStyle(style:TextStyle) : void {
        const editorBody = this.editorBody;
        
        if (!editorBody.isConnected) return;

        if (style.kind === "block") {
            // Prefer operating on the block where the slash was triggered
            let targetBlock: HTMLElement | null = this.slashBlock ?? (() => {
                const selection = window.getSelection();
                const anchorNode = selection?.anchorNode ?? null;
                const anchorElement = anchorNode && anchorNode.nodeType === Node.ELEMENT_NODE
                    ? (anchorNode as HTMLElement)
                    : (anchorNode?.parentElement ?? null);
                return this.getClosestBlock(anchorElement);
            })();

            if (targetBlock) {
                // Special handling for bulleted list (scalable to other list types)
                if (style.tag === 'ul') {
                    // Resolve latest block
                    const blockToUse = this.slashId ? (this.element?.querySelector(`[data-slash-id="${this.slashId}"]`) as HTMLElement) ?? targetBlock : targetBlock;

                    // If already inside a UL, convert the LI back to paragraph
                    const inList = blockToUse.closest('ul');
                    if (inList) {
                        // find the relevant li
                        const li = blockToUse.tagName.toLowerCase() === 'li' ? blockToUse : blockToUse.closest('li');
                        if (li) {
                            const p = document.createElement('p');
                            p.innerHTML = li.innerHTML;
                            li.parentElement?.replaceChild(p, li);

                            // If UL is empty now, remove it
                            if (inList.childElementCount === 0) inList.remove();

                            // Place caret in paragraph
                            setTimeout(() => {
                                this.editorBody?.focus();
                                const sel = window.getSelection();
                                const r = document.createRange();
                                const firstText = Array.from(p.childNodes).find(n => n.nodeType === Node.TEXT_NODE) as Text | undefined;
                                if (firstText) {
                                    r.setStart(firstText, 0);
                                    r.collapse(true);
                                } else {
                                    r.selectNodeContents(p);
                                    r.collapse(false);
                                }
                                sel?.removeAllRanges();
                                sel?.addRange(r);
                                this.updateInputValue();
                            }, 0);

                            this.removeSlashTrigger(p);
                            this.pendingSlashRemoval = false;
                            if (this.slashId) {
                                const el = this.element?.querySelector(`[data-slash-id="${this.slashId}"]`);
                                if (el instanceof HTMLElement) el.removeAttribute('data-slash-id');
                                this.slashId = null;
                            }
                            this.slashBlock = null;
                            return;
                        }
                    }

                    // Not in a list: create one with a single LI
                    const ul = document.createElement('ul');
                    if (style.styles) this.applyStylesToElement(ul, style.styles);
                    const li = document.createElement('li');
                    li.innerHTML = blockToUse.innerHTML;
                    ul.appendChild(li);
                    blockToUse.parentElement?.replaceChild(ul, blockToUse);

                    // Place caret inside the new li
                    setTimeout(() => {
                        this.editorBody?.focus();
                        const sel = window.getSelection();
                        const r = document.createRange();
                        const textNode = document.createTextNode('\u200B');
                        li.appendChild(textNode);
                        r.setStart(textNode, 0);
                        r.collapse(true);
                        sel?.removeAllRanges();
                        sel?.addRange(r);
                        this.updateInputValue();

                        // Clean up marker
                        if (this.slashId) {
                            const el = this.element?.querySelector(`[data-slash-id="${this.slashId}"]`);
                            if (el instanceof HTMLElement) el.removeAttribute('data-slash-id');
                            this.slashId = null;
                        }
                        this.slashBlock = null;
                        this.pendingSlashRemoval = false;
                    }, 0);

                    this.removeSlashTrigger(ul);
                    return;
                }

                // Try to use execCommand so browser preserves selection behavior
                try {
                    // Resolve any latest reference to the target block
                    const resolvedById = this.slashId ? this.element?.querySelector(`[data-slash-id="${this.slashId}"]`) : null;
                    const blockToUse = (resolvedById && resolvedById instanceof HTMLElement) ? resolvedById as HTMLElement : targetBlock;

                    // Select the block contents so formatBlock applies to it
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(blockToUse);
                    range.collapse(true);
                    sel?.removeAllRanges();
                    sel?.addRange(range);

                    // Apply the block format
                    document.execCommand("formatBlock", false, style.tag);

                    // Find the resulting block element (try to locate by slash id first)
                    let newBlock: HTMLElement | null = null;
                    if (this.slashId) {
                        const resolved = this.element?.querySelector(`[data-slash-id="${this.slashId}"]`);
                        if (resolved && resolved instanceof HTMLElement) newBlock = resolved;
                    }
                    if (!newBlock) {
                        const anchorNode = sel?.anchorNode ?? null;
                        const anchorEl = anchorNode && anchorNode.nodeType === Node.ELEMENT_NODE
                            ? (anchorNode as HTMLElement)
                            : (anchorNode?.parentElement ?? null);
                        newBlock = this.getClosestBlock(anchorEl);
                    }

                    if (newBlock) {
                        // Remove slash from the block
                        this.removeSlashTrigger(newBlock);

                        // Apply styles if provided
                        if (style.styles) this.applyStylesToElement(newBlock, style.styles);

                        // Place caret inside the new block reliably
                        setTimeout(() => {
                            this.editorBody?.focus();
                            const sel2 = window.getSelection();
                            const r2 = document.createRange();

                            // If block empty, insert a zero-width text node so caret can sit there
                            if (newBlock.childNodes.length === 0 || newBlock.textContent?.trim().length === 0) {
                                const textNode = document.createTextNode('\u200B');
                                newBlock.appendChild(textNode);
                                r2.setStart(textNode, 0);
                                r2.collapse(true);
                            } else {
                                const firstText = Array.from(newBlock.childNodes).find(n => n.nodeType === Node.TEXT_NODE) as Text | undefined;
                                if (firstText) {
                                    r2.setStart(firstText, 0);
                                    r2.collapse(true);
                                } else {
                                    r2.selectNodeContents(newBlock);
                                    r2.collapse(false);
                                }
                            }

                            sel2?.removeAllRanges();
                            sel2?.addRange(r2);
                            this.updateInputValue();

                            // Clean up slash marker
                            if (this.slashId) {
                                const el = this.element?.querySelector(`[data-slash-id="${this.slashId}"]`);
                                if (el instanceof HTMLElement) el.removeAttribute('data-slash-id');
                                this.slashId = null;
                            }
                            this.slashBlock = null;
                            this.pendingSlashRemoval = false;
                        }, 0);

                        return;
                    }
                } catch (e) {
                    // If anything fails, fallback to a direct replacement
                    console.warn('setTextStyle fallback due to error', e);
                }
                // Fallback: replace the tag of the block safely and apply styles
                const newEl = document.createElement(style.tag);
                newEl.innerHTML = targetBlock.innerHTML;
                newEl.className = targetBlock.className;
                newEl.style.cssText = targetBlock.style.cssText;
                if (style.styles) this.applyStylesToElement(newEl, style.styles);
                targetBlock.parentElement?.replaceChild(newEl, targetBlock);

                // Place caret inside the new element
                setTimeout(() => {
                    this.editorBody?.focus();
                    const sel = window.getSelection();
                    const range = document.createRange();

                    if (newEl.childNodes.length === 0 || newEl.textContent?.trim().length === 0) {
                        const textNode = document.createTextNode('\u200B');
                        newEl.appendChild(textNode);
                        range.setStart(textNode, 0);
                        range.collapse(true);
                    } else {
                        const firstText = Array.from(newEl.childNodes).find(n => n.nodeType === Node.TEXT_NODE) as Text | undefined;
                        if (firstText) {
                            range.setStart(firstText, 0);
                            range.collapse(true);
                        } else {
                            range.selectNodeContents(newEl);
                            range.collapse(false);
                        }
                    }

                    sel?.removeAllRanges();
                    sel?.addRange(range);
                    this.updateInputValue();
                }, 0);

                // Remove the slash trigger from the original block (if it still exists)
                this.removeSlashTrigger(newEl);
            } else {
                // Fallback to execCommand
                document.execCommand("formatBlock", false, style.tag);
            }

            // Reset slash mode
            this.contextMenuMode = null;
            this.pendingSlashRemoval = false;
            this.slashBlock = null;
            return;
        }

        if (style === TextStyle.BOLD) {
            document.execCommand("bold");
            this.applyStyleToSelectionAncestor(style);
            this.contextMenuMode = null;
            return;
        }
        if (style === TextStyle.ITALIC) {
            document.execCommand("italic");
            this.applyStyleToSelectionAncestor(style);
            this.contextMenuMode = null;
            return;
        }
        if (style === TextStyle.UNDERLINE) {
            document.execCommand("underline");
            this.applyStyleToSelectionAncestor(style);
            this.contextMenuMode = null;
            return;
        }
        if (style === TextStyle.STRIKETHROUGH) {
            document.execCommand("strikeThrough");
            this.applyStyleToSelectionAncestor(style);
            this.contextMenuMode = null;
            return;
        }
        if (style === TextStyle.CODE) {
            this.wrapSelectionWithTag(style.tag);
            this.applyStyleToSelectionAncestor(style);
            this.contextMenuMode = null;
        }

        this.contextMenuMode = null;
    }

    private setUpEventListeners(): void {
        if (!this.editorBody) return;
        // Add keydown
        this.onKeydownHandler = (event: KeyboardEvent) => this.handleKeydown(event);


        this.onInputHandler = (event: Event) => {
            this.normalizeBlocks();
            this.updateEmptyState();
            this.updateInputValue();
            this.handleInput(event);
        };
        this.onPasteHandler = (event: ClipboardEvent) => this.handlePaste(event);
        this.onSelectionChangeHandler = () => {
            if (!this.editorBody) return;
            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0) return;
            const range = selection.getRangeAt(0);
            if (!this.isRangeInsideEditor(range)) return;
            if (!selection.isCollapsed) {
                this.onHighlight();
                return;
            }

            // If we were in selection mode, hide the context menu
            if (this.contextMenuMode === "selection") {
                getContextMenu().hide();
                this.contextMenuMode = null;
            }

            // If we were in slash mode and the selection collapsed or moved away,
            // hide the context menu and reset pendingSlashRemoval so user can trigger it again.
            if (this.contextMenuMode === "slash") {
                getContextMenu().hide();
                this.contextMenuMode = null;
                this.pendingSlashRemoval = false;
                // clear any remembered slash block and attribute
                if (this.slashId) {
                    const el = this.element?.querySelector(`[data-slash-id="${this.slashId}"]`);
                    if (el instanceof HTMLElement) el.removeAttribute('data-slash-id');
                    this.slashId = null;
                }
                this.slashBlock = null;
            }
        };

        this.onClickHandler = () => {
            if (!this.editorBody) return;
            if (document.activeElement !== this.editorBody) {
                this.editorBody.focus();
            }
        };

        this.editorBody.addEventListener("keydown", this.onKeydownHandler);
        this.editorBody.addEventListener("input", this.onInputHandler);
        this.editorBody.addEventListener("paste", this.onPasteHandler);
        document.addEventListener("selectionchange", this.onSelectionChangeHandler);
        this.element?.addEventListener("click", this.onClickHandler);
    }

    private handleKeydown(event: KeyboardEvent): void {
        if (!this.editorBody) return;

        if (event.target && this.element && !this.element.contains(event.target as Node)) return;

        const hasModifier = event.metaKey || event.ctrlKey;

        if (hasModifier) {
            const key = event.key.toLowerCase();
            if (key === "b") {
                event.preventDefault();
                this.setTextStyle(TextStyle.BOLD);
                return;
            }
            if (key === "i") {
                event.preventDefault();
                this.setTextStyle(TextStyle.ITALIC);
                return;
            }
            if (key === "u") {
                event.preventDefault();
                this.setTextStyle(TextStyle.UNDERLINE);
                return;
            }
            if (key === "e") {
                event.preventDefault();
                this.setTextStyle(TextStyle.CODE);
                return;
            }
            if (event.shiftKey && key === "1") {
                event.preventDefault();
                this.setTextStyle(TextStyle.H1);
                return;
            }
            if (event.shiftKey && key === "2") {
                event.preventDefault();
                this.setTextStyle(TextStyle.H2);
                return;
            }
            if (event.shiftKey && key === "3") {
                event.preventDefault();
                this.setTextStyle(TextStyle.H3);
                return;
            }
            if (event.shiftKey && key === "0") {
                event.preventDefault();
                this.setTextStyle(TextStyle.PARAGRAPH);
                return;
            }
        }

        // Pressing Enter inside a header should move focus to a new paragraph below
        if (event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0 && selection.isCollapsed) {
                const range = selection.getRangeAt(0);
                if (this.isRangeInsideEditor(range)) {
                    const anchorNode = selection.anchorNode;
                    const anchorElement = anchorNode && anchorNode.nodeType === Node.ELEMENT_NODE
                        ? (anchorNode as HTMLElement)
                        : (anchorNode?.parentElement ?? null);
                    const block = this.getClosestBlock(anchorElement);
                    if (block && ["h1", "h2", "h3"].includes(block.tagName.toLowerCase())) {
                        event.preventDefault();
                        // Insert paragraph after header and place caret inside it
                        const p = document.createElement('p');
                        p.appendChild(document.createElement('br'));
                        block.parentElement?.insertBefore(p, block.nextSibling);

                        // Place caret inside new paragraph
                        const r = document.createRange();
                        r.setStart(p, 0);
                        r.collapse(true);
                        const sel = window.getSelection();
                        sel?.removeAllRanges();
                        sel?.addRange(r);

                        this.updateInputValue();
                        this.updateEmptyState();

                        // Reset any slash state
                        this.contextMenuMode = null;
                        this.pendingSlashRemoval = false;
                        if (this.slashId) {
                            const el = this.element?.querySelector(`[data-slash-id="${this.slashId}"]`);
                            if (el instanceof HTMLElement) el.removeAttribute('data-slash-id');
                            this.slashId = null;
                        }
                        this.slashBlock = null;
                        return;
                    }
                }
            }
        }

        if (event.key === "/") {
            window.setTimeout(() => this.onSlash(), 0);
            return;
        }

        if (
            event.key === "@" ||
            (event.shiftKey && event.key === "2") ||
            (event.shiftKey && event.code === "Digit2")
        ) {
            window.setTimeout(() => this.onAt(), 0);
        }
    }

    private handleInput(event: Event): void {
        if (event.target && this.element && !this.element.contains(event.target as Node)) return;

        const inputEvent = event as InputEvent;
        if (inputEvent?.inputType === "insertText") {
            // @ trigger (existing behavior)
            if (inputEvent.data === "@") {
                this.onAt();
                return;
            }

            if (!inputEvent.data && this.getTextBeforeCaret(1) === "@") {
                this.onAt();
                return;
            }

            // / trigger: handle both when the character is inserted (inputEvent.data === '/')
            // and when composition causes inputEvent.data to be null (fallback check)
            if (inputEvent.data === "/") {
                // After insertion the caret is after the '/', so check the text before caret
                const before = this.getTextBeforeCaret(1000);
                if (before && before.endsWith("/")) {
                    const leading = before.slice(0, -1);
                    if (leading.trim().length === 0) {
                        // At line start before the slash
                        window.setTimeout(() => this.onSlash(), 0);
                        return;
                    }
                }
            }

            if (!inputEvent.data && this.getTextBeforeCaret(1) === "/") {
                // In some input scenarios the inserted character isn't present in inputEvent.data
                const before = this.getTextBeforeCaret(1000);
                if (before && before.endsWith("/")) {
                    const leading = before.slice(0, -1);
                    if (leading.trim().length === 0) {
                        window.setTimeout(() => this.onSlash(), 0);
                        return;
                    }
                }
            }
        }
    }

    private handlePaste(event: ClipboardEvent): void {
        if (!event.clipboardData) return;
        const text = event.clipboardData.getData("text/plain");
        if (!text) return;
        event.preventDefault();
        document.execCommand("insertText", false, text);
    }

    private openContextMenuAtCaret(items: ContextMenuItem[]): void {
        
        const rect = this.getCaretClientRect();
        if (!rect) {
            if (this.editorBody) {
                const fallback = this.editorBody.getBoundingClientRect();
                const fallbackRect = new DOMRect(
                    fallback.left + 8,
                    fallback.top + 8,
                    Math.max(1, fallback.width),
                    Math.max(1, fallback.height)
                );
                this.openContextMenuAtRect(items, fallbackRect);
            }
            return;
        }
        this.openContextMenuAtRect(items, rect);
    }

    private openContextMenuAtRect(items: ContextMenuItem[], rect: DOMRect): void {
        const editorBody = this.editorBody;
        if (!editorBody) return;

        const menu = getContextMenu();

        const event = new MouseEvent("contextmenu", {
            bubbles: true,
            cancelable: true,
            clientX: Math.round(rect.left),
            clientY: Math.round(rect.bottom),
        });

        menu.show(event, editorBody, items);

    }

    private getInlineStyleMenuItems(): ContextMenuItem[] {
        return [
            TextStyle.BOLD,
            TextStyle.ITALIC,
            TextStyle.UNDERLINE,
            TextStyle.STRIKETHROUGH,
            TextStyle.CODE,
        ].map((style) => ({
            label: style.name,
            icon: style.icon,
            onClick: () => this.setTextStyle(style),
        }));
    }

    private getBlockStyleMenuItems(): ContextMenuItem[] {
        return [
            TextStyle.PARAGRAPH,
            TextStyle.H1,
            TextStyle.H2,
            TextStyle.H3,
            TextStyle.BULLETED_LIST,
        ].map((style) => ({
            label: style.name,
            icon: style.icon,
            onClick: () => this.setTextStyle(style),
        }));
    }

    private getCaretClientRect(): DOMRect | null {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0) return null;
        const range = selection.getRangeAt(0);
        if (!this.isRangeInsideEditor(range)) return null;

        const rects = range.getClientRects();
        if (rects.length > 0) {
            return rects[0] as DOMRect;
        }

        const marker = document.createElement("span");
        marker.textContent = "\u200b";
        range.insertNode(marker);
        const rect = marker.getBoundingClientRect();
        marker.remove();
        range.collapse();
        return rect;
    }

    private isRangeInsideEditor(range: Range): boolean {
        const editorBody = this.editorBody;
        if (!editorBody) return false;
        return editorBody.contains(range.commonAncestorContainer);
    }

    private isCaretAtLineStart(): boolean {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0) return false;
        if (!selection.isCollapsed) return false;
        const range = selection.getRangeAt(0);

        const anchorNode = selection.anchorNode;
        if (!anchorNode) return false;

        const anchorElement = anchorNode.nodeType === Node.ELEMENT_NODE
            ? (anchorNode as HTMLElement)
            : (anchorNode.parentElement ?? null);
        if (!anchorElement) return false;

        const block = this.getClosestBlock(anchorElement);
        if (!block) return false;

        const cloneRange = range.cloneRange();
        cloneRange.selectNodeContents(block);
        cloneRange.setEnd(range.startContainer, range.startOffset);

        const textBefore = cloneRange.toString();
        return textBefore.trim().length === 0;
    }

    private getTextBeforeCaret(maxChars = 1): string {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0) return "";
        if (!selection.isCollapsed) return "";

        const range = selection.getRangeAt(0);
        if (!this.isRangeInsideEditor(range)) return "";

        const clone = range.cloneRange();
        const startContainer = clone.startContainer;
        const startOffset = clone.startOffset;

        if (startContainer.nodeType === Node.TEXT_NODE) {
            const text = startContainer.textContent ?? "";
            const from = Math.max(0, startOffset - maxChars);
            return text.slice(from, startOffset);
        }

        clone.setStart(this.editorBody as Node, 0);
        const textBefore = clone.toString();
        return textBefore.slice(-maxChars);
    }

    private getClosestBlock(element: HTMLElement | null): HTMLElement | null {
        const editorBody = this.editorBody;
        if (!element || !editorBody) return null;
        const blockTags = ["p", "h1", "h2", "h3", "li", "blockquote"];
        let current: HTMLElement | null = element;
        while (current && current !== editorBody) {
            if (blockTags.includes(current.tagName.toLowerCase())) return current;
            current = current.parentElement;
        }
        return editorBody;
    }

    private wrapSelectionWithTag(tag: string): void {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0) return;
        const range = selection.getRangeAt(0);
        if (range.collapsed) return;
        if (!this.isRangeInsideEditor(range)) return;

        const wrapper = document.createElement(tag);
        wrapper.appendChild(range.extractContents());
        range.insertNode(wrapper);
        selection.removeAllRanges();
        const newRange = document.createRange();
        newRange.selectNodeContents(wrapper);
        selection.addRange(newRange);
    }

    private applyStylesToElement(element: HTMLElement | null, styles?: Record<string, string> | undefined) : void {
        if (!element || !styles) return;
        for (const [prop, value] of Object.entries(styles)) {
            try {
                element.style.setProperty(prop, value);
            } catch (e) {
                // ignore invalid properties
            }
        }
    }

    private applyStyleToSelectionAncestor(style: TextStyle) : void {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount === 0) return;
        const anchorNode = selection.anchorNode;
        const anchorElement = anchorNode && anchorNode.nodeType === Node.ELEMENT_NODE
            ? (anchorNode as HTMLElement)
            : (anchorNode?.parentElement ?? null);
        if (!anchorElement) return;

        // Try to find the element corresponding to the style tag
        const tag = style.tag;
        let target = anchorElement.closest(tag);
        if (!target) {
            // Fallbacks for bold/italic where execCommand may use different tags
            if (tag === 'strong') target = anchorElement.closest('b');
            if (tag === 'em') target = anchorElement.closest('i');
        }

        if (target && style.styles) {
            this.applyStylesToElement(target as HTMLElement, style.styles);
        }
    }

    private normalizeBlocks(): void {
        const body = this.editorBody;
        if (!body) return;
        if (body.childNodes.length === 0) {
            body.innerHTML = "<p><br></p>";
            return;
        }

        const nodes = Array.from(body.childNodes);
        for (const node of nodes) {
            if (node.nodeType === Node.TEXT_NODE) {
                const text = node.textContent ?? "";
                const p = document.createElement("p");
                p.textContent = text;
                body.replaceChild(p, node);
                continue;
            }
            if (node.nodeType === Node.ELEMENT_NODE) {
                const element = node as HTMLElement;
                if (element.tagName.toLowerCase() === "br") {
                    const p = document.createElement("p");
                    p.appendChild(document.createElement("br"));
                    body.replaceChild(p, element);
                }
            }
        }
    }

    private ensureDefaultBlock(): void {
        const editorBody = this.editorBody;
        if (!editorBody) return;
        if (editorBody.innerHTML.trim().length === 0) {
            editorBody.innerHTML = "<p><br></p>";
        }
    }

    private updateInputValue(): void {
        if (!this.inputElement) return;
        this.inputElement.value = this.getText();
    }

    private removeSlashTrigger(targetBlock?: HTMLElement | null): void {
        if (!this.pendingSlashRemoval) return;
        this.pendingSlashRemoval = false;

        const block = targetBlock ?? this.slashBlock ?? (() => {
            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0) return null;
            const anchorNode = selection.anchorNode;
            const anchorElement = anchorNode?.nodeType === Node.ELEMENT_NODE
                ? (anchorNode as HTMLElement)
                : (anchorNode?.parentElement ?? null);
            return this.getClosestBlock(anchorElement);
        })();

        if (!block) return;

        // Prefer the text node at the caret, fallback to first node starting with '/'
        let textNode: Text | null = null;
        const selection = window.getSelection();
        if (selection && selection.anchorNode && selection.anchorNode.nodeType === Node.TEXT_NODE && block.contains(selection.anchorNode)) {
            textNode = selection.anchorNode as Text;
        }

        if (!textNode) {
            const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
            let node = walker.nextNode() as Text | null;
            while (node) {
                if (node.nodeValue && node.nodeValue.trimStart().startsWith('/')) {
                    textNode = node;
                    break;
                }
                node = walker.nextNode() as Text | null;
            }
        }

        if (!textNode || !textNode.nodeValue) return;

        const value = textNode.nodeValue;
        if (!value.trimStart().startsWith('/')) return;

        // Remove only the slash and optional following space
        const leadingWhitespace = value.match(/^\s*/)?.[0] ?? '';
        textNode.nodeValue = leadingWhitespace + value.replace(/^\s*\/\s?/, '');

        // Clear remembered slash block
        this.slashBlock = null;
    }

    private syncPlaceholder(): void {
        if (!this.element) return;
        const editorBody = this.editorBody;
        if (!editorBody) return;

        const placeholder =
            this.element.getAttribute("data-placeholder") ??
            this.element.getAttribute("placeholder");

        if (placeholder) {
            editorBody.setAttribute("data-placeholder", placeholder);
        } else {
            editorBody.removeAttribute("data-placeholder");
        }
    }

    /**
     * Updates wheter there is no
     */
    private updateEmptyState(): void {
        const text = this.editorBody.textContent ?? "";
        const isEmpty = text.trim().length === 0;
        this.editorBody.setAttribute("data-empty", isEmpty ? "true" : "false");
    }

    private ensureEditorBody(): HTMLDivElement | null {
        if (this.editorBody && this.editorBody.isConnected) return this.editorBody;
        if (!this.element) return null;

        const existingBody = this.element.querySelector<HTMLDivElement>("[data-text-editor-body]");
        if (existingBody) {
            this.editorBody = existingBody;
            return existingBody;
        }

        // Do not create a body automatically; the template must include it
        console.warn('TextEditor: data-text-editor-body not found in DOM. Ensure the template provides it.');
        return null;
    }

}