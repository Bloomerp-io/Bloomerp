import { $createHeadingNode } from "@lexical/rich-text";
import {
    $createListNode,
} from "@lexical/list";
import { $setBlocksType } from "@lexical/selection";
import { $createTableNodeWithDimensions } from "@lexical/table";
import { $createParagraphNode, $getSelection, $insertNodes, $isRangeSelection, LexicalEditor } from "lexical"
import ace from 'ace-builds/src-noconflict/ace';
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

// TODO: Move this somewhere else, as it is not specific to the text editor
function configureAceModuleLoader(): void {
    const aceConfig = (ace as any).config;
    if (!aceConfig?.setLoader) return;

    aceConfig.setLoader((moduleName: string, cb: (error: unknown, module?: unknown) => void) => {
        const normalized = moduleName.startsWith('./') ? `ace/${moduleName.slice(2)}` : moduleName;

        const resolveModule = (): Promise<unknown> => {
            if (normalized === 'ace/theme/chrome') {
                return import('ace-builds/src-noconflict/theme-chrome');
            }

            if (normalized === 'ace/mode/json') {
                return import('ace-builds/src-noconflict/mode-json');
            }

            if (normalized === 'ace/mode/python') {
                return import('ace-builds/src-noconflict/mode-python');
            }

            if (normalized === 'ace/mode/javascript') {
                return import('ace-builds/src-noconflict/mode-javascript');
            }

            if (normalized === 'ace/mode/sql') {
                return import('ace-builds/src-noconflict/mode-sql');
            }

            if (normalized === 'ace/mode/html') {
                return import('ace-builds/src-noconflict/mode-html');
            }

            if (normalized === 'ace/mode/css') {
                return import('ace-builds/src-noconflict/mode-css');
            }

            if (normalized === 'ace/ext/language_tools') {
                return import('ace-builds/src-noconflict/ext-language_tools');
            }

            return Promise.reject(new Error(`Unsupported Ace module: ${normalized}`));
        };

        void resolveModule()
            .then((module) => cb(null, (module as any)?.default || module))
            .catch((error) => cb(error));
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
            configureAceModuleLoader();

            const modal = getGeneralModal();
            const body = modal.getBodyElement();
            if (!body) {
                return;
            }

            modal.setSize('full')
            modal.setTitle('Raw HTML')
            body.innerHTML = ''

            const wrapper = document.createElement('div')
            wrapper.className = 'flex flex-col gap-3'

            const editorContainer = document.createElement('div')
            editorContainer.className = 'w-full rounded-md border border-gray-300'
            editorContainer.style.height = '520px'
            editorContainer.style.width = '100%'

            const actions = document.createElement('div')
            actions.className = 'flex justify-end gap-2'

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
                textEditor.setValue(htmlEditor?.getValue() ?? textEditor.getValue(), true)
                modal.close()
            })

            actions.append(cancelButton, applyButton)
            wrapper.append(editorContainer, actions)
            body.appendChild(wrapper)

            modal.element?.addEventListener('bloomerp:modal-closed', cleanupEditor, { once: true });
            modal.open()

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
            htmlEditor.setValue(textEditor.getValue(), -1);

            requestAnimationFrame(() => {
                htmlEditor?.resize(true);
                htmlEditor?.focus();
            });
        }
    }
}
