import { $getNodeByKey, $getRoot, $getSelection, $isRangeSelection, $setSelection, COMMAND_PRIORITY_HIGH, PASTE_COMMAND, type BaseSelection, type LexicalEditor } from 'lexical';
import { uploadReferenceFile } from './referencePicker';
import { $createFileImageNode } from '../nodes/FileImageNode';
import { $insertImageNode } from '../nodes/ImageNode';
import { t as _ } from '@/utils/i18n';

/** Paste clipboard images through the existing stored-file upload and reference flow. */
export function registerImagePaste(editor: LexicalEditor, host: HTMLElement): () => void {
    const lifecycle = new AbortController();
    /** Upload images in clipboard order and insert them at the captured paste selection. */
    async function upload(files: File[], selection: BaseSelection | null): Promise<void> {
        host.dispatchEvent(new CustomEvent('bloomerp:file-upload-state', { bubbles: true, detail: { delta: 1 } }));
        try {
            for (const file of files) {
                const reference = await uploadReferenceFile(host, file, lifecycle.signal);
                if (lifecycle.signal.aborted || !editor.isEditable()) return;
                const url = new URL(host.dataset.referenceServeUrl!, location.origin);
                url.searchParams.set('file_id', reference.target_id);
                /** Restore a still-valid paste range and insert a stored image occurrence. */
                function insert(): void {
                    if ($isRangeSelection(selection) && (!$getNodeByKey(selection.anchor.key) || !$getNodeByKey(selection.focus.key))) selection = null;
                    $setSelection(selection?.clone() ?? null);
                    if (!$getSelection()) $getRoot().selectEnd();
                    $insertImageNode($createFileImageNode(reference, url.pathname + url.search));
                    selection = $getSelection()?.clone() ?? null;
                }
                editor.update(insert, { discrete: true });
            }
        } catch {
            if (!lifecycle.signal.aborted) window.alert(_('Could not paste the image. Please try again.'));
        } finally {
            host.dispatchEvent(new CustomEvent('bloomerp:file-upload-state', { bubbles: true, detail: { delta: -1 } }));
        }
    }
    /** Intercept actual clipboard image files while leaving rich-text and reference pastes unchanged. */
    function paste(event: ClipboardEvent | InputEvent | KeyboardEvent): boolean {
        if (!(event instanceof ClipboardEvent) || !editor.isEditable() || !host.dataset.referenceUploadUrl) return false;
        const files = Array.from(event.clipboardData?.files ?? []).filter(isImage);
        if (!files.length) return false;
        event.preventDefault();
        void upload(files, $getSelection()?.clone() ?? null);
        return true;
    }
    /** Accept raster clipboard images supported by the existing image picker. */
    function isImage(file: File): boolean { return /^image\/(png|jpeg|gif|webp|avif)$/.test(file.type); }
    const unregister = editor.registerCommand(PASTE_COMMAND, paste, COMMAND_PRIORITY_HIGH);
    /** Cancel pending uploads and remove the paste command when the editor unmounts. */
    return function cleanup(): void { lifecycle.abort(); unregister(); };
}
