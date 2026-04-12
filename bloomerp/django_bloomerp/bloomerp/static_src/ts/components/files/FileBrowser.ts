import htmx from "htmx.org";

import BaseComponent, { getComponent } from "../BaseComponent";
import FilterContainer from "../Filters";
import { MessageType } from "../UiMessage";
import { getCsrfToken } from "@/utils/cookies";
import showMessage from "@/utils/messages";
import getGeneralModal from "@/utils/modals";

type FolderOption = {
    id: string;
    label: string;
};

type FileBrowserModalResult =
    | { confirmed: true; value: string }
    | { confirmed: false };

export default class FileBrowser extends BaseComponent {
    private fullPath: string | null = null;
    private baseUrl: string | null = null;
    private moduleId: string | null = null;
    private contentTypeId: string | null = null;
    private objectId: string | null = null;
    private currentFolderId: string | null = null;
    private searchInput: HTMLInputElement | null = null;
    private uploadInput: HTMLInputElement | null = null;
    private searchTimer: number | null = null;
    private folderOptions: FolderOption[] = [];
    private afterSwapHandler: ((event: Event) => void) | null = null;
    private uploadTriggerHandler: ((event: Event) => void) | null = null;
    private createFolderHandler: ((event: Event) => void) | null = null;
    private syncUrl: boolean = false;

    public initialize(): void {
        if (!this.element) return;

        this.fullPath = this.element.dataset.url ?? null;
        this.baseUrl = this.element.dataset.baseUrl ?? null;
        this.moduleId = this.element.dataset.moduleId || null;
        this.contentTypeId = this.element.dataset.contentTypeId || null;
        this.objectId = this.element.dataset.objectId || null;
        this.currentFolderId = this.element.dataset.folderId || null;
        this.syncUrl = this.element.dataset.syncUrl === "true";
        this.searchInput = this.element.querySelector<HTMLInputElement>("[data-search-input]");
        this.uploadInput = this.element.querySelector<HTMLInputElement>("[data-upload-input]");

        try {
            this.folderOptions = JSON.parse(this.element.dataset.folderOptions || "[]");
        } catch {
            this.folderOptions = [];
        }

        this.bindSearch();
        this.bindClicks();
        this.bindUploadInput();
        this.bindDragAndDrop();
        this.bindAfterSwap();
    }

    public destroy(): void {
        if (this.searchTimer) {
            window.clearTimeout(this.searchTimer);
            this.searchTimer = null;
        }

        if (this.afterSwapHandler) {
            this.element?.removeEventListener("htmx:afterSwap", this.afterSwapHandler);
            this.afterSwapHandler = null;
        }

        const uploadTrigger = this.element?.querySelector<HTMLElement>("[data-trigger-upload]");
        if (uploadTrigger && this.uploadTriggerHandler) {
            uploadTrigger.removeEventListener("click", this.uploadTriggerHandler);
            this.uploadTriggerHandler = null;
        }

        const createFolderTrigger = this.element?.querySelector<HTMLElement>("[data-create-folder]");
        if (createFolderTrigger && this.createFolderHandler) {
            createFolderTrigger.removeEventListener("click", this.createFolderHandler);
            this.createFolderHandler = null;
        }
    }

    private bindSearch(): void {
        if (!this.searchInput) return;

        this.searchInput.addEventListener("input", () => {
            if (this.searchTimer) {
                window.clearTimeout(this.searchTimer);
            }

            this.searchTimer = window.setTimeout(() => {
                this.applyUrlMutation((url) => {
                    const value = this.searchInput?.value.trim() || "";
                    if (value) {
                        url.searchParams.set("q", value);
                    } else {
                        url.searchParams.delete("q");
                    }
                    url.searchParams.delete("page");
                }, { partial: true });
            }, 200);
        });
    }

