import { $getNearestNodeFromDOMNode, $getNodeByKey, $getRoot, $getSelection, $isElementNode, $isRangeSelection, type LexicalEditor, type LexicalNode, type NodeKey } from 'lexical';
import { $isHeadingNode } from '@lexical/rich-text';
import { $createListNode, $isListItemNode, $isListNode } from '@lexical/list';
import { t as _ } from '@/utils/i18n';

/** Include Lexical's adjacent nested-list wrapper when moving its preceding item. */
function moveGroup(node: LexicalNode): LexicalNode[] {
    const next = node.getNextSibling();
    return $isListItemNode(node) && $isListItemNode(next) && $isListNode(next.getFirstChild()) ? [node, next] : [node];
}

/** Move blocks or list-item subtrees without converting their content to HTML. */
export function moveEditorBlock(sourceKey: NodeKey, targetKey: NodeKey, after: boolean): void {
    const source = $getNodeByKey(sourceKey);
    let target = $getNodeByKey(targetKey);
    if (!source || !target || source === target) return;
    const group = moveGroup(source);
    const sourceKeys = new Set(group.map(nodeKey));
    if (sourceKeys.has(target.getKey()) || target.getParents().some(hasSourceParent)) return;
    /** Reject drops into the subtree being moved. */
    function hasSourceParent(parent: LexicalNode): boolean { return sourceKeys.has(parent.getKey()); }
    let moving = group;
    if ($isListItemNode(source) && !$isListItemNode(target)) {
        const parent = source.getParent();
        if (!$isListNode(parent)) return;
        const list = $createListNode(parent.getListType());
        // Attach the list before its existing children are moved into it.
        target = target.getTopLevelElementOrThrow();
        if (after) target.insertAfter(list); else target.insertBefore(list);
        for (const item of group) list.append(item);
        return;
    }
    if (!$isListItemNode(source)) {
        target = target.getTopLevelElementOrThrow();
        if (target === source || target.getParents().some(hasSourceParent)) return;
        moving = [source];
    }
    if (after) {
        const targets = moveGroup(target);
        let anchor = targets[targets.length - 1];
        if (sourceKeys.has(anchor.getKey())) return;
        for (const item of moving) { anchor.insertAfter(item); anchor = item; }
    } else {
        for (const item of moving) target.insertBefore(item);
    }
}

/** Read stable node identities for move-group membership checks. */
function nodeKey(node: LexicalNode): NodeKey { return node.getKey(); }

/** Add block handles, a heading outline, local folding, and empty-block hints. */
class EditorBlocks {
    private readonly lifecycle = new AbortController();
    private readonly controls = document.createElement('div');
    private readonly handle = document.createElement('button');
    private readonly fold = document.createElement('button');
    private readonly outline = document.createElement('details');
    private readonly outlineRail = document.createElement('summary');
    private readonly outlineNav = document.createElement('nav');
    private readonly indicator = document.createElement('div');
    private readonly collapsed = new Set<NodeKey>();
    private hovered: NodeKey | null = null;
    private candidate: NodeKey | null = null;
    private showTimer: ReturnType<typeof setTimeout> | null = null;
    private hideTimer: ReturnType<typeof setTimeout> | null = null;
    private dragging: NodeKey | null = null;
    private target: { key: NodeKey; after: boolean } | null = null;
    private headingsSignature = '';
    private headingKeys: NodeKey[] = [];
    private outlineTimer: ReturnType<typeof setTimeout> | null = null;
    private readonly unregister: () => void;

