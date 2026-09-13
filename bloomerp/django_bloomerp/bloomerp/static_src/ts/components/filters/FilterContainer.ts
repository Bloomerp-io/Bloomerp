import BaseComponent from '../BaseComponent';
import { t } from '@/utils/i18n';
import { FilterApi } from './api';
import { ConditionEditor } from './ConditionEditor';
import { parseInitialFilters, type Filter, type FilterCondition } from './definition';
import { button, element } from './dom';
import './editor.css';

type GroupEditor = { root: HTMLDivElement; content: HTMLElement; toggle: HTMLButtonElement; connector: HTMLSelectElement; rows: ConditionEditor[] };

export default class FilterContainer extends BaseComponent {
    static readonly applyEvent = 'bloomerp:filters-apply';
    private api: FilterApi;
    private groups: GroupEditor[] = [];
    private body = element('div', 'space-y-3 p-3 empty:hidden');
    private error = element('p', 'px-3 pb-3 text-sm text-danger-dark empty:hidden');
    private output = element('input');
    private initialized = false;
    private invalidInitialState = false;

    initialize(): void {
        if (!this.element || this.initialized) return;
        this.initialized = true;
        const scope = this.getDataAttribute('scope');
        const id = this.getDataAttribute('scopeId');
        this.error.setAttribute('role', 'alert');
        this.output.type = 'hidden';
        this.output.name = this.getDataAttribute('name') ?? 'filter';
        this.api = new FilterApi(this.element, { scope: scope as 'model' | 'workspace', id });
        const controls = element('div', 'flex flex-wrap items-center gap-2 border-t border-gray-200 p-3');
        controls.append(
            button(t('Add group'), () => this.addGroup()),
            button(t('Clear'), () => { this.setFilters([]); }),
            button(t('Apply filters'), () => this.apply(), 'btn btn-primary btn-sm'),
            button(t('Select'), ()=>this.apply(), 'btn btn-primary btn-sm')
        );
        this.element.replaceChildren(this.body, this.error, controls, this.output);
        try {
            if (!id || !['model', 'workspace'].includes(scope)) throw new Error(t('Filter scope is missing.'));
            const initialFilters = parseInitialFilters(this.getDataAttribute('initialFilters') ?? '[]');
            this.setFilters(initialFilters);
            if (initialFilters.length === 0) this.addGroup();
        } catch {
            this.invalidInitialState = true;
            this.error.textContent = t('Could not restore the initial filters.');
        }
    }

    private addGroup(initial?: Filter): void {
        const root = element('div', 'min-w-0 rounded-xl border border-gray-200');
        root.dataset.filterGroup = '';
        root.setAttribute('role', 'group');
        const toolbar = element('div', 'filter-group-toolbar flex items-stretch rounded-t-xl border-b border-gray-200');
        const actions = element('div', 'flex items-stretch');
        const connector = element('select', 'h-8 w-20 rounded-none rounded-tl-xl border-0 border-r border-gray-200 bg-transparent py-0 pl-3 pr-7 text-xs font-medium focus:ring-1 focus:ring-inset focus:ring-primary');
        connector.setAttribute('aria-label', t('Match conditions'));
        connector.append(new Option(t('AND'), 'AND'), new Option(t('OR'), 'OR'));
        connector.value = initial?.connector ?? 'AND';
        const rows = element('div');
        const toggle = this.iconButton(t('Collapse group'), 'fa-chevron-up', () => this.setGroupExpanded(group, rows.hidden));
        toggle.classList.remove('border-r');
        toggle.classList.add('border-l', 'rounded-tr-xl');
        toggle.setAttribute('aria-expanded', 'true');
        const group: GroupEditor = { root, content: rows, toggle, connector, rows: [] };
        const add = (condition?: FilterCondition): void => {
            const editor = new ConditionEditor(this.api, () => {
                editor.destroy();
                group.rows.splice(group.rows.indexOf(editor), 1);
            });
            group.rows.push(editor);
            rows.append(editor.element);
            void editor.initialize(condition);
        };
        actions.append(this.iconButton(t('Add condition'), 'fa-plus', () => { this.setGroupExpanded(group, true); add(); }), this.iconButton(t('Remove group'), 'fa-trash', () => {
            group.rows.forEach(row => row.destroy());
            this.groups.splice(this.groups.indexOf(group), 1);
            root.remove();
            this.updateGroupLabels();
        }));
        const spacer = element('span', 'flex-1');
        toolbar.append(connector, spacer, actions, toggle);
        root.append(toolbar, rows);
        this.groups.push(group);
        this.body.append(root);
        if (initial) initial.conditions.forEach(add); else add();
        this.updateGroupLabels();
    }

    private iconButton(label: string, icon: string, action: () => void): HTMLButtonElement {
        const control = button('', action, 'inline-flex h-8 w-8 shrink-0 items-center justify-center border-0 border-l border-gray-200 bg-transparent text-xs hover:bg-base focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary focus-visible:-outline-offset-2');
        control.setAttribute('aria-label', label);
        control.title = label;
        const glyph = element('i', `fa-solid ${icon}`);
        glyph.setAttribute('aria-hidden', 'true');
        control.append(glyph);
        return control;
    }

    private setGroupExpanded(group: GroupEditor, expanded: boolean): void {
        group.content.hidden = !expanded;
        group.root.dataset.collapsed = String(!expanded);
        group.toggle.setAttribute('aria-expanded', String(expanded));
        const label = expanded ? t('Collapse group') : t('Expand group');
        group.toggle.setAttribute('aria-label', label);
        group.toggle.title = label;
        group.toggle.querySelector('i')!.className = `fa-solid ${expanded ? 'fa-chevron-up' : 'fa-chevron-down'}`;
    }

    private updateGroupLabels(): void {
        this.body.querySelectorAll('[data-group-join]').forEach(label => label.remove());
        this.groups.forEach((group, index) => {
            group.root.setAttribute('aria-label', t('Condition group'));
            if (index > 0) {
                const join = element('div', 'text-xs font-medium px-3', t('AND'));
                join.dataset.groupJoin = '';
                group.root.before(join);
            }
        });
    }

    public getFilters(): Filter[] {
        if (this.invalidInitialState) throw new Error(t('Could not restore the initial filters. Clear them to start again.'));
        return this.groups.map(group => ({
            connector: group.connector.value as 'AND' | 'OR',
            conditions: group.rows.map(row => row.getCondition()),
        }));
    }

    public setFilters(filters: Filter[]): void {
        this.invalidInitialState = false;
        this.groups.forEach(group => group.rows.forEach(row => row.destroy()));
        this.groups = [];
        this.body.replaceChildren();
        this.error.textContent = '';
        filters.forEach(group => this.addGroup(group));
        this.output.value = JSON.stringify(filters);
    }

    private apply(): void {
        try {
            const filters = this.getFilters();
            this.output.value = JSON.stringify(filters);
            this.error.textContent = '';
            this.element?.dispatchEvent(new CustomEvent(FilterContainer.applyEvent, {
                bubbles: true, detail: { filters, scope: this.getDataAttribute('scope'), id: this.getDataAttribute('scopeId') },
            }));
        } catch (error) { this.error.textContent = (error as Error).message; }
    }

    destroy(): void {
        this.api?.destroy();
        this.groups.forEach(group => group.rows.forEach(row => row.destroy()));
        this.groups = [];
        this.initialized = false;
    }
}
