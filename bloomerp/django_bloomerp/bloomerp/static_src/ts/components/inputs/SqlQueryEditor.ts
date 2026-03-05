import BaseComponent from "../BaseComponent";
import ace from 'ace-builds/src-noconflict/ace';
import htmx from "htmx.org";
import { insertSkeleton } from "../../utils/animations";

interface SqlField {
    name: string;
    field_type: string;
    icon?: string;
}

interface SqlTable {
    name: string;
    icon?: string;
    fields: SqlField[];
}

interface SqlDatabase {
    name: string;
    icon?: string;
    tables: SqlTable[];
}

interface SqlSchemaResponse {
    databases: SqlDatabase[];
}

interface SavedSqlQuery {
    id: number;
    name: string;
    query: string;
}

interface SavedSqlQueryResponse {
    queries: SavedSqlQuery[];
}


export default class SqlQueryEditor extends BaseComponent {
    private editor: any = null;
    private editorContainer: HTMLElement | null = null;
    private queryInput: HTMLTextAreaElement | null = null;
    private hiddenQueryInput: HTMLInputElement | null = null;
    private executeButton: HTMLButtonElement | null = null;
    private resultsTarget: HTMLElement | null = null;
    private catalogTree: HTMLElement | null = null;
    private searchInput: HTMLInputElement | null = null;
    private resultsSearchInput: HTMLInputElement | null = null;
    private refreshButton: HTMLButtonElement | null = null;
    private pageSizeSelect: HTMLSelectElement | null = null;
    private paginationControls: HTMLElement | null = null;
    private editorPane: HTMLElement | null = null;
    private resultsPane: HTMLElement | null = null;
    private resizeHandle: HTMLElement | null = null;
    private saveButton: HTMLButtonElement | null = null;
    private queryNameInput: HTMLInputElement | null = null;
    private csrfInput: HTMLInputElement | null = null;
    private tabsContainer: HTMLElement | null = null;
    private activeQueryIdInput: HTMLInputElement | null = null;
    private schemaUrl = '/api/sql/accessible-tables/';
    private executeUrl = '/components/execute_sql_query/';
    private queriesUrl = '/api/sql/queries/';
    private schemaData: SqlDatabase[] = [];
    private savedQueries: SavedSqlQuery[] = [];
    private activeQueryId: number | null = null;
    private completionWords: string[] = [];
    private tableFieldMap: Map<string, { name: string; fields: string[] }> = new Map();
    private onEditorChange: (() => void) | null = null;
    private onExecuteClick: ((event: Event) => void) | null = null;
    private onSearchInput: ((event: Event) => void) | null = null;
    private onResultsSearchInput: ((event: Event) => void) | null = null;
    private onRefreshClick: ((event: Event) => void) | null = null;
    private onCatalogClick: ((event: Event) => void) | null = null;
    private onSaveClick: ((event: Event) => void) | null = null;
    private onTabsClick: ((event: Event) => void) | null = null;
    private onResultsSwap: ((event: Event) => void) | null = null;
    private onPageSizeChange: ((event: Event) => void) | null = null;
    private onPaginationClick: ((event: Event) => void) | null = null;
    private onResizeHandleMouseDown: ((event: MouseEvent) => void) | null = null;
    private onWindowMouseMove: ((event: MouseEvent) => void) | null = null;
    private onWindowMouseUp: (() => void) | null = null;
    private onEditorDragOver: ((event: DragEvent) => void) | null = null;
    private onEditorDrop: ((event: DragEvent) => void) | null = null;
    private schemaCompleter: any = null;
    private localTabCounter = 1;
    private currentPage = 1;
    private totalPages = 1;
    private pageSize = 25;
    private isResizing = false;
    private resizeStartY = 0;
    private resizeStartEditorHeight = 0;
    private readonly editorHeightStorageKey = 'bloomerp.sqlQueryEditor.editorHeight';

