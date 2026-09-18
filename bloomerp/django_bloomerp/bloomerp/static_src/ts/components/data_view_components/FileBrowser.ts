import { BaseDataViewCell } from "./BaseDataViewCell";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { getCsrfToken } from "@/utils/cookies";
import { MessageType } from "../UiMessage";
import showMessage from "@/utils/messages";



export class FileBrowser extends BaseDataViewComponent {
    protected cellClass = BaseDataViewCell;

    public override initialize(): void {
        super.initialize();
        if (!this.element) return;

        this.element.addEventListener("click", this.onFolderClick, {
            signal: this.ensureAbortController().signal,
        });
        this.bindUploadInput();
        this.bindDragAndDrop();
    }

    private bindUploadInput(): void {
        const input = this.dataViewContainer?.element?.querySelector<HTMLInputElement>(
            "[data-file-browser-upload-input]",
        );
        if (!input) return;

        input.onchange = async () => {
            if (!input.files?.length) return;
            await this.uploadFiles(
                input.files,
                this.element?.dataset.currentFolderId || null,
                this.element?.dataset.scopeContentTypeId || null,
                this.element?.dataset.scopeObjectId || null,
            );
            input.value = "";
        };
    }

    private onFolderClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Element)) return;

        const folder = event.target.closest<HTMLElement>("[data-folder-id]");
        if (!folder || !this.element?.contains(folder)) return;
        if (event.target.closest("[data-no-folder-click]")) return;

        const folderId = folder.dataset.folderId;
        if (!folderId) return;

        event.preventDefault();
        this.dataViewContainer?.filter({ folder_id: folderId });
    };

    private bindDragAndDrop(): void {
        if (!this.element) return;
        const signal = this.ensureAbortController().signal;

        this.element.addEventListener("dragstart", this.onDragStart, { signal });
        this.element.addEventListener("dragover", this.onDragOver, { signal });
        this.element.addEventListener("dragleave", this.onDragLeave, { signal });
        this.element.addEventListener("drop", this.onDrop, { signal });
    }

    private onDragStart = (event: DragEvent): void => {
        if (!(event.target instanceof Element) || !event.dataTransfer) return;
        if (event.target.closest("[data-no-file-drag], [data-no-folder-click]")) {
            event.preventDefault();
            return;
        }

        const folder = event.target.closest<HTMLElement>('[data-item-type="folder"]');
        if (folder?.dataset.folderId) {
            event.dataTransfer.setData("application/x-bloomerp-folder-id", folder.dataset.folderId);
            event.dataTransfer.effectAllowed = "move";
            return;
        }

        const file = event.target.closest<HTMLElement>('[data-item-type="file"]');
        if (file?.dataset.fileId) {
            event.dataTransfer.setData("application/x-bloomerp-file-id", file.dataset.fileId);
            event.dataTransfer.effectAllowed = "move";
        }
    };

    private onDragOver = (event: DragEvent): void => {
        event.preventDefault();
        const folder = this.getFolderDropzone(event.target);
        if (!folder) return;
        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = event.dataTransfer.files.length ? "copy" : "move";
        }
        folder.classList.add("ring-2", "ring-primary/30");
    };

    private onDragLeave = (event: DragEvent): void => {
        const folder = this.getFolderDropzone(event.target);
        if (!folder) return;
        if (event.relatedTarget instanceof Node && folder.contains(event.relatedTarget)) return;
        folder.classList.remove("ring-2", "ring-primary/30");
    };

    private onDrop = (event: DragEvent): void => {
        event.preventDefault();
        const folder = this.getFolderDropzone(event.target);
        folder?.classList.remove("ring-2", "ring-primary/30");

        const targetFolderId = folder?.dataset.folderDropzone || null;
        if (event.dataTransfer?.files.length) {
            void this.uploadFiles(
                event.dataTransfer.files,
                targetFolderId ?? this.element?.dataset.currentFolderId ?? null,
                folder?.dataset.folderContentTypeId || this.element?.dataset.scopeContentTypeId || null,
                folder?.dataset.folderObjectId || this.element?.dataset.scopeObjectId || null,
            );
            return;
        }

        if (!folder || !event.dataTransfer) return;

        const fileId = event.dataTransfer.getData("application/x-bloomerp-file-id");
        if (fileId) {
            void this.moveItem("file", fileId, targetFolderId || "");
            return;
        }

        const folderId = event.dataTransfer.getData("application/x-bloomerp-folder-id");
        if (folderId && folderId !== targetFolderId) {
            void this.moveItem("folder", folderId, targetFolderId || "");
        }
    };

    private getFolderDropzone(target: EventTarget | null): HTMLElement | null {
        if (!(target instanceof Element)) return null;
        return target.closest<HTMLElement>("[data-folder-dropzone]");
    }

    private async moveItem(itemType: "file" | "folder", id: string, targetFolderId: string): Promise<void> {
        const formData = new FormData();
        formData.set("item_type", itemType);
        formData.set(`${itemType}_id`, id);
        formData.set("target_folder_id", targetFolderId);
        await this.submitAction(this.element?.dataset.moveUrl, formData, "Item moved");
    }

    private async uploadFiles(
        files: FileList,
        folderId: string | null,
        contentTypeId: string | null,
        objectId: string | null,
    ): Promise<void> {
        const formData = new FormData();
        Array.from(files).forEach((file) => formData.append("files", file));
        if (folderId) formData.set("folder_id", folderId);
        if (contentTypeId) formData.set("content_type_id", contentTypeId);
        if (objectId) formData.set("object_id", objectId);
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
        this.dataViewContainer?.refresh();
    }

    moveCellUp(): BaseDataViewCell {
        return this.currentCell as BaseDataViewCell;
    }

    moveCellDown(): BaseDataViewCell {
        return this.currentCell as BaseDataViewCell;
    }

    moveCellLeft(): BaseDataViewCell {
        return this.currentCell as BaseDataViewCell;
    }

    moveCellRight(): BaseDataViewCell {
        return this.currentCell as BaseDataViewCell;
    }

}
