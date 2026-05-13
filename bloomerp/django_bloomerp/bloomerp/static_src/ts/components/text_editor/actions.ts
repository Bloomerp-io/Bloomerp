import { $createHeadingNode } from "@lexical/rich-text";
import {
    $createListNode,
    INSERT_ORDERED_LIST_COMMAND,
    INSERT_UNORDERED_LIST_COMMAND,
} from "@lexical/list";
import { $setBlocksType } from "@lexical/selection";
import { $getSelection, $isRangeSelection, LexicalEditor } from "lexical"
import { getCurrentWord, removeTextFromCurrentNode } from "./utils/wordSelector";

export type Action = {
    label: string,
    icon: string,
    handler: (editor: LexicalEditor) => void
}


function handleHeading(editor: LexicalEditor, heading: "h1" | "h2" | "h3") {
    editor.update(() => {
        const selection = $getSelection();

        const currentWord = getCurrentWord(editor);
        if (currentWord[0] === '/' || currentWord[0] === '@') {
            removeTextFromCurrentNode(editor, currentWord)
        }

        if (!$isRangeSelection(selection)) {
            return;
        }

        $setBlocksType(selection, () => $createHeadingNode(heading))
    });
}

export const ACTIONS: Record<string, Action> = {
    h1: {
        label: "Heading 1",
        icon: "fa-solid fa-heading",
        handler: (editor) => handleHeading(editor, "h1")
    },
    h2: {
        label: "Heading 2",
        icon: "fa-solid fa-heading",
        handler: (editor) => handleHeading(editor, "h2")
    },
    h3: {
        label: "Heading 3",
        icon: "fa-solid fa-heading",
        handler: (editor) => handleHeading(editor, "h3")
    },
    image: {
        label: "Image",
        icon: "fa-solid fa-image",
        handler: (editor) => {

        }
    },
    unordered_list: {
        label: "Bullet List",
        icon: "fa-solid fa-list-ul",
        handler: (editor) => {
            editor.update(() => {
                const selection = $getSelection();

                if (!$isRangeSelection(selection)) {
                    return;
                }

                $setBlocksType(selection, () => $createListNode('bullet'))
            });
        }
    },
    ordered_list: {
        label: "Numbered List",
        icon: "fa-solid fa-list-ol",
        handler: (editor) => {
            editor.update(() => {
                const selection = $getSelection();

                if (!$isRangeSelection(selection)) {
                    return;
                }

                $setBlocksType(selection, () => $createListNode('number'))
            });
        }
    }
}