    /** Bind controls outside editable content so UI state never enters saved HTML. */
    constructor(private readonly editor: LexicalEditor, private readonly host: HTMLElement) {
        this.controls.className = 'bloomerp-editor-block-controls';
        this.handle.type = this.fold.type = 'button';
        this.handle.draggable = true;
        this.handle.setAttribute('aria-label', _('Move block'));
        this.handle.title = _('Drag to move; Alt + arrow keys to reorder');
        this.handle.innerHTML = '<i class="fa-solid fa-grip-vertical" aria-hidden="true"></i>';
        this.fold.innerHTML = '<i class="fa-solid fa-chevron-right" aria-hidden="true"></i>';
        this.controls.append(this.handle, this.fold);
        this.outline.className = 'bloomerp-editor-outline';
        const summary = this.outlineRail;
        summary.setAttribute('aria-label', _('On this page'));
        summary.title = _('On this page');
        this.outlineNav.setAttribute('aria-label', _('Page headings'));
        this.outline.append(summary, this.outlineNav);
        this.indicator.className = 'bloomerp-editor-drop-indicator';
        this.indicator.hidden = true;
        host.append(this.controls, this.outline, this.indicator);
        const options = { signal: this.lifecycle.signal };
        host.addEventListener('mousemove', this.hover, options);
        host.addEventListener('mouseleave', this.leave, options);
        host.addEventListener('scroll', this.leave, { capture: true, ...options });
        host.addEventListener('focusin', this.focusChanged, options);
        host.addEventListener('focusout', this.focusChanged, options);
        host.addEventListener('dragover', this.dragOver, { capture: true, ...options });
        host.addEventListener('drop', this.drop, { capture: true, ...options });
        this.handle.addEventListener('dragstart', this.dragStart, options);
        this.handle.addEventListener('dragend', this.dragEnd, options);
        this.handle.addEventListener('keydown', this.reorderKey, options);
        this.fold.addEventListener('mousedown', this.preventFocus, options);
        this.fold.addEventListener('click', this.toggleHeading, options);
        this.outlineNav.addEventListener('click', this.jump, options);
        this.outline.addEventListener('mouseenter', this.openOutline, options);
        this.outline.addEventListener('mouseleave', this.leaveOutline, options);
        this.outline.addEventListener('focusin', this.openOutline, options);
        this.outline.addEventListener('focusout', this.leaveOutline, options);
        this.outlineRail.addEventListener('click', this.clickOutline, options);
        document.addEventListener('scroll', this.positionOutline, { capture: true, ...options });
        window.addEventListener('resize', this.positionOutline, options);
        this.unregister = editor.registerUpdateListener(this.refresh);
        this.refresh();
    }

    /** Suppress focus changes while folding a heading beside the caret. */
    private preventFocus(event: MouseEvent): void { event.preventDefault(); }

    /** Expand the heading rail on hover or keyboard focus without moving the caret. */
    private openOutline = (): void => {
        if (this.outlineTimer) clearTimeout(this.outlineTimer);
        this.outline.open = true;
    };

    /** Keep a pointer or touch activation open after hover has already revealed it. */
    private clickOutline = (event: MouseEvent): void => {
        event.preventDefault();
        this.openOutline();
    };

    /** Keep the outline open while crossing from its rail into the heading menu. */
    private leaveOutline = (): void => {
        if (this.outlineTimer) clearTimeout(this.outlineTimer);
        this.outlineTimer = setTimeout(this.closeOutline, 200);
    };

    /** Collapse the outline only after both pointer and keyboard focus leave it. */
    private closeOutline = (): void => {
        this.outlineTimer = null;
        if (!this.outline.matches(':hover') && !this.outline.contains(document.activeElement)) this.outline.open = false;
    };

    /** Keep the section rail beside its visible editor and highlight the current heading. */
    private positionOutline = (): void => {
        if (this.outline.hidden || !this.host.isConnected) return;
        const page = this.host.closest<HTMLElement>('[bloomerp-component="bloomerp:page-editor"]');
        const owner = page ?? this.host;
        const bounds = owner.getBoundingClientRect();
        let scrollParent = owner.parentElement;
        while (scrollParent && !/(auto|scroll)/.test(getComputedStyle(scrollParent).overflowY)) scrollParent = scrollParent.parentElement;
        const viewport = scrollParent?.getBoundingClientRect();
        const top = Math.max(0, viewport?.top ?? 0, bounds.top);
        const bottom = Math.min(window.innerHeight, viewport?.bottom ?? window.innerHeight, bounds.bottom);
        this.outline.style.visibility = bottom > top && bounds.width > 0 ? '' : 'hidden';
        this.outline.style.left = `${Math.max(4, bounds.left + (page ? 8 : -38))}px`;
        this.outline.style.top = `${top + (bottom - top) / 2}px`;
        let active = this.headingKeys[0];
        for (const key of this.headingKeys) {
            const heading = this.editor.getElementByKey(key);
            if (heading && heading.getClientRects().length && heading.getBoundingClientRect().top <= top + 80) active = key;
        }
        for (const item of this.outline.querySelectorAll<HTMLElement>('[data-heading-key]')) {
            const current = item.dataset.headingKey === active;
            item.classList.toggle('is-current', current);
            if (item.tagName === 'BUTTON') {
                if (current) item.setAttribute('aria-current', 'location');
                else item.removeAttribute('aria-current');
            }
        }
    };