    private bindClicks(): void {
        this.element?.addEventListener("click", (event) => {
            const target = event.target as HTMLElement | null;
            if (!target) return;

            const clearFilters = target.closest<HTMLElement>("[data-clear-filters]");
            if (clearFilters) {
                this.clearAllFilters();
                return;
            }

            const openRoot = target.closest<HTMLElement>("[data-open-root]");
            if (openRoot) {
                this.openRoot();
                return;
            }

            const removeFilter = target.closest<HTMLElement>("[data-filter-remove]");
            if (removeFilter) {
                const badge = removeFilter.closest<HTMLElement>("[data-filter-key]");
                const key = badge?.dataset.filterKey;
                if (key) {
                    this.removeFilter(key);
                }
                return;
            }

            const applyFiltersButton = target.closest<HTMLElement>("[data-apply-filters]");
            if (applyFiltersButton) {
                this.applyFilters();
                return;
            }

            const viewTypeButton = target.closest<HTMLElement>("[data-view-type]");
            if (viewTypeButton) {
                const viewType = viewTypeButton.dataset.viewType;
                if (viewType) {
                    void this.updatePreference(viewType);
                }
                return;
            }

            const uploadTrigger = target.closest<HTMLElement>("[data-trigger-upload]");
            if (uploadTrigger) {
                this.uploadInput?.click();
                return;
            }

            const createFolder = target.closest<HTMLElement>("[data-create-folder]");
            if (createFolder) {
                void this.promptCreateFolder();
                return;
            }

            const openFolder = target.closest<HTMLElement>("[data-open-folder]");
            if (openFolder) {
                this.openFolder(openFolder.dataset.openFolder || "");
                return;
            }

            const openModule = target.closest<HTMLElement>("[data-open-module]");
            if (openModule) {
                this.openModule(openModule.dataset.openModule || "");
                return;
            }

            const openModel = target.closest<HTMLElement>("[data-open-model]");
            if (openModel) {
                this.openModel(openModel.dataset.openModel || "");
                return;
            }

            const pageButton = target.closest<HTMLElement>("[data-page]");
            if (pageButton) {
                const page = pageButton.dataset.page;
                if (page) {
                    this.applyUrlMutation((url) => {
                        url.searchParams.set("page", page);
                    });
                }
                return;
            }

            const renameFile = target.closest<HTMLElement>("[data-rename-file]");
            if (renameFile) {
                void this.promptRename("file", renameFile.dataset.renameFile || "", renameFile.dataset.currentName || "");
                return;
            }

            const renameFolder = target.closest<HTMLElement>("[data-rename-folder]");
            if (renameFolder) {
                void this.promptRename("folder", renameFolder.dataset.renameFolder || "", renameFolder.dataset.currentName || "");
                return;
            }

            const moveFile = target.closest<HTMLElement>("[data-move-file]");
            if (moveFile) {
                const fileId = moveFile.dataset.moveFile || "";
                if (fileId) {
                    void this.promptMoveFile(fileId);
                }
                return;
            }

            const deleteFile = target.closest<HTMLElement>("[data-delete-file]");
            if (deleteFile) {
                const fileId = deleteFile.dataset.deleteFile || "";
                if (fileId) {
                    void this.deleteItem("file", fileId);
                }
                return;
            }

            const deleteFolder = target.closest<HTMLElement>("[data-delete-folder]");
            if (deleteFolder) {
                const folderId = deleteFolder.dataset.deleteFolder || "";
                if (folderId) {
                    void this.deleteItem("folder", folderId);
                }
            }
        });

        const uploadTrigger = this.element?.querySelector<HTMLElement>("[data-trigger-upload]");
        if (uploadTrigger) {
            this.uploadTriggerHandler = (event: Event) => {
                event.preventDefault();
                event.stopPropagation();
                this.uploadInput?.click();
            };
            uploadTrigger.addEventListener("click", this.uploadTriggerHandler);
        }

        const createFolderTrigger = this.element?.querySelector<HTMLElement>("[data-create-folder]");
        if (createFolderTrigger) {
            this.createFolderHandler = (event: Event) => {
                event.preventDefault();
                event.stopPropagation();
                void this.promptCreateFolder();
            };
            createFolderTrigger.addEventListener("click", this.createFolderHandler);
        }
    }

    private bindUploadInput(): void {
        if (!this.uploadInput) return;

        this.uploadInput.addEventListener("change", async () => {
            const files = this.uploadInput?.files;
            if (!files || files.length === 0) return;

            await this.uploadFiles(files, this.currentFolderId);
            this.uploadInput.value = "";
        });
    }

