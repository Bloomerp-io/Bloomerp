import ace from 'ace-builds/src-noconflict/ace';
import BaseComponent from "../BaseComponent";

export default class CodeEditorWidget extends BaseComponent {
    private textarea: HTMLTextAreaElement | null = null;
    private editorContainer: HTMLElement | null = null;
    private editor: any = null;
    private language: string = '';
    private boundOnEditorChange: (() => void) | null = null;

    public initialize(): void {
        this.language = this.element.dataset.language || '';
        const textareaId = this.element.dataset.textareaId || '';
        const editorId = this.element.dataset.editorId || '';

        if (!textareaId || !editorId) return;

        this.textarea = this.element.querySelector<HTMLTextAreaElement>(`#${textareaId}`);
        this.editorContainer = this.element.querySelector<HTMLElement>(`#${editorId}`);

        if (!this.textarea || !this.editorContainer) return;

        this.editor = ace.edit(editorId);

        if (this.language) {
            void this.loadLanguageMode(this.language);
        }

        this.editor.setValue(this.textarea.value || '', -1);

        this.boundOnEditorChange = () => {
            if (this.textarea) {
                this.textarea.value = this.editor.getValue();
            }
        };
        this.editor.session.on('change', this.boundOnEditorChange);
    }

    public destroy(): void {
        if (this.editor && this.boundOnEditorChange) {
            this.editor.session.off('change', this.boundOnEditorChange);
        }
    }

    private async loadLanguageMode(language: string): Promise<void> {
        try {
            await import(`ace-builds/src-noconflict/mode-${language}`);
            this.editor.session.setMode(`ace/mode/${language}`);
        } catch (error) {
            console.warn(`Ace editor language mode not found: ${language}`, error);
        }
    }
}
