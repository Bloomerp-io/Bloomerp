import { createModalInstance } from "@/utils/modals";
import { t } from "@/utils/i18n";

/** Choose any RGB color without changing the saved editor range until Apply is pressed. */
export function promptColorSelection(host: HTMLElement, initialColor: string, onApply: (color: string) => void): void {
    const modal = createModalInstance("bloomerp-general-use-modal", host);
    const body = modal.getBodyElement();
    if (!body) return;
    modal.setTitle(t("Custom text color"));
    modal.setSize("sm");
    const form = document.createElement("form");
    form.className = "flex flex-col gap-3";
    const label = document.createElement("label");
    label.textContent = t("Color");
    const input = document.createElement("input");
    input.type = "color";
    input.value = initialColor;
    input.className = "input w-full h-12 cursor-pointer p-1";
    label.appendChild(input);
    const actions = document.createElement("div");
    actions.className = "flex justify-end gap-2";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn btn-secondary";
    cancel.textContent = t("Cancel");
    /** Dismiss the chooser without applying formatting or creating a history entry. */
    function cancelColor(): void { modal.close(); }
    cancel.addEventListener("click", cancelColor);
    const apply = document.createElement("button");
    apply.type = "submit";
    apply.className = "btn btn-primary";
    apply.textContent = t("Apply");
    actions.append(cancel, apply);
    form.append(label, actions);
    /** Commit a browser-normalized color through the invoking editor action. */
    function submitColor(event: SubmitEvent): void {
        event.preventDefault();
        modal.close();
        if (host.isConnected) onApply(input.value);
    }
    form.addEventListener("submit", submitColor);
    body.replaceChildren(form);
    modal.open();
    input.focus();
}
