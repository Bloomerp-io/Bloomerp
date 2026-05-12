import BaseComponent from "../BaseComponent";

import {
    $getNodeByKey,
    $createParagraphNode,
    $createTextNode,
    $isDecoratorNode,
    $isElementNode,
    $getRoot,
    $getSelection,
    $isRangeSelection,
    $isTextNode,
    COMMAND_PRIORITY_EDITOR,
    FORMAT_ELEMENT_COMMAND,
    FORMAT_TEXT_COMMAND,
    SELECTION_CHANGE_COMMAND,
    createEditor,
    type LexicalNode,
    type LexicalEditor,
} from "lexical";
import { $generateHtmlFromNodes, $generateNodesFromDOM } from "@lexical/html";
import { $createHeadingNode, HeadingNode, registerRichText } from "@lexical/rich-text";
import { ListItemNode, ListNode, registerList } from "@lexical/list";
import { LinkNode } from "@lexical/link";
import { TableCellNode, TableNode, TableRowNode } from "@lexical/table";
import {
    resolveTemplateBuilderSections,
    type TemplateBuilderBlockDefinition,
    type TemplateBuilderBlockExecutionContext,
    type TemplateField,
} from "./blocks";
import { readTemplateFields, readVariableCatalog } from "./catalog";
import { ImageController } from "./controllers/ImageController";
import { HtmlHistory } from "./history/HtmlHistory";
import { ImageNode } from "./nodes/ImageNode";
import {
    DEFAULT_PAGE_SETTINGS,
    getPageDimensions,
    getPageWrapperStyle,
    normalizePageMargin,
    normalizePageOrientation,
    normalizePageSize,
} from "./pageSettings";
import { VariablesPanel } from "./panels/VariablesPanel";
import { injectTemplateBuilderShellStyles } from "./shellStyles";
import type {
    TemplateBuilderFreeVariable,
    TemplateBuilderPageSettings,
    TemplateBuilderTab,
    TemplateBuilderVariableCatalog,
} from "./types";


export default class TemplateBuilder extends BaseComponent {
    private editor: LexicalEditor | null = null;
    private editorRoot: HTMLDivElement | null = null;
    private toolbarEl: HTMLElement | null = null;
    private blocksEl: HTMLElement | null = null;
    private stylesEl: HTMLElement | null = null;
    private layersEl: HTMLElement | null = null;
    private settingsEl: HTMLElement | null = null;
    private variablesEl: HTMLElement | null = null;
    private pageSummaryEl: HTMLElement | null = null;
    private pageEl: HTMLElement | null = null;
    private hiddenInput: HTMLInputElement | null = null;
    private freeVariablesInput: HTMLInputElement | null = null;
    private contentTypesEl: HTMLElement | null = null;
    private fieldConfigScriptId: string | null = null;
    private variableCatalogScriptId: string | null = null;
    private shellStyleEl: HTMLStyleElement | null = null;
    private tabButtons: HTMLButtonElement[] = [];
    private tabPanels: HTMLElement[] = [];
    private activeTab: TemplateBuilderTab = "blocks";
    private blockSearchInput: HTMLInputElement | null = null;
    private pageSizeInput: HTMLSelectElement | null = null;
    private pageOrientationInput: HTMLSelectElement | null = null;
    private pageMarginInput: HTMLInputElement | null = null;
    private pageSettings: TemplateBuilderPageSettings = { ...DEFAULT_PAGE_SETTINGS };
    private unregisterUpdateListener: (() => void) | null = null;
    private unregisterListBehavior: (() => void) | null = null;
    private imageController: ImageController | null = null;
    private history: HtmlHistory | null = null;
    private lastActiveBlockKey: string | null = null;
    private variablesPanel: VariablesPanel | null = null;
    private variableCatalog: TemplateBuilderVariableCatalog | null = null;