    private bindDragAndDrop(): void {
        if (!this.element) return;

        const dropzone = this.element.querySelector<HTMLElement>("[data-upload-dropzone]");
        if (dropzone) {
            dropzone.addEventListener("dragover", (event) => {
                event.preventDefault();
                dropzone.classList.add("border-primary", "bg-primary/5");
            });
            dropzone.addEventListener("dragleave", () => {
                dropzone.classList.remove("border-primary", "bg-primary/5");
            });
            dropzone.addEventListener("drop", async (event) => {
                event.preventDefault();
                dropzone.classList.remove("border-primary", "bg-primary/5");

                const files = event.dataTransfer?.files;
                if (files && files.length > 0) {
                    await this.uploadFiles(files, this.currentFolderId);
                }
            });
        }

        const draggableItems = this.element.querySelectorAll<HTMLElement>("[data-item-type]");
        draggableItems.forEach((item) => {
            item.addEventListener("dragstart", (event) => {
                const itemType = item.dataset.itemType || "";
                const fileId = item.dataset.fileItemId || "";
                const folderId = item.dataset.folderId || "";
                item.classList.add("opacity-50");

                if (!event.dataTransfer) return;
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/file-browser-item-type", itemType);
                if (fileId) event.dataTransfer.setData("text/file-id", fileId);
                if (folderId) event.dataTransfer.setData("text/folder-id", folderId);
            });

            item.addEventListener("dragend", () => {
                item.classList.remove("opacity-50");
            });
        });

        const folderDropzones = this.element.querySelectorAll<HTMLElement>("[data-folder-dropzone]");
        folderDropzones.forEach((folder) => {
            folder.addEventListener("dragover", (event) => {
                event.preventDefault();
                folder.classList.add("ring-2", "ring-primary/30");
            });

            folder.addEventListener("dragleave", () => {
                folder.classList.remove("ring-2", "ring-primary/30");
            });

            folder.addEventListener("drop", async (event) => {
                event.preventDefault();
                folder.classList.remove("ring-2", "ring-primary/30");

                const targetFolderId = folder.dataset.folderDropzone || "";
                if (!targetFolderId) return;

                const droppedFiles = event.dataTransfer?.files;
                if (droppedFiles && droppedFiles.length > 0) {
                    await this.uploadFiles(droppedFiles, targetFolderId);
                    return;
                }

                const itemType = event.dataTransfer?.getData("text/file-browser-item-type") || "";
                if (itemType === "file") {
                    const fileId = event.dataTransfer?.getData("text/file-id") || "";
                    if (fileId) {
                        await this.moveItem({
                            itemType: "file",
                            fileId,
                            targetFolderId,
                        });
                    }
                    return;
                }

                if (itemType === "folder") {
                    const folderId = event.dataTransfer?.getData("text/folder-id") || "";
                    if (folderId && folderId !== targetFolderId) {
                        await this.moveItem({
                            itemType: "folder",
                            folderId,
                            targetFolderId,
                        });
                    }
                }
            });
        });
    }

    private applyFilters(): void {
        const filterContainer = this.getFilterContainer();
        const filters = filterContainer?.getFilters() || [];

        this.applyUrlMutation((url) => {
            const reserved = new Set(["q", "page", "folder_id", "content_type_id", "object_id", "view_type"]);
            Array.from(url.searchParams.keys()).forEach((key) => {
                if (!reserved.has(key)) {
                    url.searchParams.delete(key);
                }
            });

            filters.forEach((filter) => {
                if (!filter.value || !filter.operator) return;
                const key = `${filter.field}__${filter.operator}`;
                url.searchParams.delete(key);

                if (Array.isArray(filter.value)) {
                    filter.value.forEach((entry) => url.searchParams.append(key, String(entry)));
                } else {
                    url.searchParams.append(key, String(filter.value));
                }
            });

            url.searchParams.delete("page");
        });

        this.resetFilterSection();
    }

    private removeFilter(key: string): void {
        this.applyUrlMutation((url) => {
            url.searchParams.delete(key);
            url.searchParams.delete("page");
        });
    }

    private clearAllFilters(): void {
        this.applyUrlMutation((url) => {
            const reserved = new Set(["q", "page", "module_id", "folder_id", "content_type_id", "object_id", "view_type"]);
            Array.from(url.searchParams.keys()).forEach((key) => {
                if (!reserved.has(key)) {
                    url.searchParams.delete(key);
                }
            });
            url.searchParams.delete("page");
        });

        this.resetFilterSection();
    }

    private openFolder(folderId: string): void {
        this.applyUrlMutation((url) => {
            if (folderId) {
                url.searchParams.set("folder_id", folderId);
            } else {
                url.searchParams.delete("folder_id");
            }
            url.searchParams.delete("page");
        });
    }

