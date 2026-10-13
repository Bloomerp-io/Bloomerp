import { getContextMenu, getActiveContextMenu, type ContextMenuController, type ContextMenuItem, type ContextMenuSubmenu } from "@/utils/contextMenu";
import { $getSelection, $setSelection, $getRoot, $insertNodes, type BaseSelection, type LexicalEditor } from "lexical";
import { $generateNodesFromDOM } from "@lexical/html";
import { getSdk } from "@/sdk/getSdk";
import { t as _ } from "@/utils/i18n";
import { getCurrentWordFromSelection, removeTextFromCurrentSelection } from "./wordSelector";

export interface EditorTemplate {
    id: string;
    name: string;
    body: string;
}

export interface TemplateSelection {
    template: EditorTemplate;
    insert: (body: string) => void;
}

/** Adapt document templates to the reusable searchable context submenu. */
export class TemplatePicker {
    private selection: BaseSelection | null = null;
    private menu: ContextMenuController | null = null;

    /** Bind one picker to an editor without creating a separate dialog. */
    public constructor(private readonly host: HTMLElement, private readonly editor: LexicalEditor) {}

    /** Describe a reusable searchable submenu and its editor selection hook. */
    public submenu(): ContextMenuSubmenu {
        return {
            label: _("Template"),
            onOpen: this.captureSelection,
            search: { placeholder: _("Search templates"), load: this.load },
        };
    }

    /** Open the same submenu directly from the formatting toolbar. */
    public open(): void {
        this.menu = getContextMenu("bloomerp-text-editor-template-menu");
        this.menu.showSubmenu(this.submenu(), this.host);
    }

    /** Save the insertion range before search receives focus. */
    private captureSelection = (): void => {
        this.menu = getActiveContextMenu() ?? this.menu;
        this.editor.update(this.removeTrigger, { discrete: true });
        this.editor.getEditorState().read(this.saveSelection);
    };

    /** Remove the slash trigger before Lexical normalizes empty text nodes. */
    private removeTrigger = (): void => {
        const word = getCurrentWordFromSelection();
        if (word.startsWith("/")) removeTextFromCurrentSelection(word);
    };

    /** Clone the committed selection after empty trigger nodes have been normalized. */
    private saveSelection = (): void => {
        this.selection = $getSelection()?.clone() ?? null;
    };

    /** Return template leaves while the menu owns debounce, cancellation, and errors. */
    private load = async (query: string, signal: AbortSignal): Promise<ContextMenuItem[]> => {
        const response = await getSdk().client.request<{ templates: EditorTemplate[] }>(
            this.host.dataset.templateSearchUrl!, { query: { q: query }, signal },
        );
        return response.templates.map(this.toItem);
    };

    /** Bind a template leaf to its cancellable editor event. */
    private toItem = (template: EditorTemplate): ContextMenuItem => {
        return { label: template.name, onClick: this.select.bind(this, template) };
    };

    /** Let specialized editors prepare variables before inserting the copied content. */
    private select(template: EditorTemplate): void {
        const event = new CustomEvent<TemplateSelection>("bloomerp:template-selected", {
            bubbles: true, cancelable: true, detail: { template, insert: this.insert },
        });
        if (this.host.dispatchEvent(event)) this.insert(template.body);
    }

    /** Insert editable rich text at the captured range, retaining surrounding content. */
    private insert = (body: string): void => {
        const editor = this.editor;
        const selection = this.selection;
        /** Restore the saved range and import ordinary editable Lexical nodes. */
        function insertContent(): void {
            $setSelection(selection?.clone() ?? null);
            if (!$getSelection()) $getRoot().selectEnd();
            const document = new DOMParser().parseFromString(body, "text/html");
            $insertNodes($generateNodesFromDOM(editor, document));
        }
        editor.update(insertContent, { discrete: true });
        editor.focus();
    };

    /** Dismiss owned menu work when the editor is destroyed. */
    public destroy(): void {
        this.menu?.hide();
    }
}