    /** Boots the constrained Lexical editor and wires the builder UI around it. */
    public initialize(): void {
        if (!this.element) return;

        this.toolbarEl = this.element.querySelector<HTMLElement>("[data-template-builder-toolbar]");
        this.blocksEl = this.element.querySelector<HTMLElement>("[data-template-builder-blocks]");
        this.stylesEl = this.element.querySelector<HTMLElement>("[data-template-builder-styles]");
        this.layersEl = this.element.querySelector<HTMLElement>("[data-template-builder-layers]");
        this.settingsEl = this.element.querySelector<HTMLElement>("[data-template-builder-settings]");
        this.variablesEl = this.element.querySelector<HTMLElement>("[data-template-builder-variables]");
        this.pageSummaryEl = this.element.querySelector<HTMLElement>("[data-template-builder-page-summary]");
        this.pageEl = this.element.querySelector<HTMLElement>("[data-template-builder-page]");
        this.editorRoot = this.element.querySelector<HTMLDivElement>("[data-template-builder-editor-root]");
        this.hiddenInput = this.element.querySelector<HTMLInputElement>("[data-template-builder-input]");
        this.freeVariablesInput = this.element.querySelector<HTMLInputElement>("[data-template-builder-free-variables-input]");
        this.contentTypesEl = this.element.querySelector<HTMLElement>("[data-template-builder-content-types]");
        this.blockSearchInput = this.element.querySelector<HTMLInputElement>("[data-template-builder-block-search]");
        this.pageSizeInput = this.element.querySelector<HTMLSelectElement>("[data-template-builder-page-size]");
        this.pageOrientationInput = this.element.querySelector<HTMLSelectElement>("[data-template-builder-page-orientation]");
        this.pageMarginInput = this.element.querySelector<HTMLInputElement>("[data-template-builder-page-margin]");
        this.tabButtons = Array.from(
            this.element.querySelectorAll<HTMLButtonElement>("[data-template-builder-tab-button]")
        );
        this.tabPanels = Array.from(
            this.element.querySelectorAll<HTMLElement>("[data-template-builder-tab-panel]")
        );
        this.fieldConfigScriptId = this.element.dataset.fieldConfigId || null;
        this.variableCatalogScriptId = this.element.dataset.variableCatalogId || null;

        if (
            !this.toolbarEl ||
            !this.blocksEl ||
            !this.stylesEl ||
            !this.layersEl ||
            !this.settingsEl ||
            !this.variablesEl ||
            !this.pageEl ||
            !this.editorRoot ||
            !this.hiddenInput
        ) {
            return;
        }

        this.shellStyleEl = injectTemplateBuilderShellStyles(this.element);
        this.pageSettings = this.getInitialPageSettings();
        this.applyPageSettings();

        this.editor = createEditor({
            namespace: "DocumentTemplateBuilder",
            onError(error: Error) {
                throw error;
            },
            theme: {
                paragraph: "doc-paragraph",
                heading: {
                    h1: "doc-heading-1",
                    h2: "doc-heading-2",
                    h3: "doc-heading-3",
                },
                list: {
                    ul: "doc-list-ul",
                    ol: "doc-list-ol",
                    listitem: "doc-list-item",
                    nested: {
                        listitem: "doc-list-item-nested",
                    },
                },
                text: {
                    bold: "doc-text-bold",
                    italic: "doc-text-italic",
                    underline: "doc-text-underline",
                },
            },
            nodes: [HeadingNode, ListNode, ListItemNode, LinkNode, TableNode, TableRowNode, TableCellNode, ImageNode],
        });

        this.editor.setRootElement(this.editorRoot);
        registerRichText(this.editor);
        this.unregisterListBehavior = registerList(this.editor);
        this.registerSelectionTracking();
        this.imageController = new ImageController({
            host: this.element,
            editor: this.editor,
            editorRoot: this.editorRoot,
            insertBlockNode: (node) => this.insertBlockNode(node),
        });
        this.imageController.mount();

        this.history = new HtmlHistory((snapshot) => this.loadInitialContent(snapshot));
        this.loadInitialContent(this.hiddenInput.value || this.element.dataset.initialHtml || "");
        this.renderToolbar();
        this.variablesPanel = new VariablesPanel(this.variablesEl, {
            insertSnippet: (snippet) => this.insertTemplateSnippet(snippet),
            onFreeVariablesChange: (variables) => {
                this.syncFreeVariablesInput(variables);
                if (this.variableCatalog) {
                    this.variableCatalog.freeVariables = variables;
                }
            },
        });
        this.renderVariableCatalog(readVariableCatalog(this.variableCatalogScriptId));
        //this.renderStylesPanel();
        this.setupTabs();
        this.setupBlockSearch();
        this.setupContentTypeControl();
        this.setupSettingsControls();
        this.refreshLayersPanel();
        this.syncHiddenInput();

        this.unregisterUpdateListener = this.editor.registerUpdateListener(() => {
            this.syncHiddenInput();
            this.refreshLayersPanel();
            this.captureSelectionAnchor();
            this.captureHistorySnapshot();
        });

        this.editor.registerCommand(
            "KEY_TAB_COMMAND" as never,
            () => false,
            COMMAND_PRIORITY_EDITOR
        );
    }