    public initialize(): void {
        if (!this.element) return;

        this.schemaUrl = this.element.dataset.sqlSchemaUrl || this.schemaUrl;
        this.executeUrl = this.element.dataset.sqlExecuteUrl || this.executeUrl;
        this.queriesUrl = this.element.dataset.sqlQueriesUrl || this.queriesUrl;

        this.editorContainer = this.element.querySelector<HTMLElement>('[data-sql-editor]');
        this.queryInput = this.element.querySelector<HTMLTextAreaElement>('[data-sql-query-input]');
        this.hiddenQueryInput = this.element.querySelector<HTMLInputElement>('[data-sql-hidden-query-input]');
        this.activeQueryIdInput = this.element.querySelector<HTMLInputElement>('[data-sql-active-query-id]');
        this.executeButton = this.element.querySelector<HTMLButtonElement>('[data-sql-execute]');
        this.resultsTarget = this.element.querySelector<HTMLElement>('[data-sql-results-target]');
        this.catalogTree = this.element.querySelector<HTMLElement>('[data-sql-catalog-tree]');
        this.searchInput = this.element.querySelector<HTMLInputElement>('[data-sql-sidebar-search]');
        this.resultsSearchInput = this.element.querySelector<HTMLInputElement>('[data-sql-results-search]');
        this.refreshButton = this.element.querySelector<HTMLButtonElement>('[data-sql-refresh]');
        this.pageSizeSelect = this.element.querySelector<HTMLSelectElement>('[data-sql-page-size]');
        this.paginationControls = this.element.querySelector<HTMLElement>('[data-sql-pagination-controls]');
        this.editorPane = this.element.querySelector<HTMLElement>('[data-sql-editor-pane]');
        this.resultsPane = this.element.querySelector<HTMLElement>('[data-sql-results-pane]');
        this.resizeHandle = this.element.querySelector<HTMLElement>('[data-sql-resize-handle]');
        this.saveButton = this.element.querySelector<HTMLButtonElement>('[data-sql-save]');
        this.queryNameInput = this.element.querySelector<HTMLInputElement>('[data-sql-query-name]');
        this.tabsContainer = this.element.querySelector<HTMLElement>('[data-sql-tabs]');
        this.csrfInput = this.element.querySelector<HTMLInputElement>('[data-sql-csrf]');

        if (!this.editorContainer || !this.queryInput) return;

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
        this.setupEditorDropZone();
        this.setupResizablePanels();

        void this.loadLanguageTools();
        void this.loadSqlMode();

        const defaultQuery = this.hiddenQueryInput?.value || this.queryInput.value || this.queryInput.textContent || 'SELECT 1;';
        this.editor.setValue(defaultQuery.trim(), -1);
        this.queryInput.value = this.editor.getValue();

        if (this.hiddenQueryInput) {
            this.hiddenQueryInput.value = this.editor.getValue();
        }

        this.onEditorChange = () => {
            if (!this.queryInput || !this.editor) return;
            const value = this.editor.getValue();
            this.queryInput.value = value;

            this.persistActiveTabQuery(value);

            if (this.hiddenQueryInput) {
                this.hiddenQueryInput.value = value;
            }
        };

        this.editor.session.on('change', this.onEditorChange);

        this.onExecuteClick = (event: Event) => {
            event.preventDefault();
            this.executeQuery(1);
        };

        if (this.executeButton) {
            this.executeButton.addEventListener('click', this.onExecuteClick);
        }

        this.onSearchInput = (event: Event) => {
            const target = event.target as HTMLInputElement;
            this.renderCatalog(target.value.trim().toLowerCase());
        };

        if (this.searchInput) {
            this.searchInput.addEventListener('input', this.onSearchInput);
        }

        this.onResultsSearchInput = () => {
            this.filterResultsTable();
        };

        if (this.resultsSearchInput) {
            this.resultsSearchInput.addEventListener('input', this.onResultsSearchInput);
        }

        this.onRefreshClick = (event: Event) => {
            event.preventDefault();
            void this.fetchAndRenderSchema(true);
        };

        if (this.refreshButton) {
            this.refreshButton.addEventListener('click', this.onRefreshClick);
        }

        this.onCatalogClick = (event: Event) => {
            const target = event.target as HTMLElement;
            const insertElement = target.closest<HTMLElement>('[data-sql-insert-value]');
            if (!insertElement) return;

            const insertValue = insertElement.dataset.sqlInsertValue || '';
            if (!insertValue) return;

            event.preventDefault();
            this.insertIntoEditor(insertValue);
        };

        if (this.catalogTree) {
            this.catalogTree.addEventListener('click', this.onCatalogClick);
        }

        this.onSaveClick = (event: Event) => {
            event.preventDefault();
            void this.saveCurrentQuery();
        };

        if (this.saveButton) {
            this.saveButton.addEventListener('click', this.onSaveClick);
        }

        this.onTabsClick = (event: Event) => {
            const target = event.target as HTMLElement;

            const addTabButton = target.closest<HTMLElement>('[data-sql-tab-add]');
            if (addTabButton) {
                event.preventDefault();
                this.addNewLocalTab();
                return;
            }

            const tab = target.closest<HTMLElement>('[data-sql-tab-id]');
            if (!tab) return;

            const tabId = tab.dataset.sqlTabId || 'unsaved';
            this.activateTab(tabId);
        };

        if (this.tabsContainer) {
            this.tabsContainer.addEventListener('click', this.onTabsClick);
        }

        this.onResultsSwap = () => {
            this.filterResultsTable();
            this.syncPaginationStateFromResultsMeta();
            this.updatePaginationControls();
        };

        if (this.resultsTarget) {
            this.resultsTarget.addEventListener('htmx:afterSwap', this.onResultsSwap);
        }

        this.onPageSizeChange = (event: Event) => {
            const target = event.target as HTMLSelectElement;
            const nextPageSize = Number.parseInt(target.value, 10);
            if (Number.isNaN(nextPageSize) || nextPageSize < 1) return;

            this.pageSize = nextPageSize;
            this.executeQuery(1);
        };

        if (this.pageSizeSelect) {
            this.pageSizeSelect.value = String(this.pageSize);
            this.pageSizeSelect.addEventListener('change', this.onPageSizeChange);
        }

        this.onPaginationClick = (event: Event) => {
            const target = event.target as HTMLElement;
            const button = target.closest<HTMLElement>('[data-sql-page-nav]');
            if (!button) return;

            event.preventDefault();
            const direction = button.dataset.sqlPageNav;
            if (direction === 'prev' && this.currentPage > 1) {
                this.executeQuery(this.currentPage - 1);
            } else if (direction === 'next' && this.currentPage < this.totalPages) {
                this.executeQuery(this.currentPage + 1);
            }
        };

        if (this.paginationControls) {
            this.paginationControls.addEventListener('click', this.onPaginationClick);
        }

        this.syncPaginationStateFromResultsMeta();
        this.updatePaginationControls();

        void Promise.all([
            this.fetchAndRenderSchema(false),
            this.fetchSavedQueries(),
        ]);
    }

