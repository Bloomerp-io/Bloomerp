import {
    $createParagraphNode,
    $createTextNode,
    $getNodeByKey,
    $getRoot,
    $getSelection,
    $isRangeSelection,
    type LexicalEditor,
    type LexicalNode,
    type NodeKey,
} from "lexical";
import ace from 'ace-builds/src-noconflict/ace';
import getGeneralModal from "@/utils/modals";
import HtmlNode, { $createHtmlNode } from "../nodes/HtmlNode";

type HtmlBehaviorState = {
    rootElement: HTMLElement | null;
    selectedHtmlNodeKey: NodeKey | null;
    handleClick: (event: Event) => void;
    handleKeyDown: (event: KeyboardEvent) => void;
};

const htmlBehaviorStates = new WeakMap<LexicalEditor, HtmlBehaviorState>();

export function registerHtmlBehavior(editor: LexicalEditor): () => void {
    const state = {
        rootElement: editor.getRootElement(),
        selectedHtmlNodeKey: null,
    } as HtmlBehaviorState;

    state.handleClick = handleEditorClick(editor, state);
    state.handleKeyDown = handleEditorKeyDown(editor, state);

    state.rootElement?.addEventListener("click", state.handleClick);
    state.rootElement?.addEventListener("keydown", state.handleKeyDown);
    htmlBehaviorStates.set(editor, state);

    return () => {
        state.rootElement?.removeEventListener("click", state.handleClick);
        state.rootElement?.removeEventListener("keydown", state.handleKeyDown);
        htmlBehaviorStates.delete(editor);
    };
}

export function promptHtmlInsert(editor: LexicalEditor): void {
    openHtmlModal('', (html) => insertHtml(editor, html));
}

function promptHtmlEdit(editor: LexicalEditor, state: HtmlBehaviorState, nodeKey: NodeKey): void {
    let html = '';

    editor.getEditorState().read(() => {
        const node = $getNodeByKey(nodeKey);
        if (node instanceof HtmlNode) {
            html = node.getHtml();
        }
    });

    openHtmlModal(html, (nextHtml) => {
        editor.update(() => {
            const node = $getNodeByKey(nodeKey);
            if (node instanceof HtmlNode) {
                node.setHtml(nextHtml);
            }
        });
        setSelectedHtmlNodeKey(editor, state, nodeKey);
    });
}

function handleEditorClick(editor: LexicalEditor, state: HtmlBehaviorState): (event: Event) => void {
    return (event: Event) => {
        const target = event.target as HTMLElement | null;
        const htmlWrapper = target?.closest<HTMLElement>(".text-editor-html-node");
        const htmlNodeKey = htmlWrapper?.dataset.htmlNodeKey ?? null;

        if (!htmlNodeKey) {
            setSelectedHtmlNodeKey(editor, state, null);
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        state.rootElement?.focus();
        setSelectedHtmlNodeKey(editor, state, htmlNodeKey);

        if ((event as MouseEvent).detail === 2) {
            promptHtmlEdit(editor, state, htmlNodeKey);
        }
    };
}

function handleEditorKeyDown(editor: LexicalEditor, state: HtmlBehaviorState): (event: KeyboardEvent) => void {
    return (event: KeyboardEvent) => {
        if (!state.selectedHtmlNodeKey) return;
        if (event.key !== "Backspace" && event.key !== "Delete") return;

        event.preventDefault();
        event.stopPropagation();
        const nodeKey = state.selectedHtmlNodeKey;

        editor.update(() => {
            const node = $getNodeByKey(nodeKey);
            if (node instanceof HtmlNode) {
                node.remove();
            }
        });

        setSelectedHtmlNodeKey(editor, state, null);
    };
}

function insertHtml(editor: LexicalEditor, html: string): void {
    const state = htmlBehaviorStates.get(editor);
    state?.rootElement?.focus();

    editor.update(() => {
        const htmlNode = $createHtmlNode(html);
        const trailingParagraph = $createParagraphNode();
        trailingParagraph.append($createTextNode(""));

        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
            insertBlockNodesAfterSelection([htmlNode, trailingParagraph]);
        } else {
            $getRoot().append(htmlNode, trailingParagraph);
        }

        trailingParagraph.selectStart();
    });
}

