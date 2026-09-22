import { $createHeadingNode } from "@lexical/rich-text";
import {
    $createListNode,
    type ListType,
} from "@lexical/list";
import { $setBlocksType } from "@lexical/selection";
import { $createTableNodeWithDimensions } from "@lexical/table";
import {
    $createParagraphNode,
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


export type Action = {
    label: string,
    icon: string,
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

export let ACTIONS: Record<string, Action> = {
    h1: {
        label: "Heading 1",
        icon: "fa-solid fa-heading",
        handler: (textEditor) => handleHeading(textEditor, "h1")
    },
    h2: {
        label: "Heading 2",
        icon: "fa-solid fa-heading",
        handler: (textEditor) => handleHeading(textEditor, "h2")
    },
    h3: {
        label: "Heading 3",
        icon: "fa-solid fa-heading",
        handler: (textEditor) => handleHeading(textEditor, "h3")
    },
    image: {
        label: "Image",
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
        label: "Bullet List",
        icon: "fa-solid fa-list-ul",
        handler: handleUnorderedList,
    },
    ordered_list: {
        label: "Numbered List",
        icon: "fa-solid fa-list-ol",
        handler: handleOrderedList,
    },
    checklist: {
        label: "Checklist",
        icon: "fa-solid fa-list-check",
        handler: handleChecklist,
    },
    table: {
        label: "Table",
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
        label: "HTML",
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