    /**
     * Returns the SQL query from the editor.
     * @returns The SQL query as a string.
     */
    public getQuery() : string {
        if (this.editor) {
            return this.editor.getValue();
        }
        return this.queryInput?.value || '';
    }


    /**
     * Executes the SQL query and displays the results.
     */
    public executeQuery(page: number = this.currentPage) : void {
        const query = this.getQuery().trim();
        if (!query || !this.resultsTarget) return;

        this.currentPage = Math.max(1, page);
        insertSkeleton(this.resultsTarget);

        htmx.ajax('post', this.executeUrl, {
            target: this.resultsTarget,
            swap: 'innerHTML',
            values: {
                sql_query: query,
                sql_page: this.currentPage,
                sql_page_size: this.pageSize,
                csrfmiddlewaretoken: this.csrfInput?.value || '',
            },
        });
    }

    public destroy(): void {
        if (this.editor && this.onEditorChange) {
            this.editor.session.off('change', this.onEditorChange);
        }

        if (this.executeButton && this.onExecuteClick) {
            this.executeButton.removeEventListener('click', this.onExecuteClick);
        }

        if (this.searchInput && this.onSearchInput) {
            this.searchInput.removeEventListener('input', this.onSearchInput);
        }

        if (this.resultsSearchInput && this.onResultsSearchInput) {
            this.resultsSearchInput.removeEventListener('input', this.onResultsSearchInput);
        }

        if (this.refreshButton && this.onRefreshClick) {
            this.refreshButton.removeEventListener('click', this.onRefreshClick);
        }

        if (this.catalogTree && this.onCatalogClick) {
            this.catalogTree.removeEventListener('click', this.onCatalogClick);
        }

        if (this.saveButton && this.onSaveClick) {
            this.saveButton.removeEventListener('click', this.onSaveClick);
        }

        if (this.tabsContainer && this.onTabsClick) {
            this.tabsContainer.removeEventListener('click', this.onTabsClick);
        }

        if (this.resultsTarget && this.onResultsSwap) {
            this.resultsTarget.removeEventListener('htmx:afterSwap', this.onResultsSwap);
        }

        if (this.pageSizeSelect && this.onPageSizeChange) {
            this.pageSizeSelect.removeEventListener('change', this.onPageSizeChange);
        }

        if (this.paginationControls && this.onPaginationClick) {
            this.paginationControls.removeEventListener('click', this.onPaginationClick);
        }

        if (this.resizeHandle && this.onResizeHandleMouseDown) {
            this.resizeHandle.removeEventListener('mousedown', this.onResizeHandleMouseDown);
        }

        if (this.onWindowMouseMove) {
            window.removeEventListener('mousemove', this.onWindowMouseMove);
        }

        if (this.onWindowMouseUp) {
            window.removeEventListener('mouseup', this.onWindowMouseUp);
        }

        if (this.editorContainer && this.onEditorDragOver) {
            this.editorContainer.removeEventListener('dragover', this.onEditorDragOver);
        }

        if (this.editorContainer && this.onEditorDrop) {
            this.editorContainer.removeEventListener('drop', this.onEditorDrop);
        }

        if (this.editor) {
            this.editor.destroy();
        }

        this.editor = null;
        this.onEditorChange = null;
        this.onExecuteClick = null;
        this.onSearchInput = null;
        this.onResultsSearchInput = null;
        this.onRefreshClick = null;
        this.onCatalogClick = null;
        this.onSaveClick = null;
        this.onTabsClick = null;
        this.onResultsSwap = null;
        this.onPageSizeChange = null;
        this.onPaginationClick = null;
        this.onResizeHandleMouseDown = null;
        this.onWindowMouseMove = null;
        this.onWindowMouseUp = null;
        this.onEditorDragOver = null;
        this.onEditorDrop = null;
    }