    /** Tears down event listeners and transient DOM that were created during initialization. */
    public destroy(): void {
        this.tabButtons.forEach((button) => {
            button.removeEventListener("click", this.handleTabClick);
        });
        this.blockSearchInput?.removeEventListener("input", this.handleBlockSearch);
        this.contentTypesEl?.removeEventListener("bloomerp:widget-change", this.handleContentTypesChange);
        this.pageSizeInput?.removeEventListener("change", this.handlePageSettingChange);
        this.pageOrientationInput?.removeEventListener("change", this.handlePageSettingChange);
        this.pageMarginInput?.removeEventListener("input", this.handlePageSettingChange);
        this.unregisterUpdateListener?.();
        this.unregisterListBehavior?.();
        this.imageController?.destroy();
        this.imageController = null;
        this.editor = null;
        this.shellStyleEl?.remove();
        this.shellStyleEl = null;
    }

    /** Reads the model-backed page settings from form controls and component data attributes. */
    private getInitialPageSettings(): TemplateBuilderPageSettings {
        const pageSize = normalizePageSize(
            this.pageSizeInput?.value || this.element?.dataset.pageSize
        );
        const orientation = normalizePageOrientation(
            this.pageOrientationInput?.value || this.element?.dataset.pageOrientation
        );
        const marginInches = normalizePageMargin(
            this.pageMarginInput?.value || this.element?.dataset.pageMargin
        );

        return { pageSize, orientation, marginInches };
    }

    /** Loads previously saved HTML, or fallback starter content, into the Lexical document. */
    private loadInitialContent(initialHtml: string): void {
        if (!this.editor) return;

        const fallbackHtml = `
            <p style="margin:0 0 8px;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#475569;">A4 template</p>
            <h1 style="margin:0 0 12px;font-size:30pt;line-height:1.05;font-weight:700;">Document title</h1>
            <p style="margin:0 0 20px;color:#475569;">Start with a heading, add sections, and insert merge fields from the right.</p>
            <p style="margin:0 0 20px;">------------------------------------------------------------</p>
            <p style="margin:0;">This Lexical prototype keeps everything inside a single document surface instead of a free-form page builder canvas.</p>
        `;

        const parser = new DOMParser();
        const documentToParse = parser.parseFromString(initialHtml || fallbackHtml, "text/html");
        const pageNode = documentToParse.body.querySelector("[data-template-page-root]");
        const source = pageNode?.innerHTML?.trim() ? pageNode.innerHTML : documentToParse.body.innerHTML || fallbackHtml;

        const dom = parser.parseFromString(source, "text/html");

        this.editor.update(() => {
            const root = $getRoot();
            root.clear();
            const nodes = this.normalizeNodesForRoot($generateNodesFromDOM(this.editor!, dom));
            if (nodes.length === 0) {
                root.append($createParagraphNode().append($createTextNode("")));
                return;
            }
            root.append(...nodes);
        });

        this.syncHiddenInput();
        this.captureHistorySnapshot(true);
    }

    /** Renders the top toolbar and connects each control to editor commands. */
    private renderToolbar(): void {
        if (!this.toolbarEl) return;

        const buttons = [
            { label: "Undo", icon: "fa-solid fa-rotate-left", onClick: () => this.undo() },
            { label: "Redo", icon: "fa-solid fa-rotate-right", onClick: () => this.redo() },
            { label: "Bold", icon: "fa-solid fa-bold", onClick: () => this.editor?.dispatchCommand(FORMAT_TEXT_COMMAND, "bold") },
            { label: "Italic", icon: "fa-solid fa-italic", onClick: () => this.editor?.dispatchCommand(FORMAT_TEXT_COMMAND, "italic") },
            { label: "Underline", icon: "fa-solid fa-underline", onClick: () => this.editor?.dispatchCommand(FORMAT_TEXT_COMMAND, "underline") },
            { label: "Left", icon: "fa-solid fa-align-left", onClick: () => this.applyElementAlignment("left") },
            { label: "Center", icon: "fa-solid fa-align-center", onClick: () => this.applyElementAlignment("center") },
        ];

        this.toolbarEl.innerHTML = "";
        buttons.forEach((button) => {
            const el = document.createElement("button");
            el.type = "button";
            el.className = "btn btn-sm btn-secondary";
            el.title = button.label;
            el.innerHTML = `<i class="${button.icon}" aria-hidden="true"></i><span>${button.label}</span>`;
            el.addEventListener("click", () => {
                button.onClick();
                this.editorRoot?.focus();
            });
            this.toolbarEl?.appendChild(el);
        });
    }