function insertBlockNodesAfterSelection(nodes: LexicalNode[]): void {
    const selection = $getSelection();
    if (!$isRangeSelection(selection)) {
        $getRoot().append(...nodes);
        return;
    }

    const anchorNode = selection.anchor.getNode();
    const topLevelNode = anchorNode.getTopLevelElement();

    if (!topLevelNode) {
        $getRoot().append(...nodes);
        return;
    }

    if (!selection.isCollapsed()) {
        selection.removeText();
    }

    let previousNode: LexicalNode = topLevelNode;
    for (const node of nodes) {
        previousNode = previousNode.insertAfter(node);
    }
}

function setSelectedHtmlNodeKey(
    editor: LexicalEditor,
    state: HtmlBehaviorState,
    nodeKey: NodeKey | null,
): void {
    state.selectedHtmlNodeKey = nodeKey;

    state.rootElement
        ?.querySelectorAll<HTMLElement>(".text-editor-html-node")
        .forEach((element) => {
            const isSelected = element.dataset.htmlNodeKey === nodeKey;
            element.classList.toggle("ring-2", isSelected);
            element.classList.toggle("ring-blue-500", isSelected);
            element.classList.toggle("ring-offset-2", isSelected);
        });
}

function openHtmlModal(initialHtml: string, onApply: (html: string) => void): void {
    configureAceModuleLoader();

    const modal = getGeneralModal();
    const body = modal.getBodyElement();
    if (!body) {
        return;
    }

    modal.setSize('full');
    modal.setTitle('HTML');
    body.innerHTML = '';

    const wrapper = document.createElement('div');
    wrapper.className = 'flex flex-col gap-3';

    const editorContainer = document.createElement('div');
    editorContainer.className = 'w-full rounded-md border border-gray-300';
    editorContainer.style.height = '520px';
    editorContainer.style.width = '100%';

    const actions = document.createElement('div');
    actions.className = 'flex justify-end gap-2';

    let htmlEditor: any = null;
    let cleanedUp = false;

    const cleanupEditor = () => {
        if (cleanedUp) {
            return;
        }

        cleanedUp = true;

        if (htmlEditor) {
            htmlEditor.destroy();
            htmlEditor = null;
        }

        editorContainer.textContent = '';
        delete (editorContainer as any).env;
        modal.element?.removeEventListener('bloomerp:modal-closed', cleanupEditor);
    };

    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'btn btn-secondary';
    cancelButton.textContent = 'Cancel';
    cancelButton.addEventListener('click', () => {
        modal.close();
    });

    const applyButton = document.createElement('button');
    applyButton.type = 'button';
    applyButton.className = 'btn btn-primary';
    applyButton.textContent = 'Apply';
    applyButton.addEventListener('click', () => {
        const html = htmlEditor?.getValue() ?? '';
        if (html.trim()) {
            onApply(html);
        }
        modal.close();
    });

    actions.append(cancelButton, applyButton);
    wrapper.append(editorContainer, actions);
    body.appendChild(wrapper);

    modal.element?.addEventListener('bloomerp:modal-closed', cleanupEditor, { once: true });
    modal.open();

    htmlEditor = ace.edit(editorContainer);
    htmlEditor.setTheme('ace/theme/chrome');
    htmlEditor.setOptions({
        showPrintMargin: false,
        fontSize: 14,
        tabSize: 2,
        useSoftTabs: true,
    });
    htmlEditor.session.setUseWrapMode(true);
    htmlEditor.session.setMode('ace/mode/html');
    htmlEditor.setValue(initialHtml, -1);

    requestAnimationFrame(() => {
        htmlEditor?.resize(true);
        htmlEditor?.focus();
    });
}

function configureAceModuleLoader(): void {
    const aceConfig = (ace as any).config;
    if (!aceConfig?.setLoader) return;

    aceConfig.setLoader((moduleName: string, cb: (error: unknown, module?: unknown) => void) => {
        const normalized = moduleName.startsWith('./') ? `ace/${moduleName.slice(2)}` : moduleName;

        const resolveModule = (): Promise<unknown> => {
            if (normalized === 'ace/theme/chrome') {
                return import('ace-builds/src-noconflict/theme-chrome');
            }

            if (normalized === 'ace/mode/html') {
                return import('ace-builds/src-noconflict/mode-html');
            }

            return Promise.reject(new Error(`Unsupported Ace module: ${normalized}`));
        };

        void resolveModule()
            .then((module) => cb(null, (module as any)?.default || module))
            .catch((error) => cb(error));
    });
}
