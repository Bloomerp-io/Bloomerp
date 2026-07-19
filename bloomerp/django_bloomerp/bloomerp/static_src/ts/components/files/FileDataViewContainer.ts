import { BaseDataViewCell } from "../data_view_components/BaseDataViewCell";
import { DataViewContainer } from "../data_view_components/DataViewContainer";
import { getCsrfToken } from "@/utils/cookies";
import { MessageType } from "../UiMessage";
import showMessage from "@/utils/messages";

type FolderOption = {
    id: string;
    label: string;
};

export default class FileDataViewContainer extends DataViewContainer {
    private scopeContentTypeId: string | null = null;
    private scopeObjectId: string | null = null;
    private currentFolderId: string | null = null;
    private folderOptions: FolderOption[] = [];
    private clickHandler: ((event: MouseEvent) => void) | null = null;

    public override initialize(): void {
        super.initialize();
        if (!this.element) return;

        this.refreshFolderState();
        this.clickHandler = (event: MouseEvent) => this.handleClick(event);
        this.element.addEventListener("click", this.clickHandler);
        this.bindFileInput();
        this.bindDragAndDrop();
    }

    public override onAfterSwap(): void {
        super.onAfterSwap();
        this.refreshFolderState();
        this.bindFileInput();
        this.bindDragAndDrop();
    }

    public override destroy(): void {
        if (this.clickHandler) {
            this.element?.removeEventListener("click", this.clickHandler);
            this.clickHandler = null;
        }
        super.destroy();
    }

    protected override onAdd(): boolean {
        this.element?.querySelector<HTMLInputElement>("[data-upload-input]")?.click();
        return true;
    }

    protected override onCellClick(cell: BaseDataViewCell): boolean {
        const viewLink = this.element?.querySelector<HTMLAnchorElement>(
            `[data-file-view="${CSS.escape(cell.objectId)}"]`,
        );
        viewLink?.click();
        return true;
    }

    private refreshFolderState(): void {
        const folderSection = this.element?.querySelector<HTMLElement>("[data-file-browser-folders]");
        this.scopeContentTypeId = folderSection?.dataset.scopeContentTypeId || null;
        this.scopeObjectId = folderSection?.dataset.scopeObjectId || null;
        this.currentFolderId = folderSection?.dataset.currentFolderId || null;

        try {
            this.folderOptions = JSON.parse(folderSection?.dataset.folderOptions || "[]");
        } catch {
            this.folderOptions = [];
        }
    }

    private handleClick(event: MouseEvent): void {
        const target = event.target as HTMLElement | null;
        if (!target) return;

        if (target.closest("[data-trigger-upload]")) {
            this.element?.querySelector<HTMLInputElement>("[data-upload-input]")?.click();
            return;
        }

        if (target.closest("[data-create-folder]")) {
            void this.createFolder();
            return;
        }

        const renameFile = target.closest<HTMLElement>("[data-rename-file]");
        if (renameFile) {
            void this.renameItem("file", renameFile.dataset.renameFile || "", renameFile.dataset.currentName || "");
            return;
        }

        const renameFolder = target.closest<HTMLElement>("[data-rename-folder]");
        if (renameFolder) {
            void this.renameItem("folder", renameFolder.dataset.renameFolder || "", renameFolder.dataset.currentName || "");
            return;
        }

        const moveFile = target.closest<HTMLElement>("[data-move-file]");
        if (moveFile) {
            void this.promptMoveFile(moveFile.dataset.moveFile || "");
            return;
        }

        const deleteFile = target.closest<HTMLElement>("[data-delete-file]");
        if (deleteFile) {
            void this.deleteItem("file", deleteFile.dataset.deleteFile || "");
            return;
        }

        const deleteFolder = target.closest<HTMLElement>("[data-delete-folder]");
        if (deleteFolder) {
            void this.deleteItem("folder", deleteFolder.dataset.deleteFolder || "");
        }
    }

    private bindFileInput(): void {
        const input = this.element?.querySelector<HTMLInputElement>("[data-upload-input]");
        if (!input || input.dataset.bound === "true") return;

        input.dataset.bound = "true";
        input.addEventListener("change", async () => {
            if (!input.files?.length) return;
            await this.uploadFiles(input.files, this.currentFolderId);
            input.value = "";
        });
    }