    private async loadSqlMode(): Promise<void> {
        if (!this.editor) return;

        try {
            this.editor.session.setMode('ace/mode/sql');
        } catch (error) {
            console.warn('Failed to load Ace SQL mode', error);
        }
    }

    private async fetchAndRenderSchema(refresh: boolean): Promise<void> {
        if (!this.catalogTree) return;

        const searchValue = this.searchInput?.value.trim() || '';
        const params = new URLSearchParams();

        if (searchValue) {
            params.set('search', searchValue);
        }

        if (refresh) {
            params.set('refresh', 'true');
        }

        const endpoint = `${this.schemaUrl}?${params.toString()}`;

        try {
            insertSkeleton(this.catalogTree);

            const response = await fetch(endpoint, {
                credentials: 'same-origin',
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch schema: ${response.status}`);
            }

            const payload = await response.json() as SqlSchemaResponse;
            this.schemaData = payload.databases || [];
            this.renderCatalog(searchValue.toLowerCase());
            this.refreshAutocompleteTokens();
            this.setupSchemaCompleter();
        } catch (error) {
            this.catalogTree.innerHTML = `<div class="text-red-600 text-sm">Failed to load schema</div>`;
            console.error(error);
        }
    }

    private async fetchSavedQueries(): Promise<void> {
        if (!this.tabsContainer) return;

        try {
            const response = await fetch(this.queriesUrl, {
                credentials: 'same-origin',
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch saved queries: ${response.status}`);
            }

            const payload = await response.json() as SavedSqlQueryResponse;
            this.savedQueries = payload.queries || [];

            if (this.savedQueries.length > 0) {
                const initialId = this.activeQueryId ?? this.savedQueries[0].id;
                this.renderTabs(initialId);
                this.activateTab(String(initialId));
            } else {
                this.renderTabs(null);
            }
        } catch (error) {
            console.error(error);
            this.renderTabs(null);
        }
    }

    private renderCatalog(search: string): void {
        if (!this.catalogTree) return;

        const html: string[] = [];

        this.schemaData.forEach((database) => {
            const tableHtml: string[] = [];

            database.tables.forEach((table) => {
                const fieldRows = table.fields.filter((field) => {
                    if (!search) return true;
                    return field.name.toLowerCase().includes(search) || table.name.toLowerCase().includes(search);
                });

                const tableMatches = !search || table.name.toLowerCase().includes(search);
                if (!tableMatches && fieldRows.length === 0) return;

                const fieldsHtml = fieldRows
                    .map((field) => `
                        <button
                            type="button"
                            class="w-full min-w-0 text-left px-2 py-1.5 rounded-md hover:bg-white text-gray-700 flex items-center gap-2"
                            data-sql-insert-value="${table.name}.${field.name}"
                            draggable="true"
                            title="${table.name}.${field.name}"
                        >
                            <i class="${field.icon || 'fa-solid fa-table-columns'} text-xs text-gray-500 shrink-0"></i>
                            <span class="flex-1 min-w-0 truncate">${field.name}</span>
                            <span class="text-[10px] text-gray-400 ml-auto shrink-0">${field.field_type}</span>
                        </button>
                    `)
                    .join('');

                tableHtml.push(`
                    <details class="group border border-transparent rounded-md open:bg-white/60">
                        <summary class="list-none min-w-0 cursor-pointer px-2 py-1.5 rounded-md hover:bg-white flex items-center gap-2 text-gray-800" style="list-style: none;" title="${table.name}">
                            <i class="fa-solid fa-chevron-right text-[10px] text-gray-400 group-open:rotate-90 transition-transform shrink-0"></i>
                            <i class="${table.icon || 'fa-solid fa-table'} text-xs text-gray-500 shrink-0"></i>
                            <span
                                class="text-left hover:text-primary-700 flex-1 min-w-0 truncate"
                                data-sql-insert-value="${table.name}"
                                draggable="true"
                                title="${table.name}"
                            >${table.name}</span>
                        </summary>
                        <div class="ml-6 mt-1 space-y-0.5 min-w-0 overflow-hidden">
                            ${fieldsHtml || '<div class="text-xs text-gray-400 px-2 py-1">No fields found</div>'}
                        </div>
                    </details>
                `);
            });

            if (tableHtml.length === 0) return;

            html.push(`
                <details class="group" open>
                    <summary class="list-none min-w-0 cursor-pointer px-2 py-1.5 rounded-md bg-white border border-base flex items-center gap-2 text-gray-800" style="list-style: none;" title="${database.name}">
                        <i class="fa-solid fa-chevron-right text-[10px] text-gray-400 group-open:rotate-90 transition-transform shrink-0"></i>
                        <i class="${database.icon || 'fa-solid fa-database'} text-xs text-gray-600 shrink-0"></i>
                        <span class="flex-1 min-w-0 truncate">${database.name}</span>
                    </summary>
                    <div class="mt-2 space-y-1 min-w-0 overflow-hidden">
                        ${tableHtml.join('')}
                    </div>
                </details>
            `);
        });

        this.catalogTree.innerHTML = html.length > 0
            ? html.join('')
            : '<div class="text-gray-500 text-sm">No tables or fields match your search.</div>';

        const draggableItems = this.catalogTree.querySelectorAll<HTMLElement>('[draggable="true"]');
        draggableItems.forEach((item) => {
            item.addEventListener('dragstart', (event: DragEvent) => {
                const insertValue = item.dataset.sqlInsertValue || '';
                if (!event.dataTransfer || !insertValue) return;
                event.dataTransfer.setData('text/plain', insertValue);
                event.dataTransfer.effectAllowed = 'copy';
            });
        });
    }