    /** Find the smallest list item or top-level block at a pointer position. */
    private keyAt(element: Node | null): NodeKey | null {
        const root = this.editor.getRootElement();
        if (!element || !root?.contains(element) || element === root) return null;
        const editor = this.editor;
        /** Resolve a DOM target through Lexical while keeping list sub-items individually movable. */
        function resolve(): NodeKey | null {
            let node = $getNearestNodeFromDOMNode(element!);
            while (node && node.getParent() && node.getParent() !== $getRoot()) {
                if ($isListItemNode(node)) {
                    if ($isListNode(node.getFirstChild()) && node.getPreviousSibling()) return node.getPreviousSibling()!.getKey();
                    return node.getKey();
                }
                node = node.getParent();
            }
            return node?.getKey() ?? null;
        }
        return editor.read(resolve);
    }

    /** Reveal stable hover targets after a short delay and keep the gutter reachable. */
    private hover = (event: MouseEvent): void => {
        if (this.dragging) return;
        if (this.hideTimer) clearTimeout(this.hideTimer);
        this.hideTimer = null;
        if (this.controls.contains(event.target as Node)) return;
        const key = this.keyAt(event.target as Node);
        if (!key) return;
        if (this.candidate === key) return;
        this.candidate = key;
        if (this.showTimer) clearTimeout(this.showTimer);
        this.showTimer = setTimeout(this.showControls, 120);
    };

    /** Fade in the latest stable target without shifting controls during a drag. */
    private showControls = (): void => {
        this.showTimer = null;
        if (!this.candidate || this.dragging) return;
        this.hovered = this.candidate;
        this.positionControls();
        this.controls.classList.add('is-visible');
    };

    /** Fade out idle controls while retaining their position for the next hover. */
    private hideControls = (): void => {
        this.hideTimer = null;
        this.candidate = null;
        this.controls.classList.remove('is-visible');
    };

    /** Place floating controls in the block's left gutter without altering document layout. */
    private positionControls(): void {
        const node = this.hovered ? this.editor.getElementByKey(this.hovered) : null;
        if (!node) { this.hideControls(); return; }
        const rect = node.getBoundingClientRect();
        const host = this.host.getBoundingClientRect();
        this.controls.style.left = `${rect.left - host.left - this.controls.offsetWidth}px`;
        this.controls.style.top = `${rect.top - host.top + this.host.scrollTop}px`;
        this.handle.hidden = !this.editor.isEditable();
        this.fold.hidden = !/^H[1-6]$/.test(node.tagName);
        const collapsed = this.collapsed.has(this.hovered!);
        this.fold.setAttribute('aria-expanded', String(!collapsed));
        this.fold.setAttribute('aria-label', collapsed ? _('Expand section') : _('Collapse section'));
        this.fold.classList.toggle('is-expanded', !collapsed);
    }

    /** Allow time to cross into the block gutter before fading idle controls out. */
    private leave = (): void => {
        if (this.dragging) return;
        if (this.showTimer) clearTimeout(this.showTimer);
        this.showTimer = null;
        this.candidate = null;
        if (this.hideTimer) clearTimeout(this.hideTimer);
        this.hideTimer = setTimeout(this.hideControls, 240);
    };

    /** Recompute the caret hint after the browser has completed a focus transition. */
    private focusChanged = (): void => { queueMicrotask(this.refresh); };

    /** Begin a same-editor move without exposing document HTML through drag data. */
    private dragStart = (event: DragEvent): void => {
        if (!this.editor.isEditable() || !this.hovered || !event.dataTransfer) { event.preventDefault(); return; }
        this.dragging = this.hovered;
        if (this.showTimer) clearTimeout(this.showTimer);
        if (this.hideTimer) clearTimeout(this.hideTimer);
        this.showTimer = this.hideTimer = null;
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('application/x-bloomerp-block', this.hovered);
    };

