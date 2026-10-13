import getSdk from "@/sdk/getSdk";
import BaseComponent from "./BaseComponent";
import getGeneralModal from "@/utils/modals";
import { getCsrfToken } from "@/utils/cookies";
import htmx from "htmx.org";
import { t as _ } from "@/utils/i18n";

export class SelectPreference extends BaseComponent {
    private modelName: string | null = null;
    private readonly clickHandler = (event: Event) => this.handleClick(event);


    public initialize(): void {
        this.modelName = this.element?.dataset.modelName || null;
        if (!this.element) return;
        this.element.addEventListener("click", this.clickHandler);
    }

    public destroy(): void {
        this.element?.removeEventListener("click", this.clickHandler);
        
    }

    private async changeName(preferenceId: string, newName: string): Promise<void> {
        const modelApi = (getSdk() as any)[this.getApiProperty()] as {
            partialUpdate(id: string, payload: { name: string }): Promise<unknown>;
        };
        if (!modelApi) throw new Error("Preference API is not available.");
        await modelApi.partialUpdate(preferenceId, { name: newName });
        window.location.reload();
    }

    /** Open sharing with a complete translated title. */
    private launchShareModal(preferenceId: string): void {
        const modal = getGeneralModal();
        const title = _("Share {preference}").replace("{preference}", this.element?.dataset.modelVerboseName || _("Preference"));
        modal.setTitle(title);
        htmx.ajax("get", this.getSharePreferenceUrl(preferenceId), {
            target: modal.getBodyElement(),
            swap: "innerHTML",
        }).then(() => modal.open());
    }

    private handleClick(event: Event): void {
        const target = event.target as HTMLElement;
        const selectButton = target.closest<HTMLElement>("[data-select-preference]");
        if (selectButton) {
            this.postSelection(selectButton.dataset.selectPreference || "");
            return;
        }

        const shareButton = target.closest<HTMLElement>("[data-share-preference]");
        if (shareButton) {
            this.launchShareModal(shareButton.dataset.sharePreference || "");
            return;
        }

        const deleteButton = target.closest<HTMLElement>("[data-delete-preference]");
        if (deleteButton) {
            this.launchDeleteModal(deleteButton.dataset.deletePreference || "");
            return;
        }

        const renameButton = target.closest<HTMLElement>("[data-rename-preference]");
        if (renameButton) this.beginRename(renameButton.dataset.renamePreference || "", renameButton);
    }

    /** Open deletion with a complete translated title. */
    private launchDeleteModal(preferenceId: string): void {
        if (!preferenceId) return;

        const modal = getGeneralModal();
        const title = _("Delete {preference}").replace("{preference}", this.element?.dataset.modelVerboseName || _("Preference"));
        modal.setTitle(title);
        htmx.ajax("get", this.getDeletePreferenceUrl(preferenceId), {
            target: modal.getBodyElement(),
            swap: "innerHTML",
        }).then(() => modal.open());
    }

    private postSelection(preferenceId: string): void {
        const csrfToken = getCsrfToken();
        htmx.ajax("post", this.getSelectPreferenceUrl(), {
            values: {
                action: "select",
                preference_id: preferenceId,
                ...(csrfToken ? { csrfmiddlewaretoken: csrfToken } : {}),
            },
            headers: csrfToken ? { "X-CSRFToken": csrfToken } : {},
        });
    }

    private beginRename(preferenceId: string, button: HTMLElement): void {
        const row = button.closest<HTMLElement>("[data-preference-row]");
        const label = row?.querySelector<HTMLElement>("[data-select-preference]");
        if (!row || !label) return;

        const input = document.createElement("input");
        input.className = "input input-sm min-w-0 flex-1";
        input.value = label.textContent?.trim() || "";
        label.replaceWith(input);
        input.focus();
        input.select();

        const save = async () => {
            const name = input.value.trim();
            if (name) await this.changeName(preferenceId, name);
        };
        input.addEventListener("keydown", (keyboardEvent) => {
            if (keyboardEvent.key === "Enter") void save();
            if (keyboardEvent.key === "Escape") window.location.reload();
        });
        input.addEventListener("blur", () => void save(), { once: true });
    }

    private getSelectPreferenceUrl(): string {
        return this.element?.dataset.selectPreferenceUrl || "";
    }

    private getNewPreferenceUrl(): string {
        return this.element?.dataset.newPreferenceUrl || "";
    }

    private getSharePreferenceUrl(preferenceId: string): string {
        return (this.element?.dataset.sharePreferenceUrl || "").replace("REPLACE_WITH_ID", preferenceId);
    }

    private getDeletePreferenceUrl(preferenceId: string): string {
        return (this.element?.dataset.deletePreferenceUrl || "").replace("REPLACE_WITH_ID", preferenceId);
    }

    private getApiProperty(): string {
        const singular = `${this.modelName?.charAt(0).toLowerCase() || ""}${this.modelName?.slice(1) || ""}`;
        return singular.endsWith("y") ? `${singular.slice(0, -1)}ies` : `${singular}s`;
    }
}