    private openRoot(): void {
        this.applyUrlMutation((url) => {
            url.searchParams.delete("module_id");
            url.searchParams.delete("content_type_id");
            url.searchParams.delete("object_id");
            url.searchParams.delete("folder_id");
            url.searchParams.delete("page");
        });
    }

    private openModule(moduleId: string): void {
        this.applyUrlMutation((url) => {
            if (moduleId) {
                url.searchParams.set("module_id", moduleId);
            } else {
                url.searchParams.delete("module_id");
            }
            url.searchParams.delete("content_type_id");
            url.searchParams.delete("object_id");
            url.searchParams.delete("folder_id");
            url.searchParams.delete("page");
        });
    }

    private openModel(contentTypeId: string): void {
        this.applyUrlMutation((url) => {
            url.searchParams.delete("module_id");
            if (contentTypeId) {
                url.searchParams.set("content_type_id", contentTypeId);
            } else {
                url.searchParams.delete("content_type_id");
            }
            url.searchParams.delete("object_id");
            url.searchParams.delete("folder_id");
            url.searchParams.delete("page");
        });
    }

    private async updatePreference(viewType: string): Promise<void> {
        if (!this.element?.dataset.preferenceUrl) return;

        const formData = new FormData();
        formData.append("view_type", viewType);

        const response = await fetch(this.element.dataset.preferenceUrl, {
            method: "POST",
            body: formData,
            headers: this.buildRequestHeaders(),
        });

        if (!response.ok) {
            showMessage("Could not update file browser view", MessageType.ERROR);
            return;
        }

        await this.reload();
    }

    private async promptCreateFolder(): Promise<void> {
        const result = await this.showTextInputModal({
            title: "Create Folder",
            label: "Folder name",
            submitText: "Create",
            defaultValue: "",
            placeholder: "Enter folder name",
        });
        if (!result.confirmed) return;

        const name = result.value.trim();
        if (!name) return;

        const url = this.element?.dataset.createFolderUrl;
        if (!url) return;

        const formData = new FormData();
        formData.append("name", name);
        if (this.currentFolderId) {
            formData.append("parent_folder_id", this.currentFolderId);
        }
        if (this.contentTypeId) {
            formData.append("content_type_id", this.contentTypeId);
        }
        if (this.objectId) {
            formData.append("object_id", this.objectId);
        }

        const response = await fetch(url, {
            method: "POST",
            body: formData,
            headers: this.buildRequestHeaders(),
        });

        if (!response.ok) {
            showMessage("Could not create folder", MessageType.ERROR);
            return;
        }

        showMessage("Folder created", MessageType.SUCCESS);
        await this.reload();
    }

    private async promptRename(itemType: "file" | "folder", id: string, currentName: string): Promise<void> {
        if (!id) return;

        const result = await this.showTextInputModal({
            title: itemType === "file" ? "Rename File" : "Rename Folder",
            label: "Name",
            submitText: "Save",
            defaultValue: currentName,
            placeholder: "Enter name",
        });
        if (!result.confirmed) return;

        const name = result.value.trim();
        if (!name) return;

        const url = this.element?.dataset.renameUrl;
        if (!url) return;

        const formData = new FormData();
        formData.append("item_type", itemType);
        formData.append("name", name);
        formData.append(itemType === "file" ? "file_id" : "folder_id", id);

        const response = await fetch(url, {
            method: "POST",
            body: formData,
            headers: this.buildRequestHeaders(),
        });

        if (!response.ok) {
            showMessage("Could not rename item", MessageType.ERROR);
            return;
        }

        showMessage("Name updated", MessageType.SUCCESS);
        await this.reload();
    }

    private async promptMoveFile(fileId: string): Promise<void> {
        const result = await this.showFolderSelectModal({
            title: "Move File",
            label: "Destination folder",
            submitText: "Move",
        });
        if (!result.confirmed) return;

        await this.moveItem({
            itemType: "file",
            fileId,
            targetFolderId: result.value,
        });
    }

    private async moveItem(args: {
        itemType: "file" | "folder";
        fileId?: string;
        folderId?: string;
        targetFolderId?: string | null;
    }): Promise<void> {
        const url = this.element?.dataset.moveUrl;
        if (!url) return;

        const formData = new FormData();
        formData.append("item_type", args.itemType);
        if (args.fileId) formData.append("file_id", args.fileId);
        if (args.folderId) formData.append("folder_id", args.folderId);
        if (args.targetFolderId) formData.append("target_folder_id", args.targetFolderId);

        const response = await fetch(url, {
            method: "POST",
            body: formData,
            headers: this.buildRequestHeaders(),
        });

        if (!response.ok) {
            showMessage("Could not move item", MessageType.ERROR);
            return;
        }

        showMessage("Item moved", MessageType.SUCCESS);
        await this.reload();
    }

