import { $getNodeByKey, $getSelection, $isRangeSelection, $setSelection, type LexicalEditor, type RangeSelection } from "lexical";
import { createModalInstance } from "@/utils/modals";
import { t as _ } from "@/utils/i18n";
import { $insertEditorLink, normalizeLinkHref } from "./linkBehavior";

/** Open a disposable link form while preserving the exact selection until Apply. */
export function promptLinkInsert(editor: LexicalEditor, host: HTMLElement): void {
    if (!editor.isEditable() || host.dataset.disabled === "true") return;
    let selection: RangeSelection | null = null;
    let selectedText = "";
    /** Capture the selection before the dialog takes keyboard focus. */
    function captureSelection(): void {
        const current = $getSelection();
        if ($isRangeSelection(current)) {
            selection = current.clone();
            selectedText = current.getTextContent();
        }
    }
    editor.getEditorState().read(captureSelection);
    if (!selection) return;
    const modal = createModalInstance("bloomerp-general-use-modal", host);
    const body = modal.getBodyElement();
    if (!body) return;
    modal.setTitle(_("Insert link"));
    modal.setSize("sm");
    const form = document.createElement("form");
    form.className = "flex flex-col gap-3";
    /** Create a safely labelled input without injecting user strings into HTML. */
    function addInput(labelText: string, value: string): HTMLInputElement {
        const label = document.createElement("label");
        label.textContent = labelText;
        const input = document.createElement("input");
        input.className = "input w-full";
        input.value = value;
        label.appendChild(input);
        form.appendChild(label);
        return input;
    }
    const name = addInput(_("Link name"), selectedText);
    const href = addInput(_("Link URL"), "");
    href.required = true;
    href.placeholder = "https://";
    const actions = document.createElement("div");
    actions.className = "flex justify-end gap-2";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn btn-secondary";
    cancel.textContent = _("Cancel");
    /** Dismiss without changing document content or history. */
    function cancelInsert(): void { modal.close(); }
    cancel.addEventListener("click", cancelInsert);
    const apply = document.createElement("button");
    apply.type = "submit";
    apply.className = "btn btn-primary";
    apply.textContent = _("Insert link");
    actions.append(cancel, apply);
    form.appendChild(actions);
    body.replaceChildren(form);
    /** Clear a previous validation error as the destination changes. */
    function clearValidation(): void { href.setCustomValidity(""); }
    href.addEventListener("input", clearValidation);
    /** Validate the destination and restore the captured selection in one undoable update. */
    function submitLink(event: SubmitEvent): void {
        event.preventDefault();
        const url = normalizeLinkHref(href.value);
        if (!url) {
            href.setCustomValidity(_("Enter a valid http, https, mailto, or tel URL."));
            href.reportValidity();
            return;
        }
        if (!editor.isEditable() || host.dataset.disabled === "true" || !host.isConnected) {
            modal.close();
            return;
        }
        /** Insert only if the saved selection still refers to this document. */
        function applyLink(): void {
            if (!selection || !$getNodeByKey(selection.anchor.key)?.isAttached() || !$getNodeByKey(selection.focus.key)?.isAttached()) return;
            $setSelection(selection.clone());
            $insertEditorLink(url, name.value);
        }
        modal.close();
        editor.update(applyLink, { tag: "history-push" });
        editor.focus();
    }
    form.addEventListener("submit", submitLink);
    modal.open();
    href.focus();
}
