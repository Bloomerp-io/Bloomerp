import getSdk from "@/sdk/getSdk";
import BaseComponent, { getComponent } from "./BaseComponent";
import getGeneralModal from "@/utils/modals";
import { getCsrfToken } from "@/utils/cookies";
import htmx from "htmx.org";
import { t as _ } from "@/utils/i18n";
import showMessage from "@/utils/messages";
import { MessageType } from "./UiMessage";
import DetailTabs from "./detail_view_components/DetailTabs";
import ObjectCRUDViewContainer from "./detail_view_components/ObjectCRUDViewContainer";

type PreferenceRenameApi = {
    partialUpdate(id: string, payload: { name: string }): Promise<{ name?: string }>;
};

export class SelectPreference extends BaseComponent {
    private modelName: string | null = null;
    private readonly clickHandler = (event: Event) => this.handleClick(event);

    /** Bind row actions and the keyboard shortcut for saving a new preference. */
    public initialize(): void {
        this.modelName = this.element?.dataset.modelName || null;
        if (!this.element) return;
        this.element.addEventListener("click", this.clickHandler);
        this.element.addEventListener("keydown", this.handleSaveKeydown);
    }

    /** Release the chooser's delegated event handlers. */
    public destroy(): void {
        this.element?.removeEventListener("click", this.clickHandler);
        this.element?.removeEventListener("keydown", this.handleSaveKeydown);
    }

