import BaseComponent, { getComponent } from "../BaseComponent";
import { BloomerpTextEditor } from "../text_editor/BloomerpTextEditor";

export class EmailEditor extends BaseComponent {
    private editor: BloomerpTextEditor;
    private showCcButton: Element | null = null;
    private showBccButton: Element | null = null;
    private ccField: Element | null = null;
    private bccField: Element | null = null;
    private readonly showCcHandler = (): void => {
        this.ccField?.classList.toggle("hidden");
    };
    private readonly showBccHandler = (): void => {
        this.bccField?.classList.toggle("hidden");
    };
    
    public initialize(): void {
        this.setupCcBccListeners();
        this.setupEditor();
    }

    public setupEditor(): void {
        if (!this.element) return;
        const editorElement = this.element?.querySelector('[bloomerp-component="bloomerp-text-editor"]') as HTMLElement;
        this.editor = getComponent(editorElement) as BloomerpTextEditor;
        this.editor.editor?.focus();
    }

    public setupCcBccListeners() : void {
        if (!this.element) return;

        this.showCcButton = this.element.querySelector("#show-cc-field");
        this.showBccButton = this.element.querySelector("#show-bcc-field");
        this.ccField = this.element.querySelector("#cc-field");
        this.bccField = this.element.querySelector("#bcc-field");

        if (this.showCcButton && this.ccField) {
            this.showCcButton.addEventListener("click", this.showCcHandler);
        }

        if (this.showBccButton && this.bccField) {
            this.showBccButton.addEventListener("click", this.showBccHandler);
        }
    }

    public destroy(): void {
        this.showCcButton?.removeEventListener("click", this.showCcHandler);
        this.showBccButton?.removeEventListener("click", this.showBccHandler);
        this.showCcButton = null;
        this.showBccButton = null;
        this.ccField = null;
        this.bccField = null;
    }
}