    /** Builds the sidebar block list from static sections and dynamic merge fields. */
    private renderBlocks(fields: TemplateField[]): void {
        if (!this.blocksEl) return;
        const sections = resolveTemplateBuilderSections(fields);

        this.blocksEl.innerHTML = "";

        sections.forEach((sectionDefinition) => {
            const section = document.createElement("section");
            section.className = "template-builder-panel-section";
            section.dataset.category = sectionDefinition.id;

            const title = document.createElement("h4");
            title.className = "template-builder-panel-title";
            title.textContent = sectionDefinition.title;
            section.appendChild(title);

            const list = document.createElement("div");
            list.className = sectionDefinition.id === "merge" ? "template-builder-merge-list" : "template-builder-block-list";

            if (sectionDefinition.id === "merge") {
                sectionDefinition.blocks.forEach((block) => {
                    list.appendChild(this.createMergeItem(block));
                });
            } else {
                sectionDefinition.blocks.forEach((block) => {
                    list.appendChild(this.createBlockItem(block));
                });
            }

            section.appendChild(list);
            this.blocksEl?.appendChild(section);
        });
    }

    /** Creates a reusable icon badge used by block and merge-field buttons. */
    private createIconBadge(icon?: string, badgeClass = ""): HTMLSpanElement {
        const badge = document.createElement("span");
        badge.className = `template-builder-block-item-icon ${badgeClass}`.trim();

        const iconEl = document.createElement("i");
        iconEl.className = icon || "fa-solid fa-square-plus";
        iconEl.setAttribute("aria-hidden", "true");
        badge.appendChild(iconEl);

        return badge;
    }

    /** Builds a regular block button with icon, title, description, and affordance. */
    private createBlockItem(block: TemplateBuilderBlockDefinition): HTMLButtonElement {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "template-builder-block-item";
        button.title = block.label;
        button.dataset.blockLabel = this.getBlockSearchText(block);
        button.setAttribute("aria-label", `${block.label}. ${block.description}`);
        button.appendChild(this.createIconBadge(block.icon));

        const body = document.createElement("span");
        body.className = "template-builder-block-item-body";

        const label = document.createElement("span");
        label.className = "template-builder-block-item-label";
        label.textContent = block.label;

        const description = document.createElement("span");
        description.className = "template-builder-block-item-description";
        description.textContent = block.description;

        body.appendChild(label);
        body.appendChild(description);
        button.appendChild(body);

        const chevron = document.createElement("i");
        chevron.className = "fa-solid fa-chevron-right template-builder-block-item-chevron";
        chevron.setAttribute("aria-hidden", "true");
        button.appendChild(chevron);

        button.addEventListener("click", () => this.executeBlock(block));
        return button;
    }

    /** Builds a merge-field button with a token badge and label pairing. */
    private createMergeItem(block: TemplateBuilderBlockDefinition): HTMLButtonElement {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "template-builder-merge-item";
        button.title = block.label;
        button.dataset.blockLabel = this.getBlockSearchText(block);
        button.setAttribute("aria-label", `${block.label}. ${block.description}`);
        button.appendChild(this.createIconBadge(block.icon, "template-builder-merge-item-icon"));

        const body = document.createElement("span");
        body.className = "template-builder-merge-item-body";

        const token = document.createElement("span");
        token.className = "template-builder-merge-token";
        token.textContent = block.description.replace(/^Insert\s+/i, "");

        const label = document.createElement("span");
        label.className = "template-builder-merge-label";
        label.textContent = block.label;

        const description = document.createElement("span");
        description.className = "template-builder-merge-description";
        description.textContent = block.description;

        body.appendChild(token);
        body.appendChild(label);
        body.appendChild(description);
        button.appendChild(body);

        const chevron = document.createElement("i");
        chevron.className = "fa-solid fa-chevron-right template-builder-block-item-chevron";
        chevron.setAttribute("aria-hidden", "true");
        button.appendChild(chevron);

        button.addEventListener("click", () => this.executeBlock(block));
        return button;
    }