    private renderTabs(activeId: number | null): void {
        if (!this.tabsContainer) return;

        const tabs: string[] = [];

        if (this.savedQueries.length === 0) {
            const currentQuery = this.getQuery();
            tabs.push(`
                <li
                    class="px-4 py-3 border-b-2 border-primary bg-primary/5 text-primary font-medium cursor-pointer"
                    data-sql-tab-id="unsaved"
                    data-sql-tab-query="${this.escapeAttribute(currentQuery)}"
                    title="Unsaved Query"
                >Unsaved Query</li>
            `);
        } else {
            this.savedQueries.forEach((query) => {
                const isActive = activeId === query.id;
                tabs.push(`
                    <li
                        class="px-4 py-3 cursor-pointer border-r border-base ${isActive ? 'border-b-2 border-primary bg-primary/5 text-primary font-medium' : 'text-gray-700'}"
                        data-sql-tab-id="${query.id}"
                        data-sql-tab-query="${this.escapeAttribute(query.query)}"
                        title="${this.escapeAttribute(query.name)}"
                    >${this.escapeHtml(query.name)}</li>
                `);
            });
        }

        tabs.push('<li class="px-4 py-3 text-gray-500 cursor-pointer" data-sql-tab-add title="New query tab"><i class="fa-solid fa-plus"></i></li>');
        this.tabsContainer.innerHTML = tabs.join('');

        const localTabs = this.tabsContainer.querySelectorAll<HTMLElement>('[data-sql-tab-id^="local-"]');
        this.localTabCounter = Math.max(this.localTabCounter, localTabs.length + 1);
    }

    private activateTab(tabId: string): void {
        if (!this.tabsContainer || !this.editor) return;

        this.persistActiveTabQuery(this.getQuery());

        const tabItems = this.tabsContainer.querySelectorAll<HTMLElement>('[data-sql-tab-id]');
        let activeQuery = '';
        let activeName = 'Unsaved Query';

        tabItems.forEach((tabItem) => {
            const isActive = tabItem.dataset.sqlTabId === tabId;
            tabItem.classList.toggle('border-b-2', isActive);
            tabItem.classList.toggle('border-primary', isActive);
            tabItem.classList.toggle('bg-primary/5', isActive);
            tabItem.classList.toggle('text-primary', isActive);
            tabItem.classList.toggle('font-medium', isActive);
            tabItem.classList.toggle('text-gray-700', !isActive);

            if (isActive) {
                activeQuery = tabItem.dataset.sqlTabQuery || '';
                activeName = (tabItem.textContent || '').trim() || activeName;
            }
        });

        this.editor.setValue(activeQuery, -1);
        this.queryInput!.value = activeQuery;

        if (this.hiddenQueryInput) {
            this.hiddenQueryInput.value = activeQuery;
        }

        const numericId = Number.parseInt(tabId, 10);
        this.activeQueryId = Number.isNaN(numericId) ? null : numericId;

        if (this.activeQueryIdInput) {
            this.activeQueryIdInput.value = this.activeQueryId ? String(this.activeQueryId) : '';
        }

        if (this.queryNameInput) {
            this.queryNameInput.value = activeName;
        }
    }

    private persistActiveTabQuery(queryValue: string): void {
        if (!this.tabsContainer) return;

        const activeTab = this.tabsContainer.querySelector<HTMLElement>('[data-sql-tab-id].border-b-2');
        if (!activeTab) return;

        activeTab.dataset.sqlTabQuery = queryValue;
    }

    private addNewLocalTab(): void {
        if (!this.tabsContainer || !this.editor) return;

        this.persistActiveTabQuery(this.getQuery());

        const tabId = `local-${Date.now()}-${this.localTabCounter}`;
        const tabName = `Query ${this.localTabCounter}`;
        this.localTabCounter += 1;

        const addButton = this.tabsContainer.querySelector<HTMLElement>('[data-sql-tab-add]');

        const newTab = document.createElement('li');
        newTab.className = 'px-4 py-3 cursor-pointer border-r border-base text-gray-700';
        newTab.dataset.sqlTabId = tabId;
        newTab.dataset.sqlTabQuery = '';
        newTab.title = tabName;
        newTab.textContent = tabName;

        if (addButton && addButton.parentElement === this.tabsContainer) {
            this.tabsContainer.insertBefore(newTab, addButton);
        } else {
            this.tabsContainer.appendChild(newTab);
        }

        this.activateTab(tabId);
    }

