import { BaseDataViewCell } from "./BaseDataViewCell";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { attachObjectPreviewTooltip } from "@/utils/objectPreviewTooltip";
import { getCsrfToken } from "@/utils/cookies";
import { MessageType } from "../UiMessage";
import showMessage from "@/utils/messages";

/** Browse physical nodes or reference-derived folders without creating folders. */
export class FileBrowser extends BaseDataViewComponent {
    protected cellClass = BaseDataViewCell;
    private previewCleanups: Array<() => void> = [];

    /** Delegate navigation and upload events through the component lifecycle. */
    public override initialize(): void {
        super.initialize();
        if (!this.element) return;
        const signal = this.ensureAbortController().signal;
        this.element.addEventListener("click", this.onNavigation, { signal });
        this.element.addEventListener("change", this.onChange, { signal });
        this.bindObjectPreviews();
    }

    /** Rebind object previews after row replacement. */
    public override onAfterSwap(): void { this.bindObjectPreviews(); }

    /** Release previews together with component event listeners. */
    public override destroy(): void {
        this.clearObjectPreviews();
        super.destroy();
    }

    /** Remove tooltip listeners from the previous rendered rows. */
    private clearObjectPreviews(): void {
        for (const cleanup of this.previewCleanups) cleanup();
        this.previewCleanups = [];
    }

    /** Attach object-preview tooltips only to authorized owner links. */
    private bindObjectPreviews(): void {
        this.clearObjectPreviews();
        for (const element of this.element?.querySelectorAll<HTMLElement>("[data-preview-object-id]") ?? []) {
            const objectId = element.dataset.previewObjectId;
            const contentTypeId = element.dataset.previewContentTypeId;
            if (objectId && contentTypeId) this.previewCleanups.push(attachObjectPreviewTooltip({ element, objectId, contentTypeId }));
        }
    }

    /** Preserve filters while navigating, clearing tokens from the other folder mode. */
    private onNavigation = (event: MouseEvent): void => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest<HTMLElement>("[data-browser-path]");
        if (!button || !this.element?.contains(button)) return;
        event.preventDefault();
        const mode = this.element.dataset.folderType ?? "virtual";
        this.dataViewContainer?.filter({
            folder_type: mode,
            virtual_path: mode === "virtual" ? button.dataset.browserPath : null,
            folder_id: mode === "physical" ? button.dataset.browserFolder : null,
        });
    };

    /** Reset navigation on mode changes or upload the chosen files to the current object. */
    private onChange = (event: Event): void => {
        const target = event.target;
        if (target instanceof HTMLSelectElement && target.matches("[data-folder-type-select]")) {
            this.dataViewContainer?.filter({ folder_type: target.value, folder_id: null, virtual_path: null });
        } else if (target instanceof HTMLInputElement && target.matches("[data-file-browser-upload-input]")) {
            void this.uploadFiles(target);
        }
    };

    /** Upload each file through the node API, retaining any successful files on partial failure. */
    private async uploadFiles(input: HTMLInputElement): Promise<void> {
        const files = Array.from(input.files ?? []);
        const url = this.element?.dataset.uploadUrl;
        if (!url || !files.length) return;
        const signal = this.ensureAbortController().signal;
        input.disabled = true;
        try {
            for (const file of files) {
                const data = new FormData();
                data.set("file", file);
                const modelLabel = this.element?.dataset.uploadModelLabel;
                const objectId = this.element?.dataset.uploadObjectId;
                if (modelLabel && objectId) {
                    data.set("model_label", modelLabel);
                    data.set("object_id", objectId);
                }
                const response = await fetch(url, {
                    method: "POST", body: data, credentials: "same-origin", signal,
                    headers: { "X-CSRFToken": getCsrfToken() ?? "" },
                });
                if (!response.ok) throw new Error(`Could not upload ${file.name}`);
                await response.json();
            }
            showMessage("Files uploaded", MessageType.SUCCESS);
        } catch (error) {
            if (!signal.aborted) showMessage(error instanceof Error ? error.message : "Upload failed", MessageType.ERROR);
        } finally {
            input.value = "";
            input.disabled = false;
            if (!signal.aborted) this.dataViewContainer?.refresh();
        }
    }

    /** Keep navigation on the selected browser cell. */
    moveCellUp(): BaseDataViewCell { return this.currentCell as BaseDataViewCell; }
    /** Keep navigation on the selected browser cell. */
    moveCellDown(): BaseDataViewCell { return this.currentCell as BaseDataViewCell; }
    /** Keep navigation on the selected browser cell. */
    moveCellLeft(): BaseDataViewCell { return this.currentCell as BaseDataViewCell; }
    /** Keep navigation on the selected browser cell. */
    moveCellRight(): BaseDataViewCell { return this.currentCell as BaseDataViewCell; }
}