    /** Save the name through the SDK and update the labels in the open dropdown. */
    private async changeName(label: HTMLButtonElement, button: HTMLButtonElement, newName: string): Promise<void> {
        button.disabled = true;
        try {
            const sdk = getSdk() as unknown as Record<string, PreferenceRenameApi | undefined>;
            const modelApi = sdk[this.getApiProperty()];
            if (!modelApi) throw new Error("Preference API is not available.");
            const preference = await modelApi.partialUpdate(label.dataset.selectPreference || "", { name: newName });
            const savedName = preference.name ?? newName;
            const displayName = savedName === "Default" ? _("Default") : savedName;
            const triggerLabel = label.hasAttribute("data-selected-preference")
                ? label.closest("[data-dropdown-panel]")?.parentElement?.querySelector<HTMLElement>(
                    ':scope > button[name="preference-menu"] [data-dropdown-trigger-label]',
                )
                : null;
            const previousName = label.textContent?.trim();
            const triggerName = triggerLabel?.textContent?.trim();
            if (triggerLabel && (triggerName === previousName || (triggerName === "Default" && previousName === _("Default")))) {
                triggerLabel.textContent = displayName;
            }
            label.textContent = displayName;
        } catch {
            showMessage(_("Unable to save changes. Please try again."), MessageType.ERROR);
        } finally {
            button.disabled = false;
        }
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

    /** Dispatch actions from the preference row buttons. */
    private handleClick(event: Event): void {
        const target = event.target as HTMLElement;
        if (target.closest("[data-save-preference]")) {
            this.saveNewPreference();
            return;
        }

        const selectButton = target.closest<HTMLElement>("[data-select-preference]");
        if (selectButton) {
            const id = selectButton.dataset.selectPreference;
            if (id) void this.postPreference(this.getSelectPreferenceUrl(), { action: "select", preference_id: id });
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

        const renameButton = target.closest<HTMLButtonElement>("[data-rename-preference]");
        if (renameButton && !renameButton.disabled) this.beginRename(renameButton);
    }

    /** Save from the name field without submitting an enclosing record form. */
    private handleSaveKeydown = (event: KeyboardEvent): void => {
        if (event.key !== "Enter" || event.isComposing
            || !(event.target instanceof HTMLInputElement) || !event.target.matches("[data-new-preference-name]")) return;
        event.preventDefault();
        event.stopPropagation();
        this.saveNewPreference();
    };

    /** Create and select a named copy in the current preference scope. */
    private saveNewPreference(): void {
        const input = this.element?.querySelector<HTMLInputElement>("[data-new-preference-name]");
        const name = input?.value.trim();
        if (!input || !name) {
            input?.focus();
            return;
        }
        void this.postPreference(this.getNewPreferenceUrl(), { name }, input);
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

    /** Save within the current scope, then refresh the owning region or the chooser itself. */
    private async postPreference(
        url: string,
        fields: Record<string, string>,
        nameInput?: HTMLInputElement,
    ): Promise<void> {
        const chooser = this.element;
        if (!url || !chooser) return;

        const csrfToken = getCsrfToken();
        const scope = new URLSearchParams();
        for (const field of chooser.querySelectorAll<HTMLElement>("[data-preference-scope-key]")) {
            scope.set(field.dataset.preferenceScopeKey!, field.dataset.preferenceScopeValue ?? "");
        }
        const values = new URLSearchParams(scope);
        for (const [key, value] of Object.entries(fields)) values.set(key, value);
        if (csrfToken) values.set("csrfmiddlewaretoken", csrfToken);

        const owner = chooser.closest<HTMLElement>("[data-preference-refresh]");
        // Data views keep their current filter and search parameters on data-url.
        const ownerUrl = owner?.dataset.preferenceRefreshUrl ?? owner?.dataset.url;
        if (!ownerUrl && !nameInput) {
            void htmx.ajax("post", url, { values: Object.fromEntries(values) });
            return;
        }
        const region = owner && ownerUrl ? owner : chooser;
        const refreshUrl = ownerUrl || `${this.getSelectPreferenceUrl()}?${scope}`;
        const frame = region.dataset.preferenceRefresh === "detail-tabs"
            ? region.closest<HTMLElement>("[data-detail-view-grid]")
            : null;
        const lockedRegion = frame ?? region;
        if (lockedRegion.inert || !this.canReplaceRegion(lockedRegion)) return;

        const controller = new AbortController();
        const modal = region.closest('[bloomerp-component="modal"]');
        const previousFocus = document.activeElement;
        /** Stop refreshing an instance that has been dismissed. */
        const onModalClosed = (): void => controller.abort();
        modal?.addEventListener("bloomerp:modal-closed", onModalClosed, {
            signal: controller.signal,
            once: true,
        });
        lockedRegion.inert = true;
        lockedRegion.setAttribute("aria-busy", "true");
        let saved = false;
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "HX-Request": "true", "X-Bloomerp-Preference-Refresh": "true" },
                credentials: "same-origin",
                body: values,
                signal: controller.signal,
            });
            if (response.status !== 204) throw new Error("Unable to save preference.");
            saved = true;
            if (nameInput) nameInput.value = "";
            if (!region.isConnected || controller.signal.aborted) return;
            await this.refreshRegion(region, refreshUrl, controller.signal);
        } catch {
            if (region.isConnected && !controller.signal.aborted) {
                let message = _("Unable to save changes. Please try again.");
                if (saved) {
                    message = nameInput
                        ? _("The preference was saved, but this section could not be refreshed.")
                        : _("The preference was selected, but this section could not be refreshed. Select it again to retry.");
                }
                showMessage(message, MessageType.ERROR);
            }
        } finally {
            lockedRegion.inert = false;
            lockedRegion.removeAttribute("aria-busy");
            if (!controller.signal.aborted && region.isConnected && document.activeElement === document.body
                && previousFocus instanceof HTMLElement && previousFocus.isConnected) {
                previousFocus.focus({ preventScroll: true });
            }
            controller.abort();
        }
    }

    /** Check for edits in the layout or in the detail panel controlled by the tabs. */
    private canReplaceRegion(region: HTMLElement): boolean {
        let dirty = region.hasAttribute("data-preference-bound-form")
            || region.querySelector("[data-preference-bound-form]") !== null;
        for (const root of region.querySelectorAll<HTMLElement>('[bloomerp-component="object-crud-view-container"]')) {
            const form = getComponent(root);
            if (!(form instanceof ObjectCRUDViewContainer)) continue;
            if (form.isSavingForm) {
                showMessage(_("Wait for the form to finish saving before switching preferences."), MessageType.INFO);
                return false;
            }
            dirty ||= form.hasPendingFormChanges;
        }
        return !dirty || window.confirm(_("Switching preferences may discard unsaved changes. Continue?"));
    }

    /** Request the normal server render and swap the matching fragment into this exact instance. */
    private async refreshRegion(region: HTMLElement, path: string, signal: AbortSignal): Promise<void> {
        const tabs = region.dataset.preferenceRefresh === "detail-tabs" ? getComponent(region) : null;
        const embeddedPane = tabs instanceof DetailTabs
            ? region.closest<HTMLElement>('[data-split-view-detail-pane], [id^="drawer-detail-pane-"]')
            : null;
        const modalBody = region.closest<HTMLElement>("[data-modal-body]");
        let tabUrl: string | null = null;
        if (tabs instanceof DetailTabs) {
            tabUrl = embeddedPane || modalBody ? tabs.activeTabUrl : window.location.href;
        }
        const url = new URL(tabUrl ?? path, window.location.origin);
        if (url.origin !== window.location.origin) throw new Error("Invalid preference refresh URL.");
        const configuredTarget = region.dataset.preferenceRefreshTarget;
        const target = tabs instanceof DetailTabs
            ? embeddedPane?.id ?? "main-content"
            : configuredTarget?.startsWith("#") ? configuredTarget.slice(1)
                : modalBody?.id || region.id;
        const headers = new Headers({ "HX-Request": "true", "HX-Current-URL": window.location.href });
        if (target) headers.set("HX-Target", target);
        if (region.dataset.syncUrl === "true") headers.set("X-Bloomerp-Sync-Url", "true");
        const response = await fetch(url, { headers, credentials: "same-origin", cache: "no-store", signal });
        if (!response.ok || response.redirected || response.headers.has("HX-Redirect")) {
            throw new Error("Unable to render preference.");
        }
        const html = await response.text();
        if (!region.isConnected || signal.aborted) return;

        const selector = region.dataset.preferenceRefresh
            ? `[data-preference-refresh="${CSS.escape(region.dataset.preferenceRefresh)}"]`
            : '[bloomerp-component="select-preference"]';
        const fragment = new DOMParser().parseFromString(html, "text/html").querySelector<HTMLElement>(selector);
        if (!fragment || fragment.dataset.objectPk !== region.dataset.objectPk) {
            throw new Error("Preference region missing from the response.");
        }

        const parent = region.parentElement;
        const position = parent ? Array.from(parent.children).indexOf(region) : -1;
        htmx.swap(region, fragment.outerHTML, {
            swapStyle: "outerHTML",
            swapDelay: 0,
            settleDelay: htmx.config.defaultSettleDelay,
            ignoreTitle: true,
        }, {
            eventInfo: { target: parent },
            /** Restore focus inside the same instance once HTMX has connected its controls. */
            afterSettleCallback: (): void => {
                const updated = parent?.children[position];
                if (!(updated instanceof HTMLElement) || !updated.isConnected || !updated.matches(selector)) return;
                if (document.activeElement === document.body && !updated.closest('[aria-hidden="true"]')) {
                    const trigger = updated.querySelector<HTMLElement>('button[name="preference-menu"]')
                        ?? updated.querySelector<HTMLElement>('button[aria-haspopup="true"]');
                    trigger?.focus({ preventScroll: true });
                }
                this.activateAvailableTab(updated);
            },
        });
    }

    /** Follow the first internal tab if the new preference removed the active tab. */
    private activateAvailableTab(region: HTMLElement | null): void {
        if (region?.dataset.preferenceRefresh !== "detail-tabs" || region.querySelector('[data-tab-active="true"]')) return;
        region.querySelector<HTMLElement>("[data-tabs-strip] a[hx-get]")?.click();
    }

    /** Edit a preference in place, saving on Enter or blur and cancelling on Escape. */
    private beginRename(button: HTMLButtonElement): void {
        const row = button.closest<HTMLElement>("[data-preference-row]");
        const label = row?.querySelector<HTMLButtonElement>("[data-select-preference]");
        if (!label) return;

        const input = document.createElement("input");
        const previousName = label.textContent?.trim() || "";
        input.className = "input input-sm min-w-0 flex-1";
        input.maxLength = 255;
        input.setAttribute("aria-label", button.getAttribute("aria-label") || _("Rename preference"));
        input.value = previousName;

        /** Restore the row and issue at most one request for a changed name. */
        const finishRename = (save: boolean, restoreFocus: boolean): void => {
            input.removeEventListener("blur", onBlur);
            const name = input.value.trim();
            input.replaceWith(label);
            if (restoreFocus) label.focus({ preventScroll: true });
            if (save && name && name !== previousName) void this.changeName(label, button, name);
        };

        /** Save when the user moves focus away from the name. */
        const onBlur = (): void => finishRename(true, false);

        /** Handle edit keys before the enclosing dropdown can dismiss or navigate. */
        const onKeydown = (event: KeyboardEvent): void => {
            if (event.isComposing) return;
            if (event.key === "ArrowUp" || event.key === "ArrowDown") event.stopPropagation();
            if (event.key !== "Enter" && event.key !== "Escape") return;
            event.preventDefault();
            event.stopPropagation();
            finishRename(event.key === "Enter", true);
        };

        input.addEventListener("blur", onBlur);
        input.addEventListener("keydown", onKeydown);
        label.replaceWith(input);
        input.focus();
        input.select();
    }

    private getSelectPreferenceUrl(): string {
        return this.element?.dataset.selectPreferenceUrl || "";
    }

    /** Read the create endpoint for the preference model rendered in this chooser. */
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