    private async deleteItem(itemType: "file" | "folder", id: string): Promise<void> {
        const previewUrl = this.element?.dataset.deletePreviewUrl;
        const deleteUrl = this.element?.dataset.deleteUrl;
        if (!previewUrl || !deleteUrl) return;

        const previewParams = new URLSearchParams({
            item_type: itemType,
            [`${itemType}_id`]: id,
        });

        const previewResponse = await fetch(`${previewUrl}?${previewParams.toString()}`, {
            headers: this.buildRequestHeaders(),
        });

        if (!previewResponse.ok) {
            showMessage("Could not prepare delete action", MessageType.ERROR);
            return;
        }

        const preview = await previewResponse.json();
        const confirmed = await this.showConfirmationModal({
            title: itemType === "folder" ? "Delete Folder" : "Delete File",
            message:
                itemType === "folder"
                    ? `Delete ${preview.folders} folder(s) and ${preview.files} file(s)?`
                    : "Delete this file?",
            confirmText: "Delete",
            confirmClass: "btn btn-danger btn-sm",
        });

        if (!confirmed) return;

        const formData = new FormData();
        formData.append("item_type", itemType);
        formData.append(`${itemType}_id`, id);

        const response = await fetch(deleteUrl, {
            method: "POST",
            body: formData,
            headers: this.buildRequestHeaders(),
        });

        if (!response.ok) {
            showMessage("Could not delete item", MessageType.ERROR);
            return;
        }

        showMessage("Item deleted", MessageType.SUCCESS);
        await this.reload();
    }

    private async uploadFiles(files: FileList, folderId: string | null): Promise<void> {
        const url = this.element?.dataset.uploadUrl;
        if (!url) return;

        const formData = new FormData();
        Array.from(files).forEach((file) => formData.append("files", file));
        if (folderId) {
            formData.append("folder_id", folderId);
        }
        if (this.contentTypeId) {
            formData.append("content_type_id", this.contentTypeId);
        }
        if (this.objectId) {
            formData.append("object_id", this.objectId);
        }

        const response = await fetch(url, {
            method: "POST",
            body: formData,
            headers: this.buildRequestHeaders(),
        });

        if (!response.ok) {
            showMessage("Could not upload files", MessageType.ERROR);
            return;
        }

        showMessage("Files uploaded", MessageType.SUCCESS);
        await this.reload();
    }

    private getFilterContainer(): FilterContainer | null {
        const contentTypeId = this.element?.dataset.filterContentTypeId;
        if (!contentTypeId) return null;

        const filterElement = document.getElementById(`filter-container-${contentTypeId}`) as HTMLElement | null;
        if (!filterElement) return null;

        return getComponent(filterElement) as FilterContainer | null;
    }

    private async showTextInputModal(args: {
        title: string;
        label: string;
        submitText: string;
        defaultValue: string;
        placeholder?: string;
    }): Promise<FileBrowserModalResult> {
        const modal = getGeneralModal();
        const body = modal.getBodyElement();
        if (!body) {
            return { confirmed: false };
        }

        modal.setTitle(args.title);
        body.innerHTML = `
            <form class="flex flex-col gap-4" data-file-browser-modal-form>
                <label class="form-control w-full gap-2">
                    <span class="label-text text-sm font-medium text-gray-700">${this.escapeHtml(args.label)}</span>
                    <input
                        type="text"
                        class="input input-bordered w-full"
                        value="${this.escapeHtml(args.defaultValue)}"
                        placeholder="${this.escapeHtml(args.placeholder || "")}" 
                        data-file-browser-modal-input
                    />
                </label>
                <div class="flex justify-end gap-2">
                    <button type="button" class="btn btn-neutral btn-sm" data-file-browser-modal-cancel>Cancel</button>
                    <button type="submit" class="btn btn-primary btn-sm">${this.escapeHtml(args.submitText)}</button>
                </div>
            </form>
        `;

        return await this.awaitModalResult<FileBrowserModalResult>((resolve) => {
            const form = body.querySelector<HTMLElement>("[data-file-browser-modal-form]");
            const input = body.querySelector<HTMLInputElement>("[data-file-browser-modal-input]");
            const cancelButton = body.querySelector<HTMLElement>("[data-file-browser-modal-cancel]");
            if (!form || !input || !cancelButton) {
                resolve({ confirmed: false });
                return;
            }

            cancelButton.addEventListener("click", () => {
                modal.close();
                resolve({ confirmed: false });
            }, { once: true });

            form.addEventListener("submit", (event) => {
                event.preventDefault();
                const value = input.value;
                modal.close();
                resolve({ confirmed: true, value });
            }, { once: true });

            modal.open();
            window.setTimeout(() => {
                input.focus();
                input.select();
            }, 0);
        }, modal, { confirmed: false } as FileBrowserModalResult);
    }

