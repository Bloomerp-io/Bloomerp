import type { ContextMenuSubmenu } from "@/utils/contextMenu";
import { t as _ } from "@/utils/i18n";
import { $createHeadingNode } from "@lexical/rich-text";
import {
    $createListNode,
    type ListType,
} from "@lexical/list";
import { $setBlocksType } from "@lexical/selection";
import { $createTableNodeWithDimensions } from "@lexical/table";
import {
    $createParagraphNode,
    $getRoot,
    $getSelection,
    $insertNodes,
    $isInlineElementOrDecoratorNode,
    $isRangeSelection,
    $isTextNode,
    LexicalEditor,
    type LexicalNode,
} from "lexical"
import { getCurrentWordFromSelection, removeTextFromCurrentSelection } from "./utils/wordSelector";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import { promptImageUpload } from "./utils/imageBehavior";
import { promptHtmlInsert } from "./utils/htmlBehavior";
import { $createCodeBlockNode } from "./nodes/CodeBlockNode";


export type Action = {
    label: string,
    icon: string,
    submenu?: (textEditor: BloomerpTextEditor) => ContextMenuSubmenu;
    handler: (textEditor: BloomerpTextEditor) => void
}


function removeTriggerWord() {
    const currentWord = getCurrentWordFromSelection();
    if (currentWord[0] === '/' || currentWord[0] === '@') {
        removeTextFromCurrentSelection(currentWord)
    }
}

function getLexicalEditor(textEditor: BloomerpTextEditor): LexicalEditor | null {
    return textEditor.editor;
}

function handleHeading(textEditor: BloomerpTextEditor, heading: "h1" | "h2" | "h3") {
    const editor = getLexicalEditor(textEditor);
    if (!editor) {
        return;
    }

    editor.update(() => {
        removeTriggerWord()
        const selection = $getSelection();

        if (!$isRangeSelection(selection)) {
            return;
        }

        $setBlocksType(selection, () => $createHeadingNode(heading))
    });
}

/** Turn the selected paragraph or blocks into editable preformatted code. */
function handleCodeBlock(textEditor: BloomerpTextEditor): void {
    const editor = getLexicalEditor(textEditor);
    if (!editor) return;

    /** Convert the selected blocks or insert a block without a selection. */
    function insertCodeBlock(): void {
        removeTriggerWord();
        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
            $setBlocksType(selection, () => $createCodeBlockNode());
        } else {
            const block = $createCodeBlockNode();
            $getRoot().append(block);
            block.selectStart();
        }
    }

    editor.update(insertCodeBlock);
}

function canWrapSelectionInInlineNode(nodes: LexicalNode[]): boolean {
    if (nodes.length === 0) {
        return false;
    }

    const parent = nodes[0].getParent();

    return parent !== null && nodes.every((node) => (
        node.getParent() === parent && (
            $isTextNode(node) || $isInlineElementOrDecoratorNode(node)
        )
    ));
}

/** Convert the selected block to a list while removing a slash-command trigger. */
function handleList(textEditor: BloomerpTextEditor, listType: ListType): void {
    const editor = getLexicalEditor(textEditor);
    if (!editor) return;

    /** Replace the selected block inside Lexical's update transaction. */
    function convertSelectedBlock(): void {
        removeTriggerWord();
        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
            $setBlocksType(selection, () => $createListNode(listType));
        }
    }

    editor.update(convertSelectedBlock);
}

/** Insert a checklist using the same list conversion as the other list actions. */
function handleChecklist(textEditor: BloomerpTextEditor): void {
    handleList(textEditor, "check");
}

/** Insert an unordered list using the shared list conversion. */
function handleUnorderedList(textEditor: BloomerpTextEditor): void {
    handleList(textEditor, "bullet");
}

/** Insert an ordered list using the shared list conversion. */
function handleOrderedList(textEditor: BloomerpTextEditor): void {
    handleList(textEditor, "number");
}

/** Open the shared picker after removing a slash-command trigger. */
function handleTemplate(textEditor: BloomerpTextEditor): void {
    textEditor.openTemplatePicker();
}

/** Supply the template child page to the shared context menu. */
function templateSubmenu(textEditor: BloomerpTextEditor): ContextMenuSubmenu {
    return textEditor.getTemplateSubmenu();
}

export let ACTIONS: Record<string, Action> = {
    template: {
        /** Resolve the shared template command label. */
        get label(): string { return _("Template"); },
        icon: "fa-solid fa-file-lines",
        handler: handleTemplate,
        submenu: templateSubmenu,
    },
    code_block: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("Code Block"); },
        icon: "fa-solid fa-code",
        handler: handleCodeBlock,
    },
    h1: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("Heading 1"); },
        icon: "fa-solid fa-heading",
        handler: (textEditor) => handleHeading(textEditor, "h1")
    },
    h2: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("Heading 2"); },
        icon: "fa-solid fa-heading",
        handler: (textEditor) => handleHeading(textEditor, "h2")
    },
    h3: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("Heading 3"); },
        icon: "fa-solid fa-heading",
        handler: (textEditor) => handleHeading(textEditor, "h3")
    },
    image: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("Image"); },
        icon: "fa-solid fa-image",
        handler: (textEditor) => {
            const editor = getLexicalEditor(textEditor);
            if (!editor) {
                return;
            }

            editor.update(() => {
                removeTriggerWord()
            });
            promptImageUpload(editor);
        }
    },
    unordered_list: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("Bullet List"); },
        icon: "fa-solid fa-list-ul",
        handler: handleUnorderedList,
    },
    ordered_list: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("Numbered List"); },
        icon: "fa-solid fa-list-ol",
        handler: handleOrderedList,
    },
    checklist: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("Checklist"); },
        icon: "fa-solid fa-list-check",
        handler: handleChecklist,
    },
    table: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("Table"); },
        icon: "fa-solid fa-table",
        handler: (textEditor) => {
            const editor = getLexicalEditor(textEditor);
            if (!editor) {
                return;
            }

            editor.update(() => {
                removeTriggerWord()
                const selection = $getSelection();
                
                if (!$isRangeSelection(selection)) {
                    return;
                }

                const table = $createTableNodeWithDimensions(3, 2, {
                    rows: true,
                    columns: false,
                });
                const paragraph = $createParagraphNode();

                $insertNodes([table, paragraph]);
            });
        }
    },
    html: {
        /** Resolve the command label after the active catalog loads. */
        get label(): string { return _("HTML"); },
        icon: "fa-solid fa-code",
        handler: (textEditor) => {
            const editor = getLexicalEditor(textEditor);
            if (!editor) {
                return;
            }

            editor.update(() => {
                removeTriggerWord()
            });

            promptHtmlInsert(editor);
        }
    },
}
