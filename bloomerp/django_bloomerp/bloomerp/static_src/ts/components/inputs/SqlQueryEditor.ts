import BaseComponent from "../BaseComponent";
import ace from 'ace-builds/src-noconflict/ace';
import 'ace-builds/src-noconflict/ext-language_tools';
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
    private onEditorChange: (() => void) | null = null;
    private onExecuteClick: ((event: Event) => void) | null = null;
    private onSearchInput: ((event: Event) => void) | null = null;
    private onResultsSearchInput: ((event: Event) => void) | null = null;
    private onRefreshClick: ((event: Event) => void) | null = null;
    private onCatalogClick: ((event: Event) => void) | null = null;
    private onSaveClick: ((event: Event) => void) | null = null;
    private onTabsClick: ((event: Event) => void) | null = null;
    private onResultsSwap: ((event: Event) => void) | null = null;
    private onEditorDragOver: ((event: DragEvent) => void) | null = null;
    private onEditorDrop: ((event: DragEvent) => void) | null = null;
    private schemaCompleter: any = null;
    private localTabCounter = 1;

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
        this.saveButton = this.element.querySelector<HTMLButtonElement>('[data-sql-save]');
        this.queryNameInput = this.element.querySelector<HTMLInputElement>('[data-sql-query-name]');
        this.tabsContainer = this.element.querySelector<HTMLElement>('[data-sql-tabs]');
        this.csrfInput = this.element.querySelector<HTMLInputElement>('[data-sql-csrf]');

        if (!this.editorContainer || !this.queryInput) return;

        this.editor = ace.edit(this.editorContainer);
        this.editor.setTheme('ace/theme/chrome');

        this.editor.setOptions({
            enableBasicAutocompletion: true,
            enableLiveAutocompletion: false,
            enableSnippets: true,
            showPrintMargin: false,
            fontSize: 14,
            tabSize: 2,
            useSoftTabs: true,
        });

        this.editor.session.setUseWrapMode(true);
        this.setupEditorDropZone();

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
            this.executeQuery();
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
        };

        if (this.resultsTarget) {
            this.resultsTarget.addEventListener('htmx:afterSwap', this.onResultsSwap);
        }

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
    public executeQuery() : void {
        const query = this.getQuery().trim();
        if (!query || !this.resultsTarget) return;

        insertSkeleton(this.resultsTarget);

        htmx.ajax('post', this.executeUrl, {
            target: this.resultsTarget,
            swap: 'innerHTML',
            values: {
                sql_query: query,
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
        this.onEditorDragOver = null;
        this.onEditorDrop = null;
    }

    private async loadSqlMode(): Promise<void> {
        if (!this.editor) return;

        try {
            await import('ace-builds/src-noconflict/mode-sql');
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

                table.fields.forEach((field) => {
                    tokenSet.add(field.name);
                    tokenSet.add(`${table.name}.${field.name}`);
                });
            });
        });

        this.completionWords = Array.from(tokenSet).sort();
    }

    private setupSchemaCompleter(): void {
        if (!this.editor || this.schemaCompleter) return;

        this.schemaCompleter = {
            getCompletions: (
                _editor: any,
                _session: any,
                _pos: any,
                prefix: string,
                callback: (error: null, completions: any[]) => void,
            ) => {
                if (!prefix || prefix.length < 1) {
                    callback(null, []);
                    return;
                }

                const completions = this.completionWords
                    .filter((word) => word.toLowerCase().includes(prefix.toLowerCase()))
                    .slice(0, 100)
                    .map((word) => ({
                        caption: word,
                        value: word,
                        meta: word.includes('.') ? 'field' : 'sql',
                    }));

                callback(null, completions);
            },
        };

        const languageTools = (ace as any).require('ace/ext/language_tools');
        if (languageTools?.addCompleter) {
            languageTools.addCompleter(this.schemaCompleter);
        }
    }

}