    private async showFolderSelectModal(args: {
        title: string;
        label: string;
        submitText: string;
    }): Promise<FileBrowserModalResult> {
        const modal = getGeneralModal();
        const body = modal.getBodyElement();
        if (!body) {
            return { confirmed: false };
        }

        modal.setTitle(args.title);
        const optionsMarkup = [
            `<option value="">Root</option>`,
            ...this.folderOptions.map((option) => (
                `<option value="${this.escapeHtml(option.id)}"${option.id === this.currentFolderId ? " selected" : ""}>${this.escapeHtml(option.label)}</option>`
            )),
        ].join("");

        body.innerHTML = `
            <form class="flex flex-col gap-4" data-file-browser-modal-form>
                <label class="form-control w-full gap-2">
                    <span class="label-text text-sm font-medium text-gray-700">${this.escapeHtml(args.label)}</span>
                    <select class="select select-bordered w-full" data-file-browser-modal-select>
                        ${optionsMarkup}
                    </select>
                </label>
                <div class="flex justify-end gap-2">
                    <button type="button" class="btn btn-neutral btn-sm" data-file-browser-modal-cancel>Cancel</button>
                    <button type="submit" class="btn btn-primary btn-sm">${this.escapeHtml(args.submitText)}</button>
                </div>
            </form>
        `;

        return await this.awaitModalResult<FileBrowserModalResult>((resolve) => {
            const form = body.querySelector<HTMLElement>("[data-file-browser-modal-form]");
            const select = body.querySelector<HTMLSelectElement>("[data-file-browser-modal-select]");
            const cancelButton = body.querySelector<HTMLElement>("[data-file-browser-modal-cancel]");
            if (!form || !select || !cancelButton) {
                resolve({ confirmed: false });
                return;
            }

            cancelButton.addEventListener("click", () => {
                modal.close();
                resolve({ confirmed: false });
            }, { once: true });

            form.addEventListener("submit", (event) => {
                event.preventDefault();
                modal.close();
                resolve({ confirmed: true, value: select.value });
            }, { once: true });

            modal.open();
            window.setTimeout(() => select.focus(), 0);
        }, modal, { confirmed: false } as FileBrowserModalResult);
    }

    private async showConfirmationModal(args: {
        title: string;
        message: string;
        confirmText: string;
        confirmClass?: string;
    }): Promise<boolean> {
        const modal = getGeneralModal();
        const body = modal.getBodyElement();
        if (!body) return false;

        modal.setTitle(args.title);
        body.innerHTML = `
            <div class="flex flex-col gap-4" data-file-browser-modal-confirm>
                <p class="text-sm text-gray-700">${this.escapeHtml(args.message)}</p>
                <div class="flex justify-end gap-2">
                    <button type="button" class="btn btn-neutral btn-sm" data-file-browser-modal-cancel>Cancel</button>
                    <button type="button" class="${this.escapeHtml(args.confirmClass || "btn btn-primary btn-sm")}" data-file-browser-modal-confirm-button>${this.escapeHtml(args.confirmText)}</button>
                </div>
            </div>
        `;

        return await this.awaitModalResult((resolve) => {
            const cancelButton = body.querySelector<HTMLElement>("[data-file-browser-modal-cancel]");
            const confirmButton = body.querySelector<HTMLElement>("[data-file-browser-modal-confirm-button]");
            if (!cancelButton || !confirmButton) {
                resolve(false);
                return;
            }

            cancelButton.addEventListener("click", () => {
                modal.close();
                resolve(false);
            }, { once: true });

            confirmButton.addEventListener("click", () => {
                modal.close();
                resolve(true);
            }, { once: true });

            modal.open();
            window.setTimeout(() => confirmButton.focus(), 0);
        }, modal, false);
    }