    /** Exposes a minimal editor API so block definitions can stay declarative. */
    private getBlockExecutionContext(): TemplateBuilderBlockExecutionContext {
        if (!this.editor) {
            throw new Error("Template builder editor is not initialized.");
        }

        return {
            editor: this.editor,
            focusEditor: () => this.focusEditor(),
            insertBlockNode: (node) => this.insertBlockNode(node),
            promptImageUpload: () => this.promptImageUpload(),
        };
    }

    /** Executes a resolved block definition against the current editor instance. */
    private executeBlock(block: TemplateBuilderBlockDefinition): void {
        if (!this.editor) return;
        block.action.run(this.getBlockExecutionContext());
    }

    /** Creates the lowercase search text used by the sidebar filter. */
    private getBlockSearchText(block: TemplateBuilderBlockDefinition): string {
        return [block.label, block.description, ...(block.keywords || [])].join(" ").toLowerCase();
    }

    /** Renders the lightweight styling shortcuts shown in the Styles tab. */
    private renderStylesPanel(): void {
        if (!this.stylesEl) return;

        const controls = [
            { label: "Title", action: () => this.wrapSelectionWithBlock("h1") },
            { label: "Heading", action: () => this.wrapSelectionWithBlock("h2") },
            { label: "Text", action: () => this.wrapSelectionWithBlock("p") },
            { label: "Bold", action: () => this.editor?.dispatchCommand(FORMAT_TEXT_COMMAND, "bold") },
            { label: "Italic", action: () => this.editor?.dispatchCommand(FORMAT_TEXT_COMMAND, "italic") },
            { label: "Underline", action: () => this.editor?.dispatchCommand(FORMAT_TEXT_COMMAND, "underline") },
        ];

        this.stylesEl.innerHTML = "";
        const container = document.createElement("div");
        container.className = "template-builder-style-grid";

        controls.forEach((control) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "template-builder-style-button";
            button.textContent = control.label;
            button.addEventListener("click", () => {
                control.action();
                this.editorRoot?.focus();
            });
            container.appendChild(button);
        });

        const note = document.createElement("p");
        note.className = "template-builder-help-copy";
        note.textContent = "This Lexical prototype favors inline styling and constrained document structure over free-form dragging.";

