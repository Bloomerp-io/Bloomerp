import ace from 'ace-builds/src-noconflict/ace';
import { BaseWidget } from './BaseWidget';

export default class CodeEditorWidget extends BaseWidget {
    private static readonly editorsByContainer = new WeakMap<HTMLElement, any>();
    private static readonly editorHostClassNames = ['ace_editor', 'ace_hidpi', 'ace-chrome'];

    private textarea: HTMLTextAreaElement | null = null;
    private editorContainer: HTMLElement | null = null;
    private editor: any = null;
    private language: string = '';
    private launchFromButton: boolean = false;
    private modalId: string = '';
    private lastCommittedValue: string = '';
    private boundOnEditorChange: (() => void) | null = null;
    private boundOnModalClosed: ((event: Event) => void) | null = null;

    public initialize(): void {
        if (!this.element) return;
        this.language = this.element.dataset.language || '';
        this.launchFromButton = this.element.dataset.launchFromButton === 'true';
        this.modalId = this.element.dataset.modalId || '';
        this.textarea = this.element.querySelector<HTMLTextAreaElement>('[data-code-editor-input]');
        this.editorContainer = this.element.querySelector<HTMLElement>('[data-code-editor-container]');

        if (!this.textarea || !this.editorContainer) return;
        this.lastCommittedValue = this.textarea.value || this.textarea.textContent || '';

        this.configureAceModuleLoader();
        this.disposeEditorForContainer(this.editorContainer);

        this.editor = ace.edit(this.editorContainer);
        CodeEditorWidget.editorsByContainer.set(this.editorContainer, this.editor);

        this.editor.setTheme('ace/theme/chrome');
        this.editor.setOptions({
            showPrintMargin: false,
            fontSize: 14,
            tabSize: 2,
            useSoftTabs: true,
        });
        this.editor.session.setUseWrapMode(true);
        this.restoreEditorHostState();

        if (this.language) {
            void this.loadLanguageMode(this.language);
        }

        this.editor.setValue(this.textarea.value || this.textarea.textContent || '', -1);
        this.scheduleResize();

        this.boundOnEditorChange = () => {
            this.onChange();
        };
        this.editor.session.on('change', this.boundOnEditorChange);

        if (this.launchFromButton && this.modalId) {
            this.boundOnModalClosed = (event: Event) => {
                const customEvent = event as CustomEvent<{ modalId?: string }>;
                if (customEvent.detail?.modalId !== this.modalId) return;

                this.commitTextareaChange();
            };
            document.body.addEventListener('bloomerp:modal-closed', this.boundOnModalClosed);
        }
    }

    public destroy(): void {
        if (this.editor && this.textarea) {
            this.textarea.value = this.editor.getValue();
        }

        if (this.editor && this.boundOnEditorChange) {
            this.editor.session.off('change', this.boundOnEditorChange);
        }

        if (this.editor) {
            this.editor.destroy();
        }

        if (this.boundOnModalClosed) {
            document.body.removeEventListener('bloomerp:modal-closed', this.boundOnModalClosed);
        }

        if (this.editorContainer) {
            const registeredEditor = CodeEditorWidget.editorsByContainer.get(this.editorContainer);
            if (registeredEditor === this.editor) {
                CodeEditorWidget.editorsByContainer.delete(this.editorContainer);
            }
            this.resetEditorContainer(this.editorContainer);
        }

        this.editor = null;
        this.boundOnEditorChange = null;
        this.boundOnModalClosed = null;
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
        const editor = this.editor;

        try {
            await (ace as any).config.loadModule(`ace/mode/${language}`);
            if (this.editor === editor) {
                this.editor.session.setMode(`ace/mode/${language}`);
            }
        } catch (error) {
            console.warn(`Ace editor language mode not found: ${language}`, error);
        }
    }

    public override onChange(): void {
        if (this.textarea) {
            this.textarea.value = this.getValue();
            if (!this.launchFromButton) {
                this.commitTextareaChange();
            }
        }

        super.onChange();
    }

    public getValue(): string {
        if (this.editor) {
            return this.editor.getValue();
        }

        return this.textarea?.value || this.textarea?.textContent || '';
    }

    public setValue(value: unknown, emitChange: boolean = false): void {
        const normalizedValue = typeof value === "string" ? value : "";

        if (this.editor) {
            this.editor.setValue(normalizedValue, -1);
        }

        if (this.textarea) {
            this.textarea.value = normalizedValue;
        }

        if (emitChange) {
            this.onChange();
        }
    }

    public onAfterSwap(): void {
        this.restoreEditorHostState();
        this.scheduleResize();
    }

    private disposeEditorForContainer(container: HTMLElement): void {
        const existingEditor = CodeEditorWidget.editorsByContainer.get(container) ?? (container as any).env?.editor;

        if (existingEditor) {
            existingEditor.destroy();
            CodeEditorWidget.editorsByContainer.delete(container);
        }

        this.resetEditorContainer(container);
    }

    private resetEditorContainer(container: HTMLElement): void {
        container.textContent = '';
        delete (container as any).env;
    }

    private commitTextareaChange(): void {
        if (!this.textarea) return;

        const currentValue = this.textarea.value;
        if (currentValue === this.lastCommittedValue) return;

        this.lastCommittedValue = currentValue;
        this.textarea.dispatchEvent(new Event('change', { bubbles: true }));
    }

    private scheduleResize(): void {
        requestAnimationFrame(() => {
            this.restoreEditorHostState();
            this.editor?.resize(true);
            this.editor?.renderer?.updateFull?.();
        });
    }

    private restoreEditorHostState(): void {
        if (!this.editorContainer) return;

        this.editorContainer.classList.add(...CodeEditorWidget.editorHostClassNames);
        this.editorContainer.style.fontSize = '14px';
    }
}