    /** Preview the insertion edge while preventing native HTML drag insertion. */
    private dragOver = (event: DragEvent): void => {
        if (!this.dragging || !this.editor.isEditable()) return;
        const key = this.keyAt(event.target as Node);
        if (!key) return;
        event.preventDefault(); event.stopPropagation();
        const element = this.editor.getElementByKey(key)!;
        const rect = element.getBoundingClientRect();
        const host = this.host.getBoundingClientRect();
        const after = event.clientY > rect.top + Math.min(rect.height, 32) / 2;
        this.target = { key, after };
        this.indicator.hidden = false;
        this.indicator.style.top = `${(after ? rect.bottom : rect.top) - host.top + this.host.scrollTop}px`;
        this.indicator.style.left = `${rect.left - host.left}px`;
        this.indicator.style.width = `${rect.width}px`;
    };

    /** Apply one undoable tree move and preserve nested sub-items with their parent. */
    private drop = (event: DragEvent): void => {
        if (!this.dragging) return;
        event.preventDefault(); event.stopPropagation();
        const source = this.dragging;
        const target = this.target;
        /** Move the selected block inside a single Lexical update. */
        function move(): void { if (target) moveEditorBlock(source, target.key, target.after); }
        if (this.editor.isEditable()) this.editor.update(move);
        this.dragEnd();
    };

    /** Remove temporary drag state whether a drop succeeds or is cancelled. */
    private dragEnd = (): void => {
        this.dragging = null;
        this.target = null;
        this.indicator.hidden = true;
        this.hideControls();
    };

