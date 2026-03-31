import ace from 'ace-builds/src-noconflict/ace';
import BaseComponent from "../BaseComponent";

export default class CodeEditorWidget extends BaseComponent {
    private textarea: HTMLTextAreaElement | null = null;
    private editorContainer: HTMLElement | null = null;
    private editor: any = null;
    private language: string = '';
    private boundOnEditorChange: (() => void) | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.language = this.element.dataset.language || '';
        this.textarea = this.element.querySelector<HTMLTextAreaElement>('[data-code-editor-input]');
        this.editorContainer = this.element.querySelector<HTMLElement>('[data-code-editor-container]');

        if (!this.textarea || !this.editorContainer) return;

        this.configureAceModuleLoader();
        this.editor = ace.edit(this.editorContainer);
        this.editor.setTheme('ace/theme/chrome');
        this.editor.setOptions({
            showPrintMargin: false,
            fontSize: 14,
            tabSize: 2,
            useSoftTabs: true,
        });
        this.editor.session.setUseWrapMode(true);

        if (this.language) {
            void this.loadLanguageMode(this.language);
        }

        this.editor.setValue(this.textarea.value || this.textarea.textContent || '', -1);
        requestAnimationFrame(() => {
            this.editor?.resize(true);
        });

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

        if (this.editor) {
            this.editor.destroy();
        }
    }

    private configureAceModuleLoader(): void {
        const aceConfig = (ace as any).config;
        if (!aceConfig?.setLoader) return;

        aceConfig.setLoader((moduleName: string, cb: (error: unknown, module?: unknown) => void) => {
            const normalized = moduleName.startsWith('./') ? `ace/${moduleName.slice(2)}` : moduleName;

            const resolveModule = (): Promise<unknown> => {
                if (normalized === 'ace/theme/chrome') {
                    return import('ace-builds/src-noconflict/theme-chrome');
                }

                if (normalized === 'ace/mode/json') {
                    return import('ace-builds/src-noconflict/mode-json');
                }

                if (normalized === 'ace/mode/python') {
                    return import('ace-builds/src-noconflict/mode-python');
                }

                if (normalized === 'ace/mode/javascript') {
                    return import('ace-builds/src-noconflict/mode-javascript');
                }

                if (normalized === 'ace/mode/sql') {
                    return import('ace-builds/src-noconflict/mode-sql');
                }

                if (normalized === 'ace/mode/html') {
                    return import('ace-builds/src-noconflict/mode-html');
                }

                if (normalized === 'ace/mode/css') {
                    return import('ace-builds/src-noconflict/mode-css');
                }

                return Promise.reject(new Error(`Unsupported Ace module: ${normalized}`));
            };

            void resolveModule()
                .then((module) => cb(null, module))
                .catch((error) => cb(error));
        });
    }

    private async loadLanguageMode(language: string): Promise<void> {
        try {
            await (ace as any).config.loadModule(`ace/mode/${language}`);
            this.editor.session.setMode(`ace/mode/${language}`);
        } catch (error) {
            console.warn(`Ace editor language mode not found: ${language}`, error);
        }
    }
}