        this.stylesEl.appendChild(container);
        this.stylesEl.appendChild(note);
    }

    /** Rebuilds the simple outline view from the current top-level Lexical nodes. */
    private refreshLayersPanel(): void {
        if (!this.layersEl || !this.editor) return;

        const items: string[] = [];
        this.editor.getEditorState().read(() => {
            const root = $getRoot();
            root.getChildren().forEach((child, index) => {
                const type = child.getType();
                const text = child.getTextContent().trim().replace(/\s+/g, " ");
                const label = text.length > 48 ? `${text.slice(0, 48)}...` : text || type;
                items.push(`${index + 1}. ${label}`);
            });
        });

        this.layersEl.innerHTML = "";
        const list = document.createElement("div");
        list.className = "template-builder-layer-list";

        if (items.length === 0) {
            const empty = document.createElement("p");
            empty.className = "template-builder-help-copy";
            empty.textContent = "Your document outline will appear here.";
            list.appendChild(empty);
        } else {
            items.forEach((item) => {
                const row = document.createElement("div");
                row.className = "template-builder-layer-item";
                row.textContent = item;
                list.appendChild(row);
            });
        }

        this.layersEl.appendChild(list);
    }

    /** Attaches sidebar tab click listeners and activates the default tab. */
    private setupTabs(): void {
        this.tabButtons.forEach((button) => {
            button.addEventListener("click", this.handleTabClick);
        });
        this.setActiveTab(this.activeTab);
    }

    /** Handles a tab button click and routes it to the active-tab setter. */
    private handleTabClick = (event: Event): void => {
        const button = event.currentTarget as HTMLButtonElement | null;
        const requestedTab = button?.dataset.templateBuilderTabButton;
        if (requestedTab === "blocks" || requestedTab === "styles" || requestedTab === "layers" || requestedTab === "settings" || requestedTab === "variables") {
            this.setActiveTab(requestedTab);
        }
    };

    /** Updates the visible tab panel and active button styling. */
    private setActiveTab(tab: TemplateBuilderTab): void {
        this.activeTab = tab;
        this.tabButtons.forEach((button) => {
            const isActive = button.dataset.templateBuilderTabButton === tab;
            button.classList.toggle("bg-slate-900", isActive);
            button.classList.toggle("text-white", isActive);
            button.classList.toggle("border-slate-900", isActive);
            button.classList.toggle("bg-white", !isActive);
            button.classList.toggle("text-slate-700", !isActive);
            button.classList.toggle("border-slate-300", !isActive);
        });
        this.tabPanels.forEach((panel) => {
            panel.classList.toggle("hidden", panel.dataset.templateBuilderTabPanel !== tab);
        });
    }

    /** Enables the search input used to filter visible block buttons. */
    private setupBlockSearch(): void {
        if (!this.blockSearchInput) return;
        this.blockSearchInput.addEventListener("input", this.handleBlockSearch);
    }

    /** Wires model-backed page settings to the editor preview. */
    private setupSettingsControls(): void {
        if (this.pageSizeInput) {
            this.pageSizeInput.value = this.pageSettings.pageSize;
            this.pageSizeInput.addEventListener("change", this.handlePageSettingChange);
        }
        if (this.pageOrientationInput) {
            this.pageOrientationInput.value = this.pageSettings.orientation;
            this.pageOrientationInput.addEventListener("change", this.handlePageSettingChange);
        }
        if (this.pageMarginInput) {
            this.pageMarginInput.value = String(this.pageSettings.marginInches);
            this.pageMarginInput.addEventListener("input", this.handlePageSettingChange);
        }
    }

    /** Reloads the builder catalog for the selected model source. */
    private setupContentTypeControl(): void {
        this.contentTypesEl?.addEventListener("bloomerp:widget-change", this.handleContentTypesChange);
    }

    private handleContentTypesChange = (event: Event): void => {
        const values = (event as CustomEvent<{ value?: unknown }>).detail?.value;
        const contentTypeIds = Array.isArray(values) ? values.map((value) => String(value)) : [];
        void this.refreshVariableCatalog(contentTypeIds);
    };

    private async refreshVariableCatalog(contentTypeIds: string[]): Promise<void> {
        const response = await fetch("/components/document-template-builder/catalog/", {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": this.getCsrfToken(),
            },
            body: JSON.stringify({
                content_type_ids: contentTypeIds,
                free_variables_json: this.freeVariablesInput?.value || "[]",
                template_content: this.hiddenInput?.value || "",
            }),
        });

        if (!response.ok) {
            console.error("Failed to refresh template builder catalog", response.status);
            return;
        }

        const catalog = await response.json() as TemplateBuilderVariableCatalog;
        this.renderVariableCatalog(catalog);
    }

    private renderVariableCatalog(catalog: TemplateBuilderVariableCatalog): void {
        this.variableCatalog = catalog;
        this.variablesPanel?.render(catalog);
        this.renderBlocks([
            ...readTemplateFields(this.fieldConfigScriptId),
            ...catalog.modelVariables.map((variable) => ({
                name: variable.token,
                label: variable.label,
                type: variable.fieldTypeLabel,
                token: `{{ ${variable.token} }}`,
            })),
        ]);
    }

    private getCsrfToken(): string {
        const csrfInput = this.element?.closest("form")?.querySelector<HTMLInputElement>("input[name=csrfmiddlewaretoken]");
        return csrfInput?.value || "";
    }

    /** Updates page dimensions and serialized style when settings controls change. */
    private handlePageSettingChange = (): void => {
        this.pageSettings = this.getInitialPageSettings();
        this.applyPageSettings();
        this.syncHiddenInput();
    };

    /** Filters block sections and items based on the current search query. */
    private handleBlockSearch = (): void => {
        if (!this.blocksEl || !this.blockSearchInput) return;
        const query = this.blockSearchInput.value.trim().toLowerCase();

        Array.from(this.blocksEl.querySelectorAll<HTMLElement>(".template-builder-panel-section")).forEach((section) => {
            const buttons = Array.from(section.querySelectorAll<HTMLElement>("button"));
            let visibleCount = 0;

            buttons.forEach((button) => {
                const haystack = `${button.textContent || ""} ${button.getAttribute("title") || ""}`.toLowerCase();
                const matches = query.length === 0 || haystack.includes(query);
                button.style.display = matches ? "" : "none";
                if (matches) visibleCount += 1;
            });

            section.style.display = visibleCount > 0 ? "" : "none";
        });
    };

    /** Restores focus to the Lexical root after sidebar interactions move it away. */
    private focusEditor(): void {
        this.editorRoot?.focus();
    }

    /** Inserts a top-level node near the active block, even after sidebar focus changes. */
    private insertBlockNode(node: LexicalNode): void {
        const root = $getRoot();
        const selection = $getSelection();

        if (!$isRangeSelection(selection)) {
            const fallbackTarget = this.lastActiveBlockKey ? $getNodeByKey(this.lastActiveBlockKey) : null;
            const fallbackTopLevel = fallbackTarget?.getTopLevelElement();

            if (fallbackTopLevel && fallbackTopLevel.isAttached()) {
                const isEmpty = fallbackTopLevel.getTextContent().trim() === "";
                if (isEmpty) {
                    fallbackTopLevel.replace(node);
                } else {
                    fallbackTopLevel.insertAfter(node);
                }
            } else {
                root.append(node);
            }

            if ($isElementNode(node)) {
                node.selectStart();
            }
            return;
        }

        const anchorNode = selection.anchor.getNode();
        const topLevel = anchorNode.getTopLevelElementOrThrow();
        const isEmpty = topLevel.getTextContent().trim() === "";

        if (isEmpty) {
            topLevel.replace(node);
        } else {
            topLevel.insertAfter(node);
        }

        if ($isElementNode(node)) {
            node.selectStart();
        }
    }

    /** Tracks selection changes so sidebar actions know where to insert new blocks. */
    private registerSelectionTracking(): void {
        if (!this.editor) return;

        this.editor.registerCommand(
            SELECTION_CHANGE_COMMAND,
            () => {
                this.captureSelectionAnchor();
                return false;
            },
            COMMAND_PRIORITY_EDITOR
        );
    }

    /** Remembers the currently active top-level block for focus-safe insertions. */
    private captureSelectionAnchor(): void {
        if (!this.editor) return;

        this.editor.getEditorState().read(() => {
            const selection = $getSelection();
            if (!$isRangeSelection(selection)) return;
            const topLevel = selection.anchor.getNode().getTopLevelElement();
            this.lastActiveBlockKey = topLevel?.getKey() || null;
        });
    }

    /** Stores the latest serialized document snapshot for simple undo/redo. */
    private captureHistorySnapshot(force = false): void {
        if (!this.hiddenInput) return;
        this.history?.capture(this.hiddenInput.value, force);
    }

    /** Restores the previous saved snapshot if one exists. */
    private undo(): void {
        this.history?.undo();
    }

    /** Restores the next saved snapshot if one exists. */
    private redo(): void {
        this.history?.redo();
    }

    /** Opens the image picker for prompt-driven image insertion blocks. */
    private promptImageUpload(): void {
        this.imageController?.promptImageUpload();
    }

    /** Applies left or center alignment to the current or last-active top-level block. */
    private applyElementAlignment(alignment: "left" | "center"): void {
        if (!this.editor) return;

        this.editorRoot?.focus();
        this.editor.update(() => {
            const selection = $getSelection();
            if ($isRangeSelection(selection)) {
                this.editor?.dispatchCommand(FORMAT_ELEMENT_COMMAND, alignment);
                return;
            }

            const fallbackTarget = this.lastActiveBlockKey ? $getNodeByKey(this.lastActiveBlockKey) : null;
            const fallbackTopLevel = fallbackTarget?.getTopLevelElement();
            if ($isElementNode(fallbackTopLevel)) {
                fallbackTopLevel.setFormat(alignment);
            }
        });
    }

    /** Imports arbitrary HTML snippets and inserts them as normalized top-level nodes. */
    private insertHtmlSnippet(html: string): void {
        if (!this.editor) return;

        this.editorRoot?.focus();

        const parser = new DOMParser();
        const dom = parser.parseFromString(html, "text/html");
        const nodes = this.normalizeNodesForRoot($generateNodesFromDOM(this.editor, dom));

        this.editor.update(() => {
            if (nodes.length === 0) return;
            nodes.forEach((node) => {
                this.insertBlockNode(node);
            });
        });
    }

    /** Inserts Django template syntax as literal editor text without HTML parsing. */
    private insertTemplateSnippet(snippet: string): void {
        if (!this.editor) return;

        this.editorRoot?.focus();
        this.editor.update(() => {
            const selection = $getSelection();
            if ($isRangeSelection(selection) && !snippet.includes("\n")) {
                selection.insertText(snippet);
                return;
            }

            const paragraph = $createParagraphNode();
            paragraph.append($createTextNode(snippet));
            this.insertBlockNode(paragraph);
            paragraph.selectEnd();
        });
        this.editorRoot?.focus();
    }

    /** Ensures imported DOM content is safe to append to the Lexical root node. */
    private normalizeNodesForRoot(nodes: LexicalNode[]): LexicalNode[] {
        const normalized: LexicalNode[] = [];

        nodes.forEach((node) => {
            if (node.getType() === "root") {
                return;
            }

            if ($isElementNode(node) || $isDecoratorNode(node)) {
                normalized.push(node);
                return;
            }

            if ($isTextNode(node)) {
                const text = node.getTextContent();
                if (!text.trim()) return;

                const paragraph = $createParagraphNode();
                paragraph.append($createTextNode(text));
                normalized.push(paragraph);
                return;
            }

            const fallbackText = node.getTextContent().trim();
            if (!fallbackText) {
                return;
            }

            const paragraph = $createParagraphNode();
            paragraph.append($createTextNode(fallbackText));
            normalized.push(paragraph);
        });

        return normalized;
    }

    /** Replaces the active top-level block with a heading or paragraph variant. */
    private wrapSelectionWithBlock(type: "h1" | "h2" | "p"): void {
        if (!this.editor) return;

        this.editor.update(() => {
            const selection = $getSelection();
            const current =
                $isRangeSelection(selection)
                    ? selection.anchor.getNode().getTopLevelElementOrThrow()
                    : this.lastActiveBlockKey
                        ? $getNodeByKey(this.lastActiveBlockKey)?.getTopLevelElement()
                        : null;

            if (!current || !$isElementNode(current)) return;
            const text = current.getTextContent();

            let node;
            if (type === "h1" || type === "h2") {
                node = $createHeadingNode(type);
            } else {
                node = $createParagraphNode();
            }
            node.append($createTextNode(text));
            current.replace(node);
        });
    }

    /** Serializes the current editor state into the hidden input used by the wizard. */
    private syncHiddenInput(): void {
        if (!this.editor || !this.hiddenInput) return;

        let html = "";
        this.editor.getEditorState().read(() => {
            html = $generateHtmlFromNodes(this.editor!, null);
        });

        this.hiddenInput.value = `<section data-template-page-root="true" style="${getPageWrapperStyle(this.pageSettings)}">${html}</section>`;
    }

    /** Serializes free variable definitions for the Django model JSON field. */
    private syncFreeVariablesInput(variables: TemplateBuilderFreeVariable[]): void {
        if (!this.freeVariablesInput) return;
        this.freeVariablesInput.value = JSON.stringify(variables.map((variable) => ({
            slug: variable.slug,
            label: variable.label,
            type: variable.type,
            required: variable.required,
            choices: variable.choices || [],
        })));
    }

    /** Applies size, orientation, and margin settings to the live page preview. */
    private applyPageSettings(): void {
        if (!this.pageEl || !this.editorRoot) return;

        const dimensions = getPageDimensions(this.pageSettings);
        const margin = `${this.pageSettings.marginInches}in`;
        const minContentHeight = `calc(${dimensions.height}mm - (${margin} * 2))`;

        this.pageEl.setAttribute("style", getPageWrapperStyle(this.pageSettings));
        this.editorRoot.style.minHeight = minContentHeight;

        if (this.pageSummaryEl) {
            this.pageSummaryEl.textContent = `${this.pageSettings.pageSize} ${this.pageSettings.orientation}`;
        }
    }



}