    /** Offer keyboard reordering for users who cannot use the drag handle. */
    private reorderKey = (event: KeyboardEvent): void => {
        if (!event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key) || !this.hovered || !this.editor.isEditable()) return;
        event.preventDefault();
        const key = this.hovered;
        const after = event.key === 'ArrowDown';
        /** Reorder the focused item relative to its adjacent complete subtree. */
        function move(): void {
            const node = $getNodeByKey(key);
            if (!node) return;
            const group = moveGroup(node);
            let sibling = after ? group[group.length - 1].getNextSibling() : node.getPreviousSibling();
            if (!after && $isListItemNode(sibling) && $isListNode(sibling.getFirstChild())) sibling = sibling.getPreviousSibling();
            if (sibling) moveEditorBlock(key, sibling.getKey(), after);
        }
        this.editor.update(move);
    };

    /** Toggle presentation-only folding, selecting the heading to avoid a hidden caret. */
    private toggleHeading = (): void => {
        if (!this.hovered) return;
        const key = this.hovered;
        if (this.collapsed.has(key)) this.collapsed.delete(key); else this.collapsed.add(key);
        /** Keep the active caret visible while collapsing the following section. */
        function selectHeading(): void { const node = $getNodeByKey(key); if ($isElementNode(node)) node.selectEnd(); }
        this.editor.update(selectHeading, { discrete: true });
        this.refresh();
    };

    /** Jump to a heading and expand any personal folds that would hide its location. */
    private jump = (event: MouseEvent): void => {
        const key = (event.target as Element).closest<HTMLElement>('[data-heading-key]')?.dataset.headingKey;
        if (!key) return;
        this.collapsed.clear();
        this.refresh();
        this.editor.getElementByKey(key)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        this.outline.open = false;
        this.editor.focus();
        /** Put keyboard navigation at the selected heading after scrolling. */
        function select(): void { const node = $getNodeByKey(key!); if ($isElementNode(node)) node.selectStart(); }
        this.editor.update(select);
    };

    /** Refresh hints, headings and folds after edits without changing stored node content. */
    private refresh = (): void => {
        const root = this.editor.getRootElement();
        if (!root || this.lifecycle.signal.aborted) return;
        const headings: Array<{ key: string; title: string; level: number }> = [];
        const editor = this.editor;
        const collapsed = this.collapsed;
        const hint = _('Press / for commands or @ for mentions');
        let selected: LexicalNode | null = null;
        let activeBlock: NodeKey | null = null;
        /** Annotate leaf blocks and derive the outline from the actual document tree. */
        function visit(node: LexicalNode): void {
            const dom = editor.getElementByKey(node.getKey());
            if ($isElementNode(node)) {
                const empty = node.getKey() === activeBlock && node.getChildrenSize() === 0 && ['paragraph', 'heading', 'listitem'].includes(node.getType());
                if (dom) {
                    if (empty && editor.isEditable()) dom.dataset.blockPlaceholder = hint;
                    else delete dom.dataset.blockPlaceholder;
                }
                if ($isHeadingNode(node)) headings.push({ key: node.getKey(), title: node.getTextContent() || _('Untitled'), level: Number(node.getTag().slice(1)) });
                for (const child of node.getChildren()) visit(child);
            }
        }
        /** Apply heading scopes until the next heading of the same or higher level. */
        function read(): void {
            const selection = $getSelection();
            if ($isRangeSelection(selection)) {
                selected = selection.anchor.getNode().getTopLevelElement();
                if (selection.isCollapsed() && root!.contains(document.activeElement)) {
                    let node: LexicalNode | null = selection.anchor.getNode();
                    while (node && !['paragraph', 'heading', 'listitem'].includes(node.getType())) node = node.getParent();
                    activeBlock = node?.getKey() ?? null;
                }
            }
            visit($getRoot());
            let hiddenBy: { key: string; level: number } | null = null;
            for (const node of $getRoot().getChildren()) {
                const level = $isHeadingNode(node) ? Number(node.getTag().slice(1)) : 7;
                if (hiddenBy && level <= hiddenBy.level) hiddenBy = null;
                // Keyboard navigation into a folded section reveals it rather than editing invisible text.
                if (hiddenBy && selected === node) { collapsed.delete(hiddenBy.key); hiddenBy = null; }
                const dom = editor.getElementByKey(node.getKey());
                if (dom) dom.classList.toggle('bloomerp-editor-folded', !!hiddenBy);
                if (!hiddenBy && collapsed.has(node.getKey()) && $isHeadingNode(node)) hiddenBy = { key: node.getKey(), level };
            }
        }
        editor.getEditorState().read(read);
        root.dataset.blockHints = 'true';
        this.outline.hidden = headings.length === 0;
        const signature = JSON.stringify(headings);
        if (signature !== this.headingsSignature) {
            this.headingsSignature = signature;
            this.outlineNav.replaceChildren();
            this.outlineRail.replaceChildren();
            this.headingKeys = [];
            for (const heading of headings) {
                this.headingKeys.push(heading.key);
                const mark = document.createElement('span');
                mark.dataset.headingKey = heading.key;
                mark.setAttribute('aria-hidden', 'true');
                mark.style.width = `${Math.max(6, 26 - heading.level * 4)}px`;
                this.outlineRail.append(mark);
                const button = document.createElement('button');
                button.type = 'button';
                button.dataset.headingKey = heading.key;
                button.textContent = heading.title;
                button.setAttribute('aria-label', heading.title);
                button.style.paddingLeft = `${0.5 + (heading.level - 1) * 0.65}rem`;
                this.outlineNav.append(button);
            }
        }
        this.positionOutline();
        if (this.controls.classList.contains('is-visible')) this.positionControls();
    };

    /** Remove editor-only DOM annotations and all owned controls and listeners. */
    public destroy(): void {
        this.lifecycle.abort(); this.unregister();
        if (this.showTimer) clearTimeout(this.showTimer);
        if (this.hideTimer) clearTimeout(this.hideTimer);
        if (this.outlineTimer) clearTimeout(this.outlineTimer);
        for (const node of this.host.querySelectorAll<HTMLElement>('[data-block-placeholder]')) delete node.dataset.blockPlaceholder;
        for (const node of this.host.querySelectorAll('.bloomerp-editor-folded')) node.classList.remove('bloomerp-editor-folded');
        this.controls.remove(); this.outline.remove(); this.indicator.remove();
    }
}

/** Install document controls on ordinary editors as well as Pages and the scratchpad. */
export function registerBlockBehavior(editor: LexicalEditor, host: HTMLElement): () => void {
    const behavior = new EditorBlocks(editor, host);
    return behavior.destroy.bind(behavior);
}