    private bindDragAndDrop(): void {
        const dataSection = this.element?.querySelector<HTMLElement>("#data-view-data-section");
        if (dataSection && dataSection.dataset.fileDropBound !== "true") {
            dataSection.dataset.fileDropBound = "true";
            dataSection.addEventListener("dragover", (event) => event.preventDefault());
            dataSection.addEventListener("drop", (event) => {
                event.preventDefault();
                if (event.target instanceof Element && event.target.closest("[data-folder-dropzone]")) return;
                if (event.dataTransfer?.files.length) {
                    void this.uploadFiles(event.dataTransfer.files, this.currentFolderId);
                }
            });
        }

        this.element?.querySelectorAll<HTMLElement>('[data-object-id]:not([data-object-id=""])').forEach((objectElement) => {
            const item = objectElement.closest<HTMLElement>("tr") || objectElement;
            if (item.dataset.fileDragBound === "true") return;
            item.dataset.fileDragBound = "true";
            item.draggable = true;
            item.addEventListener("dragstart", (event) => {
                event.dataTransfer?.setData("application/x-bloomerp-file-id", objectElement.dataset.objectId || "");
            });
        });

        this.element?.querySelectorAll<HTMLElement>("[data-folder-dropzone]").forEach((folder) => {
            if (folder.dataset.folderDropBound === "true") return;
            folder.dataset.folderDropBound = "true";
            folder.addEventListener("dragstart", (event) => {
                event.dataTransfer?.setData(
                    "application/x-bloomerp-folder-id",
                    folder.dataset.folderId || "",
                );
            });
            folder.addEventListener("dragover", (event) => {
                event.preventDefault();
                folder.classList.add("ring-2", "ring-primary/30");
            });
            folder.addEventListener("dragleave", () => folder.classList.remove("ring-2", "ring-primary/30"));
            folder.addEventListener("drop", (event) => {
                event.preventDefault();
                event.stopPropagation();
                folder.classList.remove("ring-2", "ring-primary/30");
                const targetFolderId = folder.dataset.folderDropzone || "";
                if (event.dataTransfer?.files.length) {
                    void this.uploadFiles(event.dataTransfer.files, targetFolderId);
                    return;
                }

                const fileId = event.dataTransfer?.getData("application/x-bloomerp-file-id") || "";
                if (fileId) {
                    void this.moveItem("file", fileId, targetFolderId);
                    return;
                }

                const folderId = event.dataTransfer?.getData("application/x-bloomerp-folder-id") || "";
                if (folderId && folderId !== targetFolderId) {
                    void this.moveItem("folder", folderId, targetFolderId);
                }
            });
        });
    }

    private async createFolder(): Promise<void> {
        const name = window.prompt("Folder name")?.trim();
        if (!name) return;

        const formData = new FormData();
        formData.set("name", name);
        if (this.currentFolderId) formData.set("parent_folder_id", this.currentFolderId);
        if (this.scopeContentTypeId) formData.set("content_type_id", this.scopeContentTypeId);
        if (this.scopeObjectId) formData.set("object_id", this.scopeObjectId);
        await this.submitAction(this.element?.dataset.createFolderUrl, formData, "Folder created");
    }

    private async renameItem(itemType: "file" | "folder", id: string, currentName: string): Promise<void> {
        const name = window.prompt("Name", currentName)?.trim();
        if (!id || !name) return;

        const formData = new FormData();
        formData.set("item_type", itemType);
        formData.set(`${itemType}_id`, id);
        formData.set("name", name);
        await this.submitAction(this.element?.dataset.renameUrl, formData, "Name updated");
    }

    private async promptMoveFile(fileId: string): Promise<void> {
        if (!fileId || !this.folderOptions.length) return;
        const choices = this.folderOptions.map((folder) => `${folder.id}: ${folder.label}`).join("\n");
        const targetFolderId = window.prompt(`Destination folder id:\n${choices}`)?.trim();
        if (!targetFolderId || !this.folderOptions.some((folder) => folder.id === targetFolderId)) return;
        await this.moveItem("file", fileId, targetFolderId);
    }

    private async moveItem(itemType: "file" | "folder", id: string, targetFolderId: string): Promise<void> {
        const formData = new FormData();
        formData.set("item_type", itemType);
        formData.set(`${itemType}_id`, id);
        formData.set("target_folder_id", targetFolderId);
        await this.submitAction(this.element?.dataset.moveUrl, formData, "Item moved");
    }

    private async deleteItem(itemType: "file" | "folder", id: string): Promise<void> {
        if (!id || !window.confirm(`Delete this ${itemType}?`)) return;
        const formData = new FormData();
        formData.set("item_type", itemType);
        formData.set(`${itemType}_id`, id);
        await this.submitAction(this.element?.dataset.deleteUrl, formData, "Item deleted");
    }

    private async uploadFiles(files: FileList, folderId: string | null): Promise<void> {
        const formData = new FormData();
        Array.from(files).forEach((file) => formData.append("files", file));
        if (folderId) formData.set("folder_id", folderId);
        if (this.scopeContentTypeId) formData.set("content_type_id", this.scopeContentTypeId);
        if (this.scopeObjectId) formData.set("object_id", this.scopeObjectId);
        await this.submitAction(this.element?.dataset.uploadUrl, formData, "Files uploaded");
    }

    private async submitAction(url: string | undefined, formData: FormData, successMessage: string): Promise<void> {
        if (!url) return;
        const csrfToken = getCsrfToken();
        const response = await fetch(url, {
            method: "POST",
            body: formData,
            credentials: "same-origin",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
            },
        });
        if (!response.ok) {
            showMessage("The file action could not be completed", MessageType.ERROR);
            return;
        }
        showMessage(successMessage, MessageType.SUCCESS);
        this.refresh();
    }
}
