import { $createHeadingNode } from "@lexical/rich-text";
import {
    $createListNode,
} from "@lexical/list";
import { $setBlocksType } from "@lexical/selection";
import { $createTableNodeWithDimensions } from "@lexical/table";
import { $createParagraphNode, $getSelection, $insertNodes, $isRangeSelection, LexicalEditor } from "lexical"
import { getCurrentWordFromSelection, removeTextFromCurrentSelection } from "./utils/wordSelector";
import getGeneralModal from "@/utils/modals";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import { promptImageUpload } from "./utils/imageBehavior";

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

                $setBlocksType(selection, () => $createListNode('bullet'))
            });
        }
    },
    ordered_list: {
        label: "Numbered List",
        icon: "fa-solid fa-list-ol",
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

                $setBlocksType(selection, () => $createListNode('number'))
            });
        }
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
            const modal = getGeneralModal();
            const body = modal.getBodyElement();
            if (!body) {
                return;
            }

            modal.setTitle('Raw HTML')
            body.innerHTML = ''

            const wrapper = document.createElement('div')
            wrapper.className = 'flex flex-col gap-3'

            const textarea = document.createElement('textarea')
            textarea.className = 'input min-h-80 w-full font-mono text-sm'
            textarea.value = textEditor.getValue()

            const actions = document.createElement('div')
            actions.className = 'flex justify-end gap-2'

            const cancelButton = document.createElement('button')
            cancelButton.type = 'button'
            cancelButton.className = 'btn btn-secondary'
            cancelButton.textContent = 'Cancel'
            cancelButton.addEventListener('click', () => {
                modal.close()
            })

            const applyButton = document.createElement('button')
            applyButton.type = 'button'
            applyButton.className = 'btn btn-primary'
            applyButton.textContent = 'Apply'
            applyButton.addEventListener('click', () => {
                textEditor.setValue(textarea.value, true)
                modal.close()
            })

            actions.append(cancelButton, applyButton)
            wrapper.append(textarea, actions)
            body.appendChild(wrapper)
            modal.open()
            textarea.focus()
        }
    }
}