    private async awaitModalResult<T>(
        register: (resolve: (value: T) => void) => void,
        modal: ReturnType<typeof getGeneralModal>,
        fallbackValue: T,
    ): Promise<T> {
        return await new Promise<T>((resolve) => {
            let settled = false;

            const resolveOnce = (value: T) => {
                if (settled) return;
                settled = true;
                modal.element?.removeEventListener("bloomerp:modal-closed", onModalClosed);
                resolve(value);
            };

            const onModalClosed = () => {
                if (settled) return;
                settled = true;
                resolve(fallbackValue);
            };

            modal.element?.addEventListener("bloomerp:modal-closed", onModalClosed, { once: true });
            register(resolveOnce);
        });
    }

    private escapeHtml(value: string): string {
        return value
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    private bindAfterSwap(): void {
        this.afterSwapHandler = (event: Event) => {
            if (!(event instanceof CustomEvent)) return;

            const target = event.detail?.target as HTMLElement | null | undefined;
            if (!target || !this.element) return;

            const dataSection = this.element.querySelector<HTMLElement>("[id^='file-browser-data-section-']");
            const targetIsFullComponent = target.id === this.element.id;
            const targetIsDataSection = dataSection ? target.id === dataSection.id : false;
            if (!targetIsFullComponent && !targetIsDataSection) return;

            const responseUrl = event.detail?.xhr?.responseURL;
            if (!responseUrl) return;

            const nextUrl = new URL(responseUrl, window.location.origin);
            this.fullPath = nextUrl.toString();

            if (targetIsFullComponent) {
                this.currentFolderId = this.element.dataset.folderId || null;
            } else {
                this.currentFolderId = nextUrl.searchParams.get("folder_id") || nextUrl.searchParams.get("folder") || null;
            }

            if (this.syncUrl) {
                this.syncBrowserUrl(nextUrl);
            }
        };

        this.element?.addEventListener("htmx:afterSwap", this.afterSwapHandler);
    }

    private syncBrowserUrl(fileBrowserUrl: URL): void {
        const browserUrl = new URL(window.location.href);
        browserUrl.search = fileBrowserUrl.search;
        window.history.replaceState(window.history.state, "", `${browserUrl.pathname}${browserUrl.search}${browserUrl.hash}`);
    }

    private resetFilterSection(): void {
        const contentTypeId = this.element?.dataset.filterContentTypeId;
        if (!contentTypeId) return;

        const target = document.getElementById(`filter-section-${contentTypeId}`);
        if (!target) return;

        htmx.ajax("get", `/components/filters/${contentTypeId}/init/`, {
            target,
            swap: "innerHTML",
        });
    }

    private buildRequestHeaders(): HeadersInit {
        const headers: Record<string, string> = {
            "X-Requested-With": "XMLHttpRequest",
        };

        const csrfToken = getCsrfToken();
        if (csrfToken) {
            headers["X-CSRFToken"] = csrfToken;
        }

        return headers;
    }

    private applyUrlMutation(mutator: (url: URL) => void, options?: { partial?: boolean }): void {
        const url = this.getCurrentUrl();
        if (!url) return;

        const renderId = this.getRenderId();
        if (renderId) {
            url.searchParams.set("_render_id", renderId);
        }

        mutator(url);
        this.fullPath = url.toString();
        if (this.syncUrl) {
            this.syncBrowserUrl(url);
        }
        void this.reload(options);
    }

    private getCurrentUrl(): URL | null {
        const source = this.fullPath || this.baseUrl;
        if (!source) return null;
        return new URL(source, window.location.origin);
    }

    private getRenderId(): string | null {
        const id = this.element?.id;
        if (!id || !id.startsWith("file-browser-")) return null;
        return id.replace("file-browser-", "") || null;
    }

    private async reload(options?: { partial?: boolean }): Promise<void> {
        if (!this.element || !this.fullPath) return;

        const target = options?.partial
            ? this.element.querySelector<HTMLElement>("[id^='file-browser-data-section-']")
            : null;

        await htmx.ajax("get", this.fullPath, {
            target: target ? `#${target.id}` : `#${this.element.id}`,
            swap: target ? "outerHTML" : "outerHTML",
        });
    }
}