    private async saveCurrentQuery(): Promise<void> {
        const query = this.getQuery().trim();
        const name = (this.queryNameInput?.value || '').trim();

        if (!query || !name) {
            return;
        }

        const payload: Record<string, string | number> = {
            name,
            query,
        };

        if (this.activeQueryId) {
            payload.id = this.activeQueryId;
        }

        const response = await fetch(this.queriesUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfInput?.value || '',
            },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            return;
        }

        const payloadResult = await response.json() as { query: SavedSqlQuery };
        const savedQuery = payloadResult.query;

        this.activeQueryId = savedQuery.id;

        const existingIndex = this.savedQueries.findIndex((item) => item.id === savedQuery.id);
        if (existingIndex >= 0) {
            this.savedQueries[existingIndex] = savedQuery;
        } else {
            this.savedQueries.unshift(savedQuery);
        }

        this.renderTabs(savedQuery.id);
        this.activateTab(String(savedQuery.id));
    }

    private filterResultsTable(): void {
        if (!this.resultsTarget) return;

        const query = (this.resultsSearchInput?.value || '').trim().toLowerCase();
        const rows = this.resultsTarget.querySelectorAll<HTMLTableRowElement>('tbody tr');

        rows.forEach((row) => {
            const rowText = (row.textContent || '').toLowerCase();
            const matches = !query || rowText.includes(query);
            row.classList.toggle('hidden', !matches);
        });
    }

    private syncPaginationStateFromResultsMeta(): void {
        if (!this.resultsTarget) return;

        const meta = this.resultsTarget.querySelector<HTMLElement>('[data-sql-results-meta]');
        if (!meta) return;

        const nextPage = Number.parseInt(meta.dataset.sqlPage || '', 10);
        const nextTotalPages = Number.parseInt(meta.dataset.sqlTotalPages || '', 10);
        const nextPageSize = Number.parseInt(meta.dataset.sqlPageSize || '', 10);

        this.currentPage = Number.isNaN(nextPage) ? 1 : Math.max(1, nextPage);
        this.totalPages = Number.isNaN(nextTotalPages) ? 1 : Math.max(1, nextTotalPages);
        this.pageSize = Number.isNaN(nextPageSize) ? this.pageSize : Math.max(1, nextPageSize);

        if (this.pageSizeSelect) {
            this.pageSizeSelect.value = String(this.pageSize);
        }
    }

    private updatePaginationControls(): void {
        if (!this.paginationControls) return;

        const label = this.paginationControls.querySelector<HTMLElement>('[data-sql-page-label]');
        const prevButton = this.paginationControls.querySelector<HTMLButtonElement>('[data-sql-page-nav="prev"]');
        const nextButton = this.paginationControls.querySelector<HTMLButtonElement>('[data-sql-page-nav="next"]');

        if (label) {
            label.textContent = `Page ${this.currentPage} of ${this.totalPages}`;
        }

        if (prevButton) {
            prevButton.disabled = this.currentPage <= 1;
        }

        if (nextButton) {
            nextButton.disabled = this.currentPage >= this.totalPages;
        }
    }

    private setupResizablePanels(): void {
        if (!this.editorPane || !this.resultsPane || !this.resizeHandle) return;

        const storedHeight = window.localStorage.getItem(this.editorHeightStorageKey);
        if (storedHeight) {
            const parsedHeight = Number.parseInt(storedHeight, 10);
            if (!Number.isNaN(parsedHeight)) {
                this.setEditorPaneHeight(parsedHeight, false);
            }
        }

        this.onResizeHandleMouseDown = (event: MouseEvent) => {
            event.preventDefault();
            if (!this.editorPane) return;

            this.isResizing = true;
            this.resizeStartY = event.clientY;
            this.resizeStartEditorHeight = this.editorPane.getBoundingClientRect().height;
            document.body.classList.add('select-none');
            document.body.style.cursor = 'row-resize';
        };

        this.onWindowMouseMove = (event: MouseEvent) => {
            if (!this.isResizing) return;
            const deltaY = event.clientY - this.resizeStartY;
            this.setEditorPaneHeight(this.resizeStartEditorHeight + deltaY, false);
        };

        this.onWindowMouseUp = () => {
            if (!this.isResizing) return;
            this.isResizing = false;
            document.body.classList.remove('select-none');
            document.body.style.cursor = '';

            if (this.editorPane) {
                const height = Math.round(this.editorPane.getBoundingClientRect().height);
                window.localStorage.setItem(this.editorHeightStorageKey, String(height));
            }
        };

        this.resizeHandle.addEventListener('mousedown', this.onResizeHandleMouseDown);
        window.addEventListener('mousemove', this.onWindowMouseMove);
        window.addEventListener('mouseup', this.onWindowMouseUp);
    }

    private setEditorPaneHeight(rawHeight: number, persist: boolean): void {
        if (!this.editorPane || !this.resultsPane || !this.resizeHandle) return;

        const minEditorHeight = 160;
        const minResultsHeight = 180;

        const resultsRect = this.resultsPane.getBoundingClientRect();
        const handleRect = this.resizeHandle.getBoundingClientRect();
        const totalResizableHeight = this.editorPane.getBoundingClientRect().height + handleRect.height + resultsRect.height;
        const maxEditorHeight = Math.max(minEditorHeight, totalResizableHeight - handleRect.height - minResultsHeight);
        const nextHeight = Math.max(minEditorHeight, Math.min(rawHeight, maxEditorHeight));

        this.editorPane.style.height = `${Math.round(nextHeight)}px`;
        this.editorPane.style.flex = '0 0 auto';

        if (this.editor) {
            this.editor.resize();
        }

        if (persist) {
            window.localStorage.setItem(this.editorHeightStorageKey, String(Math.round(nextHeight)));
        }
    }

    private escapeHtml(value: string): string {
        return value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    private escapeAttribute(value: string): string {
        return this.escapeHtml(value).replace(/"/g, '&quot;');
    }

    private setupEditorDropZone(): void {
        if (!this.editorContainer) return;

        this.onEditorDragOver = (event: DragEvent) => {
            event.preventDefault();
            if (!event.dataTransfer) return;
            event.dataTransfer.dropEffect = 'copy';
        };

        this.onEditorDrop = (event: DragEvent) => {
            event.preventDefault();
            if (!event.dataTransfer) return;

            const value = event.dataTransfer.getData('text/plain');
            if (!value) return;
            this.insertIntoEditor(value);
        };

        this.editorContainer.addEventListener('dragover', this.onEditorDragOver);
        this.editorContainer.addEventListener('drop', this.onEditorDrop);
    }

    private insertIntoEditor(value: string): void {
        if (!this.editor || !value) return;

        const normalized = /\s/.test(value) ? `"${value}"` : value;
        this.editor.insert(normalized);
        this.editor.focus();
    }

    private refreshAutocompleteTokens(): void {
        this.tableFieldMap.clear();

        const tokenSet = new Set<string>([
            'select',
            'from',
            'where',
            'join',
            'left',
            'right',
            'inner',
            'outer',
            'group by',
            'order by',
            'limit',
            'having',
            'with',
            'as',
            'count',
            'sum',
            'avg',
            'min',
            'max',
        ]);

        this.schemaData.forEach((database) => {
            database.tables.forEach((table) => {
                tokenSet.add(table.name);
                this.tableFieldMap.set(
                    table.name.toLowerCase(),
                    {
                        name: table.name,
                        fields: table.fields.map((field) => field.name),
                    },
                );

                table.fields.forEach((field) => {
                    tokenSet.add(field.name);
                    tokenSet.add(`${table.name}.${field.name}`);
                });
            });
        });

        this.completionWords = Array.from(tokenSet).sort();
    }

    private setupSchemaCompleter(): void {
        if (!this.editor) return;

        if (!this.schemaCompleter) {
            this.schemaCompleter = {
                insertMatch: (editor: any, data: any) => {
                    const value = data?.value || data?.caption || '';
                    if (!value) return;

                    const session = editor.getSession();
                    const pos = editor.getCursorPosition();
                    const lineUntilCursor = (session.getLine(pos.row) || '').slice(0, pos.column);
                    const prefixMatch = lineUntilCursor.match(/([a-zA-Z_][\w]*)$/);

                    if (!prefixMatch) {
                        editor.insert(value);
                        return;
                    }

                    const Range = (ace as any).require('ace/range').Range;
                    const prefix = prefixMatch[1];
                    const range = new Range(pos.row, pos.column - prefix.length, pos.row, pos.column);
                    session.replace(range, value);
                },
                getCompletions: (
                    _editor: any,
                    session: any,
                    pos: any,
                    prefix: string,
                    callback: (error: null, completions: any[]) => void,
                ) => {
                    const lineUntilCursor = (session.getLine(pos.row) || '').slice(0, pos.column);
                    const identifierBeforeDotMatch = lineUntilCursor.match(/([a-zA-Z_][\w]*)\.\s*$/);
                    const isTableContext = /\b(from|join)\s+[\w"]*$/i.test(lineUntilCursor);

                    if (identifierBeforeDotMatch) {
                        const identifier = identifierBeforeDotMatch[1];
                        const aliasMap = this.extractTableAliases(this.getQuery());
                        const tableName = aliasMap.get(identifier.toLowerCase()) || identifier;
                        const tableConfig = this.tableFieldMap.get(tableName.toLowerCase());
                        const fieldNames = tableConfig?.fields || [];

                        const completions = fieldNames.slice(0, 200).map((fieldName) => ({
                            caption: fieldName,
                            value: fieldName,
                            meta: tableConfig?.name || tableName,
                            score: 2000,
                        }));
                        callback(null, completions);
                        return;
                    }

                    if (!prefix || prefix.length < 1) {
                        callback(null, []);
                        return;
                    }

                    if (isTableContext) {
                        const tableCompletions = Array.from(this.tableFieldMap.values())
                            .map((tableConfig) => tableConfig.name)
                            .filter((tableName) => tableName.toLowerCase().includes(prefix.toLowerCase()))
                            .slice(0, 100)
                            .map((tableName) => ({
                                caption: tableName,
                                value: tableName,
                                meta: 'table',
                                score: tableName.toLowerCase().startsWith(prefix.toLowerCase()) ? 1900 : 1200,
                            }));

                        callback(null, tableCompletions);
                        return;
                    }

                    const completions = this.completionWords
                        .filter((word) => word.toLowerCase().includes(prefix.toLowerCase()))
                        .slice(0, 100)
                        .map((word) => ({
                            caption: word,
                            value: word,
                            meta: word.includes('.') ? 'field' : 'sql',
                            score: word.toLowerCase().startsWith(prefix.toLowerCase()) ? 1500 : 900,
                        }));

                    callback(null, completions);
                },
            };
        }

        // Force our schema-aware completer as the active source for Ace autocomplete.
        this.editor.completers = [this.schemaCompleter];
    }

    private configureAutocompleteBehavior(): void {
        const languageTools = (ace as any).require('ace/ext/language_tools');
        if (languageTools?.Autocomplete?.prototype) {
            // Prevent automatic insertion when there is a single suggestion; user must confirm.
            languageTools.Autocomplete.prototype.autoInsert = false;
            languageTools.Autocomplete.prototype.autoSelect = true;
        }

        if (this.editor && (this.editor as any).completer) {
            (this.editor as any).completer.autoInsert = false;
            (this.editor as any).completer.autoSelect = true;
        }
    }

    private configureAceModuleLoader(): void {
        const aceConfig = (ace as any).config;
        if (!aceConfig?.setLoader) return;

        // Use Ace's native loader hook so loadModule() never falls back to "loader is not configured".
        aceConfig.setLoader((moduleName: string, cb: (error: unknown, module?: unknown) => void) => {
            const normalized = moduleName.startsWith('./') ? `ace/${moduleName.slice(2)}` : moduleName;

            const resolveModule = (): Promise<unknown> => {
                if (normalized === 'ace/theme/chrome') {
                    return import('ace-builds/src-noconflict/theme-chrome');
                }

                if (normalized === 'ace/mode/sql') {
                    return import('ace-builds/src-noconflict/mode-sql');
                }

                if (normalized === 'ace/ext/language_tools') {
                    return import('ace-builds/src-noconflict/ext-language_tools');
                }

                return Promise.reject(new Error(`Unsupported Ace module: ${normalized}`));
            };

            void resolveModule()
                .then((module) => cb(null, (module as any)?.default || module))
                .catch((error) => cb(error));
        });
    }

    private async loadLanguageTools(): Promise<void> {
        if (!this.editor) return;

        try {
            const aceConfig = (ace as any).config;
            if (!aceConfig?.loadModule) {
                throw new Error('Ace module loader is unavailable');
            }

            await new Promise<void>((resolve, reject) => {
                aceConfig.loadModule('ace/ext/language_tools', (module: any) => {
                    if (!module) {
                        reject(new Error('Ace language tools failed to load'));
                        return;
                    }
                    resolve();
                });
            });
        } catch (error) {
            console.warn('Failed to load Ace language tools', error);
            return;
        }

        this.editor.setOptions({
            enableBasicAutocompletion: true,
            enableLiveAutocompletion: true,
            enableSnippets: false,
        });
        this.configureAutocompleteBehavior();
        this.setupSchemaCompleter();
    }

    private extractTableAliases(sql: string): Map<string, string> {
        const aliasMap = new Map<string, string>();
        const aliasRegex = /\b(?:from|join)\s+("?[\w\.]+"?)\s+(?:as\s+)?("?[\w]+"?)/gi;
        let match: RegExpExecArray | null = aliasRegex.exec(sql);

        while (match) {
            const tableName = (match[1] || '').replace(/"/g, '');
            const aliasName = (match[2] || '').replace(/"/g, '');
            if (tableName && aliasName) {
                aliasMap.set(aliasName.toLowerCase(), tableName);
            }
            match = aliasRegex.exec(sql);
        }

        return aliasMap;
    }

}
