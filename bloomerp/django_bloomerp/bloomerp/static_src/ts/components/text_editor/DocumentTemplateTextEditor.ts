import type { Klass, LexicalNode } from "lexical";
import { t as _ } from "../../utils/i18n";
import type { ActionContext } from "./actionRegistry";
import { BloomerpTextEditor } from "./BloomerpTextEditor";
import { PageBreakNode } from "./nodes/PageBreakNode";
import { insertPageBreak } from "./utils/pageBreakBehavior";

/** Insert a page boundary after the shared registry restores selection and consumes any slash query. */
function handlePageBreak(editor: BloomerpTextEditor, _context: ActionContext): void {
    if (editor.editor) insertPageBreak(editor.editor);
}

/** Keep printable page-boundary nodes and actions specific to document templates. */
export class DocumentTemplateTextEditor extends BloomerpTextEditor {
    /** Register page breaks before saved template HTML is imported. */
    protected getAdditionalNodes(): Array<Klass<LexicalNode>> {
        return [...super.getAdditionalNodes(), PageBreakNode];
    }

    /** Add the translated document-only command to this editor's toolbar and menu. */
    public initialize(): void {
        super.initialize();
        this.registerAction(
            { label: _("Page break"), icon: "fa-solid fa-file-circle-plus", handler: handlePageBreak },
            "page_break",
            true,
        );
    }
}